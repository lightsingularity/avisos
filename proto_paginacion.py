#!/usr/bin/env python3
"""Sonda iter 7 — `firstRegs` como OFFSET + volcado completo de btnPaginacion.

Confirmado: PostIndice ignora pagina/ClavAviso/cookie/json.K_Avisos; devuelve 23
por llamada, distintos según el input. El form de página 1 ya trae firstRegs:23,
lo que sugiere que firstRegs es el ÍNDICE INICIAL (offset) de la página. Iter 5
falló porque cambié firstRegs Y maxRegs a la vez. Aquí se varía SOLO firstRegs y
se compara el CONJUNTO devuelto contra kav[off:off+23].
"""
import json
import time
import traceback
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from scraper.http_polite import BASE, ClienteEducado
from scraper.indice import extraer_busqueda, partes_categoria

POST_URL = f"{BASE}/Portada/PostIndice"
CANDIDATAS = [
    f"{BASE}/Portada/Indice/venta-casa-CARRETERA-NACIONAL/966501",
    f"{BASE}/Portada/Indice/venta-casa-MONTERREY/966501",
]
_buf: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); _buf.append(s)


def _func_completa(js, nombre):
    for pat in (f"function {nombre}", f"{nombre}=function", f"{nombre}:function"):
        i = js.find(pat)
        if i < 0:
            continue
        j = js.find("{", i); prof = 0
        for k in range(j, min(len(js), j + 4000)):
            if js[k] == "{":
                prof += 1
            elif js[k] == "}":
                prof -= 1
                if prof == 0:
                    return js[i:k + 1]
    return None


def _form_campos(html):
    f = BeautifulSoup(html, "html.parser").find("form", id="frmResultadosxTex")
    if not f:
        return {}, None
    c = {i.get("name"): (i.get("value") or "") for i in f.find_all("input") if i.get("name")}
    return c, c.get("__RequestVerificationToken")


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
    return [str(o.get("K_Av")) for o in av if isinstance(o, dict) and o.get("K_Av")]


def _categoria(cli):
    for u in CANDIDATAS:
        try:
            h = cli.get(u).text
            d = extraer_busqueda(h)
            if d and d.get("Registros", 0) > 100:
                return u, h, d
        except Exception as e:
            log(f"  cat {u} falló: {e}")
    return None, None, None


def main():
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cli = ClienteEducado(contacto=cfg.get("contacto", "proto"), seg_entre_solicitudes=1.0)
    cli.cargar_robots()

    # --- volcado COMPLETO de btnPaginacion ---
    js = cli.get(BASE + "/js/min/UtilComplementos.min.js").text
    cuerpo = _func_completa(js, "btnPaginacion")
    log("== btnPaginacion (completo) ==")
    log(cuerpo or "no encontrado")
    # ¿a qué función llama al final? (la que hace el POST)
    for fn in ("ResultadoBusquedaTexto", "BusquedaxTexto", "ResultadosxTexto",
               "PostResultados", "CargarResultados", "Paginar"):
        c = _func_completa(js, fn)
        if c:
            log(f"\n== {fn} ==\n{c[:700]}")

    log("\n== categoría ==")
    url_cat, html1, data1 = _categoria(cli)
    if not url_cat:
        log("sin categoría"); return
    slug, _ = partes_categoria(url_cat)
    kav = [str(x) for x in data1.get("K_Avisos", [])]
    reg = data1.get("Registros")
    base, tok = _form_campos(html1)
    jb = json.loads(base["jsonBusqueda"])
    log(f"{slug} | Registros={reg} | K_Avisos={len(kav)} | firstRegs_inicial={jb.get('firstRegs')}")

    headers = {
        "X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": url_cat,
        "Accept": "application/json, text/plain, */*", "RequestVerificationToken": tok or "",
        "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
    }

    log("\n== firstRegs como OFFSET (solo varío firstRegs; maxRegs intacto) ==")
    for off in (0, 23, 46, 69):
        jbX = dict(jb); jbX["firstRegs"] = off
        cX = dict(base); cX["jsonBusqueda"] = json.dumps(jbX, ensure_ascii=False)
        try:
            ids = _post(cli, cX, headers)
        except Exception as e:
            log(f"  firstRegs={off}: EXCEPCIÓN {e}"); continue
        esper = set(kav[off:off + 23])
        got = set(ids)
        log(f"  firstRegs={off}: recibí={len(ids)} ∩con kav[{off}:{off+23}]={len(esper & got)}/23 "
            f"igual={esper == got} first={ids[:2]}")

    log("\nFIN sonda iter 7")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("EXCEPCIÓN:\n" + traceback.format_exc())
    finally:
        print("\n".join(_buf), flush=True)
