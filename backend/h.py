import os, tempfile, warnings, json
warnings.filterwarnings("ignore")
os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

def nuevo():
    import main
    C = main.get_db()
    C.execute("DELETE FROM snapshots"); C.execute("DELETE FROM monthly_entries")
    C.execute("DELETE FROM positions"); C.execute("DELETE FROM operations")
    C.commit()
    return C

UID = 1

def me(C, y, m, ci, cf, dep=0.0, wd=0.0, pr=0.0, pu=0.0, broker="global"):
    C.execute("""INSERT OR REPLACE INTO monthly_entries
        (user_id, year, month, broker, deposits, withdrawals, pnl_realized,
         pnl_unrealized, capital_inicio, capital_final)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", (UID, y, m, broker, dep, wd, pr, pu, ci, cf))

def snap(C, date, value, netdep, source, cov=None, holdings=True, invested=None, fx=None):
    C.execute("""INSERT OR REPLACE INTO snapshots
        (user_id, date, total_value, total_invested, net_deposited, source,
         mtm_coverage, holdings_json, fx_to_usd_blue)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (UID, date, value, invested if invested is not None else value, netdep,
         source, cov, json.dumps([{"asset": "AAPL", "value_usd": value}]) if holdings else None, fx))

def pos(C):
    C.execute("INSERT INTO positions (user_id, broker, asset, is_cash, quantity, invested, entry_date)"
              " VALUES (?,?,?,?,?,?,?)", (UID, "IOL", "AAPL", 0, 1, 100, "2026-01-05"))
