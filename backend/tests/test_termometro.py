"""El termómetro del mercado (pieza 7, termometro.py).

Entra por el camino de producción: la corrida de velas de la noche
(`main._run_velas_diarias_job`) y la del termómetro, que dispara el cron de las
alertas (`main._termometro_job`, en su propio hilo), con Yahoo reemplazado en
su punto más bajo (`pricing.yahoo._historia`); la pantalla pide GET
/api/termometro. El universo se achica a 5 empresas del S&P y 2 del panel
(`_lista_sp500` y `MERVAL_TOP_25`) para que corra rápido: el código es el mismo.

Los casos que importan:
  · la noche NO baja el universo (sólo lo que alguien tiene o sigue) y el
    termómetro baja sólo lo que la noche no bajó;
  · cada parte del número sale como dice la pantalla, y el «alcista» de cada
    acción es el de SU FICHA (GET /api/tecnico/{activo});
  · corre una vez por día ARGENTINO: de 21:00 a medianoche de acá en UTC ya es
    mañana, y eso no lo hace correr de nuevo; espera a la noche;
  · «hace una semana» sale sólo de lo guardado: para atrás no se inventa;
  · con Yahoo caído para casi todo, no guarda un número a medias;
  · la poda de la noche no borra las velas del universo.

Corre con: cd backend && python3 -m pytest tests/test_termometro.py
"""
import os
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
import termometro  # noqa: E402
import velas_diarias  # noqa: E402
from fechas import hoy_art_date  # noqa: E402
from tests.test_radiografia_tecnica import YahooFalso, _ruedas  # noqa: E402

MEP = 1000.0
LISTA = {"bajada": "2026-10-29", "empresas": [
    {"symbol": "AAPL", "nombre": "Apple", "sector": "tecnologia"},
    {"symbol": "MSFT", "nombre": "Microsoft", "sector": "tecnologia"},
    {"symbol": "XOM", "nombre": "Exxon", "sector": "energia"},
    {"symbol": "KO", "nombre": "Coca-Cola", "sector": "consumo_bas"},
    {"symbol": "BRK.B", "nombre": "Berkshire", "sector": "financiero"},
]}
PANEL = ["GGAL.BA", "YPFD.BA"]


class Contador:
    """El Yahoo de mentira, anotando qué ticker se pidió en cada corrida."""

    def __init__(self, yahoo):
        self.yahoo, self.pedidos = yahoo, []

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        self.pedidos.append(ticker)
        return self.yahoo(ticker, period, interval, auto_adjust, timeout)


class TermometroTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "watchlist", "positions", "brokers",
                      "fx_rates_daily", "termometro_diario", "alerts", "operations"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"termo-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.dias = _ruedas(self.hoy, 760)
        n = self.n = len(self.dias)
        self.yahoo = YahooFalso(self.hoy)
        self.contador = Contador(self.yahoo)
        y = self.yahoo.precios
        y["AAPL"] = lambda i, d: 100 + i * 0.1                                  # sube: alcista, en su máximo
        y["MSFT"] = lambda i, d: 300 - i * 0.1                                  # baja: bajista, en su mínimo
        y["XOM"] = lambda i, d: (100 + min(i, n - 11) * 0.1) * (0.99 if i >= n - 10 else 1)   # alcista, 1 % abajo del máximo
        y["KO"] = lambda i, d: (300 - min(i, n - 11) * 0.1) * (1.01 if i >= n - 10 else 1)    # bajista, 1 % arriba del mínimo
        y["BRK-B"] = lambda i, d: 200 + i * 0.2                                 # con clase: Yahoo la llama con guión
        y["GGAL.BA"] = lambda i, d: 5000 + i * 20                               # en dólares (÷ MEP) sube
        y["^GSPC"] = lambda i, d: 4000 + i                                      # arriba de sus dos promedios
        # YPFD.BA: Yahoo no lo trae (queda sin medir: 6 de 7, sobre el 80 %).
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("pricing.yahoo._historia", self.contador),
                   mock.patch("termometro._lista_sp500", lambda: LISTA),
                   mock.patch("home.market.MERVAL_TOP_25", PANEL)]
        for p in self._p:
            p.start()
        with main.db_abierta() as conn:
            for d in self.dias:
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), MEP * 1.1, MEP))
            conn.commit()

    def tearDown(self):
        for p in self._p:
            p.stop()

    # — armado, como la app —

    def _noche(self):
        """Alguien tiene AAPL: la noche baja AAPL y el S&P 500, nada más."""
        self.client.post("/api/brokers", json={"name": "Schwab", "currency": "USD"}, headers=self.h)
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "AAPL", "quantity": 10,
                                                     "buy_price": 150, "asset_type": "STOCK"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        main._run_velas_diarias_job()

    def _marca(self, simbolo, instante):
        with main.db_abierta() as conn:
            conn.execute(
                "INSERT INTO velas_estado (symbol, ultima_corrida, ok) VALUES (?, ?, 1) "
                "ON CONFLICT(symbol) DO UPDATE SET ultima_corrida=excluded.ultima_corrida",
                (simbolo, instante.strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()

    def _cron_del_termometro(self):
        """El cron de las alertas, 70 minutos después de la noche (las marcas se
        fijan a mano: así no depende de la hora en que corre la prueba)."""
        noche = datetime(self.hoy.year, self.hoy.month, self.hoy.day, 3, 15)    # 00:15 de acá
        self._marca(velas_diarias.MARCA_CORRIDA_NOCHE, noche)
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_estado WHERE symbol=?", (termometro.MARCA_CORRIDA,))
            conn.commit()
            r = main._termometro_job(conn, noche + timedelta(minutes=70))
        self.assertEqual(r.get("status"), "started", r)
        fin = time.monotonic() + 30
        while "termometro" in main._corridas_en_curso and time.monotonic() < fin:
            time.sleep(0.05)
        self.assertNotIn("termometro", main._corridas_en_curso, "la corrida no terminó")

    def _ficha(self, asset, local=False):
        r = self.client.get(f"/api/tecnico/{asset}?moneda=usd{'&local=1' if local else ''}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # — los casos —

    def test_camino_real_noche_cron_y_pantalla(self):
        self._noche()
        noche = set(self.contador.pedidos)
        self.assertEqual(noche, {"AAPL", "^GSPC"},
                         "la noche baja sólo lo que alguien tiene (y el S&P 500), no el universo")
        self.contador.pedidos.clear()

        self._cron_del_termometro()
        self.assertEqual(sorted(set(self.contador.pedidos)),
                         ["BRK-B", "GGAL.BA", "KO", "MSFT", "XOM", "YPFD.BA"],
                         "el termómetro baja sólo lo que la noche no bajó")

        r = self.client.get("/api/termometro", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        t = r.json()
        self.assertTrue(t["disponible"], t)
        self.assertEqual(t["fecha"], self.dias[-1].isoformat(), "la fecha es la última vela del S&P")
        self.assertFalse(t["viejo"])
        a = t["amplitud"]
        self.assertEqual((a["alcistas"], a["medidas"]), (4, 6), a)
        self.assertEqual((a["sp500"]["alcistas"], a["sp500"]["medidas"]), (3, 5))
        self.assertEqual((a["panel"]["alcistas"], a["panel"]["medidas"]), (1, 1), "YPFD sin velas no cuenta")
        self.assertEqual(a["puntos"], 33)
        self.assertEqual((t["indice"]["arriba200"], t["indice"]["arriba50"], t["indice"]["puntos"]), (True, True, 25))
        self.assertEqual((t["maximos"]["maximos"], t["maximos"]["minimos"]), (3, 1), t["maximos"])
        self.assertEqual(t["maximos"]["puntos"], 19)
        # 33,3 + 25 + 18,75 = 77,08: las tres partes en enteros SUMAN el número
        # (lo que falta va a la que más perdió al redondear: 18,75 → 19).
        self.assertEqual(t["puntaje"], 77)
        self.assertEqual(a["puntos"] + t["indice"]["puntos"] + t["maximos"]["puntos"], t["puntaje"])
        self.assertEqual(t["sectores"]["tecnologia"], {"alcistas": 1, "medidas": 2, "pct": 50.0})
        self.assertEqual(t["semana_pasada"], None, "para atrás no se inventa")
        self.assertEqual(t["leyenda"],
                         "Describe cómo se mueve el mercado. No dice cuánto tener invertido ni es una recomendación.")
        for palabra in ("tené", "comprá", "vendé", "invertí"):
            self.assertNotIn(palabra, str(t).lower())

    def test_alcista_es_el_de_la_ficha(self):
        # La cuenta del termómetro y la tarjeta «Largo plazo» de cada ficha
        # tienen que decir lo mismo de cada acción: si no, el número no se
        # puede comprobar abriendo las fichas.
        self._noche()
        self._cron_del_termometro()
        t = self.client.get("/api/termometro", headers=self.h).json()
        alcistas_ficha = 0
        for asset, local in (("AAPL", False), ("MSFT", False), ("XOM", False), ("KO", False),
                             ("BRK.B", False), ("GGAL", True)):
            f = self._ficha(asset, local)
            self.assertTrue(f["disponible"], (asset, f))
            dist = f["lectura"]["dist_media200"]
            alcistas_ficha += dist >= 0
            esperado = asset in ("AAPL", "XOM", "BRK.B", "GGAL")
            self.assertEqual(dist >= 0, esperado, f"{asset}: la ficha dice {dist:+.2f} % contra su promedio de 200")
        self.assertEqual(t["amplitud"]["alcistas"], alcistas_ficha)
        # Y el % de una acción alcista: el de la ficha es el mismo número que
        # el termómetro usó (misma serie, misma lectura).
        with main.db_abierta() as conn:
            import tecnico
            x = tecnico.para_la_cartera(conn, [("AAPL", False)], hoy=self.hoy)[0]
        self.assertAlmostEqual(x["lectura"]["dist_media200"], self._ficha("AAPL")["lectura"]["dist_media200"], places=6)

    def test_una_vez_por_dia_argentino(self):
        with main.db_abierta() as conn:
            dia = datetime(2026, 10, 28)
            # Corrió el 28 a la 01:20 de acá (04:20 UTC).
            self._marca(termometro.MARCA_CORRIDA, dia.replace(hour=4, minute=20))
            self._marca(velas_diarias.MARCA_CORRIDA_NOCHE, dia.replace(hour=3, minute=10))
            # 22:30 del 28 acá = 01:30 del 29 en UTC: sigue siendo el 28. No vuelve a correr.
            self.assertFalse(termometro.toca(conn, datetime(2026, 10, 29, 1, 30)))
            self.assertFalse(termometro.toca(conn, datetime(2026, 10, 29, 2, 59)))
            # 00:05 del 29 acá: es otro día, pero la noche todavía no corrió.
            self.assertFalse(termometro.toca(conn, datetime(2026, 10, 29, 3, 5)))
            # La noche terminó a las 00:12 de acá (03:12 UTC): espera una hora.
            self._marca(velas_diarias.MARCA_CORRIDA_NOCHE, datetime(2026, 10, 29, 3, 12))
            self.assertFalse(termometro.toca(conn, datetime(2026, 10, 29, 3, 40)))
            self.assertTrue(termometro.toca(conn, datetime(2026, 10, 29, 4, 15)))
            # Sin corrida de la noche el 30: corre igual desde las 06:00 de acá.
            self._marca(termometro.MARCA_CORRIDA, datetime(2026, 10, 29, 4, 20))
            self.assertFalse(termometro.toca(conn, datetime(2026, 10, 30, 8, 59)))
            self.assertTrue(termometro.toca(conn, datetime(2026, 10, 30, 9, 0)))

    def test_una_vez_por_dia_por_el_cron(self):
        # Con la marca de hoy puesta, el cron de las alertas no lo vuelve a
        # largar (y no le pide nada a Yahoo).
        self._noche()
        self._cron_del_termometro()
        self.contador.pedidos.clear()
        with main.db_abierta() as conn:
            r = main._termometro_job(conn, datetime.utcnow())
        self.assertIn("esperando", r)
        self.assertEqual(self.contador.pedidos, [])

    def test_la_semana_pasada_sale_de_lo_guardado(self):
        self._noche()
        self._cron_del_termometro()
        ultima = self.dias[-1]
        with main.db_abierta() as conn:
            hoy = termometro.ultimo(conn, self.hoy)
            self.assertIsNone(hoy["semana_pasada"])
            # Una fila de hace 15 días: ya no es «la semana pasada».
            termometro.guardar(conn, {**hoy, "fecha": (ultima - timedelta(days=15)).isoformat(), "puntaje": 30})
            self.assertIsNone(termometro.ultimo(conn, self.hoy)["semana_pasada"])
            # La de hace 7 días sí; si hay dos en la ventana, la más nueva.
            termometro.guardar(conn, {**hoy, "fecha": (ultima - timedelta(days=9)).isoformat(), "puntaje": 41})
            termometro.guardar(conn, {**hoy, "fecha": (ultima - timedelta(days=7)).isoformat(), "puntaje": 52})
            s = termometro.ultimo(conn, self.hoy)["semana_pasada"]
        self.assertEqual(s, {"fecha": (ultima - timedelta(days=7)).isoformat(), "puntaje": 52})
        t = self.client.get("/api/termometro", headers=self.h).json()
        self.assertEqual(t["semana_pasada"]["puntaje"], 52)
        self.assertEqual(t["puntaje"], hoy["puntaje"], "el número de hoy sigue siendo el de hoy")

    def test_yahoo_caido_no_guarda_un_numero_a_medias(self):
        self._noche()
        for t in ("MSFT", "XOM", "KO", "BRK-B"):
            self.yahoo.precios.pop(t)
        self._cron_del_termometro()
        t = self.client.get("/api/termometro", headers=self.h).json()
        self.assertEqual(t, {"disponible": False}, "2 de 7 medidas: no se guarda")
        with main.db_abierta() as conn:
            # Anotó que corrió: mañana lo intenta de nuevo, no cada 10 minutos.
            self.assertFalse(termometro.toca(conn, datetime.utcnow()))

    def test_la_poda_de_la_noche_no_borra_el_universo(self):
        self._noche()
        self._cron_del_termometro()
        with main.db_abierta() as conn:
            # MSFT no la tiene nadie y hace 60 días que no se toca.
            conn.execute("UPDATE velas_estado SET ultima_corrida=datetime('now', '-60 days') WHERE symbol='MSFT'")
            conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('ZZZZ', ?, 1)",
                         (self.dias[-1].isoformat(),))
            conn.execute("INSERT INTO velas_estado (symbol, ultima_corrida, ok) "
                         "VALUES ('ZZZZ', datetime('now', '-60 days'), 1)")
            conn.commit()
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            msft = conn.execute("SELECT COUNT(*) FROM velas_diarias WHERE symbol='MSFT'").fetchone()[0]
            zzzz = conn.execute("SELECT COUNT(*) FROM velas_diarias WHERE symbol='ZZZZ'").fetchone()[0]
        self.assertGreater(msft, 700, "las velas del universo no son basura a pedido")
        self.assertEqual(zzzz, 0, "la poda sigue borrando lo que nadie usa")


if __name__ == "__main__":
    unittest.main()
