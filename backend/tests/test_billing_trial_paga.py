"""El usuario que está en la prueba gratis y PAGA.

El free trial arranca a propósito sin `credit_anchor_*` (el tiempo regalado no
vale plata; darle un anchor es lo que fabricaba 41 días de Plus, audit
2026-08-09). Eso convirtió un estado antes casi inalcanzable —acceso vigente
sin plan pago detrás— en el estado NORMAL de toda la población en prueba, y
dos caminos que nunca lo habían visto empezaron a pasar por ahí:

  1. /api/billing/change-plan cancelaba la suscripción de Rebill ANTES de
     convertir el crédito. Con anchor NULL, convert_plan tira ValueError → 500,
     pero la baja ya estaba commiteada: el usuario pagó, se quedó sin la
     suscripción y sin el plan nuevo. Y no hace falta que la busque: /subscribe
     devuelve 409 con hint=use_change_plan y el frontend abre el modal solo.

  2. El fallback del webhook (cuando falla el ledger) escribía la fecha de
     crédito solo `WHERE credit_active_until IS NULL`. Un usuario en prueba ya
     la tiene puesta → el fallback no disparaba y el mes que acababa de pagar
     le quedaba recortado a lo que le quedara de prueba.

Estos tests fijan las dos reglas: ninguna falla puede dejar a alguien pagando
por nada, y ningún fallback puede acortar lo que ya pagó.

Corre con: cd backend && python3 -m pytest tests/test_billing_trial_paga.py
"""
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import main
from billing import credits as credits_mod
from billing import trial as tr


def _nuevo_user(conn, verificado=True):
    email = f"trialpaga-{uuid.uuid4().hex[:12]}@rendi.test"
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, email_verified) "
        "VALUES (?, 'x', 1, ?)", (email, 1 if verificado else 0))
    return cur.lastrowid


class TrialQuePagaBase(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        self.uid = _nuevo_user(self.conn)
        self.conn.commit()
        self.headers = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        # Nadie manda mails de verdad (tardan ~90s y traban la base).
        self._p_mail = patch("main._notify_plan_change")
        self._p_mail.start()
        self.addCleanup(self._p_mail.stop)
        self.addCleanup(self.conn.close)

    # ── helpers de estado ───────────────────────────────────────────────────

    def _arrancar_trial(self):
        tr.start(self.conn, self.uid)

    def _con_sub_paga(self):
        """Suscripción de Rebill vigente — el usuario YA pagó."""
        self.sub_id = f"sub-{uuid.uuid4().hex[:10]}"
        self.conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars)
               VALUES (?, ?, ?, 'monthly', 'authorized', 12100)""",
            (self.uid, self.sub_id, f"rendi-{self.uid}-pro-monthly"))
        self.conn.commit()
        return self.sub_id

    def _con_anchor(self, plan="pro", period="monthly", dias=20):
        """Usuario pago de verdad: crédito CON anchor."""
        hasta = (datetime.utcnow() + timedelta(days=dias)).isoformat()
        self.conn.execute(
            """UPDATE users SET tier=?, credit_active_until=?, credit_anchor_plan=?,
                                credit_anchor_period=?, credit_anchor_amount_usd=9.0,
                                credit_anchor_at=?
               WHERE id=?""",
            (plan, hasta, plan, period, datetime.utcnow().isoformat(), self.uid))
        self.conn.commit()

    def _estado_sub(self):
        row = self.conn.execute(
            "SELECT status FROM subscriptions WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (self.uid,)).fetchone()
        return row["status"] if row else None

    def _user(self):
        return self.conn.execute(
            """SELECT tier, credit_active_until, credit_anchor_plan, credit_anchor_period
               FROM users WHERE id=?""", (self.uid,)).fetchone()

    def _cambiar_plan(self, plan="plus", period="monthly"):
        return self.client.post("/api/billing/change-plan",
                                json={"plan": plan, "period": period},
                                headers=self.headers)


class CambioDePlanEnTrial(TrialQuePagaBase):
    """El bug de plata: cancelaba la suscripción y después fallaba."""

    def test_el_usuario_en_prueba_NO_pierde_la_suscripcion_que_pago(self):
        self._arrancar_trial()
        self._con_sub_paga()

        with patch("billing.rebill.cancel_subscription") as cancel:
            r = self._cambiar_plan()

        # Lo que importa: la suscripción sigue viva. Ni en Rebill ni acá.
        cancel.assert_not_called()
        self.assertEqual(self._estado_sub(), "authorized",
                         "le dimos de baja la suscripción que pagó")
        # Y se lo decimos en un idioma que la UI entiende (409, no 500).
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(r.json()["detail"]["reason"], "no_anchor")

    def test_el_preview_no_ofrece_un_cambio_que_no_se_puede_hacer(self):
        # Antes decía eligible=True con 0 días — y el confirm reventaba.
        self._arrancar_trial()
        r = self.client.get("/api/billing/preview-change-plan?plan=plus&period=monthly",
                            headers=self.headers)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["eligible"], body)
        self.assertEqual(body["reason"], "no_anchor")

    def test_sin_credito_activo_sigue_siendo_404(self):
        # Regresión: el caso viejo (usuario free) no se toca.
        r = self._cambiar_plan()
        self.assertEqual(r.status_code, 404, r.text)


class OrdenDeLasOperaciones(TrialQuePagaBase):
    """La conversión va PRIMERO. Vale para cualquier falla, no solo el trial."""

    def test_si_la_conversion_falla_la_suscripcion_sobrevive(self):
        self._con_anchor()
        self._con_sub_paga()

        with patch("billing.credits.convert_plan", side_effect=RuntimeError("boom")), \
             patch("billing.rebill.cancel_subscription") as cancel:
            r = self._cambiar_plan()

        self.assertEqual(r.status_code, 500)
        cancel.assert_not_called()
        self.assertEqual(self._estado_sub(), "authorized",
                         "la baja quedó commiteada aunque el cambio falló")

    def test_el_camino_feliz_sigue_dando_de_baja_la_suscripcion(self):
        self._con_anchor(plan="pro", period="monthly", dias=20)
        sub_id = self._con_sub_paga()

        with patch("billing.rebill.cancel_subscription") as cancel:
            r = self._cambiar_plan(plan="plus", period="monthly")

        self.assertEqual(r.status_code, 200, r.text)
        cancel.assert_called_once_with(sub_id)
        self.assertEqual(self._estado_sub(), "superseded")
        u = self._user()
        self.assertEqual(u["tier"], "plus")
        self.assertEqual(u["credit_anchor_plan"], "plus")

    def test_si_rebill_rechaza_la_baja_el_cambio_igual_queda_hecho(self):
        # El crédito local es la fuente de verdad; una sub ya cancelada del
        # lado de Rebill no puede dejar al usuario sin el plan que pidió.
        self._con_anchor()
        self._con_sub_paga()

        with patch("billing.rebill.cancel_subscription", side_effect=RuntimeError("4xx")):
            r = self._cambiar_plan(plan="plus", period="monthly")

        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._user()["tier"], "plus")
        self.assertEqual(self._estado_sub(), "superseded")


class FallbackDelWebhook(TrialQuePagaBase):
    """Si el ledger falla, el usuario tiene que quedarse con lo que PAGÓ."""

    def _activar_con_ledger_roto(self, plan="pro", period="monthly"):
        with patch("billing.credits.grant_payment_credit",
                   side_effect=RuntimeError("ledger caído")):
            main._rebill_activate(
                self.conn, self.uid,
                {"rendi_plan": plan, "rendi_period": period},
                f"sub-{uuid.uuid4().hex[:8]}", {})

    def _dias_de_credito(self):
        u = self._user()
        return (credits_mod._parse_iso(u["credit_active_until"])
                - datetime.utcnow()).total_seconds() / 86400.0

    def test_el_mes_pagado_no_se_recorta_a_lo_que_queda_de_prueba(self):
        self._arrancar_trial()
        # Le quedan ~3 días de prueba y paga un mes.
        self.conn.execute(
            "UPDATE users SET credit_active_until=? WHERE id=?",
            ((datetime.utcnow() + timedelta(days=3)).isoformat(), self.uid))
        self.conn.commit()

        self._activar_con_ledger_roto()

        self.assertGreater(self._dias_de_credito(), 29,
                           "pagó un mes y le quedaron los días de la prueba")

    def test_el_fallback_deja_el_anchor_puesto(self):
        # Sin anchor el usuario queda con acceso pero "sin plan pago detrás":
        # no puede cambiar de plan ni repararse con restore-tier, aunque pagó.
        self._arrancar_trial()
        self._activar_con_ledger_roto(plan="pro", period="monthly")
        u = self._user()
        self.assertEqual(u["credit_anchor_plan"], "pro")
        self.assertEqual(u["credit_anchor_period"], "monthly")

    def test_el_fallback_nunca_acorta_un_credito_mas_largo(self):
        # Anual vigente + un cobro mensual que falla: no puede bajarlo a 30 días.
        self._con_anchor(plan="pro", period="annual", dias=300)
        self._activar_con_ledger_roto(plan="pro", period="monthly")
        self.assertGreater(self._dias_de_credito(), 290)

    def test_el_camino_sin_credito_previo_sigue_igual(self):
        # Usuario free que paga y falla el ledger: 30 días desde ahora.
        self._activar_con_ledger_roto()
        self.assertGreater(self._dias_de_credito(), 29)
        self.assertLess(self._dias_de_credito(), 31)


if __name__ == "__main__":
    unittest.main()
