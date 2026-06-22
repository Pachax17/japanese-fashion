"""Flask app: grid + detail page + Buyee redirect.

- "/"            grid, filterable by brand / size / condition (needs_review hidden, active only)
- "/item/<id>"  detail page with photo gallery
- "/go/<id>"    log the click, then 302 to the listing's Buyee page
                (wrapped as a Skimlinks affiliate deep-link when SKIMLINKS_ID is set)

Run:  pip install -r requirements.txt ; python app.py  -> http://127.0.0.1:5000
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template, request

load_dotenv(Path(__file__).parent / ".env")
DB_PATH = Path(__file__).parent / "data" / "listings.db"

# Skimlinks affiliate site id (e.g. "304859X1793048"). Unset -> raw Buyee links
# (so it stays inert until the account is approved and the env var is set).
SKIMLINKS_ID = os.getenv("SKIMLINKS_ID")

# Hosted form endpoint for the email waitlist (e.g. a Formspree URL
# "https://formspree.io/f/xxxx"). Unset -> the signup bar is hidden.
# Emails live with the form provider, NOT in the ephemeral SQLite.
WAITLIST_ACTION = os.getenv("WAITLIST_ACTION")

# Cloudflare Web Analytics token (free, privacy-friendly). Unset -> no tracking.
ANALYTICS_TOKEN = os.getenv("CF_ANALYTICS_TOKEN")

app = Flask(__name__)


@app.context_processor
def inject_globals():
    # makes {{ analytics_token }} available to every template
    return {"analytics_token": ANALYTICS_TOKEN}


DISPLAY = {
    "junya_watanabe": "Junya Watanabe MAN",
    "cdg_homme_plus": "Comme des Garçons Homme Plus",
    "cdg_homme": "Comme des Garçons Homme",
    "undercover": "Undercover",
    "number_nine": "Number (Nine)",
    "lgb": "LGB (Le Grand Bleu)",
    "tornado_mart": "Tornado Mart",
    "pleats_please": "Pleats Please Issey Miyake",
}
CONDITION_LABEL = {
    "new": "New", "like_new": "Like new", "good": "Good", "fair": "Fair", "poor": "Poor",
}
CONDITION_ORDER = ["new", "like_new", "good", "fair", "poor"]
SIZE_ORDER = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "XXXL"]
SHOWN_BRANDS = tuple(DISPLAY.keys())
_PH = ",".join("?" * len(SHOWN_BRANDS))


def affiliate_url(buyee_url: str, listing_id: str) -> str:
    """Wrap the Buyee URL as a Skimlinks deep-link (with per-listing xcust tracking).
    If SKIMLINKS_ID is unset, return the raw Buyee URL unchanged."""
    if not SKIMLINKS_ID:
        return buyee_url
    return (
        f"https://go.skimresources.com/?id={SKIMLINKS_ID}&xs=1"
        f"&url={quote(buyee_url, safe='')}&xcust={listing_id}"
    )


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS clicks "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id TEXT, brand TEXT, ts TEXT)"
    )
    return conn


def age_bucket(listed_at_iso: str | None) -> tuple[str, bool]:
    """Return (readable age, is_new) where is_new = True if <1 day old."""
    if not listed_at_iso:
        return ("unknown", False)
    try:
        from datetime import timedelta
        listed = datetime.fromisoformat(listed_at_iso.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        age = now - listed
        if age < timedelta(days=1):
            return ("< 1 day ago", True)
        elif age < timedelta(days=7):
            return ("< 1 week ago", False)
        elif age < timedelta(days=30):
            return ("< 1 month ago", False)
        elif age.days < 365:
            return ("this year", False)
        else:
            return ("older", False)
    except Exception:
        return ("unknown", False)


def _decorate(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["images_list"] = json.loads(d.get("images") or "[]")
    d["image"] = d["images_list"][0] if d["images_list"] else None
    d["brand_display"] = DISPLAY.get(d["brand"], d["brand"])
    d["condition_label"] = CONDITION_LABEL.get(d["condition_norm"], d["condition_norm"] or "")
    d["age_label"], d["is_new"] = age_bucket(d.get("listed_at"))
    return d


SORTS = {
    "new": "ORDER BY COALESCE(listed_at, scraped_at) DESC",   # default — freshest first
    "price_desc": "ORDER BY price_eur DESC",
    "price_asc": "ORDER BY price_eur ASC",
}


def query_listings(brand=None, size=None, condition=None,
                   sort="new", price_min=None, price_max=None) -> list[dict]:
    sql = f"SELECT * FROM listings WHERE status='active' AND brand IN ({_PH})"
    params = list(SHOWN_BRANDS)
    if brand in DISPLAY:
        sql += " AND brand = ?"; params.append(brand)
    if size:
        sql += " AND size_norm = ?"; params.append(size)
    if condition:
        sql += " AND condition_norm = ?"; params.append(condition)
    if price_min is not None:
        sql += " AND price_eur >= ?"; params.append(price_min)
    if price_max is not None:
        sql += " AND price_eur <= ?"; params.append(price_max)
    sql += " " + SORTS.get(sort, SORTS["new"])
    conn = _conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_decorate(r) for r in rows]


def brand_counts() -> dict[str, int]:
    conn = _conn()
    counts = {b: 0 for b in DISPLAY}
    for brand, n in conn.execute(
        f"SELECT brand, COUNT(*) FROM listings WHERE status='active' "
        f"AND brand IN ({_PH}) GROUP BY brand", SHOWN_BRANDS
    ):
        counts[brand] = n
    conn.close()
    return counts


def filter_options() -> dict[str, list[str]]:
    """Distinct sizes/conditions available among shown active listings, ordered sensibly."""
    conn = _conn()
    sizes = [r[0] for r in conn.execute(
        f"SELECT DISTINCT size_norm FROM listings WHERE status='active' "
        f"AND brand IN ({_PH}) AND size_norm IS NOT NULL", SHOWN_BRANDS)]
    conds = [r[0] for r in conn.execute(
        f"SELECT DISTINCT condition_norm FROM listings WHERE status='active' "
        f"AND brand IN ({_PH}) AND condition_norm IS NOT NULL", SHOWN_BRANDS)]
    conn.close()
    sizes.sort(key=lambda s: (SIZE_ORDER.index(s) if s in SIZE_ORDER else len(SIZE_ORDER), s))
    conds.sort(key=lambda c: CONDITION_ORDER.index(c) if c in CONDITION_ORDER else 99)
    return {"sizes": sizes, "conditions": [(c, CONDITION_LABEL.get(c, c)) for c in conds]}


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


@app.route("/")
def index():
    brand = request.args.get("brand") or None
    size = request.args.get("size") or None
    condition = request.args.get("condition") or None
    sort = request.args.get("sort") or "new"
    if sort not in SORTS:
        sort = "new"
    price_min = _to_int(request.args.get("price_min"))
    price_max = _to_int(request.args.get("price_max"))
    items = query_listings(brand, size, condition, sort, price_min, price_max)
    return render_template(
        "index.html",
        items=items,
        counts=brand_counts(),
        total=sum(brand_counts().values()),
        options=filter_options(),
        display=DISPLAY,
        active_brand=brand if brand in DISPLAY else None,
        active_size=size,
        active_condition=condition,
        active_sort=sort,
        price_min=price_min,
        price_max=price_max,
        waitlist_action=WAITLIST_ACTION,
    )


@app.route("/item/<id>")
def item(id):
    conn = _conn()
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (id,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    return render_template("detail.html", it=_decorate(row))


@app.route("/go/<id>")
def go(id):
    # Default: redirect to Mercari (user feedback — lets buyers pick their own proxy).
    # ?to=buyee keeps the proxy option (and the affiliate hook, if ever revived).
    dest = request.args.get("to", "mercari")
    conn = _conn()
    row = conn.execute(
        "SELECT brand, mercari_url, buyee_item_url FROM listings WHERE id = ?", (id,)
    ).fetchone()
    if not row:
        conn.close()
        abort(404)
    if dest == "buyee" and row["buyee_item_url"]:
        url = affiliate_url(row["buyee_item_url"], id)
    else:
        url = row["mercari_url"]
    if not url:
        conn.close()
        abort(404)
    conn.execute(
        "INSERT INTO clicks (listing_id, brand, ts) VALUES (?, ?, ?)",
        (id, row["brand"], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return redirect(url, code=302)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
