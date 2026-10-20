"""La lista de CEDEARs con su precio en dólares (cedears_dolar.universo).

Los casos salen del feed real de data912 del 2026-10-20: los códigos raros
(GOGLD, BA.CD, BRKBD), los tickers que terminan en D sin ser la especie dólar de
nada (BBD), y las especies D que no operaron o cotizan lejos.

Corre con: cd backend && python3 -m pytest tests/test_cedears_dolar.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import cedears_dolar as cd


def _f(c, v=100.0):
    return {'c': c, 'v': v, 'pct': 0.0}


# Recorte del feed real (pesos, dólar-MEP y cable). MEP implícito ~1.540.
FEED = {
    'AAPL': _f(27780), 'AAPLD': _f(18.04), 'AAPLC': _f(18.1),
    'SPY': _f(20780), 'SPYD': _f(13.52),
    'KO': _f(30300), 'KOD': _f(19.65),
    'GOOGL': _f(9670), 'GOGLD': _f(6.3), 'GOGLC': _f(6.31),
    'BA.C': _f(20480), 'BA.CD': _f(13.44), 'BA.CC': _f(13.5),
    'BAC': _f(7.81, v=0),                      # otra cosa, en dólares y sin operar
    'BRKB': _f(39180), 'BRKBD': _f(25.45),
    'BB': _f(4387.5), 'BBD': _f(6415), 'BBDD': _f(4.175),   # BBD = Bradesco
    'YELP': _f(15930), 'YELPD': _f(8.15, v=0),              # D lejos y sin operar
    'URBN': _f(90000), 'URBND': _f(73.9, v=500),            # D 26 % arriba
    'ABEV3': _f(3100),                                      # sin especie en dólares
    # Códigos irregulares (auditoría del 20/10: la primera versión los listaba
    # como CEDEARs "en pesos" a precio de dólar).
    'PETR3': _f(22350), 'PETRD': _f(14.5, v=10), 'PETRC': _f(6.16, v=0),   # cable vieja
    'VALE3': _f(21480), 'VAL3D': _f(13.9, v=5),
    'C': _f(65925), 'C.D': _f(42.89), 'CC': _f(44.2, v=0),
    'B': _f(32940), 'B.D': _f(21.37), 'B.C': _f(21.5),
    'BMY': _f(33500),                     # B.C NO es "BMY en dólares" (1 letra en común)
    'PHG': _f(9500),                      # PETRC NO es de PHG
    'ALAB': _f(10620), 'ALAD': _f(6.9),
    'AKO.B': _f(9800), 'AKOBD': _f(6.4),  # código con punto: la app no lo puede cotizar
    'YZCA': _f(0.01),                     # basura del feed
}


class UniversoTest(unittest.TestCase):
    def setUp(self):
        self.u = {f['s']: f for f in cd.universo(FEED, mep=1540.0)}

    def test_codigo_normal(self):
        f = self.u['AAPL']
        self.assertEqual((f['pesos'], f['dolares'], f['fuente_usd']), ('AAPL', 'AAPLD', 'byma'))
        self.assertEqual(f['px_usd'], 18.04)

    def test_codigos_que_no_son_pesos_mas_d(self):
        self.assertEqual(self.u['GOOGL']['dolares'], 'GOGLD')
        self.assertEqual((self.u['BAC']['pesos'], self.u['BAC']['dolares']), ('BA.C', 'BA.CD'))
        self.assertEqual((self.u['BRK-B']['pesos'], self.u['BRK-B']['dolares']), ('BRKB', 'BRKBD'))

    def test_las_especies_en_dolares_no_son_un_cedear_aparte(self):
        for cod in ('AAPLD', 'AAPLC', 'GOGLD', 'GOGLC', 'BA.CD', 'BA.CC', 'BRKBD', 'SPYD'):
            self.assertNotIn(cod, self.u)
        # Ni dos BAC, ni BRKB suelto.
        self.assertEqual(sum(1 for s in self.u if s == 'BAC'), 1)
        self.assertNotIn('BRKB', self.u)

    def test_un_ticker_que_termina_en_d_no_es_la_especie_dolar_de_otro(self):
        # BBD (Bradesco) no es "BB en dólares": pesos÷dólares daría ~1 peso por dólar.
        self.assertIsNone(self.u['BB']['dolares'])
        self.assertIn('BBD', self.u)
        self.assertEqual(self.u['BBD']['dolares'], 'BBDD')

    def test_precio_d_que_no_opero_o_esta_lejos_se_estima(self):
        y = self.u['YELP']
        self.assertEqual((y['dolares'], y['fuente_usd']), ('YELPD', 'estimado'))
        self.assertAlmostEqual(y['px_usd'], 15930 / 1540.0, places=3)
        u = self.u['URBN']
        self.assertEqual(u['fuente_usd'], 'estimado')
        self.assertAlmostEqual(u['px_usd'], 90000 / 1540.0, places=3)

    def test_sin_especie_en_dolares(self):
        f = self.u['ABEV3']
        self.assertIsNone(f['dolares'])
        self.assertIsNone(f['px_usd'])

    def test_sin_dolar_de_la_app_usa_el_de_la_bolsa(self):
        u = {f['s']: f for f in cd.universo(FEED, mep=None)}
        self.assertEqual(u['AAPL']['fuente_usd'], 'byma')

    def test_feed_vacio(self):
        self.assertEqual(cd.universo({}), [])

    def test_codigos_irregulares_van_con_su_raiz(self):
        self.assertEqual(self.u['PETR3']['dolares'], 'PETRD')
        self.assertEqual(self.u['VALE3']['dolares'], 'VAL3D')
        self.assertEqual(self.u['C']['dolares'], 'C.D')
        self.assertEqual(self.u['B']['dolares'], 'B.D')
        self.assertEqual(self.u['ALAB']['dolares'], 'ALAD')

    def test_ninguna_especie_en_dolares_se_ofrece_como_cedear_en_pesos(self):
        for cod in ('PETRD', 'PETRC', 'VAL3D', 'C.D', 'CC', 'B.D', 'B.C', 'ALAD', 'AKOBD'):
            self.assertNotIn(cod, self.u, cod)
        # Y ninguna raíz quedó con precio de dólar.
        self.assertTrue(all(f['px_ars'] > 100 for f in self.u.values()),
                        [f['s'] for f in self.u.values() if f['px_ars'] <= 100])

    def test_una_letra_en_comun_no_ata(self):
        self.assertIsNone(self.u['BMY']['dolares'])
        self.assertIsNone(self.u['PHG']['dolares'])

    def test_no_se_ofrece_lo_que_la_app_no_puede_cotizar(self):
        self.assertNotIn('AKO.B', self.u)
        self.assertNotIn('YZCA', self.u)


class FeedParcialTest(unittest.TestCase):
    """Antes de la apertura el feed trae la mitad (20/10: 465 códigos a las 10:23
    contra 1.025 a las 9:56): especies en dólares SIN su raíz."""

    def test_especie_en_dolares_sin_raiz_no_se_lista_como_cedear_en_pesos(self):
        feed = {'AAPL': _f(27780), 'AAPLD': _f(18.04),
                'SPYD': _f(13.52), 'MELID': _f(16.19), 'MUD': _f(192.0),   # sin SPY/MELI/MU
                'AMD': _f(87800), 'LAC': _f(3507.5)}                       # raíces que terminan en D/C
        u = {f['s']: f for f in cd.universo(feed, mep=1540.0)}
        for cod in ('SPYD', 'MELID', 'MUD'):
            self.assertNotIn(cod, u, cod)
        self.assertIn('AMD', u)
        self.assertIn('LAC', u)

    def test_vale_adr_en_dolares_no_se_ata_a_vale3(self):
        # VALED es Vale (ADR) en dólares; sin VALE en el feed se ataba a VALE3 con
        # un 2,01 — el precio de otro papel.
        feed = {'AAPL': _f(27780), 'AAPLD': _f(18.04), 'VALE3': _f(21480), 'VALED': _f(6.94)}
        u = {f['s']: f for f in cd.universo(feed, mep=1540.0)}
        self.assertIsNone(u['VALE3']['dolares'])
        self.assertNotIn('VALED', u)


class EndpointTest(unittest.TestCase):
    """GET /api/cedears: el mismo camino que la app, con el filtro de `mercado`."""

    def test_sola_los_cedears_y_con_la_moneda(self):
        import main
        from fastapi.testclient import TestClient
        feed = {k: {**v, 'mercado': 'arg_cedears'} for k, v in FEED.items()}
        # Una acción argentina con "D" al final: YPFD no es "YPF en dólares".
        feed['YPFD'] = {'c': 45000, 'v': 100, 'pct': 0, 'mercado': 'arg_stocks'}
        feed['YPF'] = {'c': 29.2, 'v': 100, 'pct': 0, 'mercado': 'arg_stocks'}
        conn = main.get_db()
        uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                           (f"ced-{id(self)}@rendi.test", "x")).lastrowid
        conn.commit()
        conn.close()
        orig = main._fetch_data912_equities
        main._fetch_data912_equities = lambda: feed
        try:
            r = TestClient(main.app).get(
                "/api/cedears", headers={"Authorization": f"Bearer {main.create_token(uid)}"})
        finally:
            main._fetch_data912_equities = orig
        self.assertEqual(r.status_code, 200, r.text)
        items = {f['s']: f for f in r.json()['items']}
        self.assertEqual(items['AAPL']['dolares'], 'AAPLD')
        self.assertNotIn('YPFD', items)
        self.assertNotIn('YPF', items)

    def test_con_feed_parcial_devuelve_la_ultima_lista_completa(self):
        import main
        from fastapi.testclient import TestClient
        completo = {k: {**v, 'mercado': 'arg_cedears'} for k, v in FEED.items()}
        parcial = {k: v for k, v in list(completo.items())[:5]}
        conn = main.get_db()
        uid = conn.execute("INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
                           (f"ced2-{id(self)}@rendi.test", "x")).lastrowid
        conn.commit()
        conn.close()
        h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        c = TestClient(main.app)
        orig, guardado = main._fetch_data912_equities, dict(main._CEDEARS_ULTIMO)
        try:
            main._CEDEARS_ULTIMO.update({"items": None, "n_feed": 0})
            main._fetch_data912_equities = lambda: completo
            lleno = c.get("/api/cedears", headers=h).json()["items"]
            main._fetch_data912_equities = lambda: parcial
            r = c.get("/api/cedears", headers=h).json()
        finally:
            main._fetch_data912_equities = orig
            main._CEDEARS_ULTIMO.clear()
            main._CEDEARS_ULTIMO.update(guardado)
        self.assertTrue(r.get("parcial"))
        self.assertEqual(r["items"], lleno)


if __name__ == "__main__":
    unittest.main()
