"""Brand keyword config — mirrors the vault Brand Dictionary.

`search_keywords[0]` is what the scraper searches on Mercari. MATCH (below) is the
brand classifier: positive (strong/weak) + negative keywords, checked in priority
order against a normalized title (NFKC, lowercased, spaces/punctuation removed).
"""

BRANDS = {
    # --- CdG / Junya (menswear lines) ---
    "junya_watanabe": {
        "display": "Junya Watanabe MAN",
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

    # --- Ura-Harajuku / archive ---
    "undercover": {
        "display": "Undercover",
        "search_keywords": ["アンダーカバー", "UNDERCOVER"],
        "exclude": [],
    },
    "number_nine": {
        "display": "Number (Nine)",
        "search_keywords": ["ナンバーナイン", "NUMBER NINE"],
        "exclude": ["ソロイスト", "TheSoloist"],
    },

    # --- Y2K Japanese ---
    "lgb": {
        "display": "LGB (Le Grand Bleu)",
        "search_keywords": ["ルグランブルー", "Le Grand Bleu"],
        "exclude": [],
    },
    "tornado_mart": {
        "display": "Tornado Mart",
        "search_keywords": ["トルネードマート", "TORNADO MART"],
        "exclude": [],
    },

    # --- Issey Miyake (womenswear line) ---
    "pleats_please": {
        "display": "Pleats Please Issey Miyake",
        "search_keywords": ["プリーツプリーズ", "PLEATS PLEASE"],
        "exclude": ["オムプリッセ", "HOMME PLISSE"],  # exclude the MEN's pleats line
    },
}

# --- Brand-matching config -------------------------------------------------
# Checked in PRIORITY ORDER (most specific first). Tokens matched against a
# normalized title (NFKC, lowercased, spaces/punctuation removed) — store readably.
#   strong  -> full/unambiguous brand name  => high confidence
#   weak    -> slang/partial                => low confidence
#   negative-> if present, this brand is disqualified
MATCH_PRIORITY = [
    "junya_watanabe", "cdg_homme_plus", "cdg_homme",
    "undercover", "number_nine", "lgb", "tornado_mart", "pleats_please",
]

MATCH = {
    "junya_watanabe": {
        "strong": ["ジュンヤワタナベマン", "JUNYA WATANABE MAN", "JUNYA WATANABE", "ジュンヤワタナベ",
                   "JYUNYA WATANABE"],  # common romaji misspelling seen in real data
        "weak": ["ジュンヤ", "JUNYA", "JYUNYA"],
        "negative": [],
    },
    "cdg_homme_plus": {
        "strong": ["コムデギャルソンオムプリュス", "COMME des GARCONS HOMME PLUS", "HOMME PLUS", "オムプリュス",
                   "HOMME PULUS"],  # 'PULUS' = common romaji misspelling of PLUS (real data)
        "weak": ["オムプラス", "HOMME+"],
        "negative": ["ジュンヤ", "JUNYA", "オムドゥ", "HOMME DEUX"],
    },
    "cdg_homme": {
        "strong": ["コムデギャルソンオム", "COMME des GARCONS HOMME"],
        "weak": ["ギャルソンオム"],
        "negative": ["オムプリュス", "HOMME PLUS", "HOMME PULUS", "オムドゥ", "HOMME DEUX", "ジュンヤ", "JUNYA"],
    },
    "undercover": {
        # 'undercover' substring also catches UNDERCOVERISM etc.
        "strong": ["アンダーカバー", "UNDERCOVER"],
        "weak": ["アンカバ"],
        "negative": [],
    },
    "number_nine": {
        # "NUMBER NINE" / "NUMBER (N)INE" both normalize to 'numbernine'.
        "strong": ["ナンバーナイン", "NUMBER NINE"],
        "weak": ["ナンバナイン"],
        "negative": ["ソロイスト", "THE SOLOIST", "TAKAHIROMIYASHITA"],  # his later label
    },
    "lgb": {
        # NOT using bare "LGB" (would match 'lgbt' etc.); rely on the full name.
        "strong": ["ルグランブルー", "Le Grand Bleu"],
        "weak": ["エルジービー"],
        "negative": [],
    },
    "tornado_mart": {
        "strong": ["トルネードマート", "TORNADO MART"],
        "weak": [],  # bare 'トルネード'/'tornado' too generic
        "negative": [],
    },
    "pleats_please": {
        "strong": ["プリーツプリーズ", "PLEATS PLEASE"],
        "weak": [],
        "negative": ["オムプリッセ", "HOMME PLISSE", "プリッセ"],  # exclude men's Homme Plissé
    },
}
