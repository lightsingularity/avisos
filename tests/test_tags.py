"""Pruebas del catálogo de etiquetas (scraper/tags.py) y de su derivación en la
base + el filtro de analytics.

Las etiquetas se DERIVAN de la descripción al reconstruir; no se versionan. Los
patrones de uso de suelo son estrictos a propósito: un nombre de colonia
("Cumbres Residencial", "Plaza Comercial") NO debe etiquetar uso de suelo.
"""
import json
from pathlib import Path

import pandas as pd

import analytics as an
from scraper import tags as tagmod
from scraper.db import reconstruir


# ----------------------------- catálogo (unidad) -----------------------------
def test_etiquetas_industriales_y_amenidades():
    desc = ("Terreno industrial en parque industrial, con andén y rampa, "
            "subestación de 225 kVA. Acceso controlado con caseta de vigilancia.")
    tags = set(tagmod.etiquetas(desc))
    assert {"terreno industrial", "parque industrial", "anden/rampa",
            "subestacion electrica", "acceso controlado / caseta"} <= tags


def test_etiquetas_sin_acentos_y_mayusculas():
    # Insensible a tildes/mayúsculas: "DEMOLICIÓN" y "demolicion" igual.
    assert "para demoler" in tagmod.etiquetas("Casa PARA DEMOLER, excelente ubicación")
    assert "para demoler" in tagmod.etiquetas("se vende para demolicion total")


def test_uso_de_suelo_exige_calificador_no_nombre_de_colonia():
    # El nombre de colonia NO debe disparar uso de suelo.
    assert "uso de suelo residencial" not in tagmod.etiquetas("Casa en Cumbres Residencial 1")
    assert "uso de suelo comercial" not in tagmod.etiquetas("Local en Plaza Comercial Valle")
    # Con el calificador explícito, sí.
    assert "uso de suelo residencial" in tagmod.etiquetas("Lote con uso de suelo residencial")
    assert "uso de suelo comercial" in tagmod.etiquetas("Predio uso comercial sobre avenida")


def test_descripcion_vacia_no_truena():
    assert tagmod.etiquetas(None) == []
    assert tagmod.etiquetas("") == []
    assert tagmod.etiquetas("casa bonita sin atributos especiales") == []


# --------------------- derivación en la base + filtro ------------------------
def _escribir(tmp_path, eventos):
    d = tmp_path / "eventos"
    d.mkdir()
    with (d / "2026-06.jsonl").open("w", encoding="utf-8") as fh:
        for ev in eventos:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return d


def _alta(idv, descripcion):
    return {"e": "alta", "f": "2026-06-20", "id": idv,
            "datos": {"tipo_transaccion": "venta", "tipo_inmueble": "terreno",
                      "zona": "APODACA", "precio": 5_000_000, "precio_unidad": "total",
                      "descripcion": descripcion, "url": f"http://x/{idv}"}, "fotos": []}


def test_reconstruir_deriva_tabla_tags_y_analisis_trae_etiquetas(tmp_path):
    d = _escribir(tmp_path, [
        _alta("A", "Terreno industrial en parque industrial, amueblado."),
        _alta("B", "Bonito lote en esquina, todos los servicios."),
        _alta("C", "Casa sin nada particular."),
    ])
    con = reconstruir(tmp_path / "db.sqlite", dir_eventos=d)
    # Tabla tags poblada.
    tags_a = {r[0] for r in con.execute("SELECT tag FROM tags WHERE id_aviso='A'")}
    assert {"terreno industrial", "parque industrial", "amueblado"} <= tags_a
    assert con.execute("SELECT COUNT(*) FROM tags WHERE id_aviso='C'").fetchone()[0] == 0
    # La vista cargada adjunta la columna 'etiquetas' (unida por '|').
    df = an.cargar_analisis(con).set_index("id_aviso")
    assert "esquina" in df.loc["B", "etiquetas"].split("|")
    assert pd.isna(df.loc["C", "etiquetas"])  # sin etiquetas -> NULL/NaN
    # opciones expone el universo de etiquetas, ordenado y único.
    ops = an.opciones(con)
    assert "amueblado" in ops["etiquetas"] and "esquina" in ops["etiquetas"]


def test_filtrar_por_etiquetas_todas_y_alguna(tmp_path):
    d = _escribir(tmp_path, [
        _alta("A", "Terreno industrial en parque industrial."),  # industrial + parque
        _alta("B", "Terreno industrial sin más."),               # solo industrial
        _alta("C", "Lote en esquina."),                          # esquina
    ])
    con = reconstruir(tmp_path / "db.sqlite", dir_eventos=d)
    df = an.cargar_analisis(con)
    # 'todas' (AND): solo A cumple ambas.
    r = an.filtrar_por_etiquetas(df, ["terreno industrial", "parque industrial"])
    assert set(r["id_aviso"]) == {"A"}
    # 'alguna' (OR): A y B tienen industrial.
    r = an.filtrar_por_etiquetas(df, ["terreno industrial", "esquina"], modo="alguna")
    assert set(r["id_aviso"]) == {"A", "B", "C"}
    # Sin selección: no filtra.
    assert len(an.filtrar_por_etiquetas(df, [])) == len(df)
