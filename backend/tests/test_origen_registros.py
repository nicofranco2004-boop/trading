"""De qué post viene cada registro, y el conteo de /admin.

El link de cada post lleva un código (`rendi.finance/?d=x-1019`). El navegador
lo anota al entrar (frontend/src/utils/origen.js) y lo manda con el registro;
acá se prueba la otra mitad: que /api/auth/register lo guarde en la cuenta y
que GET /api/admin/origenes lo cuente, con cuántos confirmaron el mail y
cuántos cargaron su cartera.

Todo por HTTP, como en producción: registro → código del mail → crear broker y
posición con la sesión del usuario → panel del admin. Lo único que se escribe a
mano es el RELOJ (se corre la fecha de alta hacia atrás para sacarla de la
ventana de 7 días).

Corre con: cd backend && python3 -m pytest tests/test_origen_registros.py
"""
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


def setUpModule():
    global _rl
    _rl = patch("main._check_rate_limit")
    _rl.start()


def tearDownModule():
    _rl.stop()


PASS = "Password123$"


class OrigenDeLosRegistros(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:8]
        self.codigo = f"x-1019-{self.tag}"
        conn = main.get_db()
        cur = conn.execute(
            "INSERT INTO users (email, password_hash, approved, is_admin, email_verified) "
            "VALUES (?, 'x', 1, 1, 1)", (f"adm-{self.tag}@rendi.test",))
        self.admin = cur.lastrowid
        conn.commit()
        conn.close()
        self.h = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self._mails = patch("billing.emails._send", return_value=True)
        self._mails.start()

    def tearDown(self):
        self._mails.stop()

    # ── el camino real ──────────────────────────────────────────────────────

    def _email(self, quien):
        # Dominio REAL a propósito: @rendi.test queda afuera del conteo.
        return f"{quien}-{self.tag}@ejemplo.com"

    def _q(self, sql, params=()):
        conn = main.get_db()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def _registrar(self, email, **extra):
        """Lo mismo que manda Login.jsx: email, clave, nombre y, si la visita
        trajo código, `origen` + `origen_visto`."""
        r = self.client.post("/api/auth/register",
                             json={"email": email, "password": PASS, "name": "x", **extra})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.cookies.clear()
        return self._q("SELECT * FROM users WHERE email=?", (email,))

    def _confirmar(self, email):
        code = self._q(
            """SELECT code FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)
               ORDER BY created_at DESC LIMIT 1""", (email,))["code"]
        r = self.client.post("/api/auth/verify-email", json={"email": email, "code": code})
        self.assertEqual(r.status_code, 200, r.text)
        # Queda con la cookie del usuario puesta: lo que sigue lo hace ÉL.

    def _cargar_cartera(self):
        r = self.client.post("/api/brokers", json={"name": "Cocos", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={
            "broker": "Cocos", "asset": "KO", "buy_price": 50, "quantity": 2,
            "invested": 100, "entry_date": "2026-02-10"})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.cookies.clear()

    def _panel(self):
        r = self.client.get("/api/admin/origenes", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    @staticmethod
    def _fila(ventana, codigo):
        return next((f for f in ventana["origenes"] if f["origen"] == codigo), None)

    # ── 1. el recorrido entero: link → registro → panel ─────────────────────

    def test_visita_con_codigo_registro_y_aparece_en_el_panel(self):
        visto = (datetime.utcnow() - timedelta(hours=2)).isoformat(timespec="milliseconds") + "Z"
        # Uno entra por el post, se registra, confirma y carga su cartera.
        u1 = self._registrar(self._email("activo"), origen=self.codigo, origen_visto=visto)
        self.assertEqual(u1["origen"], self.codigo)
        self.assertEqual(u1["origen_visto_at"][:13],
                         (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%d %H"))
        self._confirmar(self._email("activo"))
        self._cargar_cartera()
        # Otro entra por el mismo post, se registra y no confirma el mail.
        self._registrar(self._email("tibio"), origen=self.codigo, origen_visto=visto)
        # Y uno sin código.
        sin = self._registrar(self._email("directo"))
        self.assertIsNone(sin["origen"])

        panel = self._panel()
        for clave in ("7d", "30d"):
            fila = self._fila(panel[clave], self.codigo)
            self.assertEqual(fila, {"origen": self.codigo, "registros": 2,
                                    "confirmaron": 1, "cargaron": 1}, clave)
            self.assertIsNotNone(self._fila(panel[clave], None),
                                 f"{clave}: falta la fila de los que vinieron sin código")
            self.assertGreaterEqual(panel[clave]["registros"], 3)
            self.assertGreaterEqual(panel[clave]["con_codigo"], 2)
        # "Sin código" va al final, aunque sea la más grande.
        self.assertIsNone(panel["7d"]["origenes"][-1]["origen"])

    # ── 2. la ventana de días ───────────────────────────────────────────────

    def test_un_registro_de_hace_10_dias_cuenta_en_30_y_no_en_7(self):
        u = self._registrar(self._email("viejo"), origen=self.codigo)
        conn = main.get_db()
        try:
            hace_10 = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE users SET created_at=? WHERE id=?", (hace_10, u["id"]))
            conn.commit()
        finally:
            conn.close()
        panel = self._panel()
        self.assertIsNone(self._fila(panel["7d"], self.codigo))
        self.assertEqual(self._fila(panel["30d"], self.codigo)["registros"], 1)

    # ── 3. el código nunca rechaza un registro ──────────────────────────────

    def test_un_codigo_raro_se_limpia_y_el_registro_entra(self):
        u = self._registrar(self._email("raro"), origen="  IG 20261019<script>!  ",
                            origen_visto="no es una fecha")
        self.assertEqual(u["origen"], "ig-20261019script")
        self.assertIsNone(u["origen_visto_at"])

    def test_basura_en_el_origen_no_da_422(self):
        for i, (origen, visto) in enumerate([
            (12345, 99), ({"a": 1}, ["x"]), ("x" * 5000, "2099-01-01T00:00:00Z"), ("¡¡¡", None),
        ]):
            u = self._registrar(self._email(f"basura{i}"), origen=origen, origen_visto=visto)
            self.assertIn(u["origen"], (None, "x" * 60), (origen, u["origen"]))
            # Una fecha del futuro no fecha el clic.
            self.assertIsNone(u["origen_visto_at"])

    # ── 4. quién entra en la cuenta ─────────────────────────────────────────

    def test_cuentas_internas_y_clientes_de_asesor_no_cuentan(self):
        r = self.client.post("/api/auth/register", json={
            "email": f"interno-{self.tag}@rendi.test", "password": PASS, "name": "x",
            "origen": self.codigo})
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        try:
            conn.execute(
                "INSERT INTO users (email, password_hash, managed_by, origen) VALUES (?, 'x', ?, ?)",
                (self._email("cliente"), self.admin, self.codigo))
            conn.commit()
        finally:
            conn.close()
        self.assertIsNone(self._fila(self._panel()["7d"], self.codigo))

    def test_sin_ser_admin_no_se_ve(self):
        self._registrar(self._email("curioso"))
        self._confirmar(self._email("curioso"))
        r = self.client.get("/api/admin/origenes")
        self.assertIn(r.status_code, (401, 403), r.text)


class LaMismaReglaQueElNavegador(unittest.TestCase):
    """`_normalizar_origen` y `normalizarCodigo` (utils/origen.js) tienen que
    limpiar igual: los mismos casos están en origen.test.js."""

    def test_casos(self):
        casos = {
            "x-20261019": "x-20261019",
            "IG-20261019": "ig-20261019",
            "  x 1019 ": "x-1019",
            "x/campaña": "x/campaa",
            "<b>": "b",
            "": None,
            "!!!": None,
        }
        for entrada, esperado in casos.items():
            self.assertEqual(main._normalizar_origen(entrada), esperado, entrada)


if __name__ == "__main__":
    unittest.main()
