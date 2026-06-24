#!/usr/bin/env python3
"""Sonda iter 6 — prueba DEFINITIVA por conjuntos (no por orden).

Iter 5 mostró que cada POST devuelve 23 avisos DISTINTOS según los K_Avisos que
mando, pero mi comprobación era por ORDEN (falsos negativos). Hipótesis: el
servidor hidrata 23 de los ids que le envío en `json.K_Avisos`. Aquí se mide por
CONJUNTO: ¿lo recibido está contenido en lo enviado? ¿coincide un tramo de 23?

Si se confirma, la paginación se resuelve mandando los ids (que ya tenemos de la
página 1) en lotes de 23.
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
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    _buf.append(s)


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
    kav = [str(x) for x in data1.get("K_Avisos", [])]
    reg = data1.get("Registros")
    base, tok = _form_campos(html1)
    jj = json.loads(base["json"])
    log(f"{slug} | Registros={reg} | K_Avisos={len(kav)}")

    headers = {
        "X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": url_cat,
        "Accept": "application/json, text/plain, */*", "RequestVerificationToken": tok or "",
        "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
    }

    def check(nombre, enviar):
        jjX = dict(jj); jjX["K_Avisos"] = [int(x) for x in enviar]
        cX = dict(base); cX["json"] = json.dumps(jjX, ensure_ascii=False)
        try:
            ids = _post(cli, cX, headers)
        except Exception as e:
            log(f"  [{nombre}] EXCEPCIÓN {e}"); return
        env, got = set(enviar), set(ids)
        log(f"  [{nombre}] envié={len(enviar)} recibí={len(ids)} ∩={len(env & got)} "
            f"⊆enviados={got <= env} igual_conjunto={env == got}")
        log(f"      enviados[:4]={enviar[:4]}")
        log(f"      recibidos[:4]={ids[:4]}")

    log("\n== ¿el servidor hidrata los ids que le mando? ==")
    check("2 ids concretos", [kav[100], kav[200]])
    check("pagina A kav[0:23]", kav[0:23])
    check("pagina B kav[23:46]", kav[23:46])
    check("pagina C kav[46:69]", kav[46:69])
    check("lote 60 kav[60:120]", kav[60:120])

    log("\nFIN sonda iter 6")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("EXCEPCIÓN:\n" + traceback.format_exc())
    finally:
        print("\n".join(_buf), flush=True)  # asegura que todo quede en el log
