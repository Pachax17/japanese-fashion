"""Persist the catalog's history to Postgres (Neon). [AUDIT A2]

WHY: Render's free-tier disk is wiped on every deploy (i.e. every catalog
refresh), so SQLite clicks died 4x/day and sold items vanished without a
trace. This module is the project's MEASURING INSTRUMENT — it turns the
pipeline's snapshots into durable business data:

  listing_snapshots : one row per (run, listing) — raw price/status history
  listing_lifecycle : one row per listing — first_seen / last_seen / gone_at
                      (gone_at = disappeared from the feed: sold-or-removed
                      proxy -> sale-velocity dataset, per brand/size/price)
  clicks            : outbound clicks from the site (written by app.py)

Env-gated: without DATABASE_URL this is a silent no-op (exit 0), so local
runs and forks work unchanged. In CI it runs after translate.py.

Run: python history.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
SEED = HERE / "data" / "listings_matched.json"

load_dotenv(HERE / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")

DDL = [
    """CREATE TABLE IF NOT EXISTS listing_snapshots (
        run_at          TIMESTAMPTZ NOT NULL,
        source_item_id  TEXT NOT NULL,
        brand           TEXT,
        status          TEXT,
        price_jpy       INTEGER,
        price_eur       DOUBLE PRECISION,
        listed_at       TEXT,
        mercari_brand_name TEXT,
        size_norm       TEXT,
        condition_norm  TEXT,
        PRIMARY KEY (run_at, source_item_id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_snap_item ON listing_snapshots(source_item_id)",
    """CREATE TABLE IF NOT EXISTS listing_lifecycle (
        source_item_id  TEXT PRIMARY KEY,
        brand           TEXT,
        title_en        TEXT,
        listed_at       TEXT,
        status_last     TEXT,
        price_jpy_last  INTEGER,
        first_seen_at   TIMESTAMPTZ,
        last_seen_at    TIMESTAMPTZ,
        gone_at         TIMESTAMPTZ NULL
    )""",
    """CREATE TABLE IF NOT EXISTS clicks (
        id          BIGSERIAL PRIMARY KEY,
        listing_id  TEXT,
        brand       TEXT,
        dest        TEXT,
        ts          TIMESTAMPTZ DEFAULT now()
    )""",
]


def main() -> None:
    if not DATABASE_URL:
        print("[history] DATABASE_URL not set — skipping (no-op).")
        return
    import psycopg  # imported lazily: only needed when the gate is open

    payload = json.loads(SEED.read_text(encoding="utf-8"))
    listings = payload.get("listings", [])
    now = datetime.now(timezone.utc)

    snap_rows = [
        (
            now, x.get("source_item_id"), x.get("brand"), x.get("status"),
            x.get("price_jpy"), x.get("price_eur"), x.get("listed_at"),
            x.get("mercari_brand_name"), x.get("size_norm"), x.get("condition_norm"),
        )
        for x in listings if x.get("source_item_id")
    ]
    life_rows = [
        (
            x.get("source_item_id"), x.get("brand"), x.get("title_en"),
            x.get("listed_at"), x.get("status"), x.get("price_jpy"), now, now,
        )
        for x in listings if x.get("source_item_id")
    ]

    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for stmt in DDL:
                cur.execute(stmt)
            cur.executemany(
                """INSERT INTO listing_snapshots
                   (run_at, source_item_id, brand, status, price_jpy, price_eur,
                    listed_at, mercari_brand_name, size_norm, condition_norm)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                snap_rows,
            )
            cur.executemany(
                """INSERT INTO listing_lifecycle
                   (source_item_id, brand, title_en, listed_at, status_last,
                    price_jpy_last, first_seen_at, last_seen_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (source_item_id) DO UPDATE SET
                     brand=EXCLUDED.brand, title_en=EXCLUDED.title_en,
                     status_last=EXCLUDED.status_last,
                     price_jpy_last=EXCLUDED.price_jpy_last,
                     last_seen_at=EXCLUDED.last_seen_at,
                     gone_at=NULL""",
                life_rows,
            )
            # Anything alive before this run but absent from it = sold-or-removed.
            cur.execute(
                "UPDATE listing_lifecycle SET gone_at=%s "
                "WHERE gone_at IS NULL AND last_seen_at < %s",
                (now, now),
            )
            gone = cur.rowcount
            cur.execute("SELECT count(*) FROM listing_snapshots")
            n_snap = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM listing_lifecycle WHERE gone_at IS NULL")
            alive = cur.fetchone()[0]
        conn.commit()

    print(f"[history] snapshot: {len(snap_rows)} listings @ {now.isoformat()}")
    print(f"[history] lifecycle: {alive} alive | {gone} newly gone (sold/removed proxy)")
    print(f"[history] total snapshot rows in Neon: {n_snap}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        # History must NEVER break the catalog pipeline: log loudly, exit 0.
        print(f"[history] WARNING: persistence failed ({e}) — pipeline continues.")
        sys.exit(0)
