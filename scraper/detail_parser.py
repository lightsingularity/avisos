"""Parser de páginas de detalle (/Detalle/BienesRaices?Aviso=...).

Se usa SOLO para avisos que no traen título/caption en el sitemap. Estrategia
en cadena: JSON-LD, metaetiquetas, y texto visible. La zona NO se toma de aquí
(no es fiable desde el texto completo de una página).
"""
from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from .atributos import RX_CHIPS, num as _num
from .caption_parser import clasificar_titulo, parsear_caption


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
        # zona/colonia desde el texto completo de una página no son fiables;
        # se quedan vacías para los avisos sin caption (mejor que basura).
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