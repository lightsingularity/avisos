"""Segunda fuente de captura: las páginas de categoría del índice.

El sitemap de novedades (sitemap.py) trae solo ~893 avisos. El catálogo COMPLETO
(~2,332) se alcanza recorriendo además las páginas de categoría listadas en
`sitemap_grupos_bienesraices.xml`, con el patrón:

    /Portada/Indice/{transaccion}-{tipo}-{ZONA-CON-GUIONES}/{numCategoria}

Cómo trae los datos la página (verificado contra fixtures reales): NO son tarjetas
HTML que haya que raspar, ni la paginación son enlaces GET. La página incrusta un
`<input type="hidden" name="json">` con TODO lo necesario:

    {
      "Registros": 242,
      "K_Avisos": [32353380, 32364699, ...],   # los 242 ids de la categoría
      "Avisos":   [ {K_Av, Precio, ZonMun, Col, Rec, Banios, Plantas,
                     m2Const, m2Terr, ...}, ... ]   # objetos ricos de ESTA página
    }

De ahí sale todo:

  - `K_Avisos` da el CATÁLOGO COMPLETO de la categoría con UNA sola solicitud
    GET (no hay que paginar; la paginación real del sitio es un POST con token
    antiforgery a /Portada/PostIndice, frágil y evitable).
  - `Avisos` trae los objetos ricos de la página 1 (precio, colonia, recámaras,
    superficies…), ya estructurados (sin raspar texto ni superíndices `m²`).
  - id_aviso (CANÓNICO): el campo `K_Av` (8 dígitos). En la tarjeta visible el
    enlace es `/Detalle/PostBienesRaices?Aviso=…`; guardamos siempre la URL
    canónica `/Detalle/BienesRaices?Aviso=…` (la misma del sitemap) para que la
    deduplicación entre fuentes case por id.
  - tipo_transaccion, tipo_inmueble y zona: del slug de la categoría (las páginas
    de categoría son homogéneas: una "venta-casa" lista ventas de casas).

Los ids de `K_Avisos` que no aparezcan como objeto rico en la página 1 (el resto
de páginas) se registran igual con los campos derivables del slug; eso basta para
el conteo del catálogo y la detección segura de bajas, y el sitemap aporta los
campos ricos de los que sí cubre.
"""
from __future__ import annotations

import html as htmlmod
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .caption_parser import _TIPOS
from .http_polite import BASE
from .sitemap import _raiz_xml

URL_GRUPOS = "https://www.avisosdeocasion.com/sitemap_grupos_bienesraices.xml"
_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# /Portada/Indice/{slug}/{numCategoria}
RX_INDICE = re.compile(r"/Portada/Indice/([^/?#]+)/(\d+)")
# Valor del <input name="json"> con el catálogo (las comillas internas vienen
# como &quot;, así que dentro del value no hay comillas reales que cortar).
_RX_JSON_VAL = re.compile(r'value="(\{[^"]*\})"', re.S)


# --------------------------- sitemap de grupos ---------------------------
def _parsear_grupos(xml_texto: str) -> list[str]:
    raiz = _raiz_xml(xml_texto)
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


# Número de categoría PLACEHOLDER para las URLs construidas desde el historial.
# Verificado en vivo (sonda 2026-06-25): el número de /Portada/Indice/{slug}/{n}
# es COSMÉTICO —solo cambia el <title> decorativo—; quien RUTEA (y filtra por
# zona+tipo) es el SLUG. Cualquier número entero sirve; el segmento sí es
# estructuralmente obligatorio (sin él, el sitio redirige a PageNotFound).
NUM_CATEGORIA_PLACEHOLDER = "1"

# Semilla de categorías: respaldo de descubrimiento cuando el log está VACÍO (una
# re-captura desde cero o un clon nuevo) y el sitemap de grupos sigue caído. Sin
# esto no habría de dónde sacar las categorías y la corrida abortaría. Versionada
# en data/ (un slug por línea); se regenera con los slugs distintos del log.
RUTA_SEMILLA = Path(__file__).resolve().parent.parent / "data" / "categorias_semilla.txt"


def _leer_semilla() -> set[str]:
    """Slugs de categoría semilla. '#' comenta; sin archivo -> conjunto vacío."""
    try:
        lineas = RUTA_SEMILLA.read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {s.strip() for s in lineas if s.strip() and not s.strip().startswith("#")}


def urls_categoria(cliente, categorias_historicas=None) -> tuple[list[str], str]:
    """URLs de página de categoría, RESILIENTE al sitemap de grupos (caído desde
    2026-06: sirve HTML, no XML).

    Devuelve (urls, fuente). Estrategia, decidida por lo que el sitio DEVUELVE en
    cada corrida (no por una bandera fija), para que un sitemap que regresa sea un
    atajo y no una rotura:
      1) Intenta el sitemap de grupos. Si parsea como XML válido y trae URLs, úsalo
         (atajo histórico; pocas requests; se autocura solo cuando el sitio vuelve).
      2) Si no (HTML/redirección/corrupto), construye las URLs desde los slugs de
         categoría del HISTORIAL (la bitácora): `/Portada/Indice/{slug}/{placeholder}`.
         El slug rutea, así que el número placeholder basta.
      3) Si el HISTORIAL está vacío (re-captura desde cero / clon nuevo), cae a la
         SEMILLA versionada. Así el descubrimiento nunca depende al 100% del log.
    """
    try:
        urls = descargar_grupos(cliente)   # _parsear_grupos revienta si es HTML
        if urls:
            return urls, "sitemap"
    except Exception:
        pass  # el sitemap no sirvió XML; caemos al historial/semilla
    categorias = set(categorias_historicas or ())
    fuente = "historial"
    if not categorias:                     # log vacío -> respaldo por semilla
        categorias = _leer_semilla()
        fuente = "semilla"
    urls = [f"{BASE}/Portada/Indice/{slug}/{NUM_CATEGORIA_PLACEHOLDER}"
            for slug in sorted(categorias)]
    return urls, fuente


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


# --------------------------- JSON incrustado -----------------------------
def extraer_busqueda(html: str) -> dict | None:
    """Devuelve el objeto JSON del `<input name="json">` con el catálogo.

    Tolerante al orden de atributos y a la presencia de otros inputs 'json':
    elige el único cuyo valor contiene `K_Avisos`. None si no está o no parsea.
    """
    for crudo in _RX_JSON_VAL.findall(html):
        if "K_Avisos" not in crudo:
            continue
        try:
            return json.loads(htmlmod.unescape(crudo))
        except ValueError:
            return None
    return None


def ids_categoria(html: str) -> tuple[list[str], int]:
    """(ids de TODA la categoría, total declarado) desde `K_Avisos`/`Registros`."""
    data = extraer_busqueda(html)
    if not data:
        return [], 0
    ids = [str(x) for x in data.get("K_Avisos", []) if x]
    total = data.get("Registros")
    return ids, int(total) if isinstance(total, int) else len(ids)


# ----------------------------- registros ---------------------------------
# Campos numéricos del objeto JSON -> columnas de db.py (solo si vienen > 0).
_MAPA_ATRIB: list[tuple[str, str]] = [
    ("plantas", "Plantas"),
    ("recamaras", "Rec"),
    ("m2_construccion", "m2Const"),
    ("m2_terreno", "m2Terr"),
    ("m2_oficina", "m2Ofna"),
    ("m2_bodega", "m2Bodega"),
    ("metros_frente", "mFrente"),
]


def _pos(v) -> float | None:
    """El valor como float si es un número positivo; None si es 0 o no numérico."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def _registro_base(idv: str, trans, tipo, zona) -> dict:
    rec: dict = {"id_aviso": idv, "url": f"{BASE}/Detalle/BienesRaices?Aviso={idv}"}
    if trans:
        rec["tipo_transaccion"] = trans
    if tipo:
        rec["tipo_inmueble"] = tipo
    if zona:
        rec["zona"] = zona
    return rec


def _registro_rico(obj: dict, trans, tipo, zona, clasif: "Clasificacion | None" = None) -> dict:
    """Mapea un objeto de `Avisos` a un registro con columnas de db.py.

    NADA del SLUG de la categoría es fiable: las páginas mezclan avisos de otras
    categorías (p. ej. una página "venta-terreno-VALLE" lista en su primera página
    casas de VALLE con terreno grande, y una página "...-CENTRO" lista avisos cuya
    zona real es VALLE). El objeto trae sus PROPIOS datos:
      - K_Cla3 = tipo de inmueble, K_Cla2 = transacción. Si tenemos el mapa
        código→etiqueta (aprendido del catálogo completo), tipamos por el código
        del aviso; si no, caemos al slug.
      - ZonMun = su zona real. Se usa esa; el slug solo respalda si ZonMun falta.
    """
    idv = str(obj["K_Av"])
    # Marcamos cuándo el tipo/transacción salen del CÓDIGO del aviso (K_Cla3/K_Cla2)
    # —la fuente fiable—. run.py usa estas marcas (con prefijo '_', no se persisten)
    # para que el código mande sobre lo inferido del título y para que la cola
    # prefiera el detalle al slug contaminado.
    tipo_fiable = trans_fiable = False
    if clasif is not None:
        if obj.get("K_Cla3") in clasif.tipo:
            tipo, tipo_fiable = clasif.tipo[obj["K_Cla3"]], True
        if obj.get("K_Cla2") in clasif.trans:
            trans, trans_fiable = clasif.trans[obj["K_Cla2"]], True
    # La zona del propio aviso (ZonMun) es la fiable; el slug está contaminado con
    # cross-listings de otras zonas, así que solo respalda cuando ZonMun falta.
    z = (str(obj.get("ZonMun") or "").strip() or None) or zona
    rec = _registro_base(idv, trans, tipo, z)
    if tipo_fiable:
        rec["_tipo_fiable"] = True
    if trans_fiable:
        rec["_trans_fiable"] = True

    col = str(obj.get("Col") or "").strip()
    if col:
        rec["colonia"] = col

    # Precio: m2Precio>0 => por m² (terrenos); si no, el total. La MONEDA se guarda
    # nativa (no se dropea ni se convierte): el flag `USD` del índice es una pista
    # (NO fiable: deja pasar dólares como MXN), así que el DETALLE la confirma/pisa
    # en run.py. Por defecto MXN.
    por_m2 = _pos(obj.get("m2Precio"))
    total = _pos(obj.get("Precio"))
    if por_m2:
        rec["precio"], rec["precio_unidad"] = int(por_m2), "m2"
    elif total:
        rec["precio"], rec["precio_unidad"] = int(total), "total"
    if "precio" in rec and obj.get("USD"):
        rec["precio_moneda"] = "USD"

    for col_db, clave in _MAPA_ATRIB:
        v = _pos(obj.get(clave))
        if v is not None:
            rec[col_db] = v

    banos = (obj.get("Banios") or 0) + 0.5 * (obj.get("MedBan") or 0)
    if banos > 0:
        rec["banos"] = float(banos)
    return rec


def parsear_avisos(html: str, slug: str) -> list[dict]:
    """Registros ricos (uno por aviso) de los objetos `Avisos` de la página."""
    data = extraer_busqueda(html)
    if not data:
        return []
    trans, tipo, zona = partes_slug(slug)
    return [
        _registro_rico(o, trans, tipo, zona)
        for o in data.get("Avisos", [])
        if isinstance(o, dict) and o.get("K_Av")
    ]


# --------------------------- cosecha -------------------------------------
@dataclass
class ResultadoIndice:
    registros: dict[str, dict] = field(default_factory=dict)
    categorias_ok: set[str] = field(default_factory=set)
    categorias_total: int = 0
    paginas_ok: int = 0
    paginas_total: int = 0
    fuente: str = "sitemap"   # de dónde salieron las categorías: sitemap | historial

    @property
    def cobertura(self) -> float:
        """Fracción de categorías leídas por completo (0.0 a 1.0)."""
        if not self.categorias_total:
            return 0.0
        return len(self.categorias_ok) / self.categorias_total


def _riqueza(rec: dict) -> int:
    """Cuántos campos de datos trae (para preferir el registro más completo)."""
    return sum(1 for k in rec if k not in ("id_aviso", "url", "categoria")
               and not k.startswith("_"))


@dataclass
class Clasificacion:
    """Mapa código→etiqueta aprendido del catálogo: K_Cla3→tipo, K_Cla2→transacción."""
    tipo: dict = field(default_factory=dict)
    trans: dict = field(default_factory=dict)


def aprender_clasificacion(paginas) -> Clasificacion:
    """Aprende los códigos del sitio votando por MAYORÍA sobre todas las categorías.

    `paginas` es un iterable de (trans_slug, tipo_slug, avisos_ricos). Cada aviso
    rico vota su K_Cla3 -> tipo del slug de SU página y K_Cla2 -> transacción del
    slug. Como la contaminación entre categorías es minoría (una página de terrenos
    con casas mezcladas es la excepción), el voto mayoritario recupera el
    significado real de cada código (p. ej. K_Cla3=120→casa pese a aparecer en
    páginas de terreno).
    """
    voto_tipo: dict = defaultdict(Counter)
    voto_trans: dict = defaultdict(Counter)
    for trans_slug, tipo_slug, avisos in paginas:
        for o in avisos:
            k3, k2 = o.get("K_Cla3"), o.get("K_Cla2")
            if tipo_slug and k3 is not None:
                voto_tipo[k3][tipo_slug] += 1
            if trans_slug and k2 is not None:
                voto_trans[k2][trans_slug] += 1
    return Clasificacion(
        tipo={c: cnt.most_common(1)[0][0] for c, cnt in voto_tipo.items()},
        trans={c: cnt.most_common(1)[0][0] for c, cnt in voto_trans.items()},
    )


def cosechar_indice(cliente, cfg: dict | None = None,
                    categorias_historicas=None) -> ResultadoIndice:
    """Recorre TODAS las categorías (1 GET c/u) y devuelve registros deduplicados.

    La lista de categorías sale de `urls_categoria` (resiliente: sitemap de grupos
    si sirve XML; si no, los slugs del historial). `categorias_historicas` es el
    conjunto de slugs ya vistos (lo arma run.py desde la bitácora) y solo se usa en
    el camino de respaldo.

    Dos pasadas: primero descarga todas las páginas y aprende el mapa de códigos
    de clasificación (para no fiarse del slug de cada página, que mezcla tipos);
    luego construye los registros tipando cada aviso rico por SU propio código.

    Una categoría cuenta como 'ok' (COMPLETA, apta para bajas) si su página entregó
    el JSON y `K_Avisos` NO viene truncado. El sitio corta `K_Avisos` a 500 en
    categorías enormes (Registros>len(K_Avisos)): sus ids sirven para ALTAS, pero no
    para dar de baja (no sabemos cuáles faltan), así que esa categoría no es 'ok'.
    """
    res = ResultadoIndice()
    paginas: list[tuple] = []   # (slug, trans, tipo, zona, k_avisos, avisos_ricos)
    urls, res.fuente = urls_categoria(cliente, categorias_historicas)
    for url_cat in urls:
        slug, _numero = partes_categoria(url_cat)
        trans, tipo, zona = partes_slug(slug)
        res.categorias_total += 1
        res.paginas_total += 1
        try:
            html = cliente.get(url_cat).text
        except Exception:
            continue
        data = extraer_busqueda(html)
        if not data:
            continue
        res.paginas_ok += 1
        avisos = [o for o in data.get("Avisos", []) if isinstance(o, dict) and o.get("K_Av")]
        kav = [str(x) for x in data.get("K_Avisos", [])]
        total = data.get("Registros")
        total = int(total) if isinstance(total, int) else len(kav)
        if len(kav) >= total:          # completa (no truncada) -> apta para bajas
            res.categorias_ok.add(slug)
        paginas.append((slug, trans, tipo, zona, kav, avisos))

    clasif = aprender_clasificacion((t, tp, av) for _, t, tp, _, _, av in paginas)

    for slug, trans, tipo, zona, kav, avisos in paginas:
        ricos = {str(o["K_Av"]): _registro_rico(o, trans, tipo, zona, clasif) for o in avisos}
        for idv in kav:
            rec = ricos.get(idv) or _registro_base(idv, trans, tipo, zona)
            previo = res.registros.get(idv)
            # El registro más completo gana (un aviso puede estar en varias
            # categorías: rico en la suya, mínimo en otra más amplia).
            if previo is None or _riqueza(rec) > _riqueza(previo):
                res.registros[idv] = {**rec, "categoria": slug}
    return res
