# Monitor de Bienes Raíces — avisosdeocasion.com (Monterrey)

Sistema personal de investigación de mercado: captura **diariamente** todos los
avisos de bienes raíces de avisosdeocasion.com antes de que expiren, conserva el
histórico para siempre y lo deja listo para análisis (precios por zona, $/m²,
días en mercado, cambios de precio).

## Cómo funciona (todo en la nube, sin tu máquina)

```
GitHub Actions  (diario, 07:00 Monterrey)
   └─ python -m scraper
        1. Lee robots.txt y lo respeta
        2. Descarga sitemap_bienesraices.xml  ← 1 sola solicitud con TODO el inventario
        3. Parsea título/caption de cada aviso (zona, colonia, rec., baños, m², precio)
        4. Visita la página de detalle SOLO de avisos nuevos sin caption (cortésmente, 1 req/s)
        5. Diff contra el estado conocido → eventos: alta / precio / baja / realta
        6. git commit + push del log de eventos  (solo texto: diffs diminutos)

Streamlit Community Cloud  (gratis, conectado al MISMO repo)
   └─ app.py
        • En cada arranque reconstruye la base SQLite desde el log de eventos del repo
        • Sirve el tablero en una URL fija (https://TU-APP.streamlit.app)
        • Se actualiza solo cuando Actions hace push de datos nuevos
        ↓
   Tú abres la URL en el navegador  ← un favorito, nada que instalar
```

Nunca necesitas encender tu computadora. Actions captura los datos y Streamlit
Community Cloud los muestra; ambos leen y escriben en el mismo repositorio
privado de GitHub. (Lo único local, y opcional, es editar el parser si el sitio
cambia de diseño — y para eso puedes usar Claude Code.)

Decisiones de diseño importantes:

- **La bitácora JSONL es la base de datos de verdad**; SQLite es un caché que se
  reconstruye en segundos (en tu visita al tablero o en cualquier corrida). Por
  eso el tablero funciona en Community Cloud con solo el repo: regenera la base
  al arrancar. Texto plano = diffs perfectos en git.
- **Guardas de seguridad**: si el sitemap llega vacío o con menos de la mitad de
  los avisos de ayer, la corrida aborta SIN registrar bajas y GitHub te avisa
  por correo (un parser roto nunca debe "dar de baja" todo el inventario).
- **Privacidad**: teléfonos y correos de los anunciantes se eliminan del texto
  antes de guardar (`scraper/scrub.py`). Tu análisis no los necesita.
- **Fotos**: solo se guardan las URLs. La descarga de imágenes existe
  (`download_photos.py`) pero está desactivada por defecto — lee el comentario
  en `config.yaml` antes de activarla.

## Puesta en marcha — 100% en la nube (≈20 minutos, todo en el navegador)

No necesitas instalar Python ni nada en tu máquina. Solo una cuenta de GitHub.

### 1. Sube el proyecto a un repo privado de GitHub

Crea un repositorio **privado** (p. ej. `avisos-mty`) en github.com y sube
estos archivos ("Add file → Upload files", o con git si lo prefieres).

### 2. Pon tu correo de contacto

Edita `config.yaml` desde la web de GitHub (lápiz) y cambia `contacto:` por tu
correo real. Viaja en el User-Agent para que el sitio pueda escribirte si algo
le molesta — es parte de rastrear con la frente en alto. Confirma el cambio.

### 3. Calibración (un clic, pestaña Actions)

En tu repo → pestaña **Actions** → habilita los workflows si te lo pide → abre
**"Calibración (manual)"** → **Run workflow**. Descarga el sitemap real y unas
páginas de detalle, guarda los fixtures en el repo y escribe en el log:

- El total de avisos del sitemap (compáralo con el contador "Bienes Raíces N"
  del sitio web: confirma que el sitemap trae TODO el inventario).
- Si las páginas de detalle arrojan campos. Si dice "NINGUNO — afinar
  detail_parser.py", baja la carpeta `tests/fixtures/` recién creada y pásala a
  **Claude Code**: *"afina scraper/detail_parser.py contra estos fixtures"*. Es
  cosa de minutos. (El sistema funciona igual sin esto; solo perderías la
  descripción de los pocos avisos sin foto.)

### 4. Primera captura (un clic)

Pestaña **Actions** → **"Scrape diario de bienes raíces"** → **Run workflow**.
La primera corrida registra TODO el inventario (~2,300 altas, unos minutos) y
hace push de `data/eventos/2026-06.jsonl`. A partir de mañana corre sola cada
día a las 07:00 de Monterrey, y **GitHub te envía un correo si alguna corrida
falla**. Las siguientes solo registran diferencias.

> Plan B: si Actions fallara por bloqueo de IP (los runners salen de centros de
> datos), corre lo mismo en tu máquina con cron / Programador de tareas:
> `python -m scraper && git add data && git commit -m datos && git push`.

### 5. Publica el tablero en Streamlit Community Cloud (gratis)

1. Entra a **share.streamlit.io** y conéctate con tu cuenta de GitHub.
2. Autoriza el acceso a **repos privados** (tu repo lo es; el tablero hereda esa
   privacidad y solo lo verás tú o quien invites por correo).
3. **Create app** desde GitHub y completa:
   - Repository: `TU-USUARIO/avisos-mty`
   - Branch: `main`
   - Main file path: `app.py`
4. **Deploy**. En un par de minutos tendrás una URL fija tipo
   `https://avisos-mty.streamlit.app`. Guárdala como favorito: ese es tu tablero.

Cuando el scraper haga push de datos nuevos, Community Cloud reconstruye y
refresca el tablero solo. Para forzar la recarga, usa **Recargar datos** en la
barra lateral.

> El plan gratuito permite **una app privada a la vez** — justo la que necesitas.

### (Opcional) Correr en local

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest tests/ -q        # 19 pruebas
python -m scraper && python build_db.py
streamlit run app.py              # tablero en localhost
```

## Lista de verificación

- [ ] Repo privado creado con todos los archivos.
- [ ] `config.yaml` tiene tu correo en `contacto`.
- [ ] Workflow **Calibración** en verde; total del sitemap ≈ contador del sitio.
- [ ] Workflow **Scrape diario** (manual) en verde y hace commit de `data/eventos/`.
- [ ] App desplegada en Streamlit Community Cloud; la URL abre el tablero.
- [ ] El tablero muestra avisos, métricas y exporta CSV.
- [ ] Al día siguiente hay un commit nuevo con pocas altas/bajas (ya diferencial).
- [ ] La descripción de cualquier aviso en la tabla NO contiene teléfonos.


## Operación y mantenimiento

- **Correo de GitHub con job fallido**: abre el log del workflow. "ABORTO" con
  caída anómala = el sitio cambió o tuvo un mal día; si persiste 2 días, corre
  `calibrate.py` y lleva los fixtures a Claude Code.
- **Reconstruir la base cuando quieras**: `git pull && python build_db.py`.
- **Respaldo**: el repo ES el respaldo (texto plano + historial completo).
- **Tamaño**: ~200 KB de texto al día ≈ decenas de MB al año. Sin problema.

## Estructura

```
scraper/
  http_polite.py    cliente con robots.txt, 1 req/s, reintentos, UA identificado
  sitemap.py        descarga/parseo del sitemap (descubrimiento principal)
  caption_parser.py título+caption → campos estructurados (probado con datos reales)
  detail_parser.py  enriquecimiento desde páginas de detalle (calibrable)
  scrub.py          elimina teléfonos/correos del texto
  events.py         bitácora JSONL (fuente de verdad)
  db.py             SQLite derivado + vista `analisis` ($/m², días en mercado…)
  run.py            orquestador diario con guardas de seguridad
analytics.py        consultas/agregaciones para el tablero (sin Streamlit)
app.py              tablero Streamlit (Community Cloud o local)
.streamlit/config.toml         tema del tablero
.github/workflows/scrape.yml   corrida diaria + commit automático
.github/workflows/calibrate.yml   calibración manual de un clic
calibrate.py        captura fixtures reales y valida parsers
download_photos.py  descarga de fotos, tras bandera de configuración
build_db.py         reconstruye data/avisos.db desde la bitácora
tests/              19 pruebas (scraper + análisis), con capturas reales
```

