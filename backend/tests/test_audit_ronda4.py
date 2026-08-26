"""Cuarta ronda. Los cuatro le pegaban a usuarios SANOS, sin ningún import.

El patrón, otra vez: se arregla un lector y no los otros. Por eso el test que más
vale de esta ronda no está acá sino en `test_contrato_clasificacion.py`.
"""
import datetime as _d
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
            (f"r4-{id(self)}@t", "x")).lastrowid
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
            "invested, entry_date) VALUES (?,'IBKR','AAPL',0,1,100,'2024-01-01')",
            (self.uid,))
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def cron(self, d, v, nd=0.0, hold="[]", fx=1200.0, src="cron"):
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, source, fx_to_usd_blue, holdings_json) VALUES (?,?,?,?,?,?,?,?)",
            (self.uid, d, float(v), float(v), float(nd), src, fx, hold))
        self.conn.commit()

    def me(self, y, m, ci, cf, dep=0.0, wd=0.0):
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, broker, year, month, capital_inicio, "
            "capital_final, deposits, withdrawals, pnl_realized, pnl_unrealized) "
            "VALUES (?,'global',?,?,?,?,?,?,0,0)", (self.uid, y, m, ci, cf, dep, wd))
        self.conn.commit()


class DepositoAMitadDeMesTest(_Base):
    """B-b · `netdep_canonico` tiene resolución MENSUAL (los flujos manuales viven
    en `monthly_entries.manual_*` sin fecha). Enchufado punto a punto en una curva
    DIARIA retro-atribuye el depósito del 20 al día 1: un flujo contra un valor que
    todavía no lo incluye.

    HISTORIA, porque costó tres intentos: la ronda 4 prefirió la estampa y cayó al
    canónico sólo en los meses "sospechosos" —y la señal miraba la fila de fin de
    mes, la única que un import nunca deja vieja—, así que reabrió el −37,04%. La
    ronda 5 volvió al canónico puro y reabrió esto. Lo que finalmente funciona es
    anclar los BORDES DE MES al canónico y dejar que la estampa decida sólo EN QUÉ
    DÍA cae el flujo dentro del mes, con el resultado acotado al corredor entre los
    dos canónicos (`twr._aportado_por_punto`).

    Estos dos tests estuvieron marcados como `expectedFailure` mientras el defecto
    vivía. Ya no: pasan.
    """

    def _mercado_inmovil_con_deposito_el_20(self):
        self.me(2026, 1, 100000.0, 100000.0)
        self.me(2026, 2, 100000.0, 110000.0, dep=10000.0)
        for d in range(1, 32):
            self.cron(f"2026-01-{d:02d}", 100000.0, nd=100000.0)
        for d in range(1, 29):
            v = 100000.0 if d < 20 else 110000.0
            self.cron(f"2026-02-{d:02d}", v, nd=v)

    def test_el_mercado_inmovil_no_produce_drawdown(self):
        self._mercado_inmovil_con_deposito_el_20()
        c = twr.curva_indexada(self.conn, self.uid)
        self.assertAlmostEqual(c["drawdown_maximo"], 0.0, places=6)
        self.assertAlmostEqual(c["twr"], 0.0, places=6)

    def test_el_aportado_del_dia_1_no_incluye_el_deposito_del_20(self):
        self._mercado_inmovil_con_deposito_el_20()
        s = twr.serie_medible(self.conn, self.uid)
        por_fecha = {p["date"]: p["net_deposited"] for p in s["puntos"]}
        self.assertAlmostEqual(por_fecha["2026-02-01"], 100000.0, places=2)
        self.assertAlmostEqual(por_fecha["2026-02-19"], 100000.0, places=2)
        self.assertAlmostEqual(por_fecha["2026-02-20"], 110000.0, places=2)

    def test_si_la_estampa_quedo_STALE_se_cae_al_canonico(self):
        """La contracara: cuando el import reescribe la contabilidad y las estampas
        viejas dejan de coincidir, la estampa deja de ser confiable para ese mes."""
        self.me(2026, 1, 100000.0, 100000.0)
        self.me(2026, 2, 100000.0, 100000.0)
        for d in range(1, 32):
            self.cron(f"2026-01-{d:02d}", 100000.0, nd=100000.0)
        for d in range(1, 29):
            self.cron(f"2026-02-{d:02d}", 100000.0, nd=55555.0)   # estampa vieja
        s = twr.serie_medible(self.conn, self.uid)
        feb = [p for p in s["puntos"] if p["date"].startswith("2026-02")]
        for p in feb:
            self.assertAlmostEqual(p["net_deposited"], 100000.0, places=2)


class BordeConCronIncompletoTest(_Base):
    """B-c · con 5 días de tolerancia, si al cron le faltaba UN día el borde
    retrocedía a antes de un depósito que igual se contaba entero como flujo."""

    def _abril_plano_deposito_el_30(self, muere):
        self.me(2026, 4, 100000.0, 110000.0, dep=10000.0)
        self.me(2026, 5, 110000.0, 110000.0)
        for d in range(1, muere + 1):
            v = 100000.0 if d < 30 else 110000.0
            self.cron(f"2026-04-{d:02d}", v, nd=v)
        for d in range(1, 32):
            self.cron(f"2026-05-{d:02d}", 110000.0, nd=110000.0)

    def test_nunca_publica_un_porcentaje_inventado(self):
        for muere in (30, 29, 28, 25):
            with self.subTest(cron_muere=muere):
                self.conn.execute("DELETE FROM snapshots WHERE user_id=?", (self.uid,))
                self.conn.execute("DELETE FROM monthly_entries WHERE user_id=?", (self.uid,))
                self._abril_plano_deposito_el_30(muere)
                m, _ = builder.compute_metrics_for_period(
                    self.conn, self.uid, "month", "2026-05-01", "2026-05-31",
                    "global", None)
                self.assertAlmostEqual(m.delta_usd, 0.0, places=2)
                self.assertAlmostEqual(m.delta_pct, 0.0, places=2)

    def test_con_el_cron_completo_si_mide_a_mercado(self):
        """El fix no puede apagar al que tiene el cron sano."""
        self._abril_plano_deposito_el_30(30)
        m, _ = builder.compute_metrics_for_period(
            self.conn, self.uid, "month", "2026-05-01", "2026-05-31", "global", None)
        self.assertEqual(m.basis, "mercado")


class ReEstampadoFueraDelImportTest(_Base):
    def test_el_hook_post_import_no_re_estampa(self):
        """`compute_net_deposited_db` trunca la fecha a MES, así que re-estampar
        reescribe filas del cron que estaban BIEN al día: 19 de 59 filas y el chip
        "variación desde el 1 del mes" pasaba de 0 a +US$10.000 inventados, en una
        cuenta sana. Y corría en el camino de TODO import confirmado."""
        import inspect
        src = inspect.getsource(main._reconstruir_mtm)
        self.assertNotIn("_recompute_snapshots_netdep_for_user", src)

    def test_las_estampas_de_un_usuario_sano_no_se_tocan(self):
        self.me(2026, 2, 100000.0, 110000.0, dep=10000.0)
        for d in range(1, 29):
            v = 100000.0 if d < 20 else 110000.0
            self.cron(f"2026-02-{d:02d}", v, nd=v)
        antes = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=?", (self.uid,))}
        main._reconstruir_mtm(self.uid)
        despues = {r["date"]: r["net_deposited"] for r in self.conn.execute(
            "SELECT date, net_deposited FROM snapshots WHERE user_id=?", (self.uid,))}
        self.assertEqual(antes, despues)


if __name__ == "__main__":
    unittest.main()
