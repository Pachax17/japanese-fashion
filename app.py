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

# NOTE: the legacy Cloudflare beacon was removed 2026-08-06 (dead code since
# Plausible took over — and an unpinned third-party script was a semgrep flag).

app = Flask(__name__)


# Single source of truth = brands.yaml (via the brands.py loader): a brand added
# to the catalog config appears in the UI with zero code change. [AUDIT B1]
from brands import BRANDS as _BRANDS

DISPLAY = {key: cfg["display"] for key, cfg in _BRANDS.items()}
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


# --- Persistent click log (Neon Postgres) — [AUDIT A2] -----------------------
# Render's free-tier disk is wiped on every deploy, so the SQLite clicks table
# died 4x/day. If DATABASE_URL is set, clicks ALSO go to Postgres (with the
# redirect destination, which SQLite never captured). Best-effort by design:
# a dead DB must never block a user's redirect.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
_CLICKS_DDL = ("CREATE TABLE IF NOT EXISTS clicks (id BIGSERIAL PRIMARY KEY, "
               "listing_id TEXT, brand TEXT, dest TEXT, ts TIMESTAMPTZ DEFAULT now())")
_clicks_ready = False


def _log_click_persistent(listing_id: str, brand: str | None, dest: str) -> None:
    global _clicks_ready
    if not DATABASE_URL:
        return
    try:
        import psycopg
        with psycopg.connect(DATABASE_URL, connect_timeout=3) as conn:
            if not _clicks_ready:
                conn.execute(_CLICKS_DDL)
                _clicks_ready = True
            conn.execute(
                "INSERT INTO clicks (listing_id, brand, dest) VALUES (%s, %s, %s)",
                (listing_id, brand, dest),
            )
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[clicks] persistent log failed (non-blocking): {e}")


# --- Saved-search alerts ('the bot') — [PO 2026-08-06] -----------------------
# No accounts, no passwords: email + criteria + double opt-in + one-click
# erasure. See alerts.py for the sending job and the GDPR design notes.
import re as _re          # noqa: E402
import secrets as _secrets  # noqa: E402

from alerts import (       # noqa: E402
    ALERTS_DDL, describe as _describe_alert,
    send_email as _send_email, smtp_ready as _smtp_ready,
)

SITE_URL = (os.getenv("SITE_URL") or "https://mekke.co").rstrip("/")
ALERTS_ENABLED = bool(DATABASE_URL) and _smtp_ready()
MAX_ALERTS_PER_EMAIL = 5
_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TOKEN_RE = _re.compile(r"^[A-Za-z0-9_\-]{20,64}$")


def _msg(text: str, code: int = 200):
    return render_template("message.html", text=text), code


def _pg():
    import psycopg
    # 15s, not 5: Neon's serverless compute auto-suspends when idle and a cold
    # wake-up can take several seconds.
    return psycopg.connect(DATABASE_URL, connect_timeout=15)


@app.route("/alerts", methods=["POST"])
def alerts_create():
    if not ALERTS_ENABLED:
        abort(404)
    if request.form.get("website"):  # honeypot — bots fill every field
        return redirect("/")
    email = (request.form.get("email") or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return _msg("Invalid email address.", 400)
    # Strict allowlists — user input never reaches SQL text or emails raw.
    brand = request.form.get("brand") or None
    if brand is not None and brand not in DISPLAY:
        brand = None
    category = request.form.get("category") or None
    if category is not None and not _re.fullmatch(r"[A-Za-z\- ]{2,20}", category):
        category = None
    size = (request.form.get("size") or "").strip().upper() or None
    if size is not None and not _re.fullmatch(r"[A-Z0-9]{1,6}", size):
        size = None
    price_max = _to_int(request.form.get("price_max"))
    if price_max is not None and not (1 <= price_max <= 100_000):
        price_max = None
    token = _secrets.token_urlsafe(32)
    # Step 1 — store the (unconfirmed) alert.
    try:
        with _pg() as conn:
            conn.execute(ALERTS_DDL)
            n = conn.execute("SELECT count(*) FROM alerts WHERE email = %s",
                             (email,)).fetchone()[0]
            if n >= MAX_ALERTS_PER_EMAIL:
                return _msg(f"Alert limit reached ({MAX_ALERTS_PER_EMAIL} per email). "
                            "Unsubscribe from one first.", 429)
            conn.execute(
                "INSERT INTO alerts (email, brand, category, size_norm, "
                "price_max_eur, token) VALUES (%s,%s,%s,%s,%s,%s)",
                (email, brand, category, size, price_max, token))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[alerts] DB signup failed: {type(e).__name__}: {e}")
        return _msg("Couldn't save your alert — please try again later.", 500)

    # Step 2 — send the confirmation. Failing here must NOT leave an orphan row
    # the user can't confirm (and that would eat their per-email quota): roll it
    # back so a retry starts clean. Distinct message + log so the cause is obvious.
    crit = _describe_alert({"brand": brand, "category": category,
                            "size_norm": size, "price_max_eur": price_max})
    try:
        _send_email(
            email, "Confirm your Mekke alert",
            "You (or someone) asked for a Mekke alert:\n  " + crit + "\n\n"
            "Confirm it:\n  " + SITE_URL + "/alerts/confirm/" + token + "\n\n"
            "Not you? Ignore this email — unconfirmed requests are deleted "
            "after 7 days.\nPrivacy: " + SITE_URL + "/privacy")
    except Exception as e:  # noqa: BLE001
        print(f"[alerts] SMTP send failed: {type(e).__name__}: {e} "
              f"(host={os.getenv('SMTP_HOST')!r} port={os.getenv('SMTP_PORT')!r} "
              f"user={os.getenv('SMTP_USER')!r} from={os.getenv('MAIL_FROM')!r})")
        try:
            with _pg() as conn:
                conn.execute("DELETE FROM alerts WHERE token = %s", (token,))
                conn.commit()
        except Exception as e2:  # noqa: BLE001
            print(f"[alerts] rollback failed: {e2}")
        return _msg("We couldn't send the confirmation email (mail service error). "
                    "Nothing was saved — please try again later.", 502)
    return _msg("Almost done — check your inbox and click the confirmation link. "
                "(Unconfirmed requests self-delete after 7 days.)")


@app.route("/alerts/confirm/<token>")
def alerts_confirm(token):
    if not DATABASE_URL or not _TOKEN_RE.match(token):
        abort(404)
    try:
        with _pg() as conn:
            row = conn.execute(
                "UPDATE alerts SET confirmed_at = now() WHERE token = %s "
                "RETURNING id", (token,)).fetchone()
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[alerts] confirm failed: {e}")
        return _msg("Something went wrong — please try again later.", 500)
    if not row:
        return _msg("Unknown or expired link.", 404)
    return _msg("Alert confirmed ✓ — you'll get an email whenever fresh "
                "matching pieces drop. Unsubscribe anytime from any email.")


@app.route("/alerts/unsubscribe/<token>")
def alerts_unsubscribe(token):
    if not DATABASE_URL or not _TOKEN_RE.match(token):
        abort(404)
    try:
        with _pg() as conn:
            row = conn.execute("DELETE FROM alerts WHERE token = %s RETURNING id",
                               (token,)).fetchone()
            conn.commit()
    except Exception as e:  # noqa: BLE001
        print(f"[alerts] unsubscribe failed: {e}")
        return _msg("Something went wrong — please try again later.", 500)
    if not row:
        return _msg("Unknown or already-deleted link.", 404)
    return _msg("Unsubscribed — this alert and your email were deleted immediately.")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", contact=os.getenv("MAIL_FROM") or "the sender address of our emails")


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
    d["listed_date"] = ""  # human date shown on the detail page (PO request 2026-08-05)
    if d.get("listed_at"):
        try:
            d["listed_date"] = datetime.fromisoformat(
                d["listed_at"].replace("Z", "+00:00")
            ).strftime("%-d %b %Y")
        except Exception:  # noqa: BLE001
            pass
    return d


SORTS = {
    "new": "ORDER BY COALESCE(listed_at, scraped_at) DESC",   # default — freshest first
    "price_desc": "ORDER BY price_eur DESC",
    "price_asc": "ORDER BY price_eur ASC",
}


# SECURITY (semgrep 2026-08-06): SQL text below is assembled ONLY from module
# constants; every user-influenced value is bound through `?` placeholders, and
# ORDER BY comes from the SORTS allowlist. No user input ever reaches SQL text.
_BASE_WHERE = "status='active' AND brand IN (" + _PH + ")"


def query_listings(brand=None, size=None, condition=None,
                   sort="new", price_min=None, price_max=None,
                   category=None) -> list[dict]:
    where = [_BASE_WHERE]
    params: list = list(SHOWN_BRANDS)
    for clause, value in (
        ("brand = ?", brand if brand in DISPLAY else None),
        ("category_norm = ?", category),
        ("size_norm = ?", size),
        ("condition_norm = ?", condition),
        ("price_eur >= ?", price_min),
        ("price_eur <= ?", price_max),
    ):
        if value is not None:
            where.append(clause)
            params.append(value)
    order = SORTS.get(sort, SORTS["new"])  # allowlist — never raw user input
    sql = "SELECT * FROM listings WHERE " + " AND ".join(where) + " " + order
    conn = _conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_decorate(r) for r in rows]


def brand_counts() -> dict[str, int]:
    conn = _conn()
    counts = {b: 0 for b in DISPLAY}
    for brand, n in conn.execute(
        "SELECT brand, COUNT(*) FROM listings WHERE " + _BASE_WHERE + " GROUP BY brand",
        SHOWN_BRANDS,
    ):
        counts[brand] = n
    conn.close()
    return counts


def filter_options() -> dict[str, list[str]]:
    """Distinct sizes/conditions available among shown active listings, ordered sensibly."""
    conn = _conn()
    sizes = [r[0] for r in conn.execute(
        "SELECT DISTINCT size_norm FROM listings WHERE " + _BASE_WHERE +
        " AND size_norm IS NOT NULL", SHOWN_BRANDS)]
    conds = [r[0] for r in conn.execute(
        "SELECT DISTINCT condition_norm FROM listings WHERE " + _BASE_WHERE +
        " AND condition_norm IS NOT NULL", SHOWN_BRANDS)]
    cats = conn.execute(
        "SELECT category_norm, COUNT(*) FROM listings WHERE " + _BASE_WHERE +
        " AND category_norm IS NOT NULL GROUP BY category_norm ORDER BY COUNT(*) DESC",
        SHOWN_BRANDS).fetchall()
    conn.close()

    # Sizes grouped by garment area (PO request: tops/bottoms were all mixed).
    letters = sorted([s for s in sizes if s in SIZE_ORDER], key=SIZE_ORDER.index)
    waist = sorted([s for s in sizes if s.startswith("W")],
                   key=lambda s: int(s[1:]) if s[1:].isdigit() else 999)
    numeric = sorted([s for s in sizes if s not in SIZE_ORDER and not s.startswith("W")])
    size_groups = [g for g in (("Tops & general", letters),
                               ("Waist — bottoms", waist),
                               ("JP / EU numeric", numeric)) if g[1]]

    conds.sort(key=lambda c: CONDITION_ORDER.index(c) if c in CONDITION_ORDER else 99)
    return {
        "size_groups": size_groups,
        "categories": [(c, n) for c, n in cats],
        "conditions": [(c, CONDITION_LABEL.get(c, c)) for c in conds],
    }


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
    category = request.args.get("category") or None
    price_min = _to_int(request.args.get("price_min"))
    price_max = _to_int(request.args.get("price_max"))
    items = query_listings(brand, size, condition, sort, price_min, price_max, category)
    counts = brand_counts()
    return render_template(
        "index.html",
        items=items,
        counts=counts,
        total=sum(counts.values()),
        brands_available=sum(1 for n in counts.values() if n > 0),
        options=filter_options(),
        display=DISPLAY,
        active_brand=brand if brand in DISPLAY else None,
        active_category=category,
        active_size=size,
        active_condition=condition,
        active_sort=sort,
        price_min=price_min,
        price_max=price_max,
        waitlist_action=WAITLIST_ACTION,
        alerts_enabled=ALERTS_ENABLED,
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
    _log_click_persistent(id, row["brand"], dest)  # [AUDIT A2] survives deploys
    return redirect(url, code=302)


if __name__ == "__main__":
    # Never ship debug to prod (semgrep): opt-in via FLASK_DEBUG=1 locally only.
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=5000)
