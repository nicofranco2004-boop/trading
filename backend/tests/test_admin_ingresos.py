"""Cuántos usuarios iniciaron sesión, en el panel de /admin.

Lo que estaba mal (auditoría 2026-10-07):

1. Sólo el login con contraseña escribía `users.last_login_at`, que es lo que
   contaba la tarjeta "Activos (7 días)". Quien entraba verificando el mail (todo
   usuario nuevo), por "olvidé mi contraseña" o reclamando la cuenta del asesor
   no contaba — y figuraba "—" en "Último login".
2. `last_login_at` guarda sólo el ÚLTIMO ingreso: no sirve para contar un
   período pasado. Ahora se cuenta sobre `login_history`.
3. La tarjeta sumaba a los admins y a las cuentas internas, y la "Tasa de
   actividad" dividía por usuarios que nunca confirmaron el mail.

Todo por HTTP, como en producción: registro → código del mail → login →
olvidé mi contraseña → panel. Lo único que se escribe a mano es el RELOJ (se
corre la hora de un ingreso hacia atrás para ponerlo en otro período).

Corre con: cd backend && python3 -m pytest tests/test_admin_ingresos.py
"""
import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from fechas import hoy_art_date, inicio_dia_art_en_utc


def setUpModule():
    global _rl
    _rl = patch("main._check_rate_limit")
    _rl.start()


def tearDownModule():
    _rl.stop()


PASS = "Password123$"


class IngresosEnElPanel(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        self.tag = uuid.uuid4().hex[:8]
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

    def _uid(self, email):
        return self._q("SELECT id FROM users WHERE email=?", (email,))["id"]

    def _registrar_y_confirmar(self, email):
        r = self.client.post("/api/auth/register",
                             json={"email": email, "password": PASS, "name": "x"})
        self.assertEqual(r.status_code, 200, r.text)
        code = self._q(
            """SELECT code FROM email_verification_codes
               WHERE user_id = (SELECT id FROM users WHERE email=?)
               ORDER BY created_at DESC LIMIT 1""", (email,))["code"]
        r = self.client.post("/api/auth/verify-email",
                             json={"email": email, "code": code})
        self.assertEqual(r.status_code, 200, r.text)
        # La cookie del usuario le gana al header del admin: se limpia.
        self.client.cookies.clear()
        return self._uid(email)

    def _login(self, email, password=PASS):
        r = self.client.post("/api/auth/login",
                             json={"email": email, "password": password})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.cookies.clear()

    def _restablecer(self, email):
        r = self.client.post("/api/auth/forgot-password", json={"email": email})
        self.assertEqual(r.status_code, 200, r.text)
        token = self._q(
            """SELECT t.token FROM password_reset_tokens t JOIN users u ON u.id=t.user_id
               WHERE u.email=? AND t.used_at IS NULL
               ORDER BY t.id DESC LIMIT 1""", (email,))["token"]
        r = self.client.post("/api/auth/reset-password",
                             json={"token": token, "new_password": "OtraClave456$"})
        self.assertEqual(r.status_code, 200, r.text)
        self.client.cookies.clear()

    def _ingresos(self, desde=None, hasta=None):
        params = {}
        if desde:
            params["desde"] = desde.isoformat()
        if hasta:
            params["hasta"] = hasta.isoformat()
        r = self.client.get("/api/admin/uso", params=params, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["resumen"]

    def _ingresos_de(self, uid):
        conn = main.get_db()
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM login_history WHERE user_id=?", (uid,)).fetchone()[0]
        finally:
            conn.close()

    def _mover_ingresos(self, uid, a_utc):
        """El reloj: todos los ingresos de `uid` pasan a la hora `a_utc`."""
        conn = main.get_db()
        try:
            conn.execute("UPDATE login_history SET created_at=? WHERE user_id=?", (a_utc, uid))
            conn.commit()
        finally:
            conn.close()

    # ── 1. cada camino de entrada cuenta ────────────────────────────────────

    def test_verificar_el_mail_cuenta_como_ingreso(self):
        """El usuario nuevo entra verificando el mail. Antes no contaba y su
        "Último login" quedaba en "—"."""
        antes = self._ingresos()["usuarios"]
        uid = self._registrar_y_confirmar(self._email("nuevo"))
        self.assertEqual(self._ingresos()["usuarios"], antes + 1)
        self.assertIsNotNone(self._q("SELECT last_login_at FROM users WHERE id=?", (uid,))[0])

    def test_restablecer_la_contrasena_cuenta_como_ingreso(self):
        email = self._email("olvido")
        uid = self._registrar_y_confirmar(email)
        n = self._ingresos_de(uid)
        self._restablecer(email)
        self.assertEqual(self._ingresos_de(uid), n + 1)

    def test_login_con_contrasena_cuenta_y_el_mismo_usuario_cuenta_una_vez(self):
        email = self._email("repite")
        self._registrar_y_confirmar(email)
        antes = self._ingresos()
        self._login(email)
        self._login(email)
        despues = self._ingresos()
        self.assertEqual(despues["usuarios"], antes["usuarios"], "ya había entrado: no se suma")
        self.assertEqual(despues["ingresos"], antes["ingresos"] + 2)

    def test_un_login_fallido_no_cuenta(self):
        email = self._email("falla")
        uid = self._registrar_y_confirmar(email)
        n = self._ingresos_de(uid)
        r = self.client.post("/api/auth/login", json={"email": email, "password": "mal"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self._ingresos_de(uid), n)

    # ── 2. el período ───────────────────────────────────────────────────────

    def test_un_ingreso_viejo_cuenta_en_su_periodo_y_no_en_la_ultima_semana(self):
        hoy = hoy_art_date()
        uid = self._registrar_y_confirmar(self._email("viejo"))
        hace_10 = hoy - timedelta(days=10)
        antes_semana = self._ingresos()["usuarios"]
        antes_periodo = self._ingresos(hace_10, hace_10)["usuarios"]
        self._mover_ingresos(uid, inicio_dia_art_en_utc(hace_10).replace("03:00:00", "15:00:00"))
        self.assertEqual(self._ingresos()["usuarios"], antes_semana - 1)
        self.assertEqual(self._ingresos(hace_10, hace_10)["usuarios"], antes_periodo + 1)

    def test_el_dia_se_corta_en_hora_argentina(self):
        """Un ingreso a las 22:00 de Buenos Aires (01:00 UTC del día siguiente)
        es del día argentino, no del siguiente."""
        dia = hoy_art_date() - timedelta(days=20)
        siguiente = dia + timedelta(days=1)
        uid = self._registrar_y_confirmar(self._email("noche"))
        a_dia = self._ingresos(dia, dia)["usuarios"]
        a_sig = self._ingresos(siguiente, siguiente)["usuarios"]
        # 22:00 ART del `dia` = 01:00 UTC de `siguiente`.
        self._mover_ingresos(uid, f"{siguiente.isoformat()} 01:00:00")
        self.assertEqual(self._ingresos(dia, dia)["usuarios"], a_dia + 1)
        self.assertEqual(self._ingresos(siguiente, siguiente)["usuarios"], a_sig)

    def test_primera_vez_y_volvieron(self):
        hoy = hoy_art_date()
        nuevo = self._registrar_y_confirmar(self._email("primera"))
        viejo_email = self._email("vuelve")
        viejo = self._registrar_y_confirmar(viejo_email)
        # `viejo` entró por primera vez hace 30 días y volvió hoy.
        self._mover_ingresos(viejo, inicio_dia_art_en_utc(hoy - timedelta(days=30)))
        self._login(viejo_email)
        r = self._ingresos(hoy, hoy)
        self.assertGreaterEqual(r["primera_vez"], 1)
        self.assertGreaterEqual(r["volvieron"], 1)
        self.assertEqual(r["primera_vez"] + r["volvieron"], r["usuarios"])
        del nuevo

    def test_fechas_invalidas(self):
        r = self.client.get("/api/admin/uso", params={"desde": "ayer"}, headers=self.h)
        self.assertEqual(r.status_code, 400)
        hoy = hoy_art_date()
        r = self.client.get("/api/admin/uso",
                            params={"desde": hoy.isoformat(),
                                    "hasta": (hoy - timedelta(days=1)).isoformat()},
                            headers=self.h)
        self.assertEqual(r.status_code, 400)

    def test_solo_admin(self):
        uid = self._registrar_y_confirmar(self._email("intruso"))
        r = self.client.get("/api/admin/uso",
                            headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        self.assertEqual(r.status_code, 403)

    # ── 3. quién cuenta ─────────────────────────────────────────────────────

    def test_admins_y_cuentas_internas_no_cuentan(self):
        antes = self._ingresos()["usuarios"]
        for email in (f"staff-{self.tag}@rendi.finance", f"t-{self.tag}@rendi.test"):
            self._registrar_y_confirmar(email)
        self.assertEqual(self._ingresos()["usuarios"], antes)

    def test_la_tarjeta_y_el_selector_dan_lo_mismo(self):
        """La tarjeta de /admin/stats y el selector en "últimos 7 días" son la
        MISMA cuenta: si un día divergen, alguien duplicó el cálculo."""
        self._registrar_y_confirmar(self._email("tarjeta"))
        r = self.client.get("/api/admin/stats", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        sel = self._ingresos()
        self.assertEqual(r.json()["active_last_7d"], sel["usuarios"])
        self.assertEqual(r.json()["active_base"], sel["base"])


class UltimoLoginAtrasado(unittest.TestCase):
    """Las cuentas que entraron verificando el mail ANTES del arreglo tienen el
    ingreso en el historial pero "—" en la columna. El arranque lo completa."""

    def test_el_arranque_completa_la_columna_desde_el_historial(self):
        tag = uuid.uuid4().hex[:8]
        conn = main.get_db()
        try:
            sin = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified) "
                "VALUES (?, 'x', 1, 1)", (f"sin-{tag}@ejemplo.com",)).lastrowid
            vieja = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, last_login_at) "
                "VALUES (?, 'x', 1, 1, '2026-09-01 10:00:00')", (f"vieja-{tag}@ejemplo.com",)).lastrowid
            nueva = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, last_login_at) "
                "VALUES (?, 'x', 1, 1, '2026-10-05 10:00:00')", (f"nueva-{tag}@ejemplo.com",)).lastrowid
            for uid in (sin, vieja, nueva):
                conn.execute("INSERT INTO login_history (user_id, created_at) VALUES (?, '2026-09-20 12:00:00')",
                             (uid,))
            conn.commit()
        finally:
            conn.close()

        main.init_db()
        main.init_db()   # idempotente

        conn = main.get_db()
        try:
            col = {r["id"]: r["last_login_at"] for r in conn.execute(
                "SELECT id, last_login_at FROM users WHERE id IN (?,?,?)", (sin, vieja, nueva))}
        finally:
            conn.close()
        self.assertEqual(col[sin], "2026-09-20 12:00:00")
        self.assertEqual(col[vieja], "2026-09-20 12:00:00")
        self.assertEqual(col[nueva], "2026-10-05 10:00:00", "no se pisa un login más nuevo")


if __name__ == "__main__":
    unittest.main()
