"""Un cobro de Rebill suma UN período. Ni avisos que no son cobros, ni el mismo
cobro contado dos veces.

EL BUG, medido en producción el 2026-10-16: una persona pagó UNA vez Pro mensual
y el panel le mostraba 119 días. Su registro de créditos tenía 4 filas de +30:
  · 2 del mismo primer cobro: `subscription.created` y `payment.created` llegan
    con 2 segundos de diferencia y los dos acreditaban.
  · 2 de `subscription.updated` (status 'active', planUpdated) que Rebill mandó
    al editar los precios en el dashboard el 2026-10-15. No entró plata.
Otras dos personas con +60 días por lo mismo de los precios, y una de junio con
el primer mes contado doble.

Y debajo, el eslabón que dejaba pasar todo: en el aviso de cobro real el id de la
suscripción viene en `data.subscriptionId`, y `extract_subscription_id` no lo
buscaba ahí. El cobro quedaba sin suscripción y el freno anti-duplicado, que
pedía los dos ids, no se activaba nunca.

⚠️ ESTAS PRUEBAS ENTRAN POR EL WEBHOOK (POST /api/billing/rebill-webhook), que es
el camino de producción entero: el router decide qué handler corre, y ahí estaba
la mitad del bug. La FORMA de los avisos es la de los reales de producción; los
valores son inventados.

Corre con: cd backend && python3 -m pytest tests/test_rebill_dias_de_mas.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main                                              # noqa: E402
from billing import credits as credits_mod               # noqa: E402
from billing import rebill as rebill_mod                 # noqa: E402


def _meta(uid, plan, period):
    return {"rendi_plan": plan, "rendi_period": period, "rendi_user_id": str(uid)}


def aviso_alta(uid, sub_id, plan="pro", period="monthly"):
    """`subscription.created` real: el id adentro de `data.subscription`, sin cobro."""
    return {"webhook": {"event": "subscription.created"},
            "data": {"subscription": {"id": sub_id, "status": "active",
                                      "metadata": _meta(uid, plan, period)}}}


def aviso_cobro(uid, sub_id, pay_id, plan="pro", period="monthly",
                tipo="first_subscription_payment", monto=13990):
    """`payment.created` real: el id de la suscripción AL LADO de `payment`."""
    return {"webhook": {"event": "payment.created"},
            "data": {"payment": {"id": pay_id, "status": "approved",
                                 "currency": "ARS", "amount": monto,
                                 "paymentType": tipo,
                                 "metadata": _meta(uid, plan, period)},
                     "subscriptionId": sub_id}}


def aviso_cambio(uid, sub_id, plan="pro", period="monthly"):
    """`subscription.updated` real del día que se editaron los precios: el id
    en `data.id`, status 'active', planUpdated. No hay cobro."""
    return {"webhook": {"event": "subscription.updated"},
            "data": {"id": sub_id, "status": "active", "lastStatus": "active",
                     "planUpdated": True,
                     "plan": {"amount": "15900", "currency": "ARS"},
                     "metadata": _meta(uid, plan, period)}}


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(main.app)

    def setUp(self):
        self.conn = main.get_db()
        for t in ("credit_ledger", "subscriptions", "billing_events", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, name) "
            "VALUES (?,?,1,1,'Prueba')",
            (f"dias-{uuid.uuid4().hex[:8]}@rendi.test", "x")).lastrowid
        self.conn.commit()
        self.sub = f"sub_{uuid.uuid4().hex[:12]}"
        self._mails = patch("billing.emails._send", return_value=True)
        self._mails.start()

    def tearDown(self):
        self._mails.stop()
        self.conn.close()

    def _post(self, payload):
        r = self.client.post("/api/billing/rebill-webhook", json=payload)
        self.assertEqual(r.status_code, 200, r.text)

    def _en_prueba(self, dias_que_quedan=1):
        """La prueba gratis: ventana viva SIN anchor (no se pagó nada)."""
        fin = (datetime.utcnow() + timedelta(days=dias_que_quedan)).isoformat()
        self.conn.execute(
            "UPDATE users SET tier='plus', credit_active_until=? WHERE id=?",
            (fin, self.uid))
        self.conn.commit()

    def _dias(self):
        u = self.conn.execute("SELECT credit_active_until FROM users WHERE id=?",
                              (self.uid,)).fetchone()
        return (credits_mod._parse_iso(u["credit_active_until"])
                - datetime.utcnow()).total_seconds() / 86400.0

    def _cobros(self):
        return self.conn.execute(
            "SELECT source_subscription_id sid, payment_id, amount_usd "
            "FROM credit_ledger WHERE user_id=? AND kind='payment' ORDER BY id",
            (self.uid,)).fetchall()


class ElCasoQueSeVioEnProduccion(Base):

    def test_un_pago_y_los_avisos_del_cambio_de_precio_dan_UN_mes(self):
        """⭐ La secuencia exacta de la persona de los 119 días: le quedaba 1 día
        de prueba, pagó Pro mensual, y al otro día se editaron los precios."""
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_alta(self.uid, self.sub))
        self._post(aviso_cobro(self.uid, self.sub, "pay_primero"))
        self._post(aviso_cambio(self.uid, self.sub))
        self._post(aviso_cambio(self.uid, self.sub))

        # 1 día de prueba que se respeta + 30 pagados. Antes: 121.
        self.assertAlmostEqual(self._dias(), 31, delta=0.1)
        cobros = self._cobros()
        self.assertEqual(len(cobros), 1, [dict(c) for c in cobros])
        self.assertEqual(cobros[0]["payment_id"], "pay_primero",
                         "la fila del alta tiene que quedar con el id del cobro")
        self.assertEqual(cobros[0]["sid"], self.sub)

    def test_si_el_cobro_llega_ANTES_que_el_alta_tambien_es_un_mes(self):
        """El orden lo elige Rebill: en otro caso de producción el cobro llegó
        primero. Antes ese cobro no se acreditaba (no había anchor) y el mes
        lo daba el alta; ahora lo da el cobro, y el alta no suma otro."""
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_cobro(self.uid, self.sub, "pay_primero", plan="plus"))
        self._post(aviso_alta(self.uid, self.sub, plan="plus"))

        self.assertAlmostEqual(self._dias(), 31, delta=0.1)
        self.assertEqual(len(self._cobros()), 1)

    def test_el_cambio_de_precio_no_regala_dias_a_quien_ya_paga(self):
        """Los otros dos de producción: +60 días cada uno por dos avisos."""
        self._en_prueba(dias_que_quedan=0.001)
        self._post(aviso_alta(self.uid, self.sub, plan="plus"))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1", plan="plus"))
        antes = self._dias()

        self._post(aviso_cambio(self.uid, self.sub, plan="plus"))
        self._post(aviso_cambio(self.uid, self.sub, plan="plus"))

        self.assertAlmostEqual(self._dias(), antes, delta=0.01)
        self.assertEqual(len(self._cobros()), 1)

    def test_el_mismo_cobro_reenviado_no_suma_dos_veces(self):
        """Rebill reintenta si tardamos en contestar. El freno existía pero
        pedía el id de la suscripción, que en el aviso real no se leía."""
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_alta(self.uid, self.sub))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1", tipo="subscription_payment"))
        self.assertAlmostEqual(self._dias(), 31, delta=0.1)
        self.assertEqual(len(self._cobros()), 1)


class LoQueSiTieneQueSumar(Base):
    """Los contravenenos: el arreglo no puede dejar sin días a quien pagó."""

    def test_cada_renovacion_suma_su_mes(self):
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_alta(self.uid, self.sub))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
        self._post(aviso_cobro(self.uid, self.sub, "pay_2", tipo="subscription_payment"))
        self._post(aviso_cobro(self.uid, self.sub, "pay_3", tipo="subscription_payment"))
        self.assertAlmostEqual(self._dias(), 91, delta=0.1)
        self.assertEqual([c["payment_id"] for c in self._cobros()],
                         ["pay_1", "pay_2", "pay_3"])

    def test_una_reactivacion_con_cobro_suma_por_el_cobro(self):
        """Rebill reintentaba (tarjeta rechazada), la persona cambió la tarjeta:
        llega `subscription.updated` active Y el cobro. Suma una vez."""
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_alta(self.uid, self.sub))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
        antes = self._dias()
        self._post(aviso_cambio(self.uid, self.sub))
        self._post(aviso_cobro(self.uid, self.sub, "pay_2", tipo="subscription_payment"))
        self.assertAlmostEqual(self._dias(), antes + 30, delta=0.1)

    def test_el_alta_sola_sigue_dando_el_mes(self):
        """Si el aviso del cobro no llegara nunca, el alta igual da el período:
        es como funcionaba antes y no se cambia."""
        self._post(aviso_alta(self.uid, self.sub))
        self.assertAlmostEqual(self._dias(), 30, delta=0.1)

    def test_el_alta_deja_el_tier_pago(self):
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
        self._post(aviso_alta(self.uid, self.sub))
        tier = self.conn.execute("SELECT tier FROM users WHERE id=?",
                                 (self.uid,)).fetchone()["tier"]
        self.assertEqual(tier, "pro")


class LoQueQuedaAnotado(Base):

    def test_el_monto_en_pesos_no_queda_como_dolares(self):
        """El cobro de Pro quedó en el registro como «13.990 dólares». Era el
        arreglo que el alta ya tenía y no se había pasado al aviso de cobro."""
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_alta(self.uid, self.sub))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1", monto=13990,
                               tipo="subscription_payment"))
        for c in self._cobros():
            self.assertLess(c["amount_usd"], 100, "pesos anotados como dólares")
        fila = self.conn.execute(
            "SELECT amount_ars FROM subscriptions WHERE mp_subscription_id=?",
            (self.sub,)).fetchone()
        self.assertEqual(fila["amount_ars"], 13990)

    def test_el_id_de_la_suscripcion_se_lee_del_aviso_de_cobro_real(self):
        p = aviso_cobro(self.uid, "sub_real", "pay_x")
        self.assertEqual(rebill_mod.extract_subscription_id(p), "sub_real")
        # y los otros dos avisos siguen leyéndose como antes
        self.assertEqual(rebill_mod.extract_subscription_id(aviso_alta(1, "sub_a")), "sub_a")
        self.assertEqual(rebill_mod.extract_subscription_id(aviso_cambio(1, "sub_c")), "sub_c")


if __name__ == "__main__":
    unittest.main()
