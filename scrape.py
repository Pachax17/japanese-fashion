"""Scrape Junya Watanabe MAN listings from Mercari and save to data/junya_man.json.

Why Mercari and not Buyee:
  Buyee returns HTTP 403 to bots. The listing data actually lives on Mercari
  (Buyee is just a buying proxy). So we scrape Mercari directly and DERIVE the
  Buyee URL from the Mercari item id (m + 11 digits).

Scope of this slice: search -> collect listings -> save raw JSON.
No translation, no brand-matching, no DB yet (those are later slices).

Run:
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  python scrape.py
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from mercapi import Mercapi

from brands import BRANDS

DATA_DIR = Path(__file__).parent / "data"
BUYEE_ITEM_URL = "https://buyee.jp/mercari/item/{item_id}?conversionType=Mercari_DirectSearch"
MERCARI_ITEM_URL = "https://jp.mercari.com/item/{item_id}"

# Politeness / scope knobs
MAX_ITEMS_PER_BRAND = 100   # hard cap on listings collected per brand (across pages)
MAX_PAGES = 10              # safety cap on pagination
REQUEST_DELAY_S = 0.6       # pause between detail requests — be a good citizen


def _getattr_any(obj, *names, default=None):
    """Return the first attribute that exists (mercapi field names vary by version)."""
    for n in names:
        val = getattr(obj, n, None)
        if val is not None:
            return val
    return default


async def _build_record(item, brand_key: str) -> dict:
    """Build one listing record, enriched with full details (condition / category / photos)."""
    item_id = _getattr_any(item, "id_", "id")
    created = _getattr_any(item, "created")  # datetime — when the item was first listed
    record = {
        "source": "mercari",
        "source_item_id": item_id,
        "brand_guess": brand_key,            # provisional — real matching is a later slice
        "title_ja": _getattr_any(item, "name"),
        "price_jpy": _getattr_any(item, "price"),
        "status": _getattr_any(item, "status"),
        "listed_at": created.isoformat() if created else None,  # for "sort by new"
        "mercari_url": MERCARI_ITEM_URL.format(item_id=item_id) if item_id else None,
        "buyee_item_url": BUYEE_ITEM_URL.format(item_id=item_id) if item_id else None,
        "condition_raw": None,
        "category_raw": None,        # used by the parser to filter out footwear
        "size_raw": None,            # Mercari has NO structured size -> parsed from text in slice #2
        "description_ja": None,
        "photos": list(_getattr_any(item, "thumbnails", default=[]) or []),
    }
    if item_id:
        try:
            full = await item.full_item()
            cond = _getattr_any(full, "item_condition")
            record["condition_raw"] = _getattr_any(cond, "name") if cond else None
            cat = _getattr_any(full, "item_category")
            record["category_raw"] = _getattr_any(cat, "name") if cat else None
            record["description_ja"] = _getattr_any(full, "description")
            photos = _getattr_any(full, "photos", default=[]) or []
            if photos:
                record["photos"] = list(photos)
            await asyncio.sleep(REQUEST_DELAY_S)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] full_item failed for {item_id}: {e}")
    return record


async def scrape_brand(m: Mercapi, brand_key: str) -> list[dict]:
    brand = BRANDS[brand_key]
    keyword = brand["search_keywords"][0]
    print(f"[search] {brand['display']} -> '{keyword}' (cap {MAX_ITEMS_PER_BRAND} items / {MAX_PAGES} pages)")

    results = await m.search(keyword)
    listings: list[dict] = []
    page = 1
    while results is not None:
        items = getattr(results, "items", []) or []
        print(f"  [page {page}] {len(items)} items (total so far: {len(listings)})")
        for item in items:
            if len(listings) >= MAX_ITEMS_PER_BRAND:
                break
            listings.append(await _build_record(item, brand_key))

        meta = getattr(results, "meta", None)
        if (len(listings) >= MAX_ITEMS_PER_BRAND
                or page >= MAX_PAGES
                or not meta
                or not getattr(meta, "next_page_token", None)):
            break
        results = await results.next_page()
        page += 1

    print(f"[search] collected {len(listings)} listings across {page} page(s)")
    return listings


async def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    m = Mercapi()

    # Scrape every configured brand, deduping across searches (an item can show up
    # under more than one keyword — e.g. Homme vs Homme Plus).
    by_id: dict[str, dict] = {}
    for brand_key in BRANDS:
        for rec in await scrape_brand(m, brand_key):
            sid = rec.get("source_item_id")
            if sid and sid not in by_id:
                by_id[sid] = rec

    listings = list(by_id.values())
    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "source": "mercari",
        "brands_searched": list(BRANDS),
        "count": len(listings),
        "listings": listings,
    }
    out_path = DATA_DIR / "listings_raw.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] wrote {len(listings)} unique listings -> {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
