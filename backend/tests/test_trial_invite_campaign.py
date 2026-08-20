"""Campaña por tandas: avisar que la prueba gratis está disponible.

Se manda de a 50 al azar. Lo que estos tests protegen, en orden:

  1. Que la SEGUNDA tanda no repita a nadie de la primera — es la razón de ser
     de la campaña. Si se repite, el mismo usuario recibe el mismo aviso dos
     veces y la lista nunca se vacía.
  2. Que no se invite a quien NO puede aceptar. El filtro es el mismo
     `trial.eligibility()` que decide si el botón aparece: invitar a alguien que
     entra y no encuentra nada es peor que no invitarlo.
  3. Que un envío fallido NO deje a la persona marcada: tiene que volver al
     bolillero, porque el aviso no llegó.

Corre con: cd backend && python3 -m pytest tests/test_trial_invite_campaign.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main
from billing import trial as tr


class CampanaDeInvitacion(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.conn = main.get_db()
        try:
            self.conn.rollback()
        except Exception:
            pass
        for t in ("credit_ledger", "subscriptions", "trial_consumed", "trial_email_log",
                  "operations", "positions", "brokers", "users"):
            try:
                self.conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved, email_verified, is_admin) "
            "VALUES (?, 'x', 1, 1, 1)", (f"admin-{uuid.uuid4().hex[:8]}@rendi.test",))
        self.admin = cur.lastrowid
        self.conn.commit()
        self.headers = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        os.environ.pop("TRIALS_ENABLED", None)
        os.environ.pop("TRIALS_MONTHLY_CAP", None)
        self.addCleanup(self.conn.close)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _users(self, n, **kw):
        ids = []
        for _ in range(n):
            cur = self.conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, "
                "                   is_admin, managed_by) VALUES (?, 'x', 1, ?, 0, ?)",
                (f"u-{uuid.uuid4().hex[:10]}@rendi.test",
                 kw.get("email_verified", 1), kw.get("managed_by")))
            ids.append(cur.lastrowid)
        self.conn.commit()
        return ids

    def _correr(self, confirm=True, limit=50, ok=True):
        with patch("billing.emails.send_trial_invite", return_value=ok) as spy:
            r = self.client.post("/api/admin/email/trial-invite",
                                 json={"confirm": confirm, "limit": limit},
                                 headers=self.headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), spy

    def _avisados(self):
        return {r["id"] for r in self.conn.execute(
            "SELECT id FROM users WHERE trial_invite_email_sent_at IS NOT NULL")}

    # ── la razón de ser de la campaña ───────────────────────────────────────

    def test_la_segunda_tanda_no_repite_a_nadie_de_la_primera(self):
        self._users(120)
        primera, _ = self._correr(limit=50)
        avisados_1 = self._avisados()
        segunda, _ = self._correr(limit=50)
        avisados_2 = self._avisados() - avisados_1

        self.assertEqual(primera["sent_count"], 50)
        self.assertEqual(segunda["sent_count"], 50)
        self.assertEqual(len(avisados_1 & avisados_2), 0,
                         "hay gente que recibió el aviso en las dos tandas")
        self.assertEqual(len(avisados_1 | avisados_2), 100)

    def test_la_lista_se_vacia_y_la_ultima_tanda_es_mas_chica(self):
        self._users(60)
        self._correr(limit=50)
        ultima, _ = self._correr(limit=50)
        self.assertEqual(ultima["sent_count"], 10)
        self.assertEqual(ultima["quedan_despues"], 0)
        vacia, spy = self._correr(limit=50)
        self.assertEqual(vacia["sent_count"], 0)
        spy.assert_not_called()

    def test_el_sorteo_es_al_azar(self):
        # Dos corridas sobre el mismo padrón no pueden dar la misma tanda
        # siempre; si diera, el "aleatorio" sería en realidad "los primeros N".
        self._users(100)
        a, _ = self._correr(confirm=False, limit=20)
        b, _ = self._correr(confirm=False, limit=20)
        ids_a = [x["id"] for x in a["recipients"]]
        ids_b = [x["id"] for x in b["recipients"]]
        self.assertNotEqual(ids_a, ids_b)

    # ── a quién NO se invita ────────────────────────────────────────────────

    def test_no_se_invita_a_quien_no_podria_aceptar(self):
        libres = self._users(3)
        usado = self._users(1)[0]
        tr.start(self.conn, usado)                      # ya está en su prueba
        admin_extra = self._users(1)[0]
        self.conn.execute("UPDATE users SET is_admin=1 WHERE id=?", (admin_extra,))
        sin_verificar = self._users(1, email_verified=0)[0]
        gestionado = self._users(1, managed_by=self.admin)[0]
        self.conn.commit()

        res, _ = self._correr(confirm=False)
        invitados = {x["id"] for x in res["recipients"]}
        self.assertEqual(invitados, set(libres))
        for quien, etiqueta in ((usado, "ya usó el trial"), (admin_extra, "admin"),
                                (sin_verificar, "sin verificar"), (gestionado, "cuenta de asesor")):
            self.assertNotIn(quien, invitados, f"se invitó a {etiqueta}")

    def test_si_el_trial_esta_apagado_no_invita_a_nadie(self):
        # Prometer algo que el server no va a habilitar es el peor mail posible.
        self._users(10)
        os.environ["TRIALS_ENABLED"] = "false"
        try:
            res, spy = self._correr(limit=50)
        finally:
            os.environ.pop("TRIALS_ENABLED", None)
        self.assertEqual(res["sent_count"], 0)
        spy.assert_not_called()

    # ── el dry run no toca nada ─────────────────────────────────────────────

    def test_el_dry_run_no_manda_ni_marca(self):
        self._users(30)
        res, spy = self._correr(confirm=False, limit=10)
        spy.assert_not_called()
        self.assertTrue(res["dry_run"])
        self.assertEqual(len(res["recipients"]), 10)
        self.assertEqual(res["elegibles"], 30)
        self.assertEqual(res["quedan_despues"], 20)
        self.assertEqual(self._avisados(), set())

    # ── fallas ──────────────────────────────────────────────────────────────

    def test_si_el_envio_falla_la_persona_vuelve_al_bolillero(self):
        self._users(5)
        res, _ = self._correr(limit=5, ok=False)
        self.assertEqual(res["sent_count"], 0)
        self.assertEqual(res["failed_count"], 5)
        self.assertEqual(self._avisados(), set(),
                         "quedaron marcados como avisados sin que el mail saliera")
        # Y la próxima corrida los agarra de nuevo.
        ok, _ = self._correr(limit=5)
        self.assertEqual(ok["sent_count"], 5)

    def test_solo_admin(self):
        pelado = self._users(1)[0]
        r = self.client.post("/api/admin/email/trial-invite", json={"confirm": False},
                             headers={"Authorization": f"Bearer {main.create_token(pelado)}"})
        self.assertIn(r.status_code, (401, 403))

    # ── el texto del mail ───────────────────────────────────────────────────

    def test_las_dos_variantes_prometen_lo_mismo(self):
        """Cambia la redacción, no la promesa. Las tres tienen que decir el
        plazo real, que no se pide tarjeta y que no se renueva sola — son las
        tres cosas que frenan a alguien antes de apretar, y una variante que se
        olvide de alguna convierte peor por una razón que no es el mensaje."""
        from billing import emails
        for v in emails.TRIAL_INVITE_VARIANTS:
            capt = {}
            with patch("billing.emails._send",
                       side_effect=lambda to, s, h, t, **kw: capt.update(asunto=s, texto=t) or True):
                emails.send_trial_invite(to="x@y.z", user_name="Nico", variant=v,
                                         pro_days=tr.TRIAL_PRO_DAYS,
                                         plus_days=tr.TRIAL_PLUS_DAYS,
                                         total_days=tr.TRIAL_TOTAL_DAYS)
            texto = capt["texto"].lower()
            self.assertTrue(capt.get("asunto"), f"variante {v} sin asunto")
            self.assertIn(str(tr.TRIAL_TOTAL_DAYS), capt["texto"], f"variante {v}: sin el plazo")
            self.assertTrue(("tarjeta" in texto),
                            f"variante {v}: no aclara que no se pide tarjeta")
            self.assertTrue(("no se renueva sola" in texto or "sin renovación automática" in texto),
                            f"variante {v}: no aclara que no se renueva sola")
            # Lo que el mail tiene que HACER, más allá de la redacción. El
            # "ahora" no es adorno: la campaña le llega a gente que ya usa Rendi
            # hace rato, y lo primero que tiene que entender es que esto es
            # NUEVO y está disponible para ella, no una publicidad genérica.
            self.assertIn("ahora podés probar el plan pro gratis", texto,
                          f"variante {v}: no avisa que la prueba ya está disponible")
            self.assertIn("se te abren con pro", texto,
                          f"variante {v}: no anticipa nada de lo que da Pro")
            self.assertIn("/planes", capt["texto"],
                          f"variante {v}: sin link para activarla")
            self.assertIn("activá tu prueba", texto,
                          f"variante {v}: el link no se lee como la acción")

    def test_el_anticipo_de_pro_no_promete_lo_que_no_hay(self):
        """Los ganchos describen features REALES del plan (PRO_FEATURES del
        catálogo). Un mail que promete algo que después no está es la peor
        primera impresión posible, y encima llega justo cuando la persona entra
        a mirar."""
        from billing import emails
        self.assertGreaterEqual(len(emails._PRO_GANCHOS), 3)
        junto = " ".join(emails._PRO_GANCHOS).lower()
        for concreto in ("chat libre", "60 análisis", "brokers"):
            self.assertIn(concreto, junto, f"falta el gancho de {concreto}")

    def test_una_variante_inventada_cae_en_la_default(self):
        from billing import emails
        capt = {}
        with patch("billing.emails._send",
                   side_effect=lambda to, s, h, t, **kw: capt.update(asunto=s) or True):
            emails.send_trial_invite(to="x@y.z", variant="no-existe")
        self.assertIn("ahora podés probar", capt["asunto"].lower())


if __name__ == "__main__":
    unittest.main()
