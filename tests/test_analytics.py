"""Pruebas de la capa de análisis (analytics.py) con una bitácora multi-mes."""
import json
from pathlib import Path

import pandas as pd
import pytest

import analytics as an
from scraper.db import reconstruir


def _escribir_eventos(tmp_path: Path, eventos: list[dict]) -> Path:
    d = tmp_path / "eventos"
    d.mkdir()
    por_mes: dict[str, list[dict]] = {}
    for ev in eventos:
        por_mes.setdefault(ev["f"][:7], []).append(ev)
    for mes, lote in por_mes.items():
        with (d / f"{mes}.jsonl").open("w", encoding="utf-8") as fh:
            for ev in lote:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return d


def _alta(fecha, id_, **datos):
    return {"e": "alta", "f": fecha, "id": id_, "datos": datos, "fotos": []}


@pytest.fixture
def con(tmp_path):
    """Escenario: 2 casas en CUMBRES (una baja de precio, una se da de baja),
    1 casa en VALLE, 1 terreno en APODACA listado por m². Tres meses de eventos."""
    eventos = [
        # --- mayo ---
        _alta("2026-05-02", "C1", tipo_transaccion="venta", tipo_inmueble="casa",
              zona="CUMBRES", colonia="COLINAS", recamaras=3, banos=2.5,
              m2_construccion=200, m2_terreno=150, precio=6_000_000,
              precio_unidad="total"),
        _alta("2026-05-02", "C2", tipo_transaccion="venta", tipo_inmueble="casa",
              zona="CUMBRES", colonia="RENACIMIENTO", recamaras=4, banos=3,
              m2_construccion=300, m2_terreno=200, precio=9_000_000,
              precio_unidad="total"),
        _alta("2026-05-10", "V1", tipo_transaccion="venta", tipo_inmueble="casa",
              zona="VALLE", colonia="DEL VALLE", recamaras=3, banos=2,
              m2_construccion=180, m2_terreno=160, precio=8_400_000,
              precio_unidad="total"),
        _alta("2026-05-15", "T1", tipo_transaccion="venta", tipo_inmueble="terreno",
              zona="APODACA", colonia="HUINALA", m2_terreno=500, precio=4_500,
              precio_unidad="m2", descripcion="Excelente lote INDUSTRIAL, listo para construir"),
        # --- junio: C1 baja de precio; C2 se da de baja ---
        {"e": "precio", "f": "2026-06-05", "id": "C1", "precio": 5_400_000, "unidad": "total"},
        {"e": "baja", "f": "2026-06-20", "id": "C2"},
    ]
    d = _escribir_eventos(tmp_path, eventos)
    return reconstruir(tmp_path / "db.sqlite", dir_eventos=d)


def test_carga_y_opciones(con):
    df = an.cargar_analisis(con)
    assert len(df) == 4
    ops = an.opciones(con)
    assert set(ops["transacciones"]) == {"venta"}
    assert "CUMBRES" in ops["zonas"] and "APODACA" in ops["zonas"]
    assert "casa" in ops["tipos"] and "terreno" in ops["tipos"]


def test_filtros(con):
    df = an.cargar_analisis(con)
    cumbres = an.aplicar_filtros(df, transaccion="venta", tipos=["casa"], zonas=["CUMBRES"])
    assert len(cumbres) == 2
    assert set(cumbres["id_aviso"]) == {"C1", "C2"}


def test_buscar_descripcion(con):
    df = an.cargar_analisis(con)
    # Insensible a mayúsculas/minúsculas
    encontrados = an.buscar_descripcion(df, "industrial")
    assert set(encontrados["id_aviso"]) == {"T1"}
    # Sin coincidencias -> vacío; sin palabra -> no filtra (devuelve todo)
    assert an.buscar_descripcion(df, "alberca").empty
    assert len(an.buscar_descripcion(df, "")) == len(df)
    # Avisos sin descripción (NaN) no truenan la búsqueda
    assert "C1" not in set(an.buscar_descripcion(df, "industrial")["id_aviso"])


def test_resumen_segmento_excluye_precio_por_m2(con):
    df = an.cargar_analisis(con)
    # Mediana de precio total NO debe contaminarse con el terreno (precio por m²)
    r = an.resumen_segmento(df)
    # precios totales: C1=5.4M, C2=9M, V1=8.4M -> mediana 8.4M
    assert r["mediana_precio"] == 8_400_000
    # $/m² construcción presente solo para las casas
    assert r["mediana_m2_construccion"] is not None


def test_serie_mensual_total(con):
    hist = an.cargar_historial(con)
    serie = an.serie_mensual(hist, "total")
    meses = serie["mes"].dt.strftime("%Y-%m").tolist()
    assert "2026-05" in meses and "2026-06" in meses
    # En mayo hay 3 precios totales (C1 6M, C2 9M, V1 8.4M) -> mediana 8.4M
    may = serie[serie["mes"].dt.strftime("%Y-%m") == "2026-05"].iloc[0]
    assert may["mediana"] == 8_400_000 and may["n"] == 3
    # En junio solo cambió C1 -> 5.4M
    jun = serie[serie["mes"].dt.strftime("%Y-%m") == "2026-06"].iloc[0]
    assert jun["mediana"] == 5_400_000 and jun["n"] == 1


def test_serie_mensual_m2_terreno_usa_precio_directo(con):
    hist = an.cargar_historial(con)
    serie = an.serie_mensual(hist, "m2_terreno")
    # El terreno T1 está listado a $4,500/m² (unidad m2) -> aparece directo
    assert (serie["mediana"] == 4_500).any()


def test_tiempo_en_mercado(con):
    df = an.cargar_analisis(con)
    tom = an.stats_tiempo_en_mercado(df)
    assert tom["n_cerrados"] == 1   # C2 dado de baja
    assert tom["n_activos"] == 3
    assert tom["mediana_dias_cerrados"] is not None  # C2: ~49 días


def test_cambios_precio(con):
    hist = an.cargar_historial(con)
    camb = an.stats_cambios_precio(hist)
    assert camb["con_baja"] == 1            # C1 bajó de 6M a 5.4M
    assert camb["mediana_baja_pct"] == pytest.approx(-10.0, abs=0.01)
    assert camb["mediana_baja_mxn"] == pytest.approx(-600_000)


def test_precio_m2_respeta_tipo_inmueble(tmp_path):
    """El $/m² por fila respeta el tipo: terreno -> $/m² terreno; construcción ->
    $/m² construcción. Un departamento con m2_terreno NO debe producir $/m² de
    terreno (métrica sin sentido que aparecía en el tablero)."""
    eventos = [
        _alta("2026-06-01", "D1", tipo_transaccion="venta",
              tipo_inmueble="departamento", zona="VALLE",
              m2_construccion=100, m2_terreno=485, precio=8_000_000,
              precio_unidad="total"),
        _alta("2026-06-01", "T1", tipo_transaccion="venta",
              tipo_inmueble="terreno", zona="APODACA",
              m2_terreno=500, precio=10_000_000, precio_unidad="total"),
    ]
    d = _escribir_eventos(tmp_path, eventos)
    con = reconstruir(tmp_path / "db.sqlite", dir_eventos=d)
    df = an.cargar_analisis(con).set_index("id_aviso")
    # Departamento: $/m² construcción sí; $/m² terreno NO (aunque tenga m2_terreno).
    assert df.loc["D1", "precio_m2_construccion"] == 80_000
    assert pd.isna(df.loc["D1", "precio_m2_terreno"])
    # Terreno: $/m² terreno sí; $/m² construcción NO.
    assert df.loc["T1", "precio_m2_terreno"] == 20_000
    assert pd.isna(df.loc["T1", "precio_m2_construccion"])


def test_comparar_zonas(con):
    df = an.cargar_analisis(con)
    tabla = an.comparar(df, "zona", "CUMBRES", "VALLE")
    assert "CUMBRES" in tabla.columns and "VALLE" in tabla.columns
    # VALLE tiene 1 aviso; CUMBRES tiene 2
    assert tabla.loc["Avisos", "VALLE"] == 1
    assert tabla.loc["Avisos", "CUMBRES"] == 2
