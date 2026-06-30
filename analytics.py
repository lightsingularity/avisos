"""Capa de análisis: consultas y agregaciones sobre la base SQLite.

Separada de la interfaz (app.py) para poder probarla sin Streamlit. Todas las
funciones devuelven DataFrames o dicts; ninguna toca la UI. Precios en MXN.

Convención de precios:
- Los avisos con precio_unidad == 'total' tienen precio_actual = precio total.
- Los avisos con precio_unidad == 'm2' (típico en terrenos) tienen precio_actual
  expresado POR metro cuadrado. Para no mezclar peras con manzanas, las vistas
  de "precio total" usan solo unidad 'total'; los de unidad 'm2' aparecen en la
  vista de precio por m² de terreno.
"""
from __future__ import annotations

import sqlite3
import pandas as pd

# Tipos donde "precio por m²" se entiende sobre construcción vs. sobre terreno.
# Definición única en scraper.db (la usa también la vista `analisis`).
from scraper.db import MIN_M2_TERRENO, TIPOS_CONSTRUCCION, TIPOS_TERRENO


# ----------------------------- carga -----------------------------------
def cargar_analisis(con: sqlite3.Connection) -> pd.DataFrame:
    """La vista `analisis`: una fila por aviso con precio actual y derivados.

    Adjunta `etiquetas`: las tags derivadas de la descripción, unidas por '|'
    (una sola cadena por aviso) para filtrar/mostrar sin multiplicar las filas."""
    return pd.read_sql_query(
        "SELECT analisis.*, "
        "(SELECT group_concat(tag, '|') FROM tags "
        "  WHERE tags.id_aviso = analisis.id_aviso) AS etiquetas "
        "FROM analisis",
        con,
    )


def cargar_historial(con: sqlite3.Connection) -> pd.DataFrame:
    """Cada punto de precio observado, con atributos del aviso para agregaciones."""
    return pd.read_sql_query(
        """SELECT h.id_aviso, h.fecha, h.precio, h.unidad, h.moneda,
                  a.tipo_transaccion, a.tipo_inmueble, a.zona, a.colonia,
                  a.m2_construccion, a.m2_terreno
             FROM historial_precios h
             JOIN avisos a ON a.id_aviso = h.id_aviso""",
        con,
        parse_dates=["fecha"],
    )


def opciones(con: sqlite3.Connection) -> dict[str, list[str]]:
    """Valores distintos para poblar los filtros de la interfaz."""
    def distintos(col: str) -> list[str]:
        rows = con.execute(
            f"SELECT DISTINCT {col} FROM avisos "
            f"WHERE {col} IS NOT NULL AND {col} <> '' ORDER BY {col}"
        ).fetchall()
        return [r[0] for r in rows]
    etiquetas = [r[0] for r in con.execute(
        "SELECT DISTINCT tag FROM tags ORDER BY tag").fetchall()]
    return {
        "transacciones": distintos("tipo_transaccion"),
        "tipos": distintos("tipo_inmueble"),
        "zonas": distintos("zona"),
        "colonias": distintos("colonia"),
        "etiquetas": etiquetas,
    }


# ----------------------------- filtros ----------------------------------
def aplicar_filtros(df: pd.DataFrame, transaccion=None, tipos=None,
                    zonas=None, colonias=None) -> pd.DataFrame:
    """Subconjunto del DataFrame según los filtros activos (None / vacío = todos)."""
    out = df
    if transaccion:
        out = out[out["tipo_transaccion"] == transaccion]
    if tipos:
        out = out[out["tipo_inmueble"].isin(tipos)]
    if zonas:
        out = out[out["zona"].isin(zonas)]
    if colonias:
        out = out[out["colonia"].isin(colonias)]
    return out


def solo_total(df: pd.DataFrame) -> pd.DataFrame:
    """Avisos con precio total (excluye los listados por m²)."""
    return df[df["precio_unidad"] == "total"]


def buscar_descripcion(df: pd.DataFrame, palabra: str) -> pd.DataFrame:
    """Avisos cuya descripción contiene `palabra` (insensible a may/min).

    Para encontrar detalles que no tienen columna propia (lote industrial,
    cajones de estacionamiento, amenidades…) y solo viven en el texto libre.
    """
    if not palabra:
        return df
    return df[df["descripcion"].fillna("").str.contains(palabra, case=False, regex=False)]


def filtrar_por_etiquetas(df: pd.DataFrame, seleccion, modo: str = "todas") -> pd.DataFrame:
    """Avisos que tienen las etiquetas seleccionadas (None/vacío = sin filtrar).

    modo 'todas' (AND: las cumple todas) o 'alguna' (OR: al menos una). Las
    etiquetas viven en la columna `etiquetas` unidas por '|'.
    """
    if not seleccion:
        return df
    sel = set(seleccion)
    conjuntos = (df["etiquetas"].fillna("")
                 .apply(lambda s: {t for t in s.split("|") if t}))
    if modo == "alguna":
        mask = conjuntos.apply(lambda s: bool(s & sel))
    else:
        mask = conjuntos.apply(lambda s: sel <= s)
    return df[mask]


# ----------------------------- moneda -----------------------------------
def por_moneda(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Divide el DataFrame por moneda (MXN, USD…). Nunca se mezclan monedas en una
    misma mediana: el sitio cotiza muchos terrenos en USD y un total mezclado no
    significa nada. Devuelve {moneda: subDataFrame}, MXN primero."""
    col = "precio_moneda" if "precio_moneda" in df.columns else "moneda"
    if col not in df.columns:
        return {"MXN": df}
    monedas = sorted(df[col].dropna().unique(), key=lambda m: (m != "MXN", m))
    return {m: df[df[col] == m] for m in monedas}


# --------------------------- agregaciones --------------------------------
def serie_mensual(hist: pd.DataFrame, modo: str = "total", moneda: str = "MXN") -> pd.DataFrame:
    """Mediana mensual de precio. modo: 'total' | 'm2_construccion' | 'm2_terreno'.

    Una sola `moneda` (no se mezclan en un eje). Devuelve [mes, mediana, n].
    """
    if hist.empty:
        return pd.DataFrame(columns=["mes", "mediana", "n"])
    h = hist.copy()
    if "moneda" in h.columns:
        h = h[h["moneda"] == moneda]
        if h.empty:
            return pd.DataFrame(columns=["mes", "mediana", "n"])

    if modo == "total":
        h = h[h["unidad"] == "total"]
        h["valor"] = h["precio"]
    elif modo == "m2_construccion":
        h = h[(h["unidad"] == "total") & (h["m2_construccion"] > 0)
              & (h["tipo_inmueble"].isin(TIPOS_CONSTRUCCION))]
        h["valor"] = h["precio"] / h["m2_construccion"]
    elif modo == "m2_terreno":
        # Solo inmuebles de tipo terreno, para no mezclar con casas.
        h = h[h["tipo_inmueble"].isin(TIPOS_TERRENO)]
        # unidad 'm2' ya viene por metro; unidad 'total' se divide entre el terreno
        directo = h[h["unidad"] == "m2"].copy()
        directo["valor"] = directo["precio"]
        calc = h[(h["unidad"] == "total") & (h["m2_terreno"] >= MIN_M2_TERRENO)].copy()
        calc["valor"] = calc["precio"] / calc["m2_terreno"]
        h = pd.concat([directo, calc], ignore_index=True)
    else:
        raise ValueError(f"modo desconocido: {modo}")

    if h.empty:
        return pd.DataFrame(columns=["mes", "mediana", "n"])
    h["mes"] = h["fecha"].dt.to_period("M").dt.to_timestamp()
    g = h.groupby("mes")["valor"].agg(mediana="median", n="count").reset_index()
    return g.sort_values("mes").reset_index(drop=True)


def stats_tiempo_en_mercado(df: pd.DataFrame) -> dict:
    """Estadísticas de días en mercado, separando activos de ya dados de baja."""
    if df.empty:
        return {"n": 0}
    activos = df[df["fecha_baja"].isna()]
    cerrados = df[df["fecha_baja"].notna()]
    d_cerr = cerrados["dias_en_mercado"].dropna()
    d_act = activos["dias_en_mercado"].dropna()
    return {
        "n": int(len(df)),
        "n_activos": int(len(activos)),
        "n_cerrados": int(len(cerrados)),
        "mediana_dias_cerrados": float(d_cerr.median()) if len(d_cerr) else None,
        "mediana_dias_activos": float(d_act.median()) if len(d_act) else None,
        "p25_cerrados": float(d_cerr.quantile(0.25)) if len(d_cerr) else None,
        "p75_cerrados": float(d_cerr.quantile(0.75)) if len(d_cerr) else None,
    }


def stats_cambios_precio(hist: pd.DataFrame, moneda: str = "MXN") -> dict:
    """Comparación primer vs último precio por aviso (solo unidad 'total', una moneda)."""
    h = hist[hist["unidad"] == "total"]
    if "moneda" in h.columns:
        h = h[h["moneda"] == moneda]
    h = h.sort_values(["id_aviso", "fecha"])
    if h.empty:
        return {"n": 0, "con_cambio": 0, "con_baja": 0,
                "mediana_baja_pct": None, "mediana_baja_mxn": None}
    primero = h.groupby("id_aviso")["precio"].first()
    ultimo = h.groupby("id_aviso")["precio"].last()
    cont = h.groupby("id_aviso")["precio"].count()
    delta = (ultimo - primero)
    pct = (delta / primero * 100)
    con_cambio = int((cont > 1).sum())
    bajas = delta[delta < 0]
    return {
        "n": int(len(primero)),
        "con_cambio": con_cambio,
        "con_baja": int((delta < 0).sum()),
        "con_alza": int((delta > 0).sum()),
        "mediana_baja_pct": float(pct[delta < 0].median()) if len(bajas) else None,
        "mediana_baja_mxn": float(bajas.median()) if len(bajas) else None,
    }


def resumen_segmento(df: pd.DataFrame) -> dict:
    """Tarjetas de resumen para el segmento filtrado actual."""
    tot = solo_total(df)
    pm2c = df["precio_m2_construccion"].dropna()
    pm2t = df["precio_m2_terreno"].dropna()
    return {
        "n_avisos": int(len(df)),
        "mediana_precio": float(tot["precio_actual"].median()) if len(tot) else None,
        "mediana_m2_construccion": float(pm2c.median()) if len(pm2c) else None,
        "mediana_m2_terreno": float(pm2t.median()) if len(pm2t) else None,
    }


def comparar(df: pd.DataFrame, dim: str, a: str, b: str) -> pd.DataFrame:
    """Tabla comparativa de dos valores de una dimensión ('zona' o 'colonia')."""
    filas = []
    etiquetas = {
        "n_avisos": "Avisos",
        "mediana_precio": "Mediana precio total (MXN)",
        "mediana_m2_construccion": "Mediana $/m² construcción",
        "mediana_m2_terreno": "Mediana $/m² terreno",
    }
    res = {valor: resumen_segmento(df[df[dim] == valor]) for valor in (a, b)}
    for clave, etiqueta in etiquetas.items():
        filas.append({"Métrica": etiqueta, a: res[a][clave], b: res[b][clave]})
    return pd.DataFrame(filas).set_index("Métrica")
