#!/usr/bin/env python3
"""Prototipo (Camino B): ¿se puede paginar el índice?

La página de categoría no tiene enlaces GET a la página 2; el paginador es un
POST a /Portada/PostIndice desde el form `frmResultadosxTex`, con el campo
`pagina` y el token antiforgery. Este prototipo prueba si replicando ese POST
(misma sesión -> misma cookie antiforgery) el sitio devuelve los avisos ricos de
la página 2. Corre en GitHub Actions (el runner sí alcanza el sitio).
"""
import json
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from scraper.http_polite import BASE, ClienteEducado
from scraper.indice import descargar_grupos, extraer_busqueda, partes_categoria

POST_URL = f"{BASE}/Portada/PostIndice"


def _campos_form(html: str) -> dict | None:
    f = BeautifulSoup(html, "html.parser").find("form", id="frmResultadosxTex")
    if not f:
        return None
    return {i.get("name"): (i.get("value") or "") for i in f.find_all("input") if i.get("name")}


def main() -> None:
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cli = ClienteEducado(contacto=cfg.get("contacto", "proto"))
    cli.cargar_robots()

    # Elegir una categoría con varias páginas (Registros > tamaño de página).
    url_cat = data1 = html1 = None
    for u in descargar_grupos(cli):
        h = cli.get(u).text
        d = extraer_busqueda(h)
        if d and d.get("Registros", 0) > len(d.get("Avisos", [])) > 0:
            url_cat, data1, html1 = u, d, h
            break
    if not url_cat:
        print("No encontré categoría multipágina.")
        return

    slug, num = partes_categoria(url_cat)
    ids_kav = [str(x) for x in data1.get("K_Avisos", [])]
    ids_p1 = [str(o.get("K_Av")) for o in data1.get("Avisos", [])]
    print(f"Categoría: {slug} ({num}) | Registros={data1.get('Registros')} | "
          f"Avisos pág.1={len(ids_p1)} | K_Avisos={len(ids_kav)}")

    campos = _campos_form(html1)
    if not campos:
        print("No se encontró el form frmResultadosxTex.")
        return
    print("token presente:", bool(campos.get("__RequestVerificationToken")))

    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": url_cat,
        "Origin": BASE,
        "Accept": "application/json, text/plain, */*",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

    # Recorre las páginas 1..N por POST y mide cuántos avisos NUEVOS trae cada una
    # (decisivo: si 'pagina' se ignora, cada página repite la 1 -> nuevos≈0).
    vistos = set(ids_p1)
    print(f"\npág.1 (GET): Avisos={len(ids_p1)}  (acumulado únicos={len(vistos)})")
    for pg in (2, 3):
        campos["pagina"] = str(pg)
        r = cli.sesion.post(POST_URL, data=campos, headers=headers, timeout=30)
        if "charset=" not in r.headers.get("Content-Type", "").lower():
            r.encoding = "utf-8"
        try:
            d = json.loads(r.text)
        except ValueError:
            d = extraer_busqueda(r.text)
        if not isinstance(d, dict):
            print(f"pág.{pg} (POST): HTTP {r.status_code} -> no interpretable: {r.text[:160]!r}")
            return
        av = d.get("Avisos") or []
        ids = [str(o.get("K_Av")) for o in av]
        nuevos = set(ids) - vistos
        print(f"pág.{pg} (POST): HTTP {r.status_code} Avisos={len(av)} "
              f"NUEVOS={len(nuevos)} (acumulado únicos={len(vistos | set(ids))})")
        if av:
            o = av[0]
            print("   muestra:", {k: o.get(k) for k in ("K_Av", "Precio", "ZonMun", "Col", "K_Cla3")})
        vistos |= set(ids)

    print(f"\nÚnicos acumulados pág.1-3: {len(vistos)} de Registros={data1.get('Registros')} "
          f"(K_Avisos={len(ids_kav)})")
    print("VEREDICTO: si cada página POST trae ~", len(ids_p1),
          "NUEVOS, la paginación avanza y Camino B sirve.")


if __name__ == "__main__":
    main()
