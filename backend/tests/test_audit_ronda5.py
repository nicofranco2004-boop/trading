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
        julio = [p["net_deposited"] for p in _todos(s) if p["date"].startswith("2026-07")]
        self.assertEqual(len(set(julio)), 1, f"el aportado salta dentro de julio: {set(julio)}")


class ReEstampadoPorMesEsInocuoTest(_Base):
    """B-3 · `_cascade_after_movement_delete` (main.py:12450) re-estampa
    `net_deposited` al borrar un movimiento.

    Estaba anotado como "inocuo" mientras la curva usaba el canónico puro. Dejó de
    serlo con el aportado anclado: la fórmula usa la estampa para saber en qué DÍA
    del mes cayó el flujo, y el re-estampado la aplanaba a un valor por mes — o sea
    destruía justo el dato que la curva necesita. Ahora el re-estampado usa el
    MISMO aportado anclado, así que corrige lo stale sin tirar la resolución."""

    def test_la_curva_no_cambia_aunque_se_re_estampe(self):
        # ⚠️ Este test pedía sólo que el número NO SE MOVIERA, y el fixture
        # publicaba +10,00% inventado: verificaba que una mentira fuera estable.
        # Ahora exige primero que el número sea CORRECTO —mercado plano, un
        # depósito: 0,00%— y recién después que el re-estampado no lo mueva.
        self.me(2026, 1, 100000.0, 100000.0)
        for d in range(1, 32):
            self.cron(f"2026-01-{d:02d}", 100000.0, 100000.0)
        self.me(2026, 2, 100000.0, 110000.0, dep=10000.0)
        for d in range(1, 29):
            v = 100000.0 if d < 20 else 110000.0
            self.cron(f"2026-02-{d:02d}", v, v)
        antes = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(antes["twr"], 0.0, places=6)
        self.assertAlmostEqual(antes["drawdown_maximo"], 0.0, places=6)
        main._recompute_snapshots_netdep_for_user(self.conn, self.uid)
        self.conn.commit()
        despues = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(despues["twr"], 0.0, places=6)
        self.assertEqual(antes["twr"], despues["twr"])
        self.assertEqual(antes["drawdown_maximo"], despues["drawdown_maximo"])

    def test_a_un_usuario_sano_no_le_toca_NI_UNA_fila(self):
        """Antes reescribía 19 de 28 filas con un único valor por mes, destruyendo
        la resolución diaria que el cron había escrito bien. Ahora el re-estampado
        usa el mismo aportado anclado que la curva, así que en una cuenta sana no
        tiene nada que corregir."""
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
        self.assertEqual(antes, despues)

    def test_pero_SI_corrige_una_estampa_stale(self):
        """Lo que la función existe para hacer: si la contabilidad cambió, las
        estampas viejas se corrigen — anclando el borde de mes, no aplanando el mes."""
        self.me(2026, 2, 100000.0, 110000.0, dep=10000.0)
        for d in range(1, 29):
            v = 100000.0 if d < 20 else 110000.0
            self.cron(f"2026-02-{d:02d}", v, 55555.0)      # estampa stale
        main._recompute_snapshots_netdep_for_user(self.conn, self.uid)
        self.conn.commit()
        fin = self.conn.execute(
            "SELECT net_deposited FROM snapshots WHERE user_id=? AND date='2026-02-28'",
            (self.uid,)).fetchone()["net_deposited"]
        self.assertAlmostEqual(fin, 110000.0, places=2)     # anclado al canónico


class AportadoAncladoTest(_Base):
    """A-1/A-2/A-3 · el aportado anclado al canónico en los bordes de mes."""

    def _plano_con_deposito(self, dep, base=100000.0, con_mes_previo=True):
        if con_mes_previo:
            self.me(2026, 1, base, base)
            for d in range(1, 32):
                self.cron(f"2026-01-{d:02d}", base, base)
        self.me(2026, 2, base, base + dep, dep=dep)
        for d in range(1, 29):
            v = base if d < 20 else base + dep
            self.cron(f"2026-02-{d:02d}", v, v)

    def test_un_deposito_no_es_ganancia_sea_del_tamano_que_sea(self):
        """El canónico puro publicaba el depósito ENTERO como rendimiento cuando
        la serie arrancaba dentro del mes: 10k→+10%, 200k→+200%."""
        for dep in (10000.0, 50000.0, 100000.0, 200000.0):
            with self.subTest(deposito=dep):
                self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
                self.conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
                self._plano_con_deposito(dep, con_mes_previo=False)
                c = twr.curva_indexada(self.conn, self.uid)
                self.assertAlmostEqual(c["twr"], 0.0, places=6)

    def test_un_deposito_grande_no_clava_el_indice_en_menos_100(self):
        """`dietz` tiene piso en −1,0 y `idx *= (1+ret)` deja el índice en CERO,
        que es absorbente: −100% para siempre."""
        self.me(2026, 1, 5000.0, 5000.0)
        for d in range(1, 32):
            self.cron(f"2026-01-{d:02d}", 5000.0, 5000.0)
        self.me(2026, 2, 5000.0, 25000.0, dep=20000.0)
        for d in range(1, 29):
            v = 5000.0 if d < 20 else 25000.0
            self.cron(f"2026-02-{d:02d}", v, v)
        self.me(2026, 3, 25000.0, 30387.5)
        for d in range(1, 32):
            self.cron(f"2026-03-{d:02d}", 25000.0 + 5387.5 * d / 31.0, 25000.0)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["twr"], 0.2155, places=3)      # el retorno REAL

    def test_si_dietz_toca_el_piso_se_corta_en_vez_de_clavar(self):
        """Un flujo que desborda el denominador no es "perdí todo": es una
        medición imposible, y eso ya se resuelve cortando, como con un hueco."""
        self.me(2026, 1, 1000.0, 1000.0)
        self.me(2026, 2, 1000.0, 1000.0, dep=10000.0)
        self.me(2026, 3, 1000.0, 1500.0)
        self.cron("2026-01-31", 1000.0, 1000.0)
        self.cron("2026-02-28", 1000.0, 11000.0)
        self.cron("2026-03-31", 1500.0, 11000.0)
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertGreater(len(c["tramos"]), 1)
        self.assertNotEqual(c["twr"], -1.0)

    def test_los_bordes_de_mes_caen_en_el_canonico(self):
        """La propiedad de la que sale todo lo demás: si las dos puntas de cada mes
        están ancladas, ningún flujo cruza el borde y la suma telescopia."""
        self._plano_con_deposito(10000.0)
        canon = twr.netdep_canonico(self.conn, self.uid)
        s = twr.serie_medible(self.conn, self.uid)
        por_fecha = {p["date"]: p["net_deposited"] for p in _todos(s)}
        self.assertAlmostEqual(por_fecha["2026-01-31"], canon("2026-01-31"), places=2)
        self.assertAlmostEqual(por_fecha["2026-02-28"], canon("2026-02-28"), places=2)
        # Y adentro del mes, el flujo cae EL DÍA que entró.
        self.assertAlmostEqual(por_fecha["2026-02-19"], 100000.0, places=2)
        self.assertAlmostEqual(por_fecha["2026-02-20"], 110000.0, places=2)


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
