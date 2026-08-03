# 📐 Architecture — `japanese-fashion`

## 1. Vue d'ensemble

Ce projet est un **agrégateur / vitrine de mode japonaise d'occasion** : il scrape des annonces de marques ciblées (Junya Watanabe, Comme des Garçons, Undercover, Number (Nine), LGB, Tornado Mart, Pleats Please) depuis **Mercari Japan**, puis les nettoie, les traduit en anglais, les classe par marque et les stocke dans une base **SQLite**. Un petit site **Flask** affiche ensuite ce catalogue sous forme de grille filtrable (marque / taille / état / prix), avec fiche détaillée et redirection vers Mercari ou le proxy d'achat Buyee. Le tout se rafraîchit **automatiquement chaque jour** via GitHub Actions, qui recommit le catalogue et déclenche un redéploiement sur Render.

**Le cœur de la valeur** (le « moat ») n'est pas le scraping brut, mais la **couche de curation** : matching de marque fiable (les sous-lignes CdG/Junya se cross-taggent constamment) + traduction propre des titres bruités.

---

## 2. Cartographie des fichiers

### Pipeline de données (les 6 étages, dans l'ordre d'exécution)

| # | Fichier | Rôle | Entrée → Sortie |
|---|---------|------|-----------------|
| — | [brands.py](brands.py) | **Config, pas un exécutable.** Deux dictionnaires : `BRANDS` (mots-clés de recherche Mercari + termes à exclure) et `MATCH` / `MATCH_PRIORITY` (le classifieur : tokens `strong` / `weak` / `negative` par marque, vérifiés en ordre de priorité). Contient des variantes réelles de fautes de frappe romaji (`JYUNYA`, `HOMME PULUS`). | Importé par `scrape.py` et `match.py` |
| 1 | [scrape.py](scrape.py) | **Scraper.** Cherche chaque marque via `mercapi` (API Mercari reverse-engineered), enrichit chaque annonce (`full_item()` → condition, catégorie, photos, description), dédoublonne par `source_item_id`. Cap de 100 items/marque, 10 pages, délai 0,6 s (politesse). Dérive l'URL Buyee depuis l'ID Mercari (Buyee bloque les bots en 403). | ∅ → `data/listings_raw.json` |
| 2 | [parse.py](parse.py) | **Normaliseur.** Filtre : garde uniquement les IDs Mercari réguliers (`m` + 11 chiffres, pas les « Mercari Shops »), whitelist « clothing only » (drop chaussures / sacs). Mappe les 6 labels de condition Mercari → échelle normalisée, parse une taille depuis le texte libre (Mercari n'a pas de champ taille), convertit JPY→EUR. | `listings_raw.json` → `data/listings_normalized.json` |
| 3 | [translate.py](translate.py) | **Traducteur JA→EN.** Stratégie « données structurées + bruit, pas de la prose » : strip des tokens de bruit (送料無料…), pré-substitution via le glossaire YAML, puis DeepL pour le reste. **Cache incrémental** : réutilise les traductions du run précédent (via `listings_matched.json`) pour n'appeler DeepL que sur les nouveautés. Abort si toutes les traductions échouent (clé / quota morts). | `listings_normalized.json` (+ `fashion_glossary.yaml`) → `data/listings_translated.json` |
| 4 | [match.py](match.py) | **Classifieur de marque (le moat).** Normalise le titre (NFKC, lowercase, strip ponctuation), teste les marques en priorité, applique negatives / strong / weak → `brand` + `brand_confidence`. En dessous du seuil (0,6) → bucket `needs_review` (non affiché). | `listings_translated.json` → `data/listings_matched.json` |
| 5 | [db.py](db.py) | **Chargeur SQLite.** Crée le schéma `listings` (+ index), fait un **upsert sur `id`** avec suivi `first_seen_at` / `last_seen_at`, mappe le statut Mercari → `active` / `sold`. `listings_matched.json` sert de **seed committé** ; la DB est reconstruite à partir de lui au build (pas de binaire SQLite dans git). | `listings_matched.json` → `data/listings.db` |
| 6 | [app.py](app.py) | **Serveur web Flask.** 3 routes : `/` (grille filtrable, `active` uniquement, `needs_review` caché), `/item/<id>` (fiche + galerie), `/go/<id>` (log le clic → 302 vers Mercari par défaut, ou Buyee / Skimlinks via `?to=buyee`). Décore chaque ligne (badge « NEW » <1j, labels lisibles). Lit `listings.db` en lecture ; écrit dans une table `clicks`. | `listings.db` → HTML (templates) |

### Fichiers de support

| Fichier | Rôle |
|---------|------|
| [fx.py](fx.py) | Récupère le taux JPY→EUR live via **Frankfurter** (données BCE, sans clé), avec fallback `0.0060`. Applique un markup Mercari (×1,0632, ~6,3 % de marge FX) pour coller au prix EUR affiché par Mercari. Utilisé par `parse.py`. |
| [fashion_glossary.yaml](fashion_glossary.yaml) | Table de pré-substitution JA→EN (marques + jargon garment / tissu / couleur) appliquée **avant** DeepL, clés les plus longues d'abord. Utilisé par `translate.py`. |
| [render.yaml](render.yaml) | Config déploiement Render : `buildCommand` = `pip install && python db.py` (reconstruit la DB depuis le seed), `startCommand` = gunicorn. |
| [.github/workflows/daily-refresh.yml](.github/workflows/daily-refresh.yml) | **Orchestrateur.** Cron 03:00 UTC : lance scrape→parse→translate→match, **safety check** (refuse de commit si <50 listings — signe d'un blocage IP), commit le seed, `git pull --rebase -X theirs` + push (déclenche le redéploiement Render). |
| `Procfile` | `web: gunicorn app:app` — fallback de déploiement. |
| `templates/index.html`, `templates/detail.html` | Vues de la grille et de la fiche produit. |
| `requirements.txt` | Dépendances (mercapi, deepl, PyYAML, Flask, gunicorn, python-dotenv). |

---

## 3. Le flux de données (Data Flow)

```
        [brands.py]                         [fashion_glossary.yaml]      [fx.py → Frankfurter API]
            │ config                              │ pré-substitution           │ taux JPY→EUR
            ▼                                      ▼                            ▼
  ┌─────────────────┐   listings_raw.json   ┌───────────┐   normalized.json  ┌──────────────┐
  │ 1. scrape.py    │──────────────────────▶│ 2. parse  │───────────────────▶│ 3. translate │
  │ (mercapi)       │   (brut, ~770 items)  │ (filtre+  │   (~666, EUR, size)│  (DeepL +    │
  └─────────────────┘                       │  norm)    │                    │  cache)      │
                                            └───────────┘                    └─────┬────────┘
                                                                                    │ translated.json
                                            ┌───────────┐   listings_matched.json   ▼
                                            │ 5. db.py  │◀──────────────────────┌───────────┐
                                            │ (upsert)  │   (seed committé,~641)│ 4. match  │
                                            └─────┬─────┘         ▲             │ (marque + │
                                                  │ listings.db   │             │  confiance)│
                                                  ▼               │ CACHE       └───────────┘
                                            ┌───────────┐         └── (translate.py relit ce
                                            │ 6. app.py │              fichier comme cache)
                                            │  (Flask)  │──▶ HTML (grille / fiche / redirect)
                                            └───────────┘
```

**Points clés du flux :**

1. **Chaîne linéaire JSON** : chaque étage lit le JSON de l'étage précédent et en écrit un nouveau. Le format de payload est conservé et enrichi au fil de l'eau (`translate.py` et `match.py` mutent les listings en place et ajoutent des métadonnées `translated_at` / `matched_at` / `brand_distribution`).
2. **Boucle de cache** (subtile) : `translate.py` relit `listings_matched.json` (la sortie finale du run précédent) comme cache de traductions → il ne dépense du quota DeepL que sur les nouvelles annonces.
3. **`listings_matched.json` est le seed pivot** : c'est le seul fichier committé qui compte pour la prod. Render (et le build CI) reconstruit `listings.db` depuis lui. La DB n'est jamais dans git.
4. **Deux « chemins » de données dans `data/`** : les fichiers `junya_man*.json` sont une **ancienne itération mono-marque** (le prototype « slice »), les `listings_*.json` sont le pipeline multi-marques actuel.

---

## 4. État actuel

**Le projet est complet et déployé de bout en bout.** Les 6 étages fonctionnent, le rafraîchissement quotidien tourne (les commits `chore: daily catalog refresh` sont générés automatiquement par le bot GitHub Actions), et le catalogue actuel contient **~641 listings matchés** sur 8 marques.

**Chronologie récente (git) — les derniers chantiers étaient produit / UX, pas infra :**
- `9576895` — âge des annonces + badge « NEW » (<1j) → le dernier point travaillé (voir `app.py::age_bucket`).
- `d56ddda` — filtre récence + prix + **bascule de la redirection vers Mercari** (feedback utilisateur : laisser l'acheteur choisir son proxy).

**Signaux d'un travail « en pause à mi-chemin » (opportunités de monétisation dormantes) :**
- 💤 **Skimlinks inerte** : `affiliate_url()` existe mais reste désactivé tant que `SKIMLINKS_ID` n'est pas set (compte non approuvé). La redirection par défaut est passée à Mercari.
- 💤 **Waitlist email** : la barre d'inscription est cachée tant que `WAITLIST_ACTION` (Formspree) n'est pas configuré.
- 💤 **Analytics** : Cloudflare optionnel, désactivé sans token.
- 📊 **Table `clicks`** : les clics sortants sont loggés mais il n'y a **aucune vue / dashboard** pour les lire — la donnée s'accumule sans être exploitée.

**Suite logique (par ordre de valeur) :**
1. **Activer une brique de monétisation / rétention** : soit approuver Skimlinks (revenu), soit brancher la waitlist Formspree (audience) — les deux sont câblés, il ne manque que la variable d'env.
2. **Exploiter la table `clicks`** : une route admin `/stats` (annonces / marques les plus cliquées) transformerait la télémétrie déjà collectée en signal de curation.
3. **Nettoyer les artefacts `junya_man*.json`** dans `data/` (prototype mono-marque obsolète, source de confusion).
4. **Robustesse du scraping** : le safety-check CI (`<50 listings`) protège contre un blocage IP, mais il n'y a pas d'alerte quand ça arrive silencieusement — un ping (Slack / email) sur échec du workflow serait le prochain durcissement.
