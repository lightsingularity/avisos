#!/usr/bin/env python3
"""Sonda de paginación POST /Portada/PostIndice — hipótesis de COOKIE de estado.

Iteración 1 (cursor ClavAviso): el POST devuelve JSON correcto pero SIEMPRE la
página 1; el form `pagina` y `ClavAviso` se ignoran. Pista decisiva: la sesión
tiene una cookie `Pagina` (y `Sorts`). El sitio guarda el estado de paginación en
cookies (las pone el JS con document.cookie) y el servidor lee la página de AHÍ.

Esta iteración:
  FASE 1 — vuelca el JS correcto (UtilComplementos/UtilConfiguraciones, etc.)
           buscando cómo se setea la cookie `Pagina` y se llama a PostIndice.
  FASE 2 — camina las páginas SETEANDO la cookie `Pagina=n` antes de cada POST y
           verifica que los ids devueltos sean el tramo K_Avisos[(n-1)*23 : n*23].
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
JS_FILES = ["/js/min/UtilComplementos.min.js", "/js/min/UtilConfiguraciones.min.js",
            "/js/min/UtilBusqueda.min.js", "/js/min/Portada.min.js", "/js/min/Util.min.js"]
CLAVES_JS = ("btnPaginacion", "paginacionDirecta", "PostIndice", "Pagina",
             "document.cookie", "Cookie")


def _form_campos(html: str):
    f = BeautifulSoup(html, "html.parser").find("form", id="frmResultadosxTex")
    if not f:
        return {}, None
    campos = {i.get("name"): (i.get("value") or "")
              for i in f.find_all("input") if i.get("name")}
    return campos, campos.get("__RequestVerificationToken")


def _token_de(html: str):
    m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else None


def _set_pagina(cli, n):
    """Actualiza (o crea) la cookie de estado `Pagina`."""
    for c in list(cli.sesion.cookies):
        if c.name == "Pagina":
            cli.sesion.cookies.set("Pagina", str(n), domain=c.domain, path=c.path)
            return f"{c.domain}{c.path}"
    cli.sesion.cookies.set("Pagina", str(n), domain="www.avisosdeocasion.com", path="/")
    return "www.avisosdeocasion.com/"


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
    return r, d, ids, _token_de(r.text)


def _dump_js(cli):
    print("\n===== FASE 1: JS del paginador (archivos correctos) =====")
    for ruta in JS_FILES:
        try:
            js = cli.get(BASE + ruta).text
        except Exception as e:
            print(f"  {ruta}: no se pudo bajar ({e})"); continue
        encontrados = {k: js.find(k) for k in CLAVES_JS}
        encontrados = {k: i for k, i in encontrados.items() if i >= 0}
        print(f"\n  --- {ruta} ({len(js)} bytes) — claves: {list(encontrados)} ---")
        for k, i in encontrados.items():
            if k in ("Pagina", "Cookie", "document.cookie", "PostIndice"):
                print(f"  · ...{k}...: {js[max(0,i-160):i+160]}")


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

    _dump_js(cli)

    print("\n===== FASE 2: categoría multi-página =====")
    url_cat, html1, data1 = _elegir_categoria(cli)
    if not url_cat:
        print("sin categoría grande"); return
    slug, _ = partes_categoria(url_cat)
    kav = [str(x) for x in data1.get("K_Avisos", [])]
    ricos1 = [str(o.get("K_Av")) for o in data1.get("Avisos", [])
              if isinstance(o, dict) and o.get("K_Av")]
    reg = data1.get("Registros")
    base, tok = _form_campos(html1)
    print(f"Categoría {slug} | Registros={reg} | K_Avisos={len(kav)} | ricos pág1={len(ricos1)}")
    print(f"K_Avisos[0:3]={kav[:3]} … esperado pág2 = K_Avisos[23:26]={kav[23:26]}")
    print(f"Cookie Pagina inicial: "
          f"{[(c.name,c.value,c.domain) for c in cli.sesion.cookies if c.name in ('Pagina','Sorts')]}")

    headers = {
        "X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": url_cat,
        "Accept": "application/json, text/plain, */*",
        "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
    }

    print("\n----- COOKIE Pagina=n antes de cada POST -----")
    vistos = set(ricos1)
    tok_actual = tok
    for n in range(2, 8):
        dom = _set_pagina(cli, n)
        campos = dict(base)
        campos["pagina"] = str(n)
        if tok_actual:
            campos["__RequestVerificationToken"] = tok_actual
            headers["RequestVerificationToken"] = tok_actual
        r, d, ids, ntok = _post(cli, campos, headers)
        esperado = kav[(n - 1) * 23: n * 23]
        coincide = ids[:len(esperado)] == esperado
        nuevos = len(set(ids) - vistos)
        vistos |= set(ids)
        setck = r.headers.get("Set-Cookie", "")
        ckpag = next((c.value for c in cli.sesion.cookies if c.name == "Pagina"), None)
        print(f"  Pagina={n} (cookie@{dom}): HTTP {r.status_code} Avisos={len(ids)} "
              f"NUEVOS={nuevos} acum={len(vistos)} ¿=K_Avisos[{(n-1)*23}:{n*23}]? {coincide} "
              f"first={ids[:2]} cookiePagPost={ckpag} setCk={'Pagina' in setck}")
        if ntok:
            tok_actual = ntok
        if not ids:
            print("    (vacío; corto)"); break

    print(f"\nÚnicos acumulados: {len(vistos)} de Registros={reg}")
    print("VEREDICTO:", "✅ AVANZA (cookie Pagina funciona)" if len(vistos) > 80
          else "❌ no avanza — ver JS y Set-Cookie arriba")


if __name__ == "__main__":
    main()
