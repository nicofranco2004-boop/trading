"""IOL Lab (PLAN_iol_sync.md, Fase 0) — cliente read-only + endpoints /api/iol/lab/*.

Verifica lo que importa de la superficie de seguridad y del flujo:
  • el cliente NO puede salir a la red por ningún path de escritura (guard);
  • el probe anonimiza PII y resume tipos/estados/S5/S6;
  • gate por allowlist de emails (503 sin config, 403 fuera de la lista, admin pasa);
  • probe end-to-end contra un IOL falso (httpx.MockTransport): login → thread →
    run 'ok' con summary, credencial 'iol_lab' guardada cifrada (solo el refresh
    token), bitácora iniciada;
  • cron renueva y rota el token; cuando IOL rechaza el refresh → token borrado,
    bitácora dice 'dead' (esa es la medición); disconnect borra.

Corre con: cd backend && python3 -m pytest tests/test_iol_lab.py
"""
import json
import os
import sys
import tempfile
import time
import unittest
from urllib.parse import parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-iol-lab-" + "x" * 20)

import httpx
from fastapi.testclient import TestClient

import iol_api as I
import main


# ─── IOL falso ───────────────────────────────────────────────────────────────

class FakeIol:
    """Simula api.invertironline.com. Tokens: RT<n> rota a RT<n+1>; `dead` hace que
    todo refresh falle con 400 invalid_grant (token vencido)."""
    def __init__(self):
        self.dead = False
        self.calls = []
        # Historia AUTO-CONSISTENTE (sabemos la verdad):
        #   GGAL: compra 100@1500 + compra 50@1600 − venta 30@1900 = 120 en pesos
        #   GGALD (pata dólar, sin conducto): compra 10@8.2 → 10 GGAL en la sub-cuenta USD
        #   PRREMIB: suscripción FCI 1000@1.5
        #   AL30: compra CANCELADA (no entra) · Caución (no entra)
        def op(n, tipo, sim, qty, px, fecha, estado="terminada"):
            return {"numero": n, "fechaOrden": fecha + "T11:00:00", "tipo": tipo, "estado": estado,
                    "mercado": "bCBA", "simbolo": sim, "cantidad": qty, "monto": qty * px, "precio": px,
                    "fechaOperada": fecha + "T11:05:00", "cantidadOperada": qty if estado == "terminada" else 0,
                    "precioOperado": px, "montoOperado": qty * px, "plazo": "a48horas"}
        self.ops = [
            op(100, "Compra", "GGAL", 100, 1500.0, "2024-01-10"),
            op(101, "Compra", "GGAL", 50, 1600.0, "2024-02-15"),
            op(102, "Venta", "GGAL", 30, 1900.0, "2024-03-20"),
            op(103, "Suscripción FCI", "PRREMIB", 1000, 1.5, "2024-04-01"),
            op(104, "Compra", "GGALD", 10, 8.2, "2024-05-05"),
            op(105, "Compra", "AL30", 100, 50000.0, "2024-06-01", estado="cancelada"),
            op(106, "Caución", "CAUCION", 1, 100000.0, "2024-06-10"),
        ]
        self.moneda_by_numero = {104: "dolar_Estadounidense"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        p = request.url.path
        self.calls.append((request.method, p))
        if p == "/token":
            q = parse_qs(request.content.decode())
            if q.get("grant_type") == ["password"]:
                if q.get("password") == ["secret"]:
                    return httpx.Response(200, json={"access_token": "AT1", "token_type": "bearer",
                                                     "expires_in": 899, "refresh_token": "RT1"})
                return httpx.Response(400, json={"error": "invalid_grant"})
            if q.get("grant_type") == ["refresh_token"]:
                rt = q.get("refresh_token", [""])[0]
                if self.dead or not rt.startswith("RT"):
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"access_token": "AT2", "expires_in": 899,
                                                 "refresh_token": "RT" + str(int(rt[2:]) + 1)})
            return httpx.Response(400, json={"error": "invalid_grant"})
        if request.headers.get("Authorization") not in ("Bearer AT1", "Bearer AT2"):
            return httpx.Response(401, json={})
        if p == "/api/v2/Asesor/Movimientos":
            return httpx.Response(403, json={"message": "solo asesores"})
        if p == "/api/v2/datos-perfil":
            return httpx.Response(200, json={"nombre": "Juan", "apellido": "Perez", "numeroCuenta": "123",
                                             "dni": "1", "cuitCuil": "2", "email": "a@b", "perfilInversor": "moderado",
                                             "cuentaAbierta": True, "actualizarTyC": False, "actualizarDDJJ": False})
        if p == "/api/v2/estadocuenta":
            return httpx.Response(200, json={"cuentas": [{"numero": "123", "tipo": "inversion_Argentina_Pesos",
                                                          "moneda": "peso_Argentino", "disponible": 100.0, "saldo": 100.0,
                                                          "titulosValorizados": 5000.0, "saldos": [], "estado": "operable"}],
                                             "totalEnPesos": 5100.0})
        if p.startswith("/api/v2/portafolio/"):
            return httpx.Response(200, json={"pais": "argentina", "activos": [
                {"cantidad": 10, "ppc": 90.0, "ultimoPrecio": 100.0, "valorizado": 1000.0,
                 "titulo": {"simbolo": "GGAL", "tipo": "aCCIONES", "moneda": "peso_Argentino", "mercado": "bCBA"}}]})
        if p == "/api/v2/operaciones":
            d0 = request.url.params.get("filtro.fechaDesde", "2000")[:10]
            d1 = request.url.params.get("filtro.fechaHasta", "2100")[:10]
            return httpx.Response(200, json=[o for o in self.ops if d0 <= o["fechaOrden"][:10] <= d1])
        if p.startswith("/api/v2/operaciones/"):
            n = int(p.rsplit("/", 1)[1])
            return httpx.Response(200, json={"numero": n, "tipo": "compra",
                                             "moneda": self.moneda_by_numero.get(n, "peso_Argentino"),
                                             "aranceles": [{"tipo": "comision", "monto": 12.5}], "arancelesARS": 15.1,
                                             "arancelesUSD": 0, "estados": [{"estado": "terminada"}],
                                             "operaciones": [{"fecha": "2024-01-10", "cantidad": 10, "precio": 100}]})
        if p == "/api/v2/Notificacion":
            return httpx.Response(200, json={"notificaciones": []})
        return httpx.Response(404, json={})


FAKE = FakeIol()
I._transport = httpx.MockTransport(FAKE.handler)
main._IOL_LAB_PROBE_KW.update({"pause": 0, "burst": 3, "year_from": 2024})
main._IOL_LAB_IMPORT_KW.update({"pause": 0, "year_from": 2024})


def _mk_user(email, admin=0):
    conn = main.get_db()
    try:
        cur = conn.execute("INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?,?,1,?)",
                           (email, "x", admin))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _client(uid):
    c = TestClient(main.app)
    c.cookies.set(main.COOKIE_NAME, main.create_token(uid))
    return c


def _wait_run(c, timeout=15):
    for _ in range(int(timeout / 0.2)):
        st = c.get("/api/iol/lab/status").json()
        if st.get("run") and st["run"]["status"] != "running" and not st.get("running"):
            return st
        time.sleep(0.2)
    raise AssertionError("el probe no terminó a tiempo")


# ─── Tests ───────────────────────────────────────────────────────────────────

class GuardTest(unittest.TestCase):
    def test_write_paths_blocked_before_network(self):
        before = len(FAKE.calls)
        for m, p in [("GET", "/api/v2/operar/Comprar"), ("POST", "/api/v2/operar/Vender"),
                     ("POST", "/api/v2/operar/rescate/fci"), ("DELETE", "/api/v2/operaciones/1"),
                     ("GET", "/api/v2/cuentas-bancarias"), ("POST", "/api/v2/cuentas-bancarias/extraccion"),
                     ("PUT", "/api/v2/estadocuenta"), ("GET", "/api/v2/operacionesX")]:
            with self.assertRaises(I.IolGuardError, msg=f"{m} {p}"):
                I._request(m, p, "AT1")
        self.assertEqual(len(FAKE.calls), before, "un path prohibido salió a la red")

    def test_module_has_no_write_functions(self):
        names = {n.lower() for n in dir(I)}
        for bad in ("comprar", "vender", "buy", "sell", "suscrib", "rescat", "extraccion", "cancel"):
            self.assertFalse(any(bad in n for n in names), bad)

    def test_query_string_does_not_break_allowlist(self):
        body, _, _ = I.get("/api/v2/operaciones", "AT1", **{"filtro.estado": "todas",
                                                            "filtro.fechaDesde": "2024-01-01",
                                                            "filtro.fechaHasta": "2024-12-31"})
        self.assertEqual(len(body), 7)


class ProbeTest(unittest.TestCase):
    def test_probe_summary_and_masking(self):
        res = I.run_probe("AT1", pause=0, burst=3, year_from=2024)
        s = res["summary"]
        self.assertIn("tipos: {'Compra': 4, 'Venta': 1, 'Suscripción FCI': 1, 'Caución': 1}", s)
        self.assertIn("S6 tope: año 2024 anual=7 vs suma mensual=7 (IGUAL", s)
        self.assertIn("HTTP 403", s)                       # Asesor/Movimientos
        self.assertIn("aranceles=[{'tipo': 'comision'", s)
        dumped = json.dumps(res["result"], ensure_ascii=False)
        for pii in ("Juan", "Perez", "a@b", '"123"'):
            self.assertNotIn(pii, dumped)
        self.assertEqual(res["result"]["datos_perfil"]["nombre"], "***")
        self.assertEqual(res["result"]["estadocuenta"]["cuentas"][0]["numero"], "***")
        self.assertEqual(res["result"]["operaciones_todas"][0]["numero"], 100)   # int = nro de operación, se conserva
        self.assertEqual(res["stats"]["ops"], 7)


class LabEndpointsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tester = _mk_user("tester@rendi.test")
        cls.other = _mk_user("otro@rendi.test")
        cls.admin = _mk_user("admin@rendi.test", admin=1)

    def setUp(self):
        FAKE.dead = False
        os.environ["IOL_LAB_EMAILS"] = "tester@rendi.test"
        os.environ["IOL_LAB_CRON_TOKEN"] = "cron-secret"

    def test_gate(self):
        os.environ["IOL_LAB_EMAILS"] = ""
        st = _client(self.tester).get("/api/iol/lab/status").json()
        self.assertFalse(st["enabled"]); self.assertIn("no está habilitado", st["reason"])
        os.environ["IOL_LAB_EMAILS"] = "tester@rendi.test"
        st = _client(self.other).get("/api/iol/lab/status").json()
        self.assertFalse(st["enabled"]); self.assertIn("no está habilitada", st["reason"])
        r = _client(self.other).post("/api/iol/lab/probe", json={"username": "u", "password": "secret"})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(_client(self.admin).get("/api/iol/lab/status").json()["enabled"])
        self.assertTrue(_client(self.tester).get("/api/iol/lab/status").json()["enabled"])

    def test_bad_login_is_400_with_hint_and_stores_nothing(self):
        c = _client(self.tester)
        r = c.post("/api/iol/lab/probe", json={"username": "juan", "password": "wrong"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("activación de APIs", r.json()["detail"])
        conn = main.get_db()
        try:
            self.assertIsNone(conn.execute(
                "SELECT 1 FROM user_broker_credentials WHERE user_id=? AND broker='iol_lab'", (self.tester,)).fetchone())
            self.assertIsNone(conn.execute("SELECT 1 FROM iol_lab_runs WHERE user_id=?", (self.tester,)).fetchone())
        finally:
            conn.close()

    def test_probe_e2e_then_cron_then_dead_then_disconnect(self):
        c = _client(self.tester)
        r = c.post("/api/iol/lab/probe", json={"username": "juan", "password": "secret", "keep_token": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "started"); self.assertTrue(r.json()["watch"])
        st = _wait_run(c)
        self.assertEqual(st["run"]["status"], "ok", st["run"])
        self.assertIn("tipos: {'Compra': 4", st["run"]["summary"])
        # credencial: SOLO el refresh token, cifrado (no la contraseña, no el bearer)
        conn = main.get_db()
        try:
            row = conn.execute("SELECT api_key_enc, last_sync_status FROM user_broker_credentials "
                               "WHERE user_id=? AND broker='iol_lab'", (self.tester,)).fetchone()
            self.assertIsNotNone(row)
            self.assertNotIn("RT1", row["api_key_enc"]); self.assertNotIn("secret", row["api_key_enc"])
            self.assertEqual(main._wallbit_decrypt(row["api_key_enc"]), "RT1")
            self.assertEqual(row["last_sync_status"], "watch:0")
            res = json.loads(conn.execute("SELECT result_json FROM iol_lab_runs WHERE user_id=? ORDER BY id DESC",
                                          (self.tester,)).fetchone()["result_json"])
            self.assertEqual(res["datos_perfil"]["apellido"], "***")
        finally:
            conn.close()
        self.assertTrue(st["watch"]["active"]); self.assertEqual(st["watch"]["refresh_count"], 1)  # el login cuenta

        # cron sin token → 401; con token → renueva y rota RT1→RT2
        self.assertEqual(TestClient(main.app).get("/api/iol/lab/run-cron").status_code, 401)
        r = TestClient(main.app).get("/api/iol/lab/run-cron", headers={"X-Cron-Token": "cron-secret"})
        self.assertEqual(r.json()["renewed"], 1, r.text)
        conn = main.get_db()
        try:
            self.assertEqual(main._wallbit_decrypt(conn.execute(
                "SELECT api_key_enc FROM user_broker_credentials WHERE user_id=? AND broker='iol_lab'",
                (self.tester,)).fetchone()["api_key_enc"]), "RT2")
        finally:
            conn.close()
        st = c.get("/api/iol/lab/status").json()
        self.assertEqual(st["watch"]["status"], "watch:1"); self.assertEqual(st["watch"]["refresh_count"], 2)

        # renovar a mano
        r = c.post("/api/iol/lab/refresh").json()
        self.assertTrue(r["ok"]); self.assertEqual(r["count"], 2)

        # IOL mata el token → cron lo detecta: credencial borrada, bitácora 'dead'
        FAKE.dead = True
        r = TestClient(main.app).post("/api/iol/lab/run-cron?token=cron-secret").json()
        self.assertEqual(r["dead"], 1)
        st = c.get("/api/iol/lab/status").json()
        self.assertFalse(st["watch"]["active"]); self.assertIn("dead: HTTP 400", st["watch"]["status"])
        self.assertEqual(st["watch"]["refresh_count"], 3); self.assertIsNotNone(st["watch"]["hours_alive"])

        # admin ve todo; el tester no
        self.assertEqual(c.get("/api/admin/iol-lab/runs").status_code, 403)
        a = _client(self.admin).get("/api/admin/iol-lab/runs").json()
        self.assertEqual(a["runs"][0]["email"], "tester@rendi.test")
        self.assertEqual(a["watches"][0]["user_id"], self.tester)

        # nueva prueba sin keep_token no toca la (ex) credencial; disconnect es idempotente
        FAKE.dead = False
        r = c.post("/api/iol/lab/probe", json={"username": "juan", "password": "secret", "keep_token": False})
        self.assertEqual(r.status_code, 200); self.assertFalse(r.json()["watch"])
        _wait_run(c)
        self.assertFalse(c.get("/api/iol/lab/status").json()["watch"]["active"])
        self.assertEqual(c.delete("/api/iol/lab/disconnect").json()["deleted"], False)

    def test_cron_without_config_is_503(self):
        os.environ["IOL_LAB_CRON_TOKEN"] = ""
        self.assertEqual(TestClient(main.app).get("/api/iol/lab/run-cron").status_code, 503)


class AdapterTest(unittest.TestCase):
    """API → CSV 'Movimientos históricos' → parser IOL real."""

    def test_csv_parses_with_iol_parser(self):
        from importing.parsers.iol import IolParser
        det = {104: {"moneda": "dolar_Estadounidense", "arancelesUSD": 0.5, "aranceles": []},
               100: {"moneda": "peso_Argentino", "arancelesARS": 1500.0, "aranceles": []}}
        conv = I.to_movimientos_csv(FAKE.ops, det)
        self.assertEqual(conv["rows"], 5)
        motivos = {sk["numero"]: sk["motivo"] for sk in conv["skipped"]}
        self.assertIn("no operada", motivos[105]); self.assertIn("caución", motivos[106])
        pr = IolParser().parse(conv["csv"])
        self.assertEqual(pr.parse_errors, [])
        by = {r.data["notas"].split(" · ")[1]: r.data for r in pr.raw_rows}   # 'Boleto N'
        self.assertEqual(by["Boleto 100"]["tipo"], "COMPRA"); self.assertEqual(by["Boleto 100"]["activo"], "GGAL")
        self.assertEqual(by["Boleto 100"]["moneda"], "ARS")
        # A2: monto bruto + aranceles = neto 151500 → precio derivado 1515
        self.assertAlmostEqual(float(by["Boleto 100"]["monto"]), 151500.0)
        self.assertAlmostEqual(float(by["Boleto 100"]["precio"]), 1515.0)
        self.assertEqual(by["Boleto 104"]["moneda"], "USD"); self.assertEqual(by["Boleto 104"]["activo"], "GGAL")
        self.assertEqual(by["Boleto 103"]["tipo"], "COMPRA")
        self.assertEqual(pr.raw_rows[[i for i, r in enumerate(pr.raw_rows) if "Boleto 103" in r.data["notas"]][0]].data.get("asset_type"), "FUND")
        self.assertEqual(by["Boleto 102"]["tipo"], "VENTA")
        self.assertIn("A2", " ".join(conv["assumptions"]))

    def test_moneda_inferida_sin_detalle(self):
        conv = I.to_movimientos_csv(FAKE.ops, {})
        self.assertIn("Compra(GGALD)", conv["csv"])
        line = [l for l in conv["csv"].splitlines() if "Compra(GGALD)" in l][0]
        self.assertTrue(line.endswith("Cuenta Dólares"))
        self.assertTrue(any(a.startswith("A3") for a in conv["assumptions"]))

    def test_fetch_historial_refreshes_on_401(self):
        # bearer vencido a mitad del fetch → _TokenBox renueva con el refresh y sigue
        calls = {"n": 0}
        orig = FAKE.handler
        def flaky(request):
            if request.url.path == "/api/v2/operaciones" and calls["n"] == 0:
                calls["n"] += 1
                return httpx.Response(401, json={})
            return orig(request)
        I._transport = httpx.MockTransport(flaky)
        try:
            hist = I.fetch_historial({"access_token": "AT1", "refresh_token": "RT1"}, pause=0, year_from=2024)
        finally:
            I._transport = httpx.MockTransport(FAKE.handler)
        self.assertEqual(hist["ops"], 7); self.assertEqual(hist["rows"], 5); self.assertEqual(hist["details"], 5)


class ImportE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tester = _mk_user("importer@rendi.test")
        os.environ["IOL_LAB_EMAILS"] = "tester@rendi.test,importer@rendi.test"

    def test_import_start_preview_confirm(self):
        c = _client(self.tester)
        r = c.post("/api/iol/lab/import-start", json={"username": "juan", "password": "secret"})
        self.assertEqual(r.status_code, 200, r.text)
        imp = None
        for _ in range(75):
            imp = c.get("/api/iol/lab/import-status").json()["import"]
            if imp and imp["status"] != "running":
                break
            time.sleep(0.2)
        self.assertEqual(imp["status"], "ok", imp)
        self.assertEqual(imp["stats"]["rows"], 5); self.assertEqual(len(imp["stats"]["skipped"]), 2)
        pv = imp["preview"]
        self.assertTrue(pv["session_id"])
        # confirm por el endpoint NORMAL del wizard
        r = c.post("/api/imports/confirm", json={"session_id": pv["session_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        conn = main.get_db()
        try:
            q = conn.execute("SELECT SUM(quantity) FROM positions WHERE user_id=? AND asset='GGAL' AND is_cash=0",
                             (self.tester,)).fetchone()[0]
            self.assertAlmostEqual(q or 0, 130.0, places=4)   # 120 en pesos + 10 pata dólar
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM brokers WHERE user_id=? AND name='IOL' AND currency='ARS'", (self.tester,)).fetchone())
        finally:
            conn.close()
        # segunda vuelta: mismo historial → el dedup por fingerprint no duplica nada
        r = c.post("/api/iol/lab/import-start", json={"username": "juan", "password": "secret"})
        self.assertEqual(r.status_code, 200)
        for _ in range(75):
            imp = c.get("/api/iol/lab/import-status").json()["import"]
            if imp and imp["status"] != "running":
                break
            time.sleep(0.2)
        self.assertEqual(imp["status"], "ok", imp)
        self.assertEqual(len(imp["preview"].get("duplicate_row_indices") or []), 5)

    def test_bad_login_no_import_row(self):
        c = _client(self.tester)
        r = c.post("/api/iol/lab/import-start", json={"username": "juan", "password": "nope"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
