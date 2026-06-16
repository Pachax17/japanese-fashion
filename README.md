# Japanese Fashion (C)

> Claude-assisted MVP. Aggregates archive Japanese designer listings from **Mercari**
> into a clean, minimalist Western browse experience, and redirects buyers to **Buyee**
> (affiliate). Planning docs live in the Obsidian vault (`03 Projects/Japanese Fashion/`).

## What this is (and isn't)
- We **scrape Mercari directly** (Buyee 403s bots). The Buyee URL is *derived* from the Mercari item id.
- Buyers never buy through us — we redirect them to Buyee.

## MVP brands (menswear-only)
- Comme des Garçons Homme
- Comme des Garçons Homme Plus
- Junya Watanabe **MAN**

## Build slices
1. **scraper** ← *we are here* — `scrape.py`: Junya Watanabe MAN → `data/junya_man.json`
2. parser + normalize  3. translator (DeepL + glossary)  4. brand matcher
5. storage (SQLite)  6. grid page  7. `/go/{id}` redirect

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Secrets
- Copy `.env.example` → `.env` and paste your real `DEEPL_API_KEY`.
- **Never commit `.env`** (it's git-ignored) and **never paste your key in chat**.
- The scraper (slice #1) does **not** need the key — only the translator (slice #3) does.

## Run the scraper
```bash
python scrape.py
# -> writes data/junya_man.json
```

## Notes
- `mercapi` is a reverse-engineered Mercari API; field names can vary by version — `scrape.py` reads them defensively.
- Be polite: the scraper paces detail requests (`REQUEST_DELAY_S`) and only enriches the first `MAX_FULL_DETAILS` items.
