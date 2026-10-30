"""El diario de operaciones de Movimientos (pieza 11) y la tesis.

Entra por el camino de producción, como test_tecnico.py: las compras se cargan
por HTTP (/api/positions), se venden con la venta FIFO de siempre
(/api/positions/sell, que escribe una operación por lote), las velas las guarda
el trabajo nocturno real (`main._run_velas_diarias_job`) con Yahoo reemplazado
en su punto más bajo, y la tendencia de cada compra se pide por HTTP con la
fecha que trae /api/operations.

Lo que importa:
  · un activo que VENDISTE entero sigue teniendo velas (si no, el diario dice
    «sin dato» en toda tu historia);
  · venta parcial y venta que barre dos lotes: cada operación con la tendencia
    del día de SU lote;
  · compra un sábado → la vela del viernes; sin velas ese día / sin 200 días
    antes / bono → «sin dato» con el motivo, nunca un Alcista inventado;
  · CEDEAR vendido en pesos → la tendencia de la acción de afuera (en dólares);
    acción argentina → su precio de BYMA ÷ el MEP de cada día;
  · la tesis: por activo, con historia por día, la tendencia de ese día y la de
    hoy; el recordatorio es una alerta del motor de siempre que no cuenta para
    el tope del plan, no aparece en «Mis alertas» y llega por mail y push.

Corre con: cd backend && python3 -m pytest tests/test_diario_operaciones.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import pandas as pd
from fastapi.testclient import TestClient

import alerts_engine
import main
import tesis
from fechas import hoy_art_date


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class YahooFalso:
    """`precios[ticker](i)` da el cierre de la rueda i (0 = la más vieja)."""

    def __init__(self, hoy):
        self.hoy, self.precios = hoy, {}

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        f = self.precios.get(ticker)
        if f is None:
            return pd.DataFrame()
        dias = _ruedas(self.hoy, 760 if period == "3y" else 22)
        base = _ruedas(self.hoy, 760)
        filas = {pd.Timestamp(d): f(base.index(d)) for d in dias}
        idx = sorted(filas)
        c = [filas[k] for k in idx]
        return pd.DataFrame({"Open": c, "High": [x * 1.01 for x in c], "Low": [x * 0.99 for x in c],
                             "Close": c, "Volume": [1000.0] * len(c)}, index=pd.DatetimeIndex(idx))


def sube_y_baja(i):
    """Sube 500 ruedas y después cae fuerte: alcista hasta ~la 500, bajista
    bien adentro de la caída."""
    return 100.0 + i if i < 500 else 600.0 - (i - 500) * 2


class Base(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "operations", "brokers", "fx_rates_daily", "tesis", "alerts",
                      "alert_events", "financial_events"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"diario-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.dias = _ruedas(self.hoy, 760)
        self.yahoo = YahooFalso(self.hoy)
        self.cedears = frozenset()
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("velas_diarias._cedears_de_byma", lambda: self.cedears)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _broker(self, name, currency):
        r = self.client.post("/api/brokers", json={"name": name, "currency": currency}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _compra(self, broker, asset, dia, qty=10, precio=100, asset_type="STOCK", currency=None):
        body = {"broker": broker, "asset": asset, "quantity": qty, "buy_price": precio,
                "asset_type": asset_type, "entry_date": dia.isoformat()}
        if currency:
            body["currency"] = currency
        r = self.client.post("/api/positions", json=body, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _venta(self, broker, asset, qty, dia, precio=120, **extra):
        r = self.client.post("/api/positions/sell", json={
            "broker": broker, "asset": asset, "quantity": qty, "exit_price": precio,
            "date": dia.isoformat(), **extra}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _operaciones(self):
        r = self.client.get("/api/operations", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return [o for o in r.json() if o["op_type"] == "Venta"]

    def _tendencias(self, ops, local=False):
        """Lo que pide la pantalla: una fila por operación, con SU fecha de compra."""
        r = self.client.post("/api/tecnico/en-fechas", json={"items": [
            {"id": str(o["id"]), "asset": o["asset"], "local": local, "fecha": o["entry_date"]}
            for o in ops]}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["resultados"]


class TendenciaAlComprarTest(Base):

    def test_venta_que_barre_dos_lotes_y_venta_parcial(self):
        self._broker("Schwab", "USD")
        self._compra("Schwab", "NVDA", self.dias[400])          # subiendo: alcista
        self._compra("Schwab", "NVDA", self.dias[650])          # cayendo: bajista
        self._venta("Schwab", "NVDA", 15, self.dias[700])       # el lote 1 entero + medio lote 2
        self._venta("Schwab", "NVDA", 5, self.dias[720])        # el resto: ya no tenés NVDA
        self.yahoo.precios["NVDA"] = sube_y_baja
        main._run_velas_diarias_job()                           # la noche DESPUÉS de vender todo

        ops = sorted(self._operaciones(), key=lambda o: (o["date"], o["entry_date"]))
        self.assertEqual([(o["entry_date"], o["quantity"]) for o in ops],
                         [(self.dias[400].isoformat(), 10), (self.dias[650].isoformat(), 5),
                          (self.dias[650].isoformat(), 5)],
                         "una operación por lote, cada una con la fecha de SU compra")
        t = self._tendencias(ops)
        self.assertEqual([t[str(o["id"])]["tendencia"] for o in ops], ["alcista", "bajista", "bajista"],
                         "vendiste todo y las velas siguen: se siguen por las operaciones")
        a = t[str(ops[0]["id"])]
        self.assertEqual(a["fecha"], self.dias[400].isoformat())
        self.assertAlmostEqual(a["precio"], 500.0)
        self.assertAlmostEqual(a["media200"], sum(100.0 + i for i in range(201, 401)) / 200)

    def test_sabado_sin_velas_pocos_dias_y_bono(self):
        self._broker("Schwab", "USD")
        sabado = self.dias[400] + timedelta(days=(5 - self.dias[400].weekday()) % 7 or 7)
        self.assertEqual(sabado.weekday(), 5)
        viernes = sabado - timedelta(days=1)
        self._compra("Schwab", "MSFT", sabado)
        self._compra("Schwab", "MSFT", self.dias[100])          # sin 200 días antes
        self._compra("Schwab", "MSFT", self.dias[0] - timedelta(days=60))  # antes de lo guardado
        self._venta("Schwab", "MSFT", 30, self.dias[740])
        self.yahoo.precios["MSFT"] = sube_y_baja
        main._run_velas_diarias_job()
        por_fecha = {o["entry_date"]: o for o in self._operaciones()}
        t = self._tendencias(list(por_fecha.values()))
        sab = t[str(por_fecha[sabado.isoformat()]["id"])]
        self.assertEqual((sab["tendencia"], sab["fecha"]), ("alcista", viernes.isoformat()),
                         "un sábado se lee con la vela del viernes")
        self.assertEqual(t[str(por_fecha[self.dias[100].isoformat()]["id"])],
                         {"tendencia": None, "motivo": "pocos_dias", "fecha": self.dias[100].isoformat()})
        viejo = (self.dias[0] - timedelta(days=60)).isoformat()
        self.assertEqual(t[str(por_fecha[viejo]["id"])], {"tendencia": None, "motivo": "sin_precio"})
        # Un bono no tiene tendencia; un símbolo raro tampoco rompe el pedido.
        r = self.client.post("/api/tecnico/en-fechas", json={"items": [
            {"id": "b", "asset": "AL30", "fecha": self.dias[400].isoformat()},
            {"id": "x", "asset": "<script>", "fecha": self.dias[400].isoformat()}]}, headers=self.h)
        self.assertEqual(r.json()["resultados"], {"b": {"tendencia": None, "motivo": "sin_velas"},
                                                  "x": {"tendencia": None, "motivo": "sin_velas"}})

    def test_cedear_vendido_en_pesos_se_lee_con_la_accion_de_afuera(self):
        self._broker("IOL", "ARS")
        self.cedears = frozenset({"AAPL"})          # BYMA lo lista como CEDEAR
        self._compra("IOL", "AAPL", self.dias[650], precio=20000, asset_type="CEDEAR", currency="ARS")
        self._venta("IOL", "AAPL", 10, self.dias[700], precio=25000, tc_venta=1200)
        # Afuera cae; en pesos SUBE porque sube el dólar: la misma empresa.
        self.yahoo.precios["AAPL"] = sube_y_baja
        self.yahoo.precios["AAPL.BA"] = lambda i: 10000.0 + i * 40
        main._run_velas_diarias_job()
        ops = self._operaciones()
        self.assertEqual(ops[0]["currency"], "ARS")
        t = self._tendencias(ops)          # la pantalla manda local=False: es un CEDEAR
        self.assertEqual(t[str(ops[0]["id"])]["tendencia"], "bajista",
                         "en dólares, como la ficha: la de pesos diría alcista por el dólar")

    def test_accion_argentina_con_el_mep_de_cada_dia(self):
        self._broker("IOL", "ARS")
        with main.db_abierta() as conn:
            for i, d in enumerate(self.dias):      # el dólar sube más rápido que la acción
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1100.0 + i * 3, 1000.0 + i * 3))
            conn.commit()
        self._compra("IOL", "GGAL", self.dias[600], precio=5000, asset_type="ACCION", currency="ARS")
        self._venta("IOL", "GGAL", 10, self.dias[700], precio=6000, tc_venta=3000)
        self.yahoo.precios["GGAL.BA"] = lambda i: 5000.0 + i     # en pesos sube
        self.yahoo.precios["GGAL"] = lambda i: 50.0 + i          # el ADR: no es tu acción
        with main.db_abierta() as conn:      # otro sigue el ADR: hay velas de «GGAL» pelado
            conn.execute("INSERT INTO watchlist (user_id, symbol, asset_type) VALUES (?, 'GGAL', 'STOCK')",
                         (self.uid,))
            conn.commit()
        main._run_velas_diarias_job()
        ops = self._operaciones()
        local = self._tendencias(ops, local=True)[str(ops[0]["id"])]
        self.assertEqual(local["tendencia"], "bajista", "en dólares de BYMA ÷ MEP cae")
        self.assertAlmostEqual(local["precio"], (5000.0 + 600) / (1000.0 + 600 * 3), places=4)
        self.assertEqual(self._tendencias(ops)[str(ops[0]["id"])]["tendencia"], "alcista",
                         "sin la marca de acción local se leería el ADR")

    def test_los_cobros_no_se_siguen(self):
        self._broker("Schwab", "USD")
        r = self.client.post("/api/operations", json={
            "date": self.dias[700].isoformat(), "broker": "Schwab", "asset": "KO",
            "op_type": "Dividendo", "pnl_usd": 5, "entry_date": self.dias[400].isoformat()},
            headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        import velas_diarias
        with main.db_abierta() as conn:
            self.assertNotIn("KO", velas_diarias.simbolos_a_seguir(conn))

    def test_tope_del_pedido(self):
        r = self.client.post("/api/tecnico/en-fechas", json={"items": [
            {"id": str(i), "asset": "AAPL", "fecha": "2026-01-02"} for i in range(2001)]}, headers=self.h)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.client.post("/api/tecnico/en-fechas", json={"items": []}).status_code, 401)


class TesisTest(Base):

    def setUp(self):
        super().setUp()
        self._broker("Schwab", "USD")
        self._compra("Schwab", "NVDA", self.dias[650])
        self.yahoo.precios["NVDA"] = sube_y_baja
        main._run_velas_diarias_job()

    def _guardar(self, texto, asset="NVDA", local=False):
        r = self.client.put("/api/tesis", json={"asset": asset, "texto": texto, "local": local}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["id"]

    def _lista(self):
        r = self.client.get("/api/tesis", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_escribir_corregir_el_mismo_dia_y_otro_dia_guarda_otra(self):
        a = self._guardar("Data centers e IA")
        b = self._guardar("Data centers e IA, y los chips nuevos")
        self.assertEqual(a, b, "el mismo día se corrige en el lugar")
        l = self._lista()
        self.assertEqual(len(l["items"]), 1)
        t = l["items"][0]
        self.assertEqual((t["asset"], t["escrita_el"], t["texto"]),
                         ("NVDA", self.hoy.isoformat(), "Data centers e IA, y los chips nuevos"))
        self.assertEqual(t["tendencia"]["tendencia"], "bajista", "la del día que la escribiste")
        self.assertEqual(l["hoy"]["NVDA"]["tendencia"], "bajista")
        self.assertNotIn("user_id", t)
        # Un mes después la reescribe: la vieja queda (para las ventas de antes).
        en_un_mes = self.hoy + timedelta(days=30)
        with mock.patch("tesis.hoy_art_date", lambda: en_un_mes):
            c = self._guardar("Ahora la tengo por el dividendo")
        self.assertNotEqual(c, a)
        items = self._lista()["items"]
        self.assertEqual([i["texto"] for i in items],
                         ["Data centers e IA, y los chips nuevos", "Ahora la tengo por el dividendo"])

    def test_validaciones_y_de_otro_usuario(self):
        for body in ({"asset": "NVDA", "texto": "   "}, {"asset": "NVDA", "texto": "x" * 1001},
                     {"asset": "<b>", "texto": "hola"}, {"asset": "  ", "texto": "hola"}):
            self.assertIn(self.client.put("/api/tesis", json=body, headers=self.h).status_code,
                          (400, 422), body)
        tid = self._guardar("mía")
        with main.db_abierta() as conn:
            otro = conn.execute("INSERT INTO users (email, password_hash, approved, email_verified) "
                                "VALUES (?, 'x', 1, 1)", (f"otro-{uuid.uuid4().hex[:6]}@rendi.test",)).lastrowid
            conn.commit()
        h2 = {"Authorization": f"Bearer {main.create_token(otro)}"}
        self.assertEqual(self.client.get("/api/tesis", headers=h2).json()["items"], [])
        self.assertEqual(self.client.delete(f"/api/tesis/{tid}", headers=h2).status_code, 404)
        self.assertEqual(self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"},
                                         headers=h2).status_code, 404)

    def test_recordatorio_en_3_meses_no_cuenta_como_alerta(self):
        tid = self._guardar("Data centers")
        with main.db_abierta() as conn:
            conn.execute("UPDATE users SET tier='free' WHERE id=?", (self.uid,))
            conn.commit()
        r = self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["fecha"], tesis._sumar_meses(self.hoy, 3).isoformat())
        rec = self._lista()["items"][0]["recordatorio"]
        self.assertEqual((rec["tipo"], rec["avisado_at"]), ("3m", None))
        # No aparece en «Mis alertas» ni gasta el tope del plan Free (3).
        al = self.client.get("/api/alerts", headers=self.h).json()
        self.assertEqual(al["items"], [])
        from ai import plan
        with main.db_abierta() as conn:
            self.assertEqual(plan.check_alert_quota(conn, self.uid)[1]["current_count"], 0)
        # Cambiarla reusa la misma alerta; sacarla la borra.
        manana = (self.hoy + timedelta(days=1)).isoformat()
        r = self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "fecha", "fecha": manana},
                            headers=self.h)
        self.assertEqual(r.json()["fecha"], manana)
        with main.db_abierta() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 1)
        self.client.delete(f"/api/tesis/{tid}/recordatorio", headers=self.h)
        self.assertIsNone(self._lista()["items"][0]["recordatorio"])
        with main.db_abierta() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 0)

    def test_fechas_invalidas(self):
        tid = self._guardar("x")
        for body in ({"tipo": "fecha", "fecha": self.hoy.isoformat()},
                     {"tipo": "fecha", "fecha": (self.hoy + timedelta(days=800)).isoformat()},
                     {"tipo": "fecha", "fecha": "mañana"},
                     {"tipo": "nunca"}):
            r = self.client.put(f"/api/tesis/{tid}/recordatorio", json=body, headers=self.h)
            self.assertEqual(r.status_code, 400, body)

    def test_despues_del_balance(self):
        tid = self._guardar("Esperando el balance")
        balance = (self.hoy + timedelta(days=20)).isoformat()
        eventos = [{"ticker": "NVDA", "event_type": "earnings", "event_date": balance,
                    "details": {}, "confirmed": 1}]
        with mock.patch("main._fetch_yf_events", lambda t, fallas=None: eventos if t == "NVDA" else []):
            r = self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "balance"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["balance"], balance)
        self.assertEqual(r.json()["fecha"], (self.hoy + timedelta(days=21)).isoformat(),
                         "el día DESPUÉS del balance, con los números ya publicados")
        # Sin balance conocido (un ETF): lo dice, no inventa una fecha.
        self._compra("Schwab", "SPY", self.dias[650])
        t2 = self._guardar("Índice", asset="SPY")
        with mock.patch("main._fetch_yf_events", lambda t, fallas=None: []):
            r = self.client.put(f"/api/tesis/{t2}/recordatorio", json={"tipo": "balance"}, headers=self.h)
        self.assertEqual(r.status_code, 400)
        self.assertIn("próximo balance", r.json()["detail"])

    def test_el_recordatorio_llega_por_mail_y_push_una_sola_vez(self):
        tid = self._guardar("Data centers e IA")
        self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.h)
        with main.db_abierta() as conn:      # llegó el día
            conn.execute("UPDATE tesis SET recordar_el=? WHERE id=?", (self.hoy.isoformat(), tid))
            conn.commit()
        mails, pushes = [], []
        with mock.patch("billing.emails.send_alert_email", lambda **kw: mails.append(kw) or True), \
             mock.patch("main._send_push_to_user", lambda uid, p: pushes.append((uid, p)) or 1):
            # A las 8:59 de Argentina todavía no (un push a la madrugada despierta).
            antes = datetime.combine(self.hoy, datetime.min.time()) + timedelta(hours=11, minutes=59)
            with main.db_abierta() as conn:
                self.assertEqual(alerts_engine.evaluar_recordatorios(conn, now=antes), {"recordatorios": 0})
            # El cron de siempre, de día.
            with mock.patch("alerts_engine.HORA_RECORDATORIO", 0):
                main._evaluar_alertas_job()
                main._evaluar_alertas_job()           # la segunda corrida no repite
        self.assertEqual(len(mails), 1)
        self.assertEqual(len(pushes), 1)
        m = mails[0]
        self.assertEqual(m["titulo"], "Quedaste en revisar tu tesis de NVDA")
        self.assertTrue(m["detail"].startswith("escribiste esta tesis el "), m["detail"])
        self.assertIn("«Data centers e IA»", m["detail"])
        self.assertIn("no es una recomendación", m["detail"])
        self.assertEqual(m["heading"], m["titulo"])
        self.assertIn("abajo de su promedio de 200 días", m["detail"])
        self.assertEqual(m["cta_path"], "/activo/NVDA")
        self.assertNotRegex(m["detail"].lower(), r"vendé|comprá|mantené|deberías|conviene")
        self.assertEqual(pushes[0][1]["url"], "/activo/NVDA")
        rec = self._lista()["items"][0]["recordatorio"]
        self.assertIsNotNone(rec["avisado_at"])
        ev = self.client.get("/api/alerts", headers=self.h).json()["events"]
        self.assertEqual([e["message"] for e in ev], ["Quedaste en revisar tu tesis de NVDA"])

    def test_un_fondo_tambien_tiene_tesis(self):
        # Un fondo no tiene forma de ticker: con el activo en la ruta, el servidor
        # lo rechazaba («Símbolo inválido») y no había forma de escribir su tesis.
        # Es un fondo de SU cartera: la tesis es de un activo que tiene, operó o
        # sigue (main._exigir_activo_valido), no de texto libre.
        self._compra("Schwab", "FCI:COCOS-RENDIMIENTO-A", self.dias[700], asset_type="FCI")
        tid = self._guardar("Liquidez para la cuota del auto", asset="FCI:COCOS-RENDIMIENTO-A")
        l = self._lista()
        t = next(i for i in l["items"] if i["id"] == tid)
        self.assertEqual(t["asset"], "FCI:COCOS-RENDIMIENTO-A", "tal cual lo guarda la cartera")
        self.assertEqual(t["tendencia"], {"tendencia": None, "motivo": "sin_velas"})
        self.assertEqual(l["hoy"]["FCI:COCOS-RENDIMIENTO-A"]["tendencia"], None)

    def test_recordatorio_de_un_cliente_le_llega_al_asesor_diciendo_de_quien_es(self):
        with main.db_abierta() as conn:
            asesor = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified) VALUES (?, 'x', 1, 1)",
                (f"asesor-{uuid.uuid4().hex[:6]}@rendi.test",)).lastrowid
            conn.execute("UPDATE users SET managed_by=? WHERE id=?", (asesor, self.uid))
            conn.execute("INSERT INTO advisor_clients (advisor_uid, client_uid, label) VALUES (?, ?, 'Laura')",
                         (asesor, self.uid))
            conn.commit()
        tid = self._guardar("Data centers")
        self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.h)
        with main.db_abierta() as conn:
            conn.execute("UPDATE tesis SET recordar_el=? WHERE id=?", (self.hoy.isoformat(), tid))
            conn.commit()
        mails, pushes = [], []
        with mock.patch("billing.emails.send_alert_email", lambda **kw: mails.append(kw) or True), \
             mock.patch("main._send_push_to_user", lambda uid, p: pushes.append((uid, p)) or 1), \
             mock.patch("alerts_engine.HORA_RECORDATORIO", 0):
            main._evaluar_alertas_job()
        self.assertEqual([u for u, _ in pushes], [asesor])
        self.assertTrue(mails[0]["to"].startswith("asesor-"))
        self.assertEqual(mails[0]["heading"], "[Laura] Quedaste en revisar tu tesis de NVDA")
        # Adelante de la oración, no pegado a la última frase (auditoría B2, 29/10).
        self.assertTrue(mails[0]["detail"].startswith("en la cuenta de Laura, escribiste esta tesis"),
                        mails[0]["detail"])
        self.assertEqual((mails[0]["cta_path"], pushes[0][1]["url"]), ("/clientes", "/clientes"),
                         "la ficha del asesor no es la de su cliente")

    def test_un_recordatorio_que_no_se_puede_armar_queda_a_la_vista_y_no_frena_a_los_otros(self):
        """Auditoría B-P2 (29/10): si `para_el_aviso` reventaba, quedaba en un
        warning sin traza, no se contaba y se reintentaba cada 10 minutos para
        siempre sin que nadie lo viera. La misma guarda que las técnicas: nombre
        del error, traza, contado en el cron; los otros salen."""
        for asset in ("NVDA", "AAPL"):
            tid = self._guardar(f"tesis de {asset}", asset=asset)
            self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.h)
        with main.db_abierta() as conn:
            conn.execute("UPDATE tesis SET recordar_el=? WHERE user_id=?", (self.hoy.isoformat(), self.uid))
            conn.commit()
        import tesis as _t
        real = _t.para_el_aviso

        def aviso(conn, t):
            if t["asset"] == "AAPL":
                raise KeyError("tendencia_json")
            return real(conn, t)
        mails = []
        with mock.patch("billing.emails.send_alert_email", lambda **kw: mails.append(kw) or True), \
             mock.patch("main._send_push_to_user", lambda uid, p: 1), \
             mock.patch("tesis.para_el_aviso", aviso), \
             mock.patch("alerts_engine.HORA_RECORDATORIO", 0), \
             self.assertLogs("alerts", level="ERROR") as logs:
            r = main._evaluar_alertas_job()
        self.assertEqual((r["recordatorios"], r.get("errores_recordatorios")), (1, 1))
        self.assertTrue(any("KeyError" in x and "AAPL" in x for x in logs.output), logs.output)
        self.assertEqual([m["heading"] for m in mails], ["Quedaste en revisar tu tesis de NVDA"])

    def test_mis_alertas_no_reactiva_ni_borra_un_recordatorio(self):
        """Auditoría B-P4 (29/10): PATCH /api/alerts/{id} con `active: true`
        reactivaba un recordatorio ya mandado y, con la fecha vencida, salía de
        nuevo en la pasada siguiente. Y el DELETE lo borraba dejando la tesis
        apuntando a una alerta que no existe. Se manejan desde la tesis."""
        tid = self._guardar("Data centers")
        self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.h)
        with main.db_abierta() as conn:
            conn.execute("UPDATE tesis SET recordar_el=? WHERE id=?", (self.hoy.isoformat(), tid))
            conn.commit()
            aid = conn.execute("SELECT alert_id FROM tesis WHERE id=?", (tid,)).fetchone()[0]
        mails = []
        with mock.patch("billing.emails.send_alert_email", lambda **kw: mails.append(kw) or True), \
             mock.patch("main._send_push_to_user", lambda uid, p: 1), \
             mock.patch("alerts_engine.HORA_RECORDATORIO", 0):
            main._evaluar_alertas_job()
            r = self.client.patch(f"/api/alerts/{aid}", json={"active": True}, headers=self.h)
            self.assertEqual(r.status_code, 400, r.text)
            main._evaluar_alertas_job()
        self.assertEqual(len(mails), 1, "una sola vez")
        r = self.client.delete(f"/api/alerts/{aid}", headers=self.h)
        self.assertEqual(r.status_code, 400, r.text)
        with main.db_abierta() as conn:
            self.assertIsNotNone(conn.execute("SELECT 1 FROM alerts WHERE id=?", (aid,)).fetchone())
        self.assertNotIn(aid, [a["id"] for a in self.client.get("/api/alerts", headers=self.h).json()["items"]])
        # Una alerta del formulario se sigue editando y borrando.
        r = self.client.delete("/api/alerts/999999", headers=self.h)
        self.assertEqual(r.status_code, 200)

    def test_reescribirla_otro_dia_muda_el_recordatorio(self):
        tid = self._guardar("v1")
        self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.h)
        with mock.patch("tesis.hoy_art_date", lambda: self.hoy + timedelta(days=3)):
            self._guardar("v2")
        v1, v2 = self._lista()["items"]
        self.assertIsNone(v1["recordatorio"])
        self.assertEqual(v2["recordatorio"]["tipo"], "3m")

    def test_borrar_la_tesis_borra_su_recordatorio(self):
        tid = self._guardar("x")
        self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.h)
        self.assertEqual(self.client.delete(f"/api/tesis/{tid}", headers=self.h).status_code, 200)
        self.assertEqual(self._lista()["items"], [])
        with main.db_abierta() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 0)

    def test_el_motor_de_precios_no_toca_los_recordatorios(self):
        tid = self._guardar("x")
        self.client.put(f"/api/tesis/{tid}/recordatorio", json={"tipo": "3m"}, headers=self.h)
        with main.db_abierta() as conn, mock.patch("alerts_engine._prices_for") as precios, \
                mock.patch("alerts_engine._quotes_for") as quotes:
            r = alerts_engine.evaluate_alerts(conn)
        self.assertEqual(r["alerts"], 0)
        precios.assert_not_called()
        quotes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
