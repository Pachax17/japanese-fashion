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

Pipeline order [AUDIT B]: match runs BEFORE translate — classification only
needs title_ja tokens + the structured Mercari tag, so junk gets quarantined
before it can burn DeepL quota (~30% of scraped volume).

Input : data/listings_normalized.json
Output: data/listings_classified.json
Run   : python match.py
"""

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from brands import MATCH, MATCH_PRIORITY, MERCARI_BRAND_NAMES

DATA_DIR = Path(__file__).parent / "data"
IN_PATH = DATA_DIR / "listings_normalized.json"
OUT_PATH = DATA_DIR / "listings_classified.json"

CONFIDENCE_THRESHOLD = 0.6
TAG_CONF = 0.98      # seller-picked structured Mercari brand tag (item_brand.name)
STRONG_CONF = 0.95
WEAK_CONF = 0.65

_PUNCT_RE = re.compile(r"[\s　・,.\-_/×x*()\[\]【】「」『』!！?？:：;；]+")


def normalize(text: str) -> str:
    """NFKC fold (unifies full/half-width), lowercase, strip spaces/punctuation."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    return _PUNCT_RE.sub("", text)


def normalize_spaced(text: str) -> str:
    """Like normalize(), but punctuation becomes a SPACE — keeps word boundaries
    so `re:`-tokens can match bare acronyms (e.g. \\blgb\\b) without catching
    substrings ('lgbt')."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", _PUNCT_RE.sub(" ", text)).strip()


def _compile(tokens: list[str]) -> tuple[list[str], list[re.Pattern]]:
    """Split a token list into (substring tokens, compiled `re:` regex tokens)."""
    subs, regs = [], []
    for t in tokens:
        if isinstance(t, str) and t.startswith("re:"):
            regs.append(re.compile(t[3:]))
        else:
            s = normalize(t)
            if s:
                subs.append(s)
    return subs, regs


# Pre-compile the token lists once.
_NORM = {
    brand: {bucket: _compile(toks) for bucket, toks in cfg.items()}
    for brand, cfg in MATCH.items()
}

# Structured Mercari brand tag -> our brand key (normalized alias lookup).
_TAG_LOOKUP = {
    normalize(name): brand
    for brand, names in MERCARI_BRAND_NAMES.items()
    for name in names
    if normalize(name)
}


def _hit(bucket: tuple[list[str], list[re.Pattern]], text: str, spaced: str) -> bool:
    subs, regs = bucket
    return any(s in text for s in subs) or any(r.search(spaced) for r in regs)


def match_brand(
    title_ja: str | None,
    title_en: str | None = None,
    mercari_brand_name: str | None = None,
) -> tuple[str, float]:
    # 1. Seller-picked structured brand tag — POSITIVE CONFIRMATION ONLY.
    #    (Verified on real data 2026-08-04: 14/14 sampled items carried an
    #    accurate item_brand. Unknown/foreign tags are ignored, never a veto,
    #    until alias coverage is harvested from full runs — no regressions.)
    if mercari_brand_name:
        tagged = _TAG_LOOKUP.get(normalize(mercari_brand_name))
        if tagged:
            return tagged, TAG_CONF

    # 2. Title tokens (the historical moat) — TWO PASSES: a strong hit on ANY
    #    brand beats a weak hit on an earlier-priority brand. (Caught by the
    #    golden suite: "TORNADO MART ... LGB ..." must be tornado_mart-strong,
    #    not lgb-weak, even though lgb comes first in priority.)
    joined = f"{title_ja or ''} {title_en or ''}"
    text = normalize(joined)
    spaced = normalize_spaced(joined)
    for brand in MATCH_PRIORITY:
        cfg = _NORM[brand]
        if not _hit(cfg["negative"], text, spaced) and _hit(cfg["strong"], text, spaced):
            return brand, STRONG_CONF
    for brand in MATCH_PRIORITY:
        cfg = _NORM[brand]
        if not _hit(cfg["negative"], text, spaced) and _hit(cfg["weak"], text, spaced):
            return brand, WEAK_CONF
    return "needs_review", 0.0


def main() -> None:
    src = IN_PATH
    payload = json.loads(src.read_text(encoding="utf-8"))
    listings = payload.get("listings", [])

    dist: Counter[str] = Counter()
    review_examples = []
    for x in listings:
        brand, conf = match_brand(
            x.get("title_ja"), x.get("title_en"), x.get("mercari_brand_name")
        )
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
