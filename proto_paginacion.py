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
    print("Campos del form:", sorted(campos))
    print("token presente:", bool(campos.get("__RequestVerificationToken")))
    campos["pagina"] = "2"

    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": url_cat,
        "Origin": BASE,
        "Accept": "application/json, text/plain, */*",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    r = cli.sesion.post(POST_URL, data=campos, headers=headers, timeout=30)
    if "charset=" not in r.headers.get("Content-Type", "").lower():
        r.encoding = "utf-8"
    print(f"\nPOST {POST_URL} (pagina=2) -> HTTP {r.status_code} | "
          f"Content-Type={r.headers.get('Content-Type')} | {len(r.text)} chars")
    print("primeros 300 chars:", repr(r.text[:300]))

    d2 = None
    try:
        d2 = json.loads(r.text)
    except ValueError:
        d2 = extraer_busqueda(r.text)   # por si devuelve HTML con el <input json>
    if not isinstance(d2, dict):
        print("\nRESULTADO: no pude interpretar la respuesta (¿token/cookie/headers?). "
              "Camino B necesita más trabajo o no aplica.")
        return

    av2 = d2.get("Avisos") or (d2.get("d", {}) if isinstance(d2.get("d"), dict) else {}).get("Avisos") or []
    ids_p2 = [str(o.get("K_Av")) for o in av2]
    print(f"\nRESPUESTA pág.2: claves={list(d2)[:10]} | Avisos={len(av2)}")
    print("  ids pág.2 (primeros):", ids_p2[:5])
    print("  ¿distintos de pág.1?:", bool(ids_p2) and set(ids_p2).isdisjoint(ids_p1))
    print("  ¿dentro de K_Avisos?:", bool(ids_p2) and set(ids_p2) <= set(ids_kav))
    if av2:
        o = av2[0]
        print("  muestra:", {k: o.get(k) for k in
                             ("K_Av", "Precio", "m2Precio", "ZonMun", "Col", "K_Cla2", "K_Cla3")})
        print("\nRESULTADO: ✅ Camino B FUNCIONA — la página 2 trae avisos ricos con precio.")
    else:
        print("\nRESULTADO: respuesta interpretable pero SIN Avisos; revisar formato.")


if __name__ == "__main__":
    main()
