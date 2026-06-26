# Plan B — scraper sin sitemaps (relevo para sesión nueva)

> ## ✅ IMPLEMENTADO (2026-06-25)
> Este Plan B **ya está hecho**. El descubrimiento sin sitemaps vive en
> `scraper/indice.urls_categoria` (resiliente: sitemap de grupos si sirve XML, slugs
> del **historial** si no) y la orquestación en `run.py` (sitemap **opcional**, índice
> como fuente principal). Hallazgo clave de la sonda en vivo: el **número de la URL es
> COSMÉTICO**, el **slug rutea** (`NUM_CATEGORIA_PLACEHOLDER`). Guardas: truncamiento a
> 500 y protección de `categoria=None`. **57 pruebas en verde.** El doc se conserva
> como registro del diseño y del razonamiento. Pendiente: re-captura/re-tipado cuando
> el sitemap vuelva (el descubrimiento se autocura solo).

**Cómo usar:** abre una sesión NUEVA de Claude Code en este repo y pásale el
prompt de abajo (o dile "lee `docs/plan-b-scraper.md` y ejecútalo"). Se diseñó
para empezar en frío; primero debe leer `CLAUDE.md`.

**Por qué Plan B:** desde 2026-06-24 los **sitemaps XML del sitio están caídos** —
`/sitemap_bienesraices.xml` (novedades) y `/sitemap_grupos_bienesraices.xml`
(grupos/índice) devuelven una **página HTML (HTTP 200), no XML** (>12 h y contando).
El descubrimiento del scraper actual depende de ellos, así que está bloqueado. **Sí
funcionan** las páginas de índice (`/Portada/Indice/{slug}/{numero}`) y de detalle
(`/Detalle/BienesRaices?Aviso={id}`), verificado en sondas.

---

## Prompt para la sesión nueva

```
Trabajas en `avisos` — scraper educado + tablero Streamlit del mercado inmobiliario
de Monterrey (avisosdeocasion.com / Bienes Raíces). PRIMERO lee CLAUDE.md.
Convenciones: código y comentarios en ESPAÑOL; precios en MXN; la bitácora de
eventos (data/eventos/*.jsonl) es la fuente de verdad; la base SQLite está
gitignoreada y se reconstruye desde la bitácora; sé educado (1 req/s, respeta
robots.txt); NUNCA commitees la DB.

ENTORNO: este contenedor NO alcanza el sitio (CloudFront 403 a lo que no sea
navegador). Solo los runners de GitHub Actions llegan. Para correr contra el sitio
en vivo, dispara un workflow (scrape.yml o calibrate.yml) en tu rama y lee el log
de Actions; las pruebas corren offline contra fixtures en tests/fixtures/.

POR QUÉ PLAN B: los sitemaps XML del sitio — /sitemap_bienesraices.xml (novedades)
y /sitemap_grupos_bienesraices.xml (grupos) — llevan >12 h sirviendo una página
HTML (HTTP 200, el home) en vez de XML. El descubrimiento del scraper actual
depende de ellos, así que está muerto. ESTO SÍ FUNCIONA:
  - Página de índice: GET /Portada/Indice/{slug}/{numero} → HTML con un
    <input name="json"> que trae {Registros, K_Avisos:[TODOS los ids de la
    categoría], Avisos:[~23 objetos ricos de la página 1 con K_Cla3 (tipo),
    ZonMun (zona), Precio, áreas]}.
  - Página de detalle: GET /Detalle/BienesRaices?Aviso={id} → página canónica del
    aviso; scraper/detail_parser.parsear_detalle ya extrae precio/tipo/zona/colonia/
    áreas de forma fiable (datos "oro").

META: un scraper FORWARD-ONLY que NO dependa de los sitemaps XML:
  1. Descubrir el conjunto de ids activos sin DEPENDER de los sitemaps (úsalos si
     vuelven a servir XML; cae a las páginas de índice si no).
  2. Para cada id NUEVO (que no esté ya en la bitácora), visitar su página de
     DETALLE y registrar un `alta` con los campos oro.
  3. NO hacer backfill del inventario existente — conserva la bitácora actual; solo
     visita el detalle de los ids genuinamente nuevos de aquí en adelante.
  4. (Opcional/después) detección de bajas con guarda de cobertura.

DESCUBRIMIENTO (la pieza clave — diséñala primero): el detalle necesita ids, así que
hace falta una fuente de ids. Usa las páginas de índice (que SÍ funcionan):
  - Arma la lista de URLs de categoría (slug + numero) SIN el sitemap de grupos,
    desde: (a) los enlaces de categoría (/Portada/Indice/{slug}/{numero}) en el
    HTML del home / la navegación del sitio (que SÍ se sirve), y/o (b) los slugs de
    `categoria` ya presentes en la bitácora (historial). Verifica si {numero} es
    obligatorio o cosmético (prueba una categoría con número equivocado); si importa,
    saca los números por (transaccion,tipo) de los enlaces del home.
  - GET a cada página de categoría; extrae K_Avisos (indice.extraer_busqueda /
    ids_categoria ya lo parsean). La unión sobre todas las categorías = conjunto
    activo de hoy. Ids nuevos = activos − los que ya están en la bitácora.
  - GRATIS (sin request extra): los objetos ricos `Avisos` de la página 1 que bajas
    para descubrir traen precio/tipo/zona actuales — úsalos para emitir eventos de
    cambio de precio de avisos ya conocidos (preserva el seguimiento de precios) y
    para tipar avisos de página 1 sin visitar el detalle.
  - RESILIENCIA (por si el sitemap VUELVE): no hardcodees "sin sitemap". Al inicio,
    INTENTA el sitemap — baja /sitemap_bienesraices.xml (y el de grupos) y valida con
    _raiz_xml que de verdad parsea como <urlset> XML (no HTML/redirección). Si es XML
    válido, úsalo como fuente RÁPIDA de ids/categorías (como antes, pocas requests);
    si es HTML, cae al descubrimiento por páginas de índice de arriba. Ramifica por lo
    que el sitio DEVUELVE en cada corrida, no por una bandera fija: así el scraper
    funciona vuelva o no el sitemap, y un sitemap que regresa es un atajo, no una
    rotura (ni un cambio de código).

DATOS: por cada id nuevo, parsear_detalle(cliente.get(url).text) → alta. Conserva la
precedencia de tipado reciente (tipo por código K_Cla3 / título canónico > slug; la
cola adopta el tipo del detalle). detail_parser ya trae el arreglo del título canónico.

REUSAR (probado y correcto — NO reescribir): scraper/http_polite.py (cliente educado
con UA de navegador que pasa CloudFront), detail_parser.py (parser oro por aviso, con
los arreglos de tipado/zona recientes), db.py + events.py (bitácora → SQLite),
atributos.py, caption_parser.py (clasificar_titulo), app.py / analytics.py (tablero).
Reescribe SOLO el descubrimiento + la orquestación (reemplaza sitemap.py y la
dependencia del sitemap de grupos en indice.py / run.py). Puedes conservar el parseo
JSON/K_Cla3 de indice.py — es el parser de la página de categoría y sigue sirviendo.

NO REINTENTAR: la paginación POST a /Portada/PostIndice está DESCARTADA (8 ciclos de
ingeniería inversa). Pagina por `firstRegs` (offset) pero el orden del servidor es
inestable: las páginas se traslapan y NO enumeran la categoría (159/237 únicos tras
11 páginas). No la reintentes. El descubrimiento va por K_Avisos de la página 1, que
ya trae TODOS los ids de la categoría en un solo GET.

SEGURIDAD/CORTESÍA: 1 req/s; respeta robots.txt; si el descubrimiento no arroja nada
o una página viene en HTML en vez del JSON esperado, aborta limpio (exit 2, mensaje
claro) — NUNCA des de baja en masa por un fallo de parseo. Conserva el espíritu de
las guardas de colapso/cobertura.

PRUEBAS: pytest contra fixtures (offline). Valida de punta a punta disparando
scrape.yml en tu rama y leyendo el log (esperado: descubre ~el tamaño actual del
catálogo, visita el detalle solo de los ids nuevos, anexa altas, la DB reconstruye).
Captura fixtures nuevos con calibrate.yml si hace falta.

ENTREGABLE: el scraper forward conectado a `python -m scraper` (para que scrape.yml
lo corra); pruebas en verde; una corrida de validación disparada con éxito. Desarrolla
en una rama nueva; commits en español; NO abras PR ni mergees salvo que se te pida.

PRIMEROS PASOS: (1) lee CLAUDE.md + hojea run.py / indice.py / sitemap.py /
detail_parser.py; (2) dispara una sonda chica para confirmar que el home expone
enlaces /Portada/Indice/... y si {numero} importa; (3) diseña el descubrimiento a
partir de eso; (4) implementa, prueba, dispara, verifica.
```

---

## Notas de contexto (lo ya hecho en `main`)

- **Tipado arreglado:** la clasificación estructurada (código `K_Cla3` / título
  canónico) manda sobre el slug y el título heurístico; la cola adopta el tipo del
  detalle. `clasificar_titulo` lee el tipo de su posición canónica.
- **Robustez XML:** `_raiz_xml` tolera XML malformado (`&` sin escapar, chars de
  control). NO ayuda cuando la respuesta es HTML (el caso actual de los sitemaps).
- **Aborto limpio:** si el sitemap no es XML, la corrida sale con código 2 y mensaje
  claro en vez de un crash.
- **Si el sitemap VUELVE:**
  - *Antes de que exista Plan B:* el scraper actual de `main` se recupera solo —
    aborta en HTML y corre normal en XML; la próxima corrida diaria retoma sin tocar
    nada.
  - *Con Plan B ya hecho:* si el descubrimiento se construyó resiliente (intentar
    sitemap → caer a índice), también lo retoma solo como atajo. No lo ignores a
    propósito.
  - En cualquier caso queda **pendiente una re-captura única** (vaciar
    `data/eventos/2026-06.jsonl` y re-correr) para re-tipar lo ya almacenado: el
    arreglo de tipado solo corrige capturas nuevas, no las filas viejas de la DB.
