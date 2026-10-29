"""SOLO LECTURA (immutable=1): cuentas con PESOS guardados en un broker en DÓLARES.

Es el daño que dejaba la regla vieja de la plantilla de Rendi (la moneda de un broker
nuevo salía de la mayoría de filas; AUDIT_plantilla_rendi_2026-10-27.md, PL1). El
arreglo evita casos nuevos; éste mide los que ya están en la base, para decidir cómo
repararlos (revertir el import y volver a subirlo lo cura si el broker queda vacío).

  cd backend && python3 scripts/diag_brokers_moneda.py ~/Downloads/trading-AAAA-MM-DD.db

Un broker cuenta si está en USD/USDT, no es la sub-cuenta "· USD" de otro, no es un
exchange cripto, y tiene lotes en pesos o filas importadas vivas en pesos.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from importing.pipeline import CRYPTO_BROKERS  # noqa: E402
from importing.schema import tx_vivas  # noqa: E402


def main():
    ruta = os.path.expanduser(sys.argv[1])
    conn = sqlite3.connect(f"file:{ruta}?immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    brokers = conn.execute(
        "SELECT user_id, name, currency FROM brokers "
        "WHERE currency IN ('USD','USDT') AND parent_broker_id IS NULL").fetchall()
    afectados = []
    for b in brokers:
        if (b["name"] or "").strip().lower() in CRYPTO_BROKERS:
            continue
        lotes = conn.execute(
            "SELECT COUNT(*) n FROM positions WHERE user_id=? AND broker=? "
            "AND COALESCE(is_cash,0)=0 AND UPPER(COALESCE(currency,''))='ARS'",
            (b["user_id"], b["name"])).fetchone()["n"]
        filas = conn.execute(
            f"SELECT COUNT(*) n, MIN(b.parser_format) fmt FROM {tx_vivas()} "
            "WHERE b.user_id=? AND n.broker=? "
            "AND UPPER(COALESCE(n.settlement_currency, n.currency, ''))='ARS'",
            (b["user_id"], b["name"])).fetchone()
        if not lotes and not filas["n"]:
            continue
        caja = conn.execute(
            "SELECT COALESCE(SUM(invested),0) v FROM positions WHERE user_id=? AND broker=? "
            "AND COALESCE(is_cash,0)=1", (b["user_id"], b["name"])).fetchone()["v"]
        afectados.append((b["user_id"], b["name"], b["currency"], lotes, filas["n"],
                          filas["fmt"], round(caja, 2)))
    print(f"brokers en dólares con pesos adentro: {len(afectados)} "
          f"· cuentas: {len({a[0] for a in afectados})}")
    print(f"{'uid':>6} {'broker':24s} {'moneda':6s} {'lotes ARS':>9} {'filas ARS':>9} "
          f"{'formato':20s} {'caja (en la moneda del broker)':>30}")
    for a in sorted(afectados, key=lambda x: -abs(x[6])):
        print(f"{a[0]:>6} {a[1][:24]:24s} {a[2]:6s} {a[3]:>9} {a[4]:>9} "
              f"{str(a[5])[:20]:20s} {a[6]:>30,.2f}")


if __name__ == "__main__":
    main()
