"""Descarga y parseo del sitemap de bienes raíces.

El sitio publica https://www.avisosdeocasion.com/sitemap_bienesraices.xml,
regenerado a diario, con una entrada <url> por aviso activo:

    <url>
      <loc>https://www.avisosdeocasion.com/Detalle/BienesRaices?Aviso=32363879</loc>
      <image:image>
        <image:loc>https://ws.avisosdeocasion.com/fotoswa/2/32363879/1/8/0/foto.jpg</image:loc>
        <image:title>Se vende departamento en CUMBRES MADEIRA</image:title>
        <image:caption>CUMBRES - CUMBRES MADEIRA 3 Recámaras 3baños ... $5,200,000 ...</image:caption>
      </image:image>
      <lastmod>2026-06-11</lastmod>
    </url>

Algunos avisos (sin foto) traen solo <loc> y <lastmod>.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
}
URL_SITEMAP = "https://www.avisosdeocasion.com/sitemap_bienesraices.xml"
RE_ID = re.compile(r"[?&]Aviso=(\d+)")


@dataclass
class EntradaSitemap:
    id_aviso: str
    url: str
    lastmod: str | None = None
    titulo: str | None = None
    caption: str | None = None
    fotos: list[str] = field(default_factory=list)

    @property
    def tiene_caption(self) -> bool:
        return bool(self.titulo or self.caption)


def parsear_sitemap(xml_texto: str) -> list[EntradaSitemap]:
    """Convierte el XML del sitemap en una lista de EntradaSitemap."""
    raiz = ET.fromstring(xml_texto.lstrip("\ufeff"))
    entradas: list[EntradaSitemap] = []
    for nodo in raiz.findall("sm:url", NS):
        loc = nodo.findtext("sm:loc", default="", namespaces=NS).strip()
        m = RE_ID.search(loc)
        if not m:
            continue  # URL que no es un aviso (p. ej. portadas)
        e = EntradaSitemap(id_aviso=m.group(1), url=loc,
                           lastmod=nodo.findtext("sm:lastmod", default=None, namespaces=NS))
        for img in nodo.findall("image:image", NS):
            u = img.findtext("image:loc", default="", namespaces=NS).strip()
            if u:
                e.fotos.append(u)
            e.titulo = e.titulo or (img.findtext("image:title", default=None, namespaces=NS) or None)
            e.caption = e.caption or (img.findtext("image:caption", default=None, namespaces=NS) or None)
        entradas.append(e)
    return entradas


def descargar_sitemap(cliente) -> list[EntradaSitemap]:
    r = cliente.get(URL_SITEMAP)
    r.raise_for_status()
    return parsear_sitemap(r.text)
