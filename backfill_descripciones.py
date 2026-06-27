"""Backfill ÚNICO de descripciones para la línea base ya capturada.

Los avisos capturados antes de que el scraper visitara el detalle de TODA alta
del índice quedaron SIN la descripción libre del vendedor (lote industrial,
cajones de estacionamiento, amenidades…). Este script visita el detalle de cada
aviso ACTIVO que aún no tiene descripción y emite un evento `desc` (que solo
rellena esa columna; no toca precios ni fechas).

Es RE-EJECUTABLE y resumible: reconstruye el estado desde la bitácora, así que
un aviso ya rellenado en una corrida previa se omite en la siguiente. Respeta un
presupuesto de tiempo (BACKFILL_MIN, def. 50 min) para terminar y confirmar
antes del timeout del workflow; si queda cola, se vuelve a despachar.

Corre en GitHub Actions (el sitio 403ea fuera de los runners). Ver
.github/workflows/backfill.yml. Los eventos se anexan a data/eventos y el
workflow los confirma.
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from scraper.db import reconstruir
from scraper.detail_parser import parsear_detalle
from scraper.events import anexar_eventos
from scraper.http_polite import ClienteEducado
from scraper.scrub import limpiar_contactos

TZ = ZoneInfo("America/Monterrey")
FLUSH_CADA = 100  # anexa eventos cada N para no perder progreso ante un fallo


def _pendientes(con) -> list[tuple[str, str]]:
    """(id_aviso, url) de los avisos ACTIVOS sin descripción y con URL."""
    filas = con.execute(
        "SELECT id_aviso, url FROM avisos "
        "WHERE (descripcion IS NULL OR descripcion='') "
        "  AND fecha_baja IS NULL AND url IS NOT NULL AND url <> ''"
    ).fetchall()
    return [(r[0], r[1]) for r in filas]


def correr() -> int:
    inicio = time.monotonic()
    presupuesto_seg = float(os.environ.get("BACKFILL_MIN", "50")) * 60
    limite = int(os.environ.get("BACKFILL_MAX", "0"))  # 0 = sin tope
    hoy = datetime.now(TZ).date().isoformat()

    ruta_cfg = Path(__file__).resolve().parent / "config.yaml"
    cfg = yaml.safe_load(ruta_cfg.read_text(encoding="utf-8")) if ruta_cfg.exists() else {}

    con = reconstruir(Path(tempfile.gettempdir()) / "backfill.db")
    pendientes = _pendientes(con)
    print(f"[{hoy}] Backfill de descripciones — {len(pendientes)} avisos pendientes "
          f"(presupuesto {presupuesto_seg/60:.0f} min)")
    if not pendientes:
        print("  Nada pendiente: todos los avisos activos ya tienen descripción.")
        return 0

    cliente = ClienteEducado(
        contacto=cfg.get("contacto", "sin-contacto@ejemplo.com"),
        seg_entre_solicitudes=cfg.get("seg_entre_solicitudes", 1.0),
    )
    cliente.cargar_robots()

    eventos: list[dict] = []
    n_ok = n_sin = n_err = 0
    for idv, url in pendientes:
        if time.monotonic() - inicio > presupuesto_seg:
            print(f"  Presupuesto agotado; se corta limpio. Falta cola para otra corrida.")
            break
        if limite and (n_ok + n_sin + n_err) >= limite:
            print(f"  Tope BACKFILL_MAX={limite} alcanzado; se corta.")
            break
        try:
            extra = parsear_detalle(cliente.get(url).text)
            desc = extra.get("descripcion")
            if desc:
                eventos.append({"e": "desc", "f": hoy, "id": idv,
                                "desc": limpiar_contactos(desc)})
                n_ok += 1
            else:
                n_sin += 1
        except Exception as exc:  # un detalle fallido no tumba el backfill
            n_err += 1
            print(f"    [aviso {idv}] detalle falló: {exc}")
        if len(eventos) >= FLUSH_CADA:
            anexar_eventos(eventos)
            eventos = []

    if eventos:
        anexar_eventos(eventos)

    procesados = n_ok + n_sin + n_err
    restantes = len(pendientes) - procesados
    print(f"  Resultado: {n_ok} con descripción, {n_sin} sin texto, {n_err} errores; "
          f"{procesados} procesados, {restantes} pendientes, "
          f"{int(time.monotonic() - inicio)} s")
    return 0


if __name__ == "__main__":
    import sys
    try:
        sys.exit(correr())
    except Exception as exc:
        print(f"ERROR FATAL: {exc}")
        sys.exit(1)
