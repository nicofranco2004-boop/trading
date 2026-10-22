"""La revisión nocturna de las velas: lo que Yahoo no corrige.

Cuando BYMA cambia el ratio de un CEDEAR, Yahoo deja en la serie '.BA' un
escalón de −50 % que no existió (XLE y XLU el 05/12/2025) y no lo anota en su
lista de splits. La revisión de cada noche (`velas_diarias.revisar`) lo detecta
comparando el CEDEAR en pesos con la acción de afuera, lo anota en
`velas_correcciones`, y `velas_diarias.serie` —la puerta por la que lee todo el
que usa las velas— lo aplica. Las velas guardadas quedan como las dio Yahoo.

Entra por el camino de producción: posiciones por HTTP, la corrida nocturna real
(`main._run_velas_diarias_job`) con Yahoo reemplazado en su punto más bajo, y la
ficha y /admin por HTTP.

Los casos que importan:
  · cualquier lector de las velas (no sólo la ficha) recibe la serie corregida,
    y lo guardado sigue siendo lo de Yahoo;
  · dos tickers que se llaman igual sin ser el mismo papel (AGRO.BA es
    Agrometal, AGRO en Nueva York es Adecoagro) NO se comparan: el salto de una
    acción argentina sin par se anota para mirarlo a mano, no se corrige;
  · un cambio de ratio el día que afuera se movió 15 % (un ETF apalancado)
    también se ve;
  · correrlo dos veces da lo mismo, y si Yahoo un día ajusta la historia él
    mismo, la corrección se va sola (no se corrige dos veces);
  · un salto en el ÚLTIMO día (todavía no se sabe si vuelve) esconde ese día y
    no reescala la historia.

Corre con: cd backend && python3 -m pytest tests/test_velas_correcciones.py
"""
import os
import sys
import unittest
import uuid
from datetime import timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import pandas as pd
from fastapi.testclient import TestClient

import main
import velas_diarias
from fechas import hoy_art_date


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class YahooFalso:
    """`precios[ticker](i, fecha)` da el cierre de la rueda i (0 = la más vieja)."""

    def __init__(self, hoy):
        self.hoy, self.precios = hoy, {}

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        f = self.precios.get(ticker)
        if f is None:
            return pd.DataFrame()
        dias = _ruedas(self.hoy, 760 if period == "3y" else 22)
        base = _ruedas(self.hoy, 760)
        filas = {}
        for d in dias:
            c = f(base.index(d), d)
            filas[pd.Timestamp(d)] = (c, c * 1.01, c * 0.99, c, 1000.0)
        idx = sorted(filas)
        o, h, l, c, v = zip(*[filas[k] for k in idx])
        return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v},
                            index=pd.DatetimeIndex(idx))


class RevisionTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "velas_correcciones", "watchlist",
                      "positions", "brokers"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"rev-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier, is_admin) "
                "VALUES (?, 'x', 1, 1, 'pro', 1)", (f"rev-adm-{tag}@rendi.test",))
            self.admin = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.h_admin = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self.hoy = hoy_art_date()
        self.dias = _ruedas(self.hoy, 760)
        self.yahoo = YahooFalso(self.hoy)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _broker(self, name, currency, h=None):
        r = self.client.post("/api/brokers", json={"name": name, "currency": currency}, headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _posicion(self, broker, asset, asset_type, h=None):
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": asset_type},
                             headers=h or self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _ficha(self, asset, moneda="ars"):
        r = self.client.get(f"/api/tecnico/{asset}?moneda={moneda}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _admin(self):
        r = self.client.get("/api/admin/velas", headers=self.h_admin)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _xle(self, cambio):
        """XLE: afuera quieto en 90; el CEDEAR en pesos en 9.000 hasta el
        cambio de ratio y 4.500 desde ese día."""
        self._broker("IOL", "ARS")
        self._posicion("IOL", "XLE", "CEDEAR")
        self.yahoo.precios["XLE"] = lambda i, d: 90.0
        self.yahoo.precios["XLE.BA"] = lambda i, d: 9000.0 if i < cambio else 4500.0

    def test_cualquier_lector_recibe_la_serie_corregida_y_lo_guardado_es_de_yahoo(self):
        cambio = len(self.dias) - 200
        self._xle(cambio)
        main._run_velas_diarias_job()

        # La puerta común (la que va a usar Fibonacci, no sólo la ficha).
        velas = velas_diarias.serie(main.get_db(), "XLE.BA")
        self.assertEqual({v["close"] for v in velas}, {4500.0}, "toda la historia en la escala nueva")
        antes = velas[0]
        self.assertAlmostEqual(antes["high"], 9000.0 * 1.01 / 2)
        self.assertAlmostEqual(antes["volume"], 2000.0, msg="el doble de CEDEARs: el volumen viejo se duplica")
        # Lo guardado es lo de Yahoo, intacto.
        crudo = main.get_db().execute(
            "SELECT close FROM velas_diarias WHERE symbol='XLE.BA' AND date=?",
            (self.dias[0].isoformat(),)).fetchone()["close"]
        self.assertEqual(crudo, 9000.0)
        # La ficha en pesos: sin caída falsa.
        ars = self._ficha("XLE")
        self.assertAlmostEqual(ars["lectura"]["dist_maximo_12m"], 0.0, places=6)
        # /admin lo muestra, con su fecha y su factor (se partió en 2).
        adm = self._admin()
        self.assertEqual([(c["symbol"], c["date"], c["factor"], c["referencia"]) for c in adm["cambios_de_ratio"]],
                         [("XLE.BA", self.dias[cambio].isoformat(), 0.5, "XLE")])

    def test_mismo_nombre_que_no_es_el_mismo_papel_no_se_compara(self):
        # Vos tenés Agrometal (AGRO.BA, acción argentina); otro usuario tiene
        # Adecoagro (AGRO, Nueva York). Agrometal cae 88 % un día (puede ser real
        # o un cambio de escala): NO hay par contra qué compararlo.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AGRO", "ACCION")
        self._broker("Schwab", "USD", h=self.h_admin)
        self._posicion("Schwab", "AGRO", "STOCK", h=self.h_admin)
        salto = len(self.dias) - 100
        self.yahoo.precios["AGRO.BA"] = lambda i, d: 1000.0 if i < salto else 120.0
        self.yahoo.precios["AGRO"] = lambda i, d: 10.0
        main._run_velas_diarias_job()

        velas = velas_diarias.serie(main.get_db(), "AGRO.BA")
        self.assertIn(1000.0, {v["close"] for v in velas}, "no se corrige con un papel que no es el mismo")
        adm = self._admin()
        self.assertEqual(adm["cambios_de_ratio"], [])
        self.assertEqual([(c["symbol"], c["date"], c["referencia"]) for c in adm["sin_explicar"]],
                         [("AGRO.BA", self.dias[salto].isoformat(), None)])
        self.assertAlmostEqual(adm["sin_explicar"][0]["factor"], 0.12)

    def test_cambio_de_ratio_el_dia_que_afuera_se_movio_mucho(self):
        # TQQQ es x3: el día del cambio de ratio afuera sube 15 %. El cociente
        # ya descuenta lo de afuera, así que el cambio igual se ve.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "TQQQ", "CEDEAR")
        cambio = len(self.dias) - 150
        self.yahoo.precios["TQQQ"] = lambda i, d: 60.0 if i < cambio else 69.0
        self.yahoo.precios["TQQQ.BA"] = lambda i, d: 6000.0 if i < cambio else 3450.0
        main._run_velas_diarias_job()
        adm = self._admin()
        self.assertEqual([(c["symbol"], c["factor"]) for c in adm["cambios_de_ratio"]], [("TQQQ.BA", 0.5)])
        velas = velas_diarias.serie(main.get_db(), "TQQQ.BA")
        self.assertEqual(velas[0]["close"], 3000.0, "antes: 6.000 en la escala vieja = 3.000 en la nueva")

    def test_dos_corridas_dan_lo_mismo_y_si_yahoo_ajusta_no_se_corrige_dos_veces(self):
        cambio = len(self.dias) - 200
        self._xle(cambio)
        main._run_velas_diarias_job()
        main._run_velas_diarias_job()
        self.assertEqual(len(self._admin()["cambios_de_ratio"]), 1)

        # Yahoo un día reescribe la historia él mismo (como hizo con Netflix).
        self.yahoo.precios["XLE.BA"] = lambda i, d: 4500.0
        with main.db_abierta() as conn:   # que toque la bajada entera
            conn.execute("UPDATE velas_estado SET ultima_completa=NULL")
            conn.commit()
        main._run_velas_diarias_job()
        self.assertEqual(self._admin()["cambios_de_ratio"], [])
        velas = velas_diarias.serie(main.get_db(), "XLE.BA")
        self.assertEqual({v["close"] for v in velas}, {4500.0}, "no 2.250: no se corrige dos veces")

    def test_salto_en_el_ultimo_dia_esconde_ese_dia_y_no_reescala_la_historia(self):
        ultimo = len(self.dias) - 1
        self._xle(ultimo)
        main._run_velas_diarias_job()
        velas = velas_diarias.serie(main.get_db(), "XLE.BA")
        self.assertEqual({v["close"] for v in velas}, {9000.0}, "la historia no se toca por un día dudoso")
        self.assertNotEqual(velas[-1]["date"], self.dias[ultimo].isoformat())
        # El último cierre que usa la ficha para "cuánto se movió hoy" pasa por
        # la misma puerta: tampoco ve el día dudoso.
        import tecnico
        self.assertEqual(tecnico.cierre_de(main.get_db(), "XLE.BA")["cierre"], 9000.0)

    def test_admin_lo_ve_y_el_usuario_no(self):
        r = self.client.get("/api/admin/velas", headers=self.h)
        self.assertEqual(r.status_code, 403)


class DetectarTest(unittest.TestCase):
    """La cuenta sola, con los cierres reales de Yahoo de XLE.BA y XLE alrededor
    del cambio de ratio del 05/12/2025."""

    def test_xle_real(self):
        byma = [{"date": "2025-12-03", "close": 69375.0}, {"date": "2025-12-04", "close": 69575.0},
                {"date": "2025-12-05", "close": 34980.0}, {"date": "2025-12-09", "close": 34320.0}]
        afuera = [{"date": "2025-12-03", "close": 45.915}, {"date": "2025-12-04", "close": 46.11},
                  {"date": "2025-12-05", "close": 45.92}, {"date": "2025-12-09", "close": 45.70}]
        self.assertEqual(velas_diarias.detectar(byma, afuera),
                         [{"date": "2025-12-05", "tipo": "ratio", "factor": 0.5}])

    def test_un_salto_que_no_es_fraccion_queda_como_se_midio(self):
        # DuPont (spin-off): el CEDEAR cae 57 % con afuera +1,5 %. No es un ratio
        # redondo: se usa el factor medido, no se inventa uno.
        byma = [{"date": "a1", "close": 73500.0}, {"date": "a2", "close": 31530.0},
                {"date": "a3", "close": 31600.0}]
        afuera = [{"date": "a1", "close": 100.0}, {"date": "a2", "close": 101.5},
                  {"date": "a3", "close": 101.5}]
        (c,) = velas_diarias.detectar(byma, afuera)
        self.assertEqual(c["tipo"], "ratio")
        despues = ((31530 / 101.5) + (31600 / 101.5)) / 2   # mediana de los días de después
        self.assertAlmostEqual(c["factor"], despues / (73500 / 100.0))
        self.assertNotAlmostEqual(c["factor"], 0.4, places=2)

    def test_precio_roto_de_dos_dias_vuelve_a_su_escala(self):
        # Dos días rotos y vuelve: no puede quedar ni la historia reescalada ni
        # los dos días rotos.
        q = [100.0] * 8 + [35.0, 35.0] + [100.0] * 8
        byma = [{"date": f"d{i:02d}", "close": x} for i, x in enumerate(q)]
        afuera = [{"date": f"d{i:02d}", "close": 1.0} for i in range(len(q))]
        cs = velas_diarias.detectar(byma, afuera)
        velas = velas_diarias._aplicar(byma, cs)
        self.assertEqual({v["close"] for v in velas}, {100.0})


if __name__ == "__main__":
    unittest.main()
