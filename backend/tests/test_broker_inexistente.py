"""No se puede cargar una POSICIÓN contra un broker que no existe.

CONTEXTO. Los brokers se linkean por NOMBRE, no por FK: no hay nada en el esquema
que impida escribir una fila contra un broker inexistente. `POST /api/monthly` ya
lo validaba a mano; `POST /api/positions` y `POST/PUT /api/operations` no.

EL BUG (auditoría 1B, casos borde). La fila entra y queda huérfana: el capital
aportado la registra, pero la valuación no la ve porque ningún broker la agrupa.
Medido en la auditoría: una pérdida fantasma de −US$9.999 (aportado 10.999 contra
una valuación de 1.000).

Es una validación que RECHAZA, así que va con el censo de callers:
`create_position` tiene un único caller interno (`register_trade`, el write-path
del chat IA) que **ya resuelve el broker por ID y aborta si no existe**, así que no
le cambia nada. Los formularios eligen de la lista del usuario. El importador no
pasa por este endpoint: escribe por el persister.

⚠️ NO se extiende a `/api/operations`, aunque tiene el mismo agujero. Ahí el
contrato TOLERA el broker desconocido a propósito, y hay un test que lo fija:
`test_importer.py::test_currency_fallback_to_usd_if_broker_unknown` ("raro pero
posible si el frontend manda un nombre libre" → cae a currency USD). El primer
intento de este fix lo extendió ahí y rompió ese test. Cambiar un contrato fijado
es una decisión de producto, no una propagación.

Corre con: cd backend && python3 -m pytest tests/test_broker_inexistente.py
"""
import unittest

import main
from fastapi.testclient import TestClient


class BrokerInexistenteTest(unittest.TestCase):
    REAL = "BrokerReal"

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "positions", "monthly_entries", "brokers", "users"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES ('brk@rendi.test','x',1,1)").lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'USDT')",
                     (self.uid, self.REAL))
        conn.commit()
        conn.close()
        self.client = TestClient(main.app)
        self.hdr = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def test_posicion_con_broker_inexistente_se_rechaza(self):
        """REGRESIÓN: entraba y quedaba huérfana."""
        r = self.client.post("/api/positions", headers=self.hdr, json={
            "broker": "NoExiste", "asset": "AAPL", "quantity": 10,
            "buy_price": 100, "invested": 1000})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("no existe", r.text)

    def test_operaciones_SIGUEN_tolerando_el_broker_desconocido(self):
        """Fija la asimetría a propósito: si alguien extiende la validación a
        /api/operations, este test lo obliga a tomar la decisión de producto en
        vez de romper el contrato de refilón."""
        r = self.client.post("/api/operations", headers=self.hdr, json={
            "date": "2025-05-10", "broker": "NoExiste", "asset": "AAPL",
            "op_type": "Venta", "pnl_usd": 100})
        self.assertEqual(r.status_code, 200, r.text)

    def test_no_queda_nada_escrito(self):
        """Lo que importa no es el 400: es que no haya fila huérfana."""
        self.client.post("/api/positions", headers=self.hdr, json={
            "broker": "NoExiste", "asset": "AAPL", "quantity": 10, "invested": 1000})
        conn = main.get_db()
        n = conn.execute("SELECT COUNT(*) c FROM positions WHERE user_id=? AND broker=?",
                         (self.uid, "NoExiste")).fetchone()["c"]
        conn.close()
        self.assertEqual(n, 0)

    def test_un_broker_real_sigue_entrando(self):
        r = self.client.post("/api/positions", headers=self.hdr, json={
            "broker": self.REAL, "asset": "AAPL", "quantity": 10,
            "buy_price": 100, "invested": 1000})
        self.assertEqual(r.status_code, 200, r.text)

    def test_global_sigue_exceptuado(self):
        """Igual que en /api/monthly: 'global' es la fila sintética de totales,
        no un broker real."""
        r = self.client.post("/api/positions", headers=self.hdr, json={
            "broker": "global", "asset": "AAPL", "quantity": 1, "invested": 10})
        self.assertNotEqual(r.status_code, 400, r.text)


if __name__ == "__main__":
    unittest.main()
