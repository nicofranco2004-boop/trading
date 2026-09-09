#!/usr/bin/env python3
"""Mide el ALCANCE REAL en producción de los hallazgos urgentes de la auditoría.

SOLO LECTURA. Abre la base en modo `ro` (el motor rechaza cualquier escritura) y
corre 13 SELECT. Imprime **sólo agregados**: conteos, sumas y distintos. Ninguna
consulta devuelve user_id, email, nombre de broker ni fila individual — están
escritas así a propósito.

⚠️ EL CAMINO NORMAL YA NO ES ESTE SCRIPT. Los mismos 13 números salen de un botón
en el panel de admin ("Alcance real de la auditoría"), que no pide instalar nada:
el servidor que atiende ese panel es el que tiene la base abierta. Railway no
tiene consola web para un servicio —su dashboard sólo COPIA el comando SSH, que
igual necesita la CLI instalada—, así que `railway ssh` obligaba a instalar un
programa para leer unos totales.

Este script queda para correrlo contra una COPIA local (un backup bajado), donde
no hay servidor que preguntarle:

    python3 audit/01_calculos/1a-medir-alcance.py /ruta/a/una-copia.db

Si no le pasás ruta, la busca en DB_PATH y en los lugares habituales.

⚠️ EL SQL NO VIVE ACÁ. Vive en `1a-alcance-produccion-sqlite.sql` y lo lee
`backend/alcance_auditoria.py`, que es el mismo módulo que usa el botón. Antes
había una copia embebida en este archivo y ya había divergido del .sql (en un
comentario, sin que nadie lo notara) — que es exactamente el defecto que esta
auditoría persigue.
"""
import os
import sqlite3
import sys
import re

import importlib.util as _il

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MOD = os.path.join(_RAIZ, "backend", "alcance_auditoria.py")
_spec = _il.spec_from_file_location("alcance_auditoria", _MOD)
_alc = _il.module_from_spec(_spec)
_spec.loader.exec_module(_alc)

SQL = _alc._sql_crudo()
secciones = _alc.secciones


def base():
    if len(sys.argv) > 1:
        return sys.argv[1]
    for c in (os.environ.get("DB_PATH"), "backend/trading.db", "trading.db",
              "/app/backend/trading.db", "/app/trading.db", "/data/trading.db"):
        if c and os.path.exists(c):
            return c
    sys.exit("No encontré la base. Pasala como argumento: python3 medir.py /ruta/trading.db")


def main():
    ruta = base()
    print(f"base: {ruta}  ({os.path.getsize(ruta) / 1e6:.1f} MB)\n")
    con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    ultimo = None
    for qid, titulo, s in secciones():
        if qid != ultimo:
            print(f"\n{'=' * 72}\n{qid} · {titulo}\n{'=' * 72}")
            ultimo = qid
        try:
            for fila in con.execute(s).fetchall():
                for k in fila.keys():
                    v = fila[k]
                    print(f"  {k:38s} {v if v is not None else '—'}")
        except Exception as ex:
            print(f"  ⚠️ falló: {ex}")
    con.close()
    print("\nListo. Nada de esto identifica a ningún usuario.")


if __name__ == "__main__":
    main()
