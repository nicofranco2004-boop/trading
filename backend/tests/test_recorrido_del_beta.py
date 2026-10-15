"""El camino completo de alguien del BETA: del 1/11 al muro, día por día.

`test_prueba_de_punta_a_punta` camina los 21 días de alguien que SE REGISTRA.
Esto camina los de alguien que YA ESTABA y recibe la prueba por la herramienta
del fin del beta — que es otro punto de partida y por eso otro camino:

  · su prueba no la arranca `verify_email`, la arranca `fin_del_beta`;
  · puede venir con la marca de "esta casilla ya usó su prueba" de la prueba
    vieja de 15 días, y esa marca es la que lo dejaría sin nada;
  · nace con `requires_plan`, que es lo que hace que el muro le aplique.

Lo que se recorre, con el reloj corriendo de verdad:

    día 1   la herramienta le arranca la prueba → Pro, 20 días, SIN muro
    día 10  la víspera avisa que se le termina el Pro
    día 11  el cron lo baja a Plus → le llega el mail del paso, sigue sin muro
    día 18  quedan 3 → "elegí un plan"
    día 21  MURO, sin que corra ningún cron
    paga    el muro se levanta en el acto

Corre con: cd backend && python3 -m pytest tests/test_recorrido_del_beta.py
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
from billing import subscriptions as subs                 # noqa: E402


def _iso(dt):
    return dt.isoformat()


class ElCaminoDelBeta(unittest.TestCase):
    RUTA_DE_DATOS = "/api/positions"

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
        self.enviados = []
        self._orig = {}
        for fn in ("send_trial_started", "send_trial_pro_ending",
                   "send_trial_plus_started", "send_trial_ending_soon",
                   "send_trial_ended", "send_welcome_free",
                   "send_trials_ended_admin"):
            if hasattr(_em, fn):
                self._orig[fn] = getattr(_em, fn)
                setattr(_em, fn, self._espia(fn))

        # ⭐ Alguien del beta: existe hace meses, es free, y YA USÓ la prueba
        # vieja de 15 días. Es el caso difícil: su marca de "ya probó" es lo que
        # lo dejaría sin prueba Y con el muro puesto el día 1.
        cur = self.conn.execute(
            "INSERT INTO users (email, name, password_hash, approved, "
            "                   email_verified, requires_plan) "
            "VALUES (?,?,?,1,1,0)",
            (f"beta-{uuid.uuid4().hex[:6]}@rendi.test", "Beta", "x"))
        self.uid = cur.lastrowid
        self.conn.commit()
        self.assertTrue(tr.start(self.conn, self.uid).get("ok"))   # la prueba vieja
        atras = timedelta(days=200)
        r = self.conn.execute(
            "SELECT trial_started_at, credit_active_until, trial_ends_at "
            "FROM users WHERE id=?", (self.uid,)).fetchone()
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, credit_active_until=?, "
            "                 trial_ends_at=?, tier='free' WHERE id=?",
            (_iso(datetime.fromisoformat(r["trial_started_at"]) - atras),
             _iso(datetime.fromisoformat(r["credit_active_until"]) - atras),
             _iso(datetime.fromisoformat(r["trial_ends_at"]) - atras), self.uid))
        self.conn.commit()
        self.enviados.clear()

    def tearDown(self):
        from billing import emails as _em
        for fn, orig in getattr(self, "_orig", {}).items():
            setattr(_em, fn, orig)
        try:
            self.conn.rollback()
        except Exception:
            pass
        self.conn.close()

    # ── utilidades ──────────────────────────────────────────────────────────

    def _espia(self, nombre):
        def _fake(**kw):
            self.enviados.append((nombre, kw))
            return True
        return _fake

    def _mails(self):
        return [n for n, _ in self.enviados]

    def _headers(self):
        return {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _entra(self):
        return self.client.get(self.RUTA_DE_DATOS, headers=self._headers())

    def _el_1_de_noviembre(self):
        """Corre la herramienta del fin del beta, como se va a correr ese día."""
        return tr.fin_del_beta(self.conn, apply=True)

    def _estamos_en_el_dia(self, dia: int):
        atras = dia - 1
        ini = datetime.utcnow() - timedelta(days=atras)
        fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, credit_active_until=?, "
            "                 trial_ends_at=? WHERE id=?",
            (_iso(ini), _iso(fin), _iso(fin), self.uid))
        self.conn.commit()

    def _paso_del_cron(self):
        tr.step_down_due_trials(self.conn)
        tr.send_due_trial_emails(self.conn)

    # ── el camino ───────────────────────────────────────────────────────────

    def test_dia_1_arranca_en_pro_con_los_20_dias_y_SIN_muro(self):
        d = self._el_1_de_noviembre()
        self.assertEqual(d["les_arranca_la_prueba"], 1, f"no le arrancó: {d}")
        self.assertEqual(quota.get_tier(self.conn, self.uid), "pro")
        self.assertEqual(tr.status(self.conn, self.uid)["days_left"],
                         tr.TRIAL_TOTAL_DAYS)
        self.assertFalse(
            main.cuenta_en_pausa(self.conn, self.uid),
            "le pusieron la marca y se come el muro el día 1")
        self.assertEqual(self._entra().status_code, 200)
        self.assertIn("send_trial_started", self._mails(),
                      "no recibió el mail de bienvenida de su prueba")

    def test_el_dia_10_le_avisan_que_se_termina_el_pro(self):
        self._el_1_de_noviembre()
        self._estamos_en_el_dia(tr.TRIAL_PRO_DAYS)
        self.enviados.clear()
        self._paso_del_cron()
        self.assertIn("send_trial_pro_ending", self._mails())
        self.assertEqual(quota.get_tier(self.conn, self.uid), "pro",
                         "lo bajó a Plus un día antes de tiempo")

    def test_el_dia_11_pasa_a_plus_y_le_llega_el_mail_del_paso(self):
        self._el_1_de_noviembre()
        self._estamos_en_el_dia(tr.TRIAL_PRO_DAYS + 1)
        self.enviados.clear()
        self._paso_del_cron()
        self.assertEqual(quota.get_tier(self.conn, self.uid), "plus")
        self.assertIn("send_trial_plus_started", self._mails())
        self.assertFalse(main.cuenta_en_pausa(self.conn, self.uid),
                         "el muro apareció a mitad de la prueba")
        self.assertEqual(self._entra().status_code, 200)

    def test_cuando_faltan_tres_le_piden_elegir_un_plan(self):
        self._el_1_de_noviembre()
        self._estamos_en_el_dia(tr.TRIAL_TOTAL_DAYS - tr.MAIL_AVISO_DIAS_ANTES + 1)
        self.enviados.clear()
        self._paso_del_cron()
        self.assertIn("send_trial_ending_soon", self._mails())
        # Y el mail tiene que saber que esta persona NO vuelve a Free.
        kw = dict(self.enviados)["send_trial_ending_soon"]
        self.assertTrue(kw.get("requiere_plan"),
                        "el mail le dice que vuelve a Free, y queda en PAUSA")

    def test_el_dia_21_aparece_el_muro_sin_que_corra_ningun_cron(self):
        self._el_1_de_noviembre()
        self._estamos_en_el_dia(tr.TRIAL_TOTAL_DAYS + 1)
        self.assertTrue(main.cuenta_en_pausa(self.conn, self.uid))
        self.assertEqual(self._entra().status_code, main.CUENTA_EN_PAUSA)

    def test_en_pausa_igual_puede_LLEVARSE_sus_datos(self):
        """Lo que hace aceptable al muro: no lo deja atrapado con sus cosas."""
        self._el_1_de_noviembre()
        self._estamos_en_el_dia(tr.TRIAL_TOTAL_DAYS + 1)
        self.assertTrue(main.cuenta_en_pausa(self.conn, self.uid))
        r = self.client.get("/api/export/positions.csv", headers=self._headers())
        self.assertNotEqual(r.status_code, main.CUENTA_EN_PAUSA)

    def test_pagar_levanta_el_muro_en_el_acto(self):
        self._el_1_de_noviembre()
        self._estamos_en_el_dia(tr.TRIAL_TOTAL_DAYS + 1)
        self.assertTrue(main.cuenta_en_pausa(self.conn, self.uid))

        from billing import credits as billing_credits
        billing_credits.grant_payment_credit(
            self.conn, user_id=self.uid, plan="plus", period="monthly",
            amount_usd=6.0, subscription_id="sub-beta", payment_id="pay-beta")
        self.assertFalse(main.cuenta_en_pausa(self.conn, self.uid),
                         "pagó y el muro sigue puesto")
        self.assertEqual(self._entra().status_code, 200)

    def test_al_que_PAGA_a_mitad_de_camino_no_le_llega_mas_ningun_aviso(self):
        """⭐ Si pagó, los mails de "tu prueba se termina" sobran y quedan mal.
        El filtro es `credit_active_until = trial_ends_at`: al pagar, el crédito
        se extiende y esa igualdad se rompe, así que sale solo de las consultas.
        Se comprueba, no se deduce."""
        self._el_1_de_noviembre()
        self._estamos_en_el_dia(tr.TRIAL_TOTAL_DAYS - tr.MAIL_AVISO_DIAS_ANTES + 1)
        from billing import credits as billing_credits
        billing_credits.grant_payment_credit(
            self.conn, user_id=self.uid, plan="pro", period="monthly",
            amount_usd=10.0, subscription_id="sub-x", payment_id="pay-x")
        self.enviados.clear()
        self._paso_del_cron()
        self.assertNotIn("send_trial_ending_soon", self._mails(),
                         "le pide elegir un plan a alguien que ya pagó")
        self.assertNotIn("send_trial_ended", self._mails())

    def test_cada_aviso_sale_UNA_sola_vez_en_todo_el_recorrido(self):
        """El cron corre todos los días: si alguno no fuera idempotente, esta
        persona recibiría el mismo mail diez mañanas seguidas."""
        self._el_1_de_noviembre()
        for dia in range(1, tr.TRIAL_TOTAL_DAYS + 3):
            self._estamos_en_el_dia(dia)
            self._paso_del_cron()
        salieron = self._mails()
        for mail in ("send_trial_pro_ending", "send_trial_plus_started",
                     "send_trial_ending_soon", "send_trial_ended"):
            self.assertEqual(salieron.count(mail), 1,
                             f"{mail} salió {salieron.count(mail)} veces: {salieron}")


if __name__ == "__main__":
    unittest.main()
