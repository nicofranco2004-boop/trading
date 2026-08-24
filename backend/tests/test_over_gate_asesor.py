"""`over` destruye en los dos flujos igual — pero sólo en uno se pregunta.

🔴 EL PUNTO DE PARTIDA: `over` NO "sólo avisaba". Con el modo override (los 7
brokers de foto), `build_tenencia_seed_txs` ya emitía una VENTA sintética por
cada `over`, sin marca de aprobación, y el confirm la aplicaba. La pantalla, en
cambio, lo mostraba como un aviso pasivo. Medido sobre la copia de prod del
2026-08-16: 180 reducciones aplicadas en 67 batches, de las cuales 60 eran
`over`.

POR QUÉ LA CASILLA VA SÓLO PARA EL ASESOR. Acá NO vale el argumento de "distinta
consecuencia" que se usó para `fecha_desconocida` — un recorte destruye igual en
los dos flujos. Vale el otro: prender la casilla para todos rompe un mecanismo
que hoy FUNCIONA. De los 21 `over` reales reconstruibles en prod, en 19 la foto
tenía razón y el recorte fue correcto; no apareció ni un caso donde `over` haya
destruido una tenencia real. Ponerle fricción a eso, para ~140 usuarios que
suben su propia foto y que en su mayoría no sabrían qué contestar, sería
cambiar aciertos por preguntas. Mismo criterio que con la fecha de Cocos.

Lo que cambia en el flujo del asesor: la reducción cae sobre la cuenta de un
tercero que no está mirando, y `over` es el único balde cuya CANTIDAD no tiene
respaldo independiente (`snapshots.holdings_json` guarda `value_usd` → verifica
composición, no cantidades).

Corre con: cd backend && python3 -m pytest tests/test_over_gate_asesor.py
"""
import io
import json
import unittest
import uuid

import main
from fastapi.testclient import TestClient
from importing import tenencia as tn

FOTO = "2026-06-30"
NOMBRE = f"portfolio_report_{FOTO.replace('-', '')}.csv"
# 100 YPFD y la foto dice 40 → `over` de 60. MELI y GGAL coinciden y están para
# que el recorte NO dispare el cap del 50%: cortar 2.700.000 sobre 10.560.000 es
# el 25,6% del valor y 1 de 3 activos. (La primera versión de este fixture tenía
# un solo activo y el cap se comía el caso — el test fallaba por el fixture, no
# por el código.)
MOV = ("nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;"
       "instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;otros;total\n"
       "1;1;04-01-2026;04-01-2026;Compra;YPF (YPFD);ARS;BYMA;100;45000,00;4500000,00;0;0;0;0;4500000,00\n"
       "2;2;05-01-2026;05-01-2026;Compra;Mercado Libre (MELI);ARS;BYMA;100;60000,00;6000000,00;0;0;0;0;6000000,00\n"
       "3;3;06-01-2026;06-01-2026;Compra;Galicia (GGAL);ARS;BYMA;1000;60,00;60000,00;0;0;0;0;60000,00\n")
FOTO_CSV = ("instrumento;cantidad;precio;moneda;total\n"
            "YPF (YPFD);40;45000,00;ARS;1800000,00\n"
            "Mercado Libre (MELI);100;60000,00;ARS;6000000,00\n"
            "Galicia (GGAL);1000;60,00;ARS;60000,00\n"
            "ARS;0;0;ARS;0\n")


def _user(conn, email, tier=None, approved=1):
    return conn.execute(
        "INSERT INTO users (email, password_hash, approved, tier) VALUES (?,'x',?,?)",
        (email, approved, tier)).lastrowid


class OverGateTest(unittest.TestCase):
    def setUp(self):
        self.http = TestClient(main.app)
        tag = uuid.uuid4().hex[:10]
        conn = main.get_db()
        self.advisor = _user(conn, f"ov-asesor-{tag}@rendi.test", tier="advisor")
        self.client_uid = _user(conn, f"ov-cliente-{tag}@rendi.test", approved=0)
        self.solo = _user(conn, f"ov-solo-{tag}@rendi.test")
        conn.execute("UPDATE users SET managed_by=? WHERE id=?", (self.advisor, self.client_uid))
        conn.execute(
            "INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, "
            "permission, status, label) VALUES (?,?,'managed','read_write','active','C')",
            (self.advisor, self.client_uid))
        for u in (self.client_uid, self.solo):
            conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                         (u, "Cocos", "ARS"))
        conn.commit(); conn.close()

    def tearDown(self):
        conn = main.get_db()
        try:
            conn.execute("DELETE FROM advisor_clients WHERE advisor_uid=?", (self.advisor,))
            conn.commit()
        finally:
            conn.close()

    def _headers(self, uid, ctx=None):
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        if ctx:
            h["X-Rendi-Client-Id"] = str(ctx)
        return h

    def _flujo(self, auth_uid, ctx=None):
        h = self._headers(auth_uid, ctx)
        r = self.http.post("/api/imports/preview",
                           files={"file": ("mov.csv", io.BytesIO(MOV.encode()), "text/csv")},
                           data={"broker": "Cocos", "format": "cocos"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.http.post("/api/imports/confirm",
                           json={"session_id": r.json()["session_id"]}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.http.post("/api/imports/tenencia/preview",
                           files={"file": (NOMBRE, io.BytesIO(FOTO_CSV.encode()), "text/csv")},
                           data={"broker": "Cocos", "format": "cocos"}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json(), h

    def _qty(self, uid, asset="YPFD"):
        conn = main.get_db()
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(quantity),0) q FROM positions WHERE user_id=? "
                "AND COALESCE(is_cash,0)=0 AND asset=?", (uid, asset)).fetchone()
            return float(row["q"] or 0)
        finally:
            conn.close()

    # ── el usuario en su propia cuenta: nada cambia ─────────────────────────
    def test_en_su_cuenta_el_ajuste_se_aplica_como_siempre(self):
        j, h = self._flujo(self.solo)
        self.assertEqual([(x["ticker"], x["rendi"], x["tenencia"]) for x in j["over"]],
                         [("YPFD", 100.0, 40.0)])
        # No hay casilla: no está en `no_reconciliable`.
        self.assertNotIn("YPFD", {x["ticker"] for x in j["no_reconciliable"]})
        self.assertEqual([x["ticker"] for x in j["override"]["reduced"]], ["YPFD"])
        r = self.http.post("/api/imports/confirm",
                           json={"session_id": j["session_id"]}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._qty(self.solo), 40.0, places=4)

    # ── el asesor: la reducción queda armada y NO entra sola ───────────────
    def test_el_asesor_tiene_que_marcarla(self):
        j, h = self._flujo(self.advisor, ctx=self.client_uid)
        dud = {x["ticker"]: x for x in j["no_reconciliable"]}
        self.assertIn("YPFD", dud)
        self.assertEqual(dud["YPFD"]["motivo"], tn.MOTIVO_OVER)
        self.assertTrue(dud["YPFD"]["requiere_aprobacion"])
        self.assertEqual(dud["YPFD"]["rendi_qty"], 100.0)
        self.assertEqual(dud["YPFD"]["foto_qty"], 40.0)
        # Confirmar SIN aprobar: la tenencia no se toca.
        r = self.http.post("/api/imports/confirm",
                           json={"session_id": j["session_id"]}, headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._qty(self.client_uid), 100.0, places=4,
                               msg="sin aprobar, la reducción NO puede entrar")

    def test_si_la_marca_el_ajuste_entra_igual_que_antes(self):
        # ⭐ El control positivo. Sin esto el test de arriba pasaría también si
        # la venta directamente no se hubiera armado — y entonces la casilla
        # sería decorativa, que es el bug que ya encontramos con el cap.
        j, h = self._flujo(self.advisor, ctx=self.client_uid)
        r = self.http.post("/api/imports/confirm",
                           json={"session_id": j["session_id"], "aprobar_tickers": ["YPFD"]},
                           headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._qty(self.client_uid), 40.0, places=4)

    def test_el_over_aprobable_NO_aparece_tambien_como_ya_ajustado(self):
        # El frontend filtra `over` por lo que espera aprobación; el backend
        # tiene que darle con qué: el mismo ticker en los dos lados.
        j, _ = self._flujo(self.advisor, ctx=self.client_uid)
        pendientes = {x["ticker"] for x in j["no_reconciliable"]
                      if x.get("requiere_aprobacion")}
        self.assertEqual({x["ticker"] for x in j["over"]} - pendientes, set(),
                         "todo `over` del asesor tiene que estar esperando decisión")


class OverrideInfoPersistidoTest(OverGateTest):
    """El instrumento que cierra el punto ciego.

    Los `over` que las guardas frenan no dejan rastro: hoy sólo hay un
    `log.warning`. Todo lo que se sabe de `over` está medido sobre la población
    que sobrevivió tres filtros. Con `override_info` en el batch, en un mes se
    puede medir la tasa real.
    """

    def _override_guardado(self, sid):
        conn = main.get_db()
        try:
            row = conn.execute("SELECT override_info FROM import_batches WHERE id=?",
                               (sid,)).fetchone()
            return json.loads(row["override_info"]) if row and row["override_info"] else None
        finally:
            conn.close()

    def test_se_guarda_con_el_batch(self):
        j, _ = self._flujo(self.solo)
        ov = self._override_guardado(j["session_id"])
        self.assertIsNotNone(ov, "el override tiene que quedar guardado con el batch")
        self.assertFalse(ov["capped"])

    def test_guarda_el_over_COMPLETO_antes_de_las_guardas(self):
        # 🔴 Es el punto entero: `reduced` es lo que SOBREVIVIÓ. Sin
        # `over_visto` no hay denominador, y se sigue midiendo sobre la muestra
        # ya filtrada.
        j, _ = self._flujo(self.solo)
        ov = self._override_guardado(j["session_id"])
        vistos = [h for p in ov.get("particiones", [ov]) for h in p.get("over_visto", [])]
        self.assertEqual([(v["ticker"], v["rendi"], v["foto"]) for v in vistos],
                         [("YPFD", 100.0, 40.0)])

    def test_guarda_los_dos_motivos_de_freno_por_separado(self):
        # "tiene datos a mano" y "vive en la otra partición del par" son
        # hipótesis distintas sobre por qué apareció el `over`. Mezcladas en
        # `skipped_manual` el dato se perdía.
        j, _ = self._flujo(self.solo)
        ov = self._override_guardado(j["session_id"])
        for p in ov.get("particiones", [ov]):
            self.assertIn("frenado", p)
            self.assertIn("manual", p["frenado"])
            self.assertIn("sibling", p["frenado"])
            self.assertIn("cap", p)
            self.assertIn("n_current", p["cap"])

    def test_guarda_por_PARTICION_y_no_agregado(self):
        # Los agregados concatenan listas y hacen OR del cap. La hipótesis de
        # doble partición se responde comparando la pata en pesos con la de
        # dólares — hay que poder verlas separadas.
        j, _ = self._flujo(self.solo)
        ov = self._override_guardado(j["session_id"])
        self.assertIn("particiones", ov)
        self.assertTrue(ov["particiones"])
        self.assertEqual(ov["particiones"][0]["broker"], "Cocos")
        self.assertEqual(ov["particiones"][0]["currency"], "ARS")


if __name__ == "__main__":
    unittest.main()
