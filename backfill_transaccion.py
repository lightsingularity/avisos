"""Backfill ÚNICO de transacción para la línea base ya capturada.

Los anuncios DOBLES "venta o renta" los archiva el sitio en la categoría de RENTA
(su `K_Cla2` dice renta) aunque su precio principal y su DETALLE sean los de VENTA.
Quedaron como "renta" con precio de venta. La página de DETALLE es la fuente de
verdad: su `og:title` dice "Se vende …". Este backfill re-lee el detalle de cada
aviso ACTIVO de RENTA y, si el detalle dice otra transacción (venta/traspaso),
emite un evento `trans` que la corrige (no toca precio ni fechas).

Solo re-lee RENTAS: es ahí donde aparece el patrón (renta con precio de venta) y
acota el costo. La clasificación SIEMPRE sale del detalle, no del precio.

Es RE-EJECUTABLE y resumible (los ya corregidos dejan de ser 'renta' y no se
vuelven a elegir) y respeta un presupuesto de tiempo (BACKFILL_MIN, def. 50 min).
Corre en GitHub Actions (ver .github/workflows/backfill_transaccion.yml).
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
FLUSH_CADA = 50  # anexa eventos cada N para no perder progreso ante un fallo


def _rentas_activas(con) -> list[tuple[str, str]]:
    """(id_aviso, url) de los avisos ACTIVOS de RENTA con URL."""
    filas = con.execute(
        "SELECT id_aviso, url FROM avisos "
        "WHERE tipo_transaccion='renta' AND fecha_baja IS NULL "
        "  AND url IS NOT NULL AND url <> ''"
    ).fetchall()
    return [(r[0], r[1]) for r in filas]


def correr() -> int:
    inicio = time.monotonic()
    presupuesto_seg = float(os.environ.get("BACKFILL_MIN", "50")) * 60
    limite = int(os.environ.get("BACKFILL_MAX", "0"))  # 0 = sin tope
    hoy = datetime.now(TZ).date().isoformat()

    ruta_cfg = Path(__file__).resolve().parent / "config.yaml"
    cfg = yaml.safe_load(ruta_cfg.read_text(encoding="utf-8")) if ruta_cfg.exists() else {}

    con = reconstruir(Path(tempfile.gettempdir()) / "backfill_trans.db")
    pendientes = _rentas_activas(con)
    print(f"[{hoy}] Backfill de transacción — {len(pendientes)} rentas activas a verificar "
          f"(presupuesto {presupuesto_seg/60:.0f} min)")
    if not pendientes:
        print("  Sin rentas activas que verificar.")
        return 0

    cliente = ClienteEducado(
        contacto=cfg.get("contacto", "sin-contacto@ejemplo.com"),
        seg_entre_solicitudes=cfg.get("seg_entre_solicitudes", 1.0),
    )
    cliente.cargar_robots()

    eventos: list[dict] = []
    n_corr = n_ok = n_err = 0
    for idv, url in pendientes:
        if time.monotonic() - inicio > presupuesto_seg:
            print("  Presupuesto agotado; se corta limpio. Falta cola para otra corrida.")
            break
        if limite and (n_corr + n_ok + n_err) >= limite:
            print(f"  Tope BACKFILL_MAX={limite} alcanzado; se corta.")
            break
        try:
            extra = parsear_detalle(cliente.get(url).text)
            trans = extra.get("tipo_transaccion")
            if trans and trans != "renta":
                eventos.append({"e": "trans", "f": hoy, "id": idv, "trans": trans})
                n_corr += 1
                print(f"    [aviso {idv}] renta -> {trans} (según el detalle)")
            else:
                n_ok += 1
        except Exception as exc:  # un detalle fallido no tumba el backfill
            n_err += 1
            print(f"    [aviso {idv}] detalle falló: {exc}")
        if len(eventos) >= FLUSH_CADA:
            anexar_eventos(eventos)
            eventos = []

    if eventos:
        anexar_eventos(eventos)

    procesados = n_corr + n_ok + n_err
    restantes = len(pendientes) - procesados
    print(f"  Resultado: {n_corr} corregidas a venta/traspaso, {n_ok} siguen renta, "
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
