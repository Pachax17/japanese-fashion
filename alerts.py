"""Saved-search email alerts — 'the bot'. [PO request 2026-08-06]

A user (for now: Paul) saves a search ("Pants · Undercover · size M · under
100 EUR") with an email. After every catalog refresh, this job emails the NEW
matching listings. GDPR by design:
  - double opt-in (a search only becomes active once its confirmation link is
    clicked — consent is provable);
  - data minimization: email + criteria, nothing else, hosted on Neon
    (eu-central-1, Frankfurt — EU soil);
  - one-click unsubscribe link in EVERY email -> immediate row deletion;
  - retention: unconfirmed signups are purged after 7 days.

Env-gated: needs DATABASE_URL + SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD
/MAIL_FROM (any missing -> silent no-op). Never fails the pipeline.

Run: python alerts.py   (CI: after history.py, so lifecycle first_seen_at is fresh)
"""

import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).parent
SEED = HERE / "data" / "listings_matched.json"

load_dotenv(HERE / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT") or 587)
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
MAIL_FROM = os.getenv("MAIL_FROM")
SITE_URL = (os.getenv("SITE_URL") or "https://mekke.co").rstrip("/")

MAX_ITEMS_PER_EMAIL = 10

ALERTS_DDL = """CREATE TABLE IF NOT EXISTS alerts (
    id              BIGSERIAL PRIMARY KEY,
    email           TEXT NOT NULL,
    brand           TEXT NULL,
    category        TEXT NULL,
    size_norm       TEXT NULL,
    price_max_eur   DOUBLE PRECISION NULL,
    token           TEXT UNIQUE NOT NULL,
    confirmed_at    TIMESTAMPTZ NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_notified_at TIMESTAMPTZ NULL
)"""


def smtp_ready() -> bool:
    return all((SMTP_HOST, SMTP_USER, SMTP_PASSWORD, MAIL_FROM))


def send_email(to_addr: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)


def criteria_match(alert: dict, listing: dict) -> bool:
    """Pure matching logic (unit-tested in tests/test_alerts.py)."""
    if listing.get("brand") in (None, "needs_review"):
        return False
    if alert.get("brand") and listing.get("brand") != alert["brand"]:
        return False
    if alert.get("category") and listing.get("category_norm") != alert["category"]:
        return False
    if alert.get("size_norm") and listing.get("size_norm") != alert["size_norm"]:
        return False
    pmax = alert.get("price_max_eur")
    if pmax is not None:
        price = listing.get("price_eur")
        if price is None or price > pmax:
            return False
    return True


def describe(alert: dict) -> str:
    parts = [alert.get("brand") or "any brand",
             alert.get("category") or "any category",
             ("size " + alert["size_norm"]) if alert.get("size_norm") else "any size"]
    if alert.get("price_max_eur") is not None:
        parts.append("under %d EUR" % int(alert["price_max_eur"]))
    return " · ".join(parts)


def digest_body(alert: dict, items: list[dict]) -> str:
    lines = ["Fresh matches for your Mekke alert (%s):" % describe(alert), ""]
    for x in items[:MAX_ITEMS_PER_EMAIL]:
        price = "%.0f EUR" % x["price_eur"] if x.get("price_eur") else "price n/a"
        lines.append("- %s | %s | %s" % (
            (x.get("title_en") or x.get("title_ja") or "")[:70],
            price,
            SITE_URL + "/item/" + str(x.get("id")),
        ))
    if len(items) > MAX_ITEMS_PER_EMAIL:
        lines.append("...and %d more on the site." % (len(items) - MAX_ITEMS_PER_EMAIL))
    lines += ["",
              "--",
              "You get this because you confirmed this alert on Mekke.",
              "Unsubscribe (deletes your data immediately): "
              + SITE_URL + "/alerts/unsubscribe/" + alert["token"]]
    return "\n".join(lines)


def main() -> None:
    if not DATABASE_URL or not smtp_ready():
        print("[alerts] DATABASE_URL/SMTP not fully configured — skipping (no-op).")
        return
    import psycopg
    from psycopg.rows import dict_row

    seed = json.loads(SEED.read_text(encoding="utf-8")).get("listings", [])
    by_sid = {x["source_item_id"]: x for x in seed if x.get("source_item_id")}

    sent = matched_total = 0
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        conn.execute(ALERTS_DDL)
        # GDPR retention: unconfirmed signups don't outlive 7 days.
        purged = conn.execute(
            "DELETE FROM alerts WHERE confirmed_at IS NULL "
            "AND created_at < now() - interval '7 days'").rowcount
        first_seen = {
            r["source_item_id"]: r["first_seen_at"]
            for r in conn.execute(
                "SELECT source_item_id, first_seen_at FROM listing_lifecycle "
                "WHERE gone_at IS NULL")
        }
        alerts = conn.execute(
            "SELECT * FROM alerts WHERE confirmed_at IS NOT NULL").fetchall()
        now = datetime.now(timezone.utc)
        for alert in alerts:
            since = alert["last_notified_at"] or alert["confirmed_at"]
            fresh = [
                x for sid, x in by_sid.items()
                if sid in first_seen and first_seen[sid] > since
                and criteria_match(alert, x)
            ]
            if not fresh:
                continue
            fresh.sort(key=lambda x: x.get("listed_at") or "", reverse=True)
            try:
                send_email(alert["email"],
                           "Mekke — %d new match(es): %s" % (len(fresh), describe(alert)),
                           digest_body(alert, fresh))
                conn.execute("UPDATE alerts SET last_notified_at=%s WHERE id=%s",
                             (now, alert["id"]))
                sent += 1
                matched_total += len(fresh)
            except Exception as e:  # noqa: BLE001 — one bad mailbox must not kill the rest
                print("[alerts] send failed for alert %s: %s" % (alert["id"], e))
        conn.commit()
    print(f"[alerts] {len(alerts)} active alert(s) | {sent} email(s) sent "
          f"({matched_total} listings) | {purged} stale unconfirmed purged")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001 — alerts must NEVER break the pipeline
        print(f"[alerts] WARNING: job failed ({e}) — pipeline continues.")
        sys.exit(0)
