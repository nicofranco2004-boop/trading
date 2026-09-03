"""FASE 6 — los demás consumidores dejan de leer los snapshots crudos.

Todos leían `SELECT ... FROM snapshots` sin filtrar por `source`, así que mezclaban
mediciones reales del cron con las fotos que el import FABRICA copiando la cadena
contable (persister.py:1289-1292). Esas no bajan con el mercado: fijan picos que
nunca existieron y meten denominadores que no son de mercado.
"""
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main


class _Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("snapshots", "positions", "operations", "monthly_entries", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("cons@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,?,?,0,1,100,?)",
            (self.uid, "IBKR", "AAPL", "2024-01-01"))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def snap(self, d, v, source="cron", nd=0.0):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) VALUES (?,?,?,?,?,?,?,?)",
            (self.uid, d, v, v, nd, source,
             1200.0 if source == "cron" else None, "[]" if source == "cron" else None))
        self.conn.commit()


class CagrObjetivosTest(_Base):
    def test_la_foto_fabricada_no_entra_en_el_cagr(self):
        # Una foto inventada MUY alta al principio: si entrara, el CAGR se hunde.
        self.snap("2025-01-31", 999999.0, source="import")
        for d, v in (("2025-02-28", 1000.0), ("2025-03-31", 1100.0),
                     ("2025-04-30", 1150.0), ("2025-05-31", 1200.0),
                     ("2025-06-30", 1250.0), ("2025-07-31", 1300.0)):
            self.snap(d, v)
        r = main._historical_cagr_global(self.conn, self.uid)
        # La propiedad que este test protege es que la foto FABRICADA no entre: si
        # entrara, el arranque sería 999.999 y el retorno se hundiría. Sigue valiendo,
        # y ahora se verifica sobre el acumulado y la ventana, porque con 5 meses el
        # motor no anualiza (piso de medio año).
        self.assertIsNone(r["cagr"])
        self.assertGreater(r["total_return_pct"], 0)      # subió: 1000 → 1300
        self.assertEqual(r["desde"], "2025-02-28")        # arranca en la MEDICIÓN
        self.assertEqual(r["months"], 5)

    def test_dos_mediciones_muy_separadas_no_explotan_el_cagr(self):
        self.snap("2025-01-31", 100000.0)
        self.snap("2026-08-31", 120000.0)         # 19 meses, +20%
        r = main._historical_cagr_global(self.conn, self.uid)
        # ⚠️ DECISIÓN, Y ES UNA PÉRDIDA CONSCIENTE. Antes esto publicaba +12,2 %
        # anual. El motor canónico corta un tramo con más de 45 días de silencio y
        # no publica de punta a punta: dos mediciones separadas 19 meses no se
        # encadenan, y los flujos del medio no se pueden ubicar en el tiempo (el
        # Modified Dietz sobre 19 meses es una aproximación gruesa). Lo importante
        # es que sigue sin publicar el 791,61 % del motor pre-ronda-2, y que ahora
        # dice lo MISMO que la pantalla de Métricas — que es lo que se pidió.
        self.assertIsNone(r["cagr"])
        self.assertIsNone(r["total_return_pct"])
        self.assertTrue(r["reason"])
        # el span de la historia medida NO se pierde: son 19 meses, no "0"
        self.assertEqual(r["historia_meses"], 19)

    def test_sin_clamp_asimetrico_un_mes_de_mas_80_no_se_trunca(self):
        self.snap("2025-01-31", 100.0)
        self.snap("2025-02-28", 180.0)
        r = main._historical_cagr_global(self.conn, self.uid)
        self.assertAlmostEqual(r["total_return"], 0.80, places=4)


class AiBuildersTest(_Base):
    def test_drawdown_del_packet_no_usa_el_pico_inventado(self):
        from ai.builders import insights_drawdown
        import datetime as _dt
        hoy = _dt.date.today()
        # El pico falso es una foto del import; lo medido apenas se movió.
        self.snap((hoy - _dt.timedelta(days=60)).isoformat(), 500000.0, source="import")
        self.snap((hoy - _dt.timedelta(days=30)).isoformat(), 1000.0)
        self.snap((hoy - _dt.timedelta(days=1)).isoformat(), 980.0)
        p = insights_drawdown.build(self.conn, self.uid, window_days=365)
        self.assertGreater(p["max_pct"], -10.0)   # −2%, no −99,8%

    def test_dashboard_evolution_explica_por_que_no_hay_curva(self):
        from ai.builders import dashboard_evolution
        self.snap("2025-06-30", 1000.0, source="import")
        p = dashboard_evolution.build(self.conn, self.uid)
        self.assertTrue(p["insufficient_data"])
        import twr
        self.assertEqual(p["reason"], twr.MOTIVO_TEXTO["importado_sin_mediciones"])


class InformeDelAsesorTest(_Base):
    def test_la_base_del_periodo_no_puede_ser_una_foto_fabricada(self):
        """Es el informe que el asesor le MANDA al cliente: donde un número
        inventado hace más daño."""
        self.snap("2026-06-30", 500000.0, source="import")   # base falsa, altísima
        self.snap("2026-07-15", 1000.0)
        self.snap("2026-07-31", 1050.0)
        pay = main._advisor_report_payload(
            self.conn, self.uid, self.uid, "Julio 2026", "2026-07-01", "2026-07-31",
            None, {"nombre": "X", "matricula": None, "logo": None}, 1200.0, 1300.0)
        # La foto de 500.000 NO puede ser la base: con ella el informe firmaba
        # un −99,8% que el cliente no vivió. La base cae en la primera MEDICIÓN.
        self.assertNotEqual(pay.get("base_date"), "2026-06-30")
        self.assertEqual(pay.get("base_date"), "2026-07-15")
        self.assertAlmostEqual(pay["ret_pct"], 5.0, places=2)   # 1000 → 1050

    def test_contrafactual_con_la_foto_fabricada_el_informe_firmaba_un_99_negativo(self):
        """Que el test de arriba pase por la razón correcta: la aritmética vieja,
        con la base fabricada, daba lo que el cliente nunca vivió."""
        import twr
        self.assertLess(twr.dietz(500000.0, 1050.0, 0.0), -0.99 + 1e-9)


if __name__ == "__main__":
    unittest.main()
