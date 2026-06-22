#!/usr/bin/env python3
"""RE ciclo 4 (decisivo): caminar páginas 1..6 por POST y ver si el conjunto
único crece ~23 por página (paginación limpia) o se estanca (estado/bug)."""
import json
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from scraper.http_polite import BASE, ClienteEducado
from scraper.indice import descargar_grupos, extraer_busqueda, partes_categoria

POST_URL = f"{BASE}/Portada/PostIndice"
HEADERS = {
    "X-Requested-With": "XMLHttpRequest", "Origin": BASE,
    "Accept": "application/json, text/plain, */*",
    "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
}


def _campos(html):
    f = BeautifulSoup(html, "html.parser").find("form", id="frmResultadosxTex")
    return {i.get("name"): (i.get("value") or "") for i in f.find_all("input") if i.get("name")}


def _post(cli, campos, headers):
    r = cli.sesion.post(POST_URL, data=campos, headers=headers, timeout=30)
    if "charset=" not in r.headers.get("Content-Type", "").lower():
        r.encoding = "utf-8"
    try:
        d = json.loads(r.text)
    except ValueError:
        d = extraer_busqueda(r.text)
    av = d.get("Avisos", []) if isinstance(d, dict) else []
    return r.status_code, [str(o.get("K_Av")) for o in av]


def main():
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cli = ClienteEducado(contacto=cfg.get("contacto", "proto"))
    cli.cargar_robots()
    url_cat = data1 = html1 = None
    for u in descargar_grupos(cli):
        h = cli.get(u).text
        d = extraer_busqueda(h)
        if d and d.get("Registros", 0) > 60:   # varias páginas
            url_cat, data1, html1 = u, d, h
            break
    if not url_cat:
        print("sin categoría grande"); return
    slug, _ = partes_categoria(url_cat)
    reg = data1.get("Registros")
    print(f"Categoría {slug} | Registros={reg} | K_Avisos={len(data1.get('K_Avisos', []))}")

    base = _campos(html1)
    HEADERS["Referer"] = url_cat
    kav = {str(x) for x in data1.get("K_Avisos", [])}

    todos = set()
    for pg in range(1, 7):
        campos = dict(base)
        campos["pagina"] = str(pg)
        code, ids = _post(cli, campos, HEADERS)
        nuevos = len(set(ids) - todos)
        todos |= set(ids)
        dentro = len(set(ids) & kav)
        print(f"  pagina={pg}: HTTP {code} Avisos={len(ids)} NUEVOS={nuevos} "
              f"(acum.únicos={len(todos)}) enKAvisos={dentro} first2={ids[:2]}")

    print(f"\nÚnicos acumulados pág.1-6: {len(todos)}  (esperado ~{6 * 23} si pagina limpio; "
          f"Registros={reg})")
    print("VEREDICTO B:", "FUNCIONA (crece ~23/pág)" if len(todos) >= 100
          else "NO avanza limpio (estado/bug) -> usar Camino A")


if __name__ == "__main__":
    main()
