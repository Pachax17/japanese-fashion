# (C) Claude-generated — Japanese Fashion MVP, build slice #6
"""Minimal Flask grid page reading from data/listings.db.

Shows only the 3 confirmed brands (needs_review is hidden) and only `active`
listings. Cards link out to the item's Buyee page.

Run:  pip install -r requirements.txt ; python app.py  -> http://127.0.0.1:5000
"""

import json
import sqlite3
from pathlib import Path

from flask import Flask, render_template, request

DB_PATH = Path(__file__).parent / "data" / "listings.db"

app = Flask(__name__)

# Display names; this dict also defines which brands are shown (needs_review excluded).
DISPLAY = {
    "junya_watanabe": "Junya Watanabe MAN",
    "cdg_homme_plus": "Comme des Garçons Homme Plus",
    "cdg_homme": "Comme des Garçons Homme",
}
CONDITION_LABEL = {
    "new": "New", "like_new": "Like new", "good": "Good", "fair": "Fair", "poor": "Poor",
}
SHOWN_BRANDS = tuple(DISPLAY.keys())
_PLACEHOLDERS = ",".join("?" * len(SHOWN_BRANDS))


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query_listings(brand: str | None) -> list[dict]:
    sql = f"SELECT * FROM listings WHERE status='active' AND brand IN ({_PLACEHOLDERS})"
    params = list(SHOWN_BRANDS)
    if brand in DISPLAY:
        sql += " AND brand = ?"
        params.append(brand)
    sql += " ORDER BY price_eur DESC"

    conn = _conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    items = []
    for r in rows:
        d = dict(r)
        images = json.loads(d.get("images") or "[]")
        d["image"] = images[0] if images else None
        d["brand_display"] = DISPLAY.get(d["brand"], d["brand"])
        d["condition_label"] = CONDITION_LABEL.get(d["condition_norm"], d["condition_norm"] or "")
        items.append(d)
    return items


def brand_counts() -> dict[str, int]:
    conn = _conn()
    counts = {b: 0 for b in DISPLAY}
    sql = (
        f"SELECT brand, COUNT(*) FROM listings WHERE status='active' "
        f"AND brand IN ({_PLACEHOLDERS}) GROUP BY brand"
    )
    for brand, n in conn.execute(sql, SHOWN_BRANDS):
        counts[brand] = n
    conn.close()
    return counts


@app.route("/")
def index():
    brand = request.args.get("brand")
    items = query_listings(brand)
    counts = brand_counts()
    return render_template(
        "index.html",
        items=items,
        counts=counts,
        total=sum(counts.values()),
        active_brand=brand if brand in DISPLAY else None,
        display=DISPLAY,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
