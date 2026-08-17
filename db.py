"""Load matched listings into SQLite (the catalog the grid page will read from).

- schema = the listing schema from the vault Data Model spec
- dedupe / upsert on `id` (= mercari_<source_item_id>)
- tracks first_seen_at / last_seen_at
- maps Mercari status -> active / sold

Input: data/listings_matched.json
DB   : data/listings.db
Run  : python db.py
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from parse import normalize_category  # fallback for seeds predating category_norm

DATA_DIR = Path(__file__).parent / "data"
IN_PATH = DATA_DIR / "listings_matched.json"
DB_PATH = DATA_DIR / "listings.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id               TEXT PRIMARY KEY,
    source           TEXT,
    source_item_id   TEXT UNIQUE,
    title_ja         TEXT,
    title_en         TEXT,
    brand            TEXT,
    brand_confidence REAL,
    mercari_brand_id   INTEGER,   -- [AUDIT B] seller-picked structured brand
    mercari_brand_name TEXT,
    category_raw     TEXT,
    category_norm    TEXT,          -- garment type (T-shirt / Jacket / Pants…)
    size_raw         TEXT,
    size_norm        TEXT,
    condition_raw    TEXT,
    condition_norm   TEXT,
    price_jpy        INTEGER,
    price_eur        REAL,
    images           TEXT,          -- JSON array
    mercari_url      TEXT,
    buyee_item_url   TEXT,
    listed_at        TEXT,          -- Mercari listing date (ISO) for sort-by-new
    status           TEXT,          -- active / sold
    scraped_at       TEXT,
    first_seen_at    TEXT,
    last_seen_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_brand  ON listings(brand);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
CREATE INDEX IF NOT EXISTS idx_listings_listed ON listings(listed_at);
"""

UPSERT = """
INSERT INTO listings (
    id, source, source_item_id, title_ja, title_en, brand, brand_confidence,
    mercari_brand_id, mercari_brand_name,
    category_raw, category_norm, size_raw, size_norm, condition_raw, condition_norm,
    price_jpy, price_eur, images, mercari_url, buyee_item_url, listed_at, status,
    scraped_at, first_seen_at, last_seen_at
) VALUES (
    :id, :source, :source_item_id, :title_ja, :title_en, :brand, :brand_confidence,
    :mercari_brand_id, :mercari_brand_name,
    :category_raw, :category_norm, :size_raw, :size_norm, :condition_raw, :condition_norm,
    :price_jpy, :price_eur, :images, :mercari_url, :buyee_item_url, :listed_at, :status,
    :scraped_at, :now, :now
)
ON CONFLICT(id) DO UPDATE SET
    title_ja=excluded.title_ja, title_en=excluded.title_en,
    brand=excluded.brand, brand_confidence=excluded.brand_confidence,
    mercari_brand_id=excluded.mercari_brand_id,
    mercari_brand_name=excluded.mercari_brand_name,
    category_raw=excluded.category_raw, category_norm=excluded.category_norm,
    size_raw=excluded.size_raw,
    size_norm=excluded.size_norm, condition_raw=excluded.condition_raw,
    condition_norm=excluded.condition_norm, price_jpy=excluded.price_jpy,
    price_eur=excluded.price_eur, images=excluded.images,
    mercari_url=excluded.mercari_url, buyee_item_url=excluded.buyee_item_url,
    listed_at=excluded.listed_at,
    status=excluded.status, scraped_at=excluded.scraped_at,
    last_seen_at=excluded.last_seen_at
;
"""


def map_status(mercari_status: str | None) -> str:
    return "active" if mercari_status == "ITEM_STATUS_ON_SALE" else "sold"


def to_row(x: dict, now: str) -> dict:
    return {
        "id": x.get("id"),
        "source": x.get("source"),
        "source_item_id": x.get("source_item_id"),
        "title_ja": x.get("title_ja"),
        "title_en": x.get("title_en"),
        "brand": x.get("brand"),
        "brand_confidence": x.get("brand_confidence"),
        "mercari_brand_id": x.get("mercari_brand_id"),
        "mercari_brand_name": x.get("mercari_brand_name"),
        "category_raw": x.get("category_raw"),
        "category_norm": x.get("category_norm")
                          or normalize_category(x.get("category_raw"), x.get("title_ja")),
        "size_raw": x.get("size_raw"),
        "size_norm": x.get("size_norm"),
        "condition_raw": x.get("condition_raw"),
        "condition_norm": x.get("condition_norm"),
        "price_jpy": x.get("price_jpy"),
        "price_eur": x.get("price_eur"),
        "images": json.dumps(x.get("images") or [], ensure_ascii=False),
        "mercari_url": x.get("mercari_url"),
        "buyee_item_url": x.get("buyee_item_url"),
        "listed_at": x.get("listed_at"),
        "status": map_status(x.get("status")),
        "scraped_at": x.get("scraped_at"),
        "now": now,
    }


def main() -> None:
    payload = json.loads(IN_PATH.read_text(encoding="utf-8"))
    listings = payload.get("listings", [])

    # [AUDIT A] Defensive dedupe. A git auto-merge of the generated seed once
    # produced exact-duplicate entries; SQLite then checks the UNIQUE
    # source_item_id index BEFORE the ON CONFLICT(id) clause can absorb the
    # row, and the whole build dies. Last occurrence wins.
    unique: dict[str, dict] = {}
    for x in listings:
        key = x.get("source_item_id") or x.get("id")
        if key:
            unique[key] = x
    if len(unique) != len(listings):
        print(f"[db] WARNING: dropped {len(listings) - len(unique)} duplicate listings from seed")
    listings = list(unique.values())

    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        # Cheap migration for pre-existing local DBs (Render rebuilds fresh anyway).
        for stmt in (
            "ALTER TABLE listings ADD COLUMN mercari_brand_id INTEGER",
            "ALTER TABLE listings ADD COLUMN mercari_brand_name TEXT",
            "ALTER TABLE listings ADD COLUMN category_norm TEXT",
        ):
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.executemany(UPSERT, [to_row(x, now) for x in listings if x.get("id")])
        conn.commit()

        total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        print(f"[db] upserted {len(listings)} listings -> {DB_PATH} (total rows: {total})")
        print("[db] by brand:")
        for brand, n in conn.execute(
            "SELECT brand, COUNT(*) FROM listings GROUP BY brand ORDER BY COUNT(*) DESC"
        ):
            print(f"     {brand:16} {n}")
        print("[db] active vs sold:")
        for status, n in conn.execute("SELECT status, COUNT(*) FROM listings GROUP BY status"):
            print(f"     {status:8} {n}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
