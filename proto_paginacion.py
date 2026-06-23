#!/usr/bin/env python3
"""Sonda iter 4 — escribe el resultado a un archivo versionado (no solo al log).

calibrate.yml hace `git add tests/fixtures` y commitea si hay cambios; por eso el
resultado se vuelca a tests/fixtures/_paginacion_resultado.txt y se puede leer con
`git fetch` (sin depender de leer el log de Actions, que ha estado intermitente).

Mecanismo ya confirmado: /Portada/PostIndice IGNORA `pagina`, `ClavAviso` y la
cookie `Pagina`; el servidor re-corre la búsqueda según `jsonBusqueda`
(trae `maxRegs`, `firstRegs`). Pruebas decisivas:
  A) mandar `json.K_Avisos` = un tramo de ids -> ¿hidrata ese tramo?
  B) subir `firstRegs`/`maxRegs` en `jsonBusqueda` -> ¿devuelve un lote grande
     (idealmente TODA la categoría) en un solo POST?
"""
import json
import time
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from scraper.http_polite import BASE, ClienteEducado
from scraper.indice import descargar_grupos, extraer_busqueda, partes_categoria

POST_URL = f"{BASE}/Portada/PostIndice"
SALIDA = Path("tests/fixtures/_paginacion_resultado.txt")
_buf: list[str] = []


def log(*a):
    linea = " ".join(str(x) for x in a)
    print(linea, flush=True)
    _buf.append(linea)


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

    url_cat, html1, data1 = _elegir_categoria(cli)
    if not url_cat:
        log("sin categoría grande"); return
    slug, _ = partes_categoria(url_cat)
    kav = [str(x) for x in data1.get("K_Avisos", [])]
    reg = data1.get("Registros")
    base, tok = _form_campos(html1)
    log(f"Categoría {slug} | Registros={reg} | K_Avisos={len(kav)}")
    try:
        jj = json.loads(base["json"]); jb = json.loads(base["jsonBusqueda"])
    except Exception as e:
        log("no parsea json/jsonBusqueda:", e); return
    log(f"jsonBusqueda keys={list(jb)}")
    log(f"jsonBusqueda={base['jsonBusqueda'][:400]}")

    headers = {
        "X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": url_cat,
        "Accept": "application/json, text/plain, */*", "RequestVerificationToken": tok or "",
        "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
    }

    def prueba(nombre, campos, esperado=None):
        _, ids = _post(cli, campos, headers)
        ok = (ids[:len(esperado)] == esperado) if esperado else None
        unicos = len(set(ids))
        log(f"  [{nombre}] Avisos={len(ids)} únicos={unicos} first={ids[:2]} "
            f"last={ids[-1:]} ¿prefijo? {ok}")
        return ids

    log("\n== TEST A: json.K_Avisos = tramo de ids ==")
    jjA = dict(jj); jjA["K_Avisos"] = [int(x) for x in kav[23:46]]
    cA = dict(base); cA["json"] = json.dumps(jjA, ensure_ascii=False)
    prueba("A1 ids[23:46]", cA, kav[23:46])
    jjA2 = dict(jj); jjA2["K_Avisos"] = [int(x) for x in kav[23:115]]
    cA2 = dict(base); cA2["json"] = json.dumps(jjA2, ensure_ascii=False)
    prueba("A2 ids[23:115] (92)", cA2, kav[23:28])

    log("\n== TEST B: subir firstRegs/maxRegs en jsonBusqueda ==")
    for tam in (300, reg):
        jbB = dict(jb)
        for k in list(jbB):
            if k.lower() in ("firstregs", "maxregs"):
                jbB[k] = int(tam)
        jbB.setdefault("firstRegs", int(tam)); jbB.setdefault("maxRegs", int(tam))
        cB = dict(base); cB["jsonBusqueda"] = json.dumps(jbB, ensure_ascii=False)
        ids = prueba(f"B firstRegs/maxRegs={tam}", cB)
        log(f"     ¿cubre toda la categoría? {len(set(ids)) >= (reg or 0)} "
            f"(únicos={len(set(ids))} vs Registros={reg})")

    log("\nFIN sonda iter 4")


if __name__ == "__main__":
    try:
        main()
    finally:
        SALIDA.parent.mkdir(parents=True, exist_ok=True)
        SALIDA.write_text("\n".join(_buf) + "\n", encoding="utf-8")
        print(f"[resultado escrito en {SALIDA}]", flush=True)
