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


if __name__ == "__main__":
    unittest.main()
