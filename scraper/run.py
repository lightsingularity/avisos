"""Orquestador de la corrida diaria.

Flujo:
  1. Carga el estado actual reproduciendo la bitácora de eventos.
  2. Sitemap de novedades — OPCIONAL. Desde 2026-06 el sitio sirve HTML en vez de
     XML; ya NO es obligatorio. Si parsea como XML lo usamos (se autocura solo);
     si no, seguimos con el índice como fuente principal. Nunca abortamos solo
     porque el sitemap esté caído.
  3. Cosecha el ÍNDICE (catálogo completo): las páginas de categoría. La lista de
     categorías es resiliente (`urls_categoria`): el sitemap de grupos si sirve
     XML, o los slugs de categoría del HISTORIAL si no (el número de la URL es
     cosmético, el slug rutea). Combina con el sitemap y deduplica por id_aviso.
  4. GUARDAS DE SEGURIDAD: si NI el sitemap NI el índice arrojan avisos, o —con
     fuentes confiables— hoy vemos menos de la mitad de los de ayer, ABORTA sin
     registrar bajas (un fallo de descubrimiento jamás debe vaciar el inventario).
  5. Altas: parsea título+caption (sitemap) y/o tarjeta (índice). Si el aviso no
     trae caption y la config lo permite, visita su página de detalle. Para altas
     del índice, si `indice.enriquecer_cola` está activo, visita el detalle de
     TODO aviso nuevo (no solo la cola sin precio) para capturar su descripción
     libre; en los "ricos" (con precio/zona ya fiables) el detalle solo aporta
     la descripción, nunca pisa lo que ya traían.
  6. Cambios de precio y reapariciones para los ya conocidos.
  7. Bajas: IDs que ayer estaban y hoy no — pero SOLO entre los avisos cuyas
     páginas se pudieron leer esta corrida (ver detección de bajas más abajo).
  8. Anexa eventos al JSONL del mes y registra la corrida.

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
from .indice import cosechar_indice
from .scrub import limpiar_contactos
from .sitemap import descargar_sitemap

TZ = ZoneInfo("America/Monterrey")
UMBRAL_CAIDA = 0.5        # aborta si hoy vemos < 50 % de lo de ayer
MIN_PREVIO_GUARDA = 20    # la guarda aplica solo con historial suficiente
UMBRAL_COBERTURA = 0.8    # mín. de categorías OK para confiar en el catálogo

# Atributos que el detalle puede aportar a un aviso de la "cola" (solo rellenan;
# nunca pisan lo que ya trae el registro del índice).
_ATRIB_DETALLE = ("recamaras", "banos", "plantas", "m2_construccion",
                  "m2_terreno", "m2_oficina", "m2_bodega", "metros_frente",
                  "hectareas", "mas_iva")


def _datos_indice(rec: dict) -> dict:
    """Copia del registro del índice apta para el evento 'alta' (sin id_aviso ni
    marcas internas con prefijo '_', que no se persisten)."""
    return {k: v for k, v in rec.items() if k != "id_aviso" and not k.startswith("_")}


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

    # Slugs de categoría ya vistos: fuente de descubrimiento del índice cuando el
    # sitemap de grupos está caído (el número de la URL es cosmético, el slug rutea).
    categorias_historicas = {s["categoria"] for s in estado.values() if s.get("categoria")}

    # ---------------- fuente 1: sitemap (novedades), OPCIONAL ----------------
    # Ya NO es obligatorio (el sitio sirve HTML desde 2026-06). Si parsea como XML
    # lo usamos —y la corrida se autocura sola cuando el sitio vuelve—; si no,
    # seguimos con el índice como fuente principal. Jamás abortamos solo por esto.
    sitemap_ok = False
    entradas: list = []
    try:
        entradas = descargar_sitemap(cliente)
        sitemap_ok = bool(entradas)
        print(f"  Sitemap de hoy: {len(entradas)} avisos")
    except Exception as exc:
        print(f"  Sitemap no disponible ({exc}); el índice será la fuente principal.")
    ids_sitemap = {e.id_aviso for e in entradas}

    # ---------------- fuente 2: índice (catálogo completo) ----------------
    usar_indice = cfg.get("usar_indice", False)
    icfg = cfg.get("indice") if isinstance(cfg.get("indice"), dict) else {}
    umbral_cobertura = float(icfg.get("umbral_cobertura", UMBRAL_COBERTURA))
    idx = None
    if usar_indice:
        try:
            idx = cosechar_indice(cliente, cfg, categorias_historicas)
            print(f"  Índice de hoy: {len(idx.registros)} avisos en "
                  f"{len(idx.categorias_ok)}/{idx.categorias_total} categorías "
                  f"(fuente: {idx.fuente}, {idx.paginas_ok}/{idx.paginas_total} páginas OK, "
                  f"cobertura {idx.cobertura:.0%})")
        except Exception as exc:  # el índice es aditivo: su caída no tumba la corrida
            print(f"  Índice no disponible esta corrida: {exc}")

    registros_indice = idx.registros if idx else {}
    categorias_ok = idx.categorias_ok if idx else set()
    cobertura = idx.cobertura if idx else 0.0
    todo_indice_ok = bool(idx and idx.categorias_total and
                          len(idx.categorias_ok) == idx.categorias_total)
    # Confiamos en el conteo combinado solo si el índice no se usa o vino completo.
    indice_confiable = (not usar_indice) or (idx is not None and cobertura >= umbral_cobertura)

    ids_hoy = ids_sitemap | set(registros_indice)

    # ---------------- guarda: descubrimiento vacío ----------------
    # Si NI el sitemap NI el índice arrojaron avisos, abortamos limpio (exit 2) sin
    # tocar la bitácora: un fallo de descubrimiento jamás debe vaciar el inventario.
    if not ids_hoy:
        print("  ¡ABORTO! Ni el sitemap ni el índice arrojaron avisos; "
              "no se registra nada.")
        return 2

    # ---------------- guarda de colapso ----------------
    if indice_confiable and len(activos_previos) >= MIN_PREVIO_GUARDA and \
            len(ids_hoy) < UMBRAL_CAIDA * len(activos_previos):
        print(f"  ¡ABORTO! Caída anómala: {len(ids_hoy)} vs "
              f"{len(activos_previos)} de ayer. Revisa el sitio/parser.")
        return 2

    eventos: list[dict] = []
    errores = 0
    modo_detalle = cfg.get("detalle", "faltantes")  # nunca | faltantes | todos
    # Enriquecer la "cola" del índice (avisos solo-id, sin precio) visitando su
    # página de detalle: añade precio (los hace visibles) y corrige zona/colonia
    # (el slug de la categoría miente). no | venta | todos.
    modo_cola = str(icfg.get("enriquecer_cola", "no")).lower()
    n_altas = n_bajas = n_cambios = n_cola = n_detalle_indice = 0
    procesados: set[str] = set()

    # ---------------- altas / cambios desde el sitemap ----------------
    for e in entradas:
        procesados.add(e.id_aviso)
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
            # El índice rellena huecos (zona/colonia/atributos) y aporta categoría;
            # la descripción del sitemap se conserva (el índice no la trae).
            rec_idx = registros_indice.get(e.id_aviso)
            if rec_idx:
                for k, v in _datos_indice(rec_idx).items():
                    datos.setdefault(k, v)
                datos["categoria"] = rec_idx.get("categoria")
                # El tipo/transacción del CÓDIGO del índice (K_Cla3/K_Cla2) es la
                # fuente más fiable: pisa lo inferido del título del sitemap, que es
                # heurístico (un tipo en el nombre de la colonia lo despistaba).
                if rec_idx.get("_tipo_fiable"):
                    datos["tipo_inmueble"] = rec_idx["tipo_inmueble"]
                if rec_idx.get("_trans_fiable"):
                    datos["tipo_transaccion"] = rec_idx["tipo_transaccion"]

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

    # ---------------- altas / cambios desde el índice (avisos no vistos en sitemap) ----------------
    for idv, rec in registros_indice.items():
        if idv in procesados:
            continue
        procesados.add(idv)
        previo = estado.get(idv)
        es_nuevo = previo is None
        reaparece = previo is not None and not previo["activo"]

        if es_nuevo or reaparece:
            datos = _datos_indice(rec)  # tipo, zona, colonia, precio, atributos, categoría
            tenia_precio = "precio" in datos
            # Visita el detalle de TODO aviso nuevo del índice, no solo la cola sin
            # precio: a los "ricos" (la mayoría, página 1, ya con precio y zona
            # fiable de ZonMun) les aporta la descripción libre, que el índice no
            # trae; a la cola (sin precio) además la hace visible y corrige
            # zona/colonia (el slug de la categoría está contaminado; el detalle no).
            quiere_detalle = modo_cola != "no" and (
                modo_cola == "todos" or datos.get("tipo_transaccion") == "venta")
            if quiere_detalle:
                try:
                    extra = parsear_detalle(cliente.get(datos["url"]).text)
                    if not tenia_precio and "precio" in extra:
                        datos["precio"] = extra["precio"]
                        datos["precio_unidad"] = extra.get("precio_unidad", "total")
                    # zona/colonia del detalle solo pisan lo de la cola: lo "rico"
                    # ya trae ZonMun, más fiable que el og:title del detalle.
                    if not tenia_precio and extra.get("zona"):
                        datos["zona"] = extra["zona"]
                    if extra.get("colonia"):
                        datos.setdefault("colonia", extra["colonia"])
                    if extra.get("descripcion"):  # el índice no trae texto libre
                        datos.setdefault("descripcion", limpiar_contactos(extra["descripcion"]))
                    # El tipo de la cola viene del SLUG (contaminado). Si no es
                    # fiable (no salió del código K_Cla3), el del detalle (og:title)
                    # manda: una casa cross-listada en una página de terrenos deja
                    # de quedar 'terreno'.
                    if not rec.get("_tipo_fiable") and extra.get("tipo_inmueble"):
                        datos["tipo_inmueble"] = extra["tipo_inmueble"]
                    # La transacción del DETALLE (página canónica del aviso, og:title
                    # "Se vende/renta…") manda sobre la del índice. En anuncios DOBLES
                    # venta/renta el sitio archiva el aviso en la categoría de RENTA
                    # (su K_Cla2 dice renta) pero su precio principal y su detalle son
                    # los de VENTA; el detalle desempata a favor de lo coherente.
                    if extra.get("tipo_transaccion"):
                        datos["tipo_transaccion"] = extra["tipo_transaccion"]
                    for k in _ATRIB_DETALLE:
                        if k in extra:
                            datos.setdefault(k, extra[k])
                    if not tenia_precio and "precio" in datos:
                        n_cola += 1
                    n_detalle_indice += 1
                except Exception as exc:  # un detalle fallido no tumba la corrida
                    errores += 1
                    print(f"    [aviso {idv}] enriquecimiento de detalle falló: {exc}")
            if reaparece:
                eventos.append({"e": "realta", "f": hoy, "id": idv})
            eventos.append({"e": "alta", "f": hoy, "id": idv,
                            "datos": datos, "fotos": []})
            n_altas += 1
        else:
            p_nuevo = rec.get("precio")
            u_nueva = rec.get("precio_unidad", "total")
            if p_nuevo is not None and (
                p_nuevo != previo.get("precio") or u_nueva != previo.get("unidad")
            ):
                eventos.append({"e": "precio", "f": hoy, "id": idv,
                                "precio": p_nuevo, "unidad": u_nueva})
                n_cambios += 1

    # ---------------- bajas (con resguardo ante fallos parciales) ----------------
    # Solo damos de baja avisos cuya "casa" se pudo leer hoy:
    #   - sin índice (modo heredado): el sitemap se trata como inventario completo.
    #   - con índice poco confiable: NO se calculan bajas (evita bajas falsas).
    #   - con índice confiable: un aviso ausente se da de baja solo si su categoría
    #     se descargó completa. Los avisos SIN categoría (capturas viejas solo del
    #     sitemap) solo podían confirmarse por el sitemap: sin él NO se dan de baja
    #     (no podemos ver hoy su "casa"); con sitemap, se exige que TODO el índice
    #     viniera completo.
    ausentes = sorted(activos_previos - ids_hoy)
    if not usar_indice:
        baja_ids = ausentes
    elif not indice_confiable:
        baja_ids = []
        print(f"  Cobertura del índice {cobertura:.0%} < {umbral_cobertura:.0%}: "
              f"se OMITE la detección de bajas esta corrida ({len(ausentes)} ausentes).")
    else:
        baja_ids = []
        omitidas = 0
        for idv in ausentes:
            cat = estado[idv].get("categoria")
            if cat:
                cubierto = cat in categorias_ok
            else:
                cubierto = sitemap_ok and todo_indice_ok
            if cubierto:
                baja_ids.append(idv)
            else:
                omitidas += 1
        if omitidas:
            print(f"  {omitidas} ausentes sin cobertura hoy: NO se dan de baja.")

    for id_baja in baja_ids:
        eventos.append({"e": "baja", "f": hoy, "id": id_baja})
        n_bajas += 1

    eventos.append({
        "e": "corrida", "f": hoy, "vistos": len(ids_hoy),
        "altas": n_altas, "bajas": n_bajas, "cambios": n_cambios,
        "errores": errores, "duracion_seg": int(time.monotonic() - inicio),
    })
    anexar_eventos(eventos)
    print(f"  Resultado: +{n_altas} altas, −{n_bajas} bajas, "
          f"~{n_cambios} cambios de precio, {n_cola} de cola enriquecidos, "
          f"{n_detalle_indice} detalles de índice visitados, "
          f"{errores} errores, {int(time.monotonic() - inicio)} s")
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
