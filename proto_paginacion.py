#!/usr/bin/env python3
"""Sonda iter 3 — el servidor hidrata los K_Avisos que le mando.

Hallazgos previos: el POST a /Portada/PostIndice devuelve SIEMPRE el primer tramo
(23) y NO lee `pagina`, ni `ClavAviso`, ni la cookie `Pagina`. El JS (btnPaginacion
en UtilComplementos) recalcula la página y reenvía el form; el payload de búsqueda
(`jsonBusqueda`) trae `maxRegs:500, firstRegs:23` (tamaño/offset). Hipótesis:

  A) el servidor hidrata los ids de `json.K_Avisos` que YO mando (cap = tamaño de
     página). Como ya tengo TODOS los K_Avisos de la categoría, basta mandar tramos.
  B) subir `firstRegs`/`maxRegs` en `jsonBusqueda` devuelve un lote grande de una.

Prueba ambas y vuelca el btnPaginacion completo y el jsonBusqueda real.
"""
import json
import re
import time
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from scraper.http_polite import BASE, ClienteEducado
from scraper.indice import descargar_grupos, extraer_busqueda, partes_categoria

POST_URL = f"{BASE}/Portada/PostIndice"


def _form_campos(html):
    f = BeautifulSoup(html, "html.parser").find("form", id="frmResultadosxTex")
    campos = {i.get("name"): (i.get("value") or "")
              for i in f.find_all("input") if i.get("name")}
    return campos, campos.get("__RequestVerificationToken")


def _post(cli, campos, headers):
    time.sleep(1.0)
    r = cli.sesion.post(POST_URL, data=campos, headers=headers, timeout=30)
    if "charset=" not in r.headers.get("Content-Type", "").lower():
        r.encoding = "utf-8"
    try:
        d = json.loads(r.text)
    except ValueError:
        d = extraer_busqueda(r.text)
    av = d.get("Avisos", []) if isinstance(d, dict) else []
    ids = [str(o.get("K_Av")) for o in av if isinstance(o, dict) and o.get("K_Av")]
    return r, ids


def _elegir_categoria(cli):
    urls = descargar_grupos(cli)
    urls.sort(key=lambda u: 0 if "casa" in u.lower() else 1)
    for u in urls[:14]:
        h = cli.get(u).text
        d = extraer_busqueda(h)
        if d and d.get("Registros", 0) > 100:
            return u, h, d
    return None, None, None


def main():
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cli = ClienteEducado(contacto=cfg.get("contacto", "proto"), seg_entre_solicitudes=1.0)
    cli.cargar_robots()

    # --- volcar btnPaginacion completo ---
    print("===== btnPaginacion (UtilComplementos.min.js) =====")
    js = cli.get(BASE + "/js/min/UtilComplementos.min.js").text
    i = js.find("function btnPaginacion")
    print(js[i:i + 1500] if i >= 0 else "no encontrado")

    print("\n===== categoría =====")
    url_cat, html1, data1 = _elegir_categoria(cli)
    if not url_cat:
        print("sin categoría grande"); return
    slug, _ = partes_categoria(url_cat)
    kav = [str(x) for x in data1.get("K_Avisos", [])]
    reg = data1.get("Registros")
    base, tok = _form_campos(html1)
    print(f"{slug} | Registros={reg} | K_Avisos={len(kav)}")
    print(f"jsonBusqueda REAL: {base.get('jsonBusqueda')}")
    try:
        jj = json.loads(base["json"]); jb = json.loads(base["jsonBusqueda"])
    except Exception as e:
        print("no parsea json/jsonBusqueda:", e); return
    print(f"json keys={list(jj)} K_Avisos_en_json={len(jj.get('K_Avisos', []))}")

    headers = {
        "X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": url_cat,
        "Accept": "application/json, text/plain, */*", "RequestVerificationToken": tok or "",
        "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
    }

    def prueba(nombre, campos, esperado_prefijo=None):
        _, ids = _post(cli, campos, headers)
        ok = (ids[:len(esperado_prefijo)] == esperado_prefijo) if esperado_prefijo else None
        print(f"  [{nombre}] Avisos={len(ids)} first={ids[:2]} last={ids[-1:]} "
              f"¿prefijo esperado? {ok}")
        return ids

    print("\n===== TEST A: mandar json.K_Avisos = tramo de ids que ya tengo =====")
    # A1: tramo página 2 (23 ids)
    jjA = dict(jj); jjA["K_Avisos"] = [int(x) for x in kav[23:46]]
    cA = dict(base); cA["json"] = json.dumps(jjA, ensure_ascii=False)
    prueba("A1 K_Avisos[23:46]", cA, kav[23:46])
    # A2: tramo grande (92 ids) — ¿respeta el tamaño o capa en 23?
    jjA2 = dict(jj); jjA2["K_Avisos"] = [int(x) for x in kav[23:115]]
    cA2 = dict(base); cA2["json"] = json.dumps(jjA2, ensure_ascii=False)
    prueba("A2 K_Avisos[23:115] (92)", cA2, kav[23:28])

    print("\n===== TEST B: subir firstRegs/maxRegs en jsonBusqueda =====")
    print(f"  jsonBusqueda keys={list(jb)}")
    jbB = dict(jb)
    for k in list(jbB):
        if k.lower() == "firstregs":
            jbB[k] = 300
        if k.lower() == "maxregs":
            jbB[k] = 300
    jbB.setdefault("firstRegs", 300)
    cB = dict(base); cB["jsonBusqueda"] = json.dumps(jbB, ensure_ascii=False)
    prueba("B firstRegs/maxRegs=300", cB)

    print("\nFIN sonda iter 3")


if __name__ == "__main__":
    main()
