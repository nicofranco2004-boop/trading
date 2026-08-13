"""E2E Balanz: un CEDEAR comprado con DÓLARES (dólar MEP) no debe partirse en dos.

Reporte de un usuario (2026-08-08): cargó su cartera de Balanz y SPY y GOOGL le
aparecieron DOS veces — una parte en el broker en pesos y otra en el sub-broker
USD, con cantidades distintas, y ninguna coincidía con su resumen:

    SPY   → Rendi: 8 en ARS + 3 en USD   · Balanz: 9   (una sola tenencia)
    GOOGL → Rendi: 7 en ARS + 5 en USD   · Balanz: 12  (una sola tenencia)

Causa: el routing por moneda del importador mandaba al sub-broker USD CUALQUIER
fila en dólares, incluida la compra del CEDEAR. Pero un CEDEAR es la MISMA
especie se pague en pesos o en dólares — el broker lo consolida en una sola
tenencia. Lo que sí sale de la cuenta en dólares es la PLATA.

Este test usa la forma REAL del export de Movimientos de Balanz (datos
sintéticos con la misma estructura: la compra en dólares viene en DOS filas del
mismo boleto — una en Dólares con el precio y otra en Pesos con los gastos — y
el dividendo en acciones llega sin moneda) y corre el pipeline completo con
rebuild, como en producción.

Corre con: cd backend && python3 -m pytest tests/test_balanz_cedear_usd_e2e.py
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

from importing import pipeline as pl
from importing import persister as ps
from importing import rebuild as rb
import main


HDR = ("Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
       "Liquidacion,Moneda,Importe,_hoja\n")

# Mismo esqueleto que el archivo real del usuario.
CSV = (HDR +
    # Fondeo en pesos y en dólares (así los nombra el export real)
    "Recibo de Cobro / 1,,,2023-11-01,0,-1,2023-11-01,Pesos,200000,mov\n"
    "Recibo de Cobro / 2,,,2023-11-01,0,-1,2023-11-01,Dólares,500,mov\n"
    # COMPRA EN DÓLARES: dos filas del MISMO boleto (la de Pesos son los gastos,
    # con precio -1 = sin precio). Así viene en el export real.
    "Boleto / 5603367 / COMPRA ,GOOGL,Cedears,2023-11-14,5,2.35,2023-11-14,Dólares,-11.82,mov\n"
    "Boleto / 5603367 / COMPRA ,GOOGL,Cedears,2023-11-14,5,-1,2023-11-14,Pesos,-9.12,mov\n"
    "Boleto / 5603368 / COMPRA ,SPY,Cedears,2023-11-14,1,22.6,2023-11-14,Dólares,-22.74,mov\n"
    "Boleto / 5603368 / COMPRA ,SPY,Cedears,2023-11-14,1,-1,2023-11-14,Pesos,-17.95,mov\n"
    # ACCIÓN DEL EXTERIOR en dólares (cuenta cable): ESTA sí vive en la cuenta USD
    "Boleto / 5603369 / COMPRA ,CCJ.E,Acciones,2023-11-15,1,97.39,2023-11-15,Dólares,-97.39,mov\n"
    # Compras en pesos del MISMO CEDEAR
    "Boleto / 2804519 / COMPRA ,GOOGL,Cedears,2026-03-05,1,7610,2026-03-05,Pesos,-7660.64,mov\n"
    "Boleto / 6140563 / COMPRA ,GOOGL,Cedears,2026-06-04,3,9605,2026-06-04,Pesos,-29006.77,mov\n"
    "Boleto / 6140564 / COMPRA ,SPY,Cedears,2026-06-04,3,19080,2026-06-04,Pesos,-57620.93,mov\n"
    "Boleto / 6730382 / COMPRA ,SPY,Cedears,2026-06-19,3,19280,2026-06-19,Pesos,-58224.92,mov\n"
    "Boleto / 8091522 / COMPRA ,GOOGL,Cedears,2026-07-27,1,9035,2026-07-27,Pesos,-9095.14,mov\n"
    "Boleto / 8388884 / COMPRA ,GOOGL,Cedears,2026-08-03,1,10220,2026-08-03,Pesos,-10288.01,mov\n"
    "Boleto / 8694302 / COMPRA ,GOOGL,Cedears,2026-08-07,1,9740,2026-08-07,Pesos,-9804.82,mov\n"
    # Dividendo en ACCIONES: suma nominales, sin moneda ni importe
    "Dividendo en acciones / SPY,SPY,Cedears,2026-06-01,2,-1,2026-06-01,,0,mov\n"
).encode("utf-8")

# La verdad, según el resumen de Balanz del mismo usuario (Mis Instrumentos y
# ResumenDeCuenta coinciden): una sola tenencia por CEDEAR.
ESPERADO = {"SPY": 9.0, "GOOGL": 12.0}


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


class BalanzCedearUsdE2E(unittest.TestCase):
    BROKER = "Balanz"

    def setUp(self):
        self.conn = main.get_db()
        for t in ("import_op_links", "import_normalized_tx", "import_raw_rows",
                  "import_batches", "operations", "positions", "monthly_entries",
                  "snapshots", "config", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("balanz_cedear@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, self.BROKER, "ARS"))
        # Conflicto por la PK compuesta (key, user_id) — nunca por `key` sola.
        # La query nombra las 3 columnas de `config`: no hay columna que el viejo
        # INSERT OR REPLACE borrara al reinsertar. Conversión equivalente.
        # (setUp vacía `config` y este es el único escritor: siempre INSERT limpio.)
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()
        self._import()

    def tearDown(self):
        self.conn.close()

    def _import(self):
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=CSV, file_name="movimientos.csv",
                broker_hint=self.BROKER, parser_format="balanz_movimientos")
        sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(self.conn, uid=self.uid, session_id=sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            tc = ps._read_tc_blue(self.conn, uid=self.uid)
            rb.rebuild_fifo_after_import(self.conn, self.uid, sid, tc_blue=tc)
        self.batch_id = sid

    def _qty_por_broker(self, asset):
        return {r["broker"]: float(r["q"]) for r in self.conn.execute(
            "SELECT broker, SUM(quantity) q FROM positions "
            "WHERE user_id=? AND asset=? AND is_cash=0 GROUP BY broker",
            (self.uid, asset)).fetchall()}

    # ── lo que reportó el usuario ───────────────────────────────────────────
    def test_el_cedear_no_se_parte_en_dos_brokers(self):
        for asset in ("SPY", "GOOGL"):
            por_broker = self._qty_por_broker(asset)
            self.assertEqual(
                list(por_broker), [self.BROKER],
                f"{asset} quedó partido entre brokers: {por_broker}")

    def test_la_cantidad_coincide_con_el_resumen_de_balanz(self):
        for asset, esperado in ESPERADO.items():
            total = sum(self._qty_por_broker(asset).values())
            self.assertAlmostEqual(total, esperado, places=6, msg=f"{asset}")

    def test_la_accion_del_exterior_sigue_en_la_cuenta_en_dolares(self):
        # El fix es SOLO para CEDEARs: una acción del exterior comprada en
        # dólares (cuenta cable) tiene su tenencia en la cuenta USD de verdad.
        por_broker = self._qty_por_broker("CCJ.E")
        self.assertEqual(len(por_broker), 1)
        self.assertIn("USD", list(por_broker)[0],
                      f"CCJ.E debería vivir en el sibling USD, quedó en {por_broker}")

    def test_la_plata_del_cedear_sale_de_la_cuenta_en_dolares(self):
        # La tenencia se consolida, pero el costo salió de los dólares: el cash
        # USD tiene que haber bajado por las dos compras (11.82 + 22.74) más la
        # acción del exterior (97.39), sobre los 500 depositados.
        cash = {r["broker"]: float(r["invested"] or 0) for r in self.conn.execute(
            "SELECT broker, invested FROM positions WHERE user_id=? AND is_cash=1",
            (self.uid,)).fetchall()}
        usd_broker = next((b for b in cash if "USD" in b), None)
        self.assertIsNotNone(usd_broker, f"no se creó el sub-broker USD: {cash}")
        self.assertAlmostEqual(cash[usd_broker], 500 - 11.82 - 22.74 - 97.39, places=2)

    def test_un_solo_lote_por_moneda_conserva_el_costo_en_dolares(self):
        # El lote comprado en dólares conserva su moneda nativa aunque viva en
        # el broker en pesos — si no, su costo se leería como pesos.
        lotes = {(r["currency"], float(r["quantity"])): float(r["invested"])
                 for r in self.conn.execute(
                     "SELECT currency, quantity, invested FROM positions "
                     "WHERE user_id=? AND asset='GOOGL' AND is_cash=0", (self.uid,)).fetchall()}
        usd_lote = [v for (c, q), v in lotes.items() if c == "USD"]
        self.assertEqual(len(usd_lote), 1, f"lotes GOOGL: {lotes}")
        self.assertAlmostEqual(usd_lote[0], 11.82, places=2)

    def test_el_dividendo_en_acciones_no_se_cuenta_dos_veces(self):
        # Llega sin moneda y sin importe: 2 nominales, una sola vez.
        filas = self.conn.execute(
            "SELECT COUNT(*) c FROM positions WHERE user_id=? AND asset='SPY' "
            "AND is_cash=0 AND COALESCE(invested,0)=0", (self.uid,)).fetchone()["c"]
        self.assertEqual(filas, 1)


    def test_revertir_deja_las_dos_cuentas_en_cero(self):
        """Revertir el batch entero tiene que deshacer TODO: depósitos y
        compras. Si la plata de un CEDEAR pagado en dólares vuelve a la cuenta
        equivocada, la de pesos queda con un sobrante y la de dólares en
        negativo — y cada ciclo revertir + re-importar lo compone (audit
        2026-08-10, reproducido con -150 USD / +150 ARS por vuelta)."""
        from importing import persister as _ps
        with self.conn:
            _ps.revert_batch(self.conn, uid=self.uid, batch_id=self.batch_id,
                             helpers=_helpers())
        cash = {r["broker"]: round(float(r["invested"] or 0), 2)
                for r in self.conn.execute(
                    "SELECT broker, invested FROM positions WHERE user_id=? AND is_cash=1",
                    (self.uid,)).fetchall()}
        for broker, saldo in cash.items():
            self.assertAlmostEqual(saldo, 0.0, places=2,
                                   msg=f"{broker} quedó en {saldo} después de revertir todo")


if __name__ == "__main__":
    unittest.main()