"""Smoke test del embudo del trial: una población de 90 días, número por número.

No prueba una función aislada: siembra una cohorte con TODOS los casos que
existen de verdad —en curso, terminados sin pagar, los que pagaron durante Pro,
durante Plus y después, uno que activó y pagó al toque, uno de hace 200 días—
y después verifica contra el endpoint real que cada casillero del panel dé el
número que corresponde, calculado a mano acá.

Es la red del panel de /admin: si un número miente, el dueño toma decisiones de
plata (subir el tope, mandar más tandas, cambiar el plazo) con datos falsos, y
un número equivocado no se ve — se ve como un dato.

⭐ El caso que motivó `activos`: alguien que activa la prueba y a los dos días
PAGA conserva su trial_ends_at futuro, así que `en_curso` lo seguía contando
como si estuviera probando. "Cuántos la tienen activa" y "cuántos arrancaron y
todavía no vencieron" NO son la misma pregunta.

Corre con: cd backend && python3 -m pytest tests/test_trial_funnel_smoke.py
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

import main
from billing import trial as tr


def _iso(dt):
    return dt.isoformat()


class EmbudoDelTrial(unittest.TestCase):
    """Cohorte sembrada a mano. Cada usuario tiene un nombre que dice qué es."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(main.app)
        conn = main.get_db()
        for t in ("credit_ledger", "subscriptions", "trial_consumed", "trial_email_log",
                  "ai_usage_daily", "import_batches", "operations", "positions",
                  "brokers", "users"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
            "VALUES (?, 'x', 1, 1, 1)", (f"admin-{uuid.uuid4().hex[:6]}@rendi.test",))
        cls.admin = cur.lastrowid
        conn.commit()
        cls.headers = {"Authorization": f"Bearer {main.create_token(cls.admin)}"}
        cls.conn = conn
        cls.ahora = datetime.utcnow()
        cls._sembrar()

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    # ── siembra ─────────────────────────────────────────────────────────────

    @classmethod
    def _trial(cls, etiqueta, hace_dias, *, pago_dia=None, importo=False,
               uso_ia=False, sub_status="authorized"):
        """Un usuario que arrancó la prueba hace `hace_dias`.

        `pago_dia`: día del trial en que se suscribió (None = nunca).
        """
        ini = cls.ahora - timedelta(days=hace_dias)
        fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
        cur = cls.conn.execute(
            """INSERT INTO users (email, password_hash, approved, email_verified,
                                  tier, trial_started_at, trial_used_at,
                                  trial_ends_at, credit_active_until)
               VALUES (?, 'x', 1, 1, 'pro', ?, ?, ?, ?)""",
            (f"{etiqueta}-{uuid.uuid4().hex[:6]}@rendi.test",
             _iso(ini), _iso(ini), _iso(fin), _iso(fin)))
        uid = cur.lastrowid
        if importo:
            cls.conn.execute(
                """INSERT INTO import_batches (id, user_id, broker, parser_format,
                                               file_name, file_hash, status, created_at)
                   VALUES (?, ?, 'Cocos', 'cocos', 'm.csv', ?, 'confirmed', ?)""",
                (uuid.uuid4().hex[:12], uid, uuid.uuid4().hex[:12],
                 _iso(ini + timedelta(hours=2)).replace("T", " ")[:19]))
        if uso_ia:
            cls.conn.execute(
                "INSERT INTO ai_usage_daily (user_id, date, analyses_count, chat_count) "
                "VALUES (?, ?, 3, 2)", (uid, (ini + timedelta(days=1)).date().isoformat()))
        if pago_dia is not None:
            cls.conn.execute(
                """INSERT INTO subscriptions (user_id, status, external_reference,
                                              period, amount_ars, created_at)
                   VALUES (?, ?, ?, 'monthly', 12100, ?)""",
                (uid, sub_status, f"ref-{uid}",
                 _iso(ini + timedelta(days=pago_dia)).replace("T", " ")[:19]))
            # El cobro de verdad. El embudo mira ESTO y no la fila de
            # subscriptions, que existe desde que se genera el link de pago.
            cls.conn.execute(
                """INSERT INTO credit_ledger (user_id, kind, amount_usd, days_delta, created_at)
                   VALUES (?, 'payment', 9.0, 30, ?)""",
                (uid, _iso(ini + timedelta(days=pago_dia)).replace("T", " ")[:19]))
            # Quien paga deja de estar "en prueba": su crédito ya no es el del
            # trial. Se replica lo que hace grant_payment_credit de verdad.
            nuevo_fin = cls.ahora + timedelta(days=30)
            cls.conn.execute(
                """UPDATE users SET credit_active_until=?, credit_anchor_plan='pro',
                                    credit_anchor_period='monthly',
                                    credit_anchor_amount_usd=9.0 WHERE id=?""",
                (_iso(nuevo_fin), uid))
        cls.conn.commit()
        return uid

    @classmethod
    def _sembrar(cls):
        # ── EN CURSO (arrancaron hace poco, no vencieron, no pagaron) ───────
        cls.en_curso_pro = [cls._trial("curso-pro", d, importo=True, uso_ia=True)
                            for d in (0, 2, 5)]          # 3, etapa Pro
        cls.en_curso_plus = [cls._trial("curso-plus", d, importo=True)
                             for d in (9, 12)]           # 2, etapa Plus
        # ── EN CURSO PERO YA PAGÓ (el caso que rompía en_curso) ────────────
        cls.pago_en_curso = cls._trial("pago-en-curso", 3, pago_dia=2,
                                       importo=True, uso_ia=True)
        # ── TERMINADOS ─────────────────────────────────────────────────────
        cls.term_sin_pagar = [cls._trial("fin-sin-pagar", d, importo=True)
                              for d in (20, 30, 45)]     # 3
        cls.term_pago_pro = cls._trial("fin-pago-pro", 40, pago_dia=3, uso_ia=True)
        cls.term_pago_plus = cls._trial("fin-pago-plus", 50, pago_dia=10, uso_ia=True)
        cls.term_pago_desp = cls._trial("fin-pago-desp", 60, pago_dia=20)
        # ── FUERA DE LA VENTANA (200 días: no entra en 90) ─────────────────
        cls.viejo = cls._trial("viejo", 200, importo=True, uso_ia=True)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _funnel(self, days=90):
        r = self.client.get(f"/api/admin/billing/trial-funnel?days={days}",
                            headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── el embudo, casillero por casillero ──────────────────────────────────

    def test_activados_cuenta_la_ventana_y_no_lo_de_antes(self):
        f = self._funnel(90)
        # 3 + 2 + 1 + 3 + 3 = 12 dentro de 90 días; el de 200 queda afuera.
        self.assertEqual(f["activados"], 12)
        self.assertEqual(self._funnel(365)["activados"], 13)

    def test_terminados_mas_en_curso_dan_los_activados(self):
        f = self._funnel(90)
        self.assertEqual(f["en_curso"] + f["terminados"], f["activados"],
                         "el embudo no cierra consigo mismo")

    def test_importaron_y_usaron_ia_no_pasan_a_los_activados(self):
        f = self._funnel(90)
        for k in ("importaron", "usaron_ia", "convirtieron"):
            self.assertLessEqual(f[k], f["activados"], f"{k} > activados")

    def test_convirtieron_son_los_cuatro_que_pagaron(self):
        f = self._funnel(90)
        # pago_en_curso + los 3 terminados que pagaron.
        self.assertEqual(f["convirtieron"], 4)

    def test_cuando_pagan_reparte_por_etapa(self):
        f = self._funnel(90)
        c = f["cuando_pagan"]
        # día 2 y día 3 → Pro · día 10 → Plus · día 20 → después.
        self.assertEqual(c["durante_pro"], 2)
        self.assertEqual(c["durante_plus"], 1)
        self.assertEqual(c["despues"], 1)
        self.assertEqual(sum(c.values()), f["convirtieron"])

    def test_la_conversion_cerrada_no_puede_pasar_de_cien(self):
        f = self._funnel(90)
        self.assertLessEqual(f["convirtieron_cerrados"], f["terminados"])
        if f["pct_conversion_cerrada"] is not None:
            self.assertLessEqual(f["pct_conversion_cerrada"], 100.0)

    # ── ⭐ lo nuevo: quiénes la tienen ACTIVA ahora ──────────────────────────

    def test_activos_no_cuenta_al_que_ya_pago(self):
        f = self._funnel(90)
        a = f["activos"]
        self.assertEqual(a["total"], 5, "activos debería ser 3 en Pro + 2 en Plus")
        ids = {u["id"] for u in a["usuarios"]}
        self.assertNotIn(self.pago_en_curso, ids,
                         "el que pagó sigue contando como si estuviera probando")
        # Y es justamente donde en_curso se equivoca: lo cuenta.
        self.assertEqual(f["en_curso"], 6)
        self.assertEqual(f["en_curso"] - a["total"], 1)

    def test_activos_reparte_por_etapa(self):
        a = self._funnel(90)["activos"]
        self.assertEqual(a["en_pro"], 3)
        self.assertEqual(a["en_plus"], 2)
        self.assertEqual(a["en_pro"] + a["en_plus"], a["total"])

    def test_activos_trae_a_quien_y_cuanto_le_queda(self):
        a = self._funnel(90)["activos"]
        self.assertEqual(len(a["usuarios"]), a["total"])
        for u in a["usuarios"]:
            self.assertTrue(u["email"], "un activo sin email")
            self.assertIn(u["stage"], ("pro", "plus"))
            self.assertGreater(u["days_left"], 0, f"{u['email']} activo con 0 días")
            self.assertLessEqual(u["days_left"], tr.TRIAL_TOTAL_DAYS)
        # Ordenados por el que se vence primero: es la lista de a quién llamar.
        dias = [u["days_left"] for u in a["usuarios"]]
        self.assertEqual(dias, sorted(dias))

    def test_activos_no_depende_de_la_ventana_de_dias(self):
        # "Quiénes la tienen activa HOY" es una foto del presente: no puede
        # cambiar según si mirás 30 o 365 días para atrás.
        self.assertEqual(self._funnel(30)["activos"]["total"],
                         self._funnel(365)["activos"]["total"])

    def test_un_trial_vencido_no_figura_como_activo(self):
        a = self._funnel(365)["activos"]
        ids = {u["id"] for u in a["usuarios"]}
        for uid in self.term_sin_pagar + [self.viejo]:
            self.assertNotIn(uid, ids, "un trial vencido aparece como activo")

    # ── lo que encontró el ataque adversarial (todos reproducidos) ──────────

    def test_un_checkout_abandonado_no_es_una_conversion(self):
        """El peor de todos: /api/billing/subscribe deja una fila 'pending'
        apenas se genera el link de pago —antes de que entre un peso— y el cron
        la pasa a 'cancelled' a los 7 días. Contando esas filas, 3 personas que
        abrieron el checkout y se arrepintieron + 1 que pagó daban 100% de
        conversión cuando la respuesta es 25%. Abandonar un checkout es lo más
        común que hay: el error inflaba justo el número con el que se decide
        escalar el gasto."""
        ini = self.ahora - timedelta(days=30)
        fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
        ids = []
        for _ in range(3):
            cur = self.conn.execute(
                """INSERT INTO users (email, password_hash, approved, email_verified, tier,
                                      trial_started_at, trial_used_at, trial_ends_at,
                                      credit_active_until)
                   VALUES (?, 'x', 1, 1, 'pro', ?, ?, ?, ?)""",
                (f"abandono-{uuid.uuid4().hex[:6]}@rendi.test", _iso(ini), _iso(ini),
                 _iso(fin), _iso(fin)))
            uid = cur.lastrowid
            ids.append(uid)
            self.conn.execute(
                """INSERT INTO subscriptions (user_id, status, external_reference, period,
                                              amount_ars, created_at)
                   VALUES (?, 'cancelled', ?, 'monthly', 0, ?)""",
                (uid, f"aband-{uid}", _iso(ini + timedelta(days=2)).replace("T", " ")[:19]))
        self.conn.commit()
        try:
            f = self._funnel(90)
            # Los 3 abandonos NO suman: convirtieron sigue siendo los 4 que pagaron.
            self.assertEqual(f["convirtieron"], 4,
                             "un checkout abandonado se está contando como conversión")
            self.assertLessEqual(f["pct_conversion_cerrada"] or 0, 100.0)
        finally:
            for uid in ids:
                self.conn.execute("DELETE FROM subscriptions WHERE user_id=?", (uid,))
                self.conn.execute("DELETE FROM users WHERE id=?", (uid,))
            self.conn.commit()

    def test_la_etapa_del_pago_sale_de_cuando_entro_la_plata(self):
        """subscriptions.created_at es cuándo se generó el LINK, no cuándo se
        pagó: el webhook actualiza esa misma fila sin tocarlo. Alguien que abrió
        el checkout el día 13 y pagó el 20 —ya terminado el trial— figuraba como
        'pagó durante los días de Plus'."""
        # Se mide el DELTA: la cohorte de la clase ya trae un pago "después".
        antes = self._funnel(90)["cuando_pagan"]
        ini = self.ahora - timedelta(days=30)
        fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
        cur = self.conn.execute(
            """INSERT INTO users (email, password_hash, approved, email_verified, tier,
                                  trial_started_at, trial_used_at, trial_ends_at,
                                  credit_active_until)
               VALUES (?, 'x', 1, 1, 'pro', ?, ?, ?, ?)""",
            (f"tarde-{uuid.uuid4().hex[:6]}@rendi.test", _iso(ini), _iso(ini),
             _iso(fin), _iso(fin)))
        uid = cur.lastrowid
        self.conn.execute(                       # link el día 13
            """INSERT INTO subscriptions (user_id, status, external_reference, period,
                                          amount_ars, created_at)
               VALUES (?, 'authorized', ?, 'monthly', 12100, ?)""",
            (uid, f"link-{uid}", _iso(ini + timedelta(days=13)).replace("T", " ")[:19]))
        self.conn.execute(                       # plata el día 20
            """INSERT INTO credit_ledger (user_id, kind, amount_usd, days_delta, created_at)
               VALUES (?, 'payment', 9.0, 30, ?)""",
            (uid, _iso(ini + timedelta(days=20)).replace("T", " ")[:19]))
        self.conn.commit()
        try:
            c = self._funnel(90)["cuando_pagan"]
            self.assertEqual(c["despues"] - antes["despues"], 1,
                             "el pago del día 20 no se contó como 'después de que terminó'")
            self.assertEqual(c["durante_plus"], antes["durante_plus"],
                             "se movió el pago del día 20 a la etapa Plus (la fecha del LINK)")
        finally:
            self.conn.execute("DELETE FROM credit_ledger WHERE user_id=?", (uid,))
            self.conn.execute("DELETE FROM subscriptions WHERE user_id=?", (uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (uid,))
            self.conn.commit()

    def test_el_import_que_disparo_la_activacion_cuenta(self):
        """El botón estrella del trial vive en la pantalla de 'importación
        terminada', así que por ese camino el batch se crea MINUTOS ANTES de que
        exista trial_started_at. Con la ventana por instante quedaba excluido
        por definición justo el caso más común, y el paso 'la app con datos
        adentro' mostraba 20% donde la respuesta era 100%."""
        ini = self.ahora - timedelta(days=20)
        fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
        cur = self.conn.execute(
            """INSERT INTO users (email, password_hash, approved, email_verified, tier,
                                  trial_started_at, trial_used_at, trial_ends_at,
                                  credit_active_until)
               VALUES (?, 'x', 1, 1, 'pro', ?, ?, ?, ?)""",
            (f"desde-import-{uuid.uuid4().hex[:6]}@rendi.test", _iso(ini), _iso(ini),
             _iso(fin), _iso(fin)))
        uid = cur.lastrowid
        self.conn.execute(
            """INSERT INTO import_batches (id, user_id, broker, parser_format, file_name,
                                           file_hash, status, created_at)
               VALUES (?, ?, 'Cocos', 'cocos', 'm.csv', ?, 'confirmed', ?)""",
            (uuid.uuid4().hex[:12], uid, uuid.uuid4().hex[:12],
             _iso(ini - timedelta(minutes=4)).replace("T", " ")[:19]))
        self.conn.commit()
        try:
            ids = {r["id"] for r in self.conn.execute(
                """SELECT DISTINCT u.id FROM users u JOIN import_batches b ON b.user_id=u.id
                    WHERE b.status='confirmed'
                      AND substr(b.created_at,1,10)
                          >= substr(replace(u.trial_started_at,'T',' '),1,10)""")}
            self.assertIn(uid, ids,
                          "el import que disparó la activación quedó afuera del embudo")
        finally:
            self.conn.execute("DELETE FROM import_batches WHERE user_id=?", (uid,))
            self.conn.execute("DELETE FROM users WHERE id=?", (uid,))
            self.conn.commit()

    def test_la_etapa_de_los_activos_coincide_con_lo_que_hizo_el_cron(self):
        """La cohorte del día 7, hora por hora. El cron corta por FECHA y baja a
        toda la cohorte de una en la madrugada; si la etiqueta del panel cortara
        por instante, diría 'en la semana de Pro' sobre gente que ya tiene Plus
        en su app — y el reparto cambiaría según la hora en que se abre el
        panel."""
        dia7 = (self.ahora - timedelta(days=tr.TRIAL_PRO_DAYS)).date()
        ids = []
        for h in (0, 6, 12, 18, 23):
            ini = datetime.combine(dia7, datetime.min.time()) + timedelta(hours=h, minutes=30)
            fin = ini + timedelta(days=tr.TRIAL_TOTAL_DAYS)
            cur = self.conn.execute(
                """INSERT INTO users (email, password_hash, approved, email_verified, tier,
                                      trial_started_at, trial_used_at, trial_ends_at,
                                      credit_active_until)
                   VALUES (?, 'x', 1, 1, 'pro', ?, ?, ?, ?)""",
                (f"h{h}-{uuid.uuid4().hex[:6]}@rendi.test", _iso(ini), _iso(ini),
                 _iso(fin), _iso(fin)))
            ids.append(cur.lastrowid)
        self.conn.commit()
        try:
            tr.step_down_due_trials(self.conn)          # el cron de la madrugada
            reales = {r["id"] for r in self.conn.execute(
                f"SELECT id FROM users WHERE tier='plus' AND id IN ({','.join('?'*len(ids))})",
                ids)}
            self.assertEqual(len(reales), len(ids), "el cron no bajó a toda la cohorte")
            a = tr.activos(self.conn)
            etiquetas = {u["id"]: u["stage"] for u in a["usuarios"] if u["id"] in set(ids)}
            for uid, etapa in etiquetas.items():
                self.assertEqual(etapa, "plus",
                                 f"uid {uid} etiquetado '{etapa}' con users.tier='plus'")
        finally:
            for uid in ids:
                self.conn.execute("DELETE FROM credit_ledger WHERE user_id=?", (uid,))
                self.conn.execute("DELETE FROM users WHERE id=?", (uid,))
            self.conn.commit()

    # ── el endpoint ─────────────────────────────────────────────────────────

    def test_solo_admin(self):
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"pelado-{uuid.uuid4().hex[:6]}@rendi.test",))
        self.conn.commit()
        r = self.client.get("/api/admin/billing/trial-funnel",
                            headers={"Authorization": f"Bearer {main.create_token(cur.lastrowid)}"})
        self.assertIn(r.status_code, (401, 403))

    def test_las_palancas_viajan_al_panel(self):
        f = self._funnel(90)
        self.assertIn("enabled", f)
        self.assertIn("monthly_cap", f)
        self.assertIn("activados_este_mes", f)


if __name__ == "__main__":
    unittest.main()
