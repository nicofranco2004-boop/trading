"""Los tres caminos que se rompían con `credit_anchor_plan` en NULL.

La prueba gratis NO tiene anchor a propósito: el tiempo regalado no vale plata,
y ponerle precio fue exactamente lo que hizo que convert_plan valuara los 15
días en USD 4,50 y los convirtiera en 41 días de Plus (audit 2026-08-09). El
costo de esa decisión es que "acceso vigente + tier pago + anchor NULL" dejó de
ser un estado casi inalcanzable y pasó a ser el estado NORMAL de toda la
población en prueba. Cada lector que asumía "tier pago ⇒ hay un plan pago
detrás" empezó a leer mal:

  1. La campaña `gift-plan` con only_gifted=True apunta a quien tiene un comp
     activo, y lo detectaba con `amount_usd == 0`. Un trial tiene el amount en
     NULL → float(None or 0) == 0 → True: le llegaba un mail ofreciéndole DE
     REGALO justo lo que ya estaba usando gratis, en la mitad de su prueba.

  2. `restore-tier` (la herramienta de admin para realinear el tier cuando se
     desincroniza) sacaba el plan objetivo del anchor y cortaba en
     `no_valid_anchor`. Un usuario en prueba con el tier roto no se podía
     arreglar desde el panel.

  3. El cron baja a Free todo crédito vencido y avisa al admin por cada uno —
     incluida CADA prueba que se termina sola. Con volumen, la señal real de
     churn (alguien que pagaba y se fue) queda tapada por pruebas venciendo.

La marca que distingue al trial es la VENTANA, no el anchor:
`credit_active_until == trial_ends_at`. Vive en billing.trial.credit_is_trial y
estos tests fijan que los tres caminos la usen — y que el usuario PAGO siga
comportándose exactamente igual que antes.

Corre con: cd backend && python3 -m pytest tests/test_billing_trial_anchor_null.py
"""
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import main
from billing import trial as tr
from billing import subscriptions as subs


def _iso(dt):
    return dt.isoformat()


class AnchorNullBase(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        # Base limpia por test: la campaña y el cron barren la tabla users
        # ENTERA, así que un usuario que quedó de otro test cambia los conteos.
        # trial_consumed va explícita porque la marca sobrevive al borrado.
        for t in ("credit_ledger", "subscriptions", "trial_consumed",
                  "trial_email_log", "operations", "positions", "brokers",
                  "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.conn.commit()
        # Los mails al usuario no salen a la red (tardan ~10s y traban la base).
        for _fn in ("send_trial_started",):
            p = patch(f"billing.emails.{_fn}", return_value=True)
            p.start()
            self.addCleanup(p.stop)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _user(self, verificado=True, admin=False, tier=None):
        email = f"anchor-{uuid.uuid4().hex[:12]}@rendi.test"
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, "
            "is_admin, tier) VALUES (?, 'x', 1, ?, ?, ?)",
            (email, 1 if verificado else 0, 1 if admin else 0, tier))
        self.conn.commit()
        return cur.lastrowid, email

    def _en_trial(self, uid, dias_transcurridos=0):
        """Arranca la prueba y, si hace falta, la corre N días hacia atrás.

        Los TRES campos se mueven juntos a propósito: si solo se mueve
        trial_started_at, `credit_active_until = trial_ends_at` deja de
        matchear y el usuario ya no parece un trial para nadie."""
        tr.start(self.conn, uid)
        if dias_transcurridos:
            row = self.conn.execute(
                "SELECT trial_started_at, trial_ends_at FROM users WHERE id=?",
                (uid,)).fetchone()
            d = timedelta(days=dias_transcurridos)
            ini = datetime.fromisoformat(row["trial_started_at"]) - d
            fin = datetime.fromisoformat(row["trial_ends_at"]) - d
            self.conn.execute(
                """UPDATE users SET trial_started_at=?, trial_ends_at=?,
                                    credit_active_until=? WHERE id=?""",
                (_iso(ini), _iso(fin), _iso(fin), uid))
            self.conn.commit()

    def _con_anchor(self, uid, plan="pro", amount=9.0, dias=20):
        """Crédito CON anchor: un pago real (amount>0) o un comp (amount=0)."""
        hasta = _iso(datetime.utcnow() + timedelta(days=dias))
        self.conn.execute(
            """UPDATE users SET tier=?, credit_active_until=?, credit_anchor_plan=?,
                                credit_anchor_period='monthly',
                                credit_anchor_amount_usd=?, credit_anchor_at=?
               WHERE id=?""",
            (plan, hasta, plan, amount, _iso(datetime.utcnow()), uid))
        self.conn.commit()
        return hasta


# ═══════════════════════════════════════════════════════════════════════════
# 1. Campaña gift-plan: el que está en su prueba no recibe "te regalamos un mes"
# ═══════════════════════════════════════════════════════════════════════════

class CampanaGiftPlanTest(AnchorNullBase):
    def _dry_run(self, **kw):
        admin_uid, _ = self._user(admin=True)
        data = main.GiftPlanEmailIn(**kw)
        return main.admin_email_gift_plan(data, uid=admin_uid)

    def _emails(self, res):
        return {r["email"] for r in res["recipients"]}

    def test_trial_activo_no_cuenta_como_regalo(self):
        """El bug: anchor NULL pasaba el test de comp (float(None or 0) == 0)."""
        uid, email = self._user()
        self._en_trial(uid)
        res = self._dry_run(only_gifted=True)
        self.assertNotIn(email, self._emails(res))
        self.assertEqual(res["excluded_in_trial"], 1)

    def test_trial_activo_queda_afuera_tambien_sin_only_gifted(self):
        """La campaña abierta tampoco puede pisarle la prueba: el mail le
        promete de regalo lo que ya está usando gratis."""
        uid, email = self._user()
        self._en_trial(uid, dias_transcurridos=8)   # ya en la etapa Plus
        res = self._dry_run(only_gifted=False)
        self.assertNotIn(email, self._emails(res))
        self.assertEqual(res["excluded_in_trial"], 1)

    def test_comp_de_verdad_sigue_entrando(self):
        """Regresión: el destinatario real de la campaña no puede perderse."""
        uid, email = self._user()
        self._con_anchor(uid, plan="pro", amount=0.0)
        res = self._dry_run(only_gifted=True)
        self.assertIn(email, self._emails(res))
        self.assertEqual(res["excluded_in_trial"], 0)
        destino = next(r for r in res["recipients"] if r["email"] == email)
        self.assertTrue(destino["has_gift"])

    def test_usuario_pago_no_figura_como_regalado(self):
        uid, email = self._user()
        self._con_anchor(uid, plan="pro", amount=9.0)
        res = self._dry_run(only_gifted=True)
        self.assertNotIn(email, self._emails(res))
        self.assertEqual(res["excluded_in_trial"], 0)

    def test_trial_terminado_vuelve_a_ser_candidato(self):
        """Cuando la prueba se termina el regalo SÍ es un regalo: el ex-trial
        vuelve a la campaña. La exclusión es por prueba VIGENTE, no por haberla
        usado alguna vez."""
        uid, email = self._user()
        self._en_trial(uid, dias_transcurridos=20)   # venció hace 5 días
        self.conn.execute("UPDATE users SET tier=NULL WHERE id=?", (uid,))
        self.conn.commit()
        res = self._dry_run(only_gifted=False)
        self.assertIn(email, self._emails(res))
        self.assertEqual(res["excluded_in_trial"], 0)


# ═══════════════════════════════════════════════════════════════════════════
# 2. restore-tier: reparar a alguien que está en su prueba
# ═══════════════════════════════════════════════════════════════════════════

class RestoreTierTrialTest(AnchorNullBase):
    def setUp(self):
        super().setUp()
        p = patch("main._notify_plan_change")
        p.start()
        self.addCleanup(p.stop)
        self.admin_uid, _ = self._user(admin=True)

    def _restore(self, email):
        return main.admin_billing_restore_tier(email=email, uid=self.admin_uid)

    def _tier(self, uid):
        return self.conn.execute(
            "SELECT tier FROM users WHERE id=?", (uid,)).fetchone()["tier"]

    def test_repara_trial_en_la_semana_de_pro(self):
        """El bug: cortaba en no_valid_anchor y el usuario quedaba sin arreglo."""
        uid, email = self._user()
        self._en_trial(uid, dias_transcurridos=2)
        self.conn.execute("UPDATE users SET tier=NULL WHERE id=?", (uid,))
        self.conn.commit()
        res = self._restore(email)
        self.assertTrue(res["ok"])
        self.assertTrue(res["changed"])
        self.assertEqual(res["after_tier"], "pro")
        self.assertEqual(res["source"], "trial")
        self.assertEqual(self._tier(uid), "pro")

    def test_repara_trial_en_la_etapa_plus(self):
        """Día 10: le toca Plus, no Pro. La etapa sale del CALENDARIO — pedirla
        por el tier efectivo sería circular, porque el tier es lo que está roto."""
        uid, email = self._user()
        self._en_trial(uid, dias_transcurridos=10)
        self.conn.execute("UPDATE users SET tier=NULL WHERE id=?", (uid,))
        self.conn.commit()
        res = self._restore(email)
        self.assertEqual(res["after_tier"], "plus")
        self.assertEqual(self._tier(uid), "plus")

    def test_repara_aunque_el_tier_haya_quedado_en_free(self):
        """'free' es lo que deja un cron mal corrido, no NULL. Mismo caso."""
        uid, email = self._user()
        self._en_trial(uid, dias_transcurridos=3)
        self.conn.execute("UPDATE users SET tier='free' WHERE id=?", (uid,))
        self.conn.commit()
        self.assertEqual(self._restore(email)["after_tier"], "pro")

    def test_deja_el_audit_en_el_ledger(self):
        uid, email = self._user()
        self._en_trial(uid, dias_transcurridos=1)
        self.conn.execute("UPDATE users SET tier=NULL WHERE id=?", (uid,))
        self.conn.commit()
        self._restore(email)
        row = self.conn.execute(
            "SELECT note FROM credit_ledger WHERE user_id=? AND kind='manual_adjust'",
            (uid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertIn("prueba gratis", row["note"])

    def test_es_idempotente(self):
        uid, email = self._user()
        self._en_trial(uid, dias_transcurridos=2)   # tier ya está en 'pro'
        res = self._restore(email)
        self.assertTrue(res["ok"])
        self.assertFalse(res["changed"])

    def test_trial_vencido_no_se_repara(self):
        """Terminó la prueba: que sea Free es correcto, no un desperfecto."""
        uid, email = self._user()
        self._en_trial(uid, dias_transcurridos=20)
        self.conn.execute("UPDATE users SET tier=NULL WHERE id=?", (uid,))
        self.conn.commit()
        res = self._restore(email)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "credit_not_active")
        self.assertIsNone(self._tier(uid))

    def test_sin_anchor_y_sin_ventana_de_trial_sigue_cortando(self):
        """Crédito vigente, anchor NULL y una ventana que NO es la del trial:
        no hay de dónde deducir el plan. Tiene que seguir negándose."""
        uid, email = self._user()
        self._en_trial(uid, dias_transcurridos=2)
        # El crédito se corre un día: deja de coincidir con trial_ends_at.
        otra = _iso(datetime.utcnow() + timedelta(days=30))
        self.conn.execute(
            "UPDATE users SET tier=NULL, credit_active_until=? WHERE id=?",
            (otra, uid))
        self.conn.commit()
        res = self._restore(email)
        self.assertFalse(res["ok"])
        self.assertEqual(res["reason"], "no_valid_anchor")

    def test_el_usuario_pago_sigue_usando_su_anchor(self):
        """Regresión: el camino de siempre no cambió."""
        uid, email = self._user()
        self._con_anchor(uid, plan="plus", amount=4.5)
        self.conn.execute("UPDATE users SET tier=NULL WHERE id=?", (uid,))
        self.conn.commit()
        res = self._restore(email)
        self.assertEqual(res["after_tier"], "plus")
        self.assertEqual(res["source"], "credito")


# ═══════════════════════════════════════════════════════════════════════════
# 3. El cron: una prueba que se apaga sola no es un cliente que se fue
# ═══════════════════════════════════════════════════════════════════════════

class AvisoDeBajaAlAdminTest(AnchorNullBase):
    def setUp(self):
        super().setUp()
        self.individuales = []
        self.agregados = []

        def _spy_individual(**kw):
            self.individuales.append(kw)
            return True

        def _spy_agregado(**kw):
            self.agregados.append(kw)
            return True

        # create=True para que estos tests midan CONDUCTA y no la existencia del
        # símbolo: sin él, correrlos contra la versión sin el fix explota en el
        # setUp en vez de mostrar el mail de baja saliendo por cada prueba.
        for nombre, spy in (("send_plan_change_admin", _spy_individual),
                            ("send_trials_ended_admin", _spy_agregado)):
            p = patch(f"billing.emails.{nombre}", spy, create=True)
            p.start()
            self.addCleanup(p.stop)

    def _vencido(self, uid, dias=1):
        """Vence el crédito hace `dias`. Si el usuario tiene prueba, la ventana
        se mueve ENTERA: credit_active_until y trial_ends_at tienen que seguir
        coincidiendo o deja de parecer un trial."""
        cau = _iso(datetime.utcnow() - timedelta(days=dias))
        row = self.conn.execute(
            "SELECT trial_ends_at FROM users WHERE id=?", (uid,)).fetchone()
        fin = cau if row["trial_ends_at"] else None
        self.conn.execute(
            "UPDATE users SET credit_active_until=?, trial_ends_at=? WHERE id=?",
            (cau, fin, uid))
        self.conn.commit()

    def test_prueba_vencida_no_manda_mail_de_baja_individual(self):
        """El bug: cada prueba que se apagaba llegaba como si fuera churn."""
        uid, email = self._user()
        self._en_trial(uid)
        self._vencido(uid)
        n = subs._downgrade_expired_credit(self.conn)
        self.assertEqual(n, 1)
        self.assertEqual([k for k in self.individuales
                          if k.get("user_email") == email], [])
        self.assertEqual(len(self.agregados), 1)
        self.assertIn(email, self.agregados[0]["emails_list"])

    def test_varias_pruebas_van_en_un_solo_mail(self):
        emails_trial = []
        for _ in range(3):
            uid, email = self._user()
            self._en_trial(uid)
            self._vencido(uid)
            emails_trial.append(email)
        subs._downgrade_expired_credit(self.conn)
        self.assertEqual(len(self.agregados), 1)
        self.assertEqual(sorted(self.agregados[0]["emails_list"]),
                         sorted(emails_trial))

    def test_el_que_pagaba_sigue_avisando_uno_por_uno(self):
        """La señal que importa no se toca: churn real = mail individual."""
        uid, email = self._user()
        self._con_anchor(uid, plan="pro", amount=9.0)
        self._vencido(uid, dias=1)
        subs._downgrade_expired_credit(self.conn)
        self.assertEqual([k["user_email"] for k in self.individuales], [email])
        self.assertEqual(self.agregados, [])

    def test_ex_trial_que_pago_y_se_fue_cuenta_como_baja_real(self):
        """El discriminador es la VENTANA, no "usó el trial alguna vez": si
        después pagó, su crédito ya no coincide con trial_ends_at y su baja es
        churn de verdad."""
        uid, email = self._user()
        self._en_trial(uid)
        fin_trial = self.conn.execute(
            "SELECT trial_ends_at FROM users WHERE id=?", (uid,)).fetchone()["trial_ends_at"]
        # Pagó: el crédito se extiende más allá de la prueba y toma anchor.
        vencido = _iso(datetime.utcnow() - timedelta(days=1))
        self.conn.execute(
            """UPDATE users SET tier='pro', credit_active_until=?,
                                credit_anchor_plan='pro', credit_anchor_period='monthly',
                                credit_anchor_amount_usd=9.0
               WHERE id=?""", (vencido, uid))
        self.conn.commit()
        self.assertNotEqual(vencido, fin_trial)
        subs._downgrade_expired_credit(self.conn)
        self.assertEqual([k["user_email"] for k in self.individuales], [email])
        self.assertEqual(self.agregados, [])

    def test_sin_la_columna_del_trial_el_downgrade_igual_corre(self):
        """La columna solo decide a quién se le avisa; la baja a Free es lo que
        hace cumplir el vencimiento del acceso pago. Un esquema sin
        trial_ends_at tiene que degradar el aviso, nunca frenar la baja."""
        class _SinColumnaTrial:
            def __init__(self, real):
                self._real = real

            def execute(self, sql, *a, **kw):
                if "trial_ends_at" in sql:
                    raise Exception("no such column: u.trial_ends_at")
                return self._real.execute(sql, *a, **kw)

            def __getattr__(self, n):
                return getattr(self._real, n)

            def __enter__(self):
                return self._real.__enter__()

            def __exit__(self, *a):
                return self._real.__exit__(*a)

        uid, email = self._user()
        self._en_trial(uid)
        self._vencido(uid)
        n = subs._downgrade_expired_credit(_SinColumnaTrial(self.conn))
        self.assertEqual(n, 1)
        self.assertIsNone(self.conn.execute(
            "SELECT tier FROM users WHERE id=?", (uid,)).fetchone()["tier"])
        # Sin el dato no se puede distinguir: el aviso sale como antes del trial.
        self.assertEqual([k["user_email"] for k in self.individuales], [email])

    def test_baja_a_free_igual_que_siempre(self):
        """Cambia a quién se le avisa, no qué se le hace al usuario."""
        uid, _ = self._user()
        self._en_trial(uid)
        self._vencido(uid)
        subs._downgrade_expired_credit(self.conn)
        row = self.conn.execute(
            "SELECT tier FROM users WHERE id=?", (uid,)).fetchone()
        self.assertIsNone(row["tier"])
        led = self.conn.execute(
            "SELECT kind FROM credit_ledger WHERE user_id=? AND kind='expiration'",
            (uid,)).fetchone()
        self.assertIsNotNone(led)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Los helpers compartidos (una sola definición de "esto es un trial")
# ═══════════════════════════════════════════════════════════════════════════

class HelpersDelModuloTest(AnchorNullBase):
    def test_credit_is_trial_compara_la_ventana(self):
        self.assertTrue(tr.credit_is_trial("2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        self.assertFalse(tr.credit_is_trial("2026-09-02T00:00:00", "2026-09-01T00:00:00"))
        self.assertFalse(tr.credit_is_trial(None, "2026-09-01T00:00:00"))
        self.assertFalse(tr.credit_is_trial("2026-09-01T00:00:00", None))
        self.assertFalse(tr.credit_is_trial(None, None))

    def test_stage_by_calendar_respeta_la_constante(self):
        ahora = datetime(2026, 8, 19, 12, 0, 0)
        ini = ahora - timedelta(days=tr.TRIAL_PRO_DAYS - 1)
        self.assertEqual(tr.stage_by_calendar(_iso(ini), ahora), "pro")
        ini = ahora - timedelta(days=tr.TRIAL_PRO_DAYS)
        self.assertEqual(tr.stage_by_calendar(_iso(ini), ahora), "plus")
        self.assertIsNone(tr.stage_by_calendar(None, ahora))
        self.assertIsNone(tr.stage_by_calendar("no-es-fecha", ahora))

    def test_repair_stage_ignora_al_que_no_esta_en_prueba(self):
        uid, _ = self._user()
        self._con_anchor(uid, plan="pro", amount=9.0)
        self.assertIsNone(tr.repair_stage(self.conn, uid))


if __name__ == "__main__":
    unittest.main()
