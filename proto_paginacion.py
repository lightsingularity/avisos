#!/usr/bin/env python3
"""Reverse-engineering ciclo 2: leer el JS minificado del paginador.

Los onclick llaman btnPaginacionDirecta()/btnPaginacion()/RecuperarAvisos(), que
están en /js/min/*.js. Descargamos esos archivos y volcamos el código alrededor
de 'PostIndice' y de esas funciones para ver EXACTAMENTE qué payload arma el
paginador (qué campo lleva la página y/o los ids). Corre en GitHub Actions.
"""
import re
from pathlib import Path

import yaml

from scraper.http_polite import BASE, ClienteEducado

JS = [
    "/js/min/UtilBusqueda.min.js",
    "/js/min/Portada.min.js",
    "/js/min/Util.min.js",
    "/js/min/UtilComplementos.min.js",
]
TOKENS = ["PostIndice", "btnPaginacionDirecta", "btnPaginacion",
          "function Paginacion", "RecuperarAvisos", "hdnPagina", "ObtenerAvisos"]


def main() -> None:
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cli = ClienteEducado(contacto=cfg.get("contacto", "proto"))
    cli.cargar_robots()
    for ruta in JS:
        url = BASE + ruta
        try:
            txt = cli.get(url).text
        except Exception as exc:
            print(f"\n==== {ruta}: FALLO {exc}")
            continue
        print(f"\n==== {ruta}  ({len(txt)} chars) ====")
        for tok in TOKENS:
            hits = [m.start() for m in re.finditer(re.escape(tok), txt)]
            if not hits:
                continue
            print(f"  -- {tok}: {len(hits)} hit(s)")
            for i in hits[:4]:
                frag = txt[max(0, i - 80):i + 360].replace("\n", " ")
                print(f"     …{frag}…")


if __name__ == "__main__":
    main()
