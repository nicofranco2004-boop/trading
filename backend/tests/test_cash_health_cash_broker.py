"""El aviso de "te quedó el saldo en negativo" y la cuenta de la que salió la plata.

Al terminar un import, persist_batch arma `cash_health` recorriendo
`brokers_touched` para que el frontend avise si algún saldo quedó en descubierto.
El set se llenaba SOLO con `tx.broker` — el broker donde vive la TENENCIA.

Pero la plata no siempre sale de ahí. El CEDEAR comprado con dólares (dólar MEP)
consolida el activo en el broker padre —es la misma especie que la comprada en
pesos, y así la muestra el broker— y debita el sibling '· USD', que es de donde
salió de verdad (ver persister.cash_broker_for). Ese sibling nunca entraba al
set: si la compra lo dejaba en rojo, el aviso no salía justo en la cuenta que
quedó en rojo. Tampoco se le reparaba la cadena mensual.

Corre con: cd backend && python3 -m pytest tests/test_cash_health_cash_broker.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from importing import pipeline as pl       # noqa: E402
from importing import persister as ps      # noqa: E402
import main                                # noqa: E402


HDR = ("Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
       "Liquidacion,Moneda,Importe,_hoja\n")

# DOS imports a propósito. El fondeo en dólares va en el PRIMERO: si viniera en
# el mismo archivo, ese depósito ya mete el sibling en brokers_touched por la vía
# normal (tx.broker) y el test pasaría con o sin el fix, sin probar nada.
CSV_FONDEO = (HDR +
    "Recibo de Cobro / 1,,,2026-01-05,0,-1,2026-01-05,Dólares,50,mov\n"
).encode("utf-8")

# El segundo trae SOLO la compra del CEDEAR en dólares, por más de lo que hay.
# Su tenencia va al broker padre (en pesos) → tx.broker es el PADRE, y el único
# vínculo con la cuenta en dólares es tx.cash_broker, de donde sale la plata.
# La cuenta en dólares queda en descubierto (50 - 200).
CSV_COMPRA = (HDR +
    "Boleto / 900001 / COMPRA ,GOOGL,Cedears,2026-01-10,10,20.00,2026-01-10,Dólares,-200.00,mov\n"
).encode("utf-8")


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


class CashHealthDelSiblingTest(unittest.TestCase):
    BROKER = "Balanz"

    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cashhealth@rendi.test", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,'ARS')",
            (self.uid, self.BROKER))
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()
        self._import(CSV_FONDEO, "fondeo.csv")        # deja dólares en la cuenta
        self.res = self._import(CSV_COMPRA, "compra.csv")

    def _import(self, contenido, nombre):
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=contenido, file_name=nombre,
                broker_hint=self.BROKER, parser_format="balanz_movimientos")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            return ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                                    raw_row_ids_by_index=raw, helpers=_helpers())

    def _sibling(self):
        return f"{self.BROKER} · USD"

    def test_el_escenario_es_el_que_creemos(self):
        """Guarda del test: la tenencia va al padre y el saldo en dólares queda
        NEGATIVO. Si esto cambia, el resto del archivo deja de probar nada."""
        por_broker = {r["broker"]: float(r["q"]) for r in self.conn.execute(
            "SELECT broker, SUM(quantity) q FROM positions WHERE user_id=? AND asset='GOOGL' "
            "AND is_cash=0 GROUP BY broker", (self.uid,))}
        self.assertEqual(list(por_broker), [self.BROKER])
        saldo = self.conn.execute(
            "SELECT invested FROM positions WHERE user_id=? AND broker=? AND is_cash=1",
            (self.uid, self._sibling())).fetchone()
        self.assertIsNotNone(saldo, "no se creó el sibling '· USD'")
        self.assertLess(float(saldo["invested"]), 0, "el saldo en dólares no quedó negativo")

    def test_el_aviso_incluye_la_cuenta_en_dolares(self):
        brokers = {c["broker"] for c in self.res.get("cash_health") or []}
        self.assertIn(self._sibling(), brokers,
                      f"cash_health no mira la cuenta de la que salió la plata: {brokers}")

    def test_el_aviso_marca_el_descubierto(self):
        neg = [c for c in (self.res.get("cash_health") or [])
               if c["broker"] == self._sibling() and float(c.get("balance") or 0) < 0]
        self.assertTrue(neg, "el saldo negativo en dólares no se reporta")
        # El currency del sibling es 'USDT' — bucket interno de "stablecoin USD"
        # que unifica cripto y tradfi (ver _ensure_usd_sibling); el nombre del
        # broker es el que ve el usuario.
        self.assertEqual(neg[0]["currency"], "USDT")


if __name__ == "__main__":
    unittest.main()
