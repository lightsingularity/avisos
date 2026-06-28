"""Pruebas del parser de detalle (ubicación estructurada) y del enriquecimiento
de altas nuevas del índice en run.py.

La página de detalle expone la zona en el og:title y la colonia en el <title>;
esto permite, para los avisos solo-índice sin precio (la cola), añadir precio y
CORREGIR la zona contaminada del slug. Desde que el detalle se visita para TODA
alta nueva del índice (no solo la cola), los avisos "ricos" (ya con precio y
zona real de ZonMun) también lo visitan, pero solo para aportar la descripción
libre: su precio/zona no deben perderse. Se usa HTML sintético (no fixtures)
para que las pruebas no dependan de la captura del día.
"""
from types import SimpleNamespace

from scraper import db as dbmod
from scraper import events as evmod
from scraper import run as runmod
from scraper.detail_parser import parsear_detalle
from scraper.indice import ResultadoIndice
from scraper.sitemap import EntradaSitemap


def _detalle_html(trans_tipo="Se vende casa", zona="VALLE", colonia="LOS ROBLES",
                  precio="3500000", con_og=True, con_label=True, descripcion_larga=None):
    og = f'<meta property="og:title" content="{trans_tipo} en {zona}">' if con_og else ""
    label = f"<p>Zona: {zona} Colonia Precio Desde: Hasta:</p>" if con_label else ""
    jsonld = ""
    if precio:
        # % en vez de f-string para no pelear con las llaves del JSON.
        jsonld = ('<script type="application/ld+json">'
                  '{"@type":"Product","offers":{"@type":"Offer",'
                  '"price":"%s","priceCurrency":"MXN"}}</script>') % precio
    desc_div = ""
    if descripcion_larga:
        desc_div = (f'<div id="id_descripcion"><p>resumen corto</p>'
                    f'<p>{descripcion_larga}</p></div>')
    return f"""<html><head>
      <title>{trans_tipo} en {colonia} | Avisos de Ocasión</title>
      {og}{jsonld}
    </head><body>{label}<div>3 Recámaras 2 baños</div>{desc_div}</body></html>"""


# ----------------------------- parser ----------------------------------
def test_detalle_zona_de_ogtitle_colonia_de_title():
    out = parsear_detalle(_detalle_html())
    assert out["zona"] == "VALLE"            # del og:title ("... en VALLE")
    assert out["colonia"] == "LOS ROBLES"    # del <title> ("... en LOS ROBLES | ...")
    assert out["tipo_transaccion"] == "venta" and out["tipo_inmueble"] == "casa"
    assert out["precio"] == 3_500_000 and out["precio_unidad"] == "total"


def test_detalle_zona_respaldo_etiqueta():
    # Sin og:title, la zona sale de la etiqueta "Zona: X".
    out = parsear_detalle(_detalle_html(con_og=False))
    assert out["zona"] == "VALLE"


def test_detalle_sin_ubicacion_no_inventa():
    # Sin og:title ni etiqueta, no se inventa zona (mejor vacío que basura).
    out = parsear_detalle(_detalle_html(con_og=False, con_label=False, colonia="X"))
    assert "zona" not in out


def test_detalle_zona_con_espacios():
    out = parsear_detalle(_detalle_html(zona="CARRETERA NACIONAL", colonia="SIERRA ALTA"))
    assert out["zona"] == "CARRETERA NACIONAL" and out["colonia"] == "SIERRA ALTA"


def test_detalle_transaccion_del_ogtitle_no_la_sombrea_jsonld():
    # Caso real (PH 32348746): el name de JSON-LD es marketing ("Espectacular
    # Penthouse…") y NO clasifica; no debe sombrear al og:title estructurado
    # "Se vende departamento en VALLE". La transacción/tipo salen del og:title.
    html = """<html><head>
      <title>Se vende departamento en VALLE ORIENTE | Avisos de Ocasión</title>
      <meta property="og:title" content="Se vende departamento en VALLE">
      <script type="application/ld+json">
      {"@type":"Product","name":"Espectacular Penthouse con las mejores vistas",
       "offers":{"@type":"Offer","price":"20800000","priceCurrency":"MXN"}}</script>
    </head><body><div>3 Recámaras 3 baños</div></body></html>"""
    out = parsear_detalle(html)
    assert out["tipo_transaccion"] == "venta"
    assert out["tipo_inmueble"] == "departamento"
    assert out["zona"] == "VALLE"


def test_detalle_descripcion_completa_no_solo_el_resumen():
    # La sección "DESCRIPCIÓN" trae el texto libre del vendedor (lote industrial,
    # cajones de estacionamiento…); no debe quedarse con el resumen corto.
    out = parsear_detalle(_detalle_html(
        descripcion_larga="Lote industrial con 4 cajones de estacionamiento"))
    assert "resumen corto" in out["descripcion"]
    assert "Lote industrial con 4 cajones de estacionamiento" in out["descripcion"]


# ----------------- enriquecimiento de la cola en run.py -----------------
class _ClienteDetalle:
    """Cliente falso: cualquier GET devuelve la misma página de detalle."""
    def __init__(self, html):
        self.html = html
        self.gets = 0

    def cargar_robots(self):
        pass

    def get(self, url):
        self.gets += 1
        return SimpleNamespace(text=self.html, raise_for_status=lambda: None)


def _sitemap_dummy():
    # Una entrada cualquiera para que la corrida no aborte por sitemap vacío;
    # NO es el aviso de cola que nos interesa.
    return [EntradaSitemap(id_aviso="999",
                           url="https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso=999",
                           lastmod="2026-06-20", titulo="Se vende casa en CUMBRES",
                           caption="CUMBRES - X $1,000,000", fotos=[])]


def _cola(trans="venta", zona_slug="CENTRO"):
    """ResultadoIndice con UN aviso solo-índice, sin precio, zona del slug."""
    rec = {"id_aviso": "32360001",
           "url": "https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso=32360001",
           "tipo_transaccion": trans, "tipo_inmueble": "casa", "zona": zona_slug,
           "categoria": f"{trans}-casa-{zona_slug}"}
    cat = f"{trans}-casa-{zona_slug}"
    return ResultadoIndice(registros={"32360001": rec}, categorias_ok={cat},
                           categorias_total=1, paginas_ok=1, paginas_total=1)


def _indice_rico(trans="venta", zona="CUMBRES"):
    """ResultadoIndice con UN aviso 'rico' (página 1: ya con precio y zona real
    de ZonMun, ambos fiables — a diferencia de la cola, que no trae precio)."""
    rec = {"id_aviso": "32360002",
           "url": "https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso=32360002",
           "tipo_transaccion": trans, "tipo_inmueble": "casa", "zona": zona,
           "categoria": f"{trans}-casa-{zona}", "precio": 9_000_000,
           "precio_unidad": "total", "_tipo_fiable": True, "_trans_fiable": True}
    cat = f"{trans}-casa-{zona}"
    return ResultadoIndice(registros={"32360002": rec}, categorias_ok={cat},
                           categorias_total=1, paginas_ok=1, paginas_total=1)


def _correr(monkeypatch, tmp_path, idx, cfg):
    monkeypatch.setattr(evmod, "DIR_EVENTOS", tmp_path / "eventos")
    cliente = _ClienteDetalle(_detalle_html(zona="VALLE", colonia="LOS ROBLES"))
    monkeypatch.setattr(runmod, "ClienteEducado", lambda **kw: cliente)
    monkeypatch.setattr(runmod, "descargar_sitemap", lambda c: _sitemap_dummy())
    monkeypatch.setattr(runmod, "cosechar_indice",
                        lambda c, cfg=None, categorias_historicas=None: idx)
    codigo = runmod.correr(cfg, fecha="2026-06-20")
    return codigo, cliente


def test_cola_enriquecida_corrige_zona_y_da_precio(monkeypatch, tmp_path):
    cfg = {"detalle": "nunca", "usar_indice": True,
           "indice": {"enriquecer_cola": "venta"}}
    codigo, cliente = _correr(monkeypatch, tmp_path, _cola(), cfg)
    assert codigo == 0
    assert cliente.gets == 1  # solo el aviso de cola visitó su detalle

    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    fila = con.execute("SELECT zona, colonia, precio_actual FROM analisis "
                       "WHERE id_aviso='32360001'").fetchone()
    # Antes: invisible (sin precio) y zona CENTRO (slug). Ahora: visible, zona real.
    assert fila == ("VALLE", "LOS ROBLES", 3_500_000)


def test_cola_enriquecida_copia_descripcion_sin_contactos(monkeypatch, tmp_path):
    # El índice no trae texto libre; el detalle de la cola debe aportarlo,
    # ya sin teléfonos.
    cfg = {"detalle": "nunca", "usar_indice": True,
           "indice": {"enriquecer_cola": "venta"}}
    monkeypatch.setattr(evmod, "DIR_EVENTOS", tmp_path / "eventos")
    html = _detalle_html(zona="VALLE", colonia="LOS ROBLES",
                         descripcion_larga="Bodega con oficinas, llamar al 81-1234-5678")
    cliente = _ClienteDetalle(html)
    monkeypatch.setattr(runmod, "ClienteEducado", lambda **kw: cliente)
    monkeypatch.setattr(runmod, "descargar_sitemap", lambda c: _sitemap_dummy())
    monkeypatch.setattr(runmod, "cosechar_indice",
                        lambda c, cfg=None, categorias_historicas=None: _cola())
    assert runmod.correr(cfg, fecha="2026-06-20") == 0

    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    desc = con.execute("SELECT descripcion FROM avisos "
                       "WHERE id_aviso='32360001'").fetchone()[0]
    assert "Bodega con oficinas" in desc
    assert "1234" not in desc and "[tel]" in desc


def test_detalle_transaccion_manda_sobre_indice(monkeypatch, tmp_path):
    # Anuncio doble venta/renta: el índice lo trae como RENTA (archivado en esa
    # categoría) pero el detalle dice "Se vende". La transacción del detalle manda.
    cfg = {"detalle": "nunca", "usar_indice": True,
           "indice": {"enriquecer_cola": "todos"}}
    monkeypatch.setattr(evmod, "DIR_EVENTOS", tmp_path / "eventos")
    cliente = _ClienteDetalle(_detalle_html(trans_tipo="Se vende departamento",
                                            zona="VALLE", colonia="VALLE ORIENTE"))
    monkeypatch.setattr(runmod, "ClienteEducado", lambda **kw: cliente)
    monkeypatch.setattr(runmod, "descargar_sitemap", lambda c: _sitemap_dummy())
    # Rico con transacción RENTA fiable (K_Cla2) y precio de venta.
    monkeypatch.setattr(runmod, "cosechar_indice",
                        lambda c, cfg=None, categorias_historicas=None:
                        _indice_rico(trans="renta"))
    assert runmod.correr(cfg, fecha="2026-06-20") == 0

    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    fila = con.execute(
        "SELECT tipo_transaccion, precio_actual FROM analisis WHERE id_aviso='32360002'").fetchone()
    assert fila == ("venta", 9_000_000)  # el detalle (venta) ganó sobre el índice (renta)


def test_cola_desactivada_deja_aviso_invisible(monkeypatch, tmp_path):
    cfg = {"detalle": "nunca", "usar_indice": True,
           "indice": {"enriquecer_cola": "no"}}
    codigo, cliente = _correr(monkeypatch, tmp_path, _cola(), cfg)
    assert codigo == 0
    assert cliente.gets == 0  # no se visita ningún detalle

    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    # Sin precio no entra en la vista analisis; en avisos sigue con la zona del slug.
    assert con.execute("SELECT COUNT(*) FROM analisis WHERE id_aviso='32360001'").fetchone()[0] == 0
    assert con.execute("SELECT zona FROM avisos WHERE id_aviso='32360001'").fetchone()[0] == "CENTRO"


def test_cola_venta_no_toca_rentas(monkeypatch, tmp_path):
    # Con scope 'venta', un aviso de RENTA en la cola no se enriquece.
    cfg = {"detalle": "nunca", "usar_indice": True,
           "indice": {"enriquecer_cola": "venta"}}
    codigo, cliente = _correr(monkeypatch, tmp_path, _cola(trans="renta"), cfg)
    assert codigo == 0
    assert cliente.gets == 0


def test_indice_rico_recibe_descripcion_sin_perder_zona_ni_precio(monkeypatch, tmp_path):
    # Un aviso 'rico' (ya con precio, página 1) ahora también visita su detalle
    # -para conseguir la descripción libre-, pero el detalle NO debe pisarle su
    # zona/precio reales (ZonMun/índice), más fiables que el og:title del detalle.
    cfg = {"detalle": "nunca", "usar_indice": True,
           "indice": {"enriquecer_cola": "venta"}}
    monkeypatch.setattr(evmod, "DIR_EVENTOS", tmp_path / "eventos")
    html = _detalle_html(zona="VALLE", colonia="LOS ROBLES",
                         descripcion_larga="Bodega con oficinas, llamar al 81-1234-5678")
    cliente = _ClienteDetalle(html)
    monkeypatch.setattr(runmod, "ClienteEducado", lambda **kw: cliente)
    monkeypatch.setattr(runmod, "descargar_sitemap", lambda c: _sitemap_dummy())
    monkeypatch.setattr(runmod, "cosechar_indice",
                        lambda c, cfg=None, categorias_historicas=None: _indice_rico())
    assert runmod.correr(cfg, fecha="2026-06-20") == 0
    assert cliente.gets == 1  # ahora también visita su detalle

    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    fila = con.execute("SELECT zona, descripcion FROM avisos "
                       "WHERE id_aviso='32360002'").fetchone()
    assert fila[0] == "CUMBRES"  # zona real (ZonMun), no la pisa el og:title (VALLE)
    assert "Bodega con oficinas" in fila[1]
    assert "1234" not in fila[1] and "[tel]" in fila[1]

    precio = con.execute("SELECT precio_actual FROM analisis "
                         "WHERE id_aviso='32360002'").fetchone()[0]
    assert precio == 9_000_000  # precio real del índice, no lo pisa el detalle ($3.5M)
