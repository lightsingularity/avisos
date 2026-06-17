#!/usr/bin/env python3
"""Reconstruye data/avisos.db desde la bitácora de eventos. Uso: python build_db.py"""
from scraper.db import RUTA_DB, reconstruir

if __name__ == "__main__":
    con = reconstruir()
    n = con.execute("SELECT COUNT(*) FROM avisos").fetchone()[0]
    act = con.execute("SELECT COUNT(*) FROM avisos WHERE fecha_baja IS NULL").fetchone()[0]
    print(f"Base reconstruida en {RUTA_DB}: {n} avisos históricos, {act} activos.")
