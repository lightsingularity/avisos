#!/usr/bin/env python3
"""Descarga LOCAL y opcional de fotos. Desactivada por defecto.

Las fotos de los anuncios son obras protegidas según el Aviso Legal del sitio;
este script solo corre si pones descargar_fotos: true en config.yaml, decisión
que es tuya. Nunca se ejecuta en GitHub Actions ni sube imágenes al repositorio.

Uso:
  python download_photos.py --zona CUMBRES --tipo casa --max 50
  python download_photos.py --id 32363879
"""
import argparse
import sqlite3
from pathlib import Path

import yaml

from scraper.db import RUTA_DB
from scraper.http_polite import ClienteEducado

DIR_FOTOS = Path(__file__).parent / "fotos"
MAX_FOTOS_POR_AVISO = 15


def main() -> None:
    cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
    if not cfg.get("descargar_fotos", False):
        raise SystemExit(
            "descargar_fotos está en false en config.yaml.\n"
            "Léete el comentario ahí antes de activarlo: la decisión es tuya."
        )

    ap = argparse.ArgumentParser()
    ap.add_argument("--zona")
    ap.add_argument("--tipo")
    ap.add_argument("--id", dest="id_aviso")
    ap.add_argument("--max", type=int, default=25, help="máx. de avisos a procesar")
    args = ap.parse_args()

    if not RUTA_DB.exists():
        raise SystemExit("No existe data/avisos.db — corre antes: python build_db.py")
    con = sqlite3.connect(RUTA_DB)

    consulta = "SELECT id_aviso FROM avisos WHERE fecha_baja IS NULL"
    parametros: list = []
    if args.id_aviso:
        consulta, parametros = "SELECT id_aviso FROM avisos WHERE id_aviso=?", [args.id_aviso]
    else:
        if args.zona:
            consulta += " AND zona=?"; parametros.append(args.zona)
        if args.tipo:
            consulta += " AND tipo_inmueble=?"; parametros.append(args.tipo)
        consulta += " LIMIT ?"; parametros.append(args.max)

    ids = [r[0] for r in con.execute(consulta, parametros)]
    print(f"{len(ids)} avisos por procesar")
    cliente = ClienteEducado(contacto=cfg.get("contacto", ""),
                             seg_entre_solicitudes=cfg.get("seg_entre_solicitudes", 1.0))

    for id_aviso in ids:
        destino = DIR_FOTOS / id_aviso
        destino.mkdir(parents=True, exist_ok=True)
        bajadas = 0
        for n in range(1, MAX_FOTOS_POR_AVISO + 1):
            url = f"https://ws.avisosdeocasion.com/fotoswa/2/{id_aviso}/{n}/8/0/foto.jpg"
            try:
                r = cliente.get(url)
            except Exception:
                break
            if r.status_code != 200 or not r.content:
                break
            ruta = destino / f"{n:02d}.jpg"
            ruta.write_bytes(r.content)
            con.execute(
                """INSERT INTO fotos (id_aviso, url_foto, orden, ruta_local)
                   VALUES (?,?,?,?)
                   ON CONFLICT(id_aviso, url_foto)
                   DO UPDATE SET ruta_local=excluded.ruta_local""",
                (id_aviso, url, n, str(ruta)),
            )
            bajadas += 1
        con.commit()
        print(f"  {id_aviso}: {bajadas} fotos")


if __name__ == "__main__":
    main()
