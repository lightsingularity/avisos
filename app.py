"""Tablero de investigación de mercado — avisosdeocasion.com (Monterrey).

Diseñado para correr en Streamlit Community Cloud directamente desde el repo:
en cada arranque reconstruye la base SQLite a partir de la bitácora de eventos
(data/eventos/*.jsonl) que el scraper deja versionada en GitHub. No requiere tu
máquina local.

Local (opcional):  streamlit run app.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import analytics as an
from scraper.db import reconstruir
from scraper.events import DIR_EVENTOS

st.set_page_config(page_title="Mercado inmobiliario · Monterrey",
                   page_icon="🏠", layout="wide")

MXN = lambda x: "—" if x is None or pd.isna(x) else f"${x:,.0f}"


# ---------------------- datos (con caché por huella) ---------------------
def _huella() -> str:
    """Cadena que cambia cuando cambian los archivos de eventos -> invalida caché."""
    if not DIR_EVENTOS.exists():
        return "vacio"
    partes = [f"{p.name}:{p.stat().st_size}" for p in sorted(DIR_EVENTOS.glob("*.jsonl"))]
    return "|".join(partes) or "vacio"


@st.cache_resource(show_spinner="Reconstruyendo base desde la bitácora…")
def _conexion(huella: str):
    ruta = Path(tempfile.gettempdir()) / "avisos_dashboard.db"
    return reconstruir(ruta)


@st.cache_data(show_spinner=False)
def _datos(huella: str):
    con = _conexion(huella)
    return an.cargar_analisis(con), an.cargar_historial(con), an.opciones(con)


huella = _huella()
df_todo, hist_todo, ops = _datos(huella)

# ------------------------------ barra lateral ---------------------------
st.sidebar.title("🏠 Mercado MTY")
st.sidebar.caption("Datos propios capturados de avisosdeocasion.com")

if st.sidebar.button("🔄 Recargar datos"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()

if df_todo.empty:
    st.title("Aún no hay datos")
    st.info(
        "La bitácora de eventos está vacía. Ejecuta el scraper (workflow "
        "**Scrape diario** en la pestaña Actions, o `python -m scraper` en local) "
        "y vuelve a cargar. Tras la primera corrida verás aquí miles de avisos."
    )
    st.stop()

st.sidebar.markdown("### Filtros")
trans = st.sidebar.selectbox("Transacción", ["(todas)"] + ops["transacciones"])
trans = None if trans == "(todas)" else trans
tipos = st.sidebar.multiselect("Tipo de inmueble", ops["tipos"])
zonas = st.sidebar.multiselect("Zona", ops["zonas"])
# Las colonias se acotan a las zonas elegidas, si hay
colonias_disp = ops["colonias"]
if zonas:
    colonias_disp = sorted(df_todo[df_todo["zona"].isin(zonas)]["colonia"]
                           .dropna().unique().tolist())
colonias = st.sidebar.multiselect("Colonia", colonias_disp)
busqueda = st.sidebar.text_input(
    "Buscar en descripción",
    placeholder="p. ej. industrial, estacionamiento",
    help="Busca dentro del texto libre del anuncio (no tiene columna propia).",
)
etiquetas = st.sidebar.multiselect(
    "Etiquetas", ops.get("etiquetas", []),
    help="Atributos detectados en el texto del anuncio (p. ej. acceso controlado, "
         "amueblado, terreno industrial). Se piden TODAS las elegidas.",
)

df = an.aplicar_filtros(df_todo, trans, tipos, zonas, colonias)
df = an.buscar_descripcion(df, busqueda)
df = an.filtrar_por_etiquetas(df, etiquetas)
ids = set(df["id_aviso"])
hist = hist_todo[hist_todo["id_aviso"].isin(ids)]

# ------------------------------ encabezado -------------------------------
st.title("Investigación de mercado inmobiliario")
ultima = df_todo["fecha_ultima_vista"].max()
st.caption(f"{len(df_todo):,} avisos en el histórico · última captura: {ultima} · "
           f"segmento filtrado: {len(df):,} avisos")

if df.empty:
    st.warning("Ningún aviso coincide con los filtros. Afloja algún criterio.")
    st.stop()

r = an.resumen_segmento(df)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Avisos en segmento", f"{r['n_avisos']:,}")
c2.metric("Mediana precio total", MXN(r["mediana_precio"]))
c3.metric("Mediana $/m² construcción", MXN(r["mediana_m2_construccion"]))
c4.metric("Mediana $/m² terreno", MXN(r["mediana_m2_terreno"]))

st.divider()

# ------------------------------ pestañas ---------------------------------
tab_dist, tab_tend, tab_tom, tab_comp, tab_datos = st.tabs(
    ["Distribución de precios", "Tendencias", "Tiempo en mercado",
     "Comparar zonas", "Datos / Exportar"]
)

# --- Distribución de precios ---
with tab_dist:
    tot = an.solo_total(df)
    if tot.empty:
        st.info("El segmento no tiene avisos con precio total (¿solo terrenos por m²?). "
                "Revisa la pestaña Tendencias con la métrica de $/m² de terreno.")
    else:
        p = tot["precio_actual"].dropna()
        lo, hi = p.quantile(0.01), p.quantile(0.99)
        fig = px.histogram(tot[(p >= lo) & (p <= hi)], x="precio_actual", nbins=40,
                           labels={"precio_actual": "Precio (MXN)"})
        fig.update_layout(yaxis_title="Avisos", bargap=0.05,
                          margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)
        a1, a2, a3 = st.columns(3)
        a1.metric("Mínimo (p01)", MXN(lo))
        a2.metric("Mediana", MXN(p.median()))
        a3.metric("Máximo (p99)", MXN(hi))
        st.caption("Recortado a percentiles 1–99 para legibilidad; las métricas de "
                   "arriba usan el segmento completo.")

# --- Tendencias ---
with tab_tend:
    modo = st.radio(
        "Métrica",
        ["total", "m2_construccion", "m2_terreno"],
        format_func={"total": "Precio total",
                     "m2_construccion": "Precio por m² (construcción)",
                     "m2_terreno": "Precio por m² (terreno)"}.get,
        horizontal=True,
    )
    serie = an.serie_mensual(hist, modo)
    if len(serie) < 1:
        st.info("Sin datos suficientes para esta métrica todavía.")
    else:
        fig = px.line(serie, x="mes", y="mediana", markers=True,
                      labels={"mes": "Mes", "mediana": "Mediana (MXN)"})
        fig.update_layout(margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Mediana mensual de los precios observados en el segmento. "
                   "Las tendencias ganan sentido conforme se acumulan semanas de captura.")
        with st.expander("Ver tabla mensual (avisos por mes)"):
            st.dataframe(serie.rename(columns={"mes": "Mes", "mediana": "Mediana",
                                               "n": "Avisos"}), use_container_width=True)

# --- Tiempo en mercado y cambios de precio ---
with tab_tom:
    tom = an.stats_tiempo_en_mercado(df)
    camb = an.stats_cambios_precio(hist)
    c1, c2, c3 = st.columns(3)
    c1.metric("Activos", f"{tom.get('n_activos', 0):,}")
    c2.metric("Dados de baja", f"{tom.get('n_cerrados', 0):,}")
    md = tom.get("mediana_dias_cerrados")
    c3.metric("Mediana días hasta baja", "—" if md is None else f"{md:.0f} días")
    if tom.get("mediana_dias_activos") is not None:
        st.caption(f"Los avisos activos llevan, en mediana, "
                   f"{tom['mediana_dias_activos']:.0f} días publicados.")
    st.markdown("#### Cambios de precio")
    d1, d2, d3 = st.columns(3)
    d1.metric("Avisos con bajada de precio", f"{camb['con_baja']:,}")
    d2.metric("Avisos con alza", f"{camb.get('con_alza', 0):,}")
    mb = camb.get("mediana_baja_pct")
    d3.metric("Bajada mediana", "—" if mb is None else f"{mb:.1f}%")
    st.caption("El tiempo en mercado y los cambios de precio se vuelven más ricos "
               "con el paso de los días, al observar qué avisos bajan de precio o desaparecen.")

# --- Comparar zonas ---
with tab_comp:
    st.markdown("Compara dos zonas (o colonias) dentro del segmento filtrado.")
    dim = st.radio("Dimensión", ["zona", "colonia"], horizontal=True)
    valores = sorted(df[dim].dropna().unique().tolist())
    if len(valores) < 2:
        st.info(f"Hacen falta al menos dos {dim}s en el segmento para comparar. "
                "Quita filtros de zona/colonia o amplía el tipo de inmueble.")
    else:
        cc1, cc2 = st.columns(2)
        a = cc1.selectbox(f"{dim.capitalize()} A", valores, index=0)
        b = cc2.selectbox(f"{dim.capitalize()} B", valores, index=1)
        if a == b:
            st.warning("Elige dos valores distintos.")
        else:
            tabla = an.comparar(df, dim, a, b)
            st.dataframe(tabla.style.format(lambda v: MXN(v) if isinstance(v, (int, float))
                                            and v is not None else v),
                         use_container_width=True)

# --- Datos / Exportar ---
with tab_datos:
    cols = ["id_aviso", "tipo_transaccion", "tipo_inmueble", "zona", "colonia",
            "precio_actual", "precio_unidad", "precio_m2_construccion",
            "precio_m2_terreno", "recamaras", "banos", "m2_construccion",
            "m2_terreno", "dias_en_mercado", "num_cambios_precio",
            "fecha_primera_vista", "fecha_baja", "url", "etiquetas", "descripcion"]
    vista = df[cols].sort_values("precio_actual", ascending=False)
    st.dataframe(vista, use_container_width=True, height=460)
    st.download_button(
        "⬇️ Descargar CSV del segmento",
        vista.to_csv(index=False).encode("utf-8"),
        file_name="segmento_mercado.csv",
        mime="text/csv",
    )
