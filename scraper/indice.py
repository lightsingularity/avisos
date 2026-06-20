"""Segunda fuente de captura: las páginas de categoría del índice.

El sitemap de novedades (sitemap.py) trae solo ~859 avisos. El catálogo COMPLETO
(~2,332) se alcanza recorriendo además las páginas de categoría listadas en
`sitemap_grupos_bienesraices.xml`, con el patrón:

    /Portada/Indice/{transaccion}-{tipo}-{ZONA-CON-GUIONES}/{numCategoria}

Cada página es HTML renderizado en el servidor (sin JavaScript), muestra
"Pág. 1 de N" y una rejilla de tarjetas. De cada tarjeta sacamos:

  - id_aviso (CANÓNICO): del href hacia /Detalle/BienesRaices?Aviso=XXXXXXXX.
    OJO: el nombre del archivo de la foto trae un id de 6 dígitos que es el id de
    FOTO, no el del aviso; por eso el id sale del enlace, no de la imagen.
  - tipo_transaccion: de la ETIQUETA de la tarjeta (VENTA/RENTA/TRASPASO), porque
    una página "venta-casa" puede contener una tarjeta de RENTA.
  - tipo_inmueble y zona: del slug de la URL de categoría.
  - colonia, precio, precio_unidad y atributos (plantas, recámaras, baños,
    m²…): del texto de la tarjeta, con las reglas compartidas de atributos.py.

Diseño robusto a propósito (no dependemos de nombres de clases CSS, que el sitio
puede cambiar): las tarjetas se delimitan por sus enlaces al detalle y la
paginación se sigue leyendo los href reales del pie de página.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .atributos import RX_CHIPS, parsear_chips, parsear_precio
from .caption_parser import _TIPOS, _zona_plausible
from .http_polite import BASE

URL_GRUPOS = "https://www.avisosdeocasion.com/sitemap_grupos_bienesraices.xml"
_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# /Portada/Indice/{slug}/{numCategoria}
RX_INDICE = re.compile(r"/Portada/Indice/([^/?#]+)/(\d+)")
# id canónico del aviso en el href de la tarjeta
RX_AVISO_HREF = re.compile(r"/Detalle/BienesRaices\?Aviso=\d+", re.I)
RX_AVISO_ID = re.compile(r"[?&]Aviso=(\d+)", re.I)
# Etiqueta de la tarjeta. En MAYÚSCULAS para no casar texto descriptivo.
RX_ETIQUETA = re.compile(r"\b(VENTA|RENTA|TRASPASO)\b")
RX_PAGINACION = re.compile(r"P[áa]g\.?\s*(\d+)\s*de\s*(\d+)", re.I)


# --------------------------- sitemap de grupos ---------------------------
def _parsear_grupos(xml_texto: str) -> list[str]:
    raiz = ET.fromstring(xml_texto.lstrip("﻿"))
    urls: list[str] = []
    for nodo in raiz.findall("sm:url", _NS):
        loc = nodo.findtext("sm:loc", default="", namespaces=_NS).strip()
        if loc and RX_INDICE.search(loc):
            urls.append(loc)
    return urls


def descargar_grupos(cliente) -> list[str]:
    """Lista de URLs de página de categoría desde el sitemap de grupos."""
    r = cliente.get(URL_GRUPOS)
    r.raise_for_status()
    return _parsear_grupos(r.text)


# ------------------------------ slug -------------------------------------
def partes_categoria(url: str) -> tuple[str, str]:
    """('venta-casa-CUMBRES', '966501') a partir de la URL de categoría."""
    m = RX_INDICE.search(url)
    if not m:
        return "", ""
    return m.group(1), m.group(2)


def _mapear_tipo(tipo_slug: str) -> str | None:
    """Mapea el segmento de tipo del slug al tipo_inmueble canónico de db.py.

    Reutiliza los patrones de caption_parser para no inventar otro vocabulario.
    """
    texto = tipo_slug.replace("-", " ").strip()
    if not texto:
        return None
    for rx, valor in _TIPOS:
        if rx.search(texto):
            return valor
    return texto.replace(" ", "_")  # p. ej. "negocio" (traspaso de negocio)


def partes_slug(slug: str) -> tuple[str | None, str | None, str | None]:
    """(transaccion, tipo_inmueble, zona) desde el slug de la categoría.

    Convención del sitio: '{transaccion}-{tipo}-{ZONA-CON-GUIONES}'. La
    transacción es el primer segmento; el tipo son los segmentos en minúsculas
    siguientes; la zona son los segmentos en MAYÚSCULAS finales. Ejemplos:
      venta-casa-CUMBRES                       -> venta, casa,        CUMBRES
      renta-bodega-nave-industrial-SANTA-CATARINA -> renta, bodega_nave, SANTA CATARINA
      venta-terreno-CARRETERA-NACIONAL         -> venta, terreno,     CARRETERA NACIONAL
      traspaso-negocio-                        -> traspaso, negocio,  (sin zona)
    """
    segmentos = [s for s in slug.split("-")]
    if not segmentos:
        return None, None, None
    transaccion = segmentos[0].lower() or None
    if transaccion not in ("venta", "renta", "traspaso"):
        transaccion = None

    tipo_tokens: list[str] = []
    zona_tokens: list[str] = []
    for s in segmentos[1:]:
        es_mayus = bool(s) and s.upper() == s and any(c.isalpha() for c in s)
        if es_mayus or zona_tokens:        # una vez en zona, lo demás es zona
            if s:
                zona_tokens.append(s)
        elif s:
            tipo_tokens.append(s)

    tipo_inmueble = _mapear_tipo("-".join(tipo_tokens))
    zona = " ".join(zona_tokens).strip() or None
    return transaccion, tipo_inmueble, zona


def _transaccion_etiqueta(texto: str) -> str | None:
    m = RX_ETIQUETA.search(texto)
    return m.group(1).lower() if m else None


# --------------------------- tarjetas ------------------------------------
def _ids_en(nodo) -> set[str]:
    ids: set[str] = set()
    for a in nodo.find_all("a", href=RX_AVISO_HREF):
        m = RX_AVISO_ID.search(a.get("href", ""))
        if m:
            ids.add(m.group(1))
    return ids


def _contenedor_tarjeta(ancla):
    """El mayor ancestro del ancla que sigue refiriéndose a UN SOLO aviso.

    Subimos mientras el padre no introduzca un segundo id de aviso; así
    aislamos la tarjeta completa sin depender de nombres de clases CSS.
    """
    nodo = ancla
    while nodo.parent is not None and getattr(nodo.parent, "name", None) not in (
        None, "body", "html", "[document]"
    ):
        if len(_ids_en(nodo.parent)) > 1:
            break
        nodo = nodo.parent
    return nodo


def _colonia(texto: str, zona: str | None) -> str | None:
    """Colonia desde el texto de la tarjeta (mejor esfuerzo).

    En la tarjeta el orden típico es: ETIQUETA $precio ZONA COLONIA <chips>.
    Recortamos hasta el primer atributo, quitamos etiqueta/precio y, si el
    texto arranca repitiendo la zona, la retiramos para quedarnos con la
    colonia. Para avisos que también están en el sitemap, la colonia del
    sitemap (más fiable) prevalece en la fusión de run.py.
    """
    cortes = [m.start() for rx in RX_CHIPS.values() if (m := rx.search(texto))]
    fin = min(cortes) if cortes else len(texto)
    seg = texto[:fin]
    seg = RX_ETIQUETA.sub(" ", seg)
    seg = re.sub(r"\$\s*[\d.,]+", " ", seg)
    seg = re.sub(r"m[áa]s\s+IVA|por\s+metro\s+cuadrado|x\s*m2|/\s*m2", " ", seg, flags=re.I)
    seg = re.sub(r"\s+", " ", seg).strip(" -·|.")
    if zona and seg.upper().startswith(zona.upper()):
        seg = seg[len(zona):].strip(" -·|.")
    seg = re.sub(r"\s*\+?\d[\d\s().\-]{6,}$", "", seg).strip(" -·|.")
    if seg and len(seg) <= 60 and _zona_plausible(seg):
        return seg
    return None


def parsear_tarjetas(html: str, slug: str) -> list[dict]:
    """Lista de dicts (uno por aviso) desde el HTML de una página de categoría."""
    trans_slug, tipo_inmueble, zona = partes_slug(slug)
    sopa = BeautifulSoup(html, "html.parser")

    contenedores: dict[str, object] = {}
    for a in sopa.find_all("a", href=RX_AVISO_HREF):
        m = RX_AVISO_ID.search(a.get("href", ""))
        if not m:
            continue
        idv = m.group(1)
        cont = _contenedor_tarjeta(a)
        previo = contenedores.get(idv)
        # Nos quedamos con el contenedor de más texto (la tarjeta, no un thumb).
        if previo is None or len(cont.get_text(strip=True)) > len(previo.get_text(strip=True)):
            contenedores[idv] = cont

    registros: list[dict] = []
    for idv, cont in contenedores.items():
        texto = cont.get_text(" ", strip=True)
        rec: dict = {
            "id_aviso": idv,
            "url": f"{BASE}/Detalle/BienesRaices?Aviso={idv}",
            "tipo_transaccion": _transaccion_etiqueta(texto) or trans_slug,
        }
        if tipo_inmueble:
            rec["tipo_inmueble"] = tipo_inmueble
        if zona:
            rec["zona"] = zona
        rec.update(parsear_precio(texto))
        chips = parsear_chips(texto)
        rec.update(chips)
        # Una tarjeta real trae precio o atributos; un enlace suelto al detalle
        # (barras de "destacados", "también te puede interesar") no, y se descarta.
        if "precio" not in rec and not chips:
            continue
        col = _colonia(texto, zona)
        if col:
            rec["colonia"] = col
        registros.append(rec)
    return registros


# --------------------------- paginación ----------------------------------
def parsear_paginacion(html: str) -> tuple[int, int]:
    """(pagina_actual, total_paginas) leyendo 'Pág. X de N'. (1, 1) si no hay."""
    m = RX_PAGINACION.search(html)
    if not m:
        texto = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        m = RX_PAGINACION.search(texto)
    return (int(m.group(1)), int(m.group(2))) if m else (1, 1)


def mapa_paginas(html: str, url_categoria: str) -> dict[int, str]:
    """{numero_pagina: url} a partir de los enlaces reales del paginador.

    Robusto al formato exacto de la URL de paginación (query, ruta o lo que
    sea): tomamos el href tal cual lo publica el sitio, exigiendo solo que el
    enlace sea numérico y apunte a la MISMA categoría.
    """
    _, numero = partes_categoria(url_categoria)
    sopa = BeautifulSoup(html, "html.parser")
    salida: dict[int, str] = {}
    for a in sopa.find_all("a", href=True):
        txt = a.get_text(strip=True)
        if not txt.isdigit():
            continue
        href = a["href"]
        if numero and numero not in href:
            continue
        salida[int(txt)] = urljoin(url_categoria, href)
    return salida


def _plantilla_pagina(url: str, n: int) -> str | None:
    """Convierte la URL de la página `n` en plantilla con '{p}' en su lugar.

    Sirve para sintetizar páginas faltantes cuando el paginador se trunca
    (p. ej. "1 2 3 … 8"): reemplaza la última aparición aislada del número.
    """
    pat = re.compile(r"(?<!\d)" + re.escape(str(n)) + r"(?!\d)")
    coincidencias = list(pat.finditer(url))
    if not coincidencias:
        return None
    ult = coincidencias[-1]
    return url[:ult.start()] + "{p}" + url[ult.end():]


@dataclass
class Pagina:
    url: str
    html: str | None
    ok: bool


def iterar_paginas(cliente, url_categoria: str, max_paginas: int = 50) -> Iterator[Pagina]:
    """Recorre las páginas 1..N de una categoría y entrega su HTML.

    Entrega un `Pagina(url, html, ok)` por página. `ok=False` (html None)
    señala una descarga fallida, para que run.py NO dé de baja avisos de
    categorías que no se pudieron leer por completo.
    """
    try:
        html1 = cliente.get(url_categoria).text
    except Exception:
        yield Pagina(url_categoria, None, False)
        return
    yield Pagina(url_categoria, html1, True)

    _, total = parsear_paginacion(html1)
    encontradas = mapa_paginas(html1, url_categoria)
    tope = min(total, max_paginas) if total else max_paginas
    if tope <= 1:
        return

    plantilla = None
    if encontradas:
        n0 = min(encontradas)
        plantilla = _plantilla_pagina(encontradas[n0], n0)

    for k in range(2, tope + 1):
        if k in encontradas:
            url_k = encontradas[k]
        elif plantilla:
            url_k = plantilla.format(p=k)
        else:
            continue
        try:
            html_k = cliente.get(url_k).text
            yield Pagina(url_k, html_k, True)
        except Exception:
            yield Pagina(url_k, None, False)


# --------------------------- cosecha -------------------------------------
@dataclass
class ResultadoIndice:
    registros: dict[str, dict] = field(default_factory=dict)
    categorias_ok: set[str] = field(default_factory=set)
    categorias_total: int = 0
    paginas_ok: int = 0
    paginas_total: int = 0

    @property
    def cobertura(self) -> float:
        """Fracción de categorías descargadas por completo (0.0 a 1.0)."""
        if not self.categorias_total:
            return 0.0
        return len(self.categorias_ok) / self.categorias_total


def cosechar_indice(cliente, cfg: dict | None = None) -> ResultadoIndice:
    """Recorre TODAS las categorías y devuelve los registros deduplicados.

    Una categoría cuenta como 'ok' solo si TODAS sus páginas se descargaron;
    así run.py sabe entre qué avisos puede calcular bajas con seguridad.
    """
    cfg = cfg or {}
    icfg = cfg.get("indice") if isinstance(cfg.get("indice"), dict) else {}
    max_paginas = int(icfg.get("max_paginas", 50))

    res = ResultadoIndice()
    for url_cat in descargar_grupos(cliente):
        slug, numero = partes_categoria(url_cat)
        res.categorias_total += 1
        cat_ok = True
        vio_alguna = False
        for pag in iterar_paginas(cliente, url_cat, max_paginas):
            res.paginas_total += 1
            if not pag.ok or pag.html is None:
                cat_ok = False
                continue
            res.paginas_ok += 1
            vio_alguna = True
            for rec in parsear_tarjetas(pag.html, slug):
                rec["categoria"] = numero
                res.registros.setdefault(rec["id_aviso"], rec)
        if cat_ok and vio_alguna:
            res.categorias_ok.add(numero)
    return res
