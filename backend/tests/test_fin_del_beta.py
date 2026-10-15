"""1/11/2026: darle la prueba de 20 días a los ~1.300 que ya estaban.

Hasta hoy la prueba arranca sola al verificar el mail y nada más. Esto es la
herramienta de UNA VEZ para el día que Rendi sale del beta, y lo que hay que
blindar no es "¿anda?" sino "¿a quién toca y en qué orden?".

Los dos riesgos, y el primero es de los caros:

  1. ⭐ EL ORDEN. Si se pone la marca de "tiene que elegir plan" ANTES de que la
     prueba arranque, esa persona entra a Rendi y se encuentra el muro EL DÍA 1,
     sin un solo día de prueba. Ya pasó en producción en septiembre con un caso
     suelto; acá serían 1.300 a la vez. Por eso la marca se escribe SÓLO si la
     prueba arrancó, y hay un test que lo fuerza a fallar para comprobarlo.
  2. ⭐ A QUIÉN NO TOCAR. Al que paga, al asesor, al del plan regalado, al que
     ya está probando y al cliente de un asesor. A cualquiera de ellos, arrancar
     una prueba le pisaría el crédito que está usando.

Y la decisión de Nico del 15/10 — «prueba para todos»: la marca de "esta casilla
ya usó su prueba" se borra, porque existe para que nadie la repita BORRÁNDOSE LA
CUENTA, no para castigar a los que probaron Rendi durante el beta.

Corre con: cd backend && python3 -m pytest tests/test_fin_del_beta.py
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
from ai import quota                                      # noqa: E402
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

    # ── el mundo del beta ───────────────────────────────────────────────────

    def _del_beta(self, *, verificado=1, admin=0, managed_by=None, tier=None):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   is_admin, managed_by, tier, requires_plan) "
            "VALUES (?,?,1,?,?,?,?,0)",
            (f"{uuid.uuid4().hex[:8]}@rendi.test", "x", verificado, admin,
             managed_by, tier))
        self.conn.commit()
        return cur.lastrowid

    def _paga(self, uid):
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, status, external_reference, "
            "  period, amount_ars, created_at) "
            "VALUES (?, 'authorized', ?, 'monthly', 8900, ?)",
            (uid, f"rendi-{uid}-plus-monthly", ts))
        self.conn.execute("UPDATE users SET tier='plus' WHERE id=?", (uid,))
        self.conn.commit()

    def _con_credito(self, uid, plan="pro", dias=90):
        """Plan regalado desde admin: tier + crédito, sin suscripción."""
        self.conn.execute(
            "UPDATE users SET tier=?, credit_active_until=? WHERE id=?",
            (plan, (datetime.utcnow() + timedelta(days=dias)).isoformat(), uid))
        self.conn.commit()

    def _marca(self, uid):
        return self.conn.execute(
            "SELECT COALESCE(requires_plan,0) c FROM users WHERE id=?",
            (uid,)).fetchone()["c"]

    def _tiene_prueba(self, uid):
        return self.conn.execute(
            "SELECT trial_started_at FROM users WHERE id=?",
            (uid,)).fetchone()["trial_started_at"] is not None


class LaVistaPrevia(Base):

    def test_por_defecto_NO_escribe_nada(self):
        uid = self._del_beta()
        d = tr.fin_del_beta(self.conn)
        self.assertFalse(d["aplicado"])
        self.assertEqual(d["les_arranca_la_prueba"], 1)
        self.assertFalse(self._tiene_prueba(uid), "arrancó la prueba sin que se lo pidieran")
        self.assertEqual(self._marca(uid), 0, "puso la marca sin que se lo pidieran")

    def test_dice_los_dias_que_va_a_dar(self):
        self.assertEqual(tr.fin_del_beta(self.conn)["dias_de_prueba"],
                         tr.TRIAL_TOTAL_DAYS)


class AQuienLeArranca(Base):

    def test_al_del_beta_le_arranca_la_prueba_Y_le_pone_la_marca(self):
        uid = self._del_beta()
        tr.fin_del_beta(self.conn, apply=True)
        self.assertTrue(self._tiene_prueba(uid))
        self.assertEqual(self._marca(uid), 1)
        self.assertEqual(quota.get_tier(self.conn, uid), "pro",
                         "arranca en Pro, como cualquier prueba")

    def test_y_NO_queda_en_pausa_el_dia_1(self):
        """⭐ Lo que de verdad se está comprando con el orden: que al entrar vea
        Rendi y no el muro."""
        uid = self._del_beta()
        tr.fin_del_beta(self.conn, apply=True)
        self.assertFalse(
            main.cuenta_en_pausa(self.conn, uid),
            "le pusimos la marca sin prueba: se come el muro el día 1")

    def test_al_que_YA_PROBÓ_en_el_beta_tambien(self):
        """⭐ «Prueba para todos» (Nico, 15/10). `trial_consumed` sobrevive a
        todo —para eso existe— así que hay que borrarle la marca o su prueba no
        arranca y la marca de plan lo manda al muro."""
        uid = self._del_beta()
        self.assertTrue(tr.start(self.conn, uid).get("ok"))      # su prueba vieja
        # Se le vence y vuelve a free, como los ~20 del beta.
        atras = timedelta(days=tr.TRIAL_TOTAL_DAYS + 30)
        row = self.conn.execute(
            "SELECT trial_started_at, credit_active_until, trial_ends_at "
            "FROM users WHERE id=?", (uid,)).fetchone()
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, credit_active_until=?, "
            "                 trial_ends_at=?, tier='free', requires_plan=0 WHERE id=?",
            ((datetime.fromisoformat(row["trial_started_at"]) - atras).isoformat(),
             (datetime.fromisoformat(row["credit_active_until"]) - atras).isoformat(),
             (datetime.fromisoformat(row["trial_ends_at"]) - atras).isoformat(), uid))
        self.conn.commit()
        self.assertEqual(quota.get_tier(self.conn, uid), "free")

        d = tr.fin_del_beta(self.conn, apply=True)
        self.assertEqual(d["fallaron"], [], f"no le arrancó la prueba: {d['fallaron']}")
        self.assertEqual(quota.get_tier(self.conn, uid), "pro")
        self.assertFalse(main.cuenta_en_pausa(self.conn, uid))

    def test_al_que_no_verifico_el_mail_le_pone_la_marca_SIN_quemar_la_prueba(self):
        """Arrancársela ahora le quemaría los 20 días sin que entre nunca.
        `verify_email` se la arranca el día que aparezca — el camino que ya
        existe para cualquiera que se registra."""
        uid = self._del_beta(verificado=0)
        d = tr.fin_del_beta(self.conn, apply=True)
        self.assertEqual(d["marca_sin_prueba_por_no_verificar"], 1)
        self.assertFalse(self._tiene_prueba(uid))
        self.assertEqual(self._marca(uid), 1)


class AQuienNoToca(Base):

    def test_al_que_PAGA_no_lo_toca(self):
        uid = self._del_beta()
        self._paga(uid)
        d = tr.fin_del_beta(self.conn, apply=True)
        self.assertEqual(d["salteados"]["paga"], 1)
        self.assertFalse(self._tiene_prueba(uid))
        self.assertEqual(self._marca(uid), 0)

    def test_al_del_plan_REGALADO_no_lo_toca(self):
        """Tier pro por crédito de admin, sin suscripción: arrancarle una prueba
        le pisaría el crédito que está usando."""
        uid = self._del_beta()
        self._con_credito(uid)
        d = tr.fin_del_beta(self.conn, apply=True)
        self.assertEqual(d["salteados"]["no_es_free"], 1)
        self.assertFalse(self._tiene_prueba(uid))

    def test_al_ADMIN_no_lo_toca(self):
        uid = self._del_beta(admin=1)
        d = tr.fin_del_beta(self.conn, apply=True)
        self.assertEqual(d["salteados"]["admin"], 1)
        self.assertEqual(self._marca(uid), 0)

    def test_al_CLIENTE_DE_UN_ASESOR_no_lo_toca(self):
        """El plan lo paga el asesor; el cliente no tiene que elegir nada. Es la
        misma excepción que ya hace el muro (`main.cuenta_en_pausa`)."""
        asesor = self._del_beta()
        uid = self._del_beta(managed_by=asesor)
        d = tr.fin_del_beta(self.conn, apply=True)
        self.assertEqual(d["salteados"]["cliente_de_asesor"], 1)
        self.assertEqual(self._marca(uid), 0)

    def test_al_que_YA_ESTA_PROBANDO_no_le_reinicia_la_prueba(self):
        uid = self._del_beta()
        self.assertTrue(tr.start(self.conn, uid).get("ok"))
        antes = self.conn.execute(
            "SELECT trial_ends_at FROM users WHERE id=?", (uid,)).fetchone()[0]
        tr.fin_del_beta(self.conn, apply=True)
        despues = self.conn.execute(
            "SELECT trial_ends_at FROM users WHERE id=?", (uid,)).fetchone()[0]
        self.assertEqual(antes, despues, "le reinició la prueba que estaba corriendo")


class SePuedeCorrerDosVeces(Base):

    def test_la_segunda_corrida_no_reinicia_nada(self):
        uid = self._del_beta()
        tr.fin_del_beta(self.conn, apply=True)
        fin1 = self.conn.execute(
            "SELECT trial_ends_at FROM users WHERE id=?", (uid,)).fetchone()[0]

        d2 = tr.fin_del_beta(self.conn, apply=True)
        fin2 = self.conn.execute(
            "SELECT trial_ends_at FROM users WHERE id=?", (uid,)).fetchone()[0]
        self.assertEqual(fin1, fin2, "la segunda corrida le dio 20 días más")
        self.assertEqual(d2["salteados"]["ya_tenia_la_marca"], 1)
        self.assertEqual(d2["les_arranca_la_prueba"], 0)


class SiLaPruebaNoArranca(Base):
    """⭐ El test que protege el ORDEN, y la única forma de probarlo es romper
    el arranque a propósito."""

    def test_si_start_falla_NO_se_pone_la_marca(self):
        uid = self._del_beta()
        original = tr.start
        try:
            tr.start = lambda conn, user_id, **kw: {"ok": False, "reason": "roto"}
            d = tr.fin_del_beta(self.conn, apply=True)
        finally:
            tr.start = original

        self.assertEqual(len(d["fallaron"]), 1)
        self.assertEqual(
            self._marca(uid), 0,
            "puso la marca sin prueba: esa persona se come el muro el día 1")
        self.assertFalse(main.cuenta_en_pausa(self.conn, uid))


class PorLaPuertaReal(Base):

    def _admin(self):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   is_admin, requires_plan) VALUES (?,?,1,1,1,0)",
            (f"jefe{uuid.uuid4().hex[:6]}@rendi.test", "x"))
        self.conn.commit()
        return cur.lastrowid

    def test_es_solo_para_admin(self):
        uid = self._del_beta()
        r = self.client.post("/api/admin/billing/fin-del-beta",
                             headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        self.assertEqual(r.status_code, 403)

    def test_el_endpoint_no_aplica_sin_que_se_lo_pidan(self):
        jefe = self._admin()
        uid = self._del_beta()
        h = {"Authorization": f"Bearer {main.create_token(jefe)}"}
        r = self.client.post("/api/admin/billing/fin-del-beta", headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["aplicado"])
        self.assertEqual(self._marca(uid), 0)

        r2 = self.client.post("/api/admin/billing/fin-del-beta?apply=1", headers=h)
        self.assertTrue(r2.json()["aplicado"])
        self.assertEqual(self._marca(uid), 1)


if __name__ == "__main__":
    unittest.main()
