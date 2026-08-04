# 📐 Architecture — `japanese-fashion`

## 1. Vue d'ensemble

Ce projet est un **agrégateur / vitrine de mode japonaise d'occasion** : il scrape des annonces de marques ciblées (Junya Watanabe, Comme des Garçons, Undercover, Number (Nine), LGB, Tornado Mart, Pleats Please) depuis **Mercari Japan**, puis les nettoie, les traduit en anglais, les classe par marque et les stocke dans une base **SQLite**. Un petit site **Flask** affiche ensuite ce catalogue sous forme de grille filtrable (marque / taille / état / prix), avec fiche détaillée et redirection vers Mercari ou le proxy d'achat Buyee. Le tout se rafraîchit **automatiquement toutes les 6 heures** via GitHub Actions, qui recommit le catalogue et déclenche un redéploiement sur Render.

**Le cœur de la valeur** (le « moat ») n'est pas le scraping brut, mais la **couche de curation** : matching de marque fiable (les sous-lignes CdG/Junya se cross-taggent constamment) + traduction propre des titres bruités.

---

## 2. Cartographie des fichiers

### Pipeline de données (les 6 étages, dans l'ordre d'exécution)

| # | Fichier | Rôle | Entrée → Sortie |
|---|---------|------|-----------------|
| — | [brands.yaml](brands.yaml) + [brands.py](brands.py) | **Config en YAML, loader validant en Python** [AUDIT B1]. Par marque : `search_keywords` (tous cherchés), `exclude` (envoyés à la requête Mercari), `match.strong/weak/negative` (tokens, dont regex `re:`), `mercari_brand_names/ids` (tags structurés vendeur). Ajouter une marque = un bloc YAML, zéro code. `brands.py` valide au chargement et échoue bruyamment. | Importé par `scrape.py` et `match.py` |
| 1 | [scrape.py](scrape.py) | **Scraper.** Cherche chaque marque via `mercapi` (API Mercari reverse-engineered), enrichit chaque annonce (`full_item()` → condition, catégorie, photos, description), dédoublonne par `source_item_id`. Cap de 100 items/marque, 10 pages, délai 0,6 s (politesse). Dérive l'URL Buyee depuis l'ID Mercari (Buyee bloque les bots en 403). | ∅ → `data/listings_raw.json` |
| 2 | [parse.py](parse.py) | **Normaliseur.** Filtre : garde uniquement les IDs Mercari réguliers (`m` + 11 chiffres, pas les « Mercari Shops »), whitelist « clothing only » (drop chaussures / sacs). Mappe les 6 labels de condition Mercari → échelle normalisée, parse une taille depuis le texte libre (Mercari n'a pas de champ taille), convertit JPY→EUR. | `listings_raw.json` → `data/listings_normalized.json` |
| 3 | [match.py](match.py) | **Classifieur de marque (le moat)** — tourne AVANT la traduction depuis l'audit [AUDIT B]. Trois signaux : (1) tag structuré `item_brand` choisi par le vendeur → 0.98 (confirmation uniquement) ; (2) tokens du titre normalisé, **2 passes** strong-partout puis weak-partout (un strong bat toujours un weak d'une marque plus prioritaire) ; (3) tokens regex `re:` sur texte à espaces préservés (`\blgb\b` sans attraper 'lgbt'). Sous le seuil (0,6) → `needs_review` (non affiché, non traduit). **Testé : suite golden de 93 cas réels en CI.** | `listings_normalized.json` → `data/listings_classified.json` |
| 4 | [translate.py](translate.py) | **Traducteur JA→EN.** Strip du bruit (送料無料…), pré-substitution glossaire YAML, DeepL pour le reste. **Cache incrémental** via le seed précédent ; **skip total des `needs_review`** (~30% du volume → 0 quota gaspillé). Abort si toutes les traductions neuves échouent. | `listings_classified.json` (+ `fashion_glossary.yaml`) → `data/listings_matched.json` (le seed) |
| 5 | [db.py](db.py) | **Chargeur SQLite.** Crée le schéma `listings` (+ index), fait un **upsert sur `id`** avec suivi `first_seen_at` / `last_seen_at`, mappe le statut Mercari → `active` / `sold`. `listings_matched.json` sert de **seed committé** ; la DB est reconstruite à partir de lui au build (pas de binaire SQLite dans git). | `listings_matched.json` → `data/listings.db` |
| 6 | [app.py](app.py) | **Serveur web Flask.** 3 routes : `/` (grille filtrable, `active` uniquement, `needs_review` caché), `/item/<id>` (fiche + galerie), `/go/<id>` (log le clic → 302 vers Mercari par défaut, ou Buyee / Skimlinks via `?to=buyee`). Décore chaque ligne (badge « NEW » <1j, labels lisibles). Lit `listings.db` en lecture ; écrit dans une table `clicks`. | `listings.db` → HTML (templates) |

### Fichiers de support

| Fichier | Rôle |
|---------|------|
| [fx.py](fx.py) | Récupère le taux JPY→EUR live via **Frankfurter** (données BCE, sans clé), avec fallback `0.0060`. Applique un markup Mercari (×1,0632, ~6,3 % de marge FX) pour coller au prix EUR affiché par Mercari. Utilisé par `parse.py`. |
| [fashion_glossary.yaml](fashion_glossary.yaml) | Table de pré-substitution JA→EN (marques + jargon garment / tissu / couleur) appliquée **avant** DeepL, clés les plus longues d'abord. Utilisé par `translate.py`. |
| [render.yaml](render.yaml) | Config déploiement Render : `buildCommand` = `pip install && python db.py` (reconstruit la DB depuis le seed), `startCommand` = gunicorn. |
| [.github/workflows/catalog-refresh.yml](.github/workflows/catalog-refresh.yml) | **Orchestrateur.** Cron toutes les 6 h (00/06/12/18 UTC) : lance scrape→parse→translate→match, **safety check** (refuse de commit si <50 listings — signe d'un blocage IP), commit le seed, `git pull --rebase -X theirs` + push (déclenche le redéploiement Render). **Alerte ntfy.sh sur échec** (secret `NTFY_TOPIC`) — [AUDIT D1]. |
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
4. ~~Deux « chemins » de données dans `data/`~~ — les artefacts `junya_man*.json` ont été supprimés (audit 2026-08-04).
5. **⚠️ Ordre modifié depuis l'audit (2026-08-04, AUDIT B)** : le schéma ci-dessus garde l'ancienne numérotation visuelle mais l'ordre réel est **scrape → parse → match → translate** ; `match` lit `listings_normalized.json` et écrit `listings_classified.json`, `translate` n'en traduit que les marques matchées et écrit le seed `listings_matched.json`. Le cache de traduction pointe toujours sur le seed commité (intact au moment où translate le lit).

---

## 4. État actuel

**Le projet est complet et déployé de bout en bout.** Les 6 étages fonctionnent, le rafraîchissement toutes les 6 h tourne (les commits `chore: catalog refresh` sont générés automatiquement par le bot GitHub Actions), et le catalogue actuel contient **~694 listings matchés** sur 8 marques. **Audit Task Force en cours (2026-08-04, option B — business)** : findings et décisions dans le dossier vault `AUDIT/` ; fixes scraping C1–C3 + alerte CI D1 implémentés sur la branche `pre-prod`.

**Chronologie récente (git) — les derniers chantiers étaient produit / UX, pas infra :**
- `9576895` — âge des annonces + badge « NEW » (<1j) → le dernier point travaillé (voir `app.py::age_bucket`).
- `d56ddda` — filtre récence + prix + **bascule de la redirection vers Mercari** (feedback utilisateur : laisser l'acheteur choisir son proxy).

**Signaux d'un travail « en pause à mi-chemin » (opportunités de monétisation dormantes) :**
- 💤 **Skimlinks inerte** : `affiliate_url()` existe mais reste désactivé tant que `SKIMLINKS_ID` n'est pas set (compte non approuvé). La redirection par défaut est passée à Mercari.
- 💤 **Waitlist email** : la barre d'inscription est cachée tant que `WAITLIST_ACTION` (Formspree) n'est pas configuré.
- ✅ **Analytics** : Plausible intégré (index + detail, commit `ff48ed5`) — remplace GTM/Cloudflare.
- 📊 **Table `clicks`** : les clics sortants sont loggés mais il n'y a **aucune vue / dashboard** pour les lire — la donnée s'accumule sans être exploitée.

**Suite logique (par ordre de valeur) :**
1. **Activer une brique de monétisation / rétention** : soit approuver Skimlinks (revenu), soit brancher la waitlist Formspree (audience) — les deux sont câblés, il ne manque que la variable d'env.
2. **Exploiter la table `clicks`** : une route admin `/stats` (annonces / marques les plus cliquées) transformerait la télémétrie déjà collectée en signal de curation.
3. ~~**Nettoyer les artefacts `junya_man*.json`**~~ ✅ fait (audit 2026-08-04 — fichiers non trackés, supprimés localement).
4. ~~**Robustesse du scraping** : alerte sur échec silencieux du workflow~~ ✅ fait (audit 2026-08-04 — step ntfy.sh `if: failure()`, actif dès que le secret `NTFY_TOPIC` est créé et la branche mergée).
