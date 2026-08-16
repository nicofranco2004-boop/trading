"""Cuánto espacio necesita la copia MIENTRAS corre, no cuánto ocupa al final.

**Por qué existe: porque nadie contó el WAL y eso tumbó el destino.**

El 2026-08-15, copiando 1 GB a un Supabase Free, la instancia se cayó con el disco
al 100%. El desglose que mostró el panel es el hallazgo entero:

    DATABASE 553 MB   ·   WAL 660 MB   ·   SYSTEM 759 MB

**El cuaderno de borrador pesaba MÁS que los datos.** Y es consecuencia directa de
una decisión de diseño del copiador: todo va en UNA transacción, para que un corte
no deje nada a medias. El precio es que el WAL no se puede reciclar hasta el commit,
así que crece monótonamente hasta el final. Los 62 índices lo multiplican: cada
índice también escribe WAL.

Todo el dimensionamiento del pasaje decía "1 GB de datos". El requisito real es
**datos + WAL de la transacción entera + sistema**, y el WAL era el término que
faltaba.

Esto lo mide, y lo bueno es que **no hace falta el destino real**: cuánto WAL genera
la copia depende de la copia, no de dónde se copie. Se mide contra cualquier
Postgres y el número sirve para dimensionar el de verdad.

Uso — en otra terminal, mientras corre el copiador:

    python3 scripts/vigilar_espacio.py --destino "$DSN"          # hasta Ctrl-C
    python3 scripts/vigilar_espacio.py --destino "$DSN" --segundos 120
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _lsn_a_bytes(lsn: str) -> int:
    """'0/16B3748' → entero. El LSN es la posición en el flujo de WAL: la resta
    entre dos da los bytes de WAL generados en el medio."""
    alto, bajo = lsn.split("/")
    return (int(alto, 16) << 32) + int(bajo, 16)


def medir(conn) -> dict:
    base = conn.execute(
        "SELECT pg_database_size(current_database())").fetchone()[0]
    lsn = conn.execute("SELECT pg_current_wal_lsn()::text").fetchone()[0]
    # Lo que está sin commitear NO aparece en pg_database_size todavía, pero SÍ
    # ocupa disco. Por eso se mira también el tamaño de los archivos temporales y
    # el backlog de WAL, que es lo que de verdad llena el disco durante la copia.
    activas = conn.execute("""
        SELECT count(*) FROM pg_stat_activity
         WHERE state = 'active' AND query ILIKE 'COPY%'""").fetchone()[0]
    return {"base": base, "lsn": _lsn_a_bytes(lsn), "copys_activos": activas}


def vigilar(dsn: str, segundos: float = 0, intervalo: float = 2.0) -> dict:
    import pgsesion
    conn = pgsesion.conectar(dsn, autocommit=True)
    try:
        cero = medir(conn)
        t0 = time.time()
        pico_base = pico_wal = 0
        print(f"base al empezar: {cero['base']/1e6:.0f} MB")
        print(f"{'seg':>5}  {'base':>10}  {'WAL generado':>14}  {'total nuevo':>12}")
        try:
            while True:
                m = medir(conn)
                t = time.time() - t0
                d_base = m["base"] - cero["base"]
                d_wal = m["lsn"] - cero["lsn"]
                pico_base = max(pico_base, d_base)
                pico_wal = max(pico_wal, d_wal)
                print(f"{t:5.0f}  {d_base/1e6:8.0f} MB  {d_wal/1e6:11.0f} MB  "
                      f"{(d_base + d_wal)/1e6:9.0f} MB"
                      + ("   ← copiando" if m["copys_activos"] else ""))
                if segundos and t >= segundos:
                    break
                time.sleep(intervalo)
        except KeyboardInterrupt:
            pass
        return {"pico_datos_mb": round(pico_base / 1e6, 1),
                "pico_wal_mb": round(pico_wal / 1e6, 1),
                "pico_total_mb": round((pico_base + pico_wal) / 1e6, 1)}
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--destino", default=os.environ.get("PG_DSN_COPIA"))
    ap.add_argument("--segundos", type=float, default=0,
                    help="0 = hasta Ctrl-C")
    ap.add_argument("--intervalo", type=float, default=2.0)
    a = ap.parse_args(argv)
    if not a.destino:
        print("falta --destino (o PG_DSN_COPIA)", file=sys.stderr)
        return 2
    r = vigilar(a.destino, a.segundos, a.intervalo)
    print(f"\nPICO — datos: {r['pico_datos_mb']:,.0f} MB · "
          f"WAL: {r['pico_wal_mb']:,.0f} MB · "
          f"TOTAL: {r['pico_total_mb']:,.0f} MB")
    print("El TOTAL es lo que el disco del destino tiene que poder aguantar a la "
          "vez, no lo que queda ocupado al final.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
