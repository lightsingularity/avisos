"""Backfill ÚNICO de atributos numéricos para la línea base ya capturada.

El ÍNDICE subcuenta los medios baños (trae `Banios` sin `MedBan`): da banos=3.0
donde el panel del detalle dice 3.5. El panel del detalle (resumen estructurado
del og:description) es la fuente de verdad. Este backfill re-lee el detalle de
cada aviso ACTIVO y, donde un atributo numérico del panel difiere del guardado,
emite un evento `attrs` que lo corrige (no toca precio/fechas/transacción).

La clasificación SIEMPRE sale del detalle, no del índice. Re-EJECUTABLE y
resumible (respeta BACKFILL_MIN). Corre en GitHub Actions (ver
.github/workflows/backfill_atributos.yml).
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from scraper.db import _COLS_ATRIB, reconstruir
from scraper.detail_parser import parsear_detalle
from scraper.events import anexar_eventos
from scraper.http_polite import ClienteEducado

TZ = ZoneInfo("America/Monterrey")
FLUSH_CADA = 50


def _activos(con) -> list[tuple]:
    """(id_aviso, url, valores actuales de los atributos) de los avisos activos."""
    cols = ", ".join(sorted(_COLS_ATRIB))
    filas = con.execute(
        f"SELECT id_aviso, url, {cols} FROM avisos "
        "WHERE fecha_baja IS NULL AND url IS NOT NULL AND url <> ''"
    ).fetchall()
    orden = sorted(_COLS_ATRIB)
    return [(r[0], r[1], dict(zip(orden, r[2:]))) for r in filas]


def correr() -> int:
    inicio = time.monotonic()
    presupuesto_seg = float(os.environ.get("BACKFILL_MIN", "50")) * 60
    limite = int(os.environ.get("BACKFILL_MAX", "0"))
    hoy = datetime.now(TZ).date().isoformat()

    ruta_cfg = Path(__file__).resolve().parent / "config.yaml"
    cfg = yaml.safe_load(ruta_cfg.read_text(encoding="utf-8")) if ruta_cfg.exists() else {}

    con = reconstruir(Path(tempfile.gettempdir()) / "backfill_attrs.db")
    pendientes = _activos(con)
    print(f"[{hoy}] Backfill de atributos — {len(pendientes)} avisos activos a verificar "
          f"(presupuesto {presupuesto_seg/60:.0f} min)")
    if not pendientes:
        print("  Sin avisos activos que verificar.")
        return 0

    cliente = ClienteEducado(
        contacto=cfg.get("contacto", "sin-contacto@ejemplo.com"),
        seg_entre_solicitudes=cfg.get("seg_entre_solicitudes", 1.0),
    )
    cliente.cargar_robots()

    eventos: list[dict] = []
    n_corr = n_ok = n_err = 0
    for idv, url, actuales in pendientes:
        if time.monotonic() - inicio > presupuesto_seg:
            print("  Presupuesto agotado; se corta limpio. Falta cola para otra corrida.")
            break
        if limite and (n_corr + n_ok + n_err) >= limite:
            print(f"  Tope BACKFILL_MAX={limite} alcanzado; se corta.")
            break
        try:
            extra = parsear_detalle(cliente.get(url).text)
            # Solo donde el panel trae un valor y DIFIERE del guardado.
            cambios = {k: extra[k] for k in _COLS_ATRIB
                       if k in extra and extra[k] != actuales.get(k)}
            if cambios:
                eventos.append({"e": "attrs", "f": hoy, "id": idv, "attrs": cambios})
                n_corr += 1
                print(f"    [aviso {idv}] {cambios}")
            else:
                n_ok += 1
        except Exception as exc:
            n_err += 1
            print(f"    [aviso {idv}] detalle falló: {exc}")
        if len(eventos) >= FLUSH_CADA:
            anexar_eventos(eventos)
            eventos = []

    if eventos:
        anexar_eventos(eventos)

    procesados = n_corr + n_ok + n_err
    restantes = len(pendientes) - procesados
    print(f"  Resultado: {n_corr} con atributos corregidos, {n_ok} sin cambios, "
          f"{n_err} errores; {procesados} verificados, {restantes} pendientes, "
          f"{int(time.monotonic() - inicio)} s")
    return 0


if __name__ == "__main__":
    import sys
    try:
        sys.exit(correr())
    except Exception as exc:
        print(f"ERROR FATAL: {exc}")
        sys.exit(1)
