"""Bitácora de eventos en JSONL: la fuente de verdad del proyecto.

Cada línea es un evento JSON. Archivos mensuales en data/eventos/AAAA-MM.jsonl.
Tipos de evento:
  alta    {"e":"alta","f":"2026-06-12","id":"...","datos":{...},"fotos":[...]}
  precio  {"e":"precio","f":"...","id":"...","precio":123,"unidad":"total"}
  baja    {"e":"baja","f":"...","id":"..."}
  realta  {"e":"realta","f":"...","id":"..."}          # reapareció tras una baja
  desc    {"e":"desc","f":"...","id":"...","desc":"..."} # backfill de descripción
                                                          # (no toca precio ni fechas)
  corrida {"e":"corrida","f":"...","vistos":N,"altas":N,"bajas":N,
           "cambios":N,"errores":N,"duracion_seg":N}

Texto plano = diffs perfectos en git y un repositorio que crece poco.
La base SQLite se RECONSTRUYE desde aquí (ver db.py) y nunca se versiona.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

DIR_EVENTOS = Path(__file__).resolve().parent.parent / "data" / "eventos"


def leer_eventos(dir_eventos: Path | None = None) -> Iterator[dict]:
    """Lee todos los eventos en orden cronológico (archivos AAAA-MM ordenados)."""
    dir_eventos = dir_eventos or DIR_EVENTOS
    if not dir_eventos.exists():
        return
    for archivo in sorted(dir_eventos.glob("*.jsonl")):
        with archivo.open(encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if linea:
                    yield json.loads(linea)


def anexar_eventos(eventos: list[dict], dir_eventos: Path | None = None) -> None:
    """Agrega eventos al archivo del mes correspondiente (clave 'f' = fecha)."""
    dir_eventos = dir_eventos or DIR_EVENTOS
    dir_eventos.mkdir(parents=True, exist_ok=True)
    por_mes: dict[str, list[dict]] = {}
    for ev in eventos:
        por_mes.setdefault(ev["f"][:7], []).append(ev)
    for mes, lote in por_mes.items():
        with (dir_eventos / f"{mes}.jsonl").open("a", encoding="utf-8") as fh:
            for ev in lote:
                fh.write(json.dumps(ev, ensure_ascii=False, separators=(",", ":")) + "\n")
