"""Parser de páginas de detalle (/Detalle/BienesRaices?Aviso=...).

Se usa para avisos sin título/caption en el sitemap y para enriquecer la "cola"
del índice (avisos solo-id, sin precio). Estrategia en cadena: JSON-LD,
metaetiquetas y texto visible.

UBICACIÓN (verificado contra fixtures reales): a diferencia del cuerpo libre —del
que zona/colonia NO son fiables—, la página la expone de forma estructurada:
  - og:title = "Se {trans} {tipo} en {ZONA}"   -> zona (coincide con ZonMun del sitio)
  - <title>  = "Se {trans} {tipo} en {COLONIA} | Avisos de Ocasión" -> colonia
  - respaldo: una etiqueta "Zona: {ZONA} Colonia ..." en la página.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

from .atributos import RX_CHIPS, num as _num
from .caption_parser import clasificar_titulo, parsear_caption

# "... en X" -> X (corta en " | ..." o al final). El tipo/transacción nunca
# contienen un " en " suelto, así que el primer " en " separa la ubicación.
_RX_EN = re.compile(r"\ben\s+(.+?)\s*(?:\||$)", re.I)
# Etiqueta explícita "Zona: VALLE Colonia ..." (respaldo si falta og:title).
_RX_ZONA_LBL = re.compile(r"Zona:\s*([^|]+?)\s+Colonia", re.I)


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

    og_title = _meta("og:title")
    doc_title = sopa.title.get_text(strip=True) if sopa.title else None
    titulo = out.pop("_titulo_jsonld", None) or og_title or doc_title
    trans, tipo = clasificar_titulo(titulo)
    if trans:
        out["tipo_transaccion"] = trans
    if tipo:
        out["tipo_inmueble"] = tipo

    # Ubicación estructurada (fiable): zona del og:title, colonia del <title>.
    if og_title and (m := _RX_EN.search(og_title)):
        out["zona"] = m.group(1).strip()
    if doc_title and (m := _RX_EN.search(doc_title)):
        out.setdefault("colonia", m.group(1).strip())

    desc_meta = _meta("og:description", "description")
    if desc_meta and "descripcion" not in out:
        out["descripcion"] = desc_meta

    # La sección visible "DESCRIPCIÓN" trae el texto LIBRE que escribió el
    # anunciante (lote industrial, cajones de estacionamiento, amenidades…);
    # meta/JSON-LD solo repiten un resumen corto plantilla. Si está, manda
    # sobre lo anterior (superconjunto más rico, no solo un respaldo).
    div_desc = sopa.find("div", id="id_descripcion")
    if div_desc:
        parrafos = [p.get_text(" ", strip=True) for p in div_desc.find_all("p")]
        texto_desc = "\n".join(p for p in parrafos if p)
        if texto_desc:
            out["descripcion"] = texto_desc

    # --- 3) Texto visible: caption-style + chips ---
    texto = sopa.get_text(" ", strip=True)
    # Respaldo de zona: la etiqueta explícita "Zona: X" si no la dio el og:title.
    if "zona" not in out and (m := _RX_ZONA_LBL.search(texto)):
        out["zona"] = m.group(1).strip()
    campos_texto = parsear_caption(texto)
    for k, v in campos_texto.items():
        # zona/colonia desde el CUERPO libre no son fiables (las estructuradas de
        # arriba sí); aquí se ignoran para no meter basura.
        if k in ("zona", "colonia"):
            continue
        out.setdefault(k, v)
    for campo, rx in RX_CHIPS.items():
        if campo not in out:
            m = rx.search(texto)
            if m:
                out[campo] = _num(m.group(1))

    # Fotos referenciadas en la página
    fotos = []
    for img in sopa.find_all("img", src=True):
        if "fotoswa" in img["src"]:
            fotos.append(img["src"])
    if fotos:
        out["fotos"] = list(dict.fromkeys(fotos))

    return out