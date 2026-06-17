"""Parser de páginas de detalle (/Detalle/BienesRaices?Aviso=...).

Se usa SOLO para avisos que no traen título/caption en el sitemap (los que no
tienen foto) o cuando config.detalle = "todos". Estrategia en cadena, de lo más
robusto a lo más heurístico:

  1. JSON-LD (schema.org) si la página lo incluye.
  2. Metaetiquetas og:title / og:description / description.
  3. Texto visible: mismas expresiones que el caption del sitemap, más el
     formato "chip" de las tarjetas: "3 Rec. | 2.5 Bñ. | 274 m2 Const. ..."

NOTA DE CALIBRACIÓN: este módulo se escribió sin ver el HTML real de una página
de detalle (el entorno de desarrollo no tiene acceso de red al sitio). Corre
`python calibrate.py` en tu máquina: descarga páginas reales a tests/fixtures/
e imprime qué estrategias funcionan. Si algo falla, esos fixtures son justo lo
que Claude Code necesita para afinar los selectores en minutos.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from .caption_parser import clasificar_titulo, parsear_caption

# Formato "chip" observado en las tarjetas del sitio:
#   **2** Plantas | **4** Rec. | **2.5** Bñ. | **274** m2 Const. | **210** m2 Terr.
_RX_CHIPS: dict[str, re.Pattern] = {
    "plantas":         re.compile(r"(\d+(?:\.\d+)?)\s*Plantas?\b", re.I),
    "recamaras":       re.compile(r"(\d+(?:\.\d+)?)\s*Rec\.", re.I),
    "banos":           re.compile(r"(\d+(?:\.\d+)?)\s*B[ñn]\.", re.I),
    "m2_construccion": re.compile(r"([\d.,]+)\s*m2\s*Const", re.I),
    "m2_terreno":      re.compile(r"([\d.,]+)\s*m2\s*Terr", re.I),
    "metros_frente":   re.compile(r"([\d.,]+)\s*m\s*Fren", re.I),
    "m2_oficina":      re.compile(r"([\d.,]+)\s*m2\s*Ofc", re.I),
    "m2_bodega":       re.compile(r"([\d.,]+)\s*m2\s*Bod", re.I),
}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parsear_detalle(html: str) -> dict[str, Any]:
    """Devuelve los campos que se logren extraer de una página de detalle."""
    sopa = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {}

    # --- 1) JSON-LD ---
    for nodo in sopa.find_all("script", type="application/ld+json"):
        try:
            datos = json.loads(nodo.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in datos if isinstance(datos, list) else [datos]:
            if not isinstance(obj, dict):
                continue
            oferta = obj.get("offers", obj)
            if isinstance(oferta, dict) and oferta.get("price"):
                try:
                    out["precio"] = int(round(float(str(oferta["price"]).replace(",", ""))))
                    out["precio_unidad"] = "total"
                except ValueError:
                    pass
            if obj.get("name"):
                out["_titulo_jsonld"] = obj["name"]
            if obj.get("description"):
                out["descripcion"] = obj["description"]

    # --- 2) Metaetiquetas ---
    def _meta(*nombres: str) -> str | None:
        for n in nombres:
            tag = sopa.find("meta", attrs={"property": n}) or sopa.find("meta", attrs={"name": n})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    titulo = out.pop("_titulo_jsonld", None) or _meta("og:title") or (
        sopa.title.get_text(strip=True) if sopa.title else None
    )
    trans, tipo = clasificar_titulo(titulo)
    if trans:
        out["tipo_transaccion"] = trans
    if tipo:
        out["tipo_inmueble"] = tipo

    desc_meta = _meta("og:description", "description")
    if desc_meta and "descripcion" not in out:
        out["descripcion"] = desc_meta

    # --- 3) Texto visible: caption-style + chips ---
    texto = sopa.get_text(" ", strip=True)
    campos_texto = parsear_caption(texto)
    for k, v in campos_texto.items():
        out.setdefault(k, v)
    for campo, rx in _RX_CHIPS.items():
        if campo not in out:
            m = rx.search(texto)
            if m:
                out[campo] = _num(m.group(1))

    # Fotos referenciadas en la página (patrón ws.avisosdeocasion.com/fotoswa/...)
    fotos = []
    for img in sopa.find_all("img", src=True):
        if "fotoswa" in img["src"]:
            fotos.append(img["src"])
    if fotos:
        out["fotos"] = list(dict.fromkeys(fotos))  # únicas, en orden

    return out
