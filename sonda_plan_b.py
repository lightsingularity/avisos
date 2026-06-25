#!/usr/bin/env python3
"""Sonda de Plan B: descubrimiento sin los sitemaps XML (caídos desde 2026-06-24).

Corre en GitHub Actions (el runner sí alcanza el sitio; este contenedor no) vía
`calibrate.yml` apuntado a este script. Responde, en UNA corrida y al log, las
incógnitas que definen el diseño del descubrimiento forward-only:

  A. ¿Los sitemaps XML siguen sirviendo HTML (no XML)?
  B. ¿El home expone enlaces de categoría /Portada/Indice/{slug}/{numero}?
  C. ¿El {numero} de la URL es COSMÉTICO? (si sí, los 59 slugs del historial
     bastan con cualquier número; no hace falta el sitemap de grupos.)
  D. ¿Manda el SLUG o el NÚMERO en el ruteo? ¿Funcionan los slugs del historial?

Guarda fixtures para las pruebas offline: home.html y, si existe, una página de
categoría "top-level" (sin zona). No escribe en la bitácora: solo diagnostica.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from scraper.http_polite import BASE, ClienteEducado
from scraper.indice import RX_INDICE, extraer_busqueda, ids_categoria, partes_slug
from scraper.sitemap import URL_SITEMAP, _raiz_xml
from scraper.indice import URL_GRUPOS

FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def _parece_html(texto: str) -> bool:
    return texto.lstrip()[:200].lower().startswith(("<!doctype", "<html"))


def sondar_categoria(cliente, url: str) -> dict:
    """Pide una página de categoría y resume qué trajo (sin reventar la sonda)."""
    info = {"url": url}
    try:
        r = cliente.get(url)
    except Exception as exc:
        info["error"] = repr(exc)
        return info
    info["http"] = r.status_code
    info["url_final"] = r.url
    info["html"] = _parece_html(r.text)
    data = extraer_busqueda(r.text)
    if not data:
        info["json"] = False
        return info
    ids, total = ids_categoria(r.text)
    info["json"] = True
    info["registros"] = data.get("Registros")
    info["k_avisos"] = len(ids)
    info["ricos_p1"] = len(data.get("Avisos", []))
    info["primeros"] = ids[:3]
    info["titulo"] = data.get("Title")
    return info


def _linea(info: dict) -> str:
    if "error" in info:
        return f"ERROR {info['error']}"
    if not info.get("json"):
        return (f"HTTP {info.get('http')} html={info.get('html')} "
                f"SIN json (url_final={info.get('url_final')})")
    return (f"HTTP {info['http']} | Registros={info['registros']} "
            f"K_Avisos={info['k_avisos']} ricos={info['ricos_p1']} "
            f"| primeros={info['primeros']} | Title={info['titulo']!r}")


def main() -> None:
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cliente = ClienteEducado(contacto=cfg.get("contacto", "sonda"))
    cliente.cargar_robots()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    print("robots.txt cargado; el cliente respeta sus reglas y limita a 1 req/s.\n")

    # ---- A. estado de los sitemaps (¿siguen HTML?) ----
    print("================ A. SITEMAPS XML ================")
    for nombre, url in (("novedades", URL_SITEMAP), ("grupos", URL_GRUPOS)):
        try:
            r = cliente.get(url)
            es_html = _parece_html(r.text)
            es_xml = False
            if not es_html:
                try:
                    raiz = _raiz_xml(r.text)
                    es_xml = raiz.tag.endswith("urlset")
                except Exception:
                    es_xml = False
            print(f"  {nombre:10s} HTTP {r.status_code} | parece_html={es_html} "
                  f"| es_xml_urlset={es_xml} | ctype={r.headers.get('Content-Type')}")
        except Exception as exc:
            print(f"  {nombre:10s} ERROR {exc!r}")
    print()

    # ---- B. ¿el home expone enlaces de categoría? ----
    print("================ B. HOME / NAVEGACIÓN ================")
    home_urls = [BASE + "/", BASE + "/Portada/BienesRaices", BASE + "/BienesRaices"]
    enlaces: list[tuple[str, str]] = []
    for u in home_urls:
        try:
            r = cliente.get(u)
        except Exception as exc:
            print(f"  {u} -> ERROR {exc!r}")
            continue
        pares = RX_INDICE.findall(r.text)  # [(slug, numero), ...]
        print(f"  {u} -> HTTP {r.status_code}, {len(r.text)} chars, "
              f"{len(pares)} enlaces /Portada/Indice/")
        if u == BASE + "/":
            (FIXTURES / "home.html").write_text(r.text, encoding="utf-8")
            print("    (guardado tests/fixtures/home.html)")
        for slug, num in pares:
            enlaces.append((slug, num))
    # Mapa (transaccion, tipo) -> numero, deducido de los enlaces del home.
    mapa_tt: dict[tuple, set] = {}
    for slug, num in enlaces:
        trans, tipo, _zona = partes_slug(slug)
        mapa_tt.setdefault((trans, tipo), set()).add(num)
    print(f"\n  Enlaces de categoría únicos en el home: {len(set(enlaces))}")
    print(f"  Combinaciones (transaccion, tipo) -> número(s) vistas en el home:")
    for (trans, tipo), nums in sorted(mapa_tt.items(), key=lambda x: str(x[0])):
        ejemplos = [s for s, _ in enlaces if partes_slug(s)[:2] == (trans, tipo)][:2]
        print(f"    {str(trans):8s} {str(tipo):22s} -> nums={sorted(nums)} ej={ejemplos}")
    print()

    # ---- C. ¿el {numero} es cosmético? (mismo slug, números distintos) ----
    print("================ C. ¿NÚMERO COSMÉTICO? (venta-casa-VALLE) ================")
    print("  Si todos los números dan el MISMO K_Avisos, el número es cosmético y")
    print("  los slugs del historial bastan con cualquier número.\n")
    slug_c = "venta-casa-VALLE"
    for num in ("966501", "1", "0", "1054526", "999999999"):
        info = sondar_categoria(cliente, f"{BASE}/Portada/Indice/{slug_c}/{num}")
        print(f"  /{slug_c}/{num:11s} -> {_linea(info)}")
    # sin número
    for tail in (f"/{slug_c}/", f"/{slug_c}"):
        info = sondar_categoria(cliente, f"{BASE}/Portada/Indice{tail}")
        print(f"  /Portada/Indice{tail:24s} -> {_linea(info)}")
    print()

    # ---- D. ¿manda el slug o el número? + slugs del historial ----
    print("================ D. RUTEO (slug vs número) + HISTORIAL ================")
    print("  Mismo número (966501=venta-casa), distinto slug: si el K_Avisos CAMBIA")
    print("  con el slug, manda el SLUG (lo que queremos); si no, manda el número.\n")
    for slug in ("venta-casa-VALLE", "venta-departamento-VALLE", "venta-terreno-VALLE",
                 "renta-casa-VALLE"):
        info = sondar_categoria(cliente, f"{BASE}/Portada/Indice/{slug}/966501")
        print(f"  /{slug}/966501 -> {_linea(info)}")
    print()
    print("  Slugs del HISTORIAL (con número placeholder=1): ¿responden con su JSON?\n")
    for slug in ("renta-casa-SAN-NICOLAS-DE-LOS-GARZA",
                 "renta-bodega-nave-industrial-SANTA-CATARINA",
                 "traspaso-negocio-", "venta-finca-campestre-CARRETERA-NACIONAL"):
        info = sondar_categoria(cliente, f"{BASE}/Portada/Indice/{slug}/1")
        print(f"  /{slug}/1 -> {_linea(info)}")
    print()

    # ---- E. top-level (sin zona): ¿trae todo el catálogo cross-zona? ----
    print("================ E. TOP-LEVEL SIN ZONA (venta-casa) ================")
    print("  Si /venta-casa/966501 trae MUCHOS más K_Avisos que una zona, podría")
    print("  enumerar todo el tipo cross-zona (descubrimiento aún más barato).\n")
    info = sondar_categoria(cliente, f"{BASE}/Portada/Indice/venta-casa/966501")
    print(f"  /venta-casa/966501 -> {_linea(info)}")
    if info.get("json"):
        # Guardar como fixture solo si trae JSON (sirve para pruebas offline).
        try:
            r = cliente.get(f"{BASE}/Portada/Indice/venta-casa/966501")
            (FIXTURES / "indice_venta-casa_p1.html").write_text(r.text, encoding="utf-8")
            print("    (guardado tests/fixtures/indice_venta-casa_p1.html)")
        except Exception as exc:
            print(f"    no se pudo guardar fixture: {exc!r}")

    print("\nListo. Lee el bloque A-E para fijar el diseño del descubrimiento.")


if __name__ == "__main__":
    main()
