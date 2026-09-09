"""Qué le pasa a la serie de fotos el día que se deploya F3. MEDIDO, no deducido."""
import logging, os, sqlite3, sys, tempfile
from datetime import datetime
from unittest.mock import patch
logging.disable(logging.CRITICAL)

sys.path.insert(0, "/Users/nicolaspussetto/Documents/trading/backend")
os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)
import fechas
from snapshots_job import run_daily_snapshot

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
c = sqlite3.connect(tmp.name)
c.executescript("""
    CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT);
    CREATE TABLE brokers (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        name TEXT, currency TEXT, parent_broker_id INTEGER);
    CREATE TABLE positions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        broker TEXT, asset TEXT, is_cash INTEGER DEFAULT 0, invested REAL, quantity REAL,
        commissions REAL DEFAULT 0, price_override REAL, asset_type TEXT, currency TEXT);
    CREATE TABLE monthly_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        year INTEGER, month INTEGER, broker TEXT, capital_inicio REAL DEFAULT 0,
        capital_final REAL DEFAULT 0, deposits REAL DEFAULT 0, withdrawals REAL DEFAULT 0,
        pnl_realized REAL DEFAULT 0, pnl_unrealized REAL DEFAULT 0);
    CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        date TEXT, total_value REAL, total_invested REAL, net_deposited REAL DEFAULT 0,
        fx_to_usd_blue REAL, holdings_json TEXT, source TEXT, mtm_coverage REAL,
        base TEXT, apto INTEGER, UNIQUE(user_id, date));
    CREATE TABLE fx_rates_daily (date TEXT PRIMARY KEY, blue_venta REAL,
        source TEXT DEFAULT 'unknown', fetched_at TEXT DEFAULT (datetime('now')));
    INSERT INTO users (id, email) VALUES (1, 'x@y');
    INSERT INTO brokers (user_id, name, currency) VALUES (1, 'Schwab', 'USDT');
""")
c.commit(); c.close()

def noche(dia_art, valor, viejo):
    """El cron de las 23:59 ART del `dia_art` (= 02:59 UTC del día siguiente)."""
    c = sqlite3.connect(tmp.name)
    c.execute("DELETE FROM positions")
    c.execute("INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity,"
              " price_override, asset_type) VALUES (1,'Schwab','AAPL',0,50,1,?,'stock')", (valor,))
    c.commit(); c.close()
    instante = datetime(2026, 9, dia_art + 1, 2, 59, 0)      # 02:59 UTC del día siguiente
    with patch("fechas.datetime") as reloj:
        reloj.utcnow.return_value = instante
        if viejo:
            return run_daily_snapshot(tmp.name, lambda: 1500, {},
                                      instante.strftime("%Y-%m-%d"))["target_date"]
        return run_daily_snapshot(tmp.name, lambda: 1500, {})["target_date"]

print("\n  El cron corre a las 23:59 de Argentina. Fotografía el cierre de ESE día.\n")
print("  cierre del…    valor    lo archiva como…    código")
print("  " + "─" * 62)
plan = [(2, 100.0, True), (3, 110.0, True), (4, 120.0, True),
        (5, 130.0, False), (6, 140.0, False)]
valor_de_fecha = {}
for dia_art, valor, viejo in plan:
    etiqueta = noche(dia_art, valor, viejo)
    valor_de_fecha[valor] = f"2026-09-{dia_art:02d}"
    marca = "viejo (UTC)" if viejo else ("NUEVO ← deploy acá" if dia_art == 5 else "nuevo (ART)")
    print(f"  2026-09-{dia_art:02d}      {valor:>6.0f}     {etiqueta}          {marca}")

c = sqlite3.connect(tmp.name); c.row_factory = sqlite3.Row
filas = c.execute("SELECT date, total_value FROM snapshots ORDER BY date").fetchall()
c.close()
print("\n  La serie que le queda al usuario:\n")
print("  archivada en   valor    es en realidad el cierre de…")
print("  " + "─" * 62)
for f in filas:
    real = valor_de_fecha[round(f["total_value"])]
    ok = "✅ correcta" if real == f["date"] else f"⚠️  corrida un día (es el cierre del {real})"
    print(f"  {f['date']}   {f['total_value']:>6.0f}    {ok}")
print()
faltan = {v for v in valor_de_fecha} - {round(f["total_value"]) for f in filas}
if faltan:
    print(f"  Cierres que NO quedaron en la serie: "
          f"{', '.join(valor_de_fecha[v] for v in sorted(faltan))}")
os.unlink(tmp.name)
