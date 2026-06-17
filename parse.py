"""Parse + normalize raw scraped listings into the clean listing schema.

Input : data/junya_man.json        (raw, from scrape.py)
Output: data/junya_man_normalized.json

What this does:
  - drops footwear (decision 2026-06-16: no shoes for now)
  - maps Mercari's fixed condition labels -> condition_norm
  - best-effort parses a size token from the title/description (Mercari has no size field)
  - converts price JPY -> EUR (placeholder FX rate; TODO live source)
  - leaves title_en / brand matching for later slices (#3 translate, #4 match)

Run:  python parse.py
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fx import get_mercari_jpy_to_eur

DATA_DIR = Path(__file__).parent / "data"
IN_PATH = DATA_DIR / "listings_raw.json"
OUT_PATH = DATA_DIR / "listings_normalized.json"

# --- Mercari's fixed 6 condition labels -> our normalized scale -------------
CONDITION_MAP = {
    "新品、未使用": "new",
    "未使用に近い": "like_new",
    "目立った傷や汚れなし": "good",
    "やや傷や汚れあり": "fair",
    "傷や汚れあり": "fair",
    "全体的に状態が悪い": "poor",
}

# --- Clothing whitelist (decision 2026-06-16: clothing only) ----------------
#   Keep only clothing categories; this drops footwear, bags, dresses, etc.
#   Matched by substring so category-name variants still pass.
CLOTHING_MARKERS = (
    "トップス", "パンツ", "アウター", "ジャケット", "コート", "スーツ",
    "シャツ", "ニット", "セーター", "デニム", "ベスト", "パーカー",
    "スウェット", "ズボン", "短パン", "ハーフパンツ", "カーディガン",
    "スカート", "ワンピース",  # womenswear clothing (e.g. Pleats Please)
)

# --- Only regular Mercari listings (id = 'm' + 11 digits) -------------------
#   "Mercari Shops" items use 22-char IDs, fail full_item enrichment, and don't
#   map to a buyee.jp/item/mercari/m... URL -> their redirect would be dead.
#   Drop them for the MVP (revisit if we add Shops support later).
MERCARI_ID_RE = re.compile(r"^m\d{11}$")

# --- Size parsing (best effort; size lives in free text on Mercari) ---------
#   Bounded by non-alphanumerics so we don't catch the 'L' in '1906L'.
SIZE_LETTER_RE = re.compile(r"(?<![A-Za-z0-9])(XXS|XS|S|M|L|XL|XXL|XXXL)(?![A-Za-z0-9])")
SIZE_NUM_RE = re.compile(r"サイズ\s*[:：]?\s*([0-9]{1,2})")
WAIST_RE = re.compile(r"[WwＷ]\s?([0-9]{2,3})")


def is_clothing(category_raw: str | None) -> bool:
    return bool(category_raw) and any(mark in category_raw for mark in CLOTHING_MARKERS)


def parse_size(*texts: str | None) -> tuple[str | None, str | None]:
    """Return (size_raw, size_norm) best-effort from the given texts."""
    for t in texts:
        if not t:
            continue
        m = WAIST_RE.search(t)
        if m:
            return f"W{m.group(1)}", f"W{m.group(1)}"
        m = SIZE_LETTER_RE.search(t.upper())
        if m:
            return m.group(1), m.group(1)
        m = SIZE_NUM_RE.search(t)
        if m:
            return m.group(0).strip(), m.group(1)
    return None, None


def normalize(raw: dict, scraped_at: str, fx_rate: float) -> dict:
    sid = raw.get("source_item_id")
    title = raw.get("title_ja")
    desc = raw.get("description_ja")
    size_raw, size_norm = parse_size(title, desc)
    price_jpy = raw.get("price_jpy")
    cond_raw = raw.get("condition_raw")

    return {
        "id": f"mercari_{sid}" if sid else None,
        "source": "mercari",
        "source_item_id": sid,
        "mercari_url": raw.get("mercari_url"),
        "buyee_item_url": raw.get("buyee_item_url"),
        "title_ja": title,
        "title_en": None,                       # slice #3 (translation)
        "brand": raw.get("brand_guess"),        # provisional; slice #4 (matching) refines this
        "brand_confidence": None,               # slice #4
        "category_raw": raw.get("category_raw"),
        "size_raw": size_raw,
        "size_norm": size_norm,
        "condition_raw": cond_raw,
        "condition_norm": CONDITION_MAP.get(cond_raw),
        "price_jpy": price_jpy,
        "price_eur": round(price_jpy * fx_rate, 2) if isinstance(price_jpy, (int, float)) else None,
        "images": raw.get("photos") or [],
        "status": raw.get("status"),
        "scraped_at": scraped_at,
        "normalized_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    payload = json.loads(IN_PATH.read_text(encoding="utf-8"))
    raw_listings = payload.get("listings", [])
    scraped_at = payload.get("scraped_at")

    fx_rate, fx_source = get_mercari_jpy_to_eur()
    print(f"[fx] 1 JPY = {fx_rate} EUR (source: {fx_source})")

    kept, dropped_non_clothing, dropped_shops = [], 0, 0
    for raw in raw_listings:
        sid = raw.get("source_item_id") or ""
        if not MERCARI_ID_RE.match(sid):     # Mercari Shops / unknown id -> dead Buyee link
            dropped_shops += 1
            continue
        if not is_clothing(raw.get("category_raw")):   # clothing-only whitelist
            dropped_non_clothing += 1
            continue
        kept.append(normalize(raw, scraped_at, fx_rate))

    out = {
        "normalized_at": datetime.now(timezone.utc).isoformat(),
        "source": "mercari",
        "fx_jpy_eur": fx_rate,
        "fx_source": fx_source,
        "input_count": len(raw_listings),
        "dropped_shops": dropped_shops,
        "dropped_non_clothing": dropped_non_clothing,
        "count": len(kept),
        "listings": kept,
    }
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[parse] in={len(raw_listings)} | dropped shops={dropped_shops} | dropped non-clothing={dropped_non_clothing} | kept={len(kept)}")
    print(f"[done] wrote -> {OUT_PATH}")


if __name__ == "__main__":
    main()
