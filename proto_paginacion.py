#!/usr/bin/env python3
"""Reverse-engineering ciclo 3: encontrar el payload exacto de la página 2.

El JS hace: $("#hdnPagina").val(pagina); $("#frmResultadosxTex").submit() -> POST
/Portada/PostIndice. Replicarlo tal cual devolvió la página 1. Probamos variantes
del payload para ver cuál AVANZA de página (mide ids nuevos vs página 1).
"""
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
        if d and d.get("Registros", 0) > len(d.get("Avisos", [])) > 0:
            url_cat, data1, html1 = u, d, h
            break
    if not url_cat:
        print("sin categoría multipágina"); return
    slug, _ = partes_categoria(url_cat)
    P1 = {str(o.get("K_Av")) for o in data1.get("Avisos", [])}
    print(f"Categoría {slug} | Registros={data1.get('Registros')} | page1 ids[:3]={list(P1)[:3]}")

    base = _campos(html1)
    HEADERS["Referer"] = url_cat

    # Variante A: tal cual, pagina=2
    a = dict(base); a["pagina"] = "2"
    # Variante B: pagina=2 + json vacío (forzar recomputo del server)
    b = dict(base); b["pagina"] = "2"; b["json"] = ""
    # Variante C: pagina=2 + json con Avisos=[] (que no pueda "eco" la pág.1)
    c = dict(base); c["pagina"] = "2"
    try:
        jc = json.loads(base.get("json") or "{}"); jc["Avisos"] = []
        c["json"] = json.dumps(jc, ensure_ascii=False)
    except Exception as e:
        c = None; print("no pude rearmar json:", e)
    # Variante D: pagina=1 -> 0-indexado? probamos "1" a ver si difiere de "2"
    d1 = dict(base); d1["pagina"] = "1"

    pruebas = [("A pagina=2", a), ("B pagina=2 json=''", b)]
    if c:
        pruebas.append(("C pagina=2 Avisos=[]", c))
    pruebas.append(("D pagina=1", d1))
    for nombre, campos in pruebas:
        code, ids = _post(cli, campos, HEADERS)
        print(f"  {nombre:28} -> HTTP {code} Avisos={len(ids)} "
              f"NUEVOS_vs_p1={len(set(ids) - P1)} first3={ids[:3]}")

    # Variante E: token también en header
    e = dict(base); e["pagina"] = "2"
    he = dict(HEADERS); he["RequestVerificationToken"] = base.get("__RequestVerificationToken", "")
    code, ids = _post(cli, e, he)
    print(f"  {'E token-en-header':28} -> HTTP {code} Avisos={len(ids)} "
          f"NUEVOS_vs_p1={len(set(ids) - P1)} first3={ids[:3]}")

    print("\nVEREDICTO: la variante con NUEVOS≈página completa es la que pagina.")


if __name__ == "__main__":
    main()
