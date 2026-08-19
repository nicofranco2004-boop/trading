"""La ventana de cuota y los cambios de plan.

La cuota se mide sobre una ventana MÓVIL de 7 días y se compara contra el límite
del tier de HOY. Como la etapa Pro del trial dura exactamente 7 días —el mismo
largo que la ventana— al pasar a Plus el día 8 todo lo consumido con el techo de
Pro (60 análisis) se le descontaba del techo de Plus (6): el badge decía 60/6 y
cualquier análisis devolvía 429 "para 10× más análisis pasate a Rendi Pro"…
cuando en Plus no había hecho ninguno. Cuanto mejor le había ido en la prueba,
peor le iba después — justo al revés de lo que la etapa Plus tiene que provocar.

NO es un problema del trial: le pasa a cualquier bajada de plan (un Pro que
cancela y cae a Free hereda su propio consumo de Pro). El trial solo lo volvió
universal, porque baja de plan a todo el mundo dos veces en 15 días.

Dos fuentes para el piso de la ventana, porque hay dos formas de bajar:
  · users.quota_window_from — se estampa donde el tier se ESCRIBE (step-down,
    cambio de plan, regalo, cron de vencimiento).
  · credit_active_until vencido — el día 16 no pasa por NINGUNA escritura (el
    tier lo resuelve get_tier en tiempo real), así que el piso se DERIVA.

Corre con: cd backend && python3 -m pytest tests/test_quota_window_corte.py
"""
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

_TMP = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP.close()
os.environ["DB_PATH"] = _TMP.name

import main                                   # noqa: E402
from ai import quota                          # noqa: E402
from billing import trial as tr               # noqa: E402
from billing import subscriptions as subs     # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("ai_usage_daily", "credit_ledger", "subscriptions",
                  "trial_consumed", "trial_email_log", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES ('q@rendi.test','x',1,1)").lastrowid
        self.conn.commit()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _consumir(self, n, hace_dias=0):
        """Consume DE VERDAD (no INSERT a mano) y fecha el consumo N días atrás."""
        for _ in range(n):
            quota.record_analysis(self.conn, self.uid)
        if hace_dias:
            self.conn.execute(
                "UPDATE ai_usage_daily SET date=? WHERE user_id=? AND date=?",
                ((date.today() - timedelta(days=hace_dias)).isoformat(),
                 self.uid, date.today().isoformat()))
            self.conn.commit()

    def _viajar_trial(self, dias):
        """Deja el trial como si hubiera arrancado hace `dias` días. Los TRES
        campos juntos: si se mueve uno solo, step_down_due_trials deja de
        matchear (exige credit_active_until = trial_ends_at)."""
        r = self.conn.execute(
            "SELECT trial_started_at, trial_ends_at FROM users WHERE id=?",
            (self.uid,)).fetchone()
        d = timedelta(days=dias)
        ini = datetime.fromisoformat(r["trial_started_at"]) - d
        fin = datetime.fromisoformat(r["trial_ends_at"]) - d
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, trial_ends_at=?, credit_active_until=? "
            "WHERE id=?", (ini.isoformat(), fin.isoformat(), fin.isoformat(), self.uid))
        self.conn.commit()

    def _uso(self):
        return quota.get_current_usage(self.conn, self.uid)


class DiaOchoTest(Base):
    """Pro → Plus, por el cron."""

    def _hasta_el_dia_8(self, analisis):
        tr.start(self.conn, self.uid)
        self._consumir(analisis)
        self._viajar_trial(7)
        # El consumo fue en la etapa Pro = ayer, bien adentro de la ventana móvil.
        self._consumir(0)
        self.conn.execute(
            "UPDATE ai_usage_daily SET date=? WHERE user_id=?",
            ((date.today() - timedelta(days=1)).isoformat(), self.uid))
        self.conn.commit()
        self.assertEqual(tr.step_down_due_trials(self.conn), 1)
        self.assertEqual(quota.get_tier(self.conn, self.uid), "plus")

    def test_no_hereda_el_consumo_de_la_etapa_pro(self):
        """EL bug: 6 análisis (10% del tope de Pro) lo dejaban en 6/6 de Plus."""
        self._hasta_el_dia_8(6)
        u = self._uso()
        self.assertEqual(u["analyses_count"], 0)
        self.assertEqual(u["analyses_limit"], 6)
        self.assertTrue(quota.can_analyze(self.conn, self.uid)[0])

    def test_ni_siquiera_quemando_todo_el_tope_de_pro(self):
        """Cuanto mejor le fue en la prueba, peor le iba después: con los 60 que
        el propio trial le regaló quedaba bloqueado hasta el día 13."""
        self._hasta_el_dia_8(60)
        self.assertEqual(self._uso()["analyses_count"], 0)
        self.assertTrue(quota.can_analyze(self.conn, self.uid)[0])

    def test_lo_consumido_YA_en_plus_si_cuenta(self):
        """La contracara: el corte no puede volver la cuota infinita."""
        self._hasta_el_dia_8(6)
        for _ in range(6):
            quota.record_analysis(self.conn, self.uid)
        self.assertEqual(self._uso()["analyses_count"], 6)
        self.assertFalse(quota.can_analyze(self.conn, self.uid)[0])


class DiaDieciseisTest(Base):
    """Plus → Free, SIN cron: lo resuelve get_tier en tiempo real."""

    def _hasta_el_dia_16(self, analisis):
        tr.start(self.conn, self.uid)
        self._consumir(analisis, hace_dias=2)
        # 16 días: la ventana de 15 se terminó AYER (el día 16 es el primero de
        # después). Traveling 15 dejaría el vencimiento justo en este instante.
        self._viajar_trial(16)
        self.conn.execute("UPDATE users SET tier='plus' WHERE id=?", (self.uid,))
        self.conn.commit()

    def test_el_analisis_semanal_de_free_existe(self):
        """El mail de cierre le promete 1 análisis por semana. Con 1 solo
        análisis hecho en la etapa Plus, ese análisis no existía."""
        self._hasta_el_dia_16(1)
        self.assertEqual(quota.get_tier(self.conn, self.uid), "free")
        u = self._uso()
        self.assertEqual(u["analyses_count"], 0)
        self.assertEqual(u["analyses_limit"], 1)
        self.assertTrue(quota.can_analyze(self.conn, self.uid)[0])

    def test_no_hace_falta_que_corra_ningun_cron(self):
        """Es el punto del piso DERIVADO. La última escritura de
        quota_window_from fue hace 15 días (al arrancar la prueba); entre
        entonces y hoy NADIE escribió nada, y el día 16 igual tiene que cortar.
        El único dato que lo permite es credit_active_until vencido."""
        self._hasta_el_dia_16(1)
        # La marca que dejó trial.start es vieja: no puede ser la que corta.
        self.conn.execute(
            "UPDATE users SET quota_window_from=? WHERE id=?",
            ((date.today() - timedelta(days=15)).isoformat(), self.uid))
        self.conn.commit()
        self.assertEqual(quota._window_floor(self.conn, self.uid),
                         date.today() - timedelta(days=1))   # el día que venció
        self.assertTrue(quota.can_analyze(self.conn, self.uid)[0])


class CualquierBajadaDePlanTest(Base):
    """No es del trial: el mismo corte tiene que valer para todos."""

    def test_un_pro_pago_que_vence_no_arrastra_su_consumo(self):
        hasta = (datetime.utcnow() - timedelta(days=1)).isoformat()
        self.conn.execute(
            "UPDATE users SET tier='pro', credit_active_until=?, credit_anchor_plan='pro', "
            "credit_anchor_period='monthly', credit_anchor_amount_usd=9.0 WHERE id=?",
            (hasta, self.uid))
        self.conn.commit()
        self._consumir(30, hace_dias=2)          # consumo de su etapa Pro
        self.assertEqual(quota.get_tier(self.conn, self.uid), "free")
        self.assertEqual(self._uso()["analyses_count"], 0)
        self.assertTrue(quota.can_analyze(self.conn, self.uid)[0])

    def test_el_cron_que_baja_a_free_estampa_el_corte(self):
        hasta = (datetime.utcnow() - timedelta(days=1)).isoformat()
        self.conn.execute(
            "UPDATE users SET tier='pro', credit_active_until=?, credit_anchor_plan='pro', "
            "credit_anchor_period='monthly' WHERE id=?", (hasta, self.uid))
        self.conn.commit()
        subs._downgrade_expired_credit(self.conn)
        marca = self.conn.execute(
            "SELECT quota_window_from FROM users WHERE id=?", (self.uid,)).fetchone()
        self.assertEqual(marca["quota_window_from"], date.today().isoformat())

    def test_arrancar_la_prueba_limpia_la_cuota_de_free(self):
        """Si esta semana ya gastó su análisis de Free, el día 1 de Pro no puede
        salirle 1/60 — el día 1 es el que decide si la prueba se usa o se quema."""
        self._consumir(1, hace_dias=3)
        tr.start(self.conn, self.uid)
        self.assertEqual(self._uso()["analyses_count"], 0)

    def test_limite_conocido_lo_de_HOY_antes_del_cambio_sigue_contando(self):
        """LIMITACIÓN DOCUMENTADA, no un descuido.

        ai_usage_daily agrega POR DÍA: no hay hora, así que el piso solo puede
        ser un día. Lo consumido HOY antes del cambio de plan sigue contando
        contra el techo nuevo. Es el resto chico del mismo problema —queda 1 día
        en vez de 7— y cerrarlo del todo pide cambiar el esquema a timestamps.
        En la práctica no se cruza: el cron que baja de etapa corre de madrugada,
        antes de que el usuario use nada."""
        self._consumir(1)                      # hoy, con el techo de Free
        tr.start(self.conn, self.uid)          # sube a Pro hoy mismo
        self.assertEqual(self._uso()["analyses_count"], 1)


class HelperDelPisoTest(Base):
    def test_sin_piso_la_ventana_es_la_de_siempre(self):
        hoy = date.today()
        self.assertEqual(quota._window_start(hoy), hoy - timedelta(days=6))
        self.assertIsNone(quota._window_floor(self.conn, self.uid))

    def test_el_piso_nunca_adelanta_la_ventana(self):
        """Un piso viejo no puede ensanchar la ventana más allá de los 7 días."""
        hoy = date.today()
        self.assertEqual(quota._window_start(hoy, hoy - timedelta(days=90)),
                         hoy - timedelta(days=6))

    def test_gana_la_fuente_mas_nueva(self):
        """quota_window_from vs crédito vencido: manda el corte más reciente."""
        self.conn.execute(
            "UPDATE users SET quota_window_from=?, credit_active_until=?, tier='plus' WHERE id=?",
            ((date.today() - timedelta(days=5)).isoformat(),
             (datetime.utcnow() - timedelta(days=2)).isoformat(), self.uid))
        self.conn.commit()
        self.assertEqual(quota._window_floor(self.conn, self.uid),
                         date.today() - timedelta(days=2))

    def test_un_credito_VIGENTE_no_pone_piso(self):
        """Solo el vencido corta: si el crédito sigue vivo, no bajó de plan."""
        self.conn.execute(
            "UPDATE users SET credit_active_until=?, tier='pro' WHERE id=?",
            ((datetime.utcnow() + timedelta(days=10)).isoformat(), self.uid))
        self.conn.commit()
        self.assertIsNone(quota._window_floor(self.conn, self.uid))


if __name__ == "__main__":
    unittest.main()
