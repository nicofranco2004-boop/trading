"""Clasificador de ventas de GET /api/admin/diagnose-sell-fx (v2, sin currency/fx_to_usd).

La v1 branchaba sobre operations.currency y operations.fx_to_usd, que están NULL en todo
el histórico (se agregaron en 96976a4) → metía el 100% de las 73.718 ventas de producción
en un solo bucket. La v2 reconstruye el TC perdido desde la identidad
`100*pnl_usd/pnl_pct == invested_usd` (persister.py:615):

    T_rec = (exit_price*quantity - commissions) / (pnl_usd + 100*pnl_usd/pnl_pct)

Este test genera las filas con una RÉPLICA LINEA A LINEA de persister._persist_sell_fifo
(líneas 547-638) para que la verdad de cada escenario sea conocida, y verifica que cada
uno cae en su bucket. Los casos 4 y 4b son los que refutaron al estimador anterior
(basado en entry_price): daban 180 y 1450, o sea DENTRO y POR ENCIMA de la banda del
caso reparable de verdad (1450), y ningún umbral los separaba. Con T_rec dan 1,0000.
"""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False); TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main

TC_BLUE = 1450.0        # el dólar VIVO del import (persister.py:547)
BLUE_2021 = 180.0       # el dólar que REALMENTE regía en 2021


def engine_sell(*, invested, buy_price, qty, exit_price, sell_ccy, lot_ccy,
                buy_comm=0.0, sell_comm=0.0, entry_blue=None, transfer_out=False,
                tc_blue=TC_BLUE):
    """Réplica exacta de persister._persist_sell_fifo para una venta TOTAL (ratio=1)."""
    base = invested + buy_comm
    tc_venta = tc_blue if sell_ccy == "ARS" else 1.0
    if lot_ccy != sell_ccy and tc_blue:
        if lot_ccy == "USD" and sell_ccy == "ARS":
            base = base * tc_venta                 # persister.py:573
        elif lot_ccy == "ARS" and sell_ccy == "USD":
            base = base / entry_blue               # persister.py:582
    E, c = base, sell_comm
    if transfer_out:
        pnl_usd = 0.0
        invested_usd = E / tc_venta if sell_ccy == "ARS" else E
    elif sell_ccy == "ARS":
        pnl_usd = (exit_price * qty - E - c) / tc_venta      # persister.py:602-603
        invested_usd = E / tc_venta                          # persister.py:604
    else:
        pnl_usd = exit_price * qty - E - c                   # persister.py:609
        invested_usd = E                                     # persister.py:610
    pct = (pnl_usd / invested_usd * 100) if invested_usd else None
    return dict(entry_price=buy_price, exit_price=exit_price, quantity=qty,
                pnl_usd=round(pnl_usd, 2),
                pnl_pct=round(pct, 4) if pct is not None else None,
                commissions=round(c, 4))


class DiagnoseSellFxTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("operations", "brokers", "users", "fx_rates_daily",
                  "import_op_links", "import_normalized_tx", "import_batches"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved) VALUES (?,?,1)",
            ("sellfx@test", "x")).lastrowid
        # Serie FX: 2021 al 180, 2025-2026 al 1450 (el motor usó 1450 para TODAS).
        for d, b in [("2021-01-15", BLUE_2021), ("2021-06-15", BLUE_2021),
                     ("2025-11-13", 1450.0), ("2026-01-10", 1500.0)]:
            self.conn.execute(
                "INSERT OR REPLACE INTO fx_rates_daily (date,blue_venta,mep_venta,source) "
                "VALUES (?,?,?,?)", (d, b, b * 1.05, "test"))
        self.bid = "b-sellfx"
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status) "
            "VALUES (?,?,?,?,?,?)", (self.bid, self.uid, "Cocos", "generic", "h", "confirmed"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _op(self, fecha, asset, campos, *, linked=True, entry_date=None):
        oid = self.conn.execute(
            "INSERT INTO operations (user_id,date,broker,asset,op_type,entry_price,exit_price,"
            "quantity,pnl_usd,pnl_pct,commissions,entry_date) VALUES (?,?,?,?,'Venta',?,?,?,?,?,?,?)",
            (self.uid, fecha, "Cocos", asset, campos["entry_price"], campos["exit_price"],
             campos["quantity"], campos["pnl_usd"], campos["pnl_pct"],
             campos["commissions"], entry_date)).lastrowid
        if linked:
            self.conn.execute(
                "INSERT INTO import_op_links (batch_id,raw_row_id,operation_id) VALUES (?,?,?)",
                (self.bid, None, oid))
        self.conn.commit()
        return oid

    def _buckets(self):
        res = main.admin_diagnose_sell_fx(uid=self.uid)
        return res, {k: v["n"] for k, v in res["ventas"]["buckets"].items()}

    # ── B1: el caso masivo — lote ARS vendido en ARS ──────────────────────
    def test_b1_reparable_ars_recupera_el_tc_y_el_factor_de_2021(self):
        self._op("2021-06-15", "GGAL", engine_sell(
            invested=100_000, buy_price=1_000, qty=100, exit_price=1_200,
            lot_ccy="ARS", sell_ccy="ARS"))
        res, b = self._buckets()
        self.assertEqual(b.get("B1_REPARABLE_ARS"), 1, b)
        op = res["impacto_blue"]["ops_mas_distorsionadas"][0]
        self.assertAlmostEqual(op["tc_recuperado"], TC_BLUE, delta=1.0)   # recupera 1450
        self.assertEqual(op["fx_de_la_fecha"], BLUE_2021)                 # contra 180
        # 20.000 ARS de ganancia: /1450 da 13,79 USD; /180 da 111,11.
        self.assertAlmostEqual(op["pnl_actual_usd"], 13.79, delta=0.02)
        self.assertAlmostEqual(op["pnl_corregido_usd"], 111.11, delta=0.5)
        self.assertAlmostEqual(res["impacto_blue"]["factor"], TC_BLUE / BLUE_2021, delta=0.1)

    def test_b1_sobrevive_comision_de_compra(self):
        """La comisión de COMPRA sesga el eje s, no la clasificación (β = I/(I+Cb))."""
        self._op("2021-06-15", "YPFD", engine_sell(
            invested=100_000, buy_comm=2_000, buy_price=1_000, qty=100, exit_price=1_300,
            lot_ccy="ARS", sell_ccy="ARS"))
        _, b = self._buckets()
        self.assertEqual(b.get("B1_REPARABLE_ARS"), 1, b)

    # ── B2 / B5: la colisión en T_rec ≈ 1 la parte el link, no el broker ──
    def test_b2_usd_genuina_no_se_toca(self):
        self._op("2026-01-10", "AAPL", engine_sell(
            invested=1_000, buy_price=10, qty=100, exit_price=12,
            lot_ccy="USD", sell_ccy="USD"))
        res, b = self._buckets()
        self.assertEqual(b.get("B2_USD_GENUINA"), 1, b)
        self.assertEqual(res["impacto_blue"]["pnl_actual_usd"], 0.0)   # no entra a reparación

    def test_b5_manual_ambigua_las_dos_filas_indistinguibles(self):
        """El residuo irreducible: USD real y ARS con TC vacío son byte-idénticas."""
        fila_a = engine_sell(invested=1_000, buy_price=10, qty=100, exit_price=12,
                             lot_ccy="USD", sell_ccy="USD")
        fila_b = engine_sell(invested=1_450_000, buy_price=14_500, qty=100, exit_price=17_400,
                             lot_ccy="ARS", sell_ccy="ARS", tc_blue=1.0)   # TC vacío → 1
        self.assertEqual(fila_a["pnl_pct"], fila_b["pnl_pct"])             # ambas 20,0000
        self._op("2026-01-10", "GGAL", fila_a, linked=False)
        self._op("2026-01-10", "GGAL", fila_b, linked=False)
        res, b = self._buckets()
        self.assertEqual(b.get("B5_MANUAL_AMBIGUA"), 2, b)
        self.assertIsNone(b.get("B1_REPARABLE_ARS"))     # NO se repara a ciegas
        self.assertEqual(res["impacto_blue"]["pnl_actual_usd"], 0.0)

    # ── B3: cross-currency — el TC se cancela en el COSTO, no en los proceeds ──
    def test_b3_lote_usd_venta_ars_repara_solo_los_proceeds(self):
        self._op("2021-06-15", "AAPL", engine_sell(
            invested=1_000, buy_price=10, qty=100, exit_price=14.5 * TC_BLUE,
            lot_ccy="USD", sell_ccy="ARS"))
        res, b = self._buckets()
        self.assertEqual(b.get("B3_LOTE_USD_VENTA_ARS"), 1, b)
        op = res["impacto_blue"]["ops_mas_distorsionadas"][0]
        # El costo (1000 USD) ya está bien; los proceeds sí se re-dividen.
        # (450 + 1000) * 1450/180 - 1000 = 10679,17
        self.assertAlmostEqual(op["pnl_actual_usd"], 450.0, delta=1.0)
        self.assertAlmostEqual(op["pnl_corregido_usd"], 10679.17, delta=25.0)

    # ── B4: EL falso positivo que refutó al estimador basado en entry_price ──
    def test_b4_mep_inverso_2021_no_es_reparable(self):
        self._op("2021-06-15", "KO", engine_sell(
            invested=100_000, buy_price=1_000, qty=100, exit_price=8,
            lot_ccy="ARS", sell_ccy="USD", entry_blue=BLUE_2021),
            entry_date="2021-01-15")
        _, b = self._buckets()
        self.assertEqual(b.get("B4_MEP_INVERSO_OK"), 1, b)
        self.assertIsNone(b.get("B1_REPARABLE_ARS"))

    def test_b4_mep_inverso_2025_caia_arriba_del_reparable(self):
        """Con el ratio sobre entry_price esta fila daba 1450,59 y la reparable 1415,43:
        el falso positivo quedaba ARRIBA del verdadero. Con T_rec da 1,0000."""
        self._op("2026-01-10", "MSFT", engine_sell(
            invested=145_000, buy_price=1_450, qty=100, exit_price=1.2,
            lot_ccy="ARS", sell_ccy="USD", entry_blue=1450.0),
            entry_date="2025-11-13")
        _, b = self._buckets()
        self.assertEqual(b.get("B4_MEP_INVERSO_OK"), 1, b)
        self.assertIsNone(b.get("B1_REPARABLE_ARS"))

    # ── B7: el bono per-100 daba exactamente 100 con el estimador viejo ──
    def test_b7_bono_per_100_no_es_un_tc(self):
        # GD30 del fixture de Balanz: cantidad 1000, precio 66,04, monto 660,4.
        self._op("2026-01-10", "GD30", engine_sell(
            invested=660.4, buy_price=66.04, qty=1000, exit_price=70,
            lot_ccy="USD", sell_ccy="USD"))
        _, b = self._buckets()
        self.assertEqual(b.get("B7_ESCALA_PER_100"), 1, b)

    # ── L0: lo que hay que excluir ANTES de dividir ───────────────────────
    def test_l0_transfer_out_y_sweep_redondeado_a_cero(self):
        self._op("2026-01-10", "BTC", engine_sell(
            invested=1_000, buy_price=10, qty=100, exit_price=0,
            lot_ccy="USD", sell_ccy="USD", transfer_out=True))
        # Sweep de FCI en pesos: 6 ARS de ganancia → pnl_usd redondea a 0,00 con
        # pnl_pct sanísimo (0,03). La guarda de la v1 (pnl_pct != 0) NO lo agarraba.
        sweep = engine_sell(invested=20_000, buy_price=1, qty=20_000, exit_price=1.0003,
                            lot_ccy="ARS", sell_ccy="ARS")
        self.assertEqual(sweep["pnl_usd"], 0.0)
        self.assertNotEqual(sweep["pnl_pct"], 0.0)
        self._op("2026-01-10", "COCOSPPA", sweep)
        _, b = self._buckets()
        self.assertEqual(b.get("L0_DEGENERADA"), 2, b)
        self.assertIsNone(b.get("B1_REPARABLE_ARS"))

    # ── B6: "T_rec ≈ TC" prueba que el MOTOR trató el lote como pesos ─────
    def test_b6_anomala_no_se_repara(self):
        self._op("2021-06-15", "AL30", engine_sell(
            invested=1_000, buy_price=10, qty=1, exit_price=100_000,
            lot_ccy="ARS", sell_ccy="ARS"))
        res, b = self._buckets()
        self.assertEqual(b.get("B6_ANOMALA_ESCALA"), 1, b)
        self.assertEqual(res["impacto_blue"]["pnl_actual_usd"], 0.0)

    # ── Invariantes del informe ──────────────────────────────────────────
    def test_no_escribe_nada(self):
        antes = engine_sell(invested=100_000, buy_price=1_000, qty=100, exit_price=1_200,
                            lot_ccy="ARS", sell_ccy="ARS")
        oid = self._op("2021-06-15", "GGAL", antes)
        main.admin_diagnose_sell_fx(uid=self.uid)
        r = self.conn.execute(
            "SELECT pnl_usd, pnl_pct, currency, fx_to_usd FROM operations WHERE id=?",
            (oid,)).fetchone()
        self.assertEqual(r["pnl_usd"], antes["pnl_usd"])
        self.assertEqual(r["pnl_pct"], antes["pnl_pct"])
        self.assertIsNone(r["currency"])       # sigue NULL: el endpoint no estampa
        self.assertIsNone(r["fx_to_usd"])

    def test_los_dos_rieles_se_reportan_por_separado(self):
        self._op("2021-06-15", "GGAL", engine_sell(
            invested=100_000, buy_price=1_000, qty=100, exit_price=1_200,
            lot_ccy="ARS", sell_ccy="ARS"))
        res = main.admin_diagnose_sell_fx(uid=self.uid)
        # mep = blue*1,05 en el fixture → el corregido al MEP es ~5% más chico.
        self.assertLess(res["impacto_mep"]["pnl_corregido_usd"],
                        res["impacto_blue"]["pnl_corregido_usd"])
        self.assertAlmostEqual(
            res["impacto_blue"]["pnl_corregido_usd"] / res["impacto_mep"]["pnl_corregido_usd"],
            1.05, delta=0.01)

    def test_ninguna_fila_usa_currency_ni_fx_to_usd(self):
        """Regresión de la v1: con las columnas NULL (como en prod) tiene que clasificar igual."""
        self._op("2021-06-15", "GGAL", engine_sell(
            invested=100_000, buy_price=1_000, qty=100, exit_price=1_200,
            lot_ccy="ARS", sell_ccy="ARS"))
        _, sin_estampar = self._buckets()
        self.conn.execute("UPDATE operations SET currency='ARS', fx_to_usd=?", (TC_BLUE,))
        self.conn.commit()
        _, con_estampa = self._buckets()
        self.assertEqual(sin_estampar, con_estampa)

    def test_clusters_detectan_el_stamp_rancio(self):
        """Un mismo TC en ventas separadas por años = el dólar del día del IMPORT."""
        for fecha in ("2021-01-15", "2021-06-15", "2026-01-10"):
            self._op(fecha, "GGAL", engine_sell(
                invested=100_000, buy_price=1_000, qty=100, exit_price=1_200,
                lot_ccy="ARS", sell_ccy="ARS"))
        res = main.admin_diagnose_sell_fx(uid=self.uid)
        cl = res["clusters_tc"][0]["clusters"][0]
        self.assertEqual(cl["ventas"], 3)
        self.assertAlmostEqual(cl["tc"], TC_BLUE, delta=1.0)
        self.assertGreater(cl["dias_de_span"], 60)     # la prueba directa


if __name__ == "__main__":
    unittest.main()
