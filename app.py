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

app = Flask(__name__)

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


def _decorate(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["images_list"] = json.loads(d.get("images") or "[]")
    d["image"] = d["images_list"][0] if d["images_list"] else None
    d["brand_display"] = DISPLAY.get(d["brand"], d["brand"])
    d["condition_label"] = CONDITION_LABEL.get(d["condition_norm"], d["condition_norm"] or "")
    return d


def query_listings(brand=None, size=None, condition=None) -> list[dict]:
    sql = f"SELECT * FROM listings WHERE status='active' AND brand IN ({_PH})"
    params = list(SHOWN_BRANDS)
    if brand in DISPLAY:
        sql += " AND brand = ?"; params.append(brand)
    if size:
        sql += " AND size_norm = ?"; params.append(size)
    if condition:
        sql += " AND condition_norm = ?"; params.append(condition)
    sql += " ORDER BY price_eur DESC"
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


@app.route("/")
def index():
    brand = request.args.get("brand") or None
    size = request.args.get("size") or None
    condition = request.args.get("condition") or None
    items = query_listings(brand, size, condition)
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
    conn = _conn()
    row = conn.execute("SELECT brand, buyee_item_url FROM listings WHERE id = ?", (id,)).fetchone()
    if not row or not row["buyee_item_url"]:
        conn.close()
        abort(404)
    conn.execute(
        "INSERT INTO clicks (listing_id, brand, ts) VALUES (?, ?, ?)",
        (id, row["brand"], datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return redirect(affiliate_url(row["buyee_item_url"], id), code=302)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
