# CLAUDE.md — avisos (avisosdeocasion.com, Bienes Raíces, Monterrey)

Polite scraper + Streamlit dashboard for the Monterrey real-estate market. Runs on
GitHub Actions; the **event log is the source of truth** (`data/eventos/*.jsonl`,
versioned in git). The SQLite DB is rebuilt from it and is gitignored.

Code and comments are in **Spanish**; prices are **MXN**. Be polite: 1 req/s,
respect robots.txt. Never commit the SQLite DB.

---

## ⚠️ Estado actual (2026-06-24) — Plan B en curso

Los **sitemaps XML del sitio están caídos**: `sitemap_bienesraices.xml` (novedades)
y `sitemap_grupos_bienesraices.xml` (grupos/índice) llevan **>12 h devolviendo una
página HTML (HTTP 200), no XML**. Eso rompe el descubrimiento del scraper actual
(depende de los sitemaps) y, por tanto, la corrida diaria. **Lo que SÍ funciona:**
las páginas de índice (`/Portada/Indice/{slug}/{numero}` → JSON con `K_Avisos`) y
las de detalle (`/Detalle/BienesRaices?Aviso={id}`).

➡️ **Plan B = reconstruir el descubrimiento sin sitemaps. El prompt para una sesión
nueva está en [`docs/plan-b-scraper.md`](docs/plan-b-scraper.md).** Resumen: scraper
*forward-only* que descubre ids por las páginas de índice (lista de categorías sacada
de los enlaces del home y/o del historial) y captura cada aviso NUEVO desde su página
de detalle. Sin backfill.

Ya en `main` (listo para reusar): arreglo de **tipado** (código `K_Cla3` / título
canónico manda sobre slug/título), **parser XML tolerante** y **aborto limpio**
(exit 2) si el sitemap no es XML. **Pendiente** cuando vuelva el sitemap: re-captura
para re-tipar lo ya almacenado.

---

## Next steps (start here)

**El scraper está bloqueado por los sitemaps caídos — ver "Estado actual" arriba y
`docs/plan-b-scraper.md`. Esa es LA tarea.** Lo de antes quedó hecho o sin efecto:

- ✅ **Price long-tail** — resuelto enriqueciendo la cola del índice con el detalle
  (`enriquecer_cola: todos`).
- ✅ **Mis-typing / built-as-`terreno`** — resuelto con la precedencia de tipo
  estructurado (`K_Cla3` / título canónico del detalle > slug).
- **NO reintentar Camino B (paginación POST de `/Portada/PostIndice`).** Descartado
  tras **8 ciclos**: pagina por `firstRegs` (offset) pero el orden del servidor es
  inestable → las páginas se traslapan y **no enumeran** la categoría (159/237 únicos
  tras 11 páginas). El descubrimiento va por `K_Avisos` de la página 1 (trae TODOS
  los ids de la categoría en un GET).

---

## Architecture

`run.py` combines **two sources**, dedup by `id_aviso`:

1. **Sitemap (novedades)** — `scraper/sitemap.py`. ~890 avisos in 1 request. For a
   new aviso *without* a caption it fetches its **detail page** (`detail_parser`).
   ⚠️ **Caído (2026-06): el sitio devuelve HTML en esta URL; ver "Estado actual".**
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

`main` tiene: tipado por `K_Cla3` + **precedencia estructurada** (tipo del código/
detalle > slug/título), enriquecimiento de la cola por detalle
(`enriquecer_cola: todos`), métricas **$/m² por tipo de inmueble**, **parser XML
tolerante** y **aborto limpio** (exit 2) si el sitemap no es XML. **50 pruebas en
verde.** Línea base ~2,200 avisos.

**Bloqueante:** los sitemaps XML del sitio sirven HTML (no XML) desde 2026-06-24 →
el scraper y la corrida diaria están caídos. La tarea es **Plan B**
(`docs/plan-b-scraper.md`). La re-captura para re-tipar lo ya almacenado queda
pendiente hasta que el sitio vuelva a servir el sitemap.
