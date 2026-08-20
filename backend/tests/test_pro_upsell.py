"""Probar Pro sin dejar el Plus que ya se paga.

El caso que lo motivó: un suscriptor de Plus entra a Planes y no le aparece
ninguna prueba de Pro. Es el mejor candidato que hay —ya paga, ya usa la app— y
era justo el único al que no se le ofrecía nada.

El free trial normal NO sirve para él y por eso lo excluye: `start()` escribe
credit_active_until = ahora + 15d y borra los anchors, así que a alguien con 11
días pagos por delante le PISA la ventana que compró y deja al sistema sin saber
qué plan tiene. Esto es otro mecanismo: una marca aparte (`pro_trial_until`) que
get_tier mira por arriba y que vence sola.

Lo que estos tests protegen, en orden:
  1. Que NO se le toque nada del plan pago: ni la suscripción, ni la fecha de
     renovación, ni el crédito, ni el anchor. Si esto se rompe, le rompemos el
     plan a alguien que paga.
  2. Que al vencer vuelva SOLO a Plus, sin que corra ningún cron.
  3. Que volver a Plus no lo castigue con la cuota que gastó en Pro.
  4. Que solo lo pueda usar el que paga Plus, y una sola vez.

Corre con: cd backend && python3 -m pytest tests/test_pro_upsell.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
from ai import quota
from billing import trial as tr


def _iso(dt):
    return dt.isoformat()


class ProUpsellBase(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("credit_ledger", "subscriptions", "trial_consumed", "trial_email_log",
                  "ai_usage_daily", "operations", "positions", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        os.environ.pop("TRIALS_ENABLED", None)
        self.addCleanup(self.conn.close)

    # ── siembra ─────────────────────────────────────────────────────────────

    def _plus_pago(self, dias_restantes=11):
        """Un suscriptor de Plus como el del caso real."""
        hasta = datetime.utcnow() + timedelta(days=dias_restantes)
        cur = self.conn.execute(
            """INSERT INTO users (email, password_hash, approved, email_verified, tier,
                                  credit_active_until, credit_anchor_plan,
                                  credit_anchor_period, credit_anchor_amount_usd,
                                  credit_anchor_at)
               VALUES (?, 'x', 1, 1, 'plus', ?, 'plus', 'monthly', 4.0, ?)""",
            (f"plus-{uuid.uuid4().hex[:8]}@rendi.test", _iso(hasta), _iso(datetime.utcnow())))
        uid = cur.lastrowid
        self.conn.execute(
            """INSERT INTO subscriptions (user_id, status, external_reference, period,
                                          amount_ars) VALUES (?, 'authorized', ?, 'monthly', 5990)""",
            (uid, f"ref-{uid}"))
        self.conn.commit()
        return uid

    def _foto(self, uid):
        r = self.conn.execute(
            """SELECT tier, credit_active_until, credit_anchor_plan, credit_anchor_period,
                      credit_anchor_amount_usd FROM users WHERE id=?""", (uid,)).fetchone()
        s = self.conn.execute(
            "SELECT status, period FROM subscriptions WHERE user_id=?", (uid,)).fetchone()
        return dict(r), dict(s)

    def _vencer(self, uid, dias_pasados=1):
        """Mueve la prueba de Pro al pasado, como si ya hubiera terminado."""
        self.conn.execute(
            "UPDATE users SET pro_trial_until=? WHERE id=?",
            (_iso(datetime.utcnow() - timedelta(days=dias_pasados)), uid))
        self.conn.commit()


class NoLeTocaElPlanPago(ProUpsellBase):
    """Lo más importante: es alguien que PAGA."""

    def test_activarlo_no_cambia_nada_de_su_plan(self):
        uid = self._plus_pago()
        antes_u, antes_s = self._foto(uid)
        res = tr.start_pro_upsell(self.conn, uid)
        self.assertTrue(res.get("ok"), res)
        despues_u, despues_s = self._foto(uid)
        self.assertEqual(antes_u, despues_u,
                         "se le tocó el plan pago (tier / crédito / anchor)")
        self.assertEqual(antes_s, despues_s, "se le tocó la suscripción")

    def test_igual_ve_pro_mientras_dura(self):
        uid = self._plus_pago()
        self.assertEqual(quota.get_tier(self.conn, uid), "plus")
        tr.start_pro_upsell(self.conn, uid)
        self.assertEqual(quota.get_tier(self.conn, uid), "pro")

    def test_al_vencer_vuelve_a_plus_sin_que_corra_ningun_cron(self):
        uid = self._plus_pago()
        tr.start_pro_upsell(self.conn, uid)
        self._vencer(uid)
        # Sin llamar a NADA: get_tier lo resuelve en tiempo real.
        self.assertEqual(quota.get_tier(self.conn, uid), "plus")
        u, s = self._foto(uid)
        self.assertEqual(u["credit_anchor_plan"], "plus")
        self.assertEqual(s["status"], "authorized")

    def test_su_renovacion_no_se_corre(self):
        uid = self._plus_pago(dias_restantes=11)
        antes = self.conn.execute(
            "SELECT credit_active_until c FROM users WHERE id=?", (uid,)).fetchone()["c"]
        tr.start_pro_upsell(self.conn, uid)
        despues = self.conn.execute(
            "SELECT credit_active_until c FROM users WHERE id=?", (uid,)).fetchone()["c"]
        self.assertEqual(antes, despues, "le movimos la fecha de renovación")


class LaCuota(ProUpsellBase):
    """Volver a Plus no puede castigarlo por haber probado."""

    def test_arranca_la_prueba_con_la_cuota_de_pro_limpia(self):
        uid = self._plus_pago()
        for _ in range(6):                      # gastó TODO su Plus (6/semana)
            quota.record_analysis(self.conn, uid)
        self.assertEqual(quota.can_analyze(self.conn, uid)[0], False)
        tr.start_pro_upsell(self.conn, uid)
        self.assertTrue(quota.can_analyze(self.conn, uid)[0],
                        "arrancó la prueba de Pro con la cuota ya agotada")

    def test_al_volver_a_plus_no_arrastra_lo_que_gasto_en_pro(self):
        """El bug que ya nos costó una vez: la ventana de cuota es móvil de 7
        días y la prueba dura 7, así que sin un piso el que probó Pro volvía a
        su Plus con 60 análisis contando contra un techo de 6 — castigado por
        haber probado, y encima justo cuando hay que retenerlo."""
        uid = self._plus_pago()
        tr.start_pro_upsell(self.conn, uid)
        # La prueba corrió del día -8 al -1: el consumo de Pro cae DENTRO de esa
        # ventana, que es como pasa de verdad (no todo el mismo día).
        self.conn.execute(
            "UPDATE users SET pro_trial_until=?, quota_window_from=? WHERE id=?",
            (_iso(datetime.utcnow() - timedelta(days=1)),
             (datetime.utcnow() - timedelta(days=8)).date().isoformat(), uid))
        for atras in (5, 4, 3, 2):              # 40 análisis con el techo de Pro
            self.conn.execute(
                "INSERT INTO ai_usage_daily (user_id, date, analyses_count, chat_count) "
                "VALUES (?, ?, 10, 0)",
                (uid, (datetime.utcnow() - timedelta(days=atras)).date().isoformat()))
        self.conn.commit()
        self.assertEqual(quota.get_tier(self.conn, uid), "plus")
        u = quota.get_current_usage(self.conn, uid)
        self.assertEqual(u["analyses_count"], 0,
                         f"volvió a Plus arrastrando {u['analyses_count']} análisis de Pro")
        self.assertTrue(quota.can_analyze(self.conn, uid)[0])


class QuienPuede(ProUpsellBase):

    def test_el_que_paga_plus_si(self):
        uid = self._plus_pago()
        self.assertTrue(tr.pro_upsell_eligibility(self.conn, uid)["can_start"])

    def test_el_que_ya_paga_pro_no(self):
        uid = self._plus_pago()
        self.conn.execute(
            "UPDATE users SET tier='pro', credit_anchor_plan='pro' WHERE id=?", (uid,))
        self.conn.commit()
        e = tr.pro_upsell_eligibility(self.conn, uid)
        self.assertFalse(e["can_start"])
        self.assertEqual(e["reason"], "already_pro")

    def test_el_que_no_paga_no(self):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"free-{uuid.uuid4().hex[:6]}@rendi.test",))
        self.conn.commit()
        e = tr.pro_upsell_eligibility(self.conn, cur.lastrowid)
        self.assertFalse(e["can_start"])
        self.assertEqual(e["reason"], "not_paying")

    def test_el_que_esta_en_el_free_trial_no(self):
        """Su tier dice 'pro'/'plus' pero no pagó nada: le corresponde el trial
        normal, no éste. Se distingue con credit_is_trial, el criterio único."""
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?, 'x', 1, 1)", (f"trial-{uuid.uuid4().hex[:6]}@rendi.test",))
        uid = cur.lastrowid
        self.conn.commit()
        tr.start(self.conn, uid)
        e = tr.pro_upsell_eligibility(self.conn, uid)
        self.assertFalse(e["can_start"], "se le ofreció a alguien que está en el free trial")

    def test_una_sola_vez(self):
        uid = self._plus_pago()
        self.assertTrue(tr.start_pro_upsell(self.conn, uid).get("ok"))
        self._vencer(uid)
        segunda = tr.start_pro_upsell(self.conn, uid)
        self.assertFalse(segunda.get("ok"))
        self.assertEqual(segunda["reason"], "already_used")

    def test_dos_requests_simultaneos_activan_una(self):
        uid = self._plus_pago()
        a = tr.start_pro_upsell(self.conn, uid)
        b = tr.start_pro_upsell(self.conn, uid)
        self.assertTrue(a.get("ok"))
        self.assertFalse(b.get("ok"))

    def test_el_interruptor_general_lo_apaga(self):
        uid = self._plus_pago()
        os.environ["TRIALS_ENABLED"] = "false"
        try:
            self.assertFalse(tr.pro_upsell_eligibility(self.conn, uid)["can_start"])
        finally:
            os.environ.pop("TRIALS_ENABLED", None)


class ElEstadoParaLaUI(ProUpsellBase):

    def test_antes_de_activarlo(self):
        uid = self._plus_pago()
        st = tr.pro_upsell_status(self.conn, uid)
        self.assertTrue(st["can_start"])
        self.assertFalse(st["active"])
        self.assertEqual(st["days"], tr.PRO_UPSELL_DAYS)

    def test_mientras_corre(self):
        uid = self._plus_pago()
        tr.start_pro_upsell(self.conn, uid)
        st = tr.pro_upsell_status(self.conn, uid)
        self.assertTrue(st["active"])
        self.assertTrue(st["used"])
        self.assertFalse(st["can_start"])
        self.assertEqual(st["days_left"], tr.PRO_UPSELL_DAYS)

    def test_cuando_termino(self):
        uid = self._plus_pago()
        tr.start_pro_upsell(self.conn, uid)
        self._vencer(uid)
        st = tr.pro_upsell_status(self.conn, uid)
        self.assertFalse(st["active"])
        self.assertTrue(st["used"])
        self.assertFalse(st["can_start"], "se le puede volver a ofrecer")


if __name__ == "__main__":
    unittest.main()
