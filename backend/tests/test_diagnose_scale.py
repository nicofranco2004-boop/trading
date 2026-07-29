"""GET /api/admin/diagnose-scale — el error de escala en las ventas (bug per-100).

El motor toma el COSTO de `gross_amount` (columna monto = caja real, persister.py:411)
y los INGRESOS de `unit_price*quantity` (columna precio cruda, persister.py:536→609), y
nunca los reconcilia. `gross_amount` no aparece ni una vez dentro de _persist_sell_fifo.
Como el costo queda sano, un bono cotizado por 100 nominales infla el P&L ×100 entero.

El error es EXACTO y no hay que modelarlo:
    error_nativo = exit_price*qty − gross_amount*(qty/tx_qty)
    pnl_sano     = pnl_usd − error_nativo/T_rec

Los tests usan los números del fixture real de Balanz (GD30: cantidad 1000, precio 66,04,
monto 660,4 ⇒ k=100) y verifican que el P&L sano cae en 39,60 USD, que es exactamente
`monto_venta − monto_compra`.
"""
import os, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False); TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main


class DiagnoseScaleTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("operations", "positions", "brokers", "users", "monthly_entries",
                  "advisor_reports", "import_op_links", "import_normalized_tx",
                  "import_raw_rows", "import_batches"):
            try: self.conn.execute(f"DELETE FROM {t}")
            except Exception: pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email,password_hash,approved,tier) VALUES (?,?,1,?)",
            ("scale@test", "x", "pro")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,?)",
                          (self.uid, "Balanz", "ARS"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _batch(self, bid, parser, confirmed_at="2026-07-20"):
        self.conn.execute(
            "INSERT INTO import_batches (id,user_id,broker,parser_format,file_hash,status,confirmed_at) "
            "VALUES (?,?,?,?,?,?,?)", (bid, self.uid, "Balanz", parser, bid, "confirmed", confirmed_at))
        return bid

    def _tx(self, bid, *, op, asset, qty, price, monto, ccy="USD", atype="BOND"):
        rr = self.conn.execute(
            "INSERT INTO import_raw_rows (batch_id,row_index,raw_json,status) VALUES (?,?,?,?)",
            (bid, 0, "{}", "valid")).lastrowid
        self.conn.execute(
            "INSERT INTO import_normalized_tx (batch_id,raw_row_id,date,broker,operation_type,"
            "asset_symbol,asset_type,quantity,unit_price,gross_amount,currency) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (bid, rr, "2026-07-01", "Balanz", op, asset, atype, qty, price, monto, ccy))
        self.conn.commit()      # el endpoint abre su propia conexión: sin esto no lo ve
        return rr

    def _venta(self, bid, rr, *, asset, qty, exit_price, pnl_usd, pnl_pct, com=0.0, link=True):
        oid = self.conn.execute(
            "INSERT INTO operations (user_id,date,broker,asset,op_type,entry_price,exit_price,"
            "quantity,pnl_usd,pnl_pct,commissions) VALUES (?,?,?,?,'Venta',?,?,?,?,?,?)",
            (self.uid, "2026-07-01", "Balanz", asset, None, exit_price, qty,
             pnl_usd, pnl_pct, com)).lastrowid
        if link:
            self.conn.execute(
                "INSERT INTO import_op_links (batch_id,raw_row_id,operation_id) VALUES (?,?,?)",
                (bid, rr, oid))
        self.conn.commit()
        return oid

    # ── El caso canónico: bono per-100 vendido en dólares ────────────────
    def test_bono_per_100_el_pnl_sano_es_la_resta_de_los_montos(self):
        bid = self._batch("b-gd30", "balanz")
        self._tx(bid, op="BUY", asset="GD30", qty=1000, price=66.04, monto=660.4)
        rr = self._tx(bid, op="SELL", asset="GD30", qty=1000, price=70, monto=700)
        # Lo que el motor calculó: proceeds = 70*1000 = 70.000 contra un costo de 660,4
        self._venta(bid, rr, asset="GD30", qty=1000, exit_price=70,
                    pnl_usd=69339.60, pnl_pct=10499.6365)

        res = main.admin_diagnose_scale(uid=self.uid)
        v = res["ventas"]
        self.assertEqual(v["afectadas_por_escala"], 1)
        self.assertEqual(v["usuarios_afectados"], 1)
        # El P&L real es 700 − 660,40 = 39,60 USD. Ni un centavo más.
        self.assertAlmostEqual(v["pnl_sano_usd"], 39.60, delta=0.05)
        self.assertAlmostEqual(v["error_usd" if "error_usd" in v else "error_total_usd"],
                               69300.0, delta=1.0)
        peor = res["ops_peores"][0]
        self.assertEqual(peor["activo"], "GD30")
        self.assertAlmostEqual(peor["k"], 100.0, delta=0.01)
        self.assertAlmostEqual(peor["T_rec"], 1.0, delta=0.001)   # venta USD: sin FX

    def test_bono_per_100_en_pesos_el_tc_no_contamina_la_correccion(self):
        """Con FX de por medio la fórmula sigue exacta: el error se divide por el mismo T."""
        bid = self._batch("b-ars", "balanz_movimientos")
        self._tx(bid, op="BUY", asset="AL30", qty=1000, price=66040, monto=660400, ccy="ARS")
        rr = self._tx(bid, op="SELL", asset="AL30", qty=1000, price=70000, monto=700000, ccy="ARS")
        # pnl_ars = 70.000*1000 − 660.400 = 69.339.600 ; /1450 = 47.820,41
        self._venta(bid, rr, asset="AL30", qty=1000, exit_price=70000,
                    pnl_usd=47820.41, pnl_pct=10499.6365)

        res = main.admin_diagnose_scale(uid=self.uid)
        peor = res["ops_peores"][0]
        self.assertAlmostEqual(peor["T_rec"], 1450.0, delta=2.0)   # recupera el TC
        # (700.000 − 660.400)/1450 = 27,31 USD
        self.assertAlmostEqual(res["ventas"]["pnl_sano_usd"], 27.31, delta=0.15)

    def test_venta_sana_no_aparece(self):
        bid = self._batch("b-ok", "cocos")
        self._tx(bid, op="BUY", asset="AAPL", qty=10, price=150, monto=1500, atype="STOCK")
        rr = self._tx(bid, op="SELL", asset="AAPL", qty=10, price=180, monto=1800, atype="STOCK")
        self._venta(bid, rr, asset="AAPL", qty=10, exit_price=180, pnl_usd=300.0, pnl_pct=20.0)
        res = main.admin_diagnose_scale(uid=self.uid)
        self.assertEqual(res["ventas"]["afectadas_por_escala"], 0)
        self.assertEqual(res["ventas"]["error_total_usd"], 0.0)

    # ── El triángulo en la fuente: ¿gross_amount es bruto o neto? ─────────
    def test_triangulo_separa_parsers_vulnerables_de_inmunes(self):
        b1 = self._batch("b-v", "balanz")
        self._tx(b1, op="BUY", asset="GD30", qty=1000, price=66.04, monto=660.4)
        self._tx(b1, op="SELL", asset="GD30", qty=1000, price=70, monto=700)
        b2 = self._batch("b-i", "cocos")
        self._tx(b2, op="BUY", asset="AAPL", qty=10, price=150, monto=1500, atype="STOCK")

        res = main.admin_diagnose_scale(uid=self.uid)
        t = res["triangulo_en_la_fuente"]
        self.assertEqual(t["bandas"]["k~100 (per-100)"], 2)
        self.assertEqual(t["bandas"]["k~1 (sano)"], 1)
        self.assertEqual(t["por_parser"]["balanz"]["per_100"], 2)
        self.assertEqual(t["por_parser"]["cocos"]["sano"], 1)
        # Con gross_amount BRUTO el cluster cae exactamente en 100 → el fix simétrico
        # (que la venta use gross_amount, como ya hace la compra) es seguro.
        self.assertAlmostEqual(t["k100_percentiles"]["p50"], 100.0, delta=0.01)

    def test_triangulo_detecta_gross_amount_neto_de_comisiones(self):
        """Si el monto viniera NETO, el cluster se corre y el fix simétrico NO sirve."""
        b = self._batch("b-neto", "ppi")
        for i in range(3):
            self._tx(b, op="SELL", asset=f"AL3{i}", qty=1000, price=70, monto=700 * 1.003)
        res = main.admin_diagnose_scale(uid=self.uid)
        p50 = res["triangulo_en_la_fuente"]["k100_percentiles"]["p50"]
        self.assertLess(p50, 99.8)          # corrido: el monto no es el bruto
        self.assertGreater(p50, 99.5)

    # ── Régimen: dónde el UPDATE a mano es durable ───────────────────────
    def test_regimen_congelada_cuando_hay_una_venta_sin_link(self):
        bid = self._batch("b-mix", "ieb")
        self._tx(bid, op="BUY", asset="PVR1Q", qty=1000, price=66.04, monto=660.4)
        rr = self._tx(bid, op="SELL", asset="PVR1Q", qty=1000, price=70, monto=700)
        self._venta(bid, rr, asset="PVR1Q", qty=1000, exit_price=70,
                    pnl_usd=69339.60, pnl_pct=10499.6365)
        res = main.admin_diagnose_scale(uid=self.uid)
        self.assertEqual(res["cuentas"][0]["regimen"], "RECOMPUTE_REPRODUCE")

        # El usuario vende a mano el mismo activo → el par queda congelado para siempre
        # (_is_safe_to_rebuild, rebuild.py:512) → ahí el UPDATE directo SÍ es durable.
        self._venta(bid, rr, asset="PVR1Q", qty=1, exit_price=70,
                    pnl_usd=1.0, pnl_pct=1.0, link=False)
        res2 = main.admin_diagnose_scale(uid=self.uid)
        self.assertEqual(res2["cuentas"][0]["regimen"], "CONGELADA_MANUAL")

    # ── La canilla ───────────────────────────────────────────────────────
    def test_canilla_abierta_si_el_batch_es_reciente(self):
        from datetime import datetime, timedelta
        reciente = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d")
        bid = self._batch("b-hoy", "ieb", confirmed_at=reciente)
        rr = self._tx(bid, op="SELL", asset="AL29", qty=1000, price=70, monto=700)
        self._venta(bid, rr, asset="AL29", qty=1000, exit_price=70,
                    pnl_usd=69339.60, pnl_pct=10499.6365)
        res = main.admin_diagnose_scale(uid=self.uid)
        self.assertTrue(res["canilla"]["abierta"])
        self.assertEqual(res["canilla"]["ventas_afectadas_de_batches_recientes"], 1)

    # ── Contexto de decisión ─────────────────────────────────────────────
    def test_reporta_plan_capital_e_informes_congelados(self):
        bid = self._batch("b-ctx", "ieb")
        rr = self._tx(bid, op="SELL", asset="AL29", qty=1000, price=70, monto=700)
        self._venta(bid, rr, asset="AL29", qty=1000, exit_price=70,
                    pnl_usd=69339.60, pnl_pct=10499.6365)
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id,broker,year,month,capital_inicio,deposits,"
            "withdrawals,pnl_realized,pnl_unrealized,capital_final) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.uid, "global", 2026, 7, 0, 1000, 0, 69339.60, 0, 70339.60))
        self.conn.execute(
            "INSERT INTO advisor_reports (advisor_uid,client_uid,period_start,period_end,token,payload) "
            "VALUES (?,?,?,?,?,?)", (999, self.uid, "2026-06-01", "2026-06-30", "tok-1", "{}"))
        self.conn.commit()

        c = main.admin_diagnose_scale(uid=self.uid)["cuentas"][0]
        self.assertEqual(c["tier"], "pro")
        self.assertEqual(c["informes_congelados"], 1)      # superficie irreversible
        self.assertAlmostEqual(c["pnl_sano_usd"], 39.60, delta=0.05)
        self.assertGreater(c["pct_del_capital_que_es_falso"], 90)   # casi todo es falso

    def test_no_escribe_nada(self):
        bid = self._batch("b-ro", "ieb")
        rr = self._tx(bid, op="SELL", asset="AL29", qty=1000, price=70, monto=700)
        oid = self._venta(bid, rr, asset="AL29", qty=1000, exit_price=70,
                          pnl_usd=69339.60, pnl_pct=10499.6365)
        antes = dict(self.conn.execute(
            "SELECT pnl_usd, pnl_pct, exit_price FROM operations WHERE id=?", (oid,)).fetchone())
        main.admin_diagnose_scale(uid=self.uid)
        despues = dict(self.conn.execute(
            "SELECT pnl_usd, pnl_pct, exit_price FROM operations WHERE id=?", (oid,)).fetchone())
        self.assertEqual(antes, despues)


if __name__ == "__main__":
    unittest.main()
