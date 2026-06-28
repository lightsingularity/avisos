"""Pruebas contra datos REALES del sitemap (capturados el 2026-06-11) y
simulación completa de tres corridas diarias (alta → cambio de precio → baja)."""
from pathlib import Path

import pytest

from scraper import db as dbmod
from scraper import events as evmod
from scraper import run as runmod
from scraper.caption_parser import parsear_entrada
from scraper.scrub import limpiar_contactos
from scraper.sitemap import EntradaSitemap, parsear_sitemap

FIXTURE = (Path(__file__).parent / "fixtures" / "sitemap_muestra.xml").read_text(encoding="utf-8")


# ----------------------------- sitemap ---------------------------------
def test_sitemap_parsea_entradas():
    entradas = parsear_sitemap(FIXTURE)
    assert len(entradas) == 8
    por_id = {e.id_aviso: e for e in entradas}
    assert "32363885" in por_id and not por_id["32363885"].tiene_caption
    depto = por_id["32363879"]
    assert depto.tiene_caption
    assert depto.fotos == ["https://ws.avisosdeocasion.com/fotoswa/2/32363879/1/8/0/foto.jpg"]
    assert depto.url.endswith("Aviso=32363879")


def test_sitemap_tolera_ampersand_sin_escapar():
    # El sitio a veces publica '&' sin escapar en el texto libre del caption, lo
    # que rompe el parser XML estricto. El parser tolerante debe recuperarse.
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
           '<url><loc>https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso=1</loc>'
           '<image:image><image:loc>http://x/f.jpg</image:loc>'
           '<image:title>Se vende casa en CUMBRES</image:title>'
           '<image:caption>Jardín & alberca, trato directo</image:caption>'
           '</image:image></url></urlset>')
    entradas = parsear_sitemap(xml)
    assert len(entradas) == 1
    assert entradas[0].id_aviso == "1"
    assert entradas[0].caption and "alberca" in entradas[0].caption


# ------------------------- caption parser ------------------------------
def test_caption_departamento_completo():
    e = {x.id_aviso: x for x in parsear_sitemap(FIXTURE)}["32363879"]
    c = parsear_entrada(e.titulo, e.caption)
    assert c["tipo_transaccion"] == "venta"
    assert c["tipo_inmueble"] == "departamento"
    assert c["zona"] == "CUMBRES" and c["colonia"] == "CUMBRES MADEIRA"
    assert c["recamaras"] == 3 and c["banos"] == 3 and c["plantas"] == 1
    assert c["m2_construccion"] == 89
    assert c["precio"] == 5_200_000 and c["precio_unidad"] == "total"


def test_caption_bodega_industrial_con_iva():
    e = {x.id_aviso: x for x in parsear_sitemap(FIXTURE)}["32363872"]
    c = parsear_entrada(e.titulo, e.caption)
    assert c["tipo_transaccion"] == "renta"
    assert c["tipo_inmueble"] == "bodega_nave"
    assert c["m2_terreno"] == 900 and c["m2_bodega"] == 900 and c["m2_oficina"] == 30
    assert c["precio"] == 64_900 and c["mas_iva"] is True


def test_caption_terreno_precio_por_m2():
    e = {x.id_aviso: x for x in parsear_sitemap(FIXTURE)}["32363838"]
    c = parsear_entrada(e.titulo, e.caption)
    assert c["tipo_inmueble"] == "terreno"
    assert c["m2_terreno"] == 1000 and c["metros_frente"] == 26
    assert c["precio"] == 7_500 and c["precio_unidad"] == "m2"


def test_caption_finca_m2_sin_calificador():
    e = {x.id_aviso: x for x in parsear_sitemap(FIXTURE)}["32363871"]
    c = parsear_entrada(e.titulo, e.caption)
    assert c["tipo_inmueble"] == "finca_campestre"
    assert c["m2_terreno"] == pytest.approx(8614.25)
    assert c["precio"] == 18_550_000


def test_caption_medio_bano():
    e = {x.id_aviso: x for x in parsear_sitemap(FIXTURE)}["32362828"]
    c = parsear_entrada(e.titulo, e.caption)
    assert c["banos"] == 1.5 and c["recamaras"] == 3
    assert c["zona"] == "SANTA CATARINA" and c["colonia"] == "LA BANDA"


def test_caption_local_sin_atributos():
    e = {x.id_aviso: x for x in parsear_sitemap(FIXTURE)}["32362852"]
    c = parsear_entrada(e.titulo, e.caption)
    assert c["tipo_inmueble"] == "local_oficina" and c["precio"] == 5_250_000
    assert c["zona"] == "VALLE"


# ------------------------------ scrub ----------------------------------
def test_limpia_telefonos_y_correos():
    t = ("Trato directo 81-1126-8716 o al 52 81 1077 7451, "
         "tambien 8183786874 y ventas@inmobiliaria.mx. Precio $5,200,000 en 89 m2.")
    limpio = limpiar_contactos(t)
    assert "8716" not in limpio and "7451" not in limpio
    assert "8183786874" not in limpio and "@" not in limpio
    assert "$5,200,000" in limpio and "89 m2" in limpio  # lo útil sobrevive


# --------------------- simulación de 3 corridas -------------------------
class ClienteFalso:
    def cargar_robots(self):
        pass


def _entrada(id_aviso, titulo=None, caption=None, foto=True):
    return EntradaSitemap(
        id_aviso=id_aviso,
        url=f"https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso={id_aviso}",
        lastmod="2026-06-12",
        titulo=titulo,
        caption=caption,
        fotos=[f"https://ws.avisosdeocasion.com/fotoswa/2/{id_aviso}/1/8/0/foto.jpg"] if foto else [],
    )


CASA = ("Se vende casa en CUMBRES", "CUMBRES - COLINAS 3 Recámaras 2baños 2Plantas "
        "195 Metros Cuadrados de Construcción 123 Metros Cuadrados Terreno $6,690,000 tel 81-1234-5678")
DEPTO = ("Se renta departamento en VALLE", "VALLE - DEL VALLE 2 Recámaras 2baños $25,800 amueblado")
DEPTO_SUBE = ("Se renta departamento en VALLE", "VALLE - DEL VALLE 2 Recámaras 2baños $27,500 amueblado")
TERRENO = ("Se vende terreno en APODACA", "APODACA - HUINALA 500 Metros Cuadrados Totales $4,500 por metro cuadrado")


def _simular_dia(monkeypatch, tmp_path, entradas, fecha, cfg=None):
    monkeypatch.setattr(evmod, "DIR_EVENTOS", tmp_path / "eventos")
    monkeypatch.setattr(runmod, "ClienteEducado", lambda **kw: ClienteFalso())
    monkeypatch.setattr(runmod, "descargar_sitemap", lambda cliente: entradas)
    return runmod.correr(cfg or {"detalle": "nunca"}, fecha=fecha)


def test_pipeline_tres_dias(monkeypatch, tmp_path):
    # Día 1: dos altas
    codigo = _simular_dia(monkeypatch, tmp_path,
                          [_entrada("100", *CASA), _entrada("200", *DEPTO)], "2026-06-12")
    assert codigo == 0

    # Día 2: el depto sube de precio, entra un terreno, la casa se da de baja
    codigo = _simular_dia(monkeypatch, tmp_path,
                          [_entrada("200", *DEPTO_SUBE), _entrada("300", *TERRENO)], "2026-06-13")
    assert codigo == 0

    # Día 3: el depto reaparece tras... no, sigue activo; la casa REAPARECE (realta)
    codigo = _simular_dia(monkeypatch, tmp_path,
                          [_entrada("100", *CASA), _entrada("200", *DEPTO_SUBE),
                           _entrada("300", *TERRENO)], "2026-06-14")
    assert codigo == 0

    # ---- reconstruir base y verificar todo ----
    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")

    casa = con.execute("SELECT zona, colonia, recamaras, m2_construccion, fecha_baja "
                       "FROM avisos WHERE id_aviso='100'").fetchone()
    assert casa[0] == "CUMBRES" and casa[1] == "COLINAS"
    assert casa[2] == 3 and casa[3] == 195
    assert casa[4] is None  # reapareció: ya no está dada de baja

    # El texto guardado no debe traer teléfonos
    desc = con.execute("SELECT descripcion FROM avisos WHERE id_aviso='100'").fetchone()[0]
    assert "1234" not in desc and "[tel]" in desc

    # Historial de precios del depto: 25,800 -> 27,500
    precios = [r[0] for r in con.execute(
        "SELECT precio FROM historial_precios WHERE id_aviso='200' ORDER BY fecha, precio")]
    assert 25_800 in precios and 27_500 in precios and len(precios) == 2

    # Terreno con precio por m2 reflejado en la vista de análisis
    fila = con.execute("SELECT precio_actual, precio_unidad, precio_m2_terreno "
                       "FROM analisis WHERE id_aviso='300'").fetchone()
    assert fila == (4_500, "m2", 4_500)

    # Corridas registradas (1 por día simulado... mismo día real => 1 fila upsert)
    assert con.execute("SELECT COUNT(*) FROM corridas").fetchone()[0] == 3

    # Foto del sitemap registrada
    assert con.execute("SELECT COUNT(*) FROM fotos WHERE id_aviso='100'").fetchone()[0] == 1


def test_guarda_aborta_ante_colapso(monkeypatch, tmp_path):
    # Sembrar 30 avisos activos
    entradas = [_entrada(str(i), *CASA) for i in range(1000, 1030)]
    assert _simular_dia(monkeypatch, tmp_path, entradas, "2026-06-12") == 0
    # Hoy el sitemap "se rompe" y trae solo 3 -> debe abortar con código 2
    assert _simular_dia(monkeypatch, tmp_path, entradas[:3], "2026-06-13") == 2
    # y NO debe haber registrado bajas
    con = dbmod.reconstruir(tmp_path / "avisos.db", dir_eventos=tmp_path / "eventos")
    bajas = con.execute("SELECT COUNT(*) FROM avisos WHERE fecha_baja IS NOT NULL").fetchone()[0]
    assert bajas == 0


def test_guarda_aborta_sitemap_vacio(monkeypatch, tmp_path):
    assert _simular_dia(monkeypatch, tmp_path, [_entrada("1", *CASA)], "2026-06-12") == 0
    assert _simular_dia(monkeypatch, tmp_path, [], "2026-06-13") == 2


# ------------------ filtro de precios placeholder ------------------
# El sitio sirve precios basura para algunos avisos ("a consultar" como $4, $450).
# La bitácora los conserva, pero la base derivada NO los registra: no son precios.
def test_precio_valido_pisos():
    assert dbmod.precio_valido(4, "total", "venta") is False
    assert dbmod.precio_valido(100_000, "total", "venta") is True
    assert dbmod.precio_valido(460, "total", "renta") is False
    assert dbmod.precio_valido(1_800, "total", "renta") is True
    assert dbmod.precio_valido(600, "total", "traspaso") is False
    assert dbmod.precio_valido(980, "m2", "venta") is True      # por m²: otra escala
    assert dbmod.precio_valido(None, "total", "venta") is True  # sin precio: nada que filtrar


def test_evento_trans_corrige_transaccion(tmp_path):
    # El evento `trans` (backfill, re-lee el detalle) corrige la transacción de un
    # aviso existente sin tocar su precio: el PH doble venta/renta pasa a venta.
    eventos = tmp_path / "eventos"
    evmod.anexar_eventos([
        {"e": "alta", "f": "2026-06-25", "id": "D",
         "datos": {"tipo_transaccion": "renta", "tipo_inmueble": "departamento",
                   "zona": "VALLE", "precio": 20_800_000, "precio_unidad": "total",
                   "url": "http://x/D"}, "fotos": []},
        {"e": "trans", "f": "2026-06-28", "id": "D", "trans": "venta"},
    ], dir_eventos=eventos)
    con = dbmod.reconstruir(tmp_path / "db.sqlite", dir_eventos=eventos)
    fila = con.execute(
        "SELECT tipo_transaccion, precio_actual FROM analisis WHERE id_aviso='D'").fetchone()
    assert fila == ("venta", 20_800_000)


def test_evento_attrs_corrige_atributos(tmp_path):
    # El evento `attrs` (backfill, re-lee el panel del detalle) corrige atributos
    # numéricos de un aviso existente (medio baño que el índice perdió). No toca
    # otras columnas ni acepta columnas fuera de la whitelist.
    eventos = tmp_path / "eventos"
    evmod.anexar_eventos([
        {"e": "alta", "f": "2026-06-25", "id": "D",
         "datos": {"tipo_transaccion": "venta", "tipo_inmueble": "departamento",
                   "zona": "VALLE", "banos": 3.0, "recamaras": 3.0,
                   "precio": 9_000_000, "precio_unidad": "total",
                   "url": "http://x/D"}, "fotos": []},
        {"e": "attrs", "f": "2026-06-28", "id": "D",
         "attrs": {"banos": 3.5, "tipo_transaccion": "renta"}},  # trans NO está en la whitelist
    ], dir_eventos=eventos)
    con = dbmod.reconstruir(tmp_path / "db.sqlite", dir_eventos=eventos)
    fila = con.execute(
        "SELECT banos, recamaras, tipo_transaccion FROM avisos WHERE id_aviso='D'").fetchone()
    assert fila[0] == 3.5            # corregido
    assert fila[1] == 3.0            # intacto
    assert fila[2] == "venta"        # la whitelist ignoró el intento de cambiar la transacción


def test_precio_placeholder_no_entra_a_analisis(tmp_path):
    def _alta(idv, precio, trans="venta"):
        return {"e": "alta", "f": "2026-06-25", "id": idv,
                "datos": {"tipo_transaccion": trans, "tipo_inmueble": "casa",
                          "precio": precio, "precio_unidad": "total",
                          "url": f"http://x/{idv}"}, "fotos": []}
    eventos = tmp_path / "eventos"
    evmod.anexar_eventos([_alta("1", 50), _alta("2", 2_000_000)], dir_eventos=eventos)
    con = dbmod.reconstruir(tmp_path / "db.sqlite", dir_eventos=eventos)
    # Ambos avisos existen; solo el de precio real entra a la vista 'analisis'.
    assert con.execute("SELECT COUNT(*) FROM avisos").fetchone()[0] == 2
    assert {r[0] for r in con.execute("SELECT id_aviso FROM analisis")} == {"2"}
    assert con.execute(
        "SELECT COUNT(*) FROM historial_precios WHERE id_aviso='1'").fetchone()[0] == 0


def test_precio_placeholder_luego_real_si_aparece(tmp_path):
    # Alta con placeholder y, después, un cambio a precio real: el aviso entra al
    # tablero solo cuando llega el precio válido.
    eventos = tmp_path / "eventos"
    evmod.anexar_eventos([
        {"e": "alta", "f": "2026-06-25", "id": "9",
         "datos": {"tipo_transaccion": "venta", "tipo_inmueble": "casa",
                   "precio": 4, "precio_unidad": "total", "url": "http://x/9"}, "fotos": []},
        {"e": "precio", "f": "2026-06-26", "id": "9", "precio": 3_500_000, "unidad": "total"},
    ], dir_eventos=eventos)
    con = dbmod.reconstruir(tmp_path / "db.sqlite", dir_eventos=eventos)
    fila = con.execute("SELECT precio_actual FROM analisis WHERE id_aviso='9'").fetchone()
    assert fila == (3_500_000,)   # el placeholder se ignoró; el real sí entró


def test_evento_desc_rellena_sin_pisar_ni_tocar_precio(tmp_path):
    # El evento `desc` (backfill) solo rellena la descripción de un aviso ya
    # existente: no toca precio/fechas y NO pisa una descripción ya presente.
    eventos = tmp_path / "eventos"
    evmod.anexar_eventos([
        {"e": "alta", "f": "2026-06-25", "id": "A",
         "datos": {"tipo_transaccion": "venta", "tipo_inmueble": "casa",
                   "precio": 3_500_000, "precio_unidad": "total",
                   "url": "http://x/A"}, "fotos": []},
        {"e": "alta", "f": "2026-06-25", "id": "B",
         "datos": {"tipo_transaccion": "venta", "tipo_inmueble": "casa",
                   "precio": 4_000_000, "precio_unidad": "total",
                   "descripcion": "ya tenía texto", "url": "http://x/B"}, "fotos": []},
        # A no tenía descripción -> se rellena; B sí -> se respeta.
        {"e": "desc", "f": "2026-06-27", "id": "A", "desc": "Lote industrial con bodega"},
        {"e": "desc", "f": "2026-06-27", "id": "B", "desc": "intento de pisar"},
    ], dir_eventos=eventos)
    con = dbmod.reconstruir(tmp_path / "db.sqlite", dir_eventos=eventos)
    fila_a = con.execute(
        "SELECT descripcion, fecha_primera_vista FROM avisos WHERE id_aviso='A'").fetchone()
    assert fila_a[0] == "Lote industrial con bodega"
    assert fila_a[1] == "2026-06-25"  # el desc NO tocó la fecha de alta
    # El precio sigue intacto y el aviso sigue en el tablero.
    assert con.execute("SELECT precio_actual FROM analisis WHERE id_aviso='A'").fetchone() == (3_500_000,)
    # B ya tenía descripción: el desc no la pisa.
    assert con.execute("SELECT descripcion FROM avisos WHERE id_aviso='B'").fetchone()[0] == "ya tenía texto"


# ---------- precio 'por m²' mal etiquetado (en realidad un total) ----------
def test_normaliza_precio_m2_alto_a_total():
    # El sitio mete el TOTAL en el campo de "precio por m²" ($7.5M/m²): se
    # reinterpreta como total. Un precio por m² real (bajo) se respeta.
    assert dbmod.normalizar_unidad(7_500_000, "m2") == (7_500_000, "total")
    assert dbmod.normalizar_unidad(17_500, "m2") == (17_500, "m2")       # per-m² real
    assert dbmod.normalizar_unidad(5_000_000, "total") == (5_000_000, "total")


def test_terreno_m2_mal_etiquetado_da_m2_correcto(tmp_path):
    # Terreno con "precio por m²" = total (7.5M) y 1000 m²: la vista debe dar
    # $/m² = 7,500 (reinterpretado a total), no 7,500,000.
    eventos = tmp_path / "eventos"
    evmod.anexar_eventos([{
        "e": "alta", "f": "2026-06-25", "id": "7",
        "datos": {"tipo_transaccion": "venta", "tipo_inmueble": "terreno",
                  "precio": 7_500_000, "precio_unidad": "m2", "m2_terreno": 1000.0,
                  "url": "http://x/7"}, "fotos": []}], dir_eventos=eventos)
    con = dbmod.reconstruir(tmp_path / "db.sqlite", dir_eventos=eventos)
    r = con.execute("SELECT precio_actual, precio_unidad, precio_m2_terreno "
                    "FROM analisis WHERE id_aviso='7'").fetchone()
    assert r[0] == 7_500_000 and r[1] == "total" and r[2] == 7500


def test_terreno_area_implausible_no_da_precio_m2(tmp_path):
    # Área absurda (8 m²) = captura mala del área: NO se computa $/m². Un terreno
    # con área plausible sí.
    eventos = tmp_path / "eventos"
    evmod.anexar_eventos([
        {"e": "alta", "f": "2026-06-25", "id": "a", "datos": {
            "tipo_transaccion": "venta", "tipo_inmueble": "terreno", "precio": 3_250_000,
            "precio_unidad": "total", "m2_terreno": 8.0, "url": "http://x/a"}, "fotos": []},
        {"e": "alta", "f": "2026-06-25", "id": "b", "datos": {
            "tipo_transaccion": "venta", "tipo_inmueble": "terreno", "precio": 3_250_000,
            "precio_unidad": "total", "m2_terreno": 500.0, "url": "http://x/b"}, "fotos": []},
    ], dir_eventos=eventos)
    con = dbmod.reconstruir(tmp_path / "db.sqlite", dir_eventos=eventos)
    assert con.execute("SELECT precio_m2_terreno FROM analisis WHERE id_aviso='a'").fetchone()[0] is None
    assert con.execute("SELECT precio_m2_terreno FROM analisis WHERE id_aviso='b'").fetchone()[0] == 6500
