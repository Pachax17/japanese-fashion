# Archive — Japanese designer menswear, reorganised

A minimalist, Western friendly way to browse **archive Japanese designer menswear** that's
otherwise buried in Mercari Japan's dense, Japanese-only UI. Listings are scraped, translated,
classified by brand, and re-displayed as a clean Vinted/VestiaireCo style grid. You don't buy
here. When you find a piece, you're redirected to its **Buyee** page to purchase.

**Brands:** Junya Watanabe MAN · Comme des Garçons Homme / Homme Plus · Undercover · Number (Nine) · LGB (Le Grand Bleu) · Tornado Mart · Pleats Please Issey Miyake

---

## How it works

```
scrape (Mercari) → parse / normalise → translate (DeepL) → match (brand) → SQLite → web (grid + detail + redirect)
```

| Stage | File | What it does |
|---|---|---|
| Scrape | `scrape.py` | Pulls listings from **Mercari** (via `mercapi`) for each brand keyword, dedupes, enriches with condition/category/photos. |
| Normalise | `parse.py` | Maps to a clean schema; clothing-only whitelist; condition mapping; size parsed from text; JPY→EUR. |
| Translate | `translate.py` | Strips noise, pre-substitutes brand/jargon via `fashion_glossary.yaml`, then DeepL JA→EN. |
| Match | `match.py` | Brand classification with confidence + `needs_review` bucket. |
| Store | `db.py` | Loads into SQLite (`data/listings.db`), upsert/dedupe, status. |
| Web | `app.py` + `templates/` | Flask grid (filter by brand/size/condition), detail page with photo gallery, `/go/<id>` Buyee redirect. |

### A few decisions worth calling out
- **Scrape Mercari, not Buyee.** Buyee 403s bots; the data lives on Mercari anyway. The Buyee URL is *derived* from the Mercari item id, so I never scrape Buyee, I just redirect to it.
- **Brand disambiguation is the hard part.** CdG Homme / Homme Plus / Homme Deux / Shirt and Junya all cross-tag each other. Matching uses positive **and** negative keywords with a confidence score; anything ambiguous goes to `needs_review` and is never shown, so a piece is never displayed under the wrong brand. (It even catches seller misspellings like `jyunya` / `PULUS`.)
- **Prices match Mercari.** Mercari doesn't expose its FX rate, so EUR = live interbank rate (Frankfurter) × a calibrated Mercari margin, matching the price a buyer actually sees.
- **Translation ≠ raw MT.** A listing title is structured data + noise, so brand/size/season are extracted first; only the remainder is machine-translated (with a fashion glossary).

---

## Stack
Python · `mercapi` · DeepL API · SQLite · Flask/Jinja · Frankfurter (FX)

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then add your DeepL key (DEEPL_API_KEY=...)
```
> The scraper/parser don't need the key — only the translator does. Never commit `.env`.

## Run the pipeline, then the app
```bash
python scrape.py      # Mercari -> data/listings_raw.json
python parse.py       # -> data/listings_normalized.json
python translate.py   # -> data/listings_translated.json   (needs a DeepL key)
python match.py       # -> data/listings_matched.json
python db.py          # -> data/listings.db
python app.py         # http://127.0.0.1:5000
```

## Deploy (Render, free tier)
The web DB is rebuilt from the committed seed (`data/listings_matched.json`) at build time —
no SQLite binary in git.
1. Push this repo to GitHub.
2. On Render → **New Web Service** → connect the repo. `render.yaml` is auto-detected, or set:
   - **Build:** `pip install -r requirements.txt && python db.py`
   - **Start:** `gunicorn app:app --bind 0.0.0.0:$PORT`
3. Deploy → you get a public URL.

To refresh the catalog: re-run the pipeline locally and commit the new `data/listings_matched.json`.

---

## Status
MVP complete and live: browse → filter → detail/photos → redirect to Buyee, across 8 brands,
refreshed daily via GitHub Actions.
**Next:** more sources (e.g. Yahoo Auctions), finer filters (price range, saved searches), alerts.

## Disclaimer
Not affiliated with Mercari or Buyee. This is a browsing aid that reorganises public listings and
redirects to Buyee for purchase — no sales, no inventory.

---
<sub>Built with the help of AI (Claude).</sub>
