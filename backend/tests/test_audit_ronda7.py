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



def _todos(s):
    """Los puntos ACEPTADOS —medibles y no medibles— juntos y en orden.

    ⚠️ VIVE EN LOS TESTS A PROPÓSITO. `serie_medible` dejó de devolver una lista
    mezclada justamente para que producción no pueda recorrerla sin decidir; un
    test sí puede mirar todo, pero tiene que nombrarlo.
    """
    return sorted(list(s["medibles"]) + list(s["no_medibles"]), key=lambda p: p["date"])

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
        """⚠️ SON DOS PREGUNTAS. La curva se DIBUJA a cualquier cobertura —eso es
        lo que la ronda 7 vino a ganar— pero el pico y el número publicado sólo
        salen de puntos que superan el piso de medición: por debajo, el
        `total_value` de la foto reconstruida ES el costo."""
        for cov in self.TABLA:
            with self.subTest(cobertura=cov):
                self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
                self.recon("2026-01-31", 1000.0, cov, al_costo=("FCI Balanz",))
                self.recon("2026-02-28", 1100.0, cov, al_costo=("FCI Balanz",))
                c = twr.curva_indexada(self.conn, self.uid)      # default = certero
                idx = [p["index"] for p in c["curva"]]
                self.assertEqual(len(idx), 2, f"cobertura {cov} quedó SIN CURVA")
                self.assertGreater(max(idx), min(idx),
                                   f"cobertura {cov} dibuja una recta")
                if cov >= twr.COBERTURA_MEDICION:
                    self.assertAlmostEqual(c["twr"], 0.10, places=6)
                else:
                    self.assertIsNone(c["twr"])
                    self.assertTrue(all(p["estimado"] for p in c["curva"]))

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
        idx = [p["index"] for p in c["curva"]]
        self.assertGreater(max(idx), min(idx))       # la ve
        self.assertIsNone(c["drawdown_maximo"])      # pero no fija picos

    def test_el_usuario_del_demo_al_82_tambien(self):
        self.recon("2026-01-31", 1000.0, 0.8214)
        self.recon("2026-02-28", 1100.0, 0.8214)
        c = twr.curva_indexada(self.conn, self.uid)
        idx = [p["index"] for p in c["curva"]]
        self.assertGreater(max(idx), min(idx))
        self.assertAlmostEqual(idx[-1], 1.10, places=6)   # la forma es la real


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
        self.assertEqual(len(_todos(c)), 1)
        self.assertIsNone(c["twr"])
        self.assertIsNone(c["drawdown_maximo"])


if __name__ == "__main__":
    unittest.main()


class DosPreguntasNoUnaTest(_Base):
    """RONDA 8 · el umbral se saca separando dos preguntas, no haciendo todo apto.
    El mecanismo ya existía en el módulo: es el que usa INTRADIA."""

    def test_la_cartera_al_95_por_ciento_de_costo_no_fija_un_pico(self):
        """Con cobertura baja el `total_value` de la foto reconstruida ES EL COSTO,
        así que la fila es contabilidad con etiqueta de mercado. Dejarla medir
        devolvía el −47,26% del caso 452, con el pico en una fecha que el sistema
        nunca midió — la queja literal del usuario que originó todo esto."""
        self.recon("2026-04-30", 139570.56, 0.05)
        self.cron("2026-05-14", 73604.02)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertIsNone(c["drawdown_maximo"])
        self.assertIsNone(c["drawdown_maximo_pico"])
        self.assertIsNone(c["twr"])

    def test_la_frontera_ya_no_es_un_punto_basico(self):
        """La cobertura se persiste redondeada a 4 decimales: 0,0 no daba curva y
        0,0001 daba curva COMPLETA con pico y denominador."""
        for cov in (0.0, 0.0001, 0.05):
            with self.subTest(cobertura=cov):
                self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
                self.recon("2026-04-30", 139570.56, cov)
                self.cron("2026-05-14", 73604.02)
                c = twr.curva_indexada(self.conn, self.uid)
                self.assertIsNone(c["drawdown_maximo"])

    def test_en_ESTIMADO_la_cadena_contable_tampoco_es_pico(self):
        """Una cartera PLANA en 100.000 todo junio + UNA fila del import publicaba
        −44,44% desde un máximo que puso el sistema. Y quedaba la inversión
        absurda: la foto INTRADIA —posiciones × precio— no medía, y la fabricada
        al costo sí."""
        for i in range(29):
            d = _d.date(2026, 6, 1) + _d.timedelta(days=i)
            if d.day == 15:
                continue
            self.cron(d.isoformat(), 100000.0)
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,'2026-06-15',180000,180000,0,'import')",
            (self.uid,))
        self.conn.commit()
        for modo in (twr.MODO_CERTERO, twr.MODO_ESTIMADO):
            with self.subTest(modo=modo):
                c = twr.curva_indexada(self.conn, self.uid, modo=modo)
                # La afirmación de fondo NO cambió: la fila de 180.000 que fabricó
                # el import no fija un pico en ningún modo. Lo que cambió es CÓMO se
                # dice, y es más fuerte que antes:
                #   · CERTERO  → 0,0. Hay camino de precios (30 cierres del cron) y
                #     ese camino dice que la cartera estuvo plana. Es una medición.
                #   · ESTIMADO → None. La Fase 2 le sacó el drawdown al modo
                #     contable entero, porque un drawdown necesita el CAMINO y la
                #     cadena contable no es un camino de precios. Un 0,0 acá
                #     afirmaría "no hubo caída"; None dice "no lo sabemos", que es
                #     lo cierto.
                if modo == twr.MODO_ESTIMADO:
                    self.assertIsNone(c["drawdown_maximo"])
                    self.assertIsNone(c["drawdown_actual"])
                else:
                    self.assertAlmostEqual(c["drawdown_maximo"], 0.0, places=6)
                self.assertIsNone(c["drawdown_maximo_pico"])

    def test_la_banda_contable_NO_se_vacia_cuando_entran_a_la_linea(self):
        """Es la separación visual que existe para que nadie saque un pico de ahí:
        perderla justo cuando sus filas se meten en la serie es lo peor de los dos
        mundos."""
        self.cron("2026-06-01", 100000.0)
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,'2026-06-15',180000,180000,0,'import')",
            (self.uid,))
        self.conn.commit()
        est = twr.curva_indexada(self.conn, self.uid, modo=twr.MODO_ESTIMADO)
        self.assertEqual(len(est["contable"]), 1)

    def test_ningun_punto_no_apto_sale_con_estimado_False(self):
        self.recon("2026-04-30", 139570.56, 0.05)
        self.cron("2026-05-14", 73604.02)
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source) VALUES (?,'2026-05-20',180000,180000,0,'import')",
            (self.uid,))
        self.conn.commit()
        for modo in (twr.MODO_CERTERO, twr.MODO_ESTIMADO):
            c = twr.curva_indexada(self.conn, self.uid, modo=modo)
            malos = [p for p in c["curva"] if not p["apto"] and not p["estimado"]]
            self.assertEqual(malos, [], f"{modo}: {malos}")

    def test_la_curva_se_VE_aunque_ningun_punto_mida(self):
        """Lo que la ronda 7 ganó y no se puede perder: sin esto, el que tiene la
        cartera mayormente al costo veía una recta en 0,0%, que se lee
        tranquilizador."""
        for d, v in (("2026-01-31", 1000.0), ("2026-02-28", 1200.0), ("2026-03-31", 1100.0)):
            self.recon(d, v, 0.55)
        c = twr.curva_indexada(self.conn, self.uid)
        idx = [p["index"] for p in c["curva"]]
        self.assertEqual(len(idx), 3)
        self.assertGreater(max(idx), min(idx))
        self.assertAlmostEqual(idx[1], 1.20, places=6)   # la forma REAL
        self.assertAlmostEqual(idx[2], 1.10, places=6)
        self.assertIsNone(c["twr"])                      # pero no se publica
