"""Séptima ronda: corrección de DIRECCIÓN.

La intención de producto era: mostrar la curva SIEMPRE y declarar qué parte es
estimada. La implementación de la ronda 6 hizo lo contrario — no eliminó el umbral
de 0,70, lo endureció a 0,995 — y con eso el importado argentino (55% de
cobertura) y hasta el usuario del demo (82%) seguían sin ver nada en el modo que
la app abre por defecto.
"""
import datetime as _d
import json
import os
import tempfile
import unittest

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import main
import twr
from reporting import builder


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
            (f"r7-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2024-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def recon(self, d, v, cov, al_costo=()):
        hold = json.dumps(
            [{"asset": "AAPL", "value_usd": v, "al_costo": False}]
            + [{"asset": a, "value_usd": 1.0, "al_costo": True} for a in al_costo])
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, mtm_coverage, holdings_json) "
            "VALUES (?,?,?,?,0,'mtm_backfill',?,?)",
            (self.uid, d, float(v), float(v), cov, hold))
        self.conn.commit()

    def cron(self, d, v):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,0,'cron',1200,'[]')", (self.uid, d, float(v), float(v)))
        self.conn.commit()


class LaCoberturaNoEsUnUmbralTest(_Base):
    """EL CRITERIO PRINCIPAL. El umbral no había que moverlo: había que sacarlo y
    reemplazarlo por un número visible."""

    TABLA = (0.70, 0.8214, 0.88, 0.94, 0.99)

    def test_el_modo_por_defecto_muestra_la_curva_en_TODAS(self):
        for cov in self.TABLA:
            with self.subTest(cobertura=cov):
                self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
                self.recon("2026-01-31", 1000.0, cov, al_costo=("FCI Balanz",))
                self.recon("2026-02-28", 1100.0, cov, al_costo=("FCI Balanz",))
                c = twr.curva_indexada(self.conn, self.uid)      # default = certero
                self.assertIsNotNone(c["twr"], f"cobertura {cov} quedó SIN CURVA")
                self.assertAlmostEqual(c["twr"], 0.10, places=6)

    def test_y_declara_la_cobertura_con_nombres(self):
        self.recon("2026-01-31", 1000.0, 0.94, al_costo=("AL30", "FCI Balanz"))
        self.recon("2026-02-28", 1100.0, 0.94, al_costo=("AL30", "FCI Balanz"))
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["cobertura_reconstruccion"], 0.94, places=4)
        self.assertEqual(c["instrumentos_al_costo"], ["AL30", "FCI Balanz"])

    def test_la_cartera_mixta_argentina_al_55_ve_su_curva(self):
        self.recon("2026-01-31", 1000.0, 0.55, al_costo=("AL30", "FCI Balanz"))
        self.recon("2026-02-28", 1100.0, 0.55, al_costo=("AL30", "FCI Balanz"))
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["twr"], 0.10, places=6)

    def test_el_usuario_del_demo_al_82_tambien(self):
        self.recon("2026-01-31", 1000.0, 0.8214)
        self.recon("2026-02-28", 1100.0, 0.8214)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["twr"], 0.10, places=6)

    def test_la_UNICA_frontera_es_que_algo_se_haya_valuado(self):
        """Cobertura 0 = ni un solo precio consultado = la cadena contable con
        etiqueta de mercado. No es un umbral de calidad."""
        self.recon("2026-01-31", 1000.0, 0.0)
        self.recon("2026-02-28", 1100.0, 0.0)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertIsNone(c["twr"])
        est = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        self.assertIsNotNone(est["twr"])


class ElSilencioNoDesapareceTest(_Base):
    """Las dos ramas del corte exigían `ultimo_apto is not None`, así que TODO
    hueco anterior al primer punto apto de un tramo quedaba sin medir."""

    def _foto_suelta_en_enero_y_cron_desde_agosto(self):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue) "
            "VALUES (?,'2026-01-05',100000,100000,0,'browser',1200)", (self.uid,))
        for i in range(31):
            d = _d.date(2026, 8, 1) + _d.timedelta(days=i)
            self.cron(d.isoformat(), 100000.0 * (1 + 0.00254 * i))
        for m in range(1, 13):
            self.conn.execute(
                "INSERT INTO monthly_entries (user_id, broker, year, month, "
                "capital_inicio, capital_final, deposits, withdrawals, pnl_realized, "
                "pnl_unrealized) VALUES (?,'global',2026,?,100000,100000,0,0,0,0)",
                (self.uid, m))
        self.conn.commit()

    def test_cinco_meses_de_silencio_parten_la_serie(self):
        self._foto_suelta_en_enero_y_cron_desde_agosto()
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(len(c["tramos"]), 2)
        self.assertTrue(c["serie_partida"])
        self.assertIsNone(c["twr"])

    def test_y_el_anio_no_publica_un_porcentaje_de_un_mes(self):
        self._foto_suelta_en_enero_y_cron_desde_agosto()
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "year", "2026-01-01", "2026-12-31", "global", None)
        self.assertIn(m.delta_pct, (None, 0.0))

    def test_ventana_desde_es_el_primer_punto_QUE_MIDE(self):
        """`tramos_info["desde"]` tomaba `tramo[0]`, que puede ser un punto no-apto:
        `ventana_desde` mentía, y ése es el dato con el que el builder decide si el
        % anual cubre el período."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue) "
            "VALUES (?,'2026-03-01',100000,100000,0,'browser',1200)", (self.uid,))
        for i in range(10):
            self.cron((_d.date(2026, 3, 10) + _d.timedelta(days=i)).isoformat(),
                      100000.0 + i * 100)
        self.conn.commit()
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(c["ventana_desde"], "2026-03-10")   # NO 2026-03-01
        primero = c["tramos_detalle"][0]
        self.assertEqual(primero["desde"], "2026-03-10")


class ElDefaultSigueSiendoSeguroTest(_Base):
    def test_la_cadena_contable_no_entra_en_certero(self):
        """La garantía de las siete rondas: el −45% del caso 452 salía de encadenar
        la foto FABRICADA por el import."""
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,'2026-07-31',139570.56,139570.56,0,'import')",
            (self.uid,))
        self.cron("2026-08-24", 73604.02)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(len(c["puntos"]), 1)
        self.assertIsNone(c["twr"])
        self.assertIsNone(c["drawdown_maximo"])


if __name__ == "__main__":
    unittest.main()
