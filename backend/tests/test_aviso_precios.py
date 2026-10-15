"""El aviso de que cambiaron los precios: a quién se le muestra y UNA sola vez.

Nico lo pidió así, y marcó de entrada los dos riesgos reales:

  1. ⭐ QUE NO LO VEA EL QUE ESTÁ EN LA PRUEBA. En Rendi, quien está probando
     tiene `tier` 'pro' o 'plus' IGUAL que quien paga — el tier sale del crédito,
     no de la tarjeta. Preguntar por el tier le avisaría de un aumento a alguien
     que nunca pagó nada, que es la peor manera de arrancar una prueba.
  2. ⭐ QUE NO SALGA VARIAS VECES. Es el bug clásico de estos avisos. La marca
     vive en la BASE y no en el navegador justamente por eso: con `localStorage`
     vuelve a aparecer en cada dispositivo, cada navegador y cada incógnito.

Y uno que no estaba pedido pero sale del mismo lugar: el plan REGALADO desde
admin tampoco paga, así que tampoco corresponde avisarle de un cambio de precio.

Corre con: cd backend && python3 -m pytest tests/test_aviso_precios.py
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

import main                                              # noqa: E402
from billing import subscriptions as subs                 # noqa: E402
from billing import trial as tr                           # noqa: E402


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
        for t in ("credit_ledger", "subscriptions", "trial_consumed",
                  "trial_email_log", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        for var in ("TRIALS_ENABLED", "TRIALS_MONTHLY_CAP", "PAYWALL_NUEVOS"):
            os.environ.pop(var, None)
        from billing import emails as _em
        self._orig = {}
        for fn in ("send_trial_started", "send_welcome_free"):
            if hasattr(_em, fn):
                self._orig[fn] = getattr(_em, fn)
                setattr(_em, fn, lambda **kw: True)

    def tearDown(self):
        from billing import emails as _em
        for fn, orig in getattr(self, "_orig", {}).items():
            setattr(_em, fn, orig)
        try:
            self.conn.rollback()
        except Exception:
            pass
        self.conn.close()

    # ── el mundo ────────────────────────────────────────────────────────────

    def _persona(self, tier=None):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
            "VALUES (?,?,1,1,?)",
            (f"{uuid.uuid4().hex[:8]}@rendi.test", "x", tier))
        self.conn.commit()
        return cur.lastrowid

    def _paga(self, uid, plan="plus"):
        """Una suscripción COBRADA y viva: fila en `subscriptions` con estado
        authorized + la plata en el ledger. Es el alta que usa el resto de la
        suite (`test_billing_trial`)."""
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, status, external_reference, "
            "                           period, amount_ars, created_at) "
            "VALUES (?, 'authorized', ?, 'monthly', 8900, ?)",
            (uid, f"rendi-{uid}-{plan}-monthly", ts))
        self.conn.execute(
            "INSERT INTO credit_ledger (user_id, kind, amount_usd, days_delta, "
            "                           created_at) "
            "VALUES (?, 'payment', 6.0, 30, ?)", (uid, ts))
        self.conn.execute("UPDATE users SET tier=? WHERE id=?", (plan, uid))
        self.conn.commit()

    def _headers(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _ve(self, uid):
        return subs.debe_ver_aviso_precios(self.conn, uid)


class QuienLoVe(Base):

    def test_el_que_paga_plus_lo_ve(self):
        uid = self._persona()
        self._paga(uid, "plus")
        self.assertTrue(self._ve(uid))

    def test_el_que_paga_pro_lo_ve(self):
        uid = self._persona()
        self._paga(uid, "pro")
        self.assertTrue(self._ve(uid))

    def test_EL_QUE_ESTA_EN_LA_PRUEBA_NO_LO_VE(self):
        """⭐ El riesgo que marcó Nico. Su tier es 'pro' igual que el de alguien
        que paga —se lo da el crédito de la prueba— pero no pagó nada todavía."""
        uid = self._persona()
        self.assertTrue(tr.start(self.conn, uid).get("ok"))
        from ai import quota
        self.assertEqual(quota.get_tier(self.conn, uid), "pro",
                         "el montaje no reproduce el caso: su tier tiene que ser pro")
        self.assertFalse(
            self._ve(uid),
            "le estamos avisando de un aumento a alguien que está en la prueba")

    def test_el_free_no_lo_ve(self):
        uid = self._persona()
        self.assertFalse(self._ve(uid))

    def test_el_plan_REGALADO_no_lo_ve(self):
        """Tier pro puesto a mano desde admin, sin suscripción: no se le cobra
        nada, así que un cambio de precio no le dice nada."""
        uid = self._persona(tier="pro")
        self.conn.execute(
            "UPDATE users SET credit_active_until=? WHERE id=?",
            ((datetime.utcnow() + timedelta(days=90)).isoformat(), uid))
        self.conn.commit()
        self.assertFalse(self._ve(uid))


class UnaSolaVez(Base):
    """⭐ El otro riesgo que marcó Nico."""

    def test_despues_de_verlo_no_vuelve(self):
        uid = self._persona()
        self._paga(uid)
        self.assertTrue(self._ve(uid))
        subs.marcar_aviso_precios_visto(self.conn, uid)
        self.assertFalse(self._ve(uid), "el aviso vuelve a aparecer")

    def test_marcarlo_dos_veces_no_pisa_la_fecha(self):
        """Doble click, o dos pestañas abiertas. La fecha que queda es la de la
        PRIMERA vez que lo vio, no la del último intento."""
        uid = self._persona()
        self._paga(uid)
        subs.marcar_aviso_precios_visto(self.conn, uid)
        primera = self.conn.execute(
            f"SELECT {subs.AVISO_PRECIOS_COL} c FROM users WHERE id=?",
            (uid,)).fetchone()["c"]
        subs.marcar_aviso_precios_visto(self.conn, uid)
        segunda = self.conn.execute(
            f"SELECT {subs.AVISO_PRECIOS_COL} c FROM users WHERE id=?",
            (uid,)).fetchone()["c"]
        self.assertEqual(primera, segunda)

    def test_la_marca_NO_depende_del_navegador(self):
        """La razón por la que esto vive en la base: la marca es de la PERSONA.
        Se comprueba leyéndola de la tabla, que es lo que ve cualquier
        dispositivo con el que entre después."""
        uid = self._persona()
        self._paga(uid)
        subs.marcar_aviso_precios_visto(self.conn, uid)
        row = self.conn.execute(
            f"SELECT {subs.AVISO_PRECIOS_COL} c FROM users WHERE id=?",
            (uid,)).fetchone()
        self.assertTrue(row["c"], "la marca no quedó guardada en la base")


class PorElCaminoReal(Base):
    """Por los endpoints, que es como lo consume la pantalla."""

    def test_me_manda_la_bandera_y_el_post_la_apaga(self):
        uid = self._persona()
        self._paga(uid)

        r = self.client.get("/api/auth/me", headers=self._headers(uid))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("aviso_precios"),
                        "la pantalla no se entera de que hay que avisar")

        p = self.client.post("/api/me/aviso-precios-visto",
                             headers=self._headers(uid))
        self.assertEqual(p.status_code, 200, p.text)

        r2 = self.client.get("/api/auth/me", headers=self._headers(uid))
        self.assertFalse(r2.json().get("aviso_precios"),
                         "después de marcarlo visto, /me lo sigue pidiendo")

    def test_al_free_me_le_dice_que_no(self):
        uid = self._persona()
        r = self.client.get("/api/auth/me", headers=self._headers(uid))
        self.assertFalse(r.json().get("aviso_precios"))

    def test_sin_sesion_no_se_puede_marcar(self):
        self.assertEqual(
            self.client.post("/api/me/aviso-precios-visto").status_code, 401)


class ElPanelQueLePREGUNTAaRebill(Base):
    """`/api/admin/billing/precios-rebill`.

    Existe por una pregunta que Rendi no podía contestar: editar el precio de un
    plan en el dashboard de Rebill, ¿alcanza a las suscripciones que YA estaban?
    Rendi nunca manda un monto —el link lleva sólo el id del plan—, así que el
    número vive del lado de Rebill y desde la app era invisible. El panel
    compara, fila por fila, lo que Rendi registró al dar de alta contra lo que
    Rebill contesta hoy."""

    def _admin(self):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   is_admin) VALUES (?,?,1,1,1)",
            (f"jefe{uuid.uuid4().hex[:6]}@rendi.test", "x"))
        self.conn.commit()
        return cur.lastrowid

    def test_es_solo_para_admin(self):
        uid = self._persona()
        self._paga(uid)
        r = self.client.get("/api/admin/billing/precios-rebill",
                            headers=self._headers(uid))
        self.assertEqual(r.status_code, 403, r.text)

    def test_dice_los_precios_nuevos_y_lista_las_activas(self):
        jefe = self._admin()
        uid = self._persona()
        self._paga(uid, "plus")

        r = self.client.get("/api/admin/billing/precios-rebill",
                            headers=self._headers(jefe))
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()

        # Los 4 montos salen de billing/pricing.py, no escritos en el endpoint.
        from billing import pricing as planes
        self.assertEqual(d["plan_nuevo"], {
            "plus_mensual": planes.PLUS_ARS_MONTHLY_TOTAL,
            "plus_anual": planes.PLUS_ARS_ANNUAL_TOTAL,
            "pro_mensual": planes.ARS_MONTHLY_TOTAL,
            "pro_anual": planes.ARS_ANNUAL_TOTAL,
        })

        emails = [x["email"] for x in d["suscripciones"]]
        self.assertEqual(len(emails), 1, "no listó la suscripción activa")
        fila = d["suscripciones"][0]
        self.assertEqual(fila["registrado_en_rendi"], 8900)

    def test_si_rebill_no_contesta_la_fila_lo_dice_y_no_revienta(self):
        """Sin clave de API —como en los tests— cada fila tiene que reportar su
        error, no tirar abajo el panel entero. Un diagnóstico que se cae cuando
        hay un problema es justo el que no sirve."""
        jefe = self._admin()
        uid = self._persona()
        self._paga(uid)
        r = self.client.get("/api/admin/billing/precios-rebill",
                            headers=self._headers(jefe))
        self.assertEqual(r.status_code, 200, r.text)
        fila = r.json()["suscripciones"][0]
        self.assertTrue(fila["error"] or fila["rebill_dice"],
                        "ni contestó ni dijo por qué no")

    def test_no_devuelve_ninguna_credencial(self):
        jefe = self._admin()
        cuerpo = self.client.get("/api/admin/billing/precios-rebill",
                                 headers=self._headers(jefe)).text.lower()
        for secreto in ("sk_test", "sk_live", "api_key", "x-api-key"):
            self.assertNotIn(secreto, cuerpo)


if __name__ == "__main__":
    unittest.main()
