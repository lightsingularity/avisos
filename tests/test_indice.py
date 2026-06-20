"""Pruebas de la segunda fuente (páginas de categoría del índice).

El parseo se valida contra fixtures HTML guardados (reconstrucciones fieles del
formato público), NO contra descargas en vivo: el sitio está tras CloudFront y
puede responder 403, y además el entorno de CI puede tener el host bloqueado.
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
    iterar_paginas,
    mapa_paginas,
    parsear_paginacion,
    parsear_tarjetas,
    partes_slug,
)
from scraper.sitemap import EntradaSitemap

FIXDIR = Path(__file__).parent / "fixtures"
P1 = (FIXDIR / "indice_venta-casa-CUMBRES_p1.html").read_text(encoding="utf-8")
P2 = (FIXDIR / "indice_venta-casa-CUMBRES_p2.html").read_text(encoding="utf-8")
SLUG = "venta-casa-CUMBRES"
URL_CAT = "https://www.avisosdeocasion.com/Portada/Indice/venta-casa-CUMBRES/966501"


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


# --------------------------- tarjetas ----------------------------------
def test_tarjetas_extrae_campos_y_id_canonico():
    tarjetas = {t["id_aviso"]: t for t in parsear_tarjetas(P1, SLUG)}
    # 3 tarjetas reales; el enlace "destacado" sin precio/atributos NO cuenta.
    assert set(tarjetas) == {"32366810", "32366811", "32366812"}
    assert "99999999" not in tarjetas

    a = tarjetas["32366810"]
    # id de 8 dígitos del href, NO el id de foto de 6 dígitos (516891) de la imagen
    assert a["id_aviso"] == "32366810"
    assert a["tipo_transaccion"] == "venta"   # de la etiqueta de la tarjeta
    assert a["tipo_inmueble"] == "casa"        # del slug
    assert a["zona"] == "CUMBRES"              # del slug
    assert a["colonia"] == "CUMBRES MADEIRA"
    assert a["precio"] == 6_690_000 and a["precio_unidad"] == "total"
    assert a["plantas"] == 2 and a["recamaras"] == 3 and a["banos"] == 3.5
    assert a["m2_construccion"] == 228 and a["m2_terreno"] == 152
    assert a["url"].endswith("Aviso=32366810")


def test_tarjeta_renta_dentro_de_pagina_venta():
    # Una tarjeta RENTA dentro de una página "venta-casa": la transacción sale de
    # la ETIQUETA de la tarjeta, no del slug.
    tarjetas = {t["id_aviso"]: t for t in parsear_tarjetas(P1, SLUG)}
    renta = tarjetas["32366812"]
    assert renta["tipo_transaccion"] == "renta"
    assert renta["tipo_inmueble"] == "casa"
    assert renta["precio"] == 25_000


# -------------------------- paginación ----------------------------------
def test_paginacion_lee_total():
    assert parsear_paginacion(P1) == (1, 2)
    assert parsear_paginacion(P2) == (2, 2)


def test_mapa_paginas_encuentra_pagina_2():
    mapa = mapa_paginas(P1, URL_CAT)
    assert 2 in mapa
    assert mapa[2] == "https://www.avisosdeocasion.com/Portada/Indice/venta-casa-CUMBRES/966501/2"


class ClienteFixture:
    """Cliente falso que sirve HTML de fixtures según la URL pedida."""
    def __init__(self, paginas: dict[str, str], fallan: set[str] | None = None):
        self.paginas = paginas
        self.fallan = fallan or set()

    def get(self, url):
        if url in self.fallan:
            raise RuntimeError(f"403 simulado: {url}")
        return SimpleNamespace(text=self.paginas[url])


def test_iterar_paginas_recorre_todas():
    cliente = ClienteFixture({
        URL_CAT: P1,
        URL_CAT + "/2": P2,
    })
    paginas = list(iterar_paginas(cliente, URL_CAT))
    assert [p.ok for p in paginas] == [True, True]
    ids = []
    for p in paginas:
        ids += [t["id_aviso"] for t in parsear_tarjetas(p.html, SLUG)]
    assert ids == ["32366810", "32366811", "32366812", "32366813", "32366814"]


def test_iterar_paginas_marca_fallo_de_pagina():
    # La página 2 falla (403): se entrega con ok=False y html None.
    cliente = ClienteFixture({URL_CAT: P1, URL_CAT + "/2": P2},
                             fallan={URL_CAT + "/2"})
    paginas = list(iterar_paginas(cliente, URL_CAT))
    assert [p.ok for p in paginas] == [True, False]


# ----------------- integración: dos fuentes + bajas seguras -----------------
def _entrada(id_aviso, titulo, caption):
    return EntradaSitemap(
        id_aviso=id_aviso,
        url=f"https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso={id_aviso}",
        lastmod="2026-06-20", titulo=titulo, caption=caption,
        fotos=[f"https://ws.avisosdeocasion.com/fotoswa/2/{id_aviso}/1/8/0/foto.jpg"],
    )


def _resultado_indice_completo():
    """Índice 'completo': una categoría, dos páginas OK, 5 avisos."""
    registros = {}
    for html in (P1, P2):
        for rec in parsear_tarjetas(html, SLUG):
            rec["categoria"] = "966501"
            registros.setdefault(rec["id_aviso"], rec)
    return ResultadoIndice(registros=registros, categorias_ok={"966501"},
                           categorias_total=1, paginas_ok=2, paginas_total=2)


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
    idx = _resultado_indice_completo()
    assert _correr(monkeypatch, tmp_path, entradas, idx, "2026-06-20") == 0

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
    assert fila[3] == 3          # sitemap gana sobre el 3.5 de la tarjeta
    assert fila[4] == 152        # m2_terreno lo aporta el índice (faltaba en el caption)

    # Un aviso exclusivo del índice quedó registrado con sus campos
    solo_idx = con.execute("SELECT tipo_transaccion, zona, precio_actual "
                           "FROM analisis WHERE id_aviso='32366814'").fetchone()
    assert solo_idx == ("venta", "CUMBRES", 3_980_000)


def test_no_baja_falsa_cuando_falla_una_categoria(monkeypatch, tmp_path):
    # Día 1: índice completo -> 5 altas, cada una con su categoría.
    entradas = [_entrada("32366810", *CASA)]
    idx1 = _resultado_indice_completo()
    assert _correr(monkeypatch, tmp_path, entradas, idx1, "2026-06-20") == 0

    # Día 2: la categoría 966501 FALLA por completo (0 páginas OK). Ningún aviso
    # de esa categoría debe darse de baja, aunque "desaparezcan".
    idx2 = ResultadoIndice(registros={}, categorias_ok=set(),
                           categorias_total=1, paginas_ok=0, paginas_total=1)
    assert _correr(monkeypatch, tmp_path, entradas, idx2, "2026-06-21") == 0

    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    bajas = con.execute("SELECT COUNT(*) FROM avisos WHERE fecha_baja IS NOT NULL").fetchone()[0]
    assert bajas == 0  # cobertura 0% -> se omiten TODAS las bajas


def test_baja_real_cuando_cobertura_es_buena(monkeypatch, tmp_path):
    # Día 1: índice completo (5 avisos), sitemap con uno de ellos.
    entradas = [_entrada("32366810", *CASA)]
    assert _correr(monkeypatch, tmp_path, entradas,
                   _resultado_indice_completo(), "2026-06-20") == 0

    # Día 2: la categoría se descarga COMPLETA pero el aviso 32366814 ya no está.
    registros = {}
    for rec in parsear_tarjetas(P1, SLUG):  # solo página 1 -> faltan 813 y 814
        rec["categoria"] = "966501"
        registros[rec["id_aviso"]] = rec
    registros["32366813"] = {"id_aviso": "32366813", "categoria": "966501",
                             "tipo_transaccion": "venta", "tipo_inmueble": "casa",
                             "zona": "CUMBRES", "precio": 8_900_000,
                             "url": "https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso=32366813"}
    idx2 = ResultadoIndice(registros=registros, categorias_ok={"966501"},
                           categorias_total=1, paginas_ok=2, paginas_total=2)
    entradas2 = [_entrada("32366810", *CASA)]
    assert _correr(monkeypatch, tmp_path, entradas2, idx2, "2026-06-21") == 0

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
