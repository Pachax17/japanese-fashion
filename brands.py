"""Brand config LOADER — the data now lives in brands.yaml. [AUDIT B1]

Public interface (unchanged, so scrape.py / match.py need no edits):
  BRANDS          : {key: {display, search_keywords, exclude}}
  MATCH           : {key: {strong, weak, negative}}
  MATCH_PRIORITY  : [key, ...] — most specific first

New:
  MERCARI_BRAND_NAMES : {key: [structured item_brand.name aliases]}
  MERCARI_BRAND_IDS   : {key: [Mercari numeric brand ids]}
  FOREIGN_BRANDS      : [tokens] — niche brands we do NOT carry; their presence
                        in a title demotes WEAK matches to needs_review

Adding a brand = adding one YAML block (and its key to `priority`). The loader
validates the file at import time and fails LOUDLY on a malformed config —
better a crashed pipeline than a silently mis-tagged catalog.
"""

from pathlib import Path

import yaml

_PATH = Path(__file__).parent / "brands.yaml"


def _load() -> dict:
    data = yaml.safe_load(_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "brands" not in data or "priority" not in data:
        raise ValueError("brands.yaml: must define top-level 'brands' and 'priority'")

    brands = data["brands"]
    priority = data["priority"]

    if sorted(brands) != sorted(priority):
        missing = set(brands) ^ set(priority)
        raise ValueError(f"brands.yaml: 'priority' must list every brand exactly once (mismatch: {missing})")

    for key, b in brands.items():
        for field in ("display", "search_keywords", "match"):
            if not b.get(field):
                raise ValueError(f"brands.yaml: brand '{key}' is missing '{field}'")
        if not b["match"].get("strong"):
            raise ValueError(f"brands.yaml: brand '{key}' needs at least one 'strong' match token")
        for bucket in ("strong", "weak", "negative"):
            b["match"].setdefault(bucket, [])
        b.setdefault("exclude", [])
        b.setdefault("mercari_brand_names", [])
        b.setdefault("mercari_brand_ids", [])
    return data


_DATA = _load()

BRANDS = {
    key: {
        "display": b["display"],
        "search_keywords": list(b["search_keywords"]),
        "exclude": list(b["exclude"]),
    }
    for key, b in _DATA["brands"].items()
}

MATCH = {key: dict(b["match"]) for key, b in _DATA["brands"].items()}

MATCH_PRIORITY = list(_DATA["priority"])

MERCARI_BRAND_NAMES = {key: list(b["mercari_brand_names"]) for key, b in _DATA["brands"].items()}

MERCARI_BRAND_IDS = {key: list(b["mercari_brand_ids"]) for key, b in _DATA["brands"].items()}

FOREIGN_BRANDS = list(_DATA.get("foreign_brands") or [])
