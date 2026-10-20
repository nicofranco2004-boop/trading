"""Una operación en dólares hecha "en Cocos" vive en 'Cocos · USD'.

El usuario ya no elige el sub-broker en dólares: elige el broker y la moneda, y
`_pata_de_la_moneda` lo traduce. Sin esto, una compra en dólares anotada a un
broker en pesos se descontaba de la caja de PESOS y su autodepósito se asentaba
como pesos (medido: un aporte de US$ 30.000 quedó como US$ 19).

Todo pasa por los endpoints (`/api/positions`, `/api/positions/sell`,
`/api/cash/flow`, `DELETE /api/positions/{id}`), que es el camino de la app.

Corre con: cd backend && python3 -m pytest tests/test_pata_de_la_moneda.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
from fastapi.testclient import TestClient

SUB = "Cocos · USD"


class PataDeLaMonedaTest(unittest.TestCase):
    def setUp(self):
        conn = main.get_db()
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"pata-{id(self)}@rendi.test", "x"))
        self.uid = cur.lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "Cocos", "ARS"))
        conn.commit()
        conn.close()
        self.client = TestClient(main.app)
        self.hdr = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    # ── ayudas ────────────────────────────────────────────────────────────
    def _post(self, url, body):
        return self.client.post(url, json=body, headers=self.hdr)

    def _q(self, sql, *args):
        conn = main.get_db()
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()

    def _caja(self, broker):
        conn = main.get_db()
        try:
            fila = main._efectivo.caja(conn, self.uid, broker)
            return float(fila["invested"] or 0) if fila else 0.0
        finally:
            conn.close()

    def _brokers(self):
        return {r["name"] for r in self._q(
            "SELECT name FROM brokers WHERE user_id=?", self.uid)}

    # ── compra ────────────────────────────────────────────────────────────
    def test_compra_en_dolares_en_cocos_va_a_la_pata_de_dolares(self):
        r = self._post("/api/positions", {
            "broker": "Cocos", "asset": "AAPL", "quantity": 20, "buy_price": 32.5,
            "currency": "USD", "asset_type": "CEDEAR", "entry_date": "2026-10-20"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["broker"], SUB)
        self.assertEqual(r.json()["currency"], "USD")
        self.assertIn(SUB, self._brokers())       # se creó solo
        # El sub-broker quedó colgado de Cocos (no es un broker suelto).
        padre = self._q("SELECT id FROM brokers WHERE user_id=? AND name='Cocos'", self.uid)[0]
        hijo = self._q("SELECT parent_broker_id FROM brokers WHERE user_id=? AND name=?",
                       self.uid, SUB)[0]
        self.assertEqual(hijo["parent_broker_id"], padre["id"])
        # La caja de pesos ni se tocó; la de dólares quedó en 0 (autodepósito − costo).
        self.assertEqual(self._caja("Cocos"), 0.0)
        self.assertAlmostEqual(self._caja(SUB), 0.0, places=6)
        # El autodepósito se anotó en DÓLARES, en la pata de dólares: US$ 650,
        # no 650 ÷ MEP.
        flujos = self._q("SELECT broker, monto_usd, monto_nativo FROM flujos_a_mano "
                         "WHERE user_id=? AND direction='deposit'", self.uid)
        self.assertEqual(len(flujos), 1)
        self.assertEqual(flujos[0]["broker"], SUB)
        self.assertAlmostEqual(flujos[0]["monto_usd"], 650.0, places=2)

    def test_compra_en_pesos_no_crea_la_pata_de_dolares(self):
        r = self._post("/api/positions", {
            "broker": "Cocos", "asset": "AAPL", "quantity": 1, "buy_price": 27780,
            "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["broker"], "Cocos")
        self.assertNotIn(SUB, self._brokers())

    def test_compra_sin_moneda_queda_donde_se_pidio(self):
        r = self._post("/api/positions", {
            "broker": "Cocos", "asset": "GGAL", "quantity": 1, "buy_price": 5000})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["broker"], "Cocos")
        self.assertEqual(r.json()["currency"], "ARS")

    def test_compra_en_pesos_pedida_en_la_pata_de_dolares_va_al_padre(self):
        self._post("/api/cash/flow", {"broker_name": "Cocos", "direction": "deposit",
                                      "amount": 100, "currency": "USD"})
        r = self._post("/api/positions", {
            "broker": SUB, "asset": "GGAL", "quantity": 1, "buy_price": 5000,
            "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["broker"], "Cocos")
        self.assertAlmostEqual(self._caja(SUB), 100.0, places=6)

    def test_compra_usa_los_dolares_depositados(self):
        r = self._post("/api/cash/flow", {"broker_name": "Cocos", "direction": "deposit",
                                          "amount": 1000, "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._caja(SUB), 1000.0, places=6)
        self.assertEqual(self._caja("Cocos"), 0.0)
        r = self._post("/api/positions", {
            "broker": "Cocos", "asset": "SPY", "quantity": 10, "buy_price": 13.5,
            "currency": "USD", "asset_type": "CEDEAR"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._caja(SUB), 865.0, places=6)
        # Alcanzaba la plata: no hubo autodepósito.
        n = self._q("SELECT COUNT(*) AS n FROM flujos_a_mano WHERE user_id=? "
                    "AND direction='deposit'", self.uid)[0]["n"]
        self.assertEqual(n, 1)   # sólo el depósito explícito

    def test_borrar_la_compra_devuelve_los_dolares_a_su_caja(self):
        self._post("/api/cash/flow", {"broker_name": "Cocos", "direction": "deposit",
                                      "amount": 1000, "currency": "USD"})
        pid = self._post("/api/positions", {
            "broker": "Cocos", "asset": "SPY", "quantity": 10, "buy_price": 13.5,
            "currency": "USD", "asset_type": "CEDEAR"}).json()["id"]
        r = self.client.delete(f"/api/positions/{pid}", headers=self.hdr)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._caja(SUB), 1000.0, places=6)
        self.assertEqual(self._caja("Cocos"), 0.0)

    # ── venta ─────────────────────────────────────────────────────────────
    def test_venta_en_dolares_en_cocos_cobra_en_la_caja_de_dolares(self):
        self._post("/api/cash/flow", {"broker_name": "Cocos", "direction": "deposit",
                                      "amount": 1000, "currency": "USD"})
        self._post("/api/positions", {
            "broker": "Cocos", "asset": "SPY", "quantity": 10, "buy_price": 13.5,
            "currency": "USD", "asset_type": "CEDEAR"})
        r = self._post("/api/positions/sell", {
            "broker": "Cocos", "asset": "SPY", "quantity": 10, "exit_price": 15,
            "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._caja(SUB), 1015.0, places=6)
        self.assertEqual(self._caja("Cocos"), 0.0)
        op = self._q("SELECT broker, pnl_usd, currency FROM operations "
                     "WHERE user_id=? AND op_type='Venta'", self.uid)[0]
        self.assertEqual(op["broker"], SUB)
        self.assertAlmostEqual(op["pnl_usd"], 15.0, places=2)

    def _lote(self, broker, asset, currency, qty, price, fecha):
        """Un lote escrito directo (como lo deja un import viejo o un dato legacy):
        así se puede tener dólares en la pata de pesos, que la API ya no crea."""
        conn = main.get_db()
        try:
            pid = conn.execute(
                "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, buy_price, "
                "invested, currency, entry_date, asset_type) VALUES (?,?,?,0,?,?,?,?,?,'CEDEAR')",
                (self.uid, broker, asset, qty, price, qty * price, currency, fecha)).lastrowid
            conn.commit()
            return pid
        finally:
            conn.close()

    def _cant(self, pid):
        r = self._q("SELECT quantity FROM positions WHERE id=?", pid)
        return float(r[0]["quantity"]) if r else 0.0

    def test_venta_fifo_por_moneda_en_toda_la_cuenta(self):
        # La pata en dólares existe (un depósito la crea).
        self._post("/api/cash/flow", {"broker_name": "Cocos", "direction": "deposit",
                                      "amount": 10, "currency": "USD"})
        pesos_viejo = self._lote("Cocos", "NFLX", "ARS", 50, 2244, "2026-01-10")
        usd_en_pesos = self._lote("Cocos", "NFLX", "USD", 2, 115, "2026-02-01")   # legacy
        pesos_nuevo = self._lote("Cocos", "NFLX", "ARS", 68, 2354, "2026-03-01")
        usd_nuevo = self._lote(SUB, "NFLX", "USD", 5, 120, "2026-06-01")

        # Venta de 3 en dólares, pedida "en Cocos": cierra primero el de dólares más
        # viejo (aunque esté en la pata de pesos) y 1 del siguiente en dólares. Los
        # de pesos —más viejos todavía— no se tocan.
        r = self._post("/api/positions/sell", {
            "broker": "Cocos", "asset": "NFLX", "quantity": 3, "exit_price": 130,
            "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._cant(usd_en_pesos), 0.0)
        self.assertEqual(self._cant(usd_nuevo), 4.0)
        self.assertEqual(self._cant(pesos_viejo), 50.0)
        self.assertEqual(self._cant(pesos_nuevo), 68.0)
        # Lo cobrado (3 × 130) entra a la caja de dólares; la de pesos ni se mueve.
        self.assertAlmostEqual(self._caja(SUB), 10 + 390.0, places=6)
        self.assertEqual(self._caja("Cocos"), 0.0)
        # Cada pedazo de la venta queda con el broker de SU lote y su ganancia:
        # (130−115)×2 = 30 y (130−120)×1 = 10.
        ops = self._q("SELECT broker, quantity, pnl_usd, currency FROM operations "
                      "WHERE user_id=? AND op_type='Venta' ORDER BY id", self.uid)
        self.assertEqual([(o["broker"], o["quantity"], o["currency"]) for o in ops],
                         [("Cocos", 2.0, "USD"), (SUB, 1.0, "USD")])
        self.assertAlmostEqual(sum(o["pnl_usd"] for o in ops), 40.0, places=2)

        # Venta en pesos pedida "en Cocos · USD": va a la caja de pesos y cierra el
        # de pesos más viejo, sin tocar los de dólares.
        r = self._post("/api/positions/sell", {
            "broker": SUB, "asset": "NFLX", "quantity": 10, "exit_price": 2500,
            "currency": "ARS", "tc_venta": 1500})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self._cant(pesos_viejo), 40.0)
        self.assertEqual(self._cant(pesos_nuevo), 68.0)
        self.assertEqual(self._cant(usd_nuevo), 4.0)
        self.assertAlmostEqual(self._caja("Cocos"), 25000.0, places=6)
        self.assertAlmostEqual(self._caja(SUB), 400.0, places=6)

    def test_venta_en_dolares_no_alcanza_no_usa_los_de_pesos(self):
        self._lote("Cocos", "NFLX", "ARS", 50, 2244, "2026-01-10")
        self._lote("Cocos", "NFLX", "USD", 2, 115, "2026-02-01")
        r = self._post("/api/positions/sell", {
            "broker": "Cocos", "asset": "NFLX", "quantity": 5, "exit_price": 130,
            "currency": "USD"})
        self.assertEqual(r.status_code, 400, r.text)
        # Rebotó entera: ni la pata en dólares quedó creada.
        self.assertNotIn(SUB, self._brokers())

    # ── deshacer del chat ─────────────────────────────────────────────────
    def test_deshacer_del_chat_devuelve_los_dolares_a_su_caja(self):
        self._post("/api/cash/flow", {"broker_name": "Cocos", "direction": "deposit",
                                      "amount": 1000, "currency": "USD"})
        pid = self._post("/api/positions", {
            "broker": "Cocos", "asset": "SPY", "quantity": 10, "buy_price": 13.5,
            "currency": "USD", "asset_type": "CEDEAR"}).json()["id"]
        self.assertAlmostEqual(self._caja(SUB), 865.0, places=6)
        bid = self._q("SELECT id FROM brokers WHERE user_id=? AND name='Cocos'", self.uid)[0]["id"]
        # Lo que anota el chat al registrar esa compra: el broker que ELIGIÓ (Cocos).
        main._LAST_CHAT_TRADE[self.uid] = {
            "kind": "buy", "position_id": pid, "cash_debited": 135, "autodeposit": 0,
            "broker_id": bid, "asset": "SPY", "quantity": 10, "summary": "compra", "ts": 0}
        import time as _t
        main._LAST_CHAT_TRADE[self.uid]["ts"] = _t.time()
        self.addCleanup(main._LAST_CHAT_TRADE.pop, self.uid, None)
        out = main._undo_last_trade_handler(self.uid)
        self.assertEqual(out.get("status"), "undone", out)
        self.assertAlmostEqual(self._caja(SUB), 1000.0, places=6)
        self.assertEqual(self._caja("Cocos"), 0.0)

    # ── depósito / retiro ─────────────────────────────────────────────────
    def test_retiro_de_dolares_sin_saldo_no_deja_el_sub_broker_creado(self):
        r = self._post("/api/cash/flow", {"broker_name": "Cocos", "direction": "withdraw",
                                          "amount": 50, "currency": "USD"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertNotIn(SUB, self._brokers())

    def test_deposito_en_pesos_sigue_en_la_caja_de_pesos(self):
        r = self._post("/api/cash/flow", {"broker_name": "Cocos", "direction": "deposit",
                                          "amount": 100000, "currency": "ARS"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertAlmostEqual(self._caja("Cocos"), 100000.0, places=6)
        self.assertNotIn(SUB, self._brokers())

    def test_moneda_que_la_cuenta_no_tiene_se_rechaza(self):
        # Auditoría 20/10: pesos en IBKR pasaban y $100.000 quedaban como US$ 100.000.
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "IBKR", "USDT"))
        conn.commit()
        conn.close()
        r = self._post("/api/cash/flow", {"broker_name": "IBKR", "direction": "deposit",
                                          "amount": 100000, "currency": "ARS"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(self._caja("IBKR"), 0.0)

    # ── chat ──────────────────────────────────────────────────────────────
    def _chat(self, data, req):
        return main._register_trade_handler(data, self.uid, request_id=req, confirm_signal="")

    def _chat_si(self, req):
        return main._register_trade_handler({"confirm_pending": True}, self.uid,
                                            request_id=req, confirm_signal="yes")

    def test_chat_compra_en_dolares_en_cocos_va_a_la_pata_y_se_deshace_ahi(self):
        self._post("/api/cash/flow", {"broker_name": "Cocos", "direction": "deposit",
                                      "amount": 1000, "currency": "USD"})
        r = self._chat({"action": "buy", "asset": "AAPL", "broker": "Cocos", "currency": "USD",
                        "asset_type": "CEDEAR", "quantity": 10, "price": 18}, "A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        r = self._chat_si("B")
        self.assertNotIn("error", r, r)
        lote = self._q("SELECT broker, currency FROM positions WHERE user_id=? AND asset='AAPL'",
                       self.uid)[0]
        self.assertEqual((lote["broker"], lote["currency"]), (SUB, "USD"))
        self.assertAlmostEqual(self._caja(SUB), 820.0, places=6)
        self.assertEqual(self._caja("Cocos"), 0.0)
        out = main._execute_ai_tool_inner("undo_last_trade", {}, self.uid)
        self.assertEqual(out.get("status"), "undone", out)
        self.assertAlmostEqual(self._caja(SUB), 1000.0, places=6)

    def test_chat_deposito_en_dolares_crea_la_pata_y_queda_anotada_ella(self):
        r = self._chat({"action": "deposit", "broker": "Cocos", "currency": "USD",
                        "amount": 300}, "A")
        self.assertEqual(r.get("status"), "needs_confirmation", r)
        r = self._chat_si("B")
        self.assertNotIn("error", r, r)
        self.assertAlmostEqual(self._caja(SUB), 300.0, places=6)
        self.assertEqual(self._caja("Cocos"), 0.0)
        # El chat no deshace depósitos (se registra el retiro), pero lo que anota
        # tiene que apuntar a la caja donde entró la plata, no a Cocos.
        sub_id = self._q("SELECT id FROM brokers WHERE user_id=? AND name=?", self.uid, SUB)[0]["id"]
        self.assertEqual(main._LAST_CHAT_TRADE[self.uid]["broker_id"], sub_id)
        main._LAST_CHAT_TRADE.pop(self.uid, None)

    def test_chat_retiro_de_dolares_sin_pata_avisa_que_no_hay(self):
        r = self._chat({"action": "withdraw", "broker": "Cocos", "currency": "USD",
                        "amount": 50}, "A")
        self.assertIn("error", r)
        self.assertIn("0", r["error"])
        self.assertNotIn(SUB, self._brokers())

    # ── broker del exterior: nada cambia ─────────────────────────────────
    def test_broker_en_dolares_sin_padre_no_se_toca(self):
        conn = main.get_db()
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, "IBKR", "USDT"))
        conn.commit()
        conn.close()
        r = self._post("/api/positions", {
            "broker": "IBKR", "asset": "AAPL", "quantity": 1, "buy_price": 230,
            "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["broker"], "IBKR")


if __name__ == "__main__":
    unittest.main()
