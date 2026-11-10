"""Regalo masivo: N días de plan a todas las cuentas que no pagan.

Pedido de Nico (10/11): «5 días de plan más a todos los usuarios; los que ya
pagan, que no tengan más días». Todo pasa por el endpoint real con un admin
logueado, como en producción: vista previa, regalo y doble click.

Lo que se cuida en cada caso:
  • quien paga (suscripción activa, o días pagos que le quedan) no recibe nada
    aunque su id llegue en el pedido;
  • la prueba gratis se alarga SIN dejar de ser la prueba (si sólo se movía el
    vencimiento, el billing la pasaba a tratar como un regalo);
  • el regalo vigente se alarga en el MISMO plan, sumando a su vencimiento;
  • la cuenta en pausa vuelve a entrar (se mide con un pedido que el muro frena,
    no leyendo una columna);
  • a quien todavía puede activar sus 20 días de prueba no se le tapa;
  • un segundo click el mismo día no suma otra vez.
"""
import unittest
import uuid
from datetime import datetime, timedelta

import main
from billing import trial
from fastapi.testclient import TestClient


def _iso(dias):
    return (datetime.utcnow() + timedelta(days=dias)).isoformat()


def _fecha(valor):
    return datetime.fromisoformat(str(valor).replace("Z", ""))


class RegaloMasivoTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin = self._user(conn, "admin", is_admin=1)
        # Paga, en el día de la renovación: sus días pagos vencieron hace un rato
        # y el cobro nuevo todavía no entró. Lo único que dice que paga es la
        # suscripción activa — si sólo se miraran los días, recibiría 5 de Pro
        # y el regalo le pisaría el precio de su plan.
        self.paga = self._user(conn, "paga", tier="plus", credit_active_until=_iso(-0.1),
                               credit_anchor_plan="plus", credit_anchor_amount_usd=9.99)
        conn.execute(
            """INSERT INTO subscriptions (user_id, external_reference, period, status, amount_ars)
               VALUES (?, ?, 'monthly', 'authorized', 10000)""",
            (self.paga, f"ref-{self.tag}"))
        # Canceló, pero le quedan días que pagó: también paga.
        self.cancelo = self._user(conn, "cancelo", tier="pro", credit_active_until=_iso(12),
                                  credit_anchor_plan="pro", credit_anchor_amount_usd=14.99)
        # En su prueba gratis: el vencimiento del crédito ES el de la prueba.
        fin_prueba = _iso(6)
        self.prueba = self._user(conn, "prueba", tier="plus", trial_used_at=_iso(-14),
                                 trial_started_at=_iso(-14), trial_ends_at=fin_prueba,
                                 credit_active_until=fin_prueba, email_verified=1)
        # Con un regalo de Plus vigente (sin costo).
        self.regalo = self._user(conn, "regalo", tier="plus", credit_active_until=_iso(10),
                                 credit_anchor_plan="plus", credit_anchor_amount_usd=0,
                                 trial_used_at=_iso(-90), email_verified=1)
        # Free de antes de los planes pagos, prueba ya usada.
        self.free = self._user(conn, "free", tier="free", trial_used_at=_iso(-60),
                               email_verified=1)
        # En pausa: nació sin plan gratis, se le terminó la prueba y no eligió.
        self.pausa = self._user(conn, "pausa", tier="plus", requires_plan=1,
                                email_verified=1, trial_used_at=_iso(-40),
                                trial_started_at=_iso(-40), trial_ends_at=_iso(-20),
                                credit_active_until=_iso(-20))
        # Todavía no verificó el mail: su prueba de 20 días está sin usar.
        self.sin_usar = self._user(conn, "sinusar", requires_plan=1, email_verified=0)
        self.asesor = self._user(conn, "asesor", tier="advisor")
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}

    def _user(self, conn, nombre, **cols):
        cols = {"email": f"{nombre}-{self.tag}@rendi.test", "password_hash": "x",
                "approved": 1, "name": nombre, **cols}
        cur = conn.execute(
            f"INSERT INTO users ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            tuple(cols.values()))
        return cur.lastrowid

    def _fila(self, uid):
        conn = main.get_db()
        try:
            return dict(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
        finally:
            conn.close()

    def _mios(self):
        return {self.paga, self.cancelo, self.prueba, self.regalo, self.free,
                self.pausa, self.sin_usar, self.asesor, self.admin}

    def _vista_previa(self):
        r = self.client.post("/api/admin/billing/regalo-masivo",
                             json={"days": 5}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _regalar(self, ids):
        r = self.client.post("/api/admin/billing/regalo-masivo",
                             json={"days": 5, "confirm": True, "ids": sorted(ids)},
                             headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_la_vista_previa_dice_a_quien_y_por_que_sin_tocar_nada(self):
        antes = {u: self._fila(u)["credit_active_until"] for u in self._mios()}
        vp = self._vista_previa()
        grupos = {c["id"]: c["grupo"] for c in vp["cuentas"] if c["id"] in self._mios()}
        motivos = {c["id"]: c["motivo"] for c in vp["excluidas"] if c["id"] in self._mios()}
        self.assertEqual(grupos, {self.prueba: "prueba", self.regalo: "regalo",
                                  self.free: "sin_plan", self.pausa: "sin_plan"})
        self.assertEqual(motivos, {self.paga: "paga", self.cancelo: "paga",
                                   self.sin_usar: "prueba_sin_usar",
                                   self.asesor: "asesor", self.admin: "admin"})
        despues = {u: self._fila(u)["credit_active_until"] for u in self._mios()}
        self.assertEqual(antes, despues)

    def test_quien_paga_no_recibe_dias_aunque_llegue_su_id(self):
        antes = {u: self._fila(u)["credit_active_until"] for u in (self.paga, self.cancelo)}
        res = self._regalar([self.paga, self.cancelo])
        self.assertEqual(res["regaladas"], [])
        self.assertEqual({s["motivo"] for s in res["salteadas"]}, {"paga"})
        for u, vence in antes.items():
            self.assertEqual(self._fila(u)["credit_active_until"], vence)

    def test_la_prueba_se_alarga_y_sigue_siendo_la_prueba(self):
        antes = self._fila(self.prueba)
        self._regalar([self.prueba])
        f = self._fila(self.prueba)
        self.assertAlmostEqual(
            (_fecha(f["credit_active_until"]) - _fecha(antes["credit_active_until"])).days, 5)
        self.assertEqual(f["credit_active_until"], f["trial_ends_at"])
        self.assertTrue(trial.credit_is_trial(f["credit_active_until"], f["trial_ends_at"]))
        self.assertIsNone(f["credit_anchor_plan"])   # no se volvió un "regalo"
        self.assertEqual(f["trial_started_at"], antes["trial_started_at"])
        conn = main.get_db()
        try:
            kinds = [r["kind"] for r in conn.execute(
                "SELECT kind FROM credit_ledger WHERE user_id=?", (self.prueba,))]
        finally:
            conn.close()
        # 'trial' contaría como una prueba ACTIVADA para el tope del mes.
        self.assertEqual(kinds, ["comp"])

    def test_el_regalo_vigente_suma_en_el_mismo_plan(self):
        antes = self._fila(self.regalo)
        self._regalar([self.regalo])
        f = self._fila(self.regalo)
        self.assertEqual(f["tier"], "plus")
        self.assertEqual(f["credit_anchor_plan"], "plus")
        self.assertAlmostEqual(
            (_fecha(f["credit_active_until"]) - _fecha(antes["credit_active_until"])).days, 5)

    def test_free_viejo_recibe_cinco_dias_de_pro(self):
        self._regalar([self.free])
        f = self._fila(self.free)
        self.assertEqual(f["tier"], "pro")
        faltan = (_fecha(f["credit_active_until"]) - datetime.utcnow()).total_seconds() / 86400
        self.assertTrue(4.9 < faltan <= 5.0, faltan)

    def test_la_cuenta_en_pausa_vuelve_a_entrar(self):
        """Comportamiento, no columnas: un pedido de datos que el muro frena."""
        h = {"Authorization": f"Bearer {main.create_token(self.pausa)}"}
        frenado = self.client.get("/api/me/reset-data/status", headers=h)
        self.assertEqual(frenado.status_code, main.CUENTA_EN_PAUSA, frenado.text)
        self._regalar([self.pausa])
        r = self.client.get("/api/me/reset-data/status", headers=h)
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_quien_tiene_la_prueba_sin_usar_no_se_le_tapa(self):
        self._regalar([self.sin_usar])
        f = self._fila(self.sin_usar)
        self.assertIsNone(f["credit_active_until"])
        conn = main.get_db()
        try:
            self.assertTrue(trial.eligibility(conn, self.sin_usar)["reason"]
                            in (None, "email_not_verified"))
        finally:
            conn.close()

    def test_el_segundo_click_no_suma_otra_vez(self):
        ids = [self.prueba, self.regalo, self.free, self.pausa]
        primero = self._regalar(ids)
        self.assertEqual(len(primero["regaladas"]), 4, primero)
        vence = {u: self._fila(u)["credit_active_until"] for u in ids}
        segundo = self._regalar(ids)
        self.assertEqual(segundo["regaladas"], [])
        self.assertEqual({s["motivo"] for s in segundo["salteadas"]}, {"ya_recibio"})
        self.assertEqual(vence, {u: self._fila(u)["credit_active_until"] for u in ids})
        motivos = {c["id"]: c["motivo"] for c in self._vista_previa()["excluidas"]}
        for u in ids:
            self.assertEqual(motivos[u], "ya_recibio")

    def test_sin_admin_no_se_puede(self):
        h = {"Authorization": f"Bearer {main.create_token(self.free)}"}
        r = self.client.post("/api/admin/billing/regalo-masivo", json={"days": 5}, headers=h)
        self.assertIn(r.status_code, (401, 403))




class LosTextosDelRegaloTest(unittest.TestCase):
    """Quien recibe un regalo es 'credit_only' sin suscripción, igual que quien
    cambió de plan, y por eso la pantalla le decía «Cambiaste de plan… con el
    crédito convertido» y el mail «tu suscripción expira… volvé a suscribirte».
    La regla de qué es un regalo es una sola (`credits.es_regalo`); acá se mide
    que llegue a la pantalla (`/api/auth/me`) y al mail del proceso nocturno
    real (`run_lifecycle_job`)."""

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.admin = RegaloMasivoTest._user(self, conn, "admin", is_admin=1)
        # Recibe el regalo por el botón masivo, como en producción.
        self.free = RegaloMasivoTest._user(self, conn, "free", tier="free",
                                           trial_used_at=_iso(-60), email_verified=1)
        fin = _iso(6)
        self.prueba = RegaloMasivoTest._user(self, conn, "prueba", tier="plus",
                                             trial_used_at=_iso(-14), trial_started_at=_iso(-14),
                                             trial_ends_at=fin, credit_active_until=fin,
                                             email_verified=1)
        # Canceló y le quedan días que pagó: su texto NO cambia.
        self.pago = RegaloMasivoTest._user(self, conn, "pago", tier="pro",
                                           credit_active_until=_iso(2.5),
                                           credit_anchor_plan="pro",
                                           credit_anchor_period="monthly",
                                           credit_anchor_amount_usd=14.99, email_verified=1)
        conn.commit()
        conn.close()
        r = self.client.post(
            "/api/admin/billing/regalo-masivo",
            json={"days": 5, "confirm": True, "ids": [self.free, self.prueba]},
            headers={"Authorization": f"Bearer {main.create_token(self.admin)}"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["regaladas"]), 2, r.text)

    def _me(self, uid):
        r = self.client.get("/api/auth/me",
                            headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_la_pantalla_sabe_que_es_un_regalo(self):
        me = self._me(self.free)
        self.assertEqual(me["access_mode"], "credit_only")
        self.assertIs(me["credit_es_regalo"], True)
        # La prueba alargada sigue siendo la prueba, y el pago sigue siendo pago.
        self.assertIs(self._me(self.prueba)["credit_es_regalo"], False)
        self.assertIs(self._me(self.pago)["credit_es_regalo"], False)

    def _avisos(self):
        from unittest.mock import patch
        from billing import emails, subscriptions
        conn = main.get_db()
        try:
            # 2,5 días antes de vencer: dentro de la ventana de 3 días del aviso.
            conn.execute("UPDATE users SET credit_active_until=? WHERE id=?",
                         (_iso(2.5), self.free))
            conn.commit()
            with patch.object(emails, "_send", return_value=True) as send:
                subscriptions.run_lifecycle_job(conn)
        finally:
            conn.close()
        por_mail = {}
        for c in send.call_args_list:
            por_mail.setdefault(c.args[0], []).append(
                (c.args[1], " ".join(str(a) for a in c.args[2:4])))
        return por_mail

    def test_el_aviso_de_vencimiento_del_regalo_no_habla_de_suscripcion(self):
        avisos = self._avisos()
        mios = [m for m in avisos.get(f"free-{self.tag}@rendi.test", []) if "vence en" in m[0]]
        self.assertEqual(len(mios), 1, avisos.get(f"free-{self.tag}@rendi.test"))
        asunto, cuerpo = mios[0]
        self.assertIn("regalo", asunto)
        self.assertIn("que te regalamos termina", cuerpo)
        self.assertNotIn("suscripci", cuerpo)
        self.assertNotIn("suscribi", cuerpo)
        # Y el de quien pagó sigue diciendo lo de siempre.
        pagos = [m for m in avisos.get(f"pago-{self.tag}@rendi.test", []) if "vence en" in m[0]]
        self.assertEqual(len(pagos), 1, avisos.get(f"pago-{self.tag}@rendi.test"))
        self.assertNotIn("regalo", pagos[0][0])
        self.assertIn("suscripción", pagos[0][1])


class LaCampañaDeRegaloUsaLaMismaReglaTest(unittest.TestCase):
    """La campaña «Regalo Pro» (`/api/admin/email/gift-plan`, only_gifted)
    tenía su propia copia de qué es un regalo; ahora usa `credits.es_regalo`.
    Un regalo VENCIDO (la cuenta todavía dice 'pro' porque el cron de la noche
    no corrió) no es un regalo: el mail le prometería algo que ya se terminó."""

    def test_sólo_cuenta_el_regalo_vigente(self):
        client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        admin = RegaloMasivoTest._user(self, conn, "admin", is_admin=1)
        vigente = RegaloMasivoTest._user(self, conn, "vigente", tier="pro", email_verified=1,
                                         credit_active_until=_iso(10), credit_anchor_plan="pro",
                                         credit_anchor_amount_usd=0)
        vencido = RegaloMasivoTest._user(self, conn, "vencido", tier="pro", email_verified=1,
                                         credit_active_until=_iso(-1), credit_anchor_plan="pro",
                                         credit_anchor_amount_usd=0)
        pagado = RegaloMasivoTest._user(self, conn, "pagado", tier="pro", email_verified=1,
                                        credit_active_until=_iso(10), credit_anchor_plan="pro",
                                        credit_anchor_amount_usd=14.99)
        conn.commit()
        conn.close()
        r = client.post("/api/admin/email/gift-plan", json={"only_gifted": True},
                        headers={"Authorization": f"Bearer {main.create_token(admin)}"})
        self.assertEqual(r.status_code, 200, r.text)
        ids = {x["id"] for x in r.json()["recipients"]}
        self.assertIn(vigente, ids)
        self.assertNotIn(vencido, ids)
        self.assertNotIn(pagado, ids)


if __name__ == "__main__":
    unittest.main()
