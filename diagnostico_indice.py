#!/usr/bin/env python3
"""Diagnóstico puntual del tipo/categoría equivocados (issue: 32360772 = casa
quedó como terreno).

Recorre TODAS las categorías del índice (1 GET c/u) y reporta:
  - la "firma" de clasificación de cada categoría (moda de K_Cla2 entre sus
    objetos ricos) frente al tipo que dice su slug;
  - un mapa aprendido K_Cla2 -> tipo (voto mayoritario) y K_Cla1 -> transacción;
  - para los avisos objetivo, en qué categorías aparecen (en K_Avisos y/o como
    objeto rico) y qué K_Cla traen ELLOS mismos.

Guarda como fixtures unas categorías representativas para construir/probar el
arreglo. Pensado para correr en GitHub Actions (el runner sí alcanza el sitio).
"""
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from scraper.http_polite import ClienteEducado
from scraper.indice import (
    descargar_grupos,
    extraer_busqueda,
    partes_categoria,
    partes_slug,
)

FIXTURES = Path(__file__).parent / "tests" / "fixtures"
IDS_OBJETIVO = {"32360772", "32360783"}
SLUGS_GUARDAR = {"venta-casa-VALLE", "venta-terreno-VALLE", "venta-departamento-VALLE"}


def _modas(avisos, clave):
    return Counter(o.get(clave) for o in avisos if isinstance(o, dict)).most_common(3)


def main():
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    cli = ClienteEducado(contacto=cfg.get("contacto", "diagnostico"))
    cli.cargar_robots()
    urls = descargar_grupos(cli)
    print(f"categorías: {len(urls)}\n")

    voto_cla2_tipo = defaultdict(Counter)
    voto_cla1_trans = defaultdict(Counter)
    en_kavisos = defaultdict(list)   # id -> [(slug, tipo_del_slug)]
    en_avisos = defaultdict(list)    # id -> [(slug, K_Cla1, K_Cla2, K_Cla3, ZonMun)]

    FIXTURES.mkdir(parents=True, exist_ok=True)
    for url in urls:
        slug, _num = partes_categoria(url)
        trans, tipo, _zona = partes_slug(slug)
        try:
            html = cli.get(url).text
        except Exception as exc:
            print(f"  FALLO {slug}: {exc}")
            continue
        data = extraer_busqueda(html)
        if not data:
            print(f"  SIN JSON {slug}")
            continue
        kavset = {str(x) for x in data.get("K_Avisos", [])}
        avisos = [o for o in data.get("Avisos", []) if isinstance(o, dict)]
        for o in avisos:
            if tipo and o.get("K_Cla2") is not None:
                voto_cla2_tipo[o["K_Cla2"]][tipo] += 1
            if trans and o.get("K_Cla1") is not None:
                voto_cla1_trans[o["K_Cla1"]][trans] += 1

        idx = {str(o.get("K_Av")): o for o in avisos}
        for tid in IDS_OBJETIVO:
            if tid in kavset:
                en_kavisos[tid].append((slug, tipo))
            if tid in idx:
                o = idx[tid]
                en_avisos[tid].append((slug, o.get("K_Cla1"), o.get("K_Cla2"),
                                       o.get("K_Cla3"), o.get("ZonMun")))

        print(f"  {slug:44s} Reg={data.get('Registros')} "
              f"K_Avisos={len(kavset)} Avisos={len(avisos)} "
              f"modaK_Cla2={_modas(avisos, 'K_Cla2')}")

        if slug in SLUGS_GUARDAR or (kavset & IDS_OBJETIVO) or (set(idx) & IDS_OBJETIVO):
            (FIXTURES / f"indice_{slug}_p1.html").write_text(html, encoding="utf-8")
            print(f"     -> fixture guardado indice_{slug}_p1.html")

    print("\n===== MAPA aprendido K_Cla2 -> tipo (voto mayoritario) =====")
    for code, c in sorted(voto_cla2_tipo.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  K_Cla2={code}: {dict(c)}")
    print("\n===== MAPA aprendido K_Cla1 -> transacción =====")
    for code, c in sorted(voto_cla1_trans.items()):
        print(f"  K_Cla1={code}: {dict(c)}")

    print("\n===== AVISOS OBJETIVO =====")
    for tid in sorted(IDS_OBJETIVO):
        print(f"\n{tid}:")
        print(f"  en K_Avisos de : {en_kavisos.get(tid)}")
        print(f"  rico (Avisos) en: {en_avisos.get(tid)}")


if __name__ == "__main__":
    main()
