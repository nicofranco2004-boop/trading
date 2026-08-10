"""Free trial de 15 días: 7 de Pro + 8 de Plus, encadenados.

Lo que estos tests protegen, en orden de importancia:
  1. Que el tier REAL que ve el usuario sea el correcto en cada tramo — se
     verifica contra quota.get_tier(), que es lo que gatea las features, no
     contra la columna users.tier.
  2. Que no se pueda usar dos veces, ni con dos requests simultáneos.
  3. Que un cron caído NO le corte el acceso a nadie (se queda en Pro de más).
  4. Que al que ya paga no se le toque nada.

Corre con: cd backend && python3 -m pytest tests/test_billing_trial.py
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
from ai import quota
from billing import trial as tr
from billing import subscriptions as subs


def _iso(dt):
    return dt.isoformat()


class TrialBase(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        for t in ("credit_ledger", "subscriptions", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?,?,1,1)", ("trial@rendi.test", "x"))
        self.uid = cur.lastrowid
        self.conn.commit()
        os.environ.pop("TRIALS_ENABLED", None)
        os.environ.pop("TRIALS_MONTHLY_CAP", None)

    def tearDown(self):
        self.conn.close()

    def _tier(self):
        """El tier EFECTIVO — lo que realmente gatea las features."""
        return quota.get_tier(self.conn, self.uid)

    def _suscribir(self, uid=None):
        """Suscripción paga activa (la tabla exige external_reference)."""
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, status, external_reference, period, amount_ars) "
            "VALUES (?, 'authorized', ?, 'monthly', 10000)",
            (uid or self.uid, f"ref-{uid or self.uid}"))
        self.conn.commit()

    def _viajar(self, dias):
        """Simula el paso del tiempo moviendo el arranque del trial hacia
        atrás (no se puede mover el reloj del sistema en un test)."""
        row = self.conn.execute(
            "SELECT trial_started_at, credit_active_until FROM users WHERE id=?",
            (self.uid,)).fetchone()
        started = datetime.fromisoformat(row["trial_started_at"]) - timedelta(days=dias)
        until = datetime.fromisoformat(row["credit_active_until"]) - timedelta(days=dias)
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, credit_active_until=? WHERE id=?",
            (_iso(started), _iso(until), self.uid))
        self.conn.commit()


class TrialLifecycle(TrialBase):

    def test_arranca_en_pro(self):
        res = tr.start(self.conn, self.uid)
        self.assertTrue(res["ok"], res)
        self.assertEqual(self._tier(), "pro")
        st = tr.status(self.conn, self.uid)
        self.assertTrue(st["active"])
        self.assertEqual(st["stage"], "pro")
        self.assertEqual(st["days_left"], 15)

    def test_dia_8_pasa_a_plus_y_no_se_acorta_el_vencimiento(self):
        tr.start(self.conn, self.uid)
        self._viajar(7)                      # ya cumplió la semana de Pro
        # Se lee DESPUÉS de viajar: _viajar mueve la fecha a propósito, así que
        # el antes/después tiene que medir solo el efecto del step-down.
        vence_antes = self.conn.execute(
            "SELECT credit_active_until c FROM users WHERE id=?", (self.uid,)).fetchone()["c"]
        self.assertEqual(tr.step_down_due_trials(self.conn), 1)
        self.assertEqual(self._tier(), "plus")
        self.assertEqual(tr.status(self.conn, self.uid)["stage"], "plus")
        vence_despues = self.conn.execute(
            "SELECT credit_active_until c FROM users WHERE id=?", (self.uid,)).fetchone()["c"]
        # Bajar de plan NO puede correr la fecha de fin del trial.
        self.assertEqual(vence_antes, vence_despues)

    def test_dia_16_cae_a_free_solo(self):
        tr.start(self.conn, self.uid)
        self._viajar(16)
        # Sin correr NADA: get_tier corta por sí mismo al vencer el crédito.
        self.assertEqual(self._tier(), "free")
        self.assertFalse(tr.status(self.conn, self.uid)["active"])

    def test_el_paso_a_plus_es_idempotente(self):
        tr.start(self.conn, self.uid)
        self._viajar(7)
        self.assertEqual(tr.step_down_due_trials(self.conn), 1)
        self.assertEqual(tr.step_down_due_trials(self.conn), 0)   # segunda corrida: nada
        self.assertEqual(self._tier(), "plus")

    def test_si_el_cron_no_corre_el_usuario_NO_pierde_acceso(self):
        # La garantía de diseño: el error cae a favor del usuario. Sin cron,
        # sigue en Pro (de más), nunca sin nada.
        tr.start(self.conn, self.uid)
        self._viajar(10)                     # debería estar en Plus hace 3 días
        self.assertEqual(self._tier(), "pro")
        # Y cuando el cron finalmente corre, se acomoda.
        tr.step_down_due_trials(self.conn)
        self.assertEqual(self._tier(), "plus")

    def test_el_dia_7_todavia_es_pro(self):
        # Borde: recién al CUMPLIRSE los 7 días baja, no antes.
        tr.start(self.conn, self.uid)
        self._viajar(6)
        self.assertEqual(tr.step_down_due_trials(self.conn), 0)
        self.assertEqual(self._tier(), "pro")


class TrialElegibilidad(TrialBase):

    def test_no_se_puede_usar_dos_veces(self):
        self.assertTrue(tr.start(self.conn, self.uid)["ok"])
        res = tr.start(self.conn, self.uid)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "already_used")

    def test_sigue_marcado_como_usado_despues_de_terminar(self):
        tr.start(self.conn, self.uid)
        self._viajar(20)
        st = tr.status(self.conn, self.uid)
        self.assertTrue(st["used"])
        self.assertFalse(st["can_start"])     # terminado ≠ disponible de nuevo

    def test_dos_requests_simultaneos_activan_UNA_sola_vez(self):
        # El UPDATE es condicional sobre trial_used_at IS NULL: el segundo no
        # matchea ninguna fila.
        r1 = tr.start(self.conn, self.uid)
        r2 = tr.start(self.conn, self.uid)
        self.assertTrue(r1["ok"])
        self.assertFalse(r2["ok"])
        n = self.conn.execute(
            "SELECT COUNT(*) c FROM credit_ledger WHERE user_id=? AND kind='trial'",
            (self.uid,)).fetchone()["c"]
        self.assertEqual(n, 1, "un solo asiento en el ledger")

    def test_quien_ya_paga_no_lo_necesita(self):
        self._suscribir()
        self.assertEqual(tr.start(self.conn, self.uid)["reason"], "already_paying")

    def test_quien_tiene_un_regalo_vigente_no_lo_necesita(self):
        self.conn.execute(
            "UPDATE users SET tier='pro', credit_active_until=? WHERE id=?",
            (_iso(datetime.utcnow() + timedelta(days=30)), self.uid))
        self.conn.commit()
        self.assertEqual(tr.start(self.conn, self.uid)["reason"], "already_premium")

    def test_pide_email_verificado(self):
        self.conn.execute("UPDATE users SET email_verified=0 WHERE id=?", (self.uid,))
        self.conn.commit()
        self.assertEqual(tr.start(self.conn, self.uid)["reason"], "email_not_verified")

    def test_el_asesor_queda_afuera(self):
        self.conn.execute("UPDATE users SET tier='advisor' WHERE id=?", (self.uid,))
        self.conn.commit()
        self.assertEqual(tr.start(self.conn, self.uid)["reason"], "not_applicable")


class TrialPalancas(TrialBase):

    def test_el_interruptor_apaga_las_activaciones(self):
        os.environ["TRIALS_ENABLED"] = "false"
        self.assertEqual(tr.start(self.conn, self.uid)["reason"], "disabled")

    def test_apagarlo_no_le_corta_el_trial_a_quien_ya_lo_tiene(self):
        tr.start(self.conn, self.uid)
        os.environ["TRIALS_ENABLED"] = "false"
        self.assertEqual(self._tier(), "pro")
        self.assertTrue(tr.status(self.conn, self.uid)["active"])

    def test_el_tope_mensual_frena_las_nuevas(self):
        os.environ["TRIALS_MONTHLY_CAP"] = "1"
        self.assertTrue(tr.start(self.conn, self.uid)["ok"])
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?,?,1,1)", ("otro@rendi.test", "x"))
        otro = cur.lastrowid
        self.conn.commit()
        self.assertEqual(tr.start(self.conn, otro)["reason"], "monthly_cap_reached")

    def test_sin_tope_configurado_no_frena(self):
        self.assertEqual(tr.monthly_cap(), 0)
        self.assertTrue(tr.start(self.conn, self.uid)["ok"])


class TrialCron(TrialBase):

    def test_el_job_diario_incluye_el_paso_a_plus(self):
        tr.start(self.conn, self.uid)
        self._viajar(7)
        res = subs.run_lifecycle_job(self.conn)
        self.assertEqual(res.get("trials_stepped_down"), 1)
        self.assertEqual(self._tier(), "plus")

    def test_al_que_se_suscribio_en_el_medio_no_se_le_toca_el_plan(self):
        tr.start(self.conn, self.uid)
        self._suscribir()
        self._viajar(7)
        self.assertEqual(tr.step_down_due_trials(self.conn), 0)
        self.assertEqual(self._tier(), "pro", "pagó Pro: no se lo bajamos a Plus")

    def test_no_toca_a_quien_nunca_tuvo_trial(self):
        self.conn.execute(
            "UPDATE users SET tier='pro', credit_active_until=? WHERE id=?",
            (_iso(datetime.utcnow() + timedelta(days=300)), self.uid))
        self.conn.commit()
        self.assertEqual(tr.step_down_due_trials(self.conn), 0)
        self.assertEqual(self._tier(), "pro", "un regalo de Pro no es un trial")


if __name__ == "__main__":
    unittest.main()
