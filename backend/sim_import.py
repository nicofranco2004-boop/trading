"""Simula una importación de Balanz Movimientos end-to-end en un DB limpio y
reporta los números que vería el usuario en el dashboard — para verificar ANTES
de que el usuario lo cargue que no haya capital aportado negativo, P&L realizado
inflado ni ganancias retiradas fantasma.

Uso: python3 sim_import.py "<ruta al .xlsx de Movimientos>" [parser_format]
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); _tmp.close()
os.environ["DB_PATH"] = _tmp.name

from importing import pipeline as pl
from importing import persister as ps
from importing import rebuild as rb
from importing import maturity as mat
import main


def _helpers():
    h = main._ImportHelpers()
    for n in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, n, getattr(main, n))
    return h


def run(path, parser_format="balanz_movimientos", broker="Balanz", tc_blue=1582.5):
    conn = main.get_db()
    for t in ("import_op_links", "import_normalized_tx", "import_raw_rows", "import_batches",
              "operations", "positions", "monthly_entries", "snapshots", "config", "brokers", "users"):
        try: conn.execute(f"DELETE FROM {t}")
        except Exception: pass
    uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                       ("sim@rendi.test", "x")).lastrowid
    conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)", (uid, broker, "ARS"))
    conn.execute("INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
                 (uid, "tc_blue", str(tc_blue)))
    conn.commit()

    with open(path, "rb") as f:
        file_bytes = f.read()

    with conn:
        payload = pl.run_preview(conn, uid=uid, file_bytes=file_bytes, file_name=os.path.basename(path),
                                 broker_hint=broker, parser_format=parser_format, route_by_currency=True)
    if payload.get("error"):
        print("ERROR preview:", payload["error"]); return
    sid = payload["session_id"]
    perrs = payload.get("parse_errors") or payload.get("errors") or []
    print(f"parser={parser_format} · filas válidas (preview)={payload.get('valid_count', payload.get('total_rows','?'))}"
          f" · parse_errors={len(perrs)}")

    with conn:
        txs, raw = pl.load_session_for_confirm(conn, uid=uid, session_id=sid)
        ps.persist_batch(conn, uid=uid, batch_id=sid, txs=txs, raw_row_ids_by_index=raw, helpers=_helpers())
        tc = ps._read_tc_blue(conn, uid=uid)
        for step in (
            lambda: rb.rebuild_fifo_after_import(conn, uid, sid, tc_blue=tc),
            lambda: mat.sweep_matured_letras(conn, uid),
            lambda: mat.sweep_bond_amortizations(conn, uid),
            lambda: main._recalc_pnl_realized_from_ops(conn, uid),
        ):
            try: step()
            except Exception as ex: print("  (paso best-effort falló:", type(ex).__name__, str(ex)[:60], ")")

    # ── Aggregates del dashboard (global) ───────────────────────────────────
    g = conn.execute("""SELECT COALESCE(SUM(deposits),0) dep, COALESCE(SUM(withdrawals),0) wd,
                               COALESCE(SUM(pnl_realized),0) pnl
                          FROM monthly_entries WHERE user_id=? AND broker='global'""", (uid,)).fetchone()
    dep, wd, pnl = g["dep"], g["wd"], g["pnl"]
    net = dep - wd
    npos = conn.execute("SELECT COUNT(*) c FROM positions WHERE user_id=? AND is_cash=0 AND quantity>0", (uid,)).fetchone()["c"]
    cost = conn.execute("SELECT COALESCE(SUM(invested),0) v FROM positions WHERE user_id=? AND is_cash=0", (uid,)).fetchone()["v"]
    cash = conn.execute("""SELECT p.broker, br.currency, p.invested FROM positions p
                            JOIN brokers br ON br.name=p.broker AND br.user_id=p.user_id
                           WHERE p.user_id=? AND p.is_cash=1""", (uid,)).fetchall()

    print("\n" + "=" * 60)
    print("RESULTADO DE LA SIMULACIÓN (lo que vería el dashboard)")
    print("=" * 60)
    print(f"  Depósitos (Σ):        {dep:>16,.2f}")
    print(f"  Retiros (Σ):          {wd:>16,.2f}")
    print(f"  CAPITAL APORTADO:     {net:>16,.2f}   {'❌ NEGATIVO (bug)' if net < 0 else '✅ positivo'}")
    print(f"  P&L REALIZADO (Σ):    {pnl:>16,.2f}")
    print(f"  GANANCIAS RETIRADAS:  {max(0, wd-dep):>16,.2f}   {'❌ FANTASMA' if (wd-dep) > 1 and wd > 0 else '✅ ok'}")
    print(f"  Posiciones abiertas:  {npos:>16}")
    print(f"  Cost basis holdings:  {cost:>16,.2f}")
    cash_str = ', '.join("{}={:,.0f} {}".format(c['broker'], c['invested'], c['currency']) for c in cash) or '—'
    print("  Cash:                 " + cash_str)
    print("=" * 60)
    conn.close()


if __name__ == "__main__":
    path = sys.argv[1]
    fmt = sys.argv[2] if len(sys.argv) > 2 else "balanz_movimientos"
    run(path, fmt)
