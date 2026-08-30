"""Tercera ronda: los bloqueantes que dejó la ronda 2.

El patrón que se repitió: la DECISIÓN de aflojar el criterio era correcta, pero
`BASE_MERCADO` respondía dos preguntas distintas —qué entra a la serie y qué puede
ser pico o denominador— y se aflojaron las dos juntas.
"""
import math
import os
import tempfile
import unittest
import datetime as _d

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
            (f"r3-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2024-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _snap(self, d, v, source, nd=0.0, hold=None, fx=1200.0):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) VALUES (?,?,?,?,?,?,?,?)",
            (self.uid, d, float(v), float(v), float(nd), source, fx, hold))
        self.conn.commit()

    def cron(self, d, v, nd=0.0):
        self._snap(d, v, "cron", nd=nd, hold="[]")

    def browser(self, d, v, nd=0.0):
        self._snap(d, v, "browser", nd=nd, hold=None)

    def me(self, y, m, ci, cf, dep=0.0, wd=0.0):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',?,?,?,?,?,?,0,0)", (self.uid, y, m, ci, cf, dep, wd))
        self.conn.commit()


class IntradiaNoEsPicoNiDenominadorTest(_Base):
    """⚠️ FIXTURE NO MONÓTONO A PROPÓSITO. Con una serie que sólo sube, un pico
    falso es estructuralmente invisible: el test pasa sin probar nada."""

    def test_una_foto_del_browser_no_fija_el_pico(self):
        for d in ("2026-01-05", "2026-01-06", "2026-01-08", "2026-01-09"):
            self.cron(d, 10000.0)
        self.browser("2026-01-07", 15000.0)          # media rueda, no confirmada
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["twr"], 0.0, places=6)
        self.assertAlmostEqual(c["drawdown_maximo"], 0.0, places=6)
        self.assertIsNone(c["drawdown_maximo_pico"])

    def test_el_drawdown_no_depende_de_cuantas_veces_se_abre_la_app(self):
        """El sesgo va en UNA SOLA dirección —los picos sólo suben—, así que cada
        foto que sobrevive empeora el drawdown para siempre y nunca lo mejora."""
        cierres = [(f"2026-02-{d:02d}", 10000.0 * (1 + 0.002 * ((d * 7) % 5 - 2)))
                   for d in range(2, 21, 2)]
        vistos = []
        for veces in (0, 1, 2, 3):
            self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
            for d, v in cierres:
                self.cron(d, v)
            for k in range(veces):                    # el cron no corrió esos días
                self.browser(f"2026-02-{5 + k * 6:02d}", 10000.0 * (1.10 + 0.05 * k))
            c = twr.curva_indexada(self.conn, self.uid)
            vistos.append((round(c["drawdown_maximo"], 6), round(c["drawdown_actual"], 6)))
        self.assertEqual(len(set(vistos)), 1, f"el drawdown cambió con el uso: {vistos}")

    def test_la_intradia_sostiene_la_linea_igual(self):
        """Se descarta como pico y denominador, NO como punto de la serie."""
        for d in ("2026-01-05", "2026-01-06"):
            self.cron(d, 10000.0)
        self.browser("2026-01-07", 15000.0)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(len(_todos(s)), 3)
        intra = [p for p in _todos(s) if p["clase"] == twr.INTRADIA]
        self.assertEqual(len(intra), 1)
        self.assertFalse(intra[0]["apto"])

    def test_la_cadena_saltea_el_punto_no_apto_por_completo(self):
        """No alcanza con negarle ser DENOMINADOR: la pata que ENTRA a la foto
        también movía el índice, y eso queda para siempre."""
        self.cron("2026-01-05", 10000.0)
        self.browser("2026-01-06", 15000.0)
        self.cron("2026-01-07", 10000.0)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["twr"], 0.0, places=6)
        pt = [p for p in c["curva"] if p["date"] == "2026-01-06"][0]
        self.assertTrue(pt["estimado"])
        self.assertIsNone(pt["ret"])


class UsuarioSanoConservaTodoTest(_Base):
    """Los DOS, no uno: la línea Y los tramos con retorno."""

    def _seiscientas_fotos(self):
        d0 = _d.date(2025, 1, 1)
        v = 100000.0
        for i in range(600):
            d = d0 + _d.timedelta(days=i)
            v *= (1.0 + 0.0006 * math.sin(i / 23.0) + 0.00035)   # NO monótono
            self._snap(d.isoformat(), v,
                       'cron' if d >= _d.date(2026, 8, 6) else None,
                       hold='[]' if d >= _d.date(2026, 7, 4) else None)

    def test_conserva_los_600_puntos_y_los_599_tramos(self):
        self._seiscientas_fotos()
        s = twr.serie_medible(self.conn, self.uid)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(len(_todos(s)), 600)
        self.assertGreaterEqual(c["tramos_medidos"], 590)
        self.assertGreater(c["twr"], 0.15)

    def test_la_cadencia_diaria_distingue_al_cron_del_browser(self):
        """Una tanda de días calendario consecutivos sin un solo hueco la escribió
        el cron: el browser escribe salteado y sólo cuando el usuario entra."""
        self._seiscientas_fotos()
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["por_clase"][twr.INTRADIA], 0)
        self.assertGreaterEqual(s["por_clase"][twr.MEDICION], 590)

    def test_una_fila_que_DICE_browser_nunca_se_asciende(self):
        """Lo que dice `source` manda: el refinamiento sólo desambigua legacy."""
        d0 = _d.date(2026, 3, 1)
        for i in range(20):
            self.browser((d0 + _d.timedelta(days=i)).isoformat(), 10000.0 + i)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertEqual(s["por_clase"][twr.MEDICION], 0)
        self.assertEqual(s["por_clase"][twr.INTRADIA], 20)


class UnSoloCriterioTest(_Base):
    """Si dos módulos deciden distinto qué fila es una medición, uno está mal."""

    def test_los_dos_lectores_clasifican_igual_una_fila_legacy(self):
        d0 = _d.date(2026, 1, 1)
        for i in range(30):                      # cadencia diaria: es el cron
            self._snap((d0 + _d.timedelta(days=i)).isoformat(), 100000.0 + i * 10,
                       None, hold=None)
        s = twr.serie_medible(self.conn, self.uid)
        self.assertGreaterEqual(s["por_clase"][twr.MEDICION], 25)
        # Y el lector de bordes tiene que ver LO MISMO.
        b = builder.fetch_snapshot_at_or_before(
            self.conn, self.uid, "2026-01-30", mtm_only=True)
        self.assertIsNotNone(b, "el lector de bordes no vio la medición que sí ve la serie")

    def test_el_periodo_cerrado_de_un_usuario_legacy_consigue_bordes(self):
        d0 = _d.date(2026, 4, 1)
        for i in range(61):                      # abril y mayo, diario
            self._snap((d0 + _d.timedelta(days=i)).isoformat(), 100000.0, None, hold=None)
        self.me(2026, 4, 100000.0, 100000.0)
        self.me(2026, 5, 100000.0, 100000.0)
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-05-01", "2026-05-31", "global", None)
        self.assertEqual(m.basis, "mercado")
        self.assertAlmostEqual(m.delta_usd, 0.0, places=2)


class ImportNoFabricaPerdidaTest(_Base):
    def test_un_import_en_el_medio_no_inventa_37_por_ciento(self):
        """`snapshots.net_deposited` es una medición hecha sobre `monthly_entries`
        EN EL MOMENTO de escribir la fila. El import la reescribe hacia atrás sin
        re-estampar las fotos viejas: restar dos estampas medía cuánto cambió la
        contabilidad entre dos momentos, no el flujo. Y un mes cerrado no se
        autocura nunca."""
        self.me(2025, 12, 0.0, 60000.0, dep=60000.0)
        self.me(2026, 6, 60000.0, 110000.0, dep=50000.0)
        self.me(2026, 7, 110000.0, 110000.0)
        self.cron("2026-06-30", 110000.0, nd=60000.0)          # estampa VIEJA
        for d in range(1, 32):
            self.cron(f"2026-07-{d:02d}", 110000.0, nd=110000.0)   # estampa NUEVA
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-07-01", "2026-07-31", "global", None)
        self.assertAlmostEqual(m.delta_usd, 0.0, places=2)
        self.assertAlmostEqual(m.delta_pct, 0.0, places=2)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["twr"], 0.0, places=4)

    def test_el_baseline_es_un_STOCK_y_no_un_aporte_del_primer_mes(self):
        """El baseline aparecía sólo de un lado de la resta y el primer tramo lo
        leía como un aporte: un año entero publicaba −62,3%."""
        for mes in range(1, 13):
            self.me(2025, mes, 100000.0, 100000.0)
        self.cron("2024-12-31", 100000.0)
        import calendar
        for mes in range(1, 13):
            self.cron(f"2025-{mes:02d}-{calendar.monthrange(2025, mes)[1]:02d}",
                      100000.0 * (1 + 0.01 * mes))
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "year", "2025-01-01", "2025-12-31", "global", None)
        self.assertGreater(m.delta_pct, 0)
        self.assertAlmostEqual(m.delta_pct, 12.0, places=1)


class PacketDeIATest(_Base):
    def test_no_afirma_el_derrumbe_que_paso_dentro_del_hueco(self):
        from ai.builders import insights_drawdown
        hoy = _d.date.today()
        for off, v in ((320, 100000.0), (300, 150000.0), (280, 140000.0),
                       (20, 60000.0), (10, 62000.0), (1, 61000.0)):
            self.cron((hoy - _d.timedelta(days=off)).isoformat(), v)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertTrue(c["serie_partida"])
        self.assertIsNone(c["drawdown_maximo"])          # la pantalla dice "—"
        p = insights_drawdown.build(self.conn, self.uid, window_days=365)
        self.assertIsNone(p["max_pct"])                  # el packet, también
        self.assertIsNone(p["current_pct"])


class SnapshotPostNoPisaElCierreTest(_Base):
    def test_una_visita_no_reemplaza_el_valor_del_cron(self):
        """Se conservaba `source='cron'` pero se pisaba `total_value`: la fila
        quedaba diciendo "cierre medido" con un número de media rueda, y pasaba
        `BORDE_PERIODO`, el filtro más estricto."""
        from fastapi.testclient import TestClient
        hoy = main._iso_today()
        self.cron(hoy, 100000.0)
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            r = TestClient(main.app).post("/api/snapshots", json={
                "total_value": 91000.0, "total_invested": 90000.0, "net_deposited": 90000.0})
            self.assertEqual(r.status_code, 200)
        finally:
            main.app.dependency_overrides.clear()
        fila = self.conn.execute(
            "SELECT total_value, source FROM snapshots WHERE user_id=? AND date=?",
            (self.uid, hoy)).fetchone()
        self.assertAlmostEqual(fila["total_value"], 100000.0, places=2)
        self.assertEqual(fila["source"], "cron")

    def test_sin_cierre_previo_la_visita_si_escribe(self):
        from fastapi.testclient import TestClient
        hoy = main._iso_today()
        main.app.dependency_overrides[main.get_effective_user] = lambda: self.uid
        try:
            TestClient(main.app).post("/api/snapshots", json={
                "total_value": 91000.0, "total_invested": 90000.0, "net_deposited": 90000.0})
        finally:
            main.app.dependency_overrides.clear()
        fila = self.conn.execute(
            "SELECT total_value, source FROM snapshots WHERE user_id=? AND date=?",
            (self.uid, hoy)).fetchone()
        self.assertAlmostEqual(fila["total_value"], 91000.0, places=2)
        self.assertEqual(fila["source"], "browser")


if __name__ == "__main__":
    unittest.main()
