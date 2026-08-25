"""Quinta ronda: consolidación.

No agrega precisión. Cierra la regresión que introdujo la ronda 4 y deja escrito
el criterio, porque el patrón de las cuatro rondas anteriores fue siempre el
mismo: se cierra un bloqueante y se reabre otro de la misma familia.
"""
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
            (f"r5-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2024-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def cron(self, d, v, nd):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) "
            "VALUES (?,?,?,?,?,'cron',1200,'[]')",
            (self.uid, d, float(v), float(v), float(nd)))
        self.conn.commit()

    def me(self, y, m, ci, cf, dep=0.0):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',?,?,?,?,?,0,0,0)", (self.uid, y, m, ci, cf, dep))
        self.conn.commit()


class ImportAMitadDeMesTest(_Base):
    """B-1 · EL CRITERIO PRINCIPAL DE ESTA RONDA.

    La ronda 4 prefería la estampa diaria y caía al canónico sólo en los meses
    "sospechosos". La señal miraba la fila de FIN DE MES — justo la única que un
    import nunca deja vieja, porque el import cae un día cualquiera y el cron
    sigue corriendo y reescribe el resto del mes con la contabilidad nueva. El mes
    pasaba como confiable, se usaban estampas mitad viejas mitad nuevas, y el
    escalón entre unas y otras se leía como un flujo contra un valor inmóvil.
    """

    def _julio_plano_con_import_el_16(self):
        # El import reescribe monthly_entries hacia atrás: el aportado pasa de
        # 60.000 a 110.000. Julio está PLANO en 110.000 y no tuvo aportes.
        self.me(2025, 12, 0.0, 60000.0, dep=60000.0)
        self.me(2026, 6, 60000.0, 110000.0, dep=50000.0)
        self.me(2026, 7, 110000.0, 110000.0)
        self.cron("2026-06-30", 110000.0, 60000.0)              # estampa VIEJA
        for d in range(1, 16):
            self.cron(f"2026-07-{d:02d}", 110000.0, 60000.0)    # VIEJAS
        for d in range(16, 32):
            self.cron(f"2026-07-{d:02d}", 110000.0, 110000.0)   # NUEVAS (post-import)

    def test_un_mes_plano_no_fabrica_drawdown(self):
        self._julio_plano_con_import_el_16()
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["drawdown_maximo"], 0.0, places=6)
        self.assertAlmostEqual(c["twr"], 0.0, places=6)
        self.assertIsNone(c["drawdown_maximo_fecha"])

    def test_el_mes_cerrado_tampoco(self):
        """No se autocura al cerrar el mes: con el mes cerrado daba lo mismo."""
        self._julio_plano_con_import_el_16()
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-07-01", "2026-07-31", "global", None)
        self.assertAlmostEqual(m.delta_usd, 0.0, places=2)
        self.assertAlmostEqual(m.delta_pct, 0.0, places=2)

    def test_el_aportado_no_depende_de_la_estampa(self):
        """La propiedad de fondo: las dos puntas de cualquier resta salen de la
        MISMA lectura de la contabilidad, no de dos momentos distintos."""
        self._julio_plano_con_import_el_16()
        s = twr.serie_medible(self.conn, self.uid)
        julio = [p["net_deposited"] for p in s["puntos"] if p["date"].startswith("2026-07")]
        self.assertEqual(len(set(julio)), 1, f"el aportado salta dentro de julio: {set(julio)}")


class ReEstampadoPorMesEsInocuoTest(_Base):
    """B-3 · `_cascade_after_movement_delete` (main.py:12450) sigue re-estampando
    `net_deposited` con la fórmula truncada a mes. Con el aportado canónico la
    curva NO lo lee, así que para Diagnóstico y Reportes es inocuo — y este test
    existe para que siga siéndolo.

    ⚠️ Lo que NO cubre: la columna sí cambia, y la leen `/api/snapshots` (el chart
    del Dashboard) y el informe del asesor. Queda anotado, no arreglado: es de otra
    ronda."""

    def test_la_curva_no_cambia_aunque_se_re_estampe(self):
        self.me(2026, 2, 100000.0, 110000.0, dep=10000.0)
        for d in range(1, 29):
            v = 100000.0 if d < 20 else 110000.0
            self.cron(f"2026-02-{d:02d}", v, v)
        antes = twr.curva_indexada(self.conn, self.uid)
        main._recompute_snapshots_netdep_for_user(self.conn, self.uid)
        self.conn.commit()
        despues = twr.curva_indexada(self.conn, self.uid)
        self.assertEqual(antes["twr"], despues["twr"])
        self.assertEqual(antes["drawdown_maximo"], despues["drawdown_maximo"])

    def test_pero_la_columna_SI_cambia(self):
        """Documentado a propósito: si algún día esto deja de ser cierto, es porque
        alguien arregló la granularidad — y entonces este test avisa."""
        self.me(2026, 2, 100000.0, 110000.0, dep=10000.0)
        for d in range(1, 29):
            v = 100000.0 if d < 20 else 110000.0
            self.cron(f"2026-02-{d:02d}", v, v)
        antes = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=?", (self.uid,))}
        main._recompute_snapshots_netdep_for_user(self.conn, self.uid)
        self.conn.commit()
        despues = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=?", (self.uid,))}
        cambiadas = sum(1 for k in antes if antes[k] != despues[k])
        self.assertGreater(cambiadas, 0)


class LaClasificacionNoEstaMaterializadaTest(unittest.TestCase):
    """B-2 · decisión explícita, para que la próxima ronda no herede una premisa
    falsa. `backfill_source_legacy` decía correr "en un thread daemon al startup"
    y ese thread no existía: cero call-sites de producción."""

    def test_no_quedo_una_funcion_de_backfill_sin_llamadores(self):
        self.assertFalse(hasattr(twr, "backfill_source_legacy"))

    def test_la_clasificacion_es_read_time_y_esta_documentada(self):
        import inspect
        src = inspect.getsource(twr)
        self.assertIn("LA CLASIFICACIÓN ES READ-TIME", src)


if __name__ == "__main__":
    unittest.main()
