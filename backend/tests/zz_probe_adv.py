"""SONDA ADVERSARIAL (temporal, borrar). Corre escenarios y vuelca numeros.

uso: cd backend && python3 tests/zz_probe_adv.py [escenario ...]
"""
import os
import sys
import json
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
for p in (BACKEND, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from importing import pipeline as pl          # noqa: E402
from importing import persister as ps         # noqa: E402
from importing import rebuild as rb           # noqa: E402
import main                                   # noqa: E402

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"


def _csv(*rows):
    return (HDR + "".join(r + "\n" for r in rows)).encode("utf-8")


def _helpers():
    h = main._ImportHelpers()
    h._adjust_broker_cash = main._adjust_broker_cash
    h._adjust_cash = main._adjust_cash
    h._update_monthly_pnl_realized = main._update_monthly_pnl_realized
    h._update_monthly_flow = main._update_monthly_flow
    h._repair_monthly_chain = main._repair_monthly_chain
    h._ensure_usd_sibling = main._ensure_usd_sibling
    h._recalc_pnl_realized_from_ops = main._recalc_pnl_realized_from_ops
    return h


class Env:
    def __init__(self, brokers, tc_blue=1000.0):
        """brokers: lista de (nombre, currency)."""
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users", "fx_rates"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("probe@rendi.test", "x"))
        self.uid = cur.lastrowid
        for name, ccy in brokers:
            self.conn.execute(
                "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                (self.uid, name, ccy))
        self.conn.execute(
            "INSERT OR REPLACE INTO config (user_id, key, value) VALUES (?,?,?)",
            (self.uid, "tc_blue", str(tc_blue)))
        self.conn.commit()

    def imp(self, csv_bytes, broker_hint, rebuild=True):
        with self.conn:
            payload = pl.run_preview(self.conn, uid=self.uid, file_bytes=csv_bytes,
                                     file_name="x.csv", broker_hint=broker_hint,
                                     parser_format="rendi_generic")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            if rebuild:
                tc = ps._read_tc_blue(self.conn, uid=self.uid)
                rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
                main._recalc_pnl_realized_from_ops(self.conn, self.uid)
        return sid

    def dump(self):
        pos = [dict(r) for r in self.conn.execute(
            "SELECT broker, asset, ROUND(quantity,6) q, ROUND(invested,4) inv, "
            "entry_date, ROUND(buy_price,6) px, currency FROM positions "
            "WHERE user_id=? AND is_cash=0 ORDER BY asset, entry_date, broker, q",
            (self.uid,)).fetchall()]
        ops = [dict(r) for r in self.conn.execute(
            "SELECT date, broker, asset, ROUND(quantity,6) q, ROUND(entry_price,6) ep, "
            "ROUND(exit_price,6) xp, ROUND(pnl_usd,2) pnl, currency, entry_date "
            "FROM operations WHERE user_id=? AND op_type='Venta' ORDER BY date, id",
            (self.uid,)).fetchall()]
        cash = [dict(r) for r in self.conn.execute(
            "SELECT broker, ROUND(invested,2) c FROM positions "
            "WHERE user_id=? AND is_cash=1 ORDER BY broker", (self.uid,)).fetchall()]
        seeds = sum(1 for o in ops if abs((o["ep"] or 0) - (o["xp"] or 0)) < 1e-9)
        return {
            "open": pos,
            "open_qty_total": round(sum(p["q"] for p in pos), 6),
            "sells": ops,
            "pnl_total": round(sum(o["pnl"] or 0 for o in ops), 2),
            "seeds": seeds,
            "cash": cash,
        }


SCEN = {}


def scen(fn):
    SCEN[fn.__name__] = fn
    return fn


# ══════════════════════════════════════════════════════════════════════════
# 1. GUARD: tenencia genuina dual-currency (baseline conocido)
# ══════════════════════════════════════════════════════════════════════════
@scen
def s01_dual_5_5_sell7():
    e = Env([("IOL", "ARS")])
    e.imp(_csv(
        "2025-01-05,COMPRA,IOL,NU,5,5000,25000,,,0,ARS,",
        "2025-01-06,COMPRA,IOL,NU,5,10,50,,,0,USD,",
        "2025-02-01,VENTA,IOL,NU,7,5500,38500,,,0,ARS,",
    ), "IOL")
    return e.dump()


# ══════════════════════════════════════════════════════════════════════════
# 2. RETROACTIVIDAD: la MISMA venta, con y sin una fila POSTERIOR
# ══════════════════════════════════════════════════════════════════════════
@scen
def s02_retro_sin_fila_futura():
    e = Env([("IOL", "ARS")])
    e.imp(_csv(
        "2025-01-05,COMPRA,IOL,NU,100,5000,500000,,,0,ARS,",
        "2025-01-06,COMPRA,IOL,NU,100,10,1000,,,0,USD,",
        "2025-02-01,VENTA,IOL,NU,150,5500,825000,,,0,ARS,",
    ), "IOL")
    return e.dump()


@scen
def s02b_retro_con_fila_futura():
    e = Env([("IOL", "ARS")])
    e.imp(_csv(
        "2025-01-05,COMPRA,IOL,NU,100,5000,500000,,,0,ARS,",
        "2025-01-06,COMPRA,IOL,NU,100,10,1000,,,0,USD,",
        "2025-02-01,VENTA,IOL,NU,150,5500,825000,,,0,ARS,",
        "2025-09-01,COMPRA,IOL,NU,300,6000,1800000,,,0,ARS,",
    ), "IOL")
    return e.dump()


# ══════════════════════════════════════════════════════════════════════════
# 3. ORDEN DE IMPORTACION: mismo historial, dos tandas en distinto orden
# ══════════════════════════════════════════════════════════════════════════
_A = _csv(
    "2025-01-05,COMPRA,IOL,NU,100,5000,500000,,,0,ARS,",
    "2025-02-01,VENTA,IOL,NU,150,5500,825000,,,0,ARS,",
)
_B = _csv(
    "2025-01-06,COMPRA,IOL,NU,100,10,1000,,,0,USD,",
    "2025-03-01,VENTA,IOL,NU,40,11,440,,,0,USD,",
)


@scen
def s03_orden_AB():
    e = Env([("IOL", "ARS")])
    e.imp(_A, "IOL")
    e.imp(_B, "IOL")
    return e.dump()


@scen
def s03b_orden_BA():
    e = Env([("IOL", "ARS")])
    e.imp(_B, "IOL")
    e.imp(_A, "IOL")
    return e.dump()


@scen
def s03c_todo_junto():
    e = Env([("IOL", "ARS")])
    e.imp(_csv(
        "2025-01-05,COMPRA,IOL,NU,100,5000,500000,,,0,ARS,",
        "2025-01-06,COMPRA,IOL,NU,100,10,1000,,,0,USD,",
        "2025-02-01,VENTA,IOL,NU,150,5500,825000,,,0,ARS,",
        "2025-03-01,VENTA,IOL,NU,40,11,440,,,0,USD,",
    ), "IOL")
    return e.dump()


# ══════════════════════════════════════════════════════════════════════════
# 4. COSTO CRUZADO: venta USD que se come un lote ARS viejo (FX de la compra)
# ══════════════════════════════════════════════════════════════════════════
@scen
def s04_costo_cruzado_usd_come_ars():
    e = Env([("IOL", "ARS")], tc_blue=1400.0)
    e.imp(_csv(
        "2020-01-05,COMPRA,IOL,NU,100,60,6000,,,0,ARS,",     # 100 nominales a $60 (2020)
        "2026-01-06,COMPRA,IOL,NU,10,12,120,,,0,USD,",
        "2026-02-01,VENTA,IOL,NU,60,13,780,,,0,USD,",
    ), "IOL")
    return e.dump()


# ══════════════════════════════════════════════════════════════════════════
# 5. CRIPTO: mismo coin comprado en ARS (broker AR) y en USD (exchange)
# ══════════════════════════════════════════════════════════════════════════
@scen
def s05_cripto_dual():
    e = Env([("Binance", "USDT")])
    e.imp(_csv(
        "2025-01-05,COMPRA,Binance,BTC,1,60000,60000,,,0,USD,",
        "2025-01-06,COMPRA,Binance,BTC,1,90000000,90000000,,,0,ARS,",
        "2025-02-01,VENTA,Binance,BTC,1.5,70000,105000,,,0,USD,",
    ), "Binance")
    return e.dump()


# ══════════════════════════════════════════════════════════════════════════
# 6. FCI / FUND
# ══════════════════════════════════════════════════════════════════════════
@scen
def s06_fci_dual():
    e = Env([("Cocos", "ARS")])
    e.imp(_csv(
        "2025-01-05,COMPRA,Cocos,PESOSPLUS,1000,1,1000,,,0,ARS,",
        "2025-01-06,COMPRA,Cocos,PESOSPLUS,1000,0.001,1,,,0,USD,",
        "2025-02-01,VENTA,Cocos,PESOSPLUS,1500,1.1,1650,,,0,ARS,",
    ), "Cocos")
    return e.dump()


# ══════════════════════════════════════════════════════════════════════════
# 7. MEP con nominales DISTINTOS (no matchea el cancelador de conducto)
#    + tenencia vieja del mismo bono en USD
# ══════════════════════════════════════════════════════════════════════════
@scen
def s07_mep_partido_con_tenencia_vieja_usd():
    e = Env([("IOL", "ARS")])
    e.imp(_csv(
        "2024-01-05,COMPRA,IOL,AL30,1000,0.6,600,,,0,USD,",     # tenencia genuina USD
        "2026-03-10,COMPRA,IOL,AL30,1000,1000,1000000,,,0,ARS,",  # MEP: compra pesos
        "2026-03-11,VENTA,IOL,AL30,600,0.7,420,,,0,USD,",         # MEP partido en 2
        "2026-03-11,VENTA,IOL,AL30,400,0.7,280,,,0,USD,",
    ), "IOL")
    return e.dump()


# ══════════════════════════════════════════════════════════════════════════
# 8. PERDIDA DE TENENCIA: compra vieja ARS que el usuario TODAVIA tiene,
#    y un round-trip completo en USD despues
# ══════════════════════════════════════════════════════════════════════════
@scen
def s08_roundtrip_usd_no_debe_comer_ars():
    e = Env([("IOL", "ARS")])
    e.imp(_csv(
        "2023-01-05,COMPRA,IOL,NU,100,3000,300000,,,0,ARS,",   # tenencia larga en pesos
        "2025-01-06,COMPRA,IOL,NU,50,10,500,,,0,USD,",
        "2025-06-01,VENTA,IOL,NU,50,12,600,,,0,USD,",          # cierra el round-trip USD
    ), "IOL")
    return e.dump()


@scen
def s08b_roundtrip_usd_vende_de_mas_por_1():
    e = Env([("IOL", "ARS")])
    e.imp(_csv(
        "2023-01-05,COMPRA,IOL,NU,100,3000,300000,,,0,ARS,",
        "2025-01-06,COMPRA,IOL,NU,50,10,500,,,0,USD,",
        "2025-06-01,VENTA,IOL,NU,51,12,612,,,0,USD,",          # 1 de mas (redondeo/typo)
    ), "IOL")
    return e.dump()


# ══════════════════════════════════════════════════════════════════════════
# 9. CROSS-BROKER: padre ARS + sibling '· USD'
# ══════════════════════════════════════════════════════════════════════════
@scen
def s09_cross_broker():
    e = Env([("IOL", "ARS"), ("IOL · USD", "USD")])
    e.imp(_csv(
        "2024-01-05,COMPRA,IOL,NU,100,3000,300000,,,0,ARS,",
    ), "IOL")
    e.imp(_csv(
        "2025-06-01,VENTA,IOL · USD,NU,40,12,480,,,0,USD,",
    ), "IOL · USD")
    return e.dump()


# ══════════════════════════════════════════════════════════════════════════
# 10. ESCALA bono per-100 vs per-1
# ══════════════════════════════════════════════════════════════════════════
@scen
def s10_bono_escala():
    e = Env([("IOL", "ARS")])
    e.imp(_csv(
        "2026-01-05,COMPRA,IOL,AL30,10000,1000,10000000,,,0,ARS,",
        "2026-06-01,VENTA,IOL,AL30,10000,0.72,7200,,,0,USD,",
    ), "IOL")
    return e.dump()


if __name__ == "__main__":
    want = sys.argv[1:] or sorted(SCEN)
    out = {}
    for name in want:
        try:
            out[name] = SCEN[name]()
        except Exception as ex:  # noqa: BLE001
            out[name] = {"ERROR": f"{type(ex).__name__}: {ex}"}
    print(json.dumps(out, indent=1, sort_keys=True, default=str))
