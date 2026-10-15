"""El aviso de Rebill sobre una suscripción que YA existe no puede crear otra fila.

EL BUG, medido en producción el 2026-10-15 con los 8 que pagan: **14 filas
'authorized' para 8 personas**, tres de ellas con 3 filas cada una, todas con el
MISMO id de suscripción de Rebill.

La causa: `_rebill_activate` buscaba SÓLO una fila 'pending' —la que deja
`/api/billing/subscribe` mientras el checkout no tiene id todavía— y si no la
encontraba INSERTABA una nueva. A quien ya está activo hace meses no le queda
ninguna pending, así que cada aviso de Rebill sobre su suscripción creaba otra
fila del mismo cobro. Al editar los 4 precios en el dashboard, Rebill avisó por
cada suscripción afectada y aparecieron de a pares.

No cobraba dos veces (del lado de Rebill hay UNA suscripción), pero:
  · ensuciaba los registros de Rendi, y
  · ⭐ la MISMA causa dejaba `amount_ars` en 0 para todos: por el camino del
    INSERT la fila nace con `amount_ars_cobrado or 0`, y un aviso de "cambió el
    plan" no trae monto cobrado. Por eso Rendi no sabía cuánto pagaba nadie.

Corre con: cd backend && python3 -m pytest tests/test_webhook_no_duplica.py
"""
import os
import sys
import tempfile
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main                                              # noqa: E402


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(main.app)

    def setUp(self):
        self.conn = main.get_db()
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("credit_ledger", "subscriptions", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        # El aviso al admin sale por mail: no en un test.
        from billing import emails as _em
        self._orig = {}
        for fn in ("send_plan_change_admin", "send_welcome_rebill"):
            if hasattr(_em, fn):
                self._orig[fn] = getattr(_em, fn)
                setattr(_em, fn, lambda *a, **k: True)

    def tearDown(self):
        from billing import emails as _em
        for fn, orig in getattr(self, "_orig", {}).items():
            setattr(_em, fn, orig)
        try:
            self.conn.rollback()
        except Exception:
            pass
        self.conn.close()

    def _persona(self, admin=0):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   is_admin) VALUES (?,?,1,1,?)",
            (f"{uuid.uuid4().hex[:8]}@rendi.test", "x", admin))
        self.conn.commit()
        return cur.lastrowid

    def _filas(self, uid):
        return self.conn.execute(
            "SELECT id, mp_subscription_id sid, status, amount_ars "
            "FROM subscriptions WHERE user_id=? ORDER BY created_at", (uid,)
        ).fetchall()

    def _aviso_de_rebill(self, uid, sub_id, monto=None):
        """El camino real: la misma función que corre el webhook."""
        main._rebill_activate(
            self.conn, uid,
            {"rendi_plan": "plus", "rendi_period": "monthly"},
            sub_id,
            {"amount": monto} if monto else {})


class ElAvisoRepetidoNoCreaFilas(Base):

    def test_el_segundo_aviso_ACTUALIZA_y_no_duplica(self):
        """⭐ El bug exacto. Dos avisos de Rebill sobre la MISMA suscripción
        tienen que dejar UNA fila, no dos."""
        uid = self._persona()
        self._aviso_de_rebill(uid, "sub_abc")
        self.assertEqual(len(self._filas(uid)), 1)

        self._aviso_de_rebill(uid, "sub_abc")      # el aviso del cambio de plan
        filas = self._filas(uid)
        self.assertEqual(
            len(filas), 1,
            f"el segundo aviso creó otra fila del mismo cobro: {[dict(f) for f in filas]}")
        self.assertEqual(filas[0]["sid"], "sub_abc")
        self.assertEqual(filas[0]["status"], "authorized")

    def test_tres_avisos_tampoco(self):
        """Es lo que pasó en producción: tres filas por persona."""
        uid = self._persona()
        for _ in range(3):
            self._aviso_de_rebill(uid, "sub_xyz")
        self.assertEqual(len(self._filas(uid)), 1)

    def test_una_suscripcion_DISTINTA_sí_crea_su_fila(self):
        """El contraveneno, y es el que importa: el arreglo NO puede tapar una
        suscripción de verdad. Si el id es otro, es otro cobro y tiene que
        existir — confundirlos sería perder plata de vista."""
        uid = self._persona()
        self._aviso_de_rebill(uid, "sub_uno")
        self._aviso_de_rebill(uid, "sub_dos")
        sids = {f["sid"] for f in self._filas(uid)}
        self.assertEqual(sids, {"sub_uno", "sub_dos"})

    def test_sigue_usando_la_fila_pendiente_del_checkout(self):
        """El camino normal no se rompe: la fila 'pending' que deja
        /api/billing/subscribe se convierte en 'authorized' en vez de quedar
        huérfana al lado de una nueva."""
        uid = self._persona()
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, mp_subscription_id, status, "
            "  external_reference, period, amount_ars) "
            "VALUES (?,'','pending',?,'monthly',0)",
            (uid, f"rendi-{uid}-plus-monthly"))
        self.conn.commit()

        self._aviso_de_rebill(uid, "sub_nueva")
        filas = self._filas(uid)
        self.assertEqual(len(filas), 1, "quedó la pending Y una nueva")
        self.assertEqual(filas[0]["sid"], "sub_nueva")
        self.assertEqual(filas[0]["status"], "authorized")

    def test_el_monto_no_se_pierde_con_un_aviso_sin_monto(self):
        """⭐ La otra mitad del mismo bug: un aviso de "cambió el plan" no trae
        monto cobrado. No puede pisar con 0 el monto que ya estaba."""
        uid = self._persona()
        self._aviso_de_rebill(uid, "sub_m", monto=8900)
        self.assertEqual(self._filas(uid)[0]["amount_ars"], 8900)

        self._aviso_de_rebill(uid, "sub_m")        # sin monto
        self.assertEqual(
            self._filas(uid)[0]["amount_ars"], 8900,
            "un aviso sin monto borró lo que esa persona paga")


class LaLimpiezaDeLasCopias(Base):

    def _copias(self, uid, sid, n, estado="authorized"):
        for i in range(n):
            self.conn.execute(
                "INSERT INTO subscriptions (user_id, mp_subscription_id, status, "
                "  external_reference, period, amount_ars, created_at) "
                "VALUES (?,?,?,?,'monthly',0,?)",
                (uid, sid, estado, f"rendi-{uid}-plus-monthly",
                 f"2026-10-1{i} 10:00:00"))
        self.conn.commit()

    def test_por_defecto_NO_borra_nada(self):
        """Una limpieza que borra sin que se la pida es la que nadie quiere
        correr dos veces."""
        jefe = self._persona(admin=1)
        uid = self._persona()
        self._copias(uid, "sub_dup", 3)

        r = self.client.post("/api/admin/billing/dedup-suscripciones",
                             headers={"Authorization": f"Bearer {main.create_token(jefe)}"})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertFalse(d["aplicado"])
        self.assertEqual(d["filas_a_borrar"], 2)
        self.assertEqual(len(self._filas(uid)), 3, "borró sin que se lo pidieran")

    def test_con_apply_deja_UNA_y_es_la_MAS_VIEJA(self):
        jefe = self._persona(admin=1)
        uid = self._persona()
        self._copias(uid, "sub_dup", 3)
        antes = self._filas(uid)

        r = self.client.post("/api/admin/billing/dedup-suscripciones?apply=1",
                             headers={"Authorization": f"Bearer {main.create_token(jefe)}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["aplicado"])

        quedan = self._filas(uid)
        self.assertEqual(len(quedan), 1)
        self.assertEqual(quedan[0]["id"], antes[0]["id"],
                         "se quedó con una copia en vez de con el alta original")

    def test_NO_toca_suscripciones_con_ids_DISTINTOS(self):
        """El contraveneno de la limpieza: dos ids distintos son dos cobros
        reales. Borrar uno sería borrar plata."""
        jefe = self._persona(admin=1)
        uid = self._persona()
        self._copias(uid, "sub_a", 1)
        self._copias(uid, "sub_b", 1)

        r = self.client.post("/api/admin/billing/dedup-suscripciones?apply=1",
                             headers={"Authorization": f"Bearer {main.create_token(jefe)}"})
        self.assertEqual(r.json()["filas_a_borrar"], 0)
        self.assertEqual(len(self._filas(uid)), 2)

    def test_con_estados_MEZCLADOS_conserva_la_que_MANDA(self):
        """⭐ El caso que casi se va al bombo. La regla era "conservá la más
        vieja", y con copias todas 'authorized' daba igual. Pero el panel mostró
        un grupo donde las copias NO comparten estado: ahí la más vieja podía ser
        la 'cancelled' y se habría borrado la 'authorized' — dejando a alguien
        que paga figurando como que no paga.

        Ahora manda el ESTADO (mismo orden de prioridad que `/api/auth/me`) y
        recién a igualdad decide la fecha."""
        jefe = self._persona(admin=1)
        uid = self._persona()
        # La vieja está CANCELADA y la nueva ACTIVA: es el orden peligroso.
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, mp_subscription_id, status, "
            "  external_reference, period, amount_ars, created_at) "
            "VALUES (?,'sub_mix','cancelled',?,'monthly',0,'2026-07-09 17:03:30')",
            (uid, f"rendi-{uid}-plus-monthly"))
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, mp_subscription_id, status, "
            "  external_reference, period, amount_ars, created_at) "
            "VALUES (?,'sub_mix','authorized',?,'monthly',8900,'2026-10-15 17:55:00')",
            (uid, f"rendi-{uid}-plus-monthly"))
        self.conn.commit()

        h = {"Authorization": f"Bearer {main.create_token(jefe)}"}
        previo = self.client.post("/api/admin/billing/dedup-suscripciones",
                                  headers=h).json()
        # El preview tiene que MOSTRAR los estados, o no se puede revisar a ojo.
        self.assertEqual(previo["detalle"][0]["estados"],
                         ["authorized", "cancelled"])

        self.client.post("/api/admin/billing/dedup-suscripciones?apply=1", headers=h)
        quedan = self._filas(uid)
        self.assertEqual(len(quedan), 1)
        self.assertEqual(
            quedan[0]["status"], "authorized",
            "borró la ficha ACTIVA y dejó la cancelada: esa persona pasa a "
            "figurar como que no paga")
        self.assertEqual(quedan[0]["amount_ars"], 8900)

    def test_a_igualdad_de_estado_sigue_ganando_la_mas_vieja(self):
        """El contraveneno: el arreglo no puede cambiar el caso normal, que es
        el que vimos en producción (3 copias, todas 'authorized')."""
        jefe = self._persona(admin=1)
        uid = self._persona()
        self._copias(uid, "sub_dup", 3)
        antes = self._filas(uid)
        self.client.post("/api/admin/billing/dedup-suscripciones?apply=1",
                         headers={"Authorization": f"Bearer {main.create_token(jefe)}"})
        quedan = self._filas(uid)
        self.assertEqual(len(quedan), 1)
        self.assertEqual(quedan[0]["id"], antes[0]["id"])

    def test_es_solo_para_admin(self):
        uid = self._persona()
        r = self.client.post("/api/admin/billing/dedup-suscripciones",
                             headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        self.assertEqual(r.status_code, 403)

    def test_correrla_dos_veces_no_rompe(self):
        jefe = self._persona(admin=1)
        uid = self._persona()
        self._copias(uid, "sub_dup", 3)
        h = {"Authorization": f"Bearer {main.create_token(jefe)}"}
        self.client.post("/api/admin/billing/dedup-suscripciones?apply=1", headers=h)
        segunda = self.client.post("/api/admin/billing/dedup-suscripciones?apply=1",
                                   headers=h)
        self.assertEqual(segunda.status_code, 200)
        self.assertEqual(segunda.json()["filas_a_borrar"], 0)
        self.assertEqual(len(self._filas(uid)), 1)


if __name__ == "__main__":
    unittest.main()
