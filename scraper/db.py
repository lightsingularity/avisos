"""Base SQLite derivada de la bitácora de eventos.

La base NUNCA se versiona en git: se reconstruye con `python build_db.py`
(tarda segundos incluso con años de datos). Campos en español, precios en MXN.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .events import leer_eventos
from .tags import etiquetas as _etiquetas

RUTA_DB = Path(__file__).resolve().parent.parent / "data" / "avisos.db"

# Clasificación del tipo de inmueble para las métricas por m². Fuente ÚNICA de
# verdad: la comparten la vista `analisis` (métricas por fila, abajo) y
# analytics.serie_mensual (agregaciones). El $/m² de construcción solo tiene
# sentido en inmuebles construidos; el $/m² de terreno, solo en los de suelo.
TIPOS_CONSTRUCCION = frozenset({"casa", "departamento", "local_oficina", "edificio"})
TIPOS_TERRENO = frozenset({"terreno", "finca_campestre", "rancho"})

# Área mínima plausible de un terreno (m²). Por debajo es captura MALA del área (p. ej.
# 8 m²), que dispara el $/m²: con un área así NO se computa $/m². El suelo real más
# chico ronda los 100 m². Fuente única (la usan la vista `analisis` y analytics).
MIN_M2_TERRENO = 50

# Pisos de plausibilidad del precio TOTAL (MXN), por transacción. Por debajo es un
# PLACEHOLDER del sitio ("precio a consultar" / error de captura del anunciante), no
# un precio real (p. ej. local en venta $4, terreno $450): no debe entrar a la base
# derivada ni, por tanto, al tablero. La bitácora lo conserva tal cual (es la fuente
# de verdad); esto solo filtra la SQLite reconstruida y es ajustable aquí.
PISO_PRECIO_TOTAL = {"venta": 100_000, "traspaso": 10_000, "renta": 1_000}


def precio_valido(precio, unidad, transaccion) -> bool:
    """False si un precio 'total' cae por debajo del piso de su transacción (un
    placeholder implausible). Los precios por m² (terrenos) usan otra escala y no se
    filtran aquí; un precio nulo se deja pasar (no hay nada que registrar)."""
    if unidad != "total" or precio is None:
        return True
    piso = PISO_PRECIO_TOTAL.get(transaccion)
    return piso is None or precio >= piso


# Techo de plausibilidad del precio POR m² (MXN/m²). El sitio a veces mete el precio
# TOTAL en el campo de "precio por m²" (verificado: p. ej. un terreno con "$7,500,000
# por m²" que en realidad vale $7.5M totales a $7,500/m²). Ningún suelo cuesta
# $100,000/m², así que por encima de este techo NO es un precio por m² real sino un
# total mal etiquetado: lo reinterpretamos como 'total' (la vista ya saca $/m² =
# total / m2_terreno). Ajustable aquí; la bitácora conserva la unidad original.
TECHO_PRECIO_M2 = 100_000


def normalizar_unidad(precio, unidad):
    """Reinterpreta un 'precio por m²' implausiblemente alto como precio total."""
    if unidad == "m2" and precio is not None and precio > TECHO_PRECIO_M2:
        return precio, "total"
    return precio, unidad


# Techo de plausibilidad de una RENTA mensual TOTAL (MXN). Los anuncios DOBLES
# "venta o renta" (un PH en venta $20.8M / renta $125k) los archiva el sitio en la
# categoría de renta —su K_Cla2 dice renta— pero su precio principal es el de
# VENTA. Resultado: una "renta" con precio de venta. Ninguna renta mensual real
# llega a esto (en el corpus, las rentas legítimas más altas —naves industriales
# grandes— rondan $1.3M; los precios de venta mal archivados arrancan en ~$10M:
# hay un hueco enorme entre ambos). Por encima del techo reinterpretamos la
# transacción como 'venta', para que precio y transacción queden coherentes. La
# bitácora conserva la transacción original; solo la base derivada la corrige.
TECHO_RENTA_TOTAL = 3_000_000


def reinterpretar_transaccion(transaccion, precio, unidad):
    """Una 'renta' con precio TOTAL de tamaño de venta es en realidad una venta
    (anuncio doble venta/renta archivado en renta con el precio de venta)."""
    if (transaccion == "renta" and unidad == "total"
            and precio is not None and precio >= TECHO_RENTA_TOTAL):
        return "venta"
    return transaccion


def _sql_lista(valores) -> str:
    """{'a', 'b'} -> "'a', 'b'" para una cláusula IN de SQLite."""
    return ", ".join(f"'{v}'" for v in sorted(valores))


_ESQUEMA = f"""
CREATE TABLE avisos (
    id_aviso            TEXT PRIMARY KEY,
    url                 TEXT,
    tipo_transaccion    TEXT,
    tipo_inmueble       TEXT,
    zona                TEXT,
    colonia             TEXT,
    plantas             REAL,
    recamaras           REAL,
    banos               REAL,
    m2_construccion     REAL,
    m2_terreno          REAL,
    hectareas           REAL,
    metros_frente       REAL,
    m2_oficina          REAL,
    m2_bodega           REAL,
    mas_iva             INTEGER,
    descripcion         TEXT,
    fecha_primera_vista TEXT NOT NULL,
    fecha_ultima_vista  TEXT NOT NULL,
    fecha_baja          TEXT
);
CREATE TABLE historial_precios (
    id_aviso TEXT NOT NULL,
    fecha    TEXT NOT NULL,
    precio   INTEGER NOT NULL,
    unidad   TEXT NOT NULL DEFAULT 'total',
    PRIMARY KEY (id_aviso, fecha)
);
CREATE TABLE fotos (
    id_aviso   TEXT NOT NULL,
    url_foto   TEXT NOT NULL,
    orden      INTEGER,
    ruta_local TEXT,
    PRIMARY KEY (id_aviso, url_foto)
);
CREATE TABLE tags (
    id_aviso TEXT NOT NULL,
    tag      TEXT NOT NULL,
    PRIMARY KEY (id_aviso, tag)
);
CREATE TABLE corridas (
    fecha        TEXT PRIMARY KEY,
    vistos       INTEGER,
    altas        INTEGER,
    bajas        INTEGER,
    cambios      INTEGER,
    errores      INTEGER,
    duracion_seg INTEGER
);
CREATE INDEX idx_avisos_zona ON avisos(zona, tipo_inmueble, tipo_transaccion);
CREATE INDEX idx_hist_aviso ON historial_precios(id_aviso, fecha);
CREATE INDEX idx_tags_tag ON tags(tag);

-- Vista principal para análisis: último precio + métricas derivadas.
CREATE VIEW analisis AS
SELECT a.*,
       h.precio          AS precio_actual,
       h.unidad          AS precio_unidad,
       CAST(julianday(COALESCE(a.fecha_baja, date('now')))
            - julianday(a.fecha_primera_vista) AS INTEGER) AS dias_en_mercado,
       CASE WHEN h.unidad = 'total' AND a.m2_construccion > 0
                 AND a.tipo_inmueble IN ({_sql_lista(TIPOS_CONSTRUCCION)})
            THEN ROUND(h.precio / a.m2_construccion, 0) END AS precio_m2_construccion,
       CASE WHEN a.tipo_inmueble IN ({_sql_lista(TIPOS_TERRENO)}) THEN
                 CASE WHEN h.unidad = 'total' AND a.m2_terreno >= {MIN_M2_TERRENO}
                      THEN ROUND(h.precio / a.m2_terreno, 0)
                      WHEN h.unidad = 'm2' THEN h.precio END
            END                                              AS precio_m2_terreno,
       (SELECT COUNT(*) - 1 FROM historial_precios h2
         WHERE h2.id_aviso = a.id_aviso)                     AS num_cambios_precio
FROM avisos a
JOIN historial_precios h
  ON h.id_aviso = a.id_aviso
 AND h.fecha = (SELECT MAX(fecha) FROM historial_precios h3
                 WHERE h3.id_aviso = a.id_aviso);
"""

_CAMPOS_AVISO = [
    "url", "tipo_transaccion", "tipo_inmueble", "zona", "colonia", "plantas",
    "recamaras", "banos", "m2_construccion", "m2_terreno", "hectareas",
    "metros_frente", "m2_oficina", "m2_bodega", "mas_iva", "descripcion",
]


def reconstruir(ruta_db: Path = RUTA_DB, dir_eventos=None) -> sqlite3.Connection:
    """Reconstruye la base completa reproduciendo la bitácora de eventos."""
    ruta_db.parent.mkdir(parents=True, exist_ok=True)
    if ruta_db.exists():
        ruta_db.unlink()
    con = sqlite3.connect(ruta_db)
    con.executescript(_ESQUEMA)
    kw = {"dir_eventos": dir_eventos} if dir_eventos else {}
    for ev in leer_eventos(**kw):
        _aplicar(con, ev)
    _derivar_tags(con)
    con.commit()
    return con


def _derivar_tags(con: sqlite3.Connection) -> None:
    """Recalcula la tabla `tags` desde la descripción (artefacto derivado).

    Se ejecuta tras reproducir la bitácora, sobre la descripción ya consolidada
    de cada aviso. Editar el catálogo (scraper/tags.py) y reconstruir basta para
    re-etiquetar; no hay que re-scrapear ni versionar nada."""
    con.execute("DELETE FROM tags")
    filas = con.execute(
        "SELECT id_aviso, descripcion FROM avisos "
        "WHERE descripcion IS NOT NULL AND descripcion <> ''"
    ).fetchall()
    con.executemany(
        "INSERT OR IGNORE INTO tags VALUES (?, ?)",
        [(idv, tag) for idv, desc in filas for tag in _etiquetas(desc)],
    )


def _aplicar(con: sqlite3.Connection, ev: dict) -> None:
    e, f = ev["e"], ev["f"]
    if e == "alta":
        d = ev.get("datos", {})
        # Corrige el anuncio doble venta/renta archivado en renta con precio de
        # venta: la transacción almacenada pasa a 'venta' (coherente con el precio).
        unidad_alta = d.get("precio_unidad", "total")
        trans = reinterpretar_transaccion(
            d.get("tipo_transaccion"), d.get("precio"), unidad_alta)
        valores = [trans if c == "tipo_transaccion" else d.get(c) for c in _CAMPOS_AVISO]
        con.execute(
            f"""INSERT OR REPLACE INTO avisos
                (id_aviso, {', '.join(_CAMPOS_AVISO)},
                 fecha_primera_vista, fecha_ultima_vista, fecha_baja)
                VALUES (?{', ?' * len(_CAMPOS_AVISO)}, ?, ?, NULL)""",
            [ev["id"]] + valores + [f, f],
        )
        if "precio" in d:
            precio, unidad = normalizar_unidad(d["precio"], unidad_alta)
            if precio_valido(precio, unidad, trans):
                con.execute(
                    "INSERT OR REPLACE INTO historial_precios VALUES (?,?,?,?)",
                    (ev["id"], f, precio, unidad),
                )
        for i, u in enumerate(ev.get("fotos", []), start=1):
            con.execute(
                "INSERT OR IGNORE INTO fotos (id_aviso, url_foto, orden) VALUES (?,?,?)",
                (ev["id"], u, i),
            )
    elif e == "precio":
        fila = con.execute(
            "SELECT tipo_transaccion FROM avisos WHERE id_aviso=?", (ev["id"],)).fetchone()
        precio, unidad = normalizar_unidad(ev["precio"], ev.get("unidad", "total"))
        # Un cambio de precio que revela un precio de venta sobre una "renta"
        # también reclasifica la transacción (mismo anuncio doble venta/renta).
        previa = fila[0] if fila else None
        trans = reinterpretar_transaccion(previa, precio, unidad)
        if trans != previa:
            con.execute("UPDATE avisos SET tipo_transaccion=? WHERE id_aviso=?", (trans, ev["id"]))
        if precio_valido(precio, unidad, trans):
            con.execute(
                "INSERT OR REPLACE INTO historial_precios VALUES (?,?,?,?)",
                (ev["id"], f, precio, unidad),
            )
        con.execute("UPDATE avisos SET fecha_ultima_vista=? WHERE id_aviso=?", (f, ev["id"]))
    elif e == "desc":
        # Solo rellena la descripción libre de un aviso ya existente (backfill);
        # no toca precios ni fechas. No pisa una descripción ya presente.
        con.execute(
            "UPDATE avisos SET descripcion=? "
            "WHERE id_aviso=? AND (descripcion IS NULL OR descripcion='')",
            (ev["desc"], ev["id"]),
        )
    elif e == "baja":
        con.execute("UPDATE avisos SET fecha_baja=? WHERE id_aviso=?", (f, ev["id"]))
    elif e == "realta":
        con.execute(
            "UPDATE avisos SET fecha_baja=NULL, fecha_ultima_vista=? WHERE id_aviso=?",
            (f, ev["id"]),
        )
    elif e == "visto":
        con.execute("UPDATE avisos SET fecha_ultima_vista=? WHERE id_aviso=?", (f, ev["id"]))
    elif e == "corrida":
        con.execute(
            "INSERT OR REPLACE INTO corridas VALUES (?,?,?,?,?,?,?)",
            (f, ev.get("vistos"), ev.get("altas"), ev.get("bajas"),
             ev.get("cambios"), ev.get("errores"), ev.get("duracion_seg")),
        )


def estado_actual(dir_eventos=None) -> dict[str, dict]:
    """Estado en memoria {id_aviso: {activo, precio, unidad}} para la corrida diaria."""
    estado: dict[str, dict] = {}
    kw = {"dir_eventos": dir_eventos} if dir_eventos else {}
    for ev in leer_eventos(**kw):
        e = ev["e"]
        if e == "alta":
            d = ev.get("datos", {})
            estado[ev["id"]] = {
                "activo": True,
                "precio": d.get("precio"),
                "unidad": d.get("precio_unidad", "total"),
                "tiene_datos": bool(d.get("tipo_inmueble") or d.get("precio")),
                # Categoría del índice (slug, p. ej. "venta-casa-CUMBRES") si vino
                # de esa fuente; sirve para decidir con seguridad si un aviso
                # ausente puede darse de baja.
                "categoria": d.get("categoria"),
            }
        elif e == "precio" and ev["id"] in estado:
            estado[ev["id"]]["precio"] = ev["precio"]
            estado[ev["id"]]["unidad"] = ev.get("unidad", "total")
        elif e == "baja" and ev["id"] in estado:
            estado[ev["id"]]["activo"] = False
        elif e == "realta" and ev["id"] in estado:
            estado[ev["id"]]["activo"] = True
    return estado
