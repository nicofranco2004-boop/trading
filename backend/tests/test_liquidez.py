"""La liquidez en BYMA de la ficha del activo (liquidez.py + GET /api/liquidez).

Entra por HTTP, como la ficha. data912 y Yahoo se reemplazan en su punto más
bajo (la lista en vivo, la historia de un papel): las cuentas, los cortes y el
caché corren de verdad.

Los casos que importan:
  · un CEDEAR que se opera mucho dice «mucha» con la plata por día;
  · poca por plata, por días sin operar o por la diferencia entre puntas;
  · un CEDEAR chico sin historia en data912 usa la de Yahoo, y si Yahoo
    tampoco la tiene (una fila suelta) no inventa «20 días sin operar»;
  · lo que no cotiza en BYMA no pide nada a nadie;
  · se cachea: la segunda ficha no vuelve a pedir la historia.

Corre con: cd backend && python3 -m pytest tests/test_liquidez.py
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

import liquidez
import main


def _ruedas(n=25):
    out, d = [], date(2026, 10, 22)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return sorted(out)


RUEDAS = _ruedas()


def _vivo(c, bid=None, ask=None, mercado="arg_cedears", v=1000.0):
    return {"c": c, "pct": 0.0, "v": v, "mercado": mercado, "px_bid": bid, "px_ask": ask}


class LiquidezTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"liq-{tag}@rendi.test",))
            conn.commit()
            self.h = {"Authorization": f"Bearer {main.create_token(cur.lastrowid)}"}
        liquidez._cache.clear()
        self.vivo = {}
        self.d912 = {("stocks", "GGAL"): {d: 1e6 for d in RUEDAS}}
        self.yahoo = {}
        self.pedidos = []

        def d912(tipo, papel):
            self.pedidos.append(("data912", papel))
            return dict(self.d912.get((tipo, papel), {}))

        def yahoo(papel):
            self.pedidos.append(("yahoo", papel))
            return dict(self.yahoo.get(papel, {}))
        self._p = [mock.patch("main._fetch_data912_equities", lambda: self.vivo),
                   mock.patch.object(liquidez, "_historia_data912", d912),
                   mock.patch.object(liquidez, "_historia_yahoo", yahoo)]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _liq(self, papel):
        r = self.client.get(f"/api/liquidez/{papel}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_cedear_que_se_opera_mucho(self):
        # MELI: ~240.000 CEDEARs por día a $ 25.000 = $ 6.000 millones.
        self.vivo["MELI"] = _vivo(25000.0, 24980.0, 25000.0)
        self.d912[("cedears", "MELI")] = {d: 240000.0 for d in RUEDAS}
        f = self._liq("MELI.BA")
        self.assertTrue(f["disponible"])
        self.assertEqual((f["nivel"], f["es_cedear"], f["fuente"]), ("mucha", True, "data912"))
        self.assertEqual(f["pesos_por_dia"], 6_000_000_000)
        self.assertEqual((f["ruedas"], f["dias_sin_operar"]), (20, 0))
        self.assertAlmostEqual(f["spread_pct"], 0.08, places=2)

    def test_media(self):
        self.vivo["XLE"] = _vivo(57000.0, 56950.0, 57050.0)
        self.d912[("cedears", "XLE")] = {d: 3000.0 for d in RUEDAS}   # $ 171 M por día
        self.assertEqual(self._liq("XLE")["nivel"], "media")

    def test_poca_por_plata_por_dias_sin_operar_y_por_puntas(self):
        self.vivo["AGRO"] = _vivo(1000.0, 999.0, 1001.0, mercado="arg_stocks")
        self.d912[("stocks", "AGRO")] = {d: 30000.0 for d in RUEDAS}      # $ 30 M
        a = self._liq("AGRO")
        self.assertEqual((a["nivel"], a["es_cedear"]), ("poca", False))
        # Se opera bien los días que se opera, pero 5 de las últimas 20 ruedas, nada.
        self.vivo["MUX"] = _vivo(12000.0, 11990.0, 12010.0)
        self.d912[("cedears", "MUX")] = {d: (0.0 if i % 4 == 0 else 100000.0)
                                         for i, d in enumerate(RUEDAS[-20:])}
        m = self._liq("MUX")
        self.assertEqual((m["nivel"], m["dias_sin_operar"]), ("poca", 5))
        # Mucha plata, pero hoy entre compra y venta hay 2,4 %.
        self.vivo["IREN"] = _vivo(10000.0, 9900.0, 10140.0)
        self.d912[("cedears", "IREN")] = {d: 1e6 for d in RUEDAS}
        i = self._liq("IREN")
        self.assertEqual((i["nivel"], i["spread_pct"]), ("poca", 2.42))

    def test_dias_que_no_aparecen_en_la_historia_son_dias_sin_operar(self):
        # data912 no lista los días en que un papel no se operó: se cuentan
        # contra las ruedas de BYMA (las del papel de referencia).
        self.vivo["BXC"] = _vivo(5000.0)
        self.d912[("cedears", "BXC")] = {d: 1e6 for d in RUEDAS[-20:][::2]}
        f = self._liq("BXC")
        self.assertEqual((f["dias_sin_operar"], f["nivel"]), (10, "poca"))

    def test_cedear_chico_usa_yahoo_y_sin_historia_no_inventa(self):
        self.vivo["MUX"] = _vivo(12000.0, 11990.0, 12010.0)
        self.yahoo["MUX"] = {d: 2500.0 for d in RUEDAS[-20:]}            # $ 30 M
        f = self._liq("MUX")
        self.assertEqual((f["fuente"], f["nivel"], f["dias_sin_operar"]), ("yahoo", "poca", 0))
        # IRENC: ni data912 ni Yahoo tienen su historia. Antes decía «20 días
        # sin operar» de algo que se opera todos los días; ahora sólo las puntas.
        self.vivo["IRENC"] = _vivo(2.19, 2.17, 2.20)
        g = self._liq("IRENC")
        self.assertEqual((g["pesos_por_dia"], g["dias_sin_operar"]), (None, None))
        self.assertEqual((g["nivel"], g["spread_pct"]), ("poca", 1.38))
        # Sin historia y con puntas angostas (o fuera de horario): no hay nada que decir.
        self.vivo["QQQ"] = _vivo(30000.0, None, None)
        self.assertFalse(self._liq("QQQ")["disponible"])

    def test_una_fila_suelta_de_yahoo_no_es_una_historia(self):
        # La función real de Yahoo (sin el reemplazo de esta prueba), con Yahoo
        # reemplazado un nivel más abajo.
        import pandas as pd
        self._p[2].stop()
        try:
            with mock.patch("pricing.yahoo._historia") as hist:
                hist.return_value = pd.DataFrame({"Volume": [9.0]}, index=pd.to_datetime(["2026-10-22"]))
                self.assertEqual(liquidez._historia_yahoo("IRENC"), {})
                hist.return_value = pd.DataFrame({"Volume": [100.0] * 14 + [float("nan")]},
                                                 index=pd.to_datetime(RUEDAS[-15:]))
                h = liquidez._historia_yahoo("MUX")
                self.assertEqual((len(h), h[RUEDAS[-1]]), (15, 0.0), "un volumen vacío es 0, no NaN")
        finally:
            self._p[2].start()

    def test_lo_que_no_cotiza_en_byma_no_pide_nada(self):
        f = self._liq("NVDA")          # no está en la lista de data912 de esta prueba
        self.assertFalse(f["disponible"])
        self.assertEqual(self.pedidos, [])
        self.assertEqual(self.client.get("/api/liquidez/<x>", headers=self.h).status_code, 400)
        self.assertEqual(self.client.get("/api/liquidez/MELI").status_code, 401)

    def test_se_cachea_y_una_fuente_caida_no_traba(self):
        self.vivo["MELI"] = _vivo(25000.0, 24980.0, 25000.0)
        self.d912[("cedears", "MELI")] = {d: 240000.0 for d in RUEDAS}
        self._liq("MELI")
        self._liq("MELI")
        self.assertEqual(self.pedidos.count(("data912", "MELI")), 1, "la segunda ficha no vuelve a pedir")

        def caida(tipo, papel):
            raise TimeoutError("data912 no contesta")
        liquidez._cache.clear()
        with mock.patch.object(liquidez, "_historia_data912", caida):
            self.yahoo["MELI"] = {d: 240000.0 for d in RUEDAS[-20:]}
            f = self._liq("MELI")
        self.assertEqual((f["fuente"], f["nivel"]), ("yahoo", "mucha"), "cae a Yahoo, no a un error")


if __name__ == "__main__":
    unittest.main()
