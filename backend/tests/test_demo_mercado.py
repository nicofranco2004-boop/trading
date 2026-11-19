"""La puerta del demo, para lo del mercado (19/11/2026).

El demo (frontend/src/utils/demo.js) no contestaba seis lecturas que no son de
nadie: el catálogo de fondos y la lista de CEDEARs del alta, las tasas de los
bancos del plazo fijo, la serie del CER, lo que pagó cada empresa (la bandeja de
dividendos de la Cartera) y el buscador por nombre de Fundamentals. Esas partes
quedaban vacías o con «Esta sección no está disponible en modo demo». Ahora la
pantalla las pide a /api/demo/… sin sesión (main.py, «Lo del mercado, en el
demo»).

Lo que se fija:
  · cada una contesta sin cuenta lo MISMO que a una cuenta (con la caché llena);
  · el demo no sale a buscar nada afuera: ni a Yahoo con lo que escribe o
    agrega el visitante, ni a la fuente del CER o de los bancos, que se
    reintentan en cada pedido mientras están caídas;
  · lo que busca el visitante no queda en la memoria de búsquedas de las
    cuentas (no tiene tope);
  · pasa por el freno del demo.

Corre con: cd backend && python3 -m pytest tests/test_demo_mercado.py
"""
import os
import sys
import tempfile
import time
import unittest
import uuid
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
from pricing import fci as fci_mod  # noqa: E402

MEP = 1540.0
# Un recorte del feed de BYMA (tests/test_cedears_dolar.py), como lo deja
# `_fetch_data912_equities`.
FEED = {s: {"c": c, "v": 100.0, "pct": 0.0, "mercado": "arg_cedears"}
        for s, c in (("AAPL", 27780), ("AAPLD", 18.04), ("KO", 30300), ("KOD", 19.65))}
BANCOS = [{"banco": "BANCO DE PRUEBA", "logo": None, "tna_clientes": 0.31, "tna_no_clientes": 0.29}]
INTEL = [{"symbol": "INTC", "name": "Intel Corporation", "exchange": "NMS"}]
# Lo que manda la pantalla del demo en cada pedido (no se usa para lo del mercado).
DEMO = {"precios": {"NVDA": 178.5}, "cartera": {"tenencias": [], "efectivo": 0, "plazos_fijos": 0},
        "watchlist": []}


class DemoMercadoTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        with main.db_abierta() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, name, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'Ana', 'x', 1, 1, 'pro')", (f"demo-mercado-{uuid.uuid4().hex[:8]}@rendi.test",))
            self.uid = cur.lastrowid
            fci_mod.ensure_tables(conn)
            for t in ("fci_catalog", "fci_prices", "bond_indices_daily", "dividendos_emisor", "dividendos_pagados"):
                conn.execute(f"DELETE FROM {t}")
            conn.execute("INSERT INTO fci_catalog (symbol, ad_name, display_name, emisor, clase, moneda, categoria) "
                         "VALUES ('FCI-PRUEBA', 'Prueba Ahorro', 'Prueba Ahorro A', 'Prueba SA', 'A', 'ARS', "
                         "'Money Market')")
            conn.execute("INSERT INTO fci_prices (symbol, price, moneda, as_of_date) "
                         "VALUES ('FCI-PRUEBA', 1234.56, 'ARS', '2026-11-18')")
            for d, v in (("2026-11-17", 600.1), ("2026-11-18", 600.4)):
                conn.execute("INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at) "
                             "VALUES ('CER', ?, ?, 'prueba', '2026-11-18T00:00:00Z')", (d, v))
            conn.execute("INSERT INTO dividendos_emisor (ticker, pais, tipo, consultado_at) "
                         "VALUES ('AAPL', 'United States', 'EQUITY', datetime('now'))")
            conn.execute("INSERT INTO dividendos_pagados (ticker, ex_date, por_accion) "
                         "VALUES ('AAPL', date('now', '-20 days'), 0.26)")
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self._p = [
            mock.patch("main._check_rate_limit"),
            mock.patch("main._fetch_data912_equities", lambda: dict(FEED)),
            mock.patch("main._current_cedear_rate", lambda: MEP),
        ]
        for p in self._p:
            p.start()
        main._freno_reiniciar()
        self._bancos_antes = dict(main._PF_BANKS_CACHE)
        self._busquedas_antes = dict(main._symsearch_cache)
        self._indices_antes = dict(main._indices_fetched)

    def tearDown(self):
        for p in self._p:
            p.stop()
        main._freno_reiniciar()
        for memoria, antes in ((main._PF_BANKS_CACHE, self._bancos_antes),
                               (main._symsearch_cache, self._busquedas_antes),
                               (main._indices_fetched, self._indices_antes)):
            memoria.clear()
            memoria.update(antes)

    def _demo(self, ruta, **kw):
        """Un pedido del demo, como lo manda utils/api.js: POST sin sesión."""
        return self.client.post("/api/demo" + ruta, json={"demo": DEMO, "cuerpo": None}, **kw)

    def test_contesta_sin_cuenta_lo_mismo_que_a_una_cuenta(self):
        # La caché llena: lo que ya bajó el servidor para alguna cuenta.
        main._PF_BANKS_CACHE.update({"data": BANCOS, "at": time.time()})
        main._symsearch_cache["intel"] = {"ts": time.time(), "data": INTEL}
        main._indices_fetched["CER"] = time.time()
        with mock.patch("main._dividendos.actualizar", return_value=[]):
            for ruta in ("/fci/catalog", "/cedears", "/pf/banks", "/bond-indices/CER",
                         "/dividendos/historial?tickers=AAPL", "/tickers/search?q=intel"):
                demo = self._demo(ruta)
                self.assertEqual(demo.status_code, 200, f"{ruta}: {demo.text}")
                cuenta = self.client.get("/api" + ruta, headers=self.h)
                self.assertEqual(cuenta.status_code, 200, f"{ruta}: {cuenta.text}")
                self.assertEqual(demo.json(), cuenta.json(), ruta)
        # Y no son respuestas vacías: la prueba compara algo.
        self.assertEqual(self._demo("/fci/catalog").json()[0]["price"], 1234.56)
        self.assertIn("AAPL", {x["s"] for x in self._demo("/cedears").json()["items"]})
        self.assertEqual(self._demo("/bond-indices/CER").json()["latest_date"], "2026-11-18")
        self.assertEqual(self._demo("/dividendos/historial?tickers=AAPL").json()["tickers"]["AAPL"]["pagos"][0]
                         ["por_accion"], 0.26)
        self.assertEqual(self._demo("/tickers/search?q=intel").json()["results"], INTEL)

    def _salidas(self):
        """Espías en cada salida a la red de estas lecturas. Cuentan, no revientan:
        el código de las cuentas se traga el error de una fuente caída (el CER),
        así que un error no se vería."""
        return {
            "CER": mock.patch("main._fetch_cer_series", return_value={}),
            "UVA": mock.patch("main._fetch_uva_series", return_value={}),
            "dividendos de Yahoo": mock.patch("main._dividendos.actualizar", return_value=[]),
            "bancos": mock.patch("urllib.request.urlopen", side_effect=OSError("sin red")),
            "búsqueda en Yahoo": mock.patch("yfinance.Search", side_effect=OSError("sin red")),
        }

    def _pedir_todo(self, pedir):
        return [pedir("/pf/banks"), pedir("/bond-indices/CER"),
                pedir("/dividendos/historial?tickers=AAPL,ZZZZ"), pedir("/tickers/search?q=intel")]

    def _sin_cache(self):
        """Lo que una cuenta saldría a buscar: nada guardado, todo vencido, y el
        CER sin serie (se sirve con la UVA, que también se refresca)."""
        main._PF_BANKS_CACHE.clear()
        main._symsearch_cache.pop("intel", None)
        main._indices_fetched.clear()
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM bond_indices_daily")
            conn.execute("INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at) "
                         "VALUES ('UVA', '2026-11-18', 1700.5, 'prueba', '2026-11-18T00:00:00Z')")
            conn.commit()

    def test_el_demo_no_sale_a_buscar_nada_afuera(self):
        self._sin_cache()
        salidas = self._salidas()
        espias = {k: p.start() for k, p in salidas.items()}
        try:
            bancos, cer, dividendos, busqueda = self._pedir_todo(self._demo)
        finally:
            for p in salidas.values():
                p.stop()
        self.assertEqual([k for k, e in espias.items() if e.called], [])
        for r in (bancos, cer, dividendos, busqueda):
            self.assertEqual(r.status_code, 200, r.text)
        # Sin lo guardado, la forma de siempre con lo que hay.
        self.assertEqual(bancos.json(), [])
        self.assertEqual((cer.json()["basis"], cer.json()["series"]), ("UVA", {"2026-11-18": 1700.5}))
        self.assertEqual(dividendos.json()["tickers"]["ZZZZ"]["pagos"], [])
        self.assertEqual(dividendos.json()["sin_respuesta"], [])
        self.assertEqual(busqueda.json(), {"results": []})
        # Lo que buscó el visitante no quedó en la memoria de las cuentas.
        self.assertNotIn("intel", main._symsearch_cache)

    def test_los_espias_ven_la_salida_de_una_cuenta(self):
        """El control de la de arriba: con lo mismo, una cuenta sí sale a buscar
        cada cosa (si no, que el demo no salga no probaría nada)."""
        self._sin_cache()
        salidas = self._salidas()
        espias = {k: p.start() for k, p in salidas.items()}
        try:
            self._pedir_todo(lambda ruta: self.client.get("/api" + ruta, headers=self.h))
        finally:
            for p in salidas.values():
                p.stop()
        self.assertEqual([k for k, e in espias.items() if not e.called], [])

    def test_no_pide_sesion_ni_lee_la_que_llegue(self):
        main._PF_BANKS_CACHE.update({"data": BANCOS, "at": time.time()})
        r = self._demo("/pf/banks", headers={"Authorization": "Bearer basura"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), BANCOS)

    def test_pasa_por_el_freno_del_demo(self):
        with mock.patch.dict(main.FRENO_TECNICO, {"uno": (2, 3)}):
            codigos = [self._demo("/fci/catalog").status_code for _ in range(3)]
        self.assertEqual(codigos, [200, 200, 429])

    def test_un_indice_que_no_existe_es_400(self):
        self.assertEqual(self._demo("/bond-indices/OTRO").status_code, 400)


if __name__ == "__main__":
    unittest.main()
