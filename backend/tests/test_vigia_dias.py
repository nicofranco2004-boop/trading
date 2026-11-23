"""El vigía de días: ¿el plan de cada cuenta vence cuando lo que pagó dice?

POR QUÉ EXISTE. El error de Rebill de octubre (avisos que no eran cobros se
acreditaban como cobros) se arregló el 16/10, pero los días que ya había
sumado quedaron: tres cuentas con 52 a 90 días de más hasta el 23/11, y una
usando Plus gratis con la suscripción cancelada. Nada comparaba los días con
lo pagado. Ver `billing/vigia_dias.py`.

CÓMO SE PRUEBA, para que el verde signifique algo:
  · Los días entran por el WEBHOOK de Rebill (POST /api/billing/rebill-webhook),
    el mismo camino que en producción. Para tener historia (una renovación 30
    días después) se "viaja en el tiempo": se corren hacia atrás TODAS las
    fechas de la cuenta a la vez, así lo que el vigía lee es coherente.
  · Para ver que el vigía caza un cobro repetido NUEVO, se desarma el freno
    que hoy lo impide (`_rebill_cobro_ya_acreditado`) y se mira que el vigía lo
    marque. Si el vigía sólo supiera reconocer las filas de octubre, esto da
    rojo.
  · Los tres casos reales de octubre van con los renglones COMO LOS DEJÓ
    producción (medidos el 23/11, fechas y montos reales, sin datos de la
    persona). Esos renglones ya no se pueden producir por el webhook porque el
    error está arreglado: son la forma exacta que el vigía tiene que reconocer.
  · La corrección y el mail entran por el endpoint y por el ciclo de vida
    real, con un admin logueado.

Corre con: cd backend && python3 -m pytest tests/test_vigia_dias.py
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
from billing import subscriptions as subs_mod            # noqa: E402
from billing import vigia_dias                           # noqa: E402


# La forma de los tres avisos reales de Rebill, igual que en
# test_rebill_dias_de_mas.py (no se importa de ahí: ese módulo, al importarse,
# cambia la base de datos de prueba por la suya).
def _meta(uid, plan, period):
    return {"rendi_plan": plan, "rendi_period": period, "rendi_user_id": str(uid)}


def aviso_alta(uid, sub_id, plan="pro", period="monthly"):
    return {"webhook": {"event": "subscription.created"},
            "data": {"subscription": {"id": sub_id, "status": "active",
                                      "metadata": _meta(uid, plan, period)}}}


def aviso_cobro(uid, sub_id, pay_id, plan="pro", period="monthly",
                tipo="first_subscription_payment", monto=13990):
    return {"webhook": {"event": "payment.created"},
            "data": {"payment": {"id": pay_id, "status": "approved",
                                 "currency": "ARS", "amount": monto,
                                 "paymentType": tipo,
                                 "metadata": _meta(uid, plan, period)},
                     "subscriptionId": sub_id}}


def aviso_cambio(uid, sub_id, plan="pro", period="monthly"):
    return {"webhook": {"event": "subscription.updated"},
            "data": {"id": sub_id, "status": "active", "lastStatus": "active",
                     "planUpdated": True,
                     "plan": {"amount": "15900", "currency": "ARS"},
                     "metadata": _meta(uid, plan, period)}}


def _iso(dt):
    return dt.isoformat()


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
        self.tag = uuid.uuid4().hex[:8]
        self.admin = self._user("admin", is_admin=1)
        self.uid = self._user("cliente")
        self.conn.commit()
        self.sub = f"sub_{self.tag}"
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self._mails = patch("billing.emails._send", return_value=True)
        self.mails = self._mails.start()

    def tearDown(self):
        self._mails.stop()
        self.conn.close()

    def _user(self, nombre, **cols):
        cols = {"email": f"{nombre}-{self.tag}@rendi.test", "password_hash": "x",
                "approved": 1, "email_verified": 1, "name": nombre, **cols}
        return self.conn.execute(
            f"INSERT INTO users ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            tuple(cols.values())).lastrowid

    def _post(self, payload):
        r = self.client.post("/api/billing/rebill-webhook", json=payload)
        self.assertEqual(r.status_code, 200, r.text)

    def _en_prueba(self, dias_que_quedan):
        fin = _iso(datetime.utcnow() + timedelta(days=dias_que_quedan))
        self.conn.execute(
            "UPDATE users SET tier='pro', credit_active_until=?, trial_ends_at=? WHERE id=?",
            (fin, fin, self.uid))
        self.conn.execute(
            """INSERT INTO credit_ledger (user_id, kind, amount_usd, days_delta, to_plan,
                   active_until_after, note)
               VALUES (?, 'trial', 0, 20, 'pro', ?, 'Free trial')""", (self.uid, fin))
        self.conn.commit()

    def _viajar(self, dias):
        """Corre hacia atrás TODAS las fechas de la cuenta: es como si lo que
        pasó hasta ahora hubiera pasado hace `dias` días."""
        d = timedelta(days=dias)

        def corre(s):
            if not s:
                return s
            return _iso(credits_mod._parse_iso(str(s)) - d)
        for f in self.conn.execute(
                "SELECT id, created_at, active_until_before, active_until_after "
                "FROM credit_ledger WHERE user_id=?", (self.uid,)).fetchall():
            self.conn.execute(
                "UPDATE credit_ledger SET created_at=?, active_until_before=?, "
                "active_until_after=? WHERE id=?",
                (corre(f["created_at"]), corre(f["active_until_before"]),
                 corre(f["active_until_after"]), f["id"]))
        u = self.conn.execute("SELECT credit_active_until, trial_ends_at FROM users WHERE id=?",
                              (self.uid,)).fetchone()
        self.conn.execute("UPDATE users SET credit_active_until=?, trial_ends_at=? WHERE id=?",
                          (corre(u["credit_active_until"]), corre(u["trial_ends_at"]), self.uid))
        self.conn.commit()

    def _hallazgo(self):
        r = self.client.get("/api/admin/billing/vigia-dias", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        mios = [h for h in r.json()["hallazgos"] if h["id"] == self.uid]
        return mios[0] if mios else None

    def _vence(self):
        return credits_mod._parse_iso(self.conn.execute(
            "SELECT credit_active_until FROM users WHERE id=?", (self.uid,)).fetchone()[0])


class LoQueEstaBienNoSale(Base):
    """Los contravenenos: un aviso que salta con lo normal no lo mira nadie."""

    def test_pagar_desde_la_prueba_y_renovar_dos_veces(self):
        """⭐ Pagó con 18 días de prueba por delante: su plan vence siempre 18
        días después de cada cobro, para siempre. No es plata de más: son los
        días de prueba que se le respetaron."""
        self._en_prueba(dias_que_quedan=18)
        self._post(aviso_alta(self.uid, self.sub, plan="plus"))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1", plan="plus"))
        self._viajar(30)
        self._post(aviso_cobro(self.uid, self.sub, "pay_2", plan="plus",
                               tipo="subscription_payment"))
        self._viajar(30)
        self._post(aviso_cobro(self.uid, self.sub, "pay_3", plan="plus",
                               tipo="subscription_payment"))
        self.assertIsNone(self._hallazgo())

    def test_el_aviso_de_cambio_de_precio_de_hoy_no_suma_y_no_sale(self):
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_alta(self.uid, self.sub))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
        self._post(aviso_cambio(self.uid, self.sub))
        self.assertIsNone(self._hallazgo())

    def test_dos_cobros_reales_el_mismo_dia_cuentan_los_dos(self):
        """Dos ids de cobro distintos = dos cobros de verdad (cambió de tarjeta
        y pagó de nuevo). El vigía no los confunde con un repetido."""
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_alta(self.uid, self.sub))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
        self._post(aviso_cobro(self.uid, self.sub, "pay_2", tipo="subscription_payment"))
        self.assertIsNone(self._hallazgo())

    def test_la_prueba_sola_y_un_regalo_no_salen(self):
        self._en_prueba(dias_que_quedan=12)
        r = self.client.post(
            f"/api/admin/billing/grant-comp?email=cliente-{self.tag}@rendi.test"
            "&plan=pro&days=30&force=true", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(self._hallazgo())


class LoQueTieneQueSalir(Base):

    def test_un_cobro_contado_dos_veces_sale_aunque_tenga_otra_forma(self):
        """Se desarma el freno de hoy: el cobro llega antes que el alta y el
        alta vuelve a sumar el mes. Es un repetido que el vigía nunca vio."""
        self._en_prueba(dias_que_quedan=1)
        with patch("main._rebill_cobro_ya_acreditado", return_value=False):
            self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
            self._post(aviso_alta(self.uid, self.sub))
        h = self._hallazgo()
        self.assertIsNotNone(h, "el vigía no vio el mes contado dos veces")
        self.assertEqual(h["motivo"], "cobro_repetido")
        self.assertAlmostEqual(h["dias_de_mas"], 30, delta=1)
        self.assertEqual(len(h["repetidos"]), 1)

    def test_plan_vigente_sin_ningun_renglon_sale(self):
        self.conn.execute("UPDATE users SET tier='pro', credit_active_until=? WHERE id=?",
                          (_iso(datetime.utcnow() + timedelta(days=40)), self.uid))
        self.conn.commit()
        h = self._hallazgo()
        self.assertEqual(h["motivo"], "sin_registro")
        self.assertIsNone(h["deberia_vencer"])


class LosTresDeOctubre(unittest.TestCase):
    """Los renglones como los dejó producción (medidos el 23/11). Cada uno con
    la fecha que debería tener según lo que pagó."""

    AHORA = datetime(2026, 11, 23, 20, 0)

    def _fila(self, i, cuando, kind, despues, antes=None, plan="pro", pid=None):
        return {"id": i, "created_at": cuando, "kind": kind, "to_plan": plan,
                "to_period": "monthly", "payment_id": pid,
                "active_until_before": antes, "active_until_after": despues, "note": ""}

    def _evaluar(self, filas, vence, plan="pro"):
        return vigia_dias.evaluar({"id": 1, "tier": plan, "credit_active_until": vence},
                                  filas, self.AHORA)

    def test_alta_doble_mas_dos_cambios_de_precio_mas_la_renovacion(self):
        """El de Pro: pagó el 14/10 y el 14/11. Tenía hasta el 14/03."""
        f = self._fila
        filas = [
            f(1, "2026-09-25 21:38:00", "trial", "2026-10-15T21:38:00"),
            f(2, "2026-10-14 19:56:00", "payment", "2026-11-14T22:05:39", "2026-10-15T21:38:00"),
            f(3, "2026-10-14 19:56:02", "payment", "2026-12-14T22:05:39", "2026-11-14T22:05:39",
              pid="pay_5f8f"),
            f(4, "2026-10-15 17:55:00", "payment", "2027-01-13T22:05:39", "2026-12-14T22:05:39"),
            f(5, "2026-10-15 17:55:01", "payment", "2027-02-12T22:05:39", "2027-01-13T22:05:39"),
            f(6, "2026-11-14 20:03:00", "payment", "2027-03-14T22:05:39", "2027-02-12T22:05:39",
              pid="pay_cfe5"),
        ]
        h = self._evaluar(filas, "2027-03-14T22:05:39")
        self.assertEqual(h["motivo"], "cobro_repetido")
        self.assertEqual(h["deberia_vencer"][:10], "2026-12-14")
        self.assertEqual(h["dias_de_mas"], 90)
        self.assertEqual(len(h["repetidos"]), 3)

    def test_dos_cambios_de_precio_y_la_renovacion(self):
        """El de Plus que paga: cobro el 05/10 y el 12/11. Tenía hasta el 02/02."""
        f = self._fila
        filas = [
            f(1, "2026-10-05 11:15:00", "payment", "2026-11-04T11:15:04", None, plan="plus"),
            f(2, "2026-10-15 17:55:00", "payment", "2026-12-04T11:15:04", "2026-11-04T11:15:04", plan="plus"),
            f(3, "2026-10-15 17:55:01", "payment", "2027-01-03T11:15:04", "2026-12-04T11:15:04", plan="plus"),
            f(4, "2026-11-12 16:38:00", "payment", "2027-02-02T11:15:04", "2027-01-03T11:15:04",
              plan="plus", pid="pay_f28e"),
        ]
        h = self._evaluar(filas, "2027-02-02T11:15:04", plan="plus")
        self.assertEqual(h["deberia_vencer"][:10], "2026-12-12")
        self.assertEqual(h["dias_de_mas"], 52)

    def test_el_que_cancelo_y_seguia_con_plus(self):
        """Tres cobros reales (08/08, 09/09, 08/10) y dos de más el 15/10.
        Tendría que haber vencido en noviembre: hoy no debería tener plan."""
        f = self._fila
        filas = [
            f(1, "2026-08-08 22:28:00", "payment", "2026-09-07T22:28:02", None, plan="plus"),
            f(2, "2026-09-09 22:00:00", "payment", "2026-10-09T22:28:02", "2026-09-07T22:28:02",
              plan="plus", pid="pay_80c7"),
            f(3, "2026-10-08 22:00:00", "payment", "2026-11-07T22:28:02", "2026-10-09T22:28:02",
              plan="plus", pid="pay_a77e"),
            f(4, "2026-10-15 17:56:00", "payment", "2026-12-07T22:28:02", "2026-11-07T22:28:02", plan="plus"),
            f(5, "2026-10-15 17:56:01", "payment", "2027-01-06T22:28:02", "2026-12-07T22:28:02", plan="plus"),
        ]
        h = self._evaluar(filas, "2027-01-06T22:28:02", plan="plus")
        self.assertLess(h["deberia_vencer"][:10], "2026-11-23")
        self.assertGreaterEqual(h["dias_de_mas"], 58)

    def test_despues_de_la_correccion_de_hoy_ya_no_salen(self):
        """La corrección del 23/11 dejó un renglón de ajuste: cuenta como
        decisión del admin y la cuenta cierra."""
        f = self._fila
        filas = [
            f(1, "2026-10-05 11:15:00", "payment", "2026-11-04T11:15:04", None, plan="plus"),
            f(2, "2026-10-15 17:55:00", "payment", "2026-12-04T11:15:04", "2026-11-04T11:15:04", plan="plus"),
            f(3, "2026-11-12 16:38:00", "payment", "2027-01-03T11:15:04", "2026-12-04T11:15:04",
              plan="plus", pid="pay_f28e"),
            f(4, "2026-11-23 20:50:00", "manual_adjust", "2026-12-12T11:15:04", "2027-01-03T11:15:04", plan="plus"),
        ]
        self.assertIsNone(self._evaluar(filas, "2026-12-12T11:15:04", plan="plus"))


class LaCorreccionDesdeElPanel(Base):

    def _cobro_doble(self):
        self._en_prueba(dias_que_quedan=1)
        with patch("main._rebill_cobro_ya_acreditado", return_value=False):
            self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
            self._post(aviso_alta(self.uid, self.sub))
        return self._hallazgo()

    def _corregir(self, **cuerpo):
        """Como el panel: con `confirm`, primero la vista previa y después la
        escritura con la fecha que la vista previa mostró."""
        url = "/api/admin/billing/corregir-vencimiento"
        if cuerpo.get("confirm") and "antes_visto" not in cuerpo:
            p = self.client.post(url, json={"user_id": self.uid, **cuerpo, "confirm": False},
                                 headers=self.h)
            if p.status_code != 200:
                return p
            cuerpo["antes_visto"] = p.json()["antes"]
        return self.client.post(url, json={"user_id": self.uid, **cuerpo}, headers=self.h)

    def test_vista_previa_no_toca_y_corregir_deja_la_fecha_y_el_renglon(self):
        h = self._cobro_doble()
        fecha = h["deberia_vencer"][:10]
        antes = self._vence()

        p = self._corregir(fecha=fecha, motivo="Cobro contado dos veces")
        self.assertEqual(p.status_code, 200, p.text)
        self.assertFalse(p.json()["aplicado"])
        self.assertEqual(self._vence(), antes, "la vista previa escribió")

        r = self._corregir(fecha=fecha, motivo="Cobro contado dos veces", confirm=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._vence().date().isoformat(), fecha)
        self.assertEqual(self._vence().time(), antes.time(), "la hora tiene que quedar igual")
        fila = self.conn.execute(
            "SELECT kind, days_delta, note FROM credit_ledger WHERE user_id=? "
            "ORDER BY id DESC LIMIT 1", (self.uid,)).fetchone()
        self.assertEqual(fila["kind"], "manual_adjust")
        self.assertAlmostEqual(fila["days_delta"], -30, delta=1)
        self.assertIn("Cobro contado dos veces", fila["note"])
        self.assertIsNone(self._hallazgo(), "corregida, sigue saliendo")

    def test_lo_que_pago_y_el_plan_no_se_tocan(self):
        h = self._cobro_doble()
        u0 = dict(self.conn.execute(
            "SELECT tier, credit_anchor_plan, credit_anchor_amount_usd FROM users WHERE id=?",
            (self.uid,)).fetchone())
        self._corregir(fecha=h["deberia_vencer"][:10], motivo="Cobro doble", confirm=True)
        u1 = dict(self.conn.execute(
            "SELECT tier, credit_anchor_plan, credit_anchor_amount_usd FROM users WHERE id=?",
            (self.uid,)).fetchone())
        self.assertEqual(u0, u1)

    def test_dejar_como_esta_no_mueve_la_fecha_y_la_saca_de_la_lista(self):
        self._cobro_doble()
        antes = self._vence()
        r = self._corregir(fecha=None, motivo="Se lo dejo por las molestias", confirm=True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._vence(), antes)
        self.assertIsNone(self._hallazgo())

    def test_no_alarga_nunca(self):
        self._cobro_doble()
        mas_tarde = (self._vence() + timedelta(days=10)).date().isoformat()
        r = self._corregir(fecha=mas_tarde, motivo="probando", confirm=True)
        self.assertEqual(r.status_code, 400)
        self.assertIn("Regalar Pro", r.json()["detail"])

    def test_sin_motivo_no_escribe(self):
        h = self._cobro_doble()
        antes = self._vence()
        r = self._corregir(fecha=h["deberia_vencer"][:10], motivo="", confirm=True)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self._vence(), antes)

    def test_si_entro_un_cobro_mientras_mirabas_no_pisa(self):
        """La vista previa se hizo con una fecha; antes del click entró la
        renovación. La corrección no puede borrar ese cobro."""
        h = self._cobro_doble()
        fecha = h["deberia_vencer"][:10]
        p = self._corregir(fecha=fecha, motivo="Cobro doble")
        # Mientras el admin lee el cartel, entra la renovación.
        renovado = _iso(self._vence() + timedelta(days=30))
        self.conn.execute("UPDATE users SET credit_active_until=? WHERE id=?",
                          (renovado, self.uid))
        self.conn.commit()
        r = self._corregir(fecha=fecha, motivo="Cobro doble", confirm=True,
                           antes_visto=p.json()["antes"])
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(_iso(self._vence()), renovado, "la corrección pisó el cobro")

    def test_confirmar_sin_haber_visto_la_vista_previa_no_escribe(self):
        h = self._cobro_doble()
        antes = self._vence()
        r = self.client.post("/api/admin/billing/corregir-vencimiento",
                             json={"user_id": self.uid, "fecha": h["deberia_vencer"][:10],
                                   "motivo": "Cobro doble", "confirm": True}, headers=self.h)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self._vence(), antes)

    def test_sin_ser_admin_no_entra(self):
        h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.assertEqual(self.client.get("/api/admin/billing/vigia-dias", headers=h).status_code, 403)
        r = self.client.post("/api/admin/billing/corregir-vencimiento",
                             json={"user_id": self.uid, "motivo": "xxxxx", "confirm": True}, headers=h)
        self.assertEqual(r.status_code, 403)


class ElMailDeCadaNoche(Base):

    def _asuntos(self):
        return [c.args[1] for c in self.mails.call_args_list if "no cierran" in c.args[1]]

    def test_el_ciclo_de_la_madrugada_avisa_una_vez_con_la_lista(self):
        self._en_prueba(dias_que_quedan=1)
        with patch("main._rebill_cobro_ya_acreditado", return_value=False):
            self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
            self._post(aviso_alta(self.uid, self.sub))
        self.mails.reset_mock()
        res = subs_mod.run_lifecycle_job(self.conn)
        self.assertEqual(res["vigia_dias"], 1)
        self.assertEqual(len(self._asuntos()), 1, self.mails.call_args_list)
        texto = [c.args[3] for c in self.mails.call_args_list if "no cierran" in c.args[1]][0]
        self.assertIn(f"id {self.uid}", texto)

    def test_la_vuelta_de_la_tarde_no_lo_repite(self):
        self._en_prueba(dias_que_quedan=1)
        with patch("main._rebill_cobro_ya_acreditado", return_value=False):
            self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
            self._post(aviso_alta(self.uid, self.sub))
        self.mails.reset_mock()
        subs_mod.run_lifecycle_job(self.conn, solo_avisos=True)
        self.assertEqual(self._asuntos(), [])

    def test_sin_nada_raro_no_sale_mail(self):
        self._en_prueba(dias_que_quedan=1)
        self._post(aviso_alta(self.uid, self.sub))
        self._post(aviso_cobro(self.uid, self.sub, "pay_1"))
        self.mails.reset_mock()
        subs_mod.run_lifecycle_job(self.conn)
        self.assertEqual(self._asuntos(), [])


if __name__ == "__main__":
    unittest.main()
