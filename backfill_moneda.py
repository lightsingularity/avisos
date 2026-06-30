"""Backfill ÚNICO de MONEDA para la línea base ya capturada.

El sitio cotiza muchos terrenos en USD (común en MTY). El flag `USD` del índice no
es fiable: dejó pasar precios en dólares guardados como si fueran MXN (un terreno de
"$1,500 DLLS/m²" quedó 17x subvaluado y contamina las medianas). La página de
DETALLE sí lo dice (`priceCurrency` del JSON-LD y "$X Dólares"/"DLLS" en el texto).

Este backfill re-lee el detalle de cada aviso ACTIVO CON PRECIO y, donde el detalle
detecta una moneda distinta de la guardada, emite un evento `moneda` que la corrige
(relabela el precio; no cambia el número). Re-EJECUTABLE y resumible (respeta
BACKFILL_MIN). Corre en GitHub Actions (ver .github/workflows/backfill_moneda.yml).
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

TZ = ZoneInfo("America/Monterrey")
FLUSH_CADA = 50


def _con_precio(con) -> list[tuple]:
    """(id_aviso, url, moneda actual) de los avisos activos con precio y URL."""
    filas = con.execute(
        "SELECT a.id_aviso, a.url, h.moneda "
        "FROM avisos a JOIN historial_precios h ON h.id_aviso = a.id_aviso "
        "WHERE a.fecha_baja IS NULL AND a.url IS NOT NULL AND a.url <> '' "
        "GROUP BY a.id_aviso"
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in filas]


def correr() -> int:
    inicio = time.monotonic()
    presupuesto_seg = float(os.environ.get("BACKFILL_MIN", "50")) * 60
    limite = int(os.environ.get("BACKFILL_MAX", "0"))
    hoy = datetime.now(TZ).date().isoformat()

    ruta_cfg = Path(__file__).resolve().parent / "config.yaml"
    cfg = yaml.safe_load(ruta_cfg.read_text(encoding="utf-8")) if ruta_cfg.exists() else {}

    con = reconstruir(Path(tempfile.gettempdir()) / "backfill_moneda.db")
    pendientes = _con_precio(con)
    print(f"[{hoy}] Backfill de moneda — {len(pendientes)} avisos con precio a verificar "
          f"(presupuesto {presupuesto_seg/60:.0f} min)")
    if not pendientes:
        print("  Sin avisos con precio que verificar.")
        return 0

    cliente = ClienteEducado(
        contacto=cfg.get("contacto", "sin-contacto@ejemplo.com"),
        seg_entre_solicitudes=cfg.get("seg_entre_solicitudes", 1.0),
    )
    cliente.cargar_robots()

    eventos: list[dict] = []
    n_corr = n_ok = n_err = 0
    for idv, url, actual in pendientes:
        if time.monotonic() - inicio > presupuesto_seg:
            print("  Presupuesto agotado; se corta limpio. Falta cola para otra corrida.")
            break
        if limite and (n_corr + n_ok + n_err) >= limite:
            print(f"  Tope BACKFILL_MAX={limite} alcanzado; se corta.")
            break
        try:
            extra = parsear_detalle(cliente.get(url).text)
            detectada = extra.get("precio_moneda", "MXN")
            if detectada != (actual or "MXN"):
                eventos.append({"e": "moneda", "f": hoy, "id": idv, "moneda": detectada})
                n_corr += 1
                print(f"    [aviso {idv}] {actual or 'MXN'} -> {detectada} (según el detalle)")
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
    print(f"  Resultado: {n_corr} con moneda corregida, {n_ok} sin cambios, "
          f"{n_err} errores; {procesados} verificadas, {restantes} pendientes, "
          f"{int(time.monotonic() - inicio)} s")
    return 0


if __name__ == "__main__":
    import sys
    try:
        sys.exit(correr())
    except Exception as exc:
        print(f"ERROR FATAL: {exc}")
        sys.exit(1)
