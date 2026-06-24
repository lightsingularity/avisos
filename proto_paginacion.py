#!/usr/bin/env python3
"""Sonda iter 8 — DEFINITIVA: caminar firstRegs y medir cobertura de la categoría.

iter 7 mostró que variar SOLO firstRegs devuelve páginas distintas (es el offset);
el bajo solape con kav[off:off+23] es porque el server ordena distinto al array
K_Avisos. Lo único que importa para cosechar es que la UNIÓN cubra la categoría.
Aquí se camina firstRegs = 0,23,46,... hasta Registros y se compara la unión de
ids recibidos contra el conjunto K_Avisos (autoridad de la página 1).
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
    url_cat, html1, data1 = _categoria(cli)
    if not url_cat:
        log("sin categoría"); return
    slug, _ = partes_categoria(url_cat)
    kav = set(str(x) for x in data1.get("K_Avisos", []))
    reg = data1.get("Registros") or len(kav)
    base, tok = _form_campos(html1)
    jb = json.loads(base["jsonBusqueda"])
    log(f"{slug} | Registros={reg} | K_Avisos={len(kav)}")

    headers = {
        "X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": url_cat,
        "Accept": "application/json, text/plain, */*", "RequestVerificationToken": tok or "",
        "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
    }

    log("\n== caminar firstRegs 0,23,46,... y acumular unión ==")
    union: set[str] = set()
    paso_repetido = 0
    for off in range(0, reg + 23, 23):
        jbX = dict(jb); jbX["firstRegs"] = off
        cX = dict(base); cX["jsonBusqueda"] = json.dumps(jbX, ensure_ascii=False)
        try:
            ids = _post(cli, cX, headers)
        except Exception as e:
            log(f"  off={off}: EXCEPCIÓN {e}"); break
        nuevos = len(set(ids) - union)
        union |= set(ids)
        log(f"  off={off:3d}: recibí={len(ids)} nuevos={nuevos} unión={len(union)}")
        if not ids or nuevos == 0:
            paso_repetido += 1
            if paso_repetido >= 2:
                log("  (dos pasos sin nuevos; corto)"); break
        else:
            paso_repetido = 0

    cubiertos = len(union & kav)
    log(f"\nUNIÓN total={len(union)} | de K_Avisos cubiertos={cubiertos}/{len(kav)} "
        f"({cubiertos / max(1, len(kav)):.0%}) | fuera_de_kav={len(union - kav)}")
    log("VEREDICTO:", "✅ COSECHA COMPLETA por firstRegs" if cubiertos >= 0.9 * len(kav)
        else "❌ no cubre (ruido/estado)")
    log("\nFIN sonda iter 8")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("EXCEPCIÓN:\n" + traceback.format_exc())
    finally:
        print("\n".join(_buf), flush=True)
