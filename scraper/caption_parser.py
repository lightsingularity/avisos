"""Parseo de <image:title> y <image:caption> del sitemap a campos estructurados."""
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
_RX_TERRENO = re.compile(
    r"([\d.,]+)\s*Metros\s+Cuadrados"
    r"(?!\s*de\s*(?:Construcci|bodega|Oficina))",
    re.I,
)
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

    # ---- ubicación: el texto ANTES del primer campo detectado ----
    # Si no se detectó ningún campo, NO adivinamos ubicación (antes se colaba
    # todo el texto del anuncio). Y validamos que parezca una zona/colonia real.
    corte = min(posiciones) if posiciones else 0
    ubic = caption[:corte].strip(" .-\u00b7") if corte else ""
    if _ubicacion_plausible(ubic):
        if " - " in ubic:
            zona, colonia = ubic.split(" - ", 1)
            out["zona"], out["colonia"] = zona.strip(), colonia.strip(" .")
        else:
            out["zona"] = ubic
    return out


def _ubicacion_plausible(texto: str) -> bool:
    """Las zonas/colonias son cortas y en MAYÚSCULAS (CUMBRES, VALLE ORIENTE).
    El texto de un anuncio es largo y/o en minúsculas, así que lo rechazamos."""
    if not texto or len(texto) > 80:
        return False
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return False
    proporcion_mayus = sum(1 for c in letras if c.isupper()) / len(letras)
    return proporcion_mayus >= 0.6


def parsear_entrada(titulo: str | None, caption: str | None) -> dict[str, Any]:
    """Combina título + caption en un solo dict de campos."""
    trans, tipo = clasificar_titulo(titulo)
    campos = parsear_caption(caption)
    if trans:
        campos["tipo_transaccion"] = trans
    if tipo:
        campos["tipo_inmueble"] = tipo
    return campos