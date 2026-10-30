"""«Tu lista, con su lectura técnica» (tecnico.para_la_lista + POST /api/tecnico/lista).

Entra por el camino de producción, igual que test_radiografia_tecnica.py: las
posiciones y la watchlist se cargan por HTTP, las velas las guarda el trabajo
nocturno real (`main._run_velas_diarias_job`, que sigue lo que alguien tiene Y
lo que alguien sigue) con Yahoo reemplazado en su punto más bajo, y la lectura
se pide por HTTP.

Los casos que importan:
  · cada activo trae la MISMA lectura que su ficha (GET /api/tecnico/{asset}),
    lo tengas o sólo lo sigas;
  · un activo que está SÓLO en la watchlist tiene velas (las guarda la noche) y
    lectura;
  · un CEDEAR se lee en dólares (bajista aunque en pesos suba);
  · una acción argentina se lee con su BYMA ÷ el MEP, no con el ADR;
  · la línea chica son los cierres de los últimos 3 meses, el último = el precio
    de la lectura;
  · el «último cambio» sale de `tecnico.cambios_desde` (la cuenta única de la
    pieza «qué cambió esta semana»), el más reciente del último año;
  · un bono, un fondo o un activo sin velas vuelven «sin lectura» sin romper el
    pedido; con velas cortadas la lectura trae SU fecha (la pantalla la marca
    «sin lectura» con más de 10 días: utils/listaTecnica.test.js).

Corre con: cd backend && python3 -m pytest tests/test_lista_tecnica.py
"""
import os
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

from fastapi.testclient import TestClient

import main
import tecnico
from fechas import hoy_art_date
from tests.test_radiografia_tecnica import YahooFalso, _ruedas  # noqa: E402


class ListaTecnicaTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers",
                      "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"lista-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.dias = _ruedas(self.hoy, 760)
        self.n = len(self.dias)
        self.yahoo = YahooFalso(self.hoy)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _broker(self, name, currency):
        r = self.client.post("/api/brokers", json={"name": name, "currency": currency}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _posicion(self, broker, asset, asset_type):
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": asset_type},
                             headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _seguir(self, symbol, asset_type=None):
        r = self.client.post("/api/watchlist", json={"symbol": symbol, "asset_type": asset_type}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _mep(self, f):
        with main.db_abierta() as conn:
            for i, d in enumerate(self.dias):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), f(i) * 1.1, f(i)))
            conn.commit()

    def _lista(self, activos):
        r = self.client.post("/api/tecnico/lista", json={"activos": activos}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return {(x["asset"], x["local"]): x for x in r.json()["lecturas"]}

    def _ficha(self, asset, local=False):
        return self.client.get(f"/api/tecnico/{asset}?moneda=usd{'&local=1' if local else ''}",
                               headers=self.h).json()

    def _armar(self):
        self._broker("IOL", "ARS")
        self._broker("Schwab", "USD")
        self._posicion("IOL", "AAPL", "CEDEAR")
        self._posicion("IOL", "GGAL", "ACCION")
        self._posicion("IOL", "AL30", "BONO")
        self._posicion("Schwab", "GGAL", "STOCK")      # el ADR
        # Sólo en la watchlist: una acción de afuera y una argentina (como la
        # guarda la estrella de la ficha: con su .BA).
        self._seguir("TSLA")
        self._seguir("PAMP.BA")
        self._mep(lambda i: 1000 + i)
        self.yahoo.precios["AAPL"] = lambda i, d: 300 - i * 0.1
        self.yahoo.precios["AAPL.BA"] = lambda i, d: (300 - i * 0.1) * (1000 + i * 2) / 20
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 + i * 20
        self.yahoo.precios["GGAL"] = lambda i, d: 80 - i * 0.05
        self.yahoo.precios["TSLA"] = lambda i, d: 200 + i * 0.3
        self.yahoo.precios["PAMP.BA"] = lambda i, d: 3000 + i * 5
        main._run_velas_diarias_job()

    def test_la_misma_lectura_que_la_ficha_lo_tengas_o_lo_sigas(self):
        self._armar()
        pedido = [{"asset": "AAPL"}, {"asset": "GGAL", "local": True}, {"asset": "GGAL"},
                  {"asset": "TSLA"}, {"asset": "PAMP", "local": True}]
        c = self._lista(pedido)
        # Vuelve también lo que TENÉS (lo pone el servidor, 29/10), con el bono
        # AL30 sin lectura: acá se comparan los pedidos, que tienen velas.
        for clave in [(a["asset"], a.get("local", False)) for a in pedido]:
            x = c[clave]
            asset, local = clave
            self.assertTrue(x["disponible"], asset)
            self.assertEqual(x["lectura"], self._ficha(asset, local)["lectura"],
                             f"{asset}: la lista y la ficha leen distinto")
        # Y la misma que la radiografía de la Cartera (el otro que la usa).
        cartera = self.client.post("/api/tecnico/cartera", json={"activos": pedido}, headers=self.h).json()
        for x in cartera["lecturas"]:
            self.assertEqual(x["lectura"], c[(x["asset"], x["local"])]["lectura"], x["asset"])

    def test_solo_en_la_watchlist(self):
        self._armar()
        c = self._lista([{"asset": "TSLA"}, {"asset": "PAMP", "local": True}])
        tsla = c[("TSLA", False)]
        self.assertTrue(tsla["disponible"], "la noche guarda velas de lo que seguís aunque no lo tengas")
        self.assertGreater(tsla["lectura"]["dist_media200"], 0)
        pamp = c[("PAMP", True)]["lectura"]
        ultimo = self.n - 1
        self.assertAlmostEqual(pamp["precio"], (3000 + ultimo * 5) / (1000 + ultimo), places=6,
                               msg="una acción argentina que seguís: su BYMA ÷ el MEP")

    def test_cedear_en_dolares_y_accion_local_contra_adr(self):
        self._armar()
        c = self._lista([{"asset": "AAPL"}, {"asset": "GGAL", "local": True}, {"asset": "GGAL"}])
        self.assertLess(c[("AAPL", False)]["lectura"]["dist_media200"], 0,
                        "un CEDEAR se mide en dólares: bajista aunque en pesos suba")
        self.assertGreater(c[("GGAL", True)]["lectura"]["dist_media200"], 0, "GGAL de IOL: su BYMA ÷ MEP, sube")
        self.assertLess(c[("GGAL", False)]["lectura"]["dist_media200"], 0, "el ADR baja: es otra lectura")

    def test_linea_de_tres_meses(self):
        self._armar()
        x = self._lista([{"asset": "TSLA"}])[("TSLA", False)]
        linea = x["linea"]
        primero = date.fromisoformat(linea[0]["d"])
        ultimo = date.fromisoformat(linea[-1]["d"])
        self.assertEqual(linea[-1]["d"], x["lectura"]["fecha"])
        self.assertAlmostEqual(linea[-1]["c"], x["lectura"]["precio"], places=4)
        self.assertLessEqual((ultimo - primero).days, tecnico.DIAS_LINEA)
        self.assertGreater((ultimo - primero).days, tecnico.DIAS_LINEA - 7, "son 3 meses, no menos")
        self.assertEqual([p["d"] for p in linea], sorted(p["d"] for p in linea))

    def test_ultimo_cambio_sale_de_la_cuenta_unica(self):
        # La cuenta de cambios es `tecnico.cambios_desde` (la de «Tus señales»):
        # la lista se queda con el primero (el más nuevo) del último año contado
        # desde HOY. MSFT venía bajando y hace 3 ruedas saltó arriba de las dos
        # medias: ese día cambió todo junto; manda el de 200 (el orden de
        # TIPOS_CAMBIO).
        self._armar()
        self._seguir("MSFT")
        n = self.n
        self.yahoo.precios["MSFT"] = lambda i, d: 150.0 if i >= n - 3 else 100 - i * 0.01
        main._run_velas_diarias_job()
        espia = mock.patch.object(tecnico, "cambios_desde", wraps=tecnico.cambios_desde)
        with espia as contar:
            x = self._lista([{"asset": "MSFT"}])[("MSFT", False)]
        desde = (self.hoy - timedelta(days=tecnico.DIAS_ULTIMO_CAMBIO)).isoformat()
        self.assertEqual(contar.call_args.args[1], desde, "el año se cuenta desde hoy, no desde la última vela")
        with main.db_abierta() as conn:
            velas = tecnico.serie(conn, "MSFT", "usd")["velas"]
        import senales_semana
        esperado = tecnico.cambios_desde(velas, desde)[0]
        self.assertEqual(x["ultimo_cambio"], {**esperado, **senales_semana.texto_del_cambio(esperado)},
                         "el cambio y sus palabras: los mismos de «Tus señales»")
        self.assertEqual(x["ultimo_cambio"]["etiqueta"], "Tendencia de largo plazo")
        self.assertTrue(x["ultimo_cambio"]["texto"].startswith("superó su promedio de 200 días"))
        self.assertEqual(x["ultimo_cambio"]["tipo"], "media200")
        self.assertEqual(x["ultimo_cambio"]["sentido"], "arriba")
        self.assertEqual(x["ultimo_cambio"]["fecha"], self.dias[n - 3].isoformat())

        # La cuenta cambia sin que cambien las velas: lo ya leído (tecnico._leer_varios)
        # contestaría lo de antes, que es lo correcto en producción.
        tecnico.olvidar_lo_leido()
        with mock.patch.object(tecnico, "cambios_desde", lambda v, d: []):
            self.assertIsNone(self._lista([{"asset": "MSFT"}])[("MSFT", False)]["ultimo_cambio"])

    def test_bono_fondo_y_sin_velas(self):
        self._armar()
        c = self._lista([{"asset": "AL30", "local": True}, {"asset": "FCI PIONERO PESOS"},
                         {"asset": "ZZZZ"}, {"asset": "TSLA"}, {"asset": "TSLA"}])
        self.assertFalse(c[("AL30", True)]["disponible"], "un bono no tiene velas")
        self.assertFalse(c[("FCI PIONERO PESOS", False)]["disponible"], "un fondo no es un ticker")
        self.assertFalse(c[("ZZZZ", False)]["disponible"])
        self.assertTrue(c[("TSLA", False)]["disponible"])
        # El mismo activo dos veces se lee una; además vienen las 4 tenencias
        # (AAPL, GGAL local, AL30 local —el mismo que se pidió— y el ADR GGAL).
        r = self.client.post("/api/tecnico/lista", json={"activos": [{"asset": "TSLA"}, {"asset": "TSLA"}]}, headers=self.h).json()
        claves = [(x["asset"], x["local"]) for x in r["lecturas"]]
        self.assertEqual(len(claves), len(set(claves)), "nada se lee dos veces")
        self.assertEqual(claves.count(("TSLA", False)), 1)
        self.assertEqual(len(c), 4 + 3, "4 pedidos distintos + 3 tenencias que no se pidieron")

    def test_velas_viejas_traen_su_fecha(self):
        self._armar()
        corte = self.dias[self.n - 15].isoformat()
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_diarias WHERE symbol='TSLA' AND date > ?", (corte,))
            conn.commit()
        x = self._lista([{"asset": "TSLA"}])[("TSLA", False)]
        self.assertEqual(x["lectura"]["fecha"], corte)
        self.assertEqual(x["linea"][-1]["d"], corte)

    def test_tope_y_sesion(self):
        r = self.client.post("/api/tecnico/lista",
                             json={"activos": [{"asset": f"A{i}"} for i in range(tecnico.MAX_ACTIVOS_CARTERA + 1)]},
                             headers=self.h)
        self.assertEqual(r.status_code, 422, "el tope se corta al leer el pedido")
        r = self.client.post("/api/tecnico/lista", json={"activos": [{"asset": "AAPL"}]})
        self.assertIn(r.status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()


class MervalleConoceAnalisisTecnicoTest(unittest.TestCase):
    """Mervall-E sólo puede linkear a una lista cerrada de pantallas (el bloque
    «actions»). Análisis técnico y sus pestañas están en esa lista, en los dos
    modos (Pro y Free), y /fundamentals se llama «Análisis fundamental»."""

    def test_las_rutas_que_puede_linkear(self):
        for prompt in (main._AI_CHAT_SYSTEM, main._AI_CHAT_SYSTEM_FREE):
            self.assertIn("/analisis-tecnico", prompt)
            self.assertIn("?tab=lista", prompt)
            self.assertIn("?tab=senales", prompt)
            self.assertNotIn("Calidad de cartera", prompt)
        self.assertIn("/fundamentals (Análisis fundamental)", main._AI_CHAT_SYSTEM)
