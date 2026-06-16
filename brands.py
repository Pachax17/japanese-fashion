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
