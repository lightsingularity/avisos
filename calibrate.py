#!/usr/bin/env python3
"""Calibración — CORRER EN TU MÁQUINA (con acceso a internet), una sola vez.

Descarga el sitemap y unas páginas de detalle reales, las guarda como fixtures
en tests/fixtures/ y reporta qué estrategias de parseo funcionan. Si el parser
de detalle necesita ajustes, abre la carpeta con Claude Code y pídele que afine
scraper/detail_parser.py contra los fixtures descargados.

Uso:  python calibrate.py
"""
from pathlib import Path

import yaml

from scraper.detail_parser import parsear_detalle
from scraper.caption_parser import parsear_entrada
from scraper.http_polite import ClienteEducado
from scraper.sitemap import descargar_sitemap

FIXTURES = Path(__file__).parent / "tests" / "fixtures"


def main() -> None:
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cliente = ClienteEducado(contacto=cfg.get("contacto", "calibracion@ejemplo.com"))
    cliente.cargar_robots()
    print("robots.txt cargado; el cliente respetará sus reglas.\n")

    entradas = descargar_sitemap(cliente)
    con_caption = [e for e in entradas if e.tiene_caption]
    sin_caption = [e for e in entradas if not e.tiene_caption]
    print(f"Sitemap: {len(entradas)} avisos "
          f"({len(con_caption)} con caption, {len(sin_caption)} sin caption)")
    print("Compara ese total con el contador 'Bienes Raíces N' del sitio web.\n")

    FIXTURES.mkdir(parents=True, exist_ok=True)

    if con_caption:
        e = con_caption[0]
        print(f"Ejemplo de caption parseado (aviso {e.id_aviso}):")
        print(f"  título : {e.titulo}")
        print(f"  campos : {parsear_entrada(e.titulo, e.caption)}\n")

    muestras = (sin_caption[:2] + con_caption[:1]) or entradas[:3]
    for e in muestras:
        r = cliente.get(e.url)
        ruta = FIXTURES / f"detalle_{e.id_aviso}.html"
        ruta.write_text(r.text, encoding="utf-8")
        campos = parsear_detalle(r.text)
        print(f"Detalle {e.id_aviso} -> guardado en {ruta.name}")
        ok = [k for k in ("tipo_transaccion", "tipo_inmueble", "precio", "zona",
                          "descripcion") if k in campos]
        print(f"  extraído: {sorted(campos.keys()) or 'NADA'}")
        print(f"  campos clave presentes: {ok or 'NINGUNO — afinar detail_parser.py'}\n")

    print("Listo. Los fixtures quedaron en tests/fixtures/ — consérvalos en git:")
    print("son la red de seguridad contra rediseños del sitio.")


if __name__ == "__main__":
    main()
