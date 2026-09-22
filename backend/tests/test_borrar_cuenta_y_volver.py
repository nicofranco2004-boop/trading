"""Borrar la cuenta NO puede ser la forma de resetear la prueba.

La pregunta que este archivo contesta, tal cual la hizo Nico: si alguien
termina sus 20 días, borra la cuenta y se registra de nuevo, ¿puede volver a
arrancar la prueba? Si pudiera, la prueba sería infinita y el paywall no
existiría — bastaría con borrarse cada 20 días.

La defensa ya está puesta y es de un audit anterior: la marca de "esta casilla
ya usó su prueba" vive en `trial_consumed`, una tabla con `email_key` y NADA
más. El borrado de cuenta barre dinámicamente toda tabla que tenga una columna
`user_id`, así que a ésta ni la mira. Este archivo la prueba POR EL CAMINO
REAL —`DELETE /api/me` con el cliente HTTP— y no leyendo el código: la tabla
podría ganar una columna `user_id` mañana y el barrido se la llevaría sin que
nada avise.

Y prueba la contracara, que es lo que hace que la defensa sea aceptable: que
la cuenta en pausa SE PUEDA BORRAR. Si no, alguien que no quiere pagar queda
atrapado —no puede usar Rendi ni irse— y eso no es una decisión de cobranza,
es no poder ejercer el derecho a borrar sus datos.

Corre con: cd backend && python3 -m pytest tests/test_borrar_cuenta_y_volver.py
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

import main                                      # noqa: E402
from ai import quota                              # noqa: E402
from billing import trial as tr                   # noqa: E402


def _iso(dt):
    return dt.isoformat()


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
                  "trial_email_log", "ai_usage_daily", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        for var in ("TRIALS_ENABLED", "TRIALS_MONTHLY_CAP", "PAYWALL_NUEVOS"):
            os.environ.pop(var, None)
        from billing import emails as _em
        self._orig = {}
        for fn in ("send_trial_started", "send_trial_pro_ending",
                   "send_trial_ending_soon", "send_trial_ended",
                   "send_welcome_free"):
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

    # ── helpers ─────────────────────────────────────────────────────────────

    def _alta(self, email, *, requires_plan=1):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   requires_plan) VALUES (?,?,1,1,?)",
            (email, "x", requires_plan))
        self.conn.commit()
        return cur.lastrowid

    def _headers(self, uid):
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _terminar_la_prueba(self, uid):
        """Mueve las TRES fechas para que la prueba haya vencido ayer."""
        atras = timedelta(days=tr.TRIAL_TOTAL_DAYS + 1)
        row = self.conn.execute(
            "SELECT trial_started_at, credit_active_until, trial_ends_at "
            "FROM users WHERE id=?", (uid,)).fetchone()
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, credit_active_until=?, "
            "                 trial_ends_at=? WHERE id=?",
            (_iso(datetime.fromisoformat(row["trial_started_at"]) - atras),
             _iso(datetime.fromisoformat(row["credit_active_until"]) - atras),
             _iso(datetime.fromisoformat(row["trial_ends_at"]) - atras), uid))
        self.conn.commit()


class BorrarYVolverAEmpezar(Base):
    """El recorrido completo del que quiere una prueba infinita."""

    EMAIL = "vuelve@rendi.test"

    def test_no_puede_arrancar_la_prueba_de_nuevo(self):
        # 1. Se registra, usa su prueba entera y se le termina.
        uid = self._alta(self.EMAIL)
        self.assertTrue(tr.start(self.conn, uid).get("ok"))
        self._terminar_la_prueba(uid)
        self.assertTrue(main.cuenta_en_pausa(self.conn, uid))

        # 2. BORRA LA CUENTA por el camino real (el endpoint, no un DELETE a mano).
        r = self.client.delete("/api/me", headers=self._headers(uid))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(
            self.conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone(),
            "la cuenta no se borró de verdad")

        # 3. Se registra otra vez con EL MISMO mail.
        nuevo = self._alta(self.EMAIL)
        self.assertNotEqual(nuevo, uid)

        # 4. Y la prueba NO le arranca: acá está el negocio.
        res = tr.start(self.conn, nuevo)
        self.assertFalse(res.get("ok"),
                         "prueba infinita: borrar la cuenta reseteó el límite")
        self.assertEqual(res.get("reason"), "already_used")
        self.assertEqual(quota.get_tier(self.conn, nuevo), "free")
        self.assertTrue(main.cuenta_en_pausa(self.conn, nuevo))

    def test_la_marca_sobrevive_al_borrado(self):
        """La defensa concreta: `trial_consumed` no tiene columna `user_id`, así
        que el barrido dinámico del borrado no la alcanza. Si alguien le agrega
        esa columna, el barrido se la lleva y este test se pone rojo."""
        uid = self._alta("marca@rendi.test")
        tr.start(self.conn, uid)
        antes = self.conn.execute("SELECT COUNT(*) c FROM trial_consumed").fetchone()["c"]
        self.assertGreater(antes, 0, "activar la prueba no dejó la marca")

        self.client.delete("/api/me", headers=self._headers(uid))
        despues = self.conn.execute("SELECT COUNT(*) c FROM trial_consumed").fetchone()["c"]
        self.assertEqual(despues, antes, "el borrado de cuenta se llevó la marca")

    def test_con_un_alias_del_mismo_mail_tampoco(self):
        """`normalizar_email` trata al +alias y a los puntos de Gmail como la
        misma bandeja, así que el atajo obvio tampoco funciona."""
        uid = self._alta("persona@gmail.com")
        tr.start(self.conn, uid)
        self.client.delete("/api/me", headers=self._headers(uid))

        otro = self._alta("per.sona+loquesea@gmail.com")
        res = tr.start(self.conn, otro)
        self.assertFalse(res.get("ok"), "el +alias saltó el límite")
        self.assertEqual(res.get("reason"), "already_used")


class LaCuentaEnPausaSePuedeBorrar(Base):
    """La contracara, y es lo que hace aceptable a todo lo de arriba.

    El muro corta en `get_effective_user`, por donde pasan TODOS los endpoints
    de datos — y `DELETE /api/me` es uno de ellos. Sin una excepción explícita,
    quien no quiere pagar queda atrapado: no puede usar Rendi NI irse. Eso ya
    no es una decisión de cobranza; es impedirle borrar sus propios datos."""

    def test_puede_borrarse_estando_en_pausa(self):
        uid = self._alta("mequiero@rendi.test")
        tr.start(self.conn, uid)
        self._terminar_la_prueba(uid)
        self.assertTrue(main.cuenta_en_pausa(self.conn, uid))

        r = self.client.delete("/api/me", headers=self._headers(uid))
        self.assertNotEqual(
            r.status_code, main.CUENTA_EN_PAUSA,
            "la cuenta en pausa no se puede borrar: queda atrapada")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(
            self.conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone())

    def test_lo_demas_de_api_me_SIGUE_bloqueado(self):
        """La excepción es para BORRARSE, no para `/api/me/*` entero: borrar los
        datos y seguir usando la app son cosas distintas."""
        uid = self._alta("reset@rendi.test")
        tr.start(self.conn, uid)
        self._terminar_la_prueba(uid)
        r = self.client.post("/api/me/reset-data", headers=self._headers(uid))
        self.assertEqual(r.status_code, main.CUENTA_EN_PAUSA, r.text)


if __name__ == "__main__":
    unittest.main()
