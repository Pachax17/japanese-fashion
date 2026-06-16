# (C) Claude-generated
"""Brand keyword config — mirrors the vault Brand Dictionary v1.

MVP = menswear-only. We target each brand's MEN'S-line keyword so we get menswear
without a separate (unreliable) gender filter.
"""

BRANDS = {
    "junya_watanabe": {
        "display": "Junya Watanabe MAN",
        # Target the MAN line for menswear precision (see Brand Dictionary v1).
        "search_keywords": ["ジュンヤワタナベマン", "JUNYA WATANABE MAN"],
        "exclude": ["レディース", "ウィメンズ", "women"],
    },
    "cdg_homme_plus": {
        "display": "Comme des Garçons Homme Plus",
        "search_keywords": ["コムデギャルソンオムプリュス", "オムプリュス", "HOMME PLUS"],
        "exclude": ["オムドゥ", "HOMME DEUX", "シャツ", "SHIRT", "ジュンヤ"],
    },
    "cdg_homme": {
        "display": "Comme des Garçons Homme",
        "search_keywords": ["コムデギャルソンオム", "COMME des GARCONS HOMME"],
        "exclude": ["オムプリュス", "HOMME PLUS", "オムドゥ", "HOMME DEUX", "シャツ", "SHIRT", "ジュンヤ"],
    },
}

# --- Brand-matching config (slice #4) ---------------------------------------
# Checked in PRIORITY ORDER (most specific first). Tokens are matched against a
# normalized title (NFKC, lowercased, spaces/punctuation removed), so store them
# readably here — the matcher normalizes them the same way.
#   strong  -> full/unambiguous brand name  => high confidence
#   weak    -> slang/partial                => low confidence
#   negative-> if present, this brand is disqualified
MATCH_PRIORITY = ["junya_watanabe", "cdg_homme_plus", "cdg_homme"]

MATCH = {
    "junya_watanabe": {
        "strong": ["ジュンヤワタナベマン", "JUNYA WATANABE MAN", "JUNYA WATANABE", "ジュンヤワタナベ",
                   "JYUNYA WATANABE"],  # common romaji misspelling seen in real data
        "weak": ["ジュンヤ", "JUNYA", "JYUNYA"],
        "negative": [],
    },
    "cdg_homme_plus": {
        "strong": ["コムデギャルソンオムプリュス", "COMME des GARCONS HOMME PLUS", "HOMME PLUS", "オムプリュス"],
        "weak": ["オムプラス", "HOMME+"],
        "negative": ["ジュンヤ", "JUNYA", "オムドゥ", "HOMME DEUX"],
    },
    "cdg_homme": {
        "strong": ["コムデギャルソンオム", "COMME des GARCONS HOMME"],
        "weak": ["ギャルソンオム"],
        "negative": ["オムプリュス", "HOMME PLUS", "オムドゥ", "HOMME DEUX", "ジュンヤ", "JUNYA"],
    },
}
