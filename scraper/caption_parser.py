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


# Título canónico del sitio: "Se {vende|renta|traspasa} {TIPO} en {ZONA}" o
# "{Venta|Renta|Traspaso} de {TIPO} en {ZONA}". El TIPO va en una posición FIJA,
# así que se lee de ahí y NO por subcadena suelta: un tipo metido en el nombre de
# la colonia/zona (p. ej. "...casa en LOS DEPARTAMENTOS", "...en TORRE...") ya no
# voltea la clasificación.
_RX_TITULO = re.compile(
    r"^\s*(?:se\s+(vende|renta|traspasa)|(venta|renta|traspaso)\s+de)\s+"
    r"(.+?)\s+en\s+\S",
    re.I,
)
_TRANS_PALABRA = {"vende": "venta", "venta": "venta", "renta": "renta",
                  "traspasa": "traspaso", "traspaso": "traspaso"}


def _tipo_de_frase(frase: str) -> str | None:
    """La frase de tipo del título ('casa', 'bodegas y naves…') -> etiqueta."""
    for rx, valor in _TIPOS:
        if rx.search(frase):
            return valor
    return None


def clasificar_titulo(titulo: str | None) -> tuple[str | None, str | None]:
    """Devuelve (tipo_transaccion, tipo_inmueble) a partir del título.

    Lee el tipo de su posición canónica ("Se vende {TIPO} en …"); si el título no
    sigue ese formato, cae a la búsqueda por subcadena (mejor esfuerzo).
    """
    if not titulo:
        return None, None
    m = _RX_TITULO.match(titulo)
    if m:
        trans = _TRANS_PALABRA.get((m.group(1) or m.group(2) or "").lower())
        tipo = _tipo_de_frase(m.group(3))
        if trans or tipo:
            return trans, tipo
    # Respaldo: título no canónico -> subcadena (como antes).
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

    # ---- ubicación: "ZONA - COLONIA" antes de los atributos ----
    # El formato del sitio SIEMPRE separa zona y colonia con " - ". Si no hay
    # " - ", el texto es libre (descripción) y NO extraemos zona: así evitamos
    # que el texto del anuncio se cuele como si fuera una zona.
    corte = min(posiciones) if posiciones else len(caption)
    prefijo = caption[:corte]
    if " - " in prefijo:
        zona, colonia = prefijo.split(" - ", 1)
        zona = zona.strip(" .-\u00b7")
        colonia = colonia.strip(" .-\u00b7")
        # Si no había atributos, la colonia puede arrastrar un teléfono al final.
        colonia = re.sub(r"\s*\+?\d[\d\s().\-]{6,}$", "", colonia).strip(" .")
        if _zona_plausible(zona):
            out["zona"] = zona
            if colonia:
                out["colonia"] = colonia
    return out


def _zona_plausible(texto: str) -> bool:
    """La zona es corta y mayormente en MAYÚSCULAS (CUMBRES, SAN NICOLAS DE
    LOS GARZA, CARRETERA NACIONAL). El texto de un anuncio no lo es."""
    if not texto or len(texto) > 40:
        return False
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return False
    return sum(1 for c in letras if c.isupper()) / len(letras) >= 0.6


def parsear_entrada(titulo: str | None, caption: str | None) -> dict[str, Any]:
    """Combina título + caption en un solo dict de campos."""
    trans, tipo = clasificar_titulo(titulo)
    campos = parsear_caption(caption)
    if trans:
        campos["tipo_transaccion"] = trans
    if tipo:
        campos["tipo_inmueble"] = tipo
    return campos