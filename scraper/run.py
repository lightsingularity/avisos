"""Orquestador de la corrida diaria.

Flujo:
  1. Carga el estado actual reproduciendo la bitácora de eventos.
  2. Descarga el sitemap de bienes raíces (1 solicitud).
  3. GUARDAS DE SEGURIDAD: si el sitemap viene vacío o con menos de la mitad
     de los avisos de ayer, ABORTA sin registrar bajas (un parser roto jamás
     debe marcar todo el inventario como dado de baja).
  4. Altas: parsea título+caption; si el aviso no trae caption y la config lo
     permite, visita su página de detalle (cortésmente).
  5. Cambios de precio y reapariciones para los ya conocidos.
  6. Bajas: IDs que ayer estaban y hoy no.
  7. Anexa eventos al JSONL del mes y registra la corrida.

Códigos de salida: 0 ok · 2 anomalía (guardas) · 1 error inesperado.
GitHub Actions envía correo automáticamente cuando la salida no es 0.
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .caption_parser import parsear_entrada
from .db import estado_actual
from .detail_parser import parsear_detalle
from .events import anexar_eventos
from .http_polite import ClienteEducado
from .scrub import limpiar_contactos
from .sitemap import descargar_sitemap

TZ = ZoneInfo("America/Monterrey")
UMBRAL_CAIDA = 0.5      # aborta si hoy vemos < 50 % de lo de ayer
MIN_PREVIO_GUARDA = 20  # la guarda aplica solo con historial suficiente


def correr(cfg: dict, fecha: str | None = None) -> int:
    """`fecha` permite forzar la fecha de la corrida (pruebas / backfills)."""
    inicio = time.monotonic()
    hoy = fecha or datetime.now(TZ).date().isoformat()
    print(f"[{hoy}] Corrida diaria — avisosdeocasion.com / Bienes Raíces")

    estado = estado_actual()
    activos_previos = {i for i, s in estado.items() if s["activo"]}
    print(f"  Estado previo: {len(activos_previos)} avisos activos conocidos")

    cliente = ClienteEducado(
        contacto=cfg.get("contacto", "sin-contacto@ejemplo.com"),
        seg_entre_solicitudes=cfg.get("seg_entre_solicitudes", 1.0),
    )
    cliente.cargar_robots()

    entradas = descargar_sitemap(cliente)
    ids_hoy = {e.id_aviso for e in entradas}
    print(f"  Sitemap de hoy: {len(entradas)} avisos")

    # ---------------- guardas ----------------
    if not entradas:
        print("  ¡ABORTO! El sitemap vino vacío; no se registra nada.")
        return 2
    if len(activos_previos) >= MIN_PREVIO_GUARDA and \
            len(ids_hoy) < UMBRAL_CAIDA * len(activos_previos):
        print(f"  ¡ABORTO! Caída anómala: {len(ids_hoy)} vs "
              f"{len(activos_previos)} de ayer. Revisa el sitio/parser.")
        return 2

    eventos: list[dict] = []
    errores = 0
    modo_detalle = cfg.get("detalle", "faltantes")  # nunca | faltantes | todos
    n_altas = n_bajas = n_cambios = 0

    for e in entradas:
        previo = estado.get(e.id_aviso)
        es_nuevo = previo is None
        reaparece = previo is not None and not previo["activo"]

        if es_nuevo or reaparece:
            datos = parsear_entrada(e.titulo, e.caption)
            datos["url"] = e.url
            necesita_detalle = (modo_detalle == "todos") or (
                modo_detalle == "faltantes" and not e.tiene_caption
            )
            fotos = list(e.fotos)
            if necesita_detalle:
                try:
                    r = cliente.get(e.url)
                    extra = parsear_detalle(r.text)
                    fotos = extra.pop("fotos", fotos) or fotos
                    for k, v in extra.items():
                        datos.setdefault(k, v)
                except Exception as exc:  # un detalle fallido no tumba la corrida
                    errores += 1
                    print(f"    [aviso {e.id_aviso}] detalle falló: {exc}")
            if e.caption and "descripcion" not in datos:
                datos["descripcion"] = e.caption
            if datos.get("descripcion"):
                datos["descripcion"] = limpiar_contactos(datos["descripcion"])

            if reaparece:
                eventos.append({"e": "realta", "f": hoy, "id": e.id_aviso})
            eventos.append({"e": "alta", "f": hoy, "id": e.id_aviso,
                            "datos": datos, "fotos": fotos})
            n_altas += 1
        else:
            # Aviso conocido y activo: ¿cambió el precio según el caption?
            campos = parsear_entrada(e.titulo, e.caption)
            p_nuevo, u_nueva = campos.get("precio"), campos.get("precio_unidad", "total")
            if p_nuevo is not None and (
                p_nuevo != previo.get("precio") or u_nueva != previo.get("unidad")
            ):
                eventos.append({"e": "precio", "f": hoy, "id": e.id_aviso,
                                "precio": p_nuevo, "unidad": u_nueva})
                n_cambios += 1

    for id_baja in sorted(activos_previos - ids_hoy):
        eventos.append({"e": "baja", "f": hoy, "id": id_baja})
        n_bajas += 1

    eventos.append({
        "e": "corrida", "f": hoy, "vistos": len(entradas),
        "altas": n_altas, "bajas": n_bajas, "cambios": n_cambios,
        "errores": errores, "duracion_seg": int(time.monotonic() - inicio),
    })
    anexar_eventos(eventos)
    print(f"  Resultado: +{n_altas} altas, −{n_bajas} bajas, "
          f"~{n_cambios} cambios de precio, {errores} errores, "
          f"{int(time.monotonic() - inicio)} s")
    return 0


def main() -> None:
    import yaml
    from pathlib import Path

    ruta_cfg = Path(__file__).resolve().parent.parent / "config.yaml"
    cfg = yaml.safe_load(ruta_cfg.read_text(encoding="utf-8")) if ruta_cfg.exists() else {}
    try:
        sys.exit(correr(cfg))
    except Exception as exc:
        print(f"ERROR FATAL: {exc}")
        sys.exit(1)
