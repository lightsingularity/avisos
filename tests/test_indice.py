"""Pruebas de la segunda fuente (páginas de categoría del índice).

El parseo se valida contra un fixture HTML REAL capturado por calibrate.py en
GitHub Actions (el runner sí alcanza el sitio), NO contra descargas en vivo: el
sitio está tras CloudFront y el entorno de pruebas puede tener el host bloqueado.

La página de categoría no expone tarjetas raspables ni paginación GET: incrusta un
`<input name="json">` con `K_Avisos` (todos los ids de la categoría) y `Avisos`
(objetos ricos de la página 1). De ahí sale todo.
"""
from pathlib import Path
from types import SimpleNamespace

from scraper import db as dbmod
from scraper import events as evmod
from scraper import run as runmod
from scraper.atributos import parsear_chips, parsear_precio
from scraper.indice import (
    ResultadoIndice,
    _parsear_grupos,
    cosechar_indice,
    extraer_busqueda,
    ids_categoria,
    parsear_avisos,
    partes_slug,
)
from scraper.sitemap import EntradaSitemap

FIXDIR = Path(__file__).parent / "fixtures"
SLUG = "venta-casa-CARRETERA-NACIONAL"
NUMERO = "966501"
URL_CAT = f"https://www.avisosdeocasion.com/Portada/Indice/{SLUG}/{NUMERO}"
P1 = (FIXDIR / f"indice_{SLUG}_p1.html").read_text(encoding="utf-8")


# ----------------------------- slug ------------------------------------
def test_slug_separa_transaccion_tipo_zona():
    assert partes_slug("venta-casa-CUMBRES") == ("venta", "casa", "CUMBRES")
    assert partes_slug("renta-departamento-VALLE") == ("renta", "departamento", "VALLE")
    assert partes_slug("venta-terreno-CARRETERA-NACIONAL") == (
        "venta", "terreno", "CARRETERA NACIONAL")
    assert partes_slug("renta-bodega-nave-industrial-SANTA-CATARINA") == (
        "renta", "bodega_nave", "SANTA CATARINA")
    assert partes_slug("traspaso-negocio-") == ("traspaso", "negocio", None)


# --------------------------- atributos ---------------------------------
def test_chips_todos_los_tipos():
    texto = ("3 Plantas | 4 Rec. | 3.5 Bñ. | 228 m2 Const. | 152 m2 Terr. | "
             "12 m Fren. | 40 m2 Ofc. | 900 m2 Bod.")
    c = parsear_chips(texto)
    assert c == {"plantas": 3, "recamaras": 4, "banos": 3.5,
                 "m2_construccion": 228, "m2_terreno": 152,
                 "metros_frente": 12, "m2_oficina": 40, "m2_bodega": 900}


def test_precio_total_y_por_m2():
    assert parsear_precio("$6,690,000")["precio"] == 6_690_000
    assert parsear_precio("$6,690,000")["precio_unidad"] == "total"
    pm2 = parsear_precio("$7,500 por metro cuadrado")
    assert pm2["precio"] == 7_500 and pm2["precio_unidad"] == "m2"
    assert parsear_precio("$64,900 más IVA")["mas_iva"] is True


# --------------------- JSON incrustado (fixture real) -------------------
def test_extraer_busqueda_trae_catalogo_completo():
    data = extraer_busqueda(P1)
    assert data is not None
    # K_Avisos es el catálogo COMPLETO de la categoría (no solo la página 1).
    assert data["Registros"] == len(data["K_Avisos"]) == 242
    # 'Avisos' son los objetos ricos de la página 1 (un subconjunto).
    assert 0 < len(data["Avisos"]) < len(data["K_Avisos"])
    assert all(o["K_Av"] in set(data["K_Avisos"]) for o in data["Avisos"])


def test_ids_categoria():
    ids, total = ids_categoria(P1)
    assert total == 242 and len(ids) == 242 == len(set(ids))
    assert all(isinstance(i, str) for i in ids)


def test_parsear_avisos_campos_y_id_canonico():
    avisos = {a["id_aviso"]: a for a in parsear_avisos(P1, SLUG)}
    assert len(avisos) == 23                       # objetos ricos de la página 1
    a = avisos["32353380"]
    assert a["id_aviso"] == "32353380"
    assert a["tipo_transaccion"] == "venta"        # del slug
    assert a["tipo_inmueble"] == "casa"            # del slug
    assert a["zona"] == "CARRETERA NACIONAL"       # del slug
    assert a["colonia"] == "CAMINO A BAHIA ESCONDIDA"   # del campo Col
    assert a["precio"] == 26_850_000 and a["precio_unidad"] == "total"
    assert a["plantas"] == 2 and a["recamaras"] == 3 and a["banos"] == 3
    assert a["m2_construccion"] == 318 and a["m2_terreno"] == 1944
    # URL CANÓNICA (BienesRaices), no el PostBienesRaices de la tarjeta visible.
    assert a["url"] == "https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso=32353380"
    # Campos en cero del JSON no se inventan.
    assert "m2_oficina" not in a and "metros_frente" not in a


def test_parsear_avisos_sin_json_devuelve_vacio():
    assert parsear_avisos("<html><body>sin json</body></html>", SLUG) == []
    assert extraer_busqueda("<html></html>") is None


# --------------------------- cosecha (fixture real) ---------------------
class ClienteFixture:
    """Cliente falso que sirve HTML/XML de fixtures según la URL pedida."""
    def __init__(self, paginas: dict[str, str], fallan: set[str] | None = None):
        self.paginas = paginas
        self.fallan = fallan or set()

    def get(self, url):
        if url in self.fallan:
            raise RuntimeError(f"403 simulado: {url}")
        return SimpleNamespace(text=self.paginas[url], raise_for_status=lambda: None)


_GRUPOS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{URL_CAT}</loc></url>
</urlset>"""


def test_cosechar_indice_cubre_todo_el_catalogo():
    from scraper.indice import URL_GRUPOS
    cliente = ClienteFixture({URL_GRUPOS: _GRUPOS_XML, URL_CAT: P1})
    res = cosechar_indice(cliente)

    assert res.categorias_total == 1
    assert res.categorias_ok == {NUMERO}
    assert res.cobertura == 1.0
    # UNA sola solicitud por categoría basta para los 242 ids del catálogo.
    assert len(res.registros) == 242

    # Aviso rico (estaba en 'Avisos' de la página 1): trae todos los campos.
    rico = res.registros["32353380"]
    assert rico["categoria"] == NUMERO
    assert rico["precio"] == 26_850_000
    assert rico["colonia"] == "CAMINO A BAHIA ESCONDIDA"
    assert rico["m2_construccion"] == 318

    # Aviso solo-id (en K_Avisos pero no renderizado en la página 1): registro
    # mínimo con lo derivable del slug, listo para que el sitemap lo enriquezca.
    ids_ricos = {a["id_aviso"] for a in parsear_avisos(P1, SLUG)}
    id_min = next(i for i in ids_categoria(P1)[0] if i not in ids_ricos)
    minimo = res.registros[id_min]
    assert minimo["tipo_transaccion"] == "venta"
    assert minimo["tipo_inmueble"] == "casa"
    assert minimo["zona"] == "CARRETERA NACIONAL"
    assert minimo["categoria"] == NUMERO
    assert "precio" not in minimo


def test_cosechar_categoria_caida_no_cuenta_como_ok():
    from scraper.indice import URL_GRUPOS
    cliente = ClienteFixture({URL_GRUPOS: _GRUPOS_XML, URL_CAT: P1},
                             fallan={URL_CAT})
    res = cosechar_indice(cliente)
    assert res.categorias_total == 1
    assert res.categorias_ok == set()      # no se pudo leer -> no es 'ok'
    assert res.cobertura == 0.0
    assert res.registros == {}


# ----------------- integración: dos fuentes + bajas seguras -----------------
# Estos tests ejercen el MERGE/bajas de run.py (no el parseo), así que construimos
# el ResultadoIndice a mano con registros con el esquema que produce el parser.
def _entrada(id_aviso, titulo, caption):
    return EntradaSitemap(
        id_aviso=id_aviso,
        url=f"https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso={id_aviso}",
        lastmod="2026-06-20", titulo=titulo, caption=caption,
        fotos=[f"https://ws.avisosdeocasion.com/fotoswa/2/{id_aviso}/1/8/0/foto.jpg"],
    )


def _rec(idv, **extra):
    base = {"id_aviso": idv, "categoria": NUMERO,
            "url": f"https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso={idv}",
            "tipo_transaccion": "venta", "tipo_inmueble": "casa", "zona": "CUMBRES"}
    base.update(extra)
    return base


def _indice(registros, ok=True, total=1):
    return ResultadoIndice(
        registros={r["id_aviso"]: r for r in registros},
        categorias_ok={NUMERO} if ok else set(),
        categorias_total=total, paginas_ok=1 if ok else 0, paginas_total=1)


def _indice_completo():
    """Una categoría OK con 5 avisos (uno compartido con el sitemap)."""
    return _indice([
        _rec("32366810", colonia="CUMBRES MADEIRA", precio=6_690_000,
             precio_unidad="total", m2_construccion=228, m2_terreno=152, banos=3.5),
        _rec("32366811", precio=7_200_000, precio_unidad="total"),
        _rec("32366812", precio=25_000, precio_unidad="total"),
        _rec("32366813", precio=8_900_000, precio_unidad="total"),
        _rec("32366814", precio=3_980_000, precio_unidad="total"),
    ])


def _correr(monkeypatch, tmp_path, entradas, idx, fecha, cfg=None):
    monkeypatch.setattr(evmod, "DIR_EVENTOS", tmp_path / "eventos")
    monkeypatch.setattr(runmod, "ClienteEducado", lambda **kw: type("C", (), {
        "cargar_robots": lambda self: None})())
    monkeypatch.setattr(runmod, "descargar_sitemap", lambda c: entradas)
    monkeypatch.setattr(runmod, "cosechar_indice", lambda c, cfg=None: idx)
    base = {"detalle": "nunca", "usar_indice": True}
    if cfg:
        base.update(cfg)
    return runmod.correr(base, fecha=fecha)


CASA = ("Se vende casa en CUMBRES",
        "CUMBRES - CUMBRES MADEIRA 3 Recámaras 3baños 2Plantas "
        "228 Metros Cuadrados de Construcción $6,690,000 Casa con jardín, trato directo")


def test_combina_fuentes_y_deduplica(monkeypatch, tmp_path):
    # El sitemap trae 1 aviso (32366810) que TAMBIÉN está en el índice + 1 propio.
    entradas = [_entrada("32366810", *CASA),
                _entrada("32360001", "Se vende casa en VALLE",
                         "VALLE - DEL VALLE 4 Recámaras $9,000,000 amplia residencia")]
    assert _correr(monkeypatch, tmp_path, entradas, _indice_completo(), "2026-06-20") == 0

    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    # Union deduplicada: 5 del índice + 1 exclusivo del sitemap = 6 (no 7).
    assert con.execute("SELECT COUNT(*) FROM avisos").fetchone()[0] == 6

    # El aviso compartido conserva la DESCRIPCIÓN del sitemap (el índice no la trae)
    # y, en conflicto, gana el sitemap (banos: "3baños"=3, no el 3.5 de la tarjeta);
    # el índice solo RELLENA huecos (m2_terreno, que el caption no traía).
    fila = con.execute("SELECT descripcion, colonia, m2_construccion, banos, m2_terreno "
                       "FROM avisos WHERE id_aviso='32366810'").fetchone()
    assert fila[0] and "jardín" in fila[0]
    assert fila[1] == "CUMBRES MADEIRA" and fila[2] == 228
    assert fila[3] == 3          # sitemap gana sobre el 3.5 del índice
    assert fila[4] == 152        # m2_terreno lo aporta el índice (faltaba en el caption)

    # Un aviso exclusivo del índice quedó registrado con sus campos
    solo_idx = con.execute("SELECT tipo_transaccion, zona, precio_actual "
                           "FROM analisis WHERE id_aviso='32366814'").fetchone()
    assert solo_idx == ("venta", "CUMBRES", 3_980_000)


def test_no_baja_falsa_cuando_falla_una_categoria(monkeypatch, tmp_path):
    # Día 1: índice completo -> 5 altas, cada una con su categoría.
    entradas = [_entrada("32366810", *CASA)]
    assert _correr(monkeypatch, tmp_path, entradas, _indice_completo(), "2026-06-20") == 0

    # Día 2: la categoría 966501 FALLA por completo (0 categorías OK). Ningún aviso
    # de esa categoría debe darse de baja, aunque "desaparezcan".
    idx2 = _indice([], ok=False)
    assert _correr(monkeypatch, tmp_path, entradas, idx2, "2026-06-21") == 0

    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    bajas = con.execute("SELECT COUNT(*) FROM avisos WHERE fecha_baja IS NOT NULL").fetchone()[0]
    assert bajas == 0  # cobertura 0% -> se omiten TODAS las bajas


def test_baja_real_cuando_cobertura_es_buena(monkeypatch, tmp_path):
    # Día 1: índice completo (5 avisos), sitemap con uno de ellos.
    entradas = [_entrada("32366810", *CASA)]
    assert _correr(monkeypatch, tmp_path, entradas, _indice_completo(), "2026-06-20") == 0

    # Día 2: la categoría se descarga COMPLETA pero el aviso 32366814 ya no está.
    idx2 = _indice([
        _rec("32366810", colonia="CUMBRES MADEIRA", precio=6_690_000,
             precio_unidad="total", m2_construccion=228, m2_terreno=152, banos=3.5),
        _rec("32366811", precio=7_200_000, precio_unidad="total"),
        _rec("32366812", precio=25_000, precio_unidad="total"),
        _rec("32366813", precio=8_900_000, precio_unidad="total"),
    ])
    assert _correr(monkeypatch, tmp_path, entradas, idx2, "2026-06-21") == 0

    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    # 32366814 estaba en una categoría descargada completa y ya no aparece -> baja.
    baja = con.execute("SELECT fecha_baja FROM avisos WHERE id_aviso='32366814'").fetchone()[0]
    assert baja == "2026-06-21"
    # 32366810 sigue (sitemap) y 32366813 sigue (índice) -> no de baja.
    assert con.execute("SELECT fecha_baja FROM avisos WHERE id_aviso='32366810'").fetchone()[0] is None
    assert con.execute("SELECT fecha_baja FROM avisos WHERE id_aviso='32366813'").fetchone()[0] is None


def test_grupos_sitemap_filtra_indice():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.avisosdeocasion.com/Portada/Indice/venta-casa-CUMBRES/966501</loc></url>
      <url><loc>https://www.avisosdeocasion.com/Portada/Indice/renta-departamento-VALLE/1054526</loc></url>
      <url><loc>https://www.avisosdeocasion.com/otra-cosa</loc></url>
    </urlset>"""
    urls = _parsear_grupos(xml)
    assert len(urls) == 2
    assert all("/Portada/Indice/" in u for u in urls)
