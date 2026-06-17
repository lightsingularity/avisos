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
