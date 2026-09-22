"""Los 21 días de la prueba, caminados de punta a punta.

Este archivo existe porque el resto de los tests del trial prueban ESLABONES:
que el paso a Plus funciona, que tal mail sale, que el muro corta. Ninguno
camina la línea de tiempo COMPLETA, y es en el empalme donde se rompe: el día
que cambia la etapa el mail anterior ya se marcó, el crédito y `trial_ends_at`
tienen que seguir coincidiendo, y el muro tiene que aparecer justo el día
después y no antes.

Lo que se recorre, con el reloj corriendo de verdad (se mueve el arranque de la
prueba hacia atrás, que es la única forma de viajar en el tiempo acá):

    día 1   alta → Pro, 20 días, mail de bienvenida, sin muro
    día 10  la víspera → mail "mañana termina tu etapa de Pro"
    día 11  el cron baja a Plus → sigue sin muro, el vencimiento NO se acorta
    día 18  quedan 3 → mail "elegí un plan para no perder el acceso"
    día 21  MURO, sin que corra ningún cron + mail de cierre
    después paga → el muro se levanta en el acto

⚠️ El paso del cron se invoca con las dos funciones que el job diario llama
(`step_down_due_trials` y `send_due_trial_emails`) y NO con `run_lifecycle_job`
entero, porque ése además sincroniza con la pasarela por red y traba la base en
el sandbox. Que el job las llame a las dos está cubierto aparte
(`test_billing_trial.py::test_el_paso_del_cron_esta_declarado_en_el_job`), y
que el job tenga una puerta EXTERNA que lo dispare se cubre abajo — sin eso,
en Railway el cron se saltea la ventana y no sale ningún mail.

Corre con: cd backend && python3 -m pytest tests/test_prueba_de_punta_a_punta.py
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


class LaPruebaCompleta(unittest.TestCase):
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
                  "trial_email_log", "ai_usage_daily", "brokers", "users"):
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
                   "send_trial_ending_soon", "send_trial_ended",
                   "send_welcome_free", "send_trials_ended_admin"):
            if hasattr(_em, fn):
                self._orig[fn] = getattr(_em, fn)
                setattr(_em, fn, self._espia(fn))

        # El usuario de la cohorte nueva, ya verificado, con la prueba arrancada
        # como la arranca verify-email.
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "                   requires_plan) VALUES (?,?,1,1,1)",
            (f"prueba-{uuid.uuid4().hex[:8]}@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.commit()
        self.assertTrue(tr.start(self.conn, self.uid).get("ok"))

    def tearDown(self):
        from billing import emails as _em
        for fn, orig in getattr(self, "_orig", {}).items():
            setattr(_em, fn, orig)
        try:
            self.conn.rollback()
        except Exception:
            pass
        self.conn.close()

    def _espia(self, nombre):
        def _fake(**kw):
            self.enviados.append((nombre, kw))
            return True
        return _fake

    # ── el reloj ────────────────────────────────────────────────────────────

    def _estamos_en_el_dia(self, dia: int):
        """Mueve el arranque de la prueba para que HOY sea `dia`.

        Los TRES campos viajan juntos: si `trial_ends_at` deja de coincidir con
        `credit_active_until`, `step_down_due_trials` no matchea y el repro
        miente diciendo que el paso a Plus no funciona."""
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

    def _mails(self):
        return [n for n, _ in self.enviados]

    def _entra(self):
        r = self.client.get(self.RUTA_DE_DATOS,
                            headers={"Authorization": f"Bearer {main.create_token(self.uid)}"})
        return r.status_code != main.CUENTA_EN_PAUSA, r

    # ── el recorrido ────────────────────────────────────────────────────────

    def test_dia_1_arranca_en_pro_con_los_veinte_dias_y_su_mail(self):
        st = tr.status(self.conn, self.uid)
        self.assertEqual(st["stage"], "pro")
        self.assertEqual(st["days_left"], tr.TRIAL_TOTAL_DAYS)
        self.assertEqual(quota.get_tier(self.conn, self.uid), "pro")
        self.assertIn("send_trial_started", self._mails())
        self.assertNotIn("send_welcome_free", self._mails(),
                         "le llegó también el de 'bienvenido al plan gratis'")
        entra, r = self._entra()
        self.assertTrue(entra, r.text)

    def test_la_vispera_avisa_que_se_termina_la_etapa_de_pro(self):
        self.enviados.clear()
        self._estamos_en_el_dia(tr.TRIAL_PRO_DAYS)
        self._paso_del_cron()
        self.assertIn("send_trial_pro_ending", self._mails())
        self.assertEqual(quota.get_tier(self.conn, self.uid), "pro",
                         "lo bajó un día antes de lo prometido")

    def test_el_primer_dia_de_plus_baja_el_plan_y_no_acorta_el_vencimiento(self):
        antes = self.conn.execute(
            "SELECT credit_active_until c FROM users WHERE id=?", (self.uid,)
        ).fetchone()["c"]
        self._estamos_en_el_dia(tr.TRIAL_PRO_DAYS + 1)
        esperado = self.conn.execute(
            "SELECT credit_active_until c FROM users WHERE id=?", (self.uid,)
        ).fetchone()["c"]
        self._paso_del_cron()
        self.assertEqual(quota.get_tier(self.conn, self.uid), "plus")
        self.assertEqual(tr.status(self.conn, self.uid)["stage"], "plus")
        despues = self.conn.execute(
            "SELECT credit_active_until c FROM users WHERE id=?", (self.uid,)
        ).fetchone()["c"]
        self.assertEqual(despues, esperado,
                         "el paso a Plus le acortó el vencimiento de la prueba")
        self.assertNotEqual(antes, None)
        entra, r = self._entra()
        self.assertTrue(entra, "lo bloqueamos a mitad de la prueba")

    def test_cuando_faltan_tres_dias_le_pide_elegir_un_plan(self):
        self._estamos_en_el_dia(tr.TRIAL_TOTAL_DAYS - tr.MAIL_AVISO_DIAS_ANTES + 1)
        self.conn.execute("UPDATE users SET tier='plus' WHERE id=?", (self.uid,))
        self.conn.commit()
        self.enviados.clear()
        self._paso_del_cron()
        avisos = [kw for n, kw in self.enviados if n == "send_trial_ending_soon"]
        self.assertEqual(len(avisos), 1, self._mails())
        self.assertTrue(avisos[0]["requiere_plan"],
                        "el aviso le habla como si tuviera un plan gratis al que caer")
        entra, _ = self._entra()
        self.assertTrue(entra, "lo bloqueamos con la prueba todavía viva")

    def test_el_dia_despues_aparece_el_muro_sin_que_corra_ningun_cron(self):
        self._estamos_en_el_dia(tr.TRIAL_TOTAL_DAYS + 1)
        # A propósito NO se llama a _paso_del_cron: el muro lo decide
        # quota.get_tier en tiempo real. Si dependiera del cron, entre el
        # vencimiento y la corrida la cuenta seguiría abierta — y si el cron
        # falla, para siempre.
        entra, r = self._entra()
        self.assertFalse(entra, "la cuenta siguió abierta después de la prueba")
        self.assertEqual(r.json()["detail"]["code"], "plan_requerido")

    def test_y_el_cron_manda_el_mail_de_cierre_una_sola_vez(self):
        self._estamos_en_el_dia(tr.TRIAL_TOTAL_DAYS + 1)
        self.enviados.clear()
        self._paso_del_cron()
        cierres = [kw for n, kw in self.enviados if n == "send_trial_ended"]
        self.assertEqual(len(cierres), 1, self._mails())
        self.assertTrue(cierres[0]["requiere_plan"])
        self.assertEqual(cierres[0]["total_days"], tr.TRIAL_TOTAL_DAYS)
        self.enviados.clear()
        self._paso_del_cron()
        self.assertEqual([n for n, _ in self.enviados], [],
                         "el mail de cierre salió dos veces")

    def test_pagar_levanta_el_muro_en_el_acto(self):
        self._estamos_en_el_dia(tr.TRIAL_TOTAL_DAYS + 1)
        self.assertFalse(self._entra()[0])
        from billing import credits
        credits.grant_payment_credit(
            self.conn, user_id=self.uid, plan="pro", period="monthly",
            amount_usd=None, subscription_id="s1", payment_id="p1")
        entra, r = self._entra()
        self.assertTrue(entra, r.text)
        self.assertEqual(quota.get_tier(self.conn, self.uid), "pro")

    def test_los_tres_avisos_salen_una_vez_cada_uno_en_todo_el_recorrido(self):
        """El recorrido entero de una sola pasada: ningún aviso se repite ni se
        pierde cuando el cron corre TODOS los días, que es lo que hace en la
        realidad."""
        self.enviados.clear()
        for dia in range(1, tr.TRIAL_TOTAL_DAYS + 3):
            self._estamos_en_el_dia(dia)
            self._paso_del_cron()
        mails = self._mails()
        for aviso in ("send_trial_pro_ending", "send_trial_ending_soon",
                      "send_trial_ended"):
            self.assertEqual(mails.count(aviso), 1,
                             f"{aviso} salió {mails.count(aviso)} veces: {mails}")


class LaPuertaExternaDelCron(unittest.TestCase):
    """El job diario corría SOLO en el scheduler in-process, que se saltea la
    ventana si Railway está frío. Sin tarjeta al inicio, los tres mails de la
    prueba SON la conversión: si no salen, no hay ningún error — simplemente
    nadie se entera de que su prueba se termina."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(main.app)

    def tearDown(self):
        os.environ.pop("BILLING_CRON_TOKEN", None)

    def test_sin_token_configurado_el_endpoint_esta_cerrado(self):
        os.environ.pop("BILLING_CRON_TOKEN", None)
        self.assertEqual(self.client.get("/api/billing/run-cron").status_code, 503)

    def test_con_token_mal_rechaza(self):
        os.environ["BILLING_CRON_TOKEN"] = "secreto"
        r = self.client.get("/api/billing/run-cron",
                            headers={"X-Cron-Token": "otro"})
        self.assertEqual(r.status_code, 401)

    def test_con_el_token_correcto_arranca(self):
        os.environ["BILLING_CRON_TOKEN"] = "secreto"
        r = self.client.get("/api/billing/run-cron",
                            headers={"X-Cron-Token": "secreto"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(r.json()["status"], ("started", "already_running"))

    def test_tambien_acepta_el_token_por_query(self):
        """cron-job.org a veces es más fácil de configurar por URL."""
        os.environ["BILLING_CRON_TOKEN"] = "secreto"
        r = self.client.get("/api/billing/run-cron?token=secreto")
        self.assertEqual(r.status_code, 200, r.text)

    def test_el_job_diario_sigue_haciendo_los_dos_pasos_de_la_prueba(self):
        """La puerta externa no sirve si el job que dispara dejó de hacer el
        paso a Plus o de mandar los avisos."""
        import inspect
        from billing import subscriptions as subs
        fuente = inspect.getsource(subs.run_lifecycle_job)
        self.assertIn("send_due_trial_emails", fuente)
        self.assertIn("step_down_due_trials", fuente)


if __name__ == "__main__":
    unittest.main()
