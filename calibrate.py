#!/usr/bin/env python3
"""Calibración con diagnóstico, RESILIENTE al sitemap caído.

Captura fixtures REALES (página de categoría + detalle) en GitHub Actions —cuyo
runner sí alcanza el sitio— para que las pruebas corran offline, y valida el
parseo imprimiendo hallazgos al log.

Desde 2026-06 el sitio sirve HTML en vez de XML en los sitemaps. Por eso aquí el
sitemap es OPCIONAL: si parsea como XML se usa (y la herramienta se autocura
cuando el sitio vuelve); si no, se sigue con el índice descubierto por los slugs
del HISTORIAL —igual que el scraper (ver scraper/indice.urls_categoria)."""
from pathlib import Path

import yaml

from scraper.caption_parser import parsear_entrada
from scraper.db import estado_actual
from scraper.detail_parser import parsear_detalle
from scraper.http_polite import BASE, ClienteEducado
from scraper.indice import ids_categoria, parsear_avisos, partes_categoria, urls_categoria
from scraper.sitemap import URL_SITEMAP, parsear_sitemap

FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def _diagnostico(r) -> None:
    cuerpo = r.text or ""
    inicio = cuerpo.lstrip()[:400]
    parece_html = inicio[:200].lower().lstrip().startswith(("<!doctype", "<html"))
    print("\n================ DIAGNOSTICO DE LA RESPUESTA ================")
    print(f"  Codigo HTTP        : {r.status_code}")
    print(f"  URL final          : {r.url}")
    print(f"  Content-Type       : {r.headers.get('Content-Type', '(no informado)')}")
    print(f"  Tamano (caracteres): {len(cuerpo)}")
    print(f"  Parece HTML?       : {'SI' if parece_html else 'no'}")
    print("  ---- primeros 400 caracteres ----")
    print(inicio if inicio else "(respuesta vacia)")
    print("============================================================\n")


def main() -> None:
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cliente = ClienteEducado(contacto=cfg.get("contacto", "calibracion"))
    cliente.cargar_robots()
    print("robots.txt cargado; el cliente respetará sus reglas.\n")
    FIXTURES.mkdir(parents=True, exist_ok=True)

    # ---------------- sitemap de novedades (OPCIONAL) ----------------
    print(f"Descargando sitemap: {URL_SITEMAP}")
    entradas = []
    try:
        r = cliente.get(URL_SITEMAP)
        _diagnostico(r)
        entradas = parsear_sitemap(r.text or "")
        con_caption = [e for e in entradas if e.tiene_caption]
        sin_caption = [e for e in entradas if not e.tiene_caption]
        print(f"Sitemap OK! {len(entradas)} avisos "
              f"({len(con_caption)} con caption, {len(sin_caption)} sin caption)")
        if con_caption:
            e = con_caption[0]
            print(f"Ejemplo de caption parseado (aviso {e.id_aviso}): "
                  f"{parsear_entrada(e.titulo, e.caption)}")
    except Exception as exc:
        print(f"Sitemap NO es XML (caído desde 2026-06); se omite. Detalle: {exc}")

    # ---------------- índice (resiliente) + muestras de detalle ----------------
    calibrar_indice(cliente, entradas)
    print("\nListo.")


def calibrar_indice(cliente, entradas_sitemap=()) -> None:
    """Captura un fixture REAL de página de categoría y valida el parseo.

    La lista de categorías es resiliente (`urls_categoria`): el sitemap de grupos
    si sirve XML, o los slugs del HISTORIAL si no. Con UN GET, el
    `<input name="json">` trae el catálogo completo (K_Avisos) y los objetos ricos
    de la página 1 (Avisos).
    """
    print("\n================ ÍNDICE (páginas de categoría) ================")
    categorias = {s["categoria"] for s in estado_actual().values() if s.get("categoria")}
    urls, fuente = urls_categoria(cliente, categorias)
    print(f"Categorías a calibrar (fuente: {fuente}): {len(urls)}")
    if not urls:
        print("Sin categorías (¿historial vacío y sitemap de grupos caído?).")
        return

    url_cat = urls[0]
    slug, numero = partes_categoria(url_cat)
    print(f"Muestra: {slug} ({numero}) -> {url_cat}")
    ids: list[str] = []
    try:
        html = cliente.get(url_cat).text
        ruta = FIXTURES / f"indice_{slug}_p1.html"
        ruta.write_text(html, encoding="utf-8")
        ids, total = ids_categoria(html)
        avisos = parsear_avisos(html, slug)
        print(f"  {ruta.name} | K_Avisos: {len(ids)} (la página declara {total}) | "
              f"objetos ricos en pág. 1: {len(avisos)}")
        if not ids:
            print("  OJO: 0 ids -> el <input name='json'> cambió de formato; "
                  "afinar scraper/indice.py")
        elif total > len(ids):
            print(f"  NOTA: catálogo truncado ({total} declarados, {len(ids)} en "
                  f"K_Avisos): el sitio corta a 500; usa slugs por zona.")
    except Exception as exc:
        print(f"  Descarga/parseo de la categoría FALLÓ: {exc}")

    # Muestras de detalle: del sitemap si lo hubo; si no, de los ids del índice.
    if entradas_sitemap:
        muestras = [e.url for e in list(entradas_sitemap)[:3]]
    else:
        muestras = [f"{BASE}/Detalle/BienesRaices?Aviso={i}" for i in ids[:3]]
    for url in muestras:
        try:
            rd = cliente.get(url)
        except Exception as exc:
            print(f"Detalle {url}: no se pudo descargar ({exc})")
            continue
        idv = url.rsplit("=", 1)[-1]
        (FIXTURES / f"detalle_{idv}.html").write_text(rd.text, encoding="utf-8")
        campos = parsear_detalle(rd.text)
        ok = [k for k in ("tipo_transaccion", "tipo_inmueble", "precio", "zona",
                          "descripcion") if k in campos]
        print(f"Detalle {idv} -> campos clave: {ok or 'NINGUNO - afinar detail_parser.py'}")
    print("===============================================================")


if __name__ == "__main__":
    main()
