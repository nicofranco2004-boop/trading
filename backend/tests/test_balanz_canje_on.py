"""Canje de obligaciones negociables: el bono viejo sale y el nuevo entra.

Segunda causa de la diferencia Rendi (USD 71.634) vs Balanz (u$s 51.735) del
mismo usuario que motivó `test_balanz_transferencia_externa.py`.

Cuando una empresa canjea un bono por otro (GEMSA, Petrolera Aconcagua), Balanz
lo manda como "Movimiento Manual / … canje …": una fila con la cantidad del bono
VIEJO en negativo y otra con la del NUEVO en positivo, el mismo día, las dos con
Importe 0 — porque un canje no mueve efectivo. A veces con un certificado
provisorio en el medio ("21030"), que entra en un canje y sale en el siguiente.

El parser las descartaba con un guard cuya intención era otra: evitar emitir un
FEE de monto 0 que el validador rechaza. Como no traían plata, se tiraba la fila
entera y con ella la CANTIDAD → el bono viejo NUNCA salía (posición fantasma,
≈ USD 1.120 en el export real) y el nuevo NUNCA llegaba (faltaban MR44O 667,
MR46O 1.020, MR47O 140, BPY26 600, AE38 50). PECNO llegó a quedar en −24: una
venta de un bono que Rendi nunca había dado de alta.

El mismo guard se tragaba una "Amortización / RCCJO" de −232 nominales con
Importe 0 (el cobro había venido días antes en su propia fila), dejando el bono
entero como posición fantasma.

Corre con: cd backend && python3 -m pytest tests/test_balanz_canje_on.py
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
from importing.parsers.balanz_movimientos import BalanzMovimientosParser
import main


HDR = ("Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,"
       "Liquidacion,Moneda,Importe,_hoja\n")

# La forma REAL del export: compra el bono viejo, lo canjea por el nuevo (dos
# filas del mismo día, sin plata) y por separado amortiza otro bono entero.
CSV = (HDR +
    "Recibo de Cobro / 1,,,2025-01-02,0,-1,2025-01-02,Pesos,1000000,mov\n"
    "Boleto / 100 / COMPRA ,MRCLO,Corporativos,2025-01-10,600,1000,2025-01-10,Pesos,-600000,mov\n"
    "Boleto / 101 / COMPRA ,RCCJO,Corporativos,2025-01-10,232,900,2025-01-10,Pesos,-208800,mov\n"
    "Movimiento Manual / Oferta temprana canje GEMSA CL 44,MRCLO,Corporativos,2026-04-15,-600,-1,2026-04-15,,0,mov\n"
    "Movimiento Manual / Oferta temprana canje GEMSA CL 44,MR44O,Corporativos,2026-04-15,667,-1,2026-04-15,,0,mov\n"
    "Renta y Amortización / RCCJO,RCCJO,Corporativos,2026-08-04,0,-1,2026-08-04,Dólares,169.95,mov\n"
    "Amortización / RCCJO,RCCJO,Corporativos,2026-08-07,-232,-1,2026-08-07,,0,mov\n"
).encode("utf-8")


def _helpers():
    h = main._ImportHelpers()
    for n in ("_adjust_broker_cash", "_adjust_cash", "_update_monthly_pnl_realized",
              "_update_monthly_flow", "_repair_monthly_chain", "_ensure_usd_sibling",
              "_recalc_pnl_realized_from_ops"):
        setattr(h, n, getattr(main, n))
    return h


class CanjeDeOnE2E(unittest.TestCase):
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
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("balanz_canje@rendi.test", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, self.BROKER, "ARS"))
        self.conn.execute(
            "INSERT INTO config (user_id, key, value) VALUES (?,?,?) "
            "ON CONFLICT (key, user_id) DO UPDATE SET value=EXCLUDED.value",
            (self.uid, "tc_blue", "1000"))
        self.conn.commit()
        with self.conn:
            payload = pl.run_preview(
                self.conn, uid=self.uid, file_bytes=CSV, file_name="movimientos.csv",
                broker_hint=self.BROKER, parser_format="balanz_movimientos")
        self.sid = payload["session_id"]
        with self.conn:
            txs, raw = pl.load_session_for_confirm(
                self.conn, uid=self.uid, session_id=self.sid)
            ps.persist_batch(self.conn, uid=self.uid, batch_id=self.sid, txs=txs,
                             raw_row_ids_by_index=raw, helpers=_helpers())
            rb.rebuild_fifo_after_import(
                self.conn, self.uid, self.sid,
                tc_blue=ps._read_tc_blue(self.conn, uid=self.uid))

    def tearDown(self):
        self.conn.close()

    def _qty(self, asset):
        return float(self.conn.execute(
            "SELECT COALESCE(SUM(quantity),0) q FROM positions "
            "WHERE user_id=? AND asset=? AND is_cash=0", (self.uid, asset)).fetchone()["q"])

    def test_el_bono_viejo_se_va(self):
        self.assertEqual(self._qty("MRCLO"), 0.0,
                         "el bono canjeado sigue en la cartera")

    def test_el_bono_nuevo_llega(self):
        self.assertEqual(self._qty("MR44O"), 667.0,
                         "el bono que dio el canje no entró")

    def test_el_bono_amortizado_se_va(self):
        self.assertEqual(self._qty("RCCJO"), 0.0,
                         "el bono amortizado entero sigue en la cartera")

    def test_el_canje_no_toca_la_caja(self):
        # 1.000.000 − 600.000 − 208.800 = 191.200. El canje y la amortización de
        # nominales no mueven efectivo (Importe 0).
        cash = float(self.conn.execute(
            "SELECT COALESCE(SUM(invested),0) s FROM positions "
            "WHERE user_id=? AND is_cash=1 AND asset='ARS'", (self.uid,)).fetchone()["s"])
        self.assertAlmostEqual(cash, 191200.0, places=2)

    def test_el_cobro_de_la_amortizacion_si_entra(self):
        div = float(self.conn.execute(
            "SELECT COALESCE(SUM(gross_amount),0) s FROM import_normalized_tx "
            "WHERE batch_id=? AND operation_type='DIVIDEND'", (self.sid,)).fetchone()["s"])
        self.assertAlmostEqual(div, 169.95, places=2)


class CanjePorElSigno(unittest.TestCase):
    def _parse(self, *filas):
        return BalanzMovimientosParser().parse(
            HDR.replace(",_hoja", "") + "".join(f + "\n" for f in filas))

    def test_canje_de_on_mueve_los_nominales(self):
        res = self._parse(
            "Movimiento Manual / Oferta temprana canje GEMSA CL 44,MRCLO,Corporativos,2026-04-15,-600,-1,2026-04-15,,0",
            "Movimiento Manual / Oferta temprana canje GEMSA CL 44,MR44O,Corporativos,2026-04-15,667,-1,2026-04-15,,0",
        )
        self.assertEqual(res.parse_errors, [])
        d = {r.data["activo"]: r.data for r in res.raw_rows}
        self.assertEqual(d["MRCLO"]["tipo"], "VENTA")
        self.assertEqual(d["MR44O"]["tipo"], "COMPRA")
        self.assertEqual(float(d["MR44O"]["cantidad"]), 667.0)
        # ninguna mueve plata
        self.assertTrue(all(float(r.data.get("monto") or 0) == 0 for r in res.raw_rows))

    def test_amortizacion_total_baja_el_nominal(self):
        res = self._parse(
            "Amortización / RCCJO,RCCJO,Corporativos,2026-08-07,-232,-1,2026-08-07,,0")
        self.assertEqual(res.parse_errors, [])
        self.assertEqual([r.data["tipo"] for r in res.raw_rows], ["VENTA"])
        self.assertEqual(float(res.raw_rows[0].data["cantidad"]), 232.0)

    def test_el_ajuste_de_relacion_suma_nominales(self):
        res = self._parse(
            "Movimiento Manual / Ajuste por cambio relacion de canje GEMSA,MR46O,"
            "Corporativos,2026-06-10,120,-1,2026-06-10,,0")
        self.assertEqual([r.data["tipo"] for r in res.raw_rows], ["COMPRA"])
        self.assertEqual(float(res.raw_rows[0].data["cantidad"]), 120.0)

    def test_el_arancel_del_canje_sigue_siendo_plata(self):
        # Misma familia "Movimiento Manual" pero SIN cantidad y CON importe:
        # es un cargo, no una acción societaria. No debe cambiar.
        res = self._parse(
            "Movimiento Manual / Arancel oferta de canje - GEMSA,,,2026-04-15,0,-1,2026-04-15,Pesos,-1500")
        self.assertEqual([r.data["tipo"] for r in res.raw_rows], ["FEE"])
        self.assertEqual(float(res.raw_rows[0].data["monto"]), 1500.0)


class LoQueLaReclasificacionNoDebeTocar(unittest.TestCase):
    """Hallazgos de auditar el propio fix de los canjes.

    La reclasificación a "acción societaria" corre ARRIBA del loop, antes que
    las ramas de FCI y de trade-con-precio. Si se pasa de ancha, les roba filas
    y las emite a precio 0 — o sea les borra el costo."""

    def _parse(self, *filas):
        return BalanzMovimientosParser().parse(
            HDR.replace(",_hoja", "") + "".join(f + "\n" for f in filas))

    def test_una_fila_con_precio_real_conserva_su_precio(self):
        # Un rescate de FCI sin plata pero CON precio: es un trade, no un canje.
        # Si la reclasificación se lo lleva, entra a precio 0 y pierde el costo.
        res = self._parse(
            "Rescate a Balanz,BAHUSD A,Fondos,2026-09-01,-1425.35,1.433492,2026-09-01,Dólares,0")
        # OJO: exigir primero que la fila EXISTA. `all([])` es True, así que una
        # versión anterior de este test pasaba en verde con la fila descartada —
        # no verificaba nada. Lo que se mide es que conserve su PRECIO, no cuántas
        # filas salen: desde el fix de la pata del fondo sale además su pata de
        # caja compensatoria (ver `test_balanz_fci_pata_del_fondo.py`).
        movs = [r.data for r in res.raw_rows if r.data.get("activo")]
        self.assertEqual(len(movs), 1, f"la fila se perdió: {[r.data for r in res.raw_rows]}")
        self.assertAlmostEqual(float(movs[0]["precio"]), 1.433492, places=6)

    def test_con_precio_y_sin_ticker_no_inventa_un_movimiento_de_cero(self):
        # Ninguna rama la quiere: no debe emitir un FEE de monto 0 (el validador
        # lo rechaza) ni reventar con el importe vacío.
        res = self._parse(
            "Renta / X,,Bonos,2026-09-01,100,55.5,2026-09-01,Pesos,")
        self.assertEqual(res.raw_rows, [])
        self.assertEqual(res.parse_errors, [])

    def test_la_fila_manual_CON_plata_sigue_siendo_plata(self):
        # La reclasificación exige `not has_cash`: un manual con importe sigue
        # su camino de siempre aunque traiga cantidad.
        res = self._parse(
            "Movimiento Manual / Gastos por operación de Fondos,BMM A,Fondos,"
            "2026-09-01,10,-1,2026-09-01,Pesos,-500")
        self.assertEqual([r.data["tipo"] for r in res.raw_rows], ["FEE"])
        self.assertEqual(float(res.raw_rows[0].data["monto"]), 500.0)


if __name__ == "__main__":
    unittest.main()
