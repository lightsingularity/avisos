# CLAUDE.md — avisos (avisosdeocasion.com, Bienes Raíces, Monterrey)

Polite scraper + Streamlit dashboard for the Monterrey real-estate market. Runs on
GitHub Actions; the **event log is the source of truth** (`data/eventos/*.jsonl`,
versioned in git). The SQLite DB is rebuilt from it and is gitignored.

Code and comments are in **Spanish**; prices are **MXN**. Be polite: 1 req/s,
respect robots.txt. Never commit the SQLite DB.

---

## Next steps (start here)

1. **Price long-tail (main open task).** ~800–900 listings (incl. ~440 *venta*)
   have a price on the site but **not** in our data, so they don't appear in the
   dashboard (the `analisis` view inner-joins price). They are índice listings on
   category **page 2+**, whose price we never fetch. Reported symptom: avisos like
   `32360772` / `32360783` visible on the web but missing from the app.
   - **Do this — Camino A (detail-enrichment):** in `run.py`, after combining
     sources, for each índice-only listing **without a price**, GET its detail
     page and parse with `detail_parser` (already extracts price reliably). Add a
     `post`/rate-limited GET path; ~1 request per listing. Decide scope:
     **venta-only** (~440/day, ~7 min) vs **all** (~888/day, ~15 min). Then
     re-capture the baseline (see Procedures) so existing records get prices.
   - **Do NOT pursue Camino B (POST pagination of `/Portada/PostIndice`).** It was
     reverse-engineered over 4 cycles and **rejected**: the endpoint returns rich
     priced JSON but is **stateful and stalls after ~2 pages** regardless of the
     `pagina` field (walked pages 1–6 → only 44 unique of 238). Don't retry
     without genuinely new evidence. (Investigation lived on branch
     `claude/proto-paginacion`.)
2. **~25 id-only records** (no slug-derived fields, `tipo_transaccion` NULL).
   Investigate why (category slug that didn't parse, or sitemap entries with empty
   titles).
3. **1 built listing still typed `terreno`** (a rare `K_Cla3` code outside the
   majority vote). Negligible; self-corrects when next seen rich.

---

## Architecture

`run.py` combines **two sources**, dedup by `id_aviso`:

1. **Sitemap (novedades)** — `scraper/sitemap.py`. ~890 avisos in 1 request. For a
   new aviso *without* a caption it fetches its **detail page** (`detail_parser`).
2. **Índice (full catalog)** — `scraper/indice.py`. ~2,200 avisos. Each category
   page (`/Portada/Indice/{slug}/{numero}`) embeds an `<input name="json">` with
   `K_Avisos` (all ids in the category) + `Avisos` (rich objects — price, areas,
   colonia — for **page 1 only**, ~23). **One GET per category; no pagination.**

Data flow: scraper → `data/eventos/YYYY-MM.jsonl` (append-only log) → `db.py`
reconstructs SQLite → `app.py` (Streamlit) reads the `analisis` view (**priced
listings only**) via `analytics.py`.

---

## Gotchas (hard-won — read before changing the scraper)

- **The site 403s anything that isn't a real browser (CloudFront).** Only GitHub
  Actions runners can reach it; this dev container cannot. To run a script against
  the live site: **dispatch an existing workflow** (`calibrate.yml` or
  `scrape.yml`, which live on `main`) **against your branch** — it runs *your
  branch's* scripts. A brand-new workflow file is NOT dispatchable unless it's on
  the default branch. Trick used before: point `calibrate.py`'s `__main__` at a
  throwaway script, dispatch `calibrate.yml` on the branch, read the Actions log.
- **Type/transaction come from the listing's own codes, NOT the page slug.**
  Category pages are *contaminated* with cross-listed items (e.g.
  `venta-terreno-VALLE`'s page-1 grid is mostly casas). Each `Avisos` object has:
  - `K_Cla2` = transacción: `260`=venta, `261`=renta, `262`=traspaso.
  - `K_Cla3` = tipo: `120`=casa, `121`=departamento, `122`/`126`=terreno, …
    (correlates 1:1 with `m2Const>0` = built). `indice.aprender_clasificacion()`
    learns code→label by **majority vote across all categories** (contamination is
    the minority, so the vote recovers the true meaning).
  - `ZonMun` = clean zona string.
- **Category coverage is keyed by SLUG**, not the URL number. The number is a
  *type id shared across zones* (`966501` = venta-casa in every zone); keying by it
  collapses coverage and suppresses bajas.
- **`m²` rendering:** detail pages use plain `m2` (so `detail_parser`/`atributos`
  work); category cards use `m<sup>2</sup>` — but índice reads the JSON, not text.
- **Tests assert INVARIANTS** against real fixtures, which `calibrate.py`
  overwrites each run. Don't pin exact counts/ids (`tests/test_indice.py`).
- **USD listings:** price omitted (no currency column); MXN only.

---

## Workflows (`.github/workflows/`)

- `tests.yml` — pytest on every PR and push to `main`.
- `scrape.yml` — daily 13:00 UTC + manual. Runs `python -m scraper`, commits
  `data/eventos`.
- `calibrate.yml` — manual. Captures real fixtures into `tests/fixtures/`, commits.

## Procedures

- **Run code against the live site:** dispatch `calibrate.yml`/`scrape.yml` on your
  branch (see Gotchas). Read results from the Actions job log.
- **Re-capture the baseline** (after a parser fix, to correct already-stored data):
  on a branch, `git rm data/eventos/2026-06.jsonl`, commit, push; dispatch
  `scrape.yml` on the branch; open a PR and merge (take the branch's version if it
  conflicts with main's daily data commits).
- **Config** (`config.yaml`): `usar_indice`, `detalle: nunca|faltantes|todos`,
  `indice.umbral_cobertura`, `seg_entre_solicitudes`.

## Current state

`main` has the K_Cla3-based typing (PR #2) and a clean baseline (~2,184 avisos,
PR #3). 35 tests green. The price long-tail (Next steps #1) is the open item.
