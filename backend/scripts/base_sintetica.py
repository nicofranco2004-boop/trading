"""Fabrica una SQLite con la FORMA de producción, para cronometrar el copiador.

**Por qué existe.** El plan de pasaje tiene un hueco `[A MEDIR]` que decide todo lo
demás: *cuánto tarda copiar*. De ese número depende si la ventana de mantenimiento
alcanza o si hay que discutir la copia en caliente. Medirlo sobre el mini-esquema de
4 tablas de los tests daría un número lindo y mentiroso.

**Qué copia de producción y qué no.** Copia la FORMA, no los datos:

    933 MB · ~3,4M filas · 60 tablas · ~1.084 usuarios
    y el 92% de las filas es andamio de import (`import_raw_rows.raw_json`, el CSV
    entero guardado para siempre). El negocio real son ~250 mil filas.

Los valores son inventados. **No sirve para verificar plata** —para eso está
`verificar_copia.py` sobre una copia restaurada de verdad— sirve para que el reloj
signifique algo.

**Hasta dónde es fiel, medido y no estimado.** Lo que gobierna el tiempo de copia es
la CANTIDAD DE FILAS, y ahí la fixture es exacta: 3,37M contra los ~3,4M de
producción, con el andamio en 92,0%. En BYTES es ~1,14 GB contra los 933 MB reales
(la fila de CSV de la plantilla pesa 273 bytes medidos), o sea **~22% más grande**.
Esa diferencia va para el lado seguro: el reloj sobreestima, nunca subestima. Y
después del vaciado de `raw_json` —que es el estado en el que el copiador la lee—
las dos colapsan a un tamaño parecido, así que el sesgo vive sobre todo en el paso
del vaciado y no en el de la copia.

⚠️ **Las 60 tablas salen de `init_db()` MÁS `ensure_tables()`**, no de `init_db()`
sola. Ésa fue exactamente la raíz del 58-vs-60: `mkschema.py` le preguntaba a
`init_db()` cómo es producción, y producción es `init_db()` + las que
`pricing/fci.py` crea en caliente. Si esta base se armara con `init_db()` sola,
volvería a medir la forma equivocada.

⚠️ **Los batches de import salen MEZCLADOS: `confirmed` y `preview`.** No es
decoración. El vaciado de `raw_json` va acotado a `status='confirmed'`, y con todos
los batches confirmados esa cota nunca se ejercita: la medición pasaría por un
camino que el día del pasaje no es el que corre.

Uso:

    python3 scripts/base_sintetica.py /ruta/salida.db            # tamaño producción
    python3 scripts/base_sintetica.py /ruta/salida.db --escala 0.01   # 1%, para probar
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time

# ── La forma de producción, en un solo lugar ─────────────────────────────────
# Las proporciones salen del doc (MIGRACION_POSTGRES.md, "Contexto de producción"):
# 3,4M filas totales, 92% andamio de import, ~1.084 usuarios, 933 MB.
USUARIOS = 1084
RAW_ROWS = 3_100_000           # el 92%
# Piso del `raw_json`. **Medido: la plantilla sola ya pesa 273 bytes**, así que hoy
# el relleno NO se aplica nunca — está para el día que alguien achique la plantilla
# y no para maquillar el tamaño. Se deja escrito porque una constante que parece
# gobernar algo y no gobierna nada es peor que no tenerla.
BYTES_RAW_JSON = 160
# El resto suma ~268 mil, que es lo que hace que el andamio dé 92,0% y no 88%.
# Es "el negocio real" del que habla el doc (~250 mil filas).
NORMALIZED_TX = 80_000
OP_LINKS = 70_000
POSICIONES = 25_000
OPERACIONES = 35_000
SNAPSHOTS = 50_000
BROKERS_POR_USUARIO = 3
BATCHES = 4_000
FRACCION_PREVIEW = 0.08        # batches sin confirmar: la cota del vaciado

# Una fila de CSV de broker, que es lo que de verdad vive en `raw_json`.
_PLANTILLA_RAW = {
    "Fecha": "2026-03-14", "Especie": "GGAL", "Tipo": "Compra",
    "Cantidad": "150", "Precio": "4821,50", "Importe": "-723225,00",
    "Comision": "1446,45", "IVA": "303,75", "Moneda": "ARS",
    "Comitente": "123456", "Liquidacion": "2026-03-16", "Mercado": "BYMA",
}


def _raw_json(i: int) -> str:
    """Un `raw_json` del tamaño real. El relleno va adentro de un campo, no pegado
    afuera: tiene que ser JSON válido, porque el confirm hace `json.loads`."""
    d = dict(_PLANTILLA_RAW, _fila=str(i))
    base = json.dumps(d, ensure_ascii=False)
    falta = BYTES_RAW_JSON - len(base)
    if falta > 0:
        d["Observaciones"] = "x" * falta
        base = json.dumps(d, ensure_ascii=False)
    return base


def _fecha_dia(k: int) -> str:
    """Día número k desde 2020-01-01, en 'YYYY-MM-DD'. Sin `datetime.now()`: la
    base tiene que salir igual todas las veces para que dos mediciones se puedan
    comparar."""
    import datetime
    return (datetime.date(2020, 1, 1) + datetime.timedelta(days=k)).isoformat()


def _crear_esquema(ruta: str) -> None:
    """Las 60 tablas: `init_db()` + `ensure_tables()`. Ver el ⚠️ del docstring."""
    os.environ["DB_PATH"] = ruta
    os.environ.setdefault("SECRET_KEY", "x")
    os.environ.pop("DATABASE_URL", None)          # esto es SQLite, siempre
    aqui = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, aqui)
    import main                                   # corre init_db() al importar
    import pricing.fci as fci
    conn = sqlite3.connect(main.DB_PATH)
    fci.ensure_tables(conn)
    conn.commit()
    conn.close()


def _lote(conn, sql, filas, tam=20_000):
    """Inserta por tandas: 3,1M filas de una sola vez no entran en memoria."""
    buf = []
    for f in filas:
        buf.append(f)
        if len(buf) >= tam:
            conn.executemany(sql, buf)
            buf = []
    if buf:
        conn.executemany(sql, buf)


def poblar(ruta: str, escala: float = 1.0, verboso: bool = True) -> dict:
    """Llena la base. Devuelve el resumen de lo que quedó."""
    n = lambda x: max(1, int(x * escala))
    t0 = time.time()
    _crear_esquema(ruta)

    conn = sqlite3.connect(ruta)
    conn.execute("PRAGMA journal_mode=OFF")       # es una base desechable
    conn.execute("PRAGMA synchronous=OFF")

    n_users = n(USUARIOS)
    _lote(conn, "INSERT INTO users (id,email,name,password_hash,created_at,is_admin,"
                "approved,tier) VALUES (?,?,?,?,?,?,?,?)",
          ((i, f"user{i}@rendi.test", f"Usuario {i}", "x" * 60, "2026-01-15",
            0, 1, "free" if i % 3 else "plus") for i in range(1, n_users + 1)))

    # brokers: incluye padre/hijo, que es la FK auto-referencial de la que depende
    # el orden de inserción DENTRO de la tabla.
    brokers = []
    bid = 0
    for u in range(1, n_users + 1):
        padre = None
        for k in range(BROKERS_POR_USUARIO):
            bid += 1
            brokers.append((bid, u, f"Broker{k}", "ARS" if k else "USD", padre))
            if k == 0:
                padre = bid                       # los siguientes cuelgan del primero
    _lote(conn, "INSERT INTO brokers (id,user_id,name,currency,parent_broker_id) "
                "VALUES (?,?,?,?,?)", brokers)

    n_batches = n(BATCHES)
    corte = int(n_batches * (1 - FRACCION_PREVIEW))
    _lote(conn, "INSERT INTO import_batches (id,user_id,broker,parser_format,file_name,"
                "file_hash,total_rows,valid_rows,invalid_rows,status,created_at,"
                "route_by_currency) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
          ((f"b{i:07d}", (i % n_users) + 1, "Balanz", "balanz_ordenes", f"f{i}.csv",
            f"h{i:040d}", 800, 800, 0,
            "confirmed" if i < corte else "preview",       # ⬅️ la cota del vaciado
            "2026-02-01", 0) for i in range(n_batches)))

    n_raw = n(RAW_ROWS)
    _lote(conn, "INSERT INTO import_raw_rows (id,batch_id,row_index,raw_json,status) "
                "VALUES (?,?,?,?,?)",
          ((i, f"b{i % n_batches:07d}", i % 800, _raw_json(i), "ok")
           for i in range(1, n_raw + 1)))

    n_tx = n(NORMALIZED_TX)
    _lote(conn, "INSERT INTO import_normalized_tx (id,batch_id,raw_row_id,date,broker,"
                "operation_type,asset_symbol,quantity,unit_price,gross_amount,fees,"
                "currency,transfer_out) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
          ((i, f"b{i % n_batches:07d}", (i % n_raw) + 1, "2026-03-14", "Balanz",
            "buy", "GGAL", 150.0, 4821.5, -723225.0, 1446.45, "ARS", 0)
           for i in range(1, n_tx + 1)))

    n_links = n(OP_LINKS)
    _lote(conn, "INSERT INTO import_op_links (id,batch_id,raw_row_id,position_id,"
                "operation_id) VALUES (?,?,?,?,?)",
          ((i, f"b{i % n_batches:07d}", (i % n_raw) + 1, (i % n(POSICIONES)) + 1, None)
           for i in range(1, n_links + 1)))

    n_pos = n(POSICIONES)
    _lote(conn, "INSERT INTO positions (id,user_id,broker,asset,is_cash,buy_price,"
                "quantity,invested,commissions,currency) VALUES (?,?,?,?,?,?,?,?,?,?)",
          ((i, (i % n_users) + 1, "Broker0", "USD" if i % 7 == 0 else f"TICK{i%400}",
            1 if i % 7 == 0 else 0, 12.5 + (i % 900), 10.0 + (i % 300),
            1500.25 + i, 3.5, "USD" if i % 2 else "ARS")
           for i in range(1, n_pos + 1)))

    n_ops = n(OPERACIONES)
    _lote(conn, "INSERT INTO operations (id,user_id,date,broker,asset,op_type,"
                "entry_price,exit_price,quantity,pnl_usd,pnl_pct,commissions,currency) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
          ((i, (i % n_users) + 1, "2026-04-02", "Broker0", f"TICK{i%400}", "sell",
            10.0 + (i % 100), 12.0 + (i % 100), 5.0, 123.45 - (i % 250), 3.2, 1.1,
            "USD") for i in range(1, n_ops + 1)))

    # `snapshots` tiene UNIQUE(user_id, date) de verdad, así que el par se arma
    # dividiendo y no con dos módulos: un usuario por resto, un DÍA distinto por
    # cociente. Con dos módulos se repiten los pares y la carga explota — y que
    # explote está bien: significa que esta base respeta las mismas restricciones
    # que producción, que es justamente lo que la hace servir para medir.
    n_snap = n(SNAPSHOTS)
    _lote(conn, "INSERT INTO snapshots (id,user_id,date,total_value,total_invested,"
                "net_deposited,fx_to_usd_blue,source,holdings_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
          ((i, (i % n_users) + 1, _fecha_dia(i // n_users),
            50000.0 + i, 40000.0 + i, 35000.0 + i, 1415.5, "cron",
            '{"h":[]}') for i in range(1, n_snap + 1)))

    conn.commit()
    conn.close()

    tam = os.path.getsize(ruta)
    filas = {"users": n_users, "brokers": len(brokers), "import_batches": n_batches,
             "import_raw_rows": n_raw, "import_normalized_tx": n_tx,
             "import_op_links": n_links, "positions": n_pos,
             "operations": n_ops, "snapshots": n_snap}
    total = sum(filas.values())
    res = {"ruta": ruta, "bytes": tam, "mb": round(tam / 1e6, 1), "filas": total,
           "detalle": filas, "pct_andamio": round(100 * n_raw / total, 1),
           "batches_preview": n_batches - corte, "segundos": round(time.time() - t0, 1)}
    if verboso:
        print(f"{res['mb']} MB · {total:,} filas · {res['pct_andamio']}% andamio · "
              f"{res['batches_preview']} batches en preview · {res['segundos']}s")
    return res


def main_cli():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("salida")
    ap.add_argument("--escala", type=float, default=1.0,
                    help="1.0 = tamaño producción (~933 MB). 0.01 = 1%%, para probar.")
    a = ap.parse_args()
    if os.path.exists(a.salida):
        sys.exit(f"ya existe: {a.salida} (borralo a mano si querés rehacerlo)")
    poblar(a.salida, a.escala)


if __name__ == "__main__":
    main_cli()
