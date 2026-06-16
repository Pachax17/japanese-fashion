# (C) Claude-generated — Japanese Fashion MVP, build slice #4
"""Brand matcher — assign each listing a brand + confidence (the project's moat).

Why this matters: CdG sub-lines (Homme / Homme Plus / Homme Deux) and Junya all
cross-tag each other; a naive keyword search mislabels them. We use positive +
negative keywords with a confidence score and a `needs_review` bucket so nothing
gets shown under the wrong brand.

Algorithm (see brands.MATCH / MATCH_PRIORITY):
  - normalize the title (NFKC, lowercase, strip spaces/punctuation)
  - check brands in priority order: Junya -> Homme Plus -> Homme
  - a brand's `negative` token disqualifies it
  - `strong` hit => 0.95, `weak`-only hit => 0.65
  - nothing above threshold => brand = 'needs_review' (held back, not displayed)

Input : data/junya_man_translated.json
Output: data/junya_man_matched.json
Run   : python match.py
"""

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from brands import MATCH, MATCH_PRIORITY

DATA_DIR = Path(__file__).parent / "data"
IN_PATH = DATA_DIR / "listings_translated.json"
NORM_PATH = DATA_DIR / "listings_normalized.json"  # fallback if not translated yet
OUT_PATH = DATA_DIR / "listings_matched.json"

CONFIDENCE_THRESHOLD = 0.6
STRONG_CONF = 0.95
WEAK_CONF = 0.65

_PUNCT_RE = re.compile(r"[\s　・,.\-_/×x*()\[\]【】「」『』!！?？:：;；]+")


def normalize(text: str) -> str:
    """NFKC fold (unifies full/half-width), lowercase, strip spaces/punctuation."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    return _PUNCT_RE.sub("", text)


# Pre-normalize the token lists once.
_NORM = {
    brand: {bucket: [normalize(t) for t in toks] for bucket, toks in cfg.items()}
    for brand, cfg in MATCH.items()
}


def match_brand(title_ja: str | None, title_en: str | None = None) -> tuple[str, float]:
    text = normalize(f"{title_ja or ''} {title_en or ''}")
    for brand in MATCH_PRIORITY:
        cfg = _NORM[brand]
        if any(neg and neg in text for neg in cfg["negative"]):
            continue  # disqualified
        if any(tok and tok in text for tok in cfg["strong"]):
            return brand, STRONG_CONF
        if any(tok and tok in text for tok in cfg["weak"]):
            return brand, WEAK_CONF
    return "needs_review", 0.0


def main() -> None:
    src = IN_PATH if IN_PATH.exists() else NORM_PATH
    payload = json.loads(src.read_text(encoding="utf-8"))
    listings = payload.get("listings", [])

    dist: Counter[str] = Counter()
    review_examples = []
    for x in listings:
        brand, conf = match_brand(x.get("title_ja"), x.get("title_en"))
        if conf < CONFIDENCE_THRESHOLD:
            brand = "needs_review"
        x["brand"] = brand
        x["brand_confidence"] = conf
        dist[brand] += 1
        if brand == "needs_review" and len(review_examples) < 8:
            review_examples.append(x.get("title_ja"))

    payload["matched_at"] = datetime.now(timezone.utc).isoformat()
    payload["brand_distribution"] = dict(dist)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[match] {len(listings)} listings (from {src.name})")
    for brand, n in dist.most_common():
        print(f"  {brand:16} {n}")
    if review_examples:
        print("[match] sample needs_review titles:")
        for t in review_examples:
            print(f"   - {t}")
    print(f"[done] wrote -> {OUT_PATH}")


if __name__ == "__main__":
    main()
