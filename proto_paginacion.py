#!/usr/bin/env python3
"""Sonda de paginación POST /Portada/PostIndice — hipótesis del CURSOR.

Contexto: el ciclo 4 (rama proto-paginacion) trataba la paginación como
'pagina=N' y reusaba el token de la página 1; se estancaba (~44 únicos de 238).
Pero el menú de búsqueda del sitio pagina SIN fallar, así que el endpoint
funciona: lo que faltaba era replicar el handshake con estado.

Pistas nuevas (del fixture de categoría): el form `frmResultadosxTex` trae,
junto a `pagina`, un campo `ClavAviso` (vacío) — huele a CURSOR (clave del último
aviso). Si el servidor pagina por cursor, dejar `ClavAviso` vacío devuelve
siempre el inicio (= el estancamiento observado).

Esta sonda hace dos cosas en UNA corrida (se lee del log de Actions):
  FASE 1 — vuelca el JS del paginador (btnPaginacion / paginacionDirecta y el
           contexto de PostIndice/ClavAviso) para ver el payload REAL.
  FASE 2 — control (pagina sola, estilo ciclo 4) vs. CURSOR (ClavAviso = último
           K_Av) con token fresco por respuesta y cookies de sesión; mide el
           crecimiento de avisos únicos.
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
JS_FILES = ["/js/min/UtilBusqueda.min.js", "/js/min/Portada.min.js", "/js/min/Util.min.js"]


# ---------------------------------------------------------------- utilidades
def _extraer_funcion(js: str, nombre: str) -> str | None:
    """Extrae el cuerpo completo de una función con balance de llaves."""
    for pat in (f"function {nombre}", f"{nombre}=function", f"{nombre}:function",
                f"{nombre}=async function"):
        i = js.find(pat)
        if i < 0:
            continue
        j = js.find("{", i)
        if j < 0:
            continue
        prof = 0
        for k in range(j, min(len(js), j + 6000)):
            if js[k] == "{":
                prof += 1
            elif js[k] == "}":
                prof -= 1
                if prof == 0:
                    return js[i:k + 1]
        return js[i:j + 2500]
    return None


def _contexto(js: str, clave: str, ancho: int = 220) -> str | None:
    i = js.find(clave)
    return None if i < 0 else js[max(0, i - ancho):i + ancho]


def _form_campos(html: str):
    f = BeautifulSoup(html, "html.parser").find("form", id="frmResultadosxTex")
    if not f:
        return {}, None
    campos = {i.get("name"): (i.get("value") or "")
              for i in f.find_all("input") if i.get("name")}
    return campos, campos.get("__RequestVerificationToken")


def _token_de(html: str) -> str | None:
    m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else None


def _post(cli, campos, headers):
    time.sleep(1.0)  # cortesía (1 req/s)
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


# ------------------------------------------------------------------ FASE 1
def _dump_js(cli) -> None:
    print("\n===== FASE 1: JS del paginador =====")
    for ruta in JS_FILES:
        try:
            js = cli.get(BASE + ruta).text
        except Exception as e:
            print(f"  {ruta}: no se pudo bajar ({e})")
            continue
        print(f"\n  --- {ruta} ({len(js)} bytes) ---")
        for fn in ("btnPaginacion", "paginacionDirecta"):
            cuerpo = _extraer_funcion(js, fn)
            if cuerpo:
                print(f"  · {fn}():\n{cuerpo[:1200]}\n")
        for clave in ("PostIndice", "ClavAviso"):
            ctx = _contexto(js, clave)
            if ctx:
                print(f"  · ...{clave}...: {ctx}\n")


# ------------------------------------------------------------------ FASE 2
def _elegir_categoria(cli):
    """Primera categoría con varias páginas (Registros > 100), priorizando casas."""
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
    mtot = re.search(r"P[áa]g\.\s*\d+\s*de\s*(\d+)", html1)
    base, tok = _form_campos(html1)
    print(f"Categoría {slug} | Registros={reg} | K_Avisos={len(kav)} | "
          f"páginas={mtot.group(1) if mtot else '?'} | ricos pág1={len(ricos1)}")
    print(f"Campos del form: {sorted(base)}")
    print(f"ClavAviso inicial={base.get('ClavAviso')!r} | token pág1={tok[:20] if tok else None}…")
    print(f"Cookies de sesión: {sorted(cli.sesion.cookies.keys())}")

    headers = {
        "X-Requested-With": "XMLHttpRequest", "Origin": BASE, "Referer": url_cat,
        "Accept": "application/json, text/plain, */*",
        "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
    }

    # ---- CONTROL: pagina=2 con ClavAviso vacío (reproduce el ciclo 4) ----
    print("\n----- CONTROL (pagina=2, ClavAviso vacío, estilo ciclo 4) -----")
    campos = dict(base); campos["pagina"] = "2"; campos["ClavAviso"] = ""
    r, d, ids, ntok = _post(cli, campos, headers)
    print(f"  HTTP {r.status_code} | ctype={r.headers.get('Content-Type','')[:40]} | "
          f"len={len(r.text)} | Avisos={len(ids)} | first={ids[:3]}")
    if isinstance(d, dict):
        print(f"  claves top-level de la respuesta: {list(d.keys())[:12]}")
    else:
        print(f"  respuesta no-JSON; inicio: {r.text[:160]!r}")

    # ---- CURSOR: ClavAviso = último K_Av, token fresco, secuencial ----
    print("\n----- CURSOR (ClavAviso = último K_Av, token fresco, secuencial) -----")
    vistos = set(ricos1)
    cursor = ricos1[-1] if ricos1 else ""
    tok_actual = tok
    print(f"  página 1 (del GET): {len(ricos1)} ricos | cursor inicial={cursor}")
    for paso in range(2, 11):
        campos = dict(base)
        campos["pagina"] = str(paso)
        campos["ClavAviso"] = cursor
        if tok_actual:
            campos["__RequestVerificationToken"] = tok_actual
            headers["RequestVerificationToken"] = tok_actual
        r, d, ids, ntok = _post(cli, campos, headers)
        nuevos = len(set(ids) - vistos)
        vistos |= set(ids)
        print(f"  paso {paso}: HTTP {r.status_code} Avisos={len(ids)} NUEVOS={nuevos} "
              f"acum={len(vistos)} cursor={cursor} "
              f"tokRot={'sí' if ntok and ntok != tok_actual else 'no'} first={ids[:2]}")
        if not ids:
            print("    (vacío; corto)"); break
        cursor = ids[-1]
        if ntok:
            tok_actual = ntok
        if nuevos == 0:
            print("    (sin nuevos; el cursor no avanzó)"); break

    print(f"\nÚnicos acumulados (cursor): {len(vistos)} de Registros={reg}")
    print("VEREDICTO:", "✅ AVANZA (cursor funciona)" if len(vistos) > 80
          else "❌ aún no avanza — revisar el JS volcado arriba")


if __name__ == "__main__":
    main()
