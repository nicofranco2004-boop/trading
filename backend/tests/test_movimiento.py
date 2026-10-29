"""«Cuánto se mueve este papel» y los balances/dividendos del gráfico de la ficha
(movimiento.py + GET /api/tecnico/{asset} + GET /api/tecnico/{asset}/eventos).

Dos partes:
  · DIFERENCIALES: cada cuenta de movimiento.py contra una cuenta independiente
    escrita de otra forma (fuerza bruta para la peor caída, pandas para el
    desvío), sobre cientos de series al azar.
  · CAMINO REAL: las posiciones entran por HTTP, las velas las guarda el
    trabajo nocturno real con Yahoo reemplazado en su punto más bajo, los
    balances y dividendos los trae el pedido de la ficha (con Yahoo reemplazado
    también abajo de todo) y lo que se compara es lo que devuelve el endpoint.

Corre con: cd backend && python3 -m pytest tests/test_movimiento.py
"""
import os
import random
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta
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

import main
import movimiento
from fechas import hoy_art_date
from tests.test_tecnico import YahooFalso, _ruedas


def _serie(cierres, desde=date(2024, 1, 1)):
    out, d = [], desde
    for c in cierres:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append({"date": d.isoformat(), "close": c})
        d += timedelta(days=1)
    return out


def _caminata(n, semilla, vol=0.02):
    rnd = random.Random(semilla)
    xs, x = [], 100.0
    for _ in range(n):
        x *= 1 + rnd.gauss(0, vol)
        # Cierres repetidos a propósito (empates de máximos y de pisos).
        xs.append(round(x, 1) if rnd.random() < 0.3 else x)
    return xs


def _peor_caida_fuerza_bruta(cierres):
    """Otra forma de contar: todos los pares (i < j), la baja más grande. Entre
    empates, el primer piso y, para ese piso, el primer máximo con ese cierre."""
    mejor = None
    for j in range(len(cierres)):
        for i in range(j):
            c = cierres[j] / cierres[i] - 1
            if c < 0 and (mejor is None or c < mejor[2] - 1e-15):
                mejor = (i, j, c)
    if mejor is None:
        return None
    i, j, c = mejor
    # El máximo de esa caída es el cierre más alto antes del piso.
    alto = max(cierres[:j + 1])
    i = cierres.index(alto)
    vuelta = next((k for k in range(j + 1, len(cierres)) if cierres[k] >= alto), None)
    return i, j, c, vuelta


class DiferencialTest(unittest.TestCase):

    def test_peor_caida_contra_fuerza_bruta(self):
        for semilla in range(300):
            cierres = _caminata(random.Random(semilla).randint(2, 120), semilla)
            velas = _serie(cierres)
            nuestra = movimiento.peor_caida(velas)
            ref = _peor_caida_fuerza_bruta(cierres)
            if ref is None:
                self.assertIsNone(nuestra, semilla)
                continue
            i, j, c, vuelta = ref
            self.assertAlmostEqual(nuestra["pct"], c * 100, places=9, msg=semilla)
            self.assertAlmostEqual(nuestra["pico"]["precio"], cierres[i], places=9, msg=semilla)
            self.assertAlmostEqual(nuestra["piso"]["precio"], cierres[j], places=9, msg=semilla)
            self.assertEqual(nuestra["volvio"], velas[vuelta]["date"] if vuelta is not None else None, semilla)
            self.assertEqual(nuestra["dias_para_volver"], (vuelta - j) if vuelta is not None else None, semilla)

    def test_solo_sube_no_tiene_caida(self):
        self.assertIsNone(movimiento.peor_caida(_serie([1, 2, 3, 3, 4])))

    def test_desvio_y_dias_malos_contra_pandas(self):
        for semilla in range(50):
            cierres = _caminata(300, semilla, vol=0.01 + semilla / 2000)
            sp = _caminata(300, semilla + 1000, vol=0.01)
            v, vsp = _serie(cierres), _serie(sp)
            r = movimiento.dia_normal(v, vsp)
            # La cuenta independiente: el último año (365 días corridos hasta la
            # última vela) y el desvío de población, el de la lectura técnica (A5).
            piso = (date.fromisoformat(v[-1]["date"]) - timedelta(days=365)).isoformat()
            anio = [k for k, x in enumerate(v) if x["date"] > piso]
            self.assertLess(len(anio), len(v), "la serie tiene que pasar del año para que el corte importe")
            rets = pd.Series([cierres[k] for k in anio]).pct_change().dropna()
            ref = rets.std(ddof=0)
            self.assertAlmostEqual(r["desvio_pct"], ref * 100, places=9)
            self.assertEqual(r["desde"], v[anio[0]]["date"])
            self.assertEqual(r["dias"], len(rets))
            self.assertEqual(r["dias_malos"], int((rets <= -ref).sum()))
            ref_sp = pd.Series([sp[k] for k in anio]).pct_change().dropna().std(ddof=0)
            self.assertAlmostEqual(r["sp500_desvio_pct"], ref_sp * 100, places=9)
            self.assertAlmostEqual(r["veces_el_sp500"], ref / ref_sp, places=9)

    def test_sp500_se_corta_al_mismo_periodo(self):
        v = _serie(_caminata(100, 1), desde=date(2025, 1, 1))
        # El S&P empieza un año antes y es MUY movido ese año: no tiene que contar.
        antes = _serie([100 * (1.5 if k % 2 else 0.6) for k in range(260)], desde=date(2024, 1, 1))
        antes = [x for x in antes if x["date"] < "2025-01-01"]
        mismo = _serie(_caminata(100, 2, vol=0.01), desde=date(2025, 1, 1))
        r = movimiento.dia_normal(v, antes + mismo)
        ref = pd.Series([x["close"] for x in mismo]).pct_change().dropna().std(ddof=0)
        self.assertAlmostEqual(r["sp500_desvio_pct"], ref * 100, places=9)

    def test_reaccion(self):
        v = _serie([100, 110, 99, 120, 120], desde=date(2025, 3, 3))   # lun 3 a vie 7
        # Antes del cierre del martes 4: el cierre del martes contra el lunes.
        r = movimiento.reaccion(v, "2025-03-04", "antes_del_cierre")
        self.assertEqual((r["desde"], r["hasta"], r["cuando"]), ("2025-03-03", "2025-03-04", "ese_dia"))
        self.assertAlmostEqual(r["pct"], 10.0)
        # Después del cierre del martes: el miércoles contra el martes.
        r = movimiento.reaccion(v, "2025-03-04", "despues_del_cierre")
        self.assertEqual((r["desde"], r["hasta"], r["cuando"]), ("2025-03-04", "2025-03-05", "al_otro_dia"))
        self.assertAlmostEqual(r["pct"], -10.0)
        # Sin hora: del lunes al miércoles (los dos días juntos).
        r = movimiento.reaccion(v, "2025-03-04", None)
        self.assertEqual((r["desde"], r["hasta"], r["cuando"]), ("2025-03-03", "2025-03-05", "dos_dias"))
        self.assertAlmostEqual(r["pct"], -1.0)
        # Un sábado después del cierre: el viernes contra el lunes siguiente no
        # está en la serie (termina el viernes): no se inventa.
        self.assertIsNone(movimiento.reaccion(v, "2025-03-08", "despues_del_cierre"))
        # El primer día de la serie no tiene anterior.
        self.assertIsNone(movimiento.reaccion(v, "2025-03-03", "antes_del_cierre"))

    def test_pocos_dias_no_publica(self):
        r = movimiento.calcular(_serie([100 + k for k in range(30)]))
        self.assertFalse(r["disponible"])


class FichaMovimientoTest(unittest.TestCase):
    """Por el endpoint, con el trabajo nocturno real."""

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "financial_events", "dividendos_pagados",
                      "dividendos_emisor"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"mov-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        main._earnings_pasados_at.clear()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.dias = _ruedas(self.hoy, 760)
        self.yahoo = YahooFalso(self.hoy)
        self.balances = {}     # ticker → [pd.Timestamp con hora, en Nueva York]
        self.dividendos = {}   # ticker → [(fecha, monto)]
        prueba = self

        class TickerFalso:
            def __init__(self, t):
                self.t = t

            def get_earnings_dates(self, limit=12):
                idx = prueba.balances.get(self.t)
                if idx is None:
                    return None
                return pd.DataFrame({"EPS Estimate": [1.0] * len(idx)}, index=pd.DatetimeIndex(idx))

        def _div(pedido):
            t, _ = pedido
            return {"pagos": [(f, m) for f, m in self.dividendos.get(t, [])], "pais": "United States",
                    "tipo": "EQUITY"}

        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch.object(main.yf, "Ticker", TickerFalso),
                   mock.patch("dividendos._consultar_yahoo", _div)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _posicion(self, broker, currency, asset, asset_type):
        self.client.post("/api/brokers", json={"name": broker, "currency": currency}, headers=self.h)
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": asset_type},
                             headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _get(self, url):
        r = self.client.get(url, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    @staticmethod
    def _mep(k):
        return 1000 * (1 + 0.02 * ((k * 7919) % 13 - 6) / 6)

    def _precio(self, semilla, vol):
        xs = _caminata(len(self.dias), semilla, vol)
        return lambda i, d: xs[i]

    def test_cuanto_se_mueve_por_el_endpoint(self):
        self._posicion("Schwab", "USD", "NVDA", "STOCK")
        self.yahoo.precios["NVDA"] = self._precio(7, 0.03)
        self.yahoo.precios["^GSPC"] = self._precio(8, 0.01)
        main._run_velas_diarias_job()   # el S&P 500 se guarda aunque nadie lo tenga

        f = self._get("/api/tecnico/NVDA?moneda=usd")
        m = f["movimiento"]
        self.assertTrue(m["disponible"])

        # La cuenta independiente: pandas sobre los cierres de los últimos 730 días
        # (la peor caída) y del último año (el día normal, A5).
        piso = (self.dias[-1] - timedelta(days=730)).isoformat()
        dias = [d for d in self.dias if d.isoformat() > piso]
        ix = [self.dias.index(d) for d in dias]
        nv = pd.Series([self.yahoo.precios["NVDA"](i, None) for i in ix])
        piso_anio = (self.dias[-1] - timedelta(days=365)).isoformat()
        ix_anio = [self.dias.index(d) for d in self.dias if d.isoformat() > piso_anio]
        nv_anio = pd.Series([self.yahoo.precios["NVDA"](i, None) for i in ix_anio])
        sp_anio = pd.Series([self.yahoo.precios["^GSPC"](i, None) for i in ix_anio])
        self.assertAlmostEqual(m["dia_normal"]["desvio_pct"], nv_anio.pct_change().dropna().std(ddof=0) * 100, places=6)
        self.assertAlmostEqual(m["dia_normal"]["sp500_desvio_pct"],
                               sp_anio.pct_change().dropna().std(ddof=0) * 100, places=6)
        i, j, c, vuelta = _peor_caida_fuerza_bruta(list(nv))
        self.assertAlmostEqual(m["peor_caida"]["pct"], c * 100, places=6)
        self.assertEqual(m["peor_caida"]["piso"]["fecha"], dias[j].isoformat())
        # La caída desde el máximo del año es LA de la lectura, no otra cuenta.
        self.assertEqual(m["desde_el_maximo"]["pct"], f["lectura"]["dist_maximo_12m"])

    def test_un_solo_dia_normal_en_la_ficha(self):
        # A5 (auditoría 29/10): la tarjeta «Cuánto se mueve» decía «su día normal
        # del último año (1,1 %)» y la sección «Cuánto se mueve este papel», «Un
        # día normal ±2,3 %»: dos cuentas (desvío de población y de muestra) sobre
        # dos ventanas (1 y 2 años). Un papel que el año anterior se movía ±3 % por
        # día y el último año ±1 %. Tiene que ser UN número: el de la lectura.
        self._posicion("Schwab", "USD", "MSFT", "STOCK")
        n, c, x = len(self.dias), [], 100.0
        for i in range(n):
            x *= (1 + (0.03 if i < n - 252 else 0.01) * (1 if i % 2 else -1))
            c.append(x)
        self.yahoo.precios["MSFT"] = lambda i, d: c[i]
        self.yahoo.precios["^GSPC"] = self._precio(8, 0.01)
        main._run_velas_diarias_job()
        f = self._get("/api/tecnico/MSFT?moneda=usd")
        self.assertIsNotNone(f["lectura"]["mov_dia_anio"])
        self.assertEqual(f["movimiento"]["dia_normal"]["desvio_pct"], f["lectura"]["mov_dia_anio"])

    def test_en_pesos_el_sp500_tambien_va_en_pesos(self):
        self._posicion("IOL", "ARS", "AAPL", "CEDEAR")
        with main.db_abierta() as conn:
            for k, d in enumerate(self.dias):   # el dólar va y viene todos los días
                mep = self._mep(k)
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), mep * 1.1, mep))
            conn.commit()
        self.yahoo.precios["AAPL"] = self._precio(1, 0.01)
        self.yahoo.precios["AAPL.BA"] = lambda i, d: self.yahoo.precios["AAPL"](i, d) * self._mep(i) / 20
        self.yahoo.precios["^GSPC"] = lambda i, d: 5000.0      # quieto en dólares
        main._run_velas_diarias_job()
        usd = self._get("/api/tecnico/AAPL?moneda=usd")["movimiento"]["dia_normal"]
        ars = self._get("/api/tecnico/AAPL?moneda=ars")["movimiento"]["dia_normal"]
        self.assertAlmostEqual(usd["sp500_desvio_pct"], 0.0, places=9)
        # En pesos, el S&P quieto en dólares se mueve lo que se mueve el dólar:
        # su desvío es el del MEP de esos días (cuenta independiente con pandas).
        piso = (self.dias[-1] - timedelta(days=365)).isoformat()
        meps = pd.Series([self._mep(k) for k, d in enumerate(self.dias) if d.isoformat() > piso])
        self.assertAlmostEqual(ars["sp500_desvio_pct"], meps.pct_change().dropna().std(ddof=0) * 100, places=6)

    def test_balances_y_dividendos_con_lo_que_se_movio(self):
        self._posicion("IOL", "ARS", "AAPL", "CEDEAR")
        cierres = {d: 100.0 + k for k, d in enumerate(self.dias)}
        self.yahoo.precios["AAPL"] = lambda i, d: 100.0 + i
        self.yahoo.precios["AAPL.BA"] = lambda i, d: (100.0 + i) * 50
        main._run_velas_diarias_job()

        d_desp, d_antes, d_div = self.dias[-100], self.dias[-50], self.dias[-30]
        ny = "America/New_York"
        self.balances["AAPL"] = [
            pd.Timestamp(f"{d_desp.isoformat()} 16:30", tz=ny),   # después del cierre
            pd.Timestamp(f"{d_antes.isoformat()} 07:00", tz=ny),  # antes de abrir
            pd.Timestamp(f"{(self.hoy + timedelta(days=20)).isoformat()} 16:30", tz=ny),   # el próximo
        ]
        self.dividendos["AAPL"] = [(d_div.isoformat(), 0.26), ("2010-01-04", 0.1)]

        r = self._get("/api/tecnico/AAPL/eventos?moneda=usd")
        self.assertEqual(r["empresa"], "AAPL")
        evs = {(e["tipo"], e["fecha"]): e for e in r["eventos"]}
        self.assertEqual(len(evs), 3, r["eventos"])   # el futuro y el de 2010 no entran

        b = evs[("balance", d_desp.isoformat())]
        self.assertEqual(b["momento"], "despues_del_cierre")
        sig = self.dias[self.dias.index(d_desp) + 1]
        self.assertEqual(b["reaccion"]["hasta"], sig.isoformat())
        self.assertAlmostEqual(b["reaccion"]["pct"], (cierres[sig] / cierres[d_desp] - 1) * 100, places=6)

        b = evs[("balance", d_antes.isoformat())]
        ant = self.dias[self.dias.index(d_antes) - 1]
        self.assertEqual((b["reaccion"]["desde"], b["reaccion"]["hasta"]), (ant.isoformat(), d_antes.isoformat()))

        dv = evs[("dividendo", d_div.isoformat())]
        self.assertEqual((dv["monto"], dv["moneda"]), (0.26, "usd"))

        # En pesos: los MISMOS eventos de la empresa, medidos sobre el CEDEAR.
        ars = self._get("/api/tecnico/AAPL/eventos?moneda=ars")
        self.assertEqual({(e["tipo"], e["fecha"]) for e in ars["eventos"]}, set(evs))

        # Novedades («lo que se viene») no ve los balances pasados.
        prox = self._get("/api/events/portfolio?days=90")["events"]
        self.assertFalse([e for e in prox if e["event_type"] == "earnings" and e["event_date"] < self.hoy.isoformat()])

    def test_cripto_no_tiene_eventos(self):
        self._posicion("Binance", "USD", "BTC", "CRYPTO")
        self.yahoo.precios["BTC-USD"] = lambda i, d: 60000.0 + i
        main._run_velas_diarias_job()
        r = self._get("/api/tecnico/BTC/eventos?moneda=usd")
        self.assertEqual(r["eventos"], [])


if __name__ == "__main__":
    unittest.main()
