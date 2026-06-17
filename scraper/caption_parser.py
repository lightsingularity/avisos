"""Parseo de <image:title> y <image:caption> del sitemap a campos estructurados.

Ejemplos reales que este módulo debe entender:

  título:  "Se vende departamento en CUMBRES MADEIRA"
  caption: "CUMBRES - CUMBRES MADEIRA 3 Recámaras 3baños 1Planta 89 Metros
            Cuadrados de Construcción $5,200,000 DEPARTAMENTOS CON ALTA PLUSVALIA..."

  caption: "CENTRO - GARZA NIETO 900 Metros Cuadrados totales de terreno 900 Metros
            Cuadrados de bodega 30 Metros Cuadrados de Oficina $64,900 más IVA, ..."

  caption: "CARRETERA NACIONAL - LAS VISITAS DEL VERGEL 1000 Metros Cuadrados Totales
            26 metros de frente $7,500 por metro cuadrado 81-1126-8716."

  caption: "SANTA CATARINA - LA BANDA 3 Recámaras 1 1/2baños $40,000 81-1680-2755."
"""
from __future__ import annotations

import re
from typing import Any

# ---------- transacción y tipo de inmueble a partir del título ----------
_TRANSACCIONES = [
    (re.compile(r"\b(se\s+vende|venta\s+de)\b", re.I), "venta"),
    (re.compile(r"\b(se\s+renta|renta\s+de)\b", re.I), "renta"),
    (re.compile(r"\b(se\s+traspasa|traspaso\s+de)\b", re.I), "traspaso"),
]
_TIPOS = [
    (re.compile(r"finca\s+campestre|quinta", re.I), "finca_campestre"),
    (re.compile(r"bodegas?\s+y\s+naves|nave\s+industrial|bodega", re.I), "bodega_nave"),
    (re.compile(r"locales?\s+y\s+oficinas?|local\b|oficina", re.I), "local_oficina"),
    (re.compile(r"departamento", re.I), "departamento"),
    (re.compile(r"\bcasa\b", re.I), "casa"),
    (re.compile(r"terreno", re.I), "terreno"),
    (re.compile(r"edificio", re.I), "edificio"),
    (re.compile(r"rancho", re.I), "rancho"),
]


def clasificar_titulo(titulo: str | None) -> tuple[str | None, str | None]:
    """Devuelve (tipo_transaccion, tipo_inmueble) a partir del título del sitemap."""
    if not titulo:
        return None, None
    trans = next((v for rx, v in _TRANSACCIONES if rx.search(titulo)), None)
    tipo = next((v for rx, v in _TIPOS if rx.search(titulo)), None)
    return trans, tipo


# ---------- campos numéricos del caption ----------
def _num(s: str) -> float:
    return float(s.replace(",", "").rstrip("."))


_RXF: dict[str, re.Pattern] = {
    "recamaras":       re.compile(r"(\d+)\s*Rec[áa]maras?", re.I),
    "plantas":         re.compile(r"(\d+)\s*Plantas?", re.I),
    "m2_construccion": re.compile(r"([\d.,]+)\s*Metros\s+Cuadrados\s+de\s+Construcci", re.I),
    "m2_bodega":       re.compile(r"([\d.,]+)\s*Metros\s+Cuadrados\s+de\s+bodega", re.I),
    "m2_oficina":      re.compile(r"([\d.,]+)\s*Metros\s+Cuadrados\s+de\s+Oficina", re.I),
    "metros_frente":   re.compile(r"([\d.,]+)\s*metros?\s+de\s+frente", re.I),
    "hectareas":       re.compile(r"([\d.,]+)\s*hect[áa]reas?", re.I),
}
# Terreno: "Metros Cuadrados" NO seguido de construcción/bodega/oficina.
# El lookahead negativo descarta esas variantes; lo que queda es terreno.
_RX_TERRENO = re.compile(
    r"([\d.,]+)\s*Metros\s+Cuadrados"
    r"(?!\s*de\s*(?:Construcci|bodega|Oficina))",
    re.I,
)
# Baños: "3baños", "2.5 baños", "1 1/2baños"
_RX_BANOS = re.compile(r"(\d+(?:\.\d+)?(?:\s+1/2)?)\s*ba[ñn]os?", re.I)
_RX_PRECIO = re.compile(r"\$\s*([\d.,]+)")
_RX_POR_M2 = re.compile(r"\$\s*[\d.,]+\s*(?:por\s+metro\s+cuadrado|x\s*m2)", re.I)
_RX_MAS_IVA = re.compile(r"m[áa]s\s+IVA", re.I)


def parsear_caption(caption: str | None) -> dict[str, Any]:
    """Extrae campos numéricos, precio y ubicación (zona, colonia) del caption."""
    out: dict[str, Any] = {}
    if not caption:
        return out
    posiciones: list[int] = []

    for campo, rx in _RXF.items():
        m = rx.search(caption)
        if m:
            out[campo] = _num(m.group(1))
            posiciones.append(m.start())

    m = _RX_TERRENO.search(caption)
    if m:
        out["m2_terreno"] = _num(m.group(1))
        posiciones.append(m.start())

    m = _RX_BANOS.search(caption)
    if m:
        v = m.group(1)
        out["banos"] = float(v.split()[0]) + 0.5 if "1/2" in v else float(v)
        posiciones.append(m.start())

    m = _RX_PRECIO.search(caption)
    if m:
        out["precio"] = int(round(_num(m.group(1))))
        out["precio_unidad"] = "m2" if _RX_POR_M2.search(caption) else "total"
        out["mas_iva"] = bool(_RX_MAS_IVA.search(caption))
        posiciones.append(m.start())

    # ---- ubicación: todo lo que está antes del primer campo detectado ----
    corte = min(posiciones) if posiciones else len(caption)
    ubic = caption[:corte].strip(" .-\u00b7")
    if " - " in ubic:
        zona, colonia = ubic.split(" - ", 1)
        out["zona"], out["colonia"] = zona.strip(), colonia.strip(" .")
    elif ubic:
        out["zona"] = ubic
    return out


def parsear_entrada(titulo: str | None, caption: str | None) -> dict[str, Any]:
    """Combina título + caption en un solo dict de campos."""
    trans, tipo = clasificar_titulo(titulo)
    campos = parsear_caption(caption)
    if trans:
        campos["tipo_transaccion"] = trans
    if tipo:
        campos["tipo_inmueble"] = tipo
    return campos
