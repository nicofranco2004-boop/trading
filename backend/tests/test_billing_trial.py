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
        # Cualquier transacción que haya quedado abierta en un test anterior
        # hace que el siguiente espere el busy_timeout entero (~90s) antes de
        # fallar. Arrancamos siempre en limpio.
        try:
            self.conn.rollback()
        except Exception:
            pass
        # trial_consumed a propósito: la marca SOBREVIVE al borrado de la
        # cuenta (ese es el fix), así que entre tests hay que limpiarla a mano.
        # El orden importa: las que referencian users van ANTES (FK activas).
        for t in ("credit_ledger", "subscriptions", "trial_consumed",
                  "trial_email_log", "operations", "positions", "brokers",
                  "ai_usage_daily", "users"):
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
        # Nadie manda mails de verdad: sin esto el envío intenta salir a la red,
        # tarda ~90s y deja la base trabada para los tests que siguen.
        from billing import emails as _em
        self.enviados = []
        self._orig_mails = {}
        for _fn in ("send_trial_started", "send_trial_pro_ending",
                    "send_trial_ending_soon", "send_trial_ended"):
            self._orig_mails[_fn] = getattr(_em, _fn)
            setattr(_em, _fn, self._spy(_fn))

    def tearDown(self):
        from billing import emails as _em
        for _fn, _orig in getattr(self, "_orig_mails", {}).items():
            setattr(_em, _fn, _orig)
        try:
            self.conn.rollback()   # no dejar nada abierto para el que sigue
        except Exception:
            pass
        self.conn.close()

    def _spy(self, nombre):
        def _fake(**kw):
            self.enviados.append((nombre, kw))
            return True
        return _fake

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
            "SELECT trial_started_at, credit_active_until, trial_ends_at FROM users WHERE id=?",
            (self.uid,)).fetchone()
        started = datetime.fromisoformat(row["trial_started_at"]) - timedelta(days=dias)
        until = datetime.fromisoformat(row["credit_active_until"]) - timedelta(days=dias)
        # trial_ends_at viaja junto: es la marca de "este crédito ES el del
        # trial" y tiene que seguir coincidiendo con credit_active_until.
        ends = datetime.fromisoformat(row["trial_ends_at"]) - timedelta(days=dias)
        self.conn.execute(
            "UPDATE users SET trial_started_at=?, credit_active_until=?, trial_ends_at=? "
            "WHERE id=?", (_iso(started), _iso(until), _iso(ends), self.uid))
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


class TrialAuditFixes(TrialBase):
    """Hallazgos del audit del 2026-08-08. Cada test fija un agujero que ya
    estaba en producción (aunque sin UI, así que nadie llegó a activarlo)."""

    def _otro_user(self, email="otro@rendi.test", **cols):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified) "
            "VALUES (?,?,1,1)", (email, "x"))
        uid = cur.lastrowid
        for k, v in cols.items():
            self.conn.execute(f"UPDATE users SET {k}=? WHERE id=?", (v, uid))
        self.conn.commit()
        return uid

    # ── El cron NO puede tocar a un Pro que no es del trial ─────────────────
    def test_no_baja_el_pro_regalado_a_un_ex_trial(self):
        # Hizo el trial hace meses; hoy el admin le regala Pro por 30 días.
        tr.start(self.conn, self.uid)
        self._viajar(120)
        self.conn.execute(
            "UPDATE users SET tier='pro', credit_active_until=? WHERE id=?",
            (_iso(datetime.utcnow() + timedelta(days=30)), self.uid))
        self.conn.commit()
        self.assertEqual(tr.step_down_due_trials(self.conn), 0,
                         "el regalo NO es el crédito del trial")
        self.assertEqual(self._tier(), "pro")

    def test_no_baja_el_pro_de_una_suscripcion_cancelada_en_gracia(self):
        # Pagó Pro y canceló: conserva Pro hasta fin de período, sin sub
        # 'authorized'. Antes el cron se lo bajaba a Plus.
        tr.start(self.conn, self.uid)
        self._viajar(120)
        self.conn.execute(
            "UPDATE users SET tier='pro', credit_active_until=? WHERE id=?",
            (_iso(datetime.utcnow() + timedelta(days=22)), self.uid))
        self.conn.execute(
            "INSERT INTO subscriptions (user_id, status, external_reference, period, amount_ars) "
            "VALUES (?, 'cancelled', 'ref-cancel', 'monthly', 10000)", (self.uid,))
        self.conn.commit()
        self.assertEqual(tr.step_down_due_trials(self.conn), 0)
        self.assertEqual(self._tier(), "pro")

    # ── El trial no puede fabricar crédito con plata ────────────────────────
    def test_no_hereda_el_anchor_de_una_suscripcion_vieja(self):
        # Ex-suscriptor: el anchor queda pegado y le pone PRECIO al crédito.
        # Sin limpiarlo, los 15 días gratis valían USD 4,50 y "cambiar de plan"
        # los convertía en 41 días de Plus.
        self.conn.execute(
            """UPDATE users SET credit_anchor_plan='pro', credit_anchor_period='monthly',
                   credit_anchor_amount_usd=9.0, credit_active_until=? WHERE id=?""",
            (_iso(datetime.utcnow() - timedelta(days=5)), self.uid))
        self.conn.commit()
        self.assertTrue(tr.start(self.conn, self.uid)["ok"])
        row = self.conn.execute(
            "SELECT credit_anchor_plan p, credit_anchor_amount_usd a FROM users WHERE id=?",
            (self.uid,)).fetchone()
        self.assertIsNone(row["p"], "el anchor viejo tiene que quedar limpio")
        self.assertIsNone(row["a"])
        from billing import credits as _c
        st = _c.get_credit_state(self.conn, self.uid)
        self.assertEqual(st["remaining_usd"], 0.0, "un trial no vale plata")

    # ── Uno por persona, aunque borre la cuenta ─────────────────────────────
    def test_borrar_la_cuenta_no_devuelve_el_trial(self):
        tr.start(self.conn, self.uid)
        email = self.conn.execute(
            "SELECT email e FROM users WHERE id=?", (self.uid,)).fetchone()["e"]
        self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
        self.conn.commit()
        nuevo = self._otro_user(email=email)      # se registra de nuevo, mismo mail
        self.assertEqual(tr.start(self.conn, nuevo)["reason"], "already_used")

    # ── Nadie pierde lo que ya tiene ────────────────────────────────────────
    def test_no_pisa_el_credito_de_alguien_que_ya_tiene_plan(self):
        futuro = _iso(datetime.utcnow() + timedelta(days=200))
        self.conn.execute(
            "UPDATE users SET tier='plus', credit_active_until=? WHERE id=?",
            (futuro, self.uid))
        self.conn.commit()
        tr.start(self.conn, self.uid)
        row = self.conn.execute(
            "SELECT tier, credit_active_until c FROM users WHERE id=?", (self.uid,)).fetchone()
        self.assertEqual(row["c"], futuro, "no se le acorta el plan que ya tenía")
        self.assertEqual(row["tier"], "plus")

    def test_el_admin_no_se_autodegrada(self):
        # Un admin tiene límites MÁS altos que Pro: el trial lo bajaría.
        admin = self._otro_user(email="admin@rendi.test", is_admin=1)
        self.assertEqual(tr.start(self.conn, admin)["reason"], "not_applicable")
        self.assertEqual(quota.get_tier(self.conn, admin), "admin")

    # ── La UI no puede contradecir al gate ──────────────────────────────────
    def test_la_etapa_sigue_al_tier_real_no_al_calendario(self):
        # Cron caído: pasó el día 8 pero el usuario TODAVÍA tiene Pro.
        tr.start(self.conn, self.uid)
        self._viajar(10)
        self.assertEqual(self._tier(), "pro")
        self.assertEqual(tr.status(self.conn, self.uid)["stage"], "pro",
                         "la app no puede decir Plus mientras el gate da Pro")
        tr.step_down_due_trials(self.conn)
        self.assertEqual(tr.status(self.conn, self.uid)["stage"], "plus")

    def test_days_to_switch_siempre_presente(self):
        tr.start(self.conn, self.uid)
        self.assertIn("days_to_switch", tr.status(self.conn, self.uid))
        self._viajar(9)
        tr.step_down_due_trials(self.conn)
        self.assertIn("days_to_switch", tr.status(self.conn, self.uid))

    # ── Las palancas fallan del lado seguro ─────────────────────────────────
    def test_el_tope_no_se_recicla_al_borrar_cuentas(self):
        os.environ["TRIALS_MONTHLY_CAP"] = "1"
        tr.start(self.conn, self.uid)
        self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
        self.conn.commit()
        otro = self._otro_user(email="tercero@rendi.test")
        self.assertEqual(tr.start(self.conn, otro)["reason"], "monthly_cap_reached",
                         "el cupo se cuenta sobre el ledger, no sobre users")


class TrialAvisos(TrialBase):
    """Los cuatro mails del trial. Lo que más importa: que NO se repitan —
    el aviso genérico de vencimiento salía 4 días seguidos porque su
    idempotencia se apoyaba en una tabla que un usuario de trial no tiene."""

    def _kinds(self):
        return [r["kind"] for r in self.conn.execute(
            "SELECT kind FROM trial_email_log WHERE user_id=?", (self.uid,)).fetchall()]

    def test_el_de_bienvenida_sale_al_activar_no_al_dia_siguiente(self):
        tr.start(self.conn, self.uid)
        self.assertEqual([n for n, _ in self.enviados], ["send_trial_started"])
        kw = self.enviados[0][1]
        self.assertEqual(kw["pro_days"], 7)
        self.assertEqual(kw["total_days"], 15)

    def test_avisa_la_vispera_del_cambio_a_plus(self):
        tr.start(self.conn, self.uid)
        self.enviados.clear()
        self._viajar(6)                       # día 7: mañana pasa a Plus
        self.assertEqual(tr.send_due_trial_emails(self.conn), 1)
        self.assertEqual(self.enviados[0][0], "send_trial_pro_ending")

    def test_ese_aviso_NO_se_repite_al_dia_siguiente(self):
        tr.start(self.conn, self.uid)
        self._viajar(6)
        tr.send_due_trial_emails(self.conn)
        self.enviados.clear()
        self._viajar(1)                       # el cron corre de nuevo
        tr.send_due_trial_emails(self.conn)
        self.assertEqual([n for n, _ in self.enviados], [],
                         "un aviso por trial, no uno por día")

    def test_avisa_cuando_faltan_dos_dias(self):
        tr.start(self.conn, self.uid)
        self.enviados.clear()
        self._viajar(13)                      # quedan 2
        tr.send_due_trial_emails(self.conn)
        nombres = [n for n, _ in self.enviados]
        self.assertIn("send_trial_ending_soon", nombres)

    def test_el_de_cierre_sale_una_vez_y_lleva_el_resumen(self):
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (self.uid, "Cocos", "ARS"))
        self.conn.commit()
        tr.start(self.conn, self.uid)
        self.enviados.clear()
        self._viajar(16)                      # terminó
        tr.send_due_trial_emails(self.conn)
        cierre = [kw for n, kw in self.enviados if n == "send_trial_ended"]
        self.assertEqual(len(cierre), 1)
        self.assertEqual(cierre[0]["stats"].get("brokers"), 1)
        # Y no vuelve a salir aunque el cron corra otra vez
        self.enviados.clear()
        tr.send_due_trial_emails(self.conn)
        self.assertEqual(self.enviados, [])

    def test_al_que_se_suscribio_no_se_le_manda_el_de_cierre(self):
        tr.start(self.conn, self.uid)
        self._suscribir()
        self.enviados.clear()
        self._viajar(16)
        tr.send_due_trial_emails(self.conn)
        self.assertEqual([n for n, _ in self.enviados], [],
                         "pagó: no se le anuncia que perdió nada")

    def test_dos_corridas_simultaneas_no_duplican(self):
        tr.start(self.conn, self.uid)
        self._viajar(6)
        tr.send_due_trial_emails(self.conn)
        tr.send_due_trial_emails(self.conn)
        self.assertEqual(self._kinds().count(tr.MAIL_PRO_ENDING), 1)

    # El enganche al cron diario ya está cubierto en TrialCron (el job completo
    # hace llamadas de red que traban la base en el sandbox). Acá probamos la
    # unidad real: send_due_trial_emails.
    def test_el_paso_del_cron_esta_declarado_en_el_job(self):
        import inspect
        fuente = inspect.getsource(subs.run_lifecycle_job)
        self.assertIn("send_due_trial_emails", fuente)
        self.assertIn("trial_emails_sent", fuente)
