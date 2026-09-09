"""El mail de bienvenida cuando el alta entra por REBILL.

⚠️ QUÉ SE ROMPÍA. `send_welcome_pro` tenía UN caller en producción y colgaba de
`_process_preapproval_event`, o sea del webhook de MERCADO PAGO. Las altas de hoy
entran por Rebill, y sus tres handlers (`_rebill_activate` 169 líneas,
`_rebill_subscription_status_change` 36, `_rebill_record_payment` 105) no mandan un
solo mail: **quien se suscribía no recibía nada**. Los únicos tests del mail
(`test_billing_emails.py`) mockean `billing.mercadopago` y están en verde, porque
prueban el camino que ya no corre.

⚠️ ESTOS TESTS ENTRAN POR EL WEBHOOK, no por el helper. El disparador vive en el
router (`main.py`, rama `subscription.created`), así que un test que llame a
`_maybe_send_welcome_email` directo —o incluso a `_rebill_activate`— pasaría en
verde sin ejercer una línea del arreglo.

⚠️ LA FORMA DE LOS PAYLOADS ES REAL, LOS VALORES NO. La estructura sale de lo que
`extract_event_name` / `extract_subscription_id` / `extract_metadata` leen de verdad
(`billing/rebill.py:509-570`): el evento va en `webhook.event`, el id en
`data.subscription.id` y el metadata en `data.subscription.metadata`. Ningún dato
personal real entra acá.
"""
import json
import os
import sys
import unittest
import uuid
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _payload(uid, sub_id, *, plan="pro", period="monthly",
             evento="subscription.created", next_charge="2026-10-08"):
    return {
        "webhook": {"event": evento},
        "data": {
            "subscription": {
                "id": sub_id,
                "status": "active",
                "nextChargeDate": next_charge,
                "metadata": {
                    "rendi_user_id": str(uid),
                    "rendi_plan": plan,
                    "rendi_period": period,
                },
            },
            "payment": {"id": f"pay_{uuid.uuid4().hex[:8]}", "amount": 12100},
        },
    }


class BienvenidaRebillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.conn = main.get_db()
        self.email = f"bienvenida-{uuid.uuid4().hex[:8]}@rendi.test"
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, name) VALUES (?,?,1,?)",
            (self.email, "x", "Nico")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _pendiente(self, link_id):
        """La fila que deja `/api/billing/subscribe` antes de que la persona pague."""
        self.conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars, created_at, updated_at)
               VALUES (?,?,?,'monthly','pending',0, datetime('now'), datetime('now'))""",
            (self.uid, link_id, f"rendi-{self.uid}-pro-monthly"))
        self.conn.commit()

    def _webhook(self, payload):
        """El camino de producción entero: POST al endpoint."""
        with patch("billing.emails._send") as send:
            send.return_value = True
            r = self.client.post("/api/billing/rebill-webhook", json=payload)
        return r, send

    def _fila(self, sub_id):
        return self.conn.execute(
            "SELECT status, welcome_email_sent_at FROM subscriptions WHERE mp_subscription_id=?",
            (sub_id,)).fetchone()

    # ── el agujero ───────────────────────────────────────────────────────────

    def test_el_alta_por_rebill_manda_la_bienvenida(self):
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        self._pendiente("link-1")
        r, send = self._webhook(_payload(self.uid, sub_id))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(send.called, "el alta por Rebill no mandó bienvenida")
        destinatario = send.call_args[0][0]
        asunto = send.call_args[0][1]
        self.assertEqual(destinatario, self.email)
        self.assertIn("Bienvenido", asunto)
        self.assertIsNotNone(self._fila(sub_id)["welcome_email_sent_at"],
                             "no quedó estampado el envío")

    def test_no_le_dice_Pro_a_alguien_que_compro_Plus(self):
        """`send_welcome_pro` defaultea a 'pro'; el metadata de Rebill sabe el plan."""
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        self._pendiente("link-2")
        _, send = self._webhook(_payload(self.uid, sub_id, plan="plus"))
        self.assertIn("Plus", send.call_args[0][1])
        self.assertNotIn("Pro", send.call_args[0][1])

    def test_no_manda_un_importe_que_no_tenemos(self):
        """Por Rebill `amount_ars` nace en 0 y nadie lo actualiza: el mail no puede
        decirle 'ARS 0' a alguien que acaba de pagar."""
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        self._pendiente("link-3")
        _, send = self._webhook(_payload(self.uid, sub_id))
        cuerpo_html, cuerpo_txt = send.call_args[0][2], send.call_args[0][3]
        self.assertNotIn("ARS 0", cuerpo_html)
        self.assertNotIn("ARS 0", cuerpo_txt)
        # Y la fecha de renovación sí sale: Rebill la manda como `nextChargeDate`,
        # el helper la leía con el nombre de MP (`next_payment_date`).
        self.assertIn("08/10/2026", cuerpo_html)

    # ── las trabas ───────────────────────────────────────────────────────────

    def test_el_mismo_evento_repetido_no_manda_dos_veces(self):
        """`subscription.created` se re-entrega — está medido sobre payloads reales."""
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        self._pendiente("link-4")
        p = _payload(self.uid, sub_id)
        _, send1 = self._webhook(p)
        self.assertTrue(send1.called)
        _, send2 = self._webhook(p)
        self.assertFalse(send2.called, "mandó la bienvenida dos veces")

    def test_sin_sub_id_no_le_manda_el_mail_a_otro(self):
        """Buscar por '' matchearía cualquier fila con el campo vacío. Se corta antes.

        El test primero manda un alta VÁLIDA: sin eso, "no mandó nada" también pasa
        sobre el código roto (donde no se manda nunca) y el guard no probaría nada."""
        sub_ok = f"sub_{uuid.uuid4().hex[:10]}"
        self._pendiente("link-5a")
        _, send_ok = self._webhook(_payload(self.uid, sub_ok))
        self.assertTrue(send_ok.called, "el mecanismo tiene que estar vivo")

        otro = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"otro-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars)
               VALUES (?, '', ?, 'monthly', 'authorized', 0)""",
            (otro, f"rendi-{otro}-pro-monthly"))
        self.conn.commit()
        self._pendiente("link-5b")
        _, send = self._webhook(_payload(self.uid, ""))
        self.assertFalse(send.called, "le mandó la bienvenida a una suscripción ajena")

    def test_si_el_mail_falla_el_alta_sigue_valiendo(self):
        """Un mail caído no puede voltear un alta ya cobrada."""
        sub_id = f"sub_{uuid.uuid4().hex[:10]}"
        self._pendiente("link-6")
        with patch("billing.emails.send_welcome_pro",
                   side_effect=RuntimeError("resend caído")) as roto:
            r = self.client.post("/api/billing/rebill-webhook",
                                 json=_payload(self.uid, sub_id))
        # Se INTENTÓ mandar (si no, el test pasaría igual sobre el código roto, donde
        # no se manda nunca) y aun así el alta quedó firme.
        self.assertTrue(roto.called, "ni siquiera intentó mandar el mail")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._fila(sub_id)["status"], "authorized")
        # Y no queda estampado como enviado: si falló, tiene que poder reintentarse.
        self.assertIsNone(self._fila(sub_id)["welcome_email_sent_at"])


class MarcaDeLosQueYaEstabanTest(unittest.TestCase):
    """La marca de una sola vez que corre al arrancar (`_marcar_bienvenidas_previas`).

    Los que se suscribieron por Rebill ANTES de este arreglo figuran como "nunca se
    les avisó", y Rebill re-entrega eventos viejos: sin la marca, una re-entrega les
    mandaría un "¡Bienvenido!" con fecha de hace meses."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.conn = main.get_db()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, name) VALUES (?,?,1,'Nico')",
            (f"marca-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _sub(self, sub_id, *, status="authorized", creada="2026-07-01 10:00:00", marca=None):
        self.conn.execute(
            """INSERT INTO subscriptions (user_id, mp_subscription_id, external_reference,
                                          period, status, amount_ars, created_at,
                                          welcome_email_sent_at)
               VALUES (?,?,?,'monthly',?,0,?,?)""",
            (self.uid, sub_id, f"rendi-{self.uid}-pro-monthly", status, creada, marca))
        self.conn.commit()

    def _marca(self, sub_id):
        return self.conn.execute(
            "SELECT welcome_email_sent_at FROM subscriptions WHERE mp_subscription_id=?",
            (sub_id,)).fetchone()["welcome_email_sent_at"]

    def test_marca_a_los_que_ya_estaban(self):
        self._sub("sub-vieja")
        main._marcar_bienvenidas_previas(self.conn)
        self.assertIsNotNone(self._marca("sub-vieja"))

    def test_no_toca_a_los_nuevos(self):
        """Una suscripción creada DESPUÉS del corte sí tiene que recibir su mail."""
        self._sub("sub-nueva", creada="2026-09-20 10:00:00")
        main._marcar_bienvenidas_previas(self.conn)
        self.assertIsNone(self._marca("sub-nueva"))

    def test_no_toca_las_que_no_llegaron_a_pagar(self):
        """Una `pending` que active algún día merece su bienvenida."""
        self._sub("sub-pendiente", status="pending")
        main._marcar_bienvenidas_previas(self.conn)
        self.assertIsNone(self._marca("sub-pendiente"))

    def test_no_pisa_una_marca_que_ya_estaba(self):
        self._sub("sub-ya-avisada", marca="2026-06-01 09:00:00")
        main._marcar_bienvenidas_previas(self.conn)
        self.assertEqual(self._marca("sub-ya-avisada"), "2026-06-01 09:00:00")

    def test_correrla_dos_veces_no_hace_nada_la_segunda(self):
        self._sub("sub-idem")
        self.assertEqual(main._marcar_bienvenidas_previas(self.conn), 1)
        self.assertEqual(main._marcar_bienvenidas_previas(self.conn), 0)

    def test_una_reentrega_vieja_ya_no_manda_el_mail(self):
        """El efecto que se busca, extremo a extremo: sub vieja + marca puesta +
        Rebill repite el evento de alta → no le llega nada."""
        self._sub("sub-reentrega")
        main._marcar_bienvenidas_previas(self.conn)
        with patch("billing.emails._send") as send:
            send.return_value = True
            r = self.client.post("/api/billing/rebill-webhook",
                                 json=_payload(self.uid, "sub-reentrega"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(send.called, "le mandó una bienvenida con fecha vieja")


if __name__ == "__main__":
    unittest.main()
