"""Unit tests for the alert criteria matching (alerts.criteria_match)."""

from alerts import criteria_match

LISTING = {
    "brand": "undercover", "category_norm": "Pants",
    "size_norm": "M", "price_eur": 89.5,
}


def test_exact_match():
    alert = {"brand": "undercover", "category": "Pants",
             "size_norm": "M", "price_max_eur": 100}
    assert criteria_match(alert, LISTING)


def test_any_field_is_wildcard():
    assert criteria_match({}, LISTING)
    assert criteria_match({"brand": None, "category": None,
                           "size_norm": None, "price_max_eur": None}, LISTING)


def test_brand_mismatch():
    assert not criteria_match({"brand": "kapital"}, LISTING)


def test_category_mismatch():
    assert not criteria_match({"category": "Jacket"}, LISTING)


def test_size_mismatch():
    assert not criteria_match({"size_norm": "XL"}, LISTING)


def test_price_over_budget():
    assert not criteria_match({"price_max_eur": 50}, LISTING)


def test_price_unknown_never_matches_budget():
    x = dict(LISTING, price_eur=None)
    assert not criteria_match({"price_max_eur": 100}, x)


def test_needs_review_never_alerts():
    x = dict(LISTING, brand="needs_review")
    assert not criteria_match({}, x)
