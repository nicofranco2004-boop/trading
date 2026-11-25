"""La bienvenida obligatoria: quién tiene que subir su primer archivo antes de ver Rendi.

Lo decidió Nico el 25/11/2026: al terminar de registrarse, la persona no ve Rendi
hasta haber subido y CONFIRMADO un archivo de su broker. La regla vive en un solo
lugar, `bienvenida.falta_cargar_historial`, y llega a la pantalla como
`falta_cargar_historial` en `GET /api/auth/me`.

CAMINO. Todo lo que la persona hace entra por las puertas de producción, con una
sesión real (el token que devuelve el servidor, no un atajo de pruebas):
  · la cuenta nueva se registra (`POST /api/auth/register`) y confirma su mail
    (`POST /api/auth/verify-email`, que además le arranca la prueba gratis);
  · el archivo se sube y se confirma como en el importador: `POST /api/imports/preview`
    + `POST /api/imports/confirm`, y se deshace con `POST /api/imports/{id}/revert`;
  · el plan Asesor lo da el botón del panel (`/api/admin/billing/grant-comp`), el
    cliente lo crea el asesor (`POST /api/advisor/clients`) y lo reclama la persona
    (`/invite` + `POST /api/auth/claim`);
  · lo que se mide es siempre `GET /api/auth/me`, lo mismo que lee la app.
Lo que todavía no tiene una puerta que lo haga en una línea va por SQL y lo dice
en su prueba: la fecha de alta de una cuenta vieja, `is_admin`, `managed_by` sin
vínculo, el vínculo 'linked' de un asesor y el pase entre brokers (sus dos lotes,
con la forma que escribe `aplicar_plan`).

Corre con: cd backend && python3 -m pytest tests/test_bienvenida_obligatoria.py -q
"""
import io
import os
import sys
import time
import unittest
import uuid
from urllib.parse import parse_qs, urlparse
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402
import bienvenida  # noqa: E402
from importing import traspaso_a_mano  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

HDR = "fecha,tipo,broker,activo,cantidad,precio,monto,monto_usd,tc,comisiones,moneda,notas\n"
# El archivo más chico que el importador acepta: un depósito en IBKR (en dólares,
# sin títulos: no necesita precios ni dólar de ningún día).
ARCHIVO = (HDR + "2025-03-03,DEPOSITO,IBKR,,,,1000,,,0,USD,primer deposito\n").encode()

CORTE = bienvenida.BIENVENIDA_OBLIGATORIA_DESDE


def setUpModule():
    # Varias altas y verificaciones seguidas desde la misma "IP": sin esto el
    # freno de 5 registros cada 5 minutos corta la tercera prueba.
    global _parches
    _parches = [mock.patch("main._check_rate_limit"),
                mock.patch("billing.emails._send", return_value=True)]
    for p in _parches:
        p.start()


def tearDownModule():
    for p in _parches:
        p.stop()


class _Base(unittest.TestCase):

    def setUp(self):
        self.http = TestClient(main.app)
        self._cuentas = []

    def tearDown(self):
        # La reconstrucción a mercado que dispara el confirm corre al terminar el
        # pedido: se la espera, así no escribe mientras arranca la prueba siguiente.
        for uid in self._cuentas:
            self._esperar_reconstruccion(uid)
        self.http.cookies.clear()

    # ── las puertas reales ──────────────────────────────────────────────────────
    def _registrarse(self, nombre="Ana"):
        """(uid, encabezado con su sesión) de una cuenta recién registrada y con el
        mail confirmado: exactamente lo que tiene la persona al llegar a la app."""
        email = f"bienvenida-{uuid.uuid4().hex[:10]}@rendi.test"
        r = self.http.post("/api/auth/register",
                           json={"email": email, "password": "Password123$", "name": nombre})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("needs_verification"), r.text)
        conn = main.get_db()
        try:
            uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
            codigo = conn.execute(
                "SELECT code FROM email_verification_codes WHERE user_id=? AND used_at IS NULL "
                "ORDER BY created_at DESC LIMIT 1", (uid,)).fetchone()["code"]
        finally:
            conn.close()
        r = self.http.post("/api/auth/verify-email", json={"email": email, "code": codigo})
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        # La respuesta deja la cookie de sesión en el cliente de pruebas (como en un
        # navegador). Se usa el token por encabezado para poder hablar como varias
        # personas en la misma prueba: si quedara la cookie, ganaría ella.
        self.http.cookies.clear()
        self._cuentas.append(uid)
        return uid, {"Authorization": f"Bearer {token}"}

    def _me(self, headers):
        r = self.http.get("/api/auth/me", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertIn("falta_cargar_historial", d, "el campo no llega a la pantalla")
        self.assertIsInstance(d["falta_cargar_historial"], bool)
        return d

    def _falta(self, headers):
        return self._me(headers)["falta_cargar_historial"]

    def _subir(self, headers):
        """Sube el archivo (vista previa) SIN confirmarlo. Devuelve el id del lote."""
        r = self.http.post(
            "/api/imports/preview",
            files=[("files", ("movimientos.csv", io.BytesIO(ARCHIVO), "text/csv"))],
            data={"format": "rendi_generic", "broker": "IBKR"}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session_id"]

    def _confirmar(self, headers, lote):
        r = self.http.post("/api/imports/confirm",
                           json={"session_id": lote, "skip_row_indices": [],
                                 "aprobar_tickers": []}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)

    def _revertir(self, headers, lote):
        r = self.http.post(f"/api/imports/{lote}/revert", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)

    def _esperar_reconstruccion(self, uid):
        limite = time.time() + 60
        while time.time() < limite:
            with main._MTM_RUNNING_LOCK:
                if uid not in main._MTM_RUNNING:
                    return
            time.sleep(0.02)
        self.fail("la reconstrucción a mercado no terminó en 60 s")

    # ── lo que no tiene puerta de una línea ─────────────────────────────────────
    def _sql(self, sql, params=()):
        conn = main.get_db()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _estado_de_lotes(self, uid):
        conn = main.get_db()
        try:
            return sorted((r["status"], r["parser_format"] or "") for r in conn.execute(
                "SELECT status, parser_format FROM import_batches WHERE user_id=?",
                (uid,)).fetchall())
        finally:
            conn.close()

    def _cuenta_con_fecha_de_alta(self, created_at):
        """Una cuenta cualquiera (sin admin, sin asesor, sin nada cargado) con la
        fecha de alta que se pida, y su sesión real."""
        uid = self._sql(
            "INSERT INTO users (email, password_hash, approved, email_verified, created_at) "
            "VALUES (?, 'x', 1, 1, ?)",
            (f"vieja-{uuid.uuid4().hex[:10]}@rendi.test", created_at))
        return uid, {"Authorization": f"Bearer {main.create_token(uid)}"}


    # ── ayudantes del asesor ────────────────────────────────────────────────────
    def _admin(self):
        uid = self._sql("INSERT INTO users (email, password_hash, approved, is_admin) "
                        "VALUES (?, 'x', 1, 1)", (f"admin-{uuid.uuid4().hex[:10]}@rendi.test",))
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _dar_plan_asesor(self, uid):
        """El botón «Asesor» del panel de admin (`force`: la persona está en la prueba)."""
        conn = main.get_db()
        try:
            email = conn.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone()["email"]
        finally:
            conn.close()
        r = self.http.post("/api/admin/billing/grant-comp",
                           params={"email": email, "plan": "advisor", "days": 30, "force": True},
                           headers=self._admin())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json().get("ok"), r.text)

    def _crear_cliente(self, h_asesor):
        r = self.http.post("/api/advisor/clients", json={"label": "Juan P"}, headers=h_asesor)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["client_uid"]

    def _reclamar(self, h_asesor, cliente):
        """El asesor invita a la persona por mail y ella reclama la cuenta con el link."""
        tokens = []

        def _capturar(**kw):
            tokens.append(parse_qs(urlparse(kw["claim_url"]).query)["token"][0])
            return True
        with mock.patch("billing.emails.send_advisor_claim", side_effect=_capturar):
            r = self.http.post(f"/api/advisor/clients/{cliente}/invite",
                               json={"email": f"juan-{uuid.uuid4().hex[:8]}@example.com"},
                               headers=h_asesor)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(tokens, "el mail de la invitación no salió")
        r = self.http.post("/api/auth/claim",
                           json={"token": tokens[-1], "new_password": "unaClaveLarga1"})
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        self.http.cookies.clear()
        return {"Authorization": f"Bearer {token}"}


class CuentaNueva(_Base):

    def test_recien_registrada_y_sin_nada_tiene_que_cargar(self):
        uid, h = self._registrarse()
        self.assertTrue(self._falta(h))
        # El mismo pedido sigue contando la prueba gratis como siempre: la
        # bienvenida no toca billing (la prueba arranca al confirmar el mail).
        self.assertIn(self._me(h)["tier"], ("pro", "plus"))

    def test_subido_sin_confirmar_no_destraba(self):
        """Un lote en vista previa no cargó nada: la persona puede haber cerrado el
        asistente antes de confirmar."""
        uid, h = self._registrarse()
        self._subir(h)
        self.assertEqual(self._estado_de_lotes(uid), [("preview", "rendi_generic")],
                         "el montaje no reproduce el caso: tiene que haber un lote en preview")
        self.assertTrue(self._falta(h))

    def test_confirmar_destraba_y_deshacer_lo_vuelve_a_pedir(self):
        uid, h = self._registrarse()
        lote = self._subir(h)
        self._confirmar(h, lote)
        self.assertFalse(self._falta(h), "confirmó un archivo y la app lo sigue mandando a cargar")
        self._revertir(h, lote)
        self.assertEqual(self._estado_de_lotes(uid), [("reverted", "rendi_generic")],
                         "el montaje no reproduce el caso: el lote tiene que quedar revertido")
        self.assertTrue(self._falta(h), "deshizo su único import y la app no lo devuelve a cargar")

    def test_otro_import_confirmado_sostiene_aunque_deshaga_uno(self):
        uid, h = self._registrarse()
        primero = self._subir(h)
        self._confirmar(h, primero)
        segundo = self._subir(h)
        self._confirmar(h, segundo)
        self._revertir(h, primero)
        self.assertFalse(self._falta(h))

    def test_solo_un_pase_entre_brokers_no_destraba(self):
        """Cargar a mano no destraba, y pasar eso a otro broker tampoco: el pase
        escribe dos lotes CONFIRMADOS, pero mueve lo que ya estaba, no trae nada de un
        archivo. Todo por las puertas de la pantalla: «Agregar» (`POST /api/positions`)
        y «Mover a otro broker» (vista previa + confirmar)."""
        uid, h = self._registrarse()
        self._sql("INSERT INTO interruptores (nombre, encendido, cambiado_at) "
                  "VALUES (?, 1, datetime('now')) "
                  "ON CONFLICT(nombre) DO UPDATE SET encendido=excluded.encendido",
                  (traspaso_a_mano.INTERRUPTOR,))
        self.addCleanup(self._sql, "DELETE FROM interruptores WHERE nombre=?",
                        (traspaso_a_mano.INTERRUPTOR,))
        for broker in ("IBKR", "Schwab"):
            self._sql("INSERT INTO brokers (user_id, name, currency) VALUES (?, ?, 'USD')",
                      (uid, broker))
        r = self.http.post("/api/positions", headers=h, json={
            "broker": "IBKR", "asset": "MSFT", "quantity": 5, "buy_price": 300,
            "invested": 1500, "entry_date": "2025-02-03", "currency": "USD"})
        self.assertEqual(r.status_code, 200, r.text)
        self._esperar_reconstruccion(uid)
        self.assertTrue(self._falta(h), "cargó a mano y la app lo dejó pasar")
        pedido = {"broker_origen": "IBKR", "asset": "MSFT", "moneda": "USD",
                  "broker_destino": "Schwab", "fecha": "2025-06-16", "precio_manual": 400}
        v = self.http.post("/api/positions/traspaso/vista-previa", json=pedido, headers=h)
        self.assertEqual(v.status_code, 200, v.text)
        c = self.http.post("/api/positions/traspaso", headers=h, json={
            **pedido, "firma": v.json()["firma"], "valuacion": v.json()["valuacion"]})
        self.assertEqual(c.status_code, 200, c.text)
        self._esperar_reconstruccion(uid)
        self.assertEqual(self._estado_de_lotes(uid),
                         [("confirmed", traspaso_a_mano.FORMATO)] * 2,
                         "el montaje no reproduce el caso: el pase escribe dos lotes confirmados")
        self.assertTrue(self._falta(h))
        # Y un archivo de verdad, encima del pase, sí destraba.
        self._confirmar(h, self._subir(h))
        self.assertFalse(self._falta(h))


class QuienesQuedanAfuera(_Base):

    def test_el_admin(self):
        uid, h = self._registrarse()
        self.assertTrue(self._falta(h), "control: antes de ser admin le tocaba")
        self._sql("UPDATE users SET is_admin=1 WHERE id=?", (uid,))
        self.assertFalse(self._falta(h))

    def test_el_asesor(self):
        uid, h = self._registrarse()
        self.assertTrue(self._falta(h), "control: antes del plan Asesor le tocaba")
        self._dar_plan_asesor(uid)
        self.assertEqual(self._me(h)["tier"], "advisor",
                         "el montaje no reproduce el caso: su plan tiene que ser Asesor")
        self.assertFalse(self._falta(h))

    def test_la_ficha_que_crea_el_asesor(self):
        """La cuenta administrada (`managed_by` + vínculo 'managed'), tal como la crea
        el asesor desde su panel."""
        asesor, h_asesor = self._registrarse("Asesora")
        self._dar_plan_asesor(asesor)
        cliente = self._crear_cliente(h_asesor)
        h_cliente = {"Authorization": f"Bearer {main.create_token(cliente)}"}
        self.assertFalse(self._falta(h_cliente))

    def test_el_cliente_que_reclamo_su_cuenta(self):
        """Al reclamarla, `managed_by` vuelve a NULL (la cuenta pasa a ser suya), pero
        el vínculo 'managed' queda en `advisor_clients`: sigue siendo un cliente que
        armó el asesor, y su historial ya lo carga el asesor. En cualquier estado del
        vínculo (aunque la persona después le saque el acceso)."""
        asesor, h_asesor = self._registrarse("Asesora")
        self._dar_plan_asesor(asesor)
        cliente = self._crear_cliente(h_asesor)
        h_cliente = self._reclamar(h_asesor, cliente)
        conn = main.get_db()
        try:
            fila = conn.execute("SELECT managed_by, approved FROM users WHERE id=?",
                                (cliente,)).fetchone()
        finally:
            conn.close()
        self.assertEqual((fila["managed_by"], bool(fila["approved"])), (None, True),
                         "el montaje no reproduce el caso: la cuenta tiene que estar reclamada")
        self.assertFalse(self._falta(h_cliente))
        self._sql("UPDATE advisor_clients SET status='revoked', revoked_at=datetime('now') "
                  "WHERE client_uid=?", (cliente,))
        self.assertFalse(self._falta(h_cliente))

    def test_managed_by_sin_vinculo(self):
        """`managed_by` solo, sin fila en `advisor_clients`: también afuera."""
        asesor, _ = self._registrarse("Asesora")
        uid, h = self._registrarse()
        self.assertTrue(self._falta(h), "control: sin managed_by le tocaba")
        self._sql("UPDATE users SET managed_by=? WHERE id=?", (asesor, uid))
        self.assertFalse(self._falta(h))

    def test_la_cuenta_creada_antes_del_corte(self):
        for created_at in ("2026-11-24 23:59:59",       # como la escribe SQLite
                           "2026-11-24T23:59:59",       # como la escribe Python
                           # ⚠️ La trampa: el mismo día del corte, ANTES de las 03:00
                           # UTC, escrita con 'T'. Comparada cruda contra el corte
                           # ('T' > ' ') pasaba por posterior.
                           "2026-11-25T02:59:59",
                           "2026-11-25T02:59:59.999999",
                           "2026-11-25 02:59:59",
                           "2025-03-01 12:00:00"):
            with self.subTest(created_at=created_at):
                _, h = self._cuenta_con_fecha_de_alta(created_at)
                self.assertFalse(self._falta(h))

    def test_desde_el_corte_si_le_toca(self):
        """La otra cara de la anterior: desde el segundo del corte, con 'T' o con
        espacio, le toca. Sin esto, una regla que devolviera siempre False pasaría
        las pruebas de arriba."""
        for created_at in (CORTE, CORTE.replace(" ", "T"), "2026-11-25T03:00:00.000001",
                           "2026-11-25 03:00:01", "2027-01-10 15:00:00"):
            with self.subTest(created_at=created_at):
                _, h = self._cuenta_con_fecha_de_alta(created_at)
                self.assertTrue(self._falta(h))

    def test_sin_fecha_de_alta(self):
        uid, h = self._cuenta_con_fecha_de_alta(None)
        conn = main.get_db()
        try:
            self.assertIsNone(conn.execute("SELECT created_at FROM users WHERE id=?",
                                           (uid,)).fetchone()["created_at"],
                              "el montaje no reproduce el caso: created_at tiene que ser NULL")
        finally:
            conn.close()
        self.assertFalse(self._falta(h))


class AsesorMirandoAUnCliente(_Base):

    def test_el_campo_responde_por_el_asesor(self):
        """Con un asesor mirando la cuenta de un cliente vacío, la app manda el
        encabezado X-Rendi-Client-Id en TODOS los pedidos, `/api/auth/me` incluido.
        Ahí el servidor lo ignora (`/api/auth` está en CLIENT_CTX_EXEMPT_PREFIXES):
        `/auth/me` contesta siempre por quien inició sesión. Eso es lo que esta prueba
        protege: con el encabezado del cliente, la respuesta es la del ASESOR —su
        `id` y su `falta_cargar_historial`—, no la del cliente.

        El cliente es una persona que se registró sola y le dio acceso (vínculo
        'linked', por SQL: el pedido de acceso tiene su propio ida y vuelta de
        mails): a ELLA sí le toca la bienvenida, y eso no puede tapar la pantalla del
        asesor. Si alguien saca `/api/auth` de la lista de exentos, `/auth/me`
        empieza a contestar con el `id` del cliente y esta prueba se pone en rojo.
        (Que la pantalla no muestre la bienvenida mientras el asesor mira a un
        cliente lo decide además `clientCtx` en utils/bienvenidaObligatoria.js.)"""
        asesor, h_asesor = self._registrarse("Asesora")
        self._dar_plan_asesor(asesor)
        cliente, h_cliente = self._registrarse("Juan")
        self._sql("INSERT INTO advisor_clients (advisor_uid, client_uid, link_type, permission, "
                  "status) VALUES (?, ?, 'linked', 'read_write', 'active')", (asesor, cliente))
        self.assertTrue(self._falta(h_cliente), "control: al cliente, en su cuenta, le toca")
        propio = self._me(h_asesor)
        self.assertEqual(propio["id"], asesor)
        self.assertFalse(propio["falta_cargar_historial"], "control: al asesor no le toca")
        mirando = self._me({**h_asesor, "X-Rendi-Client-Id": str(cliente)})
        self.assertEqual(mirando["id"], asesor,
                         "/auth/me contestó por el cliente: el encabezado ya no se ignora ahí")
        self.assertEqual(mirando["falta_cargar_historial"], propio["falta_cargar_historial"])



class FallaAbierta(_Base):

    def test_si_la_consulta_revienta_deja_entrar(self):
        """Un error en la regla no puede encerrar a nadie afuera de su cuenta: el campo
        da False, `/api/auth/me` contesta igual (es el pedido que arranca la app) y el
        resto de sus campos siguen llegando."""
        uid, h = self._registrarse()
        self.assertTrue(self._falta(h), "control: sin la falla le tocaba")
        with mock.patch.object(bienvenida, "no_es_un_pase",
                               return_value="esto no es SQL valido ((("), \
                self.assertLogs("bienvenida", level="WARNING") as registro:
            d = self._me(h)
        self.assertFalse(d["falta_cargar_historial"])
        self.assertIn(f"uid={uid}", "\n".join(registro.output))
        self.assertIn(d["tier"], ("pro", "plus"))
        self.assertFalse(d["cuenta_en_pausa"])

    def test_la_cuenta_que_no_existe(self):
        conn = main.get_db()
        try:
            self.assertFalse(bienvenida.falta_cargar_historial(conn, 987654321))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
