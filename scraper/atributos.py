"""Atributos numéricos y precio en formato "chips".

Las páginas de detalle y las tarjetas de las páginas de categoría muestran los
mismos atributos con el mismo formato:

    2 Plantas | 3 Rec. | 3.5 Bñ. | 228 m2 Const. | 152 m2 Terr.
    12 m Fren. | 40 m2 Ofc. | 900 m2 Bod.

Estas expresiones regulares vivían en detail_parser.py; se factorizaron aquí
para que detail_parser.py (detalle) e indice.py (tarjetas de categoría)
compartan EXACTAMENTE las mismas reglas sin duplicarlas.
"""
from __future__ import annotations

import re
from typing import Any

# Un atributo por "chip". El nombre coincide con las columnas de db.py.
RX_CHIPS: dict[str, re.Pattern] = {
    "plantas":         re.compile(r"(\d+(?:\.\d+)?)\s*Plantas?\b", re.I),
    "recamaras":       re.compile(r"(\d+(?:\.\d+)?)\s*Rec\.", re.I),
    "banos":           re.compile(r"(\d+(?:\.\d+)?)\s*B[ñn]\.", re.I),
    "m2_construccion": re.compile(r"([\d.,]+)\s*m2\s*Const", re.I),
    "m2_terreno":      re.compile(r"([\d.,]+)\s*m2\s*Terr", re.I),
    "metros_frente":   re.compile(r"([\d.,]+)\s*m\s*Fren", re.I),
    "m2_oficina":      re.compile(r"([\d.,]+)\s*m2\s*Ofc", re.I),
    "m2_bodega":       re.compile(r"([\d.,]+)\s*m2\s*Bod", re.I),
}

_RX_PRECIO = re.compile(r"\$\s*([\d.,]+)")
# Precio por m² (típico en terrenos). Conservador a propósito: NO marcamos "m2"
# a secas como por-m² para no confundir un atributo de superficie con el precio.
_RX_POR_M2 = re.compile(
    r"\$\s*[\d.,]+\s*(?:por\s+metro\s+cuadrado|x\s*m2|/\s*m2)", re.I
)
_RX_MAS_IVA = re.compile(r"m[áa]s\s+IVA", re.I)


def num(s: str) -> float:
    """'1,234.5' -> 1234.5 ; '228' -> 228.0 ; tolera coma de miles y punto final."""
    return float(s.replace(",", "").rstrip("."))


def parsear_chips(texto: str | None) -> dict[str, float]:
    """Devuelve los atributos numéricos presentes en `texto`."""
    out: dict[str, float] = {}
    if not texto:
        return out
    for campo, rx in RX_CHIPS.items():
        m = rx.search(texto)
        if m:
            out[campo] = num(m.group(1))
    return out


def parsear_precio(texto: str | None) -> dict[str, Any]:
    """Extrae precio, unidad ('total' | 'm2') y bandera 'más IVA' de `texto`."""
    out: dict[str, Any] = {}
    if not texto:
        return out
    m = _RX_PRECIO.search(texto)
    if m:
        out["precio"] = int(round(num(m.group(1))))
        out["precio_unidad"] = "m2" if _RX_POR_M2.search(texto) else "total"
        out["mas_iva"] = bool(_RX_MAS_IVA.search(texto))
    return out
