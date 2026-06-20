#!/usr/bin/env python3
"""Calibración con diagnóstico: si el sitemap no llega como XML válido, muestra
QUÉ respondió el sitio para saber si nos bloquea o nos redirige."""
from pathlib import Path

import yaml

from scraper.caption_parser import parsear_entrada
from scraper.detail_parser import parsear_detalle
from scraper.http_polite import ClienteEducado
from scraper.indice import (
    URL_GRUPOS,
    _parsear_grupos,
    iterar_paginas,
    parsear_paginacion,
    parsear_tarjetas,
    partes_categoria,
)
from scraper.sitemap import URL_SITEMAP, parsear_sitemap

FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def main() -> None:
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cliente = ClienteEducado(contacto=cfg.get("contacto", "calibracion"))
    cliente.cargar_robots()
    print("robots.txt cargado; el cliente respetará sus reglas.\n")

    print(f"Descargando sitemap: {URL_SITEMAP}")
    try:
        r = cliente.get(URL_SITEMAP)
    except Exception as exc:
        print(f"ERROR al pedir el sitemap: {exc}")
        raise SystemExit(1)

    cuerpo = r.text or ""
    inicio = cuerpo.lstrip()[:400]
    parece_html = inicio[:200].lower().lstrip().startswith(("<!doctype", "<html"))

    print("\n================ DIAGNOSTICO DE LA RESPUESTA ================")
    print(f"  Codigo HTTP        : {r.status_code}")
    print(f"  URL final          : {r.url}")
    print(f"  Content-Type       : {r.headers.get('Content-Type', '(no informado)')}")
    print(f"  Content-Encoding   : {r.headers.get('Content-Encoding', '(ninguno)')}")
    print(f"  Tamano (caracteres): {len(cuerpo)}")
    print(f"  Parece HTML?       : {'SI' if parece_html else 'no'}")
    print("  ---- primeros 400 caracteres ----")
    print(inicio if inicio else "(respuesta vacia)")
    print("============================================================\n")

    try:
        entradas = parsear_sitemap(cuerpo)
    except Exception as exc:
        print("No se pudo interpretar la respuesta como XML del sitemap.")
        print("El bloque DIAGNOSTICO de arriba dice que respondio el sitio.")
        print(f"Detalle tecnico: {exc}")
        raise SystemExit(1)

    con_caption = [e for e in entradas if e.tiene_caption]
    sin_caption = [e for e in entradas if not e.tiene_caption]
    print(f"Sitemap OK! {len(entradas)} avisos "
          f"({len(con_caption)} con caption, {len(sin_caption)} sin caption)")
    print("Compara ese total con el contador 'Bienes Raices N' del sitio web.\n")

    FIXTURES.mkdir(parents=True, exist_ok=True)
    if con_caption:
        e = con_caption[0]
        print(f"Ejemplo de caption parseado (aviso {e.id_aviso}):")
        print(f"  titulo : {e.titulo}")
        print(f"  campos : {parsear_entrada(e.titulo, e.caption)}\n")

    muestras = (sin_caption[:2] + con_caption[:1]) or entradas[:3]
    for e in muestras:
        try:
            rd = cliente.get(e.url)
        except Exception as exc:
            print(f"Detalle {e.id_aviso}: no se pudo descargar ({exc})")
            continue
        ruta = FIXTURES / f"detalle_{e.id_aviso}.html"
        ruta.write_text(rd.text, encoding="utf-8")
        campos = parsear_detalle(rd.text)
        ok = [k for k in ("tipo_transaccion", "tipo_inmueble", "precio", "zona",
                          "descripcion") if k in campos]
        print(f"Detalle {e.id_aviso} -> {ruta.name} | campos clave: "
              f"{ok or 'NINGUNO - afinar detail_parser.py'}")

    calibrar_indice(cliente)
    print("\nListo.")


def calibrar_indice(cliente) -> None:
    """Captura fixtures REALES de páginas de categoría y valida el parseo.

    Corre en GitHub Actions (cuyo runner sí alcanza el sitio); guarda el HTML en
    tests/fixtures/ para que las pruebas no dependan de descargas en vivo.
    """
    print("\n================ ÍNDICE (páginas de categoría) ================")
    print(f"Descargando sitemap de grupos: {URL_GRUPOS}")
    try:
        r = cliente.get(URL_GRUPOS)
        r.raise_for_status()
    except Exception as exc:
        print(f"ERROR al pedir el sitemap de grupos: {exc}")
        return

    urls = _parsear_grupos(r.text)
    print(f"Categorías en el índice: {len(urls)}")
    if not urls:
        print("El sitemap de grupos no trajo URLs de categoría; revisa el formato.")
        return

    # Capturamos una categoría con varias páginas (hasta 2) como muestra.
    url_cat = urls[0]
    slug, numero = partes_categoria(url_cat)
    print(f"Muestra: {slug} ({numero}) -> {url_cat}")
    total_tarjetas = 0
    for i, pag in enumerate(iterar_paginas(cliente, url_cat, max_paginas=2), start=1):
        if not pag.ok or pag.html is None:
            print(f"  Página {i}: descarga FALLÓ ({pag.url})")
            continue
        ruta = FIXTURES / f"indice_{slug}_p{i}.html"
        ruta.write_text(pag.html, encoding="utf-8")
        actual, total = parsear_paginacion(pag.html)
        tarjetas = parsear_tarjetas(pag.html, slug)
        total_tarjetas += len(tarjetas)
        print(f"  Página {i}: {ruta.name} | 'Pág. {actual} de {total}' | "
              f"{len(tarjetas)} tarjetas")
        if tarjetas:
            t = tarjetas[0]
            claves = {k: t.get(k) for k in (
                "id_aviso", "tipo_transaccion", "tipo_inmueble", "zona",
                "colonia", "precio", "precio_unidad")}
            print(f"    1ª tarjeta: {claves}")
            faltan = [k for k in ("id_aviso", "tipo_transaccion", "precio") if not t.get(k)]
            if faltan:
                print(f"    OJO faltan campos clave {faltan} -> afinar scraper/indice.py")
    print(f"Total de tarjetas parseadas en la muestra: {total_tarjetas}")
    print("Compara con el contador 'N resultados' de la página de categoría.")
    print("===============================================================")


if __name__ == "__main__":
    main()