"""Audit de los futuros (Fases 1 y 2) — 2026-08-12.

Tres bugs REALES encontrados auditando lo recién shippeado. Los tres los
introduje yo, y los tres mueven plata. Este archivo los deja clavados.

  A) MONEDA. `_adjust_broker_cash` recibe la moneda NATIVA del broker —así lo
     dice su contrato y así lo usa el importador— pero los futuros le pasaban
     `pnl_usd` directo. Con un broker en USDT no se nota (1:1). Con uno en PESOS
     —el dólar futuro de Rofex/Matba se opera en ARS— 100 dólares de ganancia
     entraban como 100 PESOS. Medido: un saldo de 1.000.000 quedó en 1.000.100 en
     vez de sumar ~141.500. Error del orden del tipo de cambio.

  B) CIERRE NO ATÓMICO. El endpoint chequeaba `closed_at` y después updateaba,
     pero el SELECT no toma lock: dos cierres en paralelo lo pasaban los dos.
     Medido: dos requests simultáneos dejaron 2.000 de efectivo en vez de 1.500 y
     crearon dos operaciones. Plata fabricada de la nada.

  C) BORRAR EL CIERRE PERDÍA LA POSICIÓN. Borrar la operación devolvía bien el
     efectivo y el P&L, pero la posición quedaba marcada como cerrada: no estaba
     en la lista de abiertas y su resultado ya no existía en ningún lado.
"""
import threading
import unittest
import uuid

import main


def _cliente():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def _usuario(currency="USDT", saldo=1000.0, broker="Binance"):
    conn = main.get_db()
    uid = conn.execute(
        "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
        (f"aud-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
    conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                 (uid, broker, currency))
    conn.execute("""INSERT INTO positions (user_id, broker, asset, is_cash, invested, quantity)
                    VALUES (?,?,?,1,?,?)""",
                 (uid, broker, 'ARS' if currency == 'ARS' else 'USDT', saldo, saldo))
    conn.commit()
    conn.close()
    return uid, {"Authorization": f"Bearer {main.create_token(uid)}"}


def _cash(uid):
    conn = main.get_db()
    r = conn.execute("SELECT invested FROM positions WHERE user_id=? AND is_cash=1",
                     (uid,)).fetchone()
    conn.close()
    return float(r["invested"]) if r else 0.0


def _pnl_realizado(uid):
    conn = main.get_db()
    r = conn.execute("SELECT COALESCE(SUM(pnl_realized),0) p FROM monthly_entries "
                     " WHERE user_id=? AND broker='global'", (uid,)).fetchone()
    conn.close()
    return float(r["p"])


class A_MonedaDelEfectivo(unittest.TestCase):
    """El efectivo vive en la moneda del broker; el P&L, en dólares."""

    def setUp(self):
        self.client = _cliente()

    def test_en_un_broker_en_PESOS_el_pnl_se_convierte_al_tipo_de_cambio(self):
        uid, h = _usuario(currency="ARS", saldo=1_000_000, broker="Rofex")
        r = self.client.post("/api/operations", headers=h, json={
            "date": "2026-08-11", "broker": "Rofex", "asset": "DLR/AGO26",
            "op_type": "Futuros", "pnl_usd": 100, "commissions": 0, "kind": "futures"})
        self.assertEqual(r.status_code, 200, r.text)
        sumado = _cash(uid) - 1_000_000
        # El bug sumaba exactamente 100. Cualquier TC razonable da miles.
        self.assertGreater(sumado, 10_000,
                           f"sumó {sumado} al efectivo en pesos — parece USD sin convertir")

    def test_pero_el_PL_realizado_sigue_en_dolares(self):
        """monthly_entries es USD para todos los brokers. Si se convirtiera
        también acá, el P&L de una cuenta en pesos se inflaría ×1400."""
        uid, h = _usuario(currency="ARS", saldo=1_000_000, broker="Rofex")
        self.client.post("/api/operations", headers=h, json={
            "date": "2026-08-11", "broker": "Rofex", "asset": "DLR/AGO26",
            "op_type": "Futuros", "pnl_usd": 100, "commissions": 0, "kind": "futures"})
        self.assertAlmostEqual(_pnl_realizado(uid), 100, places=2)

    def test_en_un_broker_en_USDT_no_cambia_nada(self):
        """El caso del 99% de los usuarios: nativa == USD, conversión 1:1."""
        uid, h = _usuario(currency="USDT", saldo=1000)
        self.client.post("/api/operations", headers=h, json={
            "date": "2026-08-11", "broker": "Binance", "asset": "BTCUSDT",
            "op_type": "Futuros", "pnl_usd": 47, "commissions": 0, "kind": "futures"})
        self.assertAlmostEqual(_cash(uid), 1047, places=2)

    def test_el_cierre_de_una_posicion_convierte_igual(self):
        uid, h = _usuario(currency="ARS", saldo=1_000_000, broker="Rofex")
        f = self.client.post("/api/futures", headers=h, json={
            "broker": "Rofex", "symbol": "DLR", "side": "long",
            "quantity": 1, "entry_price": 100, "opened_at": "2026-08-01"}).json()
        self.client.post(f"/api/futures/{f['id']}/close", headers=h,
                         json={"exit_price": 200})   # +100 USD
        self.assertGreater(_cash(uid) - 1_000_000, 10_000)


class B_CierreAtomico(unittest.TestCase):
    def setUp(self):
        self.client = _cliente()

    def test_dos_cierres_en_PARALELO_acreditan_UNA_sola_vez(self):
        uid, h = _usuario(saldo=1000)
        f = self.client.post("/api/futures", headers=h, json={
            "broker": "Binance", "symbol": "ETHUSDT", "side": "long",
            "quantity": 1, "entry_price": 1000, "opened_at": "2026-08-01"}).json()

        # 8 hilos con BARRERA, no 2 sueltos. Con 2 el race sale 1 de 6 veces y el
        # test sería una guarda de mentira; con 8 arrancando a la vez reprodujo
        # 6 de 6 contra el código sin el fix (8 operaciones de 8 intentos).
        N = 8
        arranque = threading.Barrier(N)
        codigos = []
        def cerrar():
            arranque.wait()
            codigos.append(self.client.post(f"/api/futures/{f['id']}/close",
                                            headers=h, json={"exit_price": 1500}).status_code)
        hilos = [threading.Thread(target=cerrar) for _ in range(N)]
        for t in hilos: t.start()
        for t in hilos: t.join()

        self.assertEqual(codigos.count(200), 1, f"más de un cierre pasó: {codigos}")
        conn = main.get_db()
        n = conn.execute("SELECT COUNT(*) c FROM operations WHERE user_id=?", (uid,)).fetchone()["c"]
        conn.close()
        self.assertEqual(n, 1, "se creó más de una operación")
        self.assertAlmostEqual(_cash(uid), 1500, places=2)

    def test_cerrar_dos_veces_en_serie_tampoco(self):
        uid, h = _usuario(saldo=1000)
        f = self.client.post("/api/futures", headers=h, json={
            "broker": "Binance", "symbol": "ETHUSDT", "side": "long",
            "quantity": 1, "entry_price": 1000, "opened_at": "2026-08-01"}).json()
        self.client.post(f"/api/futures/{f['id']}/close", headers=h, json={"exit_price": 1500})
        r = self.client.post(f"/api/futures/{f['id']}/close", headers=h, json={"exit_price": 1500})
        self.assertEqual(r.status_code, 400)
        self.assertAlmostEqual(_cash(uid), 1500, places=2)


class C_BorrarElCierreDevuelveLaPosicion(unittest.TestCase):
    def setUp(self):
        self.client = _cliente()

    def _abrir_y_cerrar(self):
        uid, h = _usuario(saldo=1000)
        f = self.client.post("/api/futures", headers=h, json={
            "broker": "Binance", "symbol": "BTCUSDT", "side": "long",
            "quantity": 0.5, "entry_price": 60000, "opened_at": "2026-08-01"}).json()
        r = self.client.post(f"/api/futures/{f['id']}/close", headers=h,
                             json={"exit_price": 62000}).json()
        return uid, h, f, r

    def test_borrar_la_operacion_REABRE_la_posicion(self):
        uid, h, f, r = self._abrir_y_cerrar()
        d = self.client.delete(f"/api/operations/{r['operation_id']}", headers=h)
        self.assertEqual(d.status_code, 200, d.text)
        abiertas = self.client.get("/api/futures", headers=h).json()
        self.assertEqual(len(abiertas), 1, "la posición se perdió al borrar su cierre")
        self.assertEqual(abiertas[0]["id"], f["id"])
        self.assertAlmostEqual(_cash(uid), 1000, places=2)

    def test_y_el_deshacer_la_vuelve_a_cerrar(self):
        uid, h, f, r = self._abrir_y_cerrar()
        d = self.client.delete(f"/api/operations/{r['operation_id']}", headers=h)
        u = self.client.post(f"/api/operations/undo/{d.json()['undo_token']}", headers=h)
        self.assertEqual(u.status_code, 200, u.text)
        self.assertEqual(self.client.get("/api/futures", headers=h).json(), [])
        self.assertAlmostEqual(_cash(uid), 2000, places=2)

    def test_borrar_una_op_de_futuros_CARGADA_A_MANO_no_toca_ninguna_posicion(self):
        """La de la Fase 1 no tiene `futuro_id`: no puede reabrir nada ajeno."""
        uid, h = _usuario(saldo=1000)
        f = self.client.post("/api/futures", headers=h, json={
            "broker": "Binance", "symbol": "BTCUSDT", "side": "long",
            "quantity": 1, "entry_price": 100, "opened_at": "2026-08-01"}).json()
        op = self.client.post("/api/operations", headers=h, json={
            "date": "2026-08-11", "broker": "Binance", "asset": "OTRO",
            "op_type": "Futuros", "pnl_usd": 10, "commissions": 0, "kind": "futures"}).json()
        self.client.delete(f"/api/operations/{op['id']}", headers=h)
        abiertas = self.client.get("/api/futures", headers=h).json()
        self.assertEqual(len(abiertas), 1)
        self.assertIsNone(abiertas[0]["closed_at"])


if __name__ == "__main__":
    unittest.main()
