"""Golden regression tests for the brand matcher (the project's moat). [AUDIT B2]

The fixture (golden_set.json) is built from REAL data:
  - positives: strong-confidence titles from the live catalog, per brand;
  - negatives: actual junk collected by the newest-first scrape (GAP chinos,
    NIKE pants, tag-spam listings...) that must stay in `needs_review`.

Any change to brands.yaml / match.py must keep this suite green. If a change
legitimately reclassifies a golden case, update the fixture IN THE SAME commit
and say why in the commit message.

Run: python -m pytest -q tests/
"""

import json
from pathlib import Path

import pytest

from match import match_brand, CONFIDENCE_THRESHOLD

CASES = json.loads(
    (Path(__file__).parent / "golden_set.json").read_text(encoding="utf-8")
)


def classify(case: dict) -> str:
    kwargs = {}
    if case.get("mercari_brand") is not None:
        # only future-era cases carry the structured Mercari brand tag
        kwargs["mercari_brand_name"] = case["mercari_brand"]
    brand, conf = match_brand(case["title"], **kwargs)
    return brand if conf >= CONFIDENCE_THRESHOLD else "needs_review"


@pytest.mark.parametrize(
    "case", CASES, ids=[c["title"][:35].replace(" ", "_") for c in CASES]
)
def test_golden(case):
    assert classify(case) == case["expected"]
