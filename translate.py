"""Translate listing titles JA -> EN.

Strategy (from the vault Translation Test): a Mercari title is structured data +
noise, not prose. So we DON'T just throw it at MT. We:
  1. strip obvious noise tokens (送料無料, 即購入OK, 値下げ, emojis ...);
  2. pre-substitute brand names + fashion jargon to English via fashion_glossary.yaml
     (longest keys first) so DeepL can't mangle them;
  3. send the cleaned string to DeepL for the remainder -> title_en.

Input : data/junya_man_normalized.json
Output: data/junya_man_translated.json

Setup: pip install -r requirements.txt ; cp .env.example .env ; put your key in .env
Run  : python translate.py [--limit N]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import deepl
import yaml
from dotenv import load_dotenv

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
IN_PATH = DATA_DIR / "listings_normalized.json"
OUT_PATH = DATA_DIR / "listings_translated.json"
GLOSSARY_PATH = HERE / "fashion_glossary.yaml"
# The committed seed from the previous run; reused as a translation cache so the
# daily refresh only spends DeepL quota on *new* listings.
CACHE_PATH = DATA_DIR / "listings_matched.json"

load_dotenv(HERE / ".env")
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")

# Noise tokens that are not product info (we already have condition/price elsewhere).
NOISE_TOKENS = [
    "送料無料", "即購入OK", "即購入可", "即購入", "値下げ交渉", "値下げ可", "値下げ",
    "プロフ必読", "コメント不要", "お値下げ", "新品未使用", "タグ付き",
]
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF⬀-⯿←-⇿⌀-⏿]"
)


def load_glossary() -> dict[str, str]:
    data = yaml.safe_load(GLOSSARY_PATH.read_text(encoding="utf-8")) or {}
    entries: dict[str, str] = {}
    for section in ("brands", "terms"):
        entries.update(data.get(section) or {})
    # Apply longest keys first so 'コムデギャルソンオムプリュス' wins over 'コムデギャルソン'.
    return dict(sorted(entries.items(), key=lambda kv: len(kv[0]), reverse=True))


def load_translation_cache() -> dict[str, str]:
    """Map source_item_id -> title_en from the previous run's seed (incremental refresh)."""
    if not CACHE_PATH.exists():
        return {}
    try:
        prev = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {
        x["source_item_id"]: x["title_en"]
        for x in prev.get("listings", [])
        if x.get("source_item_id") and x.get("title_en")
    }


def preprocess(title: str, glossary: dict[str, str]) -> str:
    if not title:
        return ""
    text = title
    for ja, en in glossary.items():
        text = text.replace(ja, f" {en} ")
    for tok in NOISE_TOKENS:
        text = text.replace(tok, " ")
    text = EMOJI_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="translate only the first N (saves quota while testing)")
    args = ap.parse_args()

    glossary = load_glossary()
    cache = load_translation_cache()
    translator = None  # lazy init: only needed if there are new (uncached) titles

    payload = json.loads(IN_PATH.read_text(encoding="utf-8"))
    listings = payload.get("listings", [])
    todo = listings if args.limit is None else listings[: args.limit]
    print(f"[translate] {len(todo)} titles (glossary: {len(glossary)}, cached: {len(cache)})")

    ok = reused = 0
    for x in todo:
        sid = x.get("source_item_id")
        if sid in cache:                 # already translated in a previous run -> reuse
            x["title_en"] = cache[sid]
            reused += 1
            continue
        if translator is None:           # first new title -> we actually need DeepL
            if not DEEPL_API_KEY:
                sys.exit("ERROR: new listings need translation but DEEPL_API_KEY is missing. "
                         "Add it to .env (local) or repo secrets (CI).")
            translator = deepl.Translator(DEEPL_API_KEY)
        cleaned = preprocess(x.get("title_ja") or "", glossary)
        try:
            res = translator.translate_text(cleaned, source_lang="JA", target_lang="EN-US")
            x["title_en"] = res.text
            ok += 1
        except Exception as e:  # noqa: BLE001
            x["title_en"] = None
            print(f"  [warn] translate failed for {x.get('id')}: {e}")

    payload["translated_at"] = __import__("datetime").datetime.now(
        __import__("datetime").timezone.utc
    ).isoformat()
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if translator is not None:
        try:
            usage = translator.get_usage()
            print(f"[translate] new={ok} reused={reused} of {len(todo)} | "
                  f"DeepL usage: {usage.character.count}/{usage.character.limit} chars")
        except Exception as e:  # noqa: BLE001
            print(f"[translate] new={ok} reused={reused} of {len(todo)} | usage unavailable: {e}")
    else:
        print(f"[translate] new=0 reused={reused} of {len(todo)} | DeepL not called (all cached)")
    print(f"[done] wrote -> {OUT_PATH}")


if __name__ == "__main__":
    main()
