"""Eliminación de datos de contacto (teléfonos y correos) de textos de anuncios.
"""
from __future__ import annotations

import re

# +52 81 1077 7451 / 81-8378-6874 / (81) 8150 8150 / 8110777451
_RX_TEL_FORMATO = re.compile(
    r"(?:\+?52[\s.\-]?)?(?:\(?\d{2,3}\)?[\s.\-])?\d{3,4}[\s.\-]\d{4}\b"
)
_RX_TEL_PEGADO = re.compile(r"\b\d{10}\b")
_RX_CORREO = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_RX_ESPACIOS = re.compile(r"\s{2,}")


def limpiar_contactos(texto: str | None) -> str | None:
    if not texto:
        return texto
    t = _RX_CORREO.sub("[correo]", texto)
    t = _RX_TEL_FORMATO.sub("[tel]", t)
    t = _RX_TEL_PEGADO.sub("[tel]", t)
    return _RX_ESPACIOS.sub(" ", t).strip()
