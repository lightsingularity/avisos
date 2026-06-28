"""Catálogo de etiquetas (tags) derivadas del texto libre de la descripción.

Las etiquetas NO se capturan ni se versionan: se DERIVAN al reconstruir la base
(`db.reconstruir`) aplicando este catálogo de reglas sobre la descripción. Editar
el catálogo y reconstruir recalcula las etiquetas, sin re-scrapear.

Cada regla es un regex que se aplica sobre la descripción NORMALIZADA (minúsculas
y sin acentos). Las reglas de uso de suelo EXIGEN el calificador "uso/suelo" para
no confundirse con nombres de colonia ("X Residencial", "Plaza Comercial").

Conteos de referencia (sobre 2,081 descripciones reales, 2026-06-27) en el
comentario de cada regla: orientan, no son contrato.
"""
from __future__ import annotations

import re
import unicodedata


def normalizar(texto: str | None) -> str:
    """Minúsculas y sin acentos, para que las reglas no dependan de tildes."""
    s = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# tag legible -> patrón (se aplica sobre el texto YA normalizado)
CATALOGO: dict[str, str] = {
    # --- industriales / logísticos ---
    "terreno industrial": r"(terreno|suelo|predio|lote).{0,20}industrial|uso (de suelo )?industrial",
    "parque industrial": r"parque industrial",
    "nave industrial": r"nave industrial",
    "zona DOT": r"\bdot\b|desarrollo orientado al transporte",
    "acceso a ferrocarril": r"ferrocarril|via(s)? del? tren|espuela|spur",
    "frente a carretera/avenida":
        r"frente a .{0,10}(carretera|avenida|\bav\b|blvd|boulevard|periferico|autopista)",
    "anden/rampa": r"\banden\b|\brampa\b",
    "subestacion electrica": r"subestacion",
    "cuarto frio/refrigeracion": r"cuarto frio|refrigerad",
    # --- uso de suelo / estado (patrón ESTRICTO: exige "uso/suelo") ---
    "uso de suelo comercial": r"uso (de suelo )?comercial|suelo comercial|zonificacion comercial",
    "uso de suelo residencial": r"uso (de suelo )?residencial|suelo residencial|zonificacion residencial",
    "uso de suelo multifamiliar": r"multifamiliar",
    "todos los servicios": r"todos los servicios|todos servicios",
    "para estrenar / nueva":
        r"para estrenar|a estrenar|recien construid|nueva construccion|construccion nueva|nuevecit",
    "remodelada": r"remodelad|remodelacion",
    "para demoler": r"para demoler|a demoler|\bdemolicion\b|\bdemoler\b",
    # --- amenidades / atributos ---
    "acceso controlado / caseta":
        r"acceso controlado|caseta de vigilancia|vigilancia 24|seguridad 24|coto privado|privada con caseta",
    "amueblado": r"amueblad",
    "esquina": r"\ben esquina|local en esquina|terreno esquina|lote esquina",
}

_COMPILADO = {tag: re.compile(pat) for tag, pat in CATALOGO.items()}


def etiquetas(descripcion: str | None) -> list[str]:
    """Etiquetas que dispara una descripción (en el orden estable del catálogo)."""
    if not descripcion:
        return []
    t = normalizar(descripcion)
    return [tag for tag, rx in _COMPILADO.items() if rx.search(t)]
