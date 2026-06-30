# CLAUDE.md — avisos (avisosdeocasion.com, Bienes Raíces, Monterrey)

Polite scraper + Streamlit dashboard for the Monterrey real-estate market. Runs on
GitHub Actions; the **event log is the source of truth** (`data/eventos/*.jsonl`,
versioned in git). The SQLite DB is rebuilt from it and is gitignored.

Code and comments are in **Spanish**; prices are **MXN**. Be polite: 1 req/s,
respect robots.txt. Never commit the SQLite DB.

---

## Estado actual (2026-06-25) — Plan B IMPLEMENTADO

Los **sitemaps XML del sitio siguen caídos** (sirven HTML, HTTP 200, no XML desde
2026-06-24): `sitemap_bienesraices.xml` (novedades) y `sitemap_grupos_bienesraices.xml`
(grupos/índice). **Plan B ya está implementado** y el scraper corre de nuevo sin
depender de ellos.

**Cómo descubre ahora (`scraper/indice.urls_categoria`, resiliente):** intenta el
sitemap de grupos; si sirve XML válido lo usa (atajo, se autocura solo); si sirve
HTML, **construye las URLs de categoría desde los slugs del HISTORIAL** (la bitácora)
con la forma `/Portada/Indice/{slug}/{n}`. Verificado en vivo (sonda 2026-06-25): el
**`{n}` es COSMÉTICO** (solo cambia el `<title>`); quien rutea/filtra por zona+tipo es
el **SLUG**. Si el historial está vacío (re-captura desde cero / clon nuevo), cae a la
**SEMILLA** versionada (`data/categorias_semilla.txt`, 59 slugs) para no quedarse sin
categorías. `run.py` ya no aborta cuando el sitemap está caído: el **índice es la
fuente principal**, el sitemap de novedades es **opcional** (se usa si vuelve a servir
XML). Captura forward-only: TODA alta nueva del índice visita detalle
(`enriquecer_cola: todos`) — a la cola (sin precio) le aporta precio y corrige
zona/colonia; a los "ricos" de página 1 (tipo/precio/zona ya fiables desde los
objetos del índice) el detalle solo les aporta la descripción libre del
vendedor, sin pisar lo ya fiable.

**Línea base re-capturada limpia (2026-06-25) vía Plan B + semilla** —ya NO esperó al
sitemap—: ~2,215 avisos, tipado por `K_Cla3`, 97 % con precio. El ruido legacy (mal
tipados, precios stale/placeholder) se eliminó; lo que queda (2 terrenos con
construcción por su propio `K_Cla3`, ~17 precios placeholder) es del ORIGEN, no de la
captura.

---

## Next steps (start here)

Plan B está hecho y validado en `scrape.yml`. Posibles siguientes pasos:

- **Re-captura/re-tipado** de la línea base cuando el sitemap vuelva a servir XML
  (ver Procedures). Hasta entonces el índice por historial mantiene la corrida diaria.
- **Cobertura de categorías nuevas:** el descubrimiento por historial no ve zonas/tipos
  que nunca hayan aparecido (el home **no** expone enlaces `/Portada/Indice/` — 0,
  verificado). Si surge una categoría nueva, entra al historial en cuanto el sitemap
  vuelva, o se puede sembrar a mano en la bitácora.
- **NO reintentar Camino B (paginación POST de `/Portada/PostIndice`).** Descartado
  tras **8 ciclos**: pagina por `firstRegs` (offset) con orden inestable → no enumera.
  El descubrimiento va por `K_Avisos` (trae TODOS los ids de la categoría en un GET).

---

## Architecture

`run.py` combines **two sources**, dedup by `id_aviso`:

1. **Sitemap (novedades)** — `scraper/sitemap.py`. ~890 avisos in 1 request. For a
   new aviso *without* a caption it fetches its **detail page** (`detail_parser`).
   ⚠️ **OPCIONAL desde Plan B (2026-06): el sitio sirve HTML aquí. `run.py` lo
   intenta y, si no es XML, sigue con el índice como fuente principal sin abortar.**
2. **Índice (full catalog, fuente principal)** — `scraper/indice.py`. ~2,200 avisos.
   La lista de categorías sale de `urls_categoria` (**resiliente**): el sitemap de
   grupos si sirve XML, o los **slugs del historial** (`/Portada/Indice/{slug}/{n}`,
   `n` cosmético) si no. Each category page embeds an `<input name="json">` with
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
- **Category coverage is keyed by SLUG**, not the URL number. **El número de la URL
  es COSMÉTICO** (verificado en vivo 2026-06-25): `/Portada/Indice/{slug}/{n}` con
  `n` ∈ {966501, 1, 0, …} devuelve el MISMO `K_Avisos`; `n` solo cambia el `<title>`.
  Quien rutea/filtra por **zona+tipo es el SLUG**. El segmento `{n}` sí es
  estructuralmente obligatorio (sin él → PageNotFound), pero su valor da igual
  (`indice.NUM_CATEGORIA_PLACEHOLDER`). Por eso el descubrimiento por historial usa
  los slugs con un número placeholder.
- **`K_Avisos` se trunca a 500** en categorías enormes (p. ej. un slug sin zona:
  `Registros`>`len(K_Avisos)`). `cosechar_indice` detecta el truncamiento
  (`len(kav) < total`) y NO marca esa categoría como completa: sus ids sirven para
  altas, pero no se usan para bajas. Los slugs **por zona** quedan bajo el tope.
- **El home NO expone enlaces de categoría** (`/Portada/Indice/…`): 0 en `/`,
  `/Portada/BienesRaices`, `/BienesRaices` (verificado). La única fuente de slugs sin
  el sitemap de grupos es el **historial** (la bitácora).
- **`m²` rendering:** detail pages use plain `m2` (so `detail_parser`/`atributos`
  work); category cards use `m<sup>2</sup>` — but índice reads the JSON, not text.
- **El índice es CATÁLOGO, el detalle es VERDAD.** El índice sirve para DESCUBRIR
  (qué avisos existen, `K_Avisos`) y para BAJAS; sus atributos son un atajo de la
  página 1, pero **subcuentan** (p. ej. los medios baños: trae `Banios` sin `MedBan`,
  da 3.0 donde el panel dice 3.5). Como YA visitamos el detalle de toda alta, los
  atributos numéricos del **panel del detalle MANDAN** sobre el índice (`run.py`,
  override). El panel se lee del **`og:description` ESTRUCTURADO** (no del cuerpo
  libre: el cuerpo tiene números sueltos —"… 2 Baños 2.5 …"— y un parseo del cuerpo
  agarra el "2"). Para la línea base, el evento `attrs` (backfill
  `backfill_atributos.py`) re-lee el panel y corrige.
- **Tests assert INVARIANTS** against real fixtures, which `calibrate.py`
  overwrites each run. Don't pin exact counts/ids (`tests/test_indice.py`).
- **USD listings:** el sitio cotiza muchos terrenos en USD (común en MTY). Se guarda
  la **moneda nativa** (`historial_precios.moneda`, MXN por defecto), nunca se dropea
  ni se convierte. El flag `USD` del índice **no es fiable** (dejó pasar dólares como
  MXN → 17x subvaluado); el **DETALLE manda**: `priceCurrency` del JSON-LD y, sobre
  todo, "$X Dólares" / "DLLS/MTS2" en el texto (`detail_parser._RX_USD`). Las medianas
  **nunca mezclan monedas** (`analytics.por_moneda`); el tablero muestra MXN y USD en
  tarjetas separadas y las gráficas usan una sola moneda. Los umbrales de plausibilidad
  (`PISO_PRECIO_TOTAL`, `TECHO_PRECIO_M2`) se escalan a USD con `_ESCALA_USD` (~20, NO
  es tipo de cambio: solo umbral). Backfill: evento `moneda` (`backfill_moneda.py`).
- **Precios placeholder:** el sitio sirve precios basura cuando el anunciante deja el
  precio "a consultar" (venta $4, terreno $450…). `db.precio_valido` los descarta al
  reconstruir la SQLite (pisos del precio TOTAL por transacción: venta ≥ $100k,
  traspaso ≥ $10k, renta ≥ $1k; por m² no se filtra). La **bitácora los conserva**
  (fuente de verdad, fiel al sitio); solo la **base derivada** los omite, así que no
  llegan al tablero. Ajustable en `PISO_PRECIO_TOTAL`.
- **Precio por m² mal etiquetado:** el sitio a veces mete el TOTAL en el campo de
  "precio por m²" (un terreno con "$7,500,000/m²" que en realidad vale $7.5M a
  $7,500/m²). `db.normalizar_unidad` reinterpreta como `total` cualquier `m2` por
  encima de `TECHO_PRECIO_M2` ($100k/m², imposible para suelo) al reconstruir; la
  vista ya saca $/m² = total / m2_terreno. (Aparte, un `m2_terreno` mal capturado
  —p. ej. 8 m²— inflaría el $/m²; la vista NO computa $/m² si el área es menor a
  `MIN_M2_TERRENO` (50 m²): ningún suelo real es tan chico.)
- **Anuncios dobles venta/renta (renta con precio de venta):** un anuncio "en venta
  o renta" (p. ej. un PH venta $20.8M / renta $125k) el sitio lo archiva en la
  categoría de RENTA —su `K_Cla2` dice renta— pero su precio principal y su DETALLE
  son los de VENTA. La **página de detalle es la fuente de verdad de la transacción**:
  su `og:title` dice "Se vende departamento en VALLE". Por eso `run.py` deja que la
  transacción del detalle **mande sobre el `K_Cla2`** del índice, y el detalle se
  clasifica desde el `og:title`/`<title>` ESTRUCTURADO **antes** que el `name` de
  JSON-LD (que es marketing —"Espectacular Penthouse…"— y no clasifica; si se probara
  primero sombrearía al og:title). Para la línea base ya guardada, el evento `trans`
  (backfill `backfill_transaccion.py`) re-lee el detalle y corrige la transacción.

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
  conflicts with main's daily data commits). **Con el sitemap caído, el
  descubrimiento del log vacío arranca desde `data/categorias_semilla.txt`** (la
  semilla); regenérala con los slugs distintos del log si añades categorías. La
  re-captura completa visita el detalle de toda la cola (~24 min, bajo el timeout de
  30; los eventos se anexan al final, así que un timeout no deja datos a medias).
- **Config** (`config.yaml`): `usar_indice`, `detalle: nunca|faltantes|todos`,
  `indice.umbral_cobertura`, `seg_entre_solicitudes`.

## Current state

**Plan B implementado.** El descubrimiento ya no depende de los sitemaps XML
(`urls_categoria`: sitemap de grupos si sirve XML, slugs del historial si no; número
de URL cosmético, el slug rutea). `run.py` trata el sitemap de novedades como
**opcional** y el índice como **fuente principal**; aborta limpio (exit 2) solo si NI
sitemap NI índice arrojan avisos. Guardas nuevas: **truncamiento a 500** (categoría no
apta para bajas si `K_Avisos` viene cortado) y **protección de `categoria=None`** (las
capturas viejas solo-sitemap no se dan de baja sin sitemap). Cuando el log está vacío,
el descubrimiento cae a la **semilla** (`data/categorias_semilla.txt`) y no depende al
100 % del log. Reúso total del resto (detalle, `K_Cla3`, cola, db/eventos, tablero).
**59 pruebas en verde.** Línea base **re-capturada limpia** (~2,215 avisos, 97 % con
precio) vía Plan B + semilla, sin esperar al sitemap.

Lo previo sigue vigente: tipado por `K_Cla3` + precedencia estructurada,
`enriquecer_cola: todos`, métricas $/m² por tipo, parser XML tolerante.

**Hecho:** la re-captura para re-tipar/re-preciar la línea base ya se ejecutó (vía
Plan B + semilla, sin sitemap). **Pendiente (menor):** cuando el sitemap vuelva a
servir XML, el descubrimiento lo retoma solo como atajo (self-heal, sin tocar código).
