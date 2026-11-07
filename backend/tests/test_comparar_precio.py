"""El comparador de precios (pieza 16): comparar.py + GET /api/comparar/precio.

Entra por el camino de producción: las posiciones se cargan por HTTP, las velas
las guarda el trabajo nocturno real (`main._run_velas_diarias_job`) o la bajada
a pedido de la ficha (`_velas_a_pedido`), con Yahoo reemplazado en su punto más
bajo, y la comparación se pide por HTTP. Lo que se compara es la MISMA serie que
dibuja la ficha (`/api/tecnico`), y eso también se prueba.

Los casos que importan:
  · todos arrancan en 100 el mismo día y el último valor es precio de hoy ÷
    precio de ese día × 100;
  · en pesos, lo de afuera va × el MEP de cada día, y guardar dólares es el MEP;
    en dólares, guardar dólares es 100 quieto y la inflación no se ofrece;
  · un CEDEAR con cambio de ratio no muestra la caída falsa de su serie en pesos;
  · una acción argentina se compara con SU precio de BYMA ÷ el MEP (no el ADR);
  · un día sin rueda (sábado) arranca con el cierre anterior; si un activo
    empieza después, el 100 se corre para todos y se dice cuál lo corrió.

Corre con: cd backend && python3 -m pytest tests/test_comparar_precio.py
"""
import os
import sys
import unittest
import unittest.mock
import uuid
from datetime import date, datetime, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import pandas as pd
from fastapi.testclient import TestClient

import comparar
from velas_diarias import PERIODO_COMPLETO
import main
from fechas import hoy_art_date
from tests.test_ultimos_n_anios import _el_ultimo

N_RUEDAS = 760


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class YahooFalso:
    """`precios[ticker](i, fecha)` da el cierre de la rueda i (0 = la más vieja);
    None = ese día no cotizó (un activo que empezó a cotizar después)."""

    def __init__(self, hoy):
        self.hoy, self.precios = hoy, {}

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        f = self.precios.get(ticker) or ((lambda i, d: 5000.0) if ticker == "^GSPC" else None)
        if f is None:
            return pd.DataFrame()
        base = _ruedas(self.hoy, N_RUEDAS)
        dias = _ruedas(self.hoy, N_RUEDAS if period == PERIODO_COMPLETO else 22)
        filas = {}
        for d in dias:
            c = f(base.index(d), d)
            if c is not None:
                filas[pd.Timestamp(d)] = (c, c, c, c, 1000.0)
        if not filas:
            return pd.DataFrame()
        idx = sorted(filas)
        o, h, l, c, v = zip(*[filas[k] for k in idx])
        return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v},
                            index=pd.DatetimeIndex(idx))


class CompararTest(unittest.TestCase):
    DIA_DE_LA_SEMANA = 1   # martes (ver `setUp`)

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "bond_indices_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"cmp-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        # El día de la prueba, fijo (`fechas.ahora_art`, el día argentino de toda la app):
        # un martes, el último precio es del lunes y «1 año» arranca un domingo, sin rueda
        # (vale el cierre del viernes). Con el día real, el caso cambiaba con el día de la
        # semana en que corría la suite (auditoría 06/11 de las pruebas del precio de
        # arranque, H3). La copia «UnViernes» corre lo mismo con un arranque con rueda.
        dia = _el_ultimo(self.DIA_DE_LA_SEMANA)
        reloj = mock.patch("fechas.ahora_art", return_value=datetime(dia.year, dia.month, dia.day, 15, 0))
        reloj.start()
        self.addCleanup(reloj.stop)
        self.hoy = hoy_art_date()
        self.dias = _ruedas(self.hoy, N_RUEDAS)
        self.yahoo = YahooFalso(self.hoy)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   # La inflación sale de lo guardado: sin red.
                   mock.patch("main._fetch_cer_series", lambda: {}),
                   mock.patch("main._fetch_uva_series", lambda: {})]
        for p in self._p:
            p.start()
        import velas_diarias
        velas_diarias._a_pedido_hechos.clear()

    def tearDown(self):
        for p in self._p:
            p.stop()
        with main.db_abierta() as conn:   # tablas globales (sin user_id)
            for t in ("fx_rates_daily", "bond_indices_daily", "velas_diarias", "velas_estado"):
                conn.execute(f"DELETE FROM {t}")
            conn.commit()

    # ─── ayudas ──────────────────────────────────────────────────────────────

    def _broker(self, name, currency):
        r = self.client.post("/api/brokers", json={"name": name, "currency": currency}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)

    def _posicion(self, broker, asset, asset_type):
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": asset_type},
                             headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _mep(self, f):
        with main.db_abierta() as conn:
            for i, d in enumerate(self.dias):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), f(i) * 1.1, f(i)))
            conn.commit()

    def _comparar(self, activos, moneda="usd", plazo="1a", local="", desde=None, status=200):
        q = f"/api/comparar/precio?activos={activos}&moneda={moneda}&plazo={plazo}"
        if local:
            q += f"&local={local}"
        if desde:
            q += f"&desde={desde}"
        r = self.client.get(q, headers=self.h)
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def _serie(self, res, clave):
        return next((s for s in res["series"] if s["clave"] == clave), None)

    def _un_anio(self):
        """El día del 100 de «1 año»: el mismo día de hace un año desde el último
        precio (la última rueda), con el cierre que tenía ese día: de fecha a fecha,
        como la ficha (Nico, 06/11: `tecnico.dia_de_arranque`). Hasta el 06/11 era
        hoy − 365; el 06/11 a la tarde (`4165c2f6`), el día siguiente a ése."""
        return (self.dias[-1] - timedelta(days=365)).isoformat()

    def _i(self, fecha):
        """La rueda que vale en `fecha` (la última en ese día o antes)."""
        return max(i for i, d in enumerate(self.dias) if d.isoformat() <= fecha)

    # ─── casos ───────────────────────────────────────────────────────────────

    def test_todos_arrancan_en_100_el_mismo_dia(self):
        # Dos activos que nadie sigue: se bajan en el momento, como en la ficha.
        self.yahoo.precios["MSFT"] = lambda i, d: 100 + i
        self.yahoo.precios["NVDA"] = lambda i, d: 400 - i * 0.2
        self.yahoo.precios["^GSPC"] = lambda i, d: 5000 + i * 2
        main._run_velas_diarias_job()   # el S&P 500 lo guarda la corrida de cada noche
        r = self._comparar("MSFT,NVDA", "usd", "1a")

        base = self._un_anio()
        self.assertEqual(r["base"], base)
        self.assertIsNone(r["base_corrida_por"])
        ib, ult = self._i(base), len(self.dias) - 1
        msft, nvda, sp, mep = (self._serie(r, k) for k in ("MSFT", "NVDA", "sp500", "mep"))
        for s in (msft, nvda, sp, mep):
            self.assertEqual(s["puntos"][0], {"d": base, "v": 100.0}, s["clave"])
        self.assertAlmostEqual(msft["final"], (100 + ult) / (100 + ib) * 100, places=2)
        self.assertAlmostEqual(nvda["final"], (400 - ult * 0.2) / (400 - ib * 0.2) * 100, places=2)
        self.assertAlmostEqual(sp["final"], (5000 + ult * 2) / (5000 + ib * 2) * 100, places=2)
        # En dólares, guardar dólares es 100 quieto y la inflación no se ofrece.
        self.assertEqual({p["v"] for p in mep["puntos"]}, {100.0})
        self.assertIn({"clave": "cer", "motivo": "solo_en_pesos"}, r["faltan"])
        self.assertIsNone(self._serie(r, "cer"))

        # Es la MISMA serie que dibuja la ficha: el último cierre ÷ el del día del 100.
        ficha = self.client.get("/api/tecnico/MSFT?moneda=usd", headers=self.h).json()["puntos"]
        en_base = [p["c"] for p in ficha if p["d"] <= base][-1]
        self.assertAlmostEqual(msft["final"], ficha[-1]["c"] / en_base * 100, places=2)

        # 3 años: el 100 se va para atrás. Lo guardado en esta prueba (760
        # ruedas) no llega a 3 años: arranca el primer día guardado, lo dice, y
        # no culpa a ningún activo (el S&P empieza el mismo día: es lo guardado).
        r3 = self._comparar("MSFT,NVDA", "usd", "3a")
        self.assertEqual(r3["base"], self.dias[0].isoformat())
        self.assertTrue(r3["base_corrida"])
        self.assertIsNone(r3["base_corrida_por"])

    def test_pesos_contra_dolares(self):
        # El dólar sube de 1000 a 1759: lo de afuera en pesos sube eso más lo suyo.
        self._mep(lambda i: 1000 + i)
        self.yahoo.precios["MSFT"] = lambda i, d: 100 + i
        self.yahoo.precios["^GSPC"] = lambda i, d: 5000.0
        base = self._un_anio()
        ib, ult = self._i(base), len(self.dias) - 1
        mep_sube = (1000 + ult) / (1000 + ib)
        with main.db_abierta() as conn:   # la inflación: el índice sube 30 %
            for i, d in enumerate(self.dias):
                conn.execute("INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at) "
                             "VALUES ('CER', ?, ?, 'test', 'x')", (d.isoformat(), 10 + i * 0.01))
            conn.commit()

        main._run_velas_diarias_job()
        usd = self._comparar("MSFT", "usd", "1a")
        ars = self._comparar("MSFT", "ars", "1a")
        m_usd, m_ars = self._serie(usd, "MSFT"), self._serie(ars, "MSFT")
        self.assertAlmostEqual(m_ars["final"], m_usd["final"] * mep_sube, delta=0.05)
        self.assertEqual(m_ars["convertida"], "mep")
        # En pesos, guardar dólares es el MEP; el S&P quieto en dólares sube como el dólar.
        self.assertAlmostEqual(self._serie(ars, "mep")["final"], mep_sube * 100, places=2)
        self.assertAlmostEqual(self._serie(ars, "sp500")["final"], mep_sube * 100, places=2)
        self.assertAlmostEqual(self._serie(usd, "sp500")["final"], 100.0, places=2)
        cer = self._serie(ars, "cer")
        self.assertEqual((cer["ticker"], cer["nombre"]), ("CER", "Inflación (CER)"))
        self.assertAlmostEqual(cer["final"], (10 + ult * 0.01) / (10 + ib * 0.01) * 100, places=2)

    def test_en_pesos_el_sp500_va_con_el_dolar_de_los_cedears(self):
        # Un CEDEAR en pesos va con el contado con liqui de cada día (Nico, 06/11), y
        # el S&P 500 con el MISMO dólar: es el que se compra en la Bolsa, con el
        # CEDEAR de SPY. Con el MEP, en Comparar SPY le «ganaba» 4,45 % en un año al
        # S&P 500, la misma canasta, y la ficha medía «cuántas veces se mueve lo que
        # el S&P 500» con dos dólares (auditoría del contado con liqui, H2 del
        # servidor). Acá MSFT se mueve igual que el S&P 500, y el contado con liqui
        # se separa del MEP con el tiempo y salta de un día al otro.
        self._mep(lambda i: 1000 + i)
        ccl = lambda i: (1000 + i) * (1 + i / 2000) * (1.005 if i % 2 else 0.995)   # noqa: E731
        fuente = [(d.isoformat(), ccl(i) - 1, ccl(i) + 1) for i, d in enumerate(self.dias)]
        with mock.patch("main._bajar_ccl", lambda: fuente):
            main._actualizar_ccl()
        self.yahoo.precios["MSFT"] = lambda i, d: 100.0 + i
        self.yahoo.precios["^GSPC"] = lambda i, d: 5000.0 + 50 * i
        main._run_velas_diarias_job()
        ars = self._comparar("MSFT", "ars", "1a")
        msft, sp = self._serie(ars, "MSFT"), self._serie(ars, "sp500")
        self.assertEqual((msft["convertida"], sp["convertida"]), ("ccl", "ccl"))
        self.assertAlmostEqual(msft["final"], sp["final"], places=1)
        ib, ult = self._i(self._un_anio()), len(self.dias) - 1
        self.assertAlmostEqual(self._serie(ars, "mep")["final"], (1000 + ult) / (1000 + ib) * 100, places=2,
                               msg="guardar dólares sigue siendo el MEP")
        ficha = self.client.get("/api/tecnico/MSFT?moneda=ars", headers=self.h).json()
        self.assertAlmostEqual(ficha["movimiento"]["dia_normal"]["veces_el_sp500"], 1.0, places=3)

    def test_sin_cer_se_usa_la_uva_y_se_dice(self):
        # La fuente del CER da 404 desde 09/2026: se mide con la UVA (el BCRA la
        # ajusta por CER) y el nombre lo dice.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["MSFT"] = lambda i, d: 100.0
        with main.db_abierta() as conn:
            for i, d in enumerate(self.dias):
                conn.execute("INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at) "
                             "VALUES ('UVA', ?, ?, 'test', 'x')", (d.isoformat(), 1000 + i))
            conn.commit()
        main._run_velas_diarias_job()
        cer = self._serie(self._comparar("MSFT", "ars", "1a"), "cer")
        self.assertEqual((cer["ticker"], cer["nombre"]), ("UVA", "Inflación (CER, vía UVA)"))
        ib, ult = self._i(self._un_anio()), len(self.dias) - 1
        self.assertAlmostEqual(cer["final"], (1000 + ult) / (1000 + ib) * 100, places=2)

    def test_cedear_con_cambio_de_ratio(self):
        # Apple quieta en Nueva York; el CEDEAR en pesos pasa de ratio 10 a 20 a
        # los 7 meses: Yahoo muestra −50 % ese día sin que nada pase.
        self._mep(lambda i: 1000.0)
        salto = N_RUEDAS - 150
        self.yahoo.precios["AAPL"] = lambda i, d: 200.0
        self.yahoo.precios["AAPL.BA"] = lambda i, d: 20000.0 if i < salto else 10000.0
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AAPL", "CEDEAR")
        main._run_velas_diarias_job()

        r = self._comparar("AAPL", "ars", "1a")
        aapl = self._serie(r, "AAPL")
        self.assertEqual(aapl["ticker"], "AAPL.BA", "en pesos, la serie del CEDEAR")
        self.assertAlmostEqual(aapl["final"], 100.0, places=2, msg="sin la caída falsa del cambio de ratio")
        self.assertGreater(min(p["v"] for p in aapl["puntos"]), 99.0)

    def test_accion_argentina_con_su_precio_de_byma(self):
        # Tu GGAL de IOL: $ 5.000 quieto con el dólar subiendo → en dólares baja.
        # El ADR de Nueva York (otro instrumento) sube: no es el tuyo.
        self._mep(lambda i: 1000 + i)
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        self.yahoo.precios["GGAL"] = lambda i, d: 50 + i
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        main._run_velas_diarias_job()

        base = self._un_anio()
        ib, ult = self._i(base), len(self.dias) - 1
        r = self._comparar("GGAL", "usd", "1a", local="GGAL")
        g = self._serie(r, "GGAL")
        self.assertEqual((g["ticker"], g["convertida"]), ("GGAL.BA", "mep"))
        self.assertAlmostEqual(g["final"], (1000 + ib) / (1000 + ult) * 100, places=2,
                               msg="$ 5.000 ÷ el MEP de cada día")
        ars = self._serie(self._comparar("GGAL", "ars", "1a", local="GGAL"), "GGAL")
        self.assertAlmostEqual(ars["final"], 100.0, places=2, msg="en pesos no se movió")
        adr = self._serie(self._comparar("GGAL", "usd", "1a"), "GGAL")
        self.assertEqual(adr["ticker"], "GGAL", "sin la marca, el ADR (como la ficha)")

    def test_fecha_sin_precio_ese_dia(self):
        # Tu primera compra fue un sábado: vale el cierre del viernes.
        self.yahoo.precios["MSFT"] = lambda i, d: 100 + i
        sabado = next(d for d in reversed(self.dias[:-60]) if d.weekday() == 4) + timedelta(days=1)
        viernes = sabado - timedelta(days=1)
        lunes = sabado + timedelta(days=2)
        r = self._comparar("MSFT", "usd", "compra", desde=sabado.isoformat())
        self.assertEqual(r["base"], sabado.isoformat())
        m = self._serie(r, "MSFT")
        self.assertEqual(m["puntos"][0], {"d": sabado.isoformat(), "v": 100.0})
        iv, il = self.dias.index(viernes), self.dias.index(lunes)
        self.assertEqual(m["puntos"][1]["d"], lunes.isoformat())
        self.assertAlmostEqual(m["puntos"][1]["v"], (100 + il) / (100 + iv) * 100, places=2)

    def test_un_activo_que_empieza_despues_corre_el_100_para_todos(self):
        # NVDA cotiza desde hace 100 ruedas: con «1 año», todos arrancan ese día.
        desde_i = N_RUEDAS - 100
        self.yahoo.precios["MSFT"] = lambda i, d: 100 + i
        self.yahoo.precios["NVDA"] = lambda i, d: (50.0 + i) if i >= desde_i else None
        main._run_velas_diarias_job()
        r = self._comparar("MSFT,NVDA", "usd", "1a")
        primero = self.dias[desde_i].isoformat()
        self.assertEqual((r["base"], r["base_corrida"], r["base_corrida_por"]), (primero, True, "NVDA"))
        for k in ("MSFT", "NVDA", "sp500", "mep"):
            self.assertEqual(self._serie(r, k)["puntos"][0], {"d": primero, "v": 100.0}, k)

    def test_desde_antes_de_lo_guardado_el_sp500_que_empieza_unos_dias_despues_no_se_cae(self):
        # «Desde tu primera compra», de antes de lo guardado: todo arranca donde
        # empieza lo guardado. Si ahí el S&P 500 empieza 2 ruedas después que el
        # activo (otro calendario, otro día de bajada entera), quedaba afuera:
        # «S&P 500: sin datos desde esa fecha» (auditoría de método 06/11, H1). Ahora
        # arranca con él: es LA regla de «Una cartera» (`comparar.dia_del_cien`).
        self.yahoo.precios["MSFT"] = lambda i, d: 100 + i
        self.yahoo.precios["^GSPC"] = lambda i, d: (5000.0 + i) if i >= 2 else None
        main._run_velas_diarias_job()
        r = self._comparar("MSFT", "usd", "compra", desde="2019-03-15")
        dia_del_sp = self.dias[2].isoformat()
        self.assertEqual(r["base"], dia_del_sp)
        self.assertNotIn("sp500", [f["clave"] for f in r["faltan"]])
        for k in ("MSFT", "sp500", "mep"):
            self.assertEqual(self._serie(r, k)["puntos"][0], {"d": dia_del_sp, "v": 100.0}, k)
        # Lo guardado empieza ahí para todos: no es que MSFT cotice hace menos.
        self.assertEqual((r["base_corrida"], r["base_corrida_por"]), (True, None))

    def test_una_serie_cortada_no_se_muestra_como_de_hoy(self):
        # KO dejó de actualizarse hace 20 ruedas (deslistada, o nadie la baja):
        # su último valor NO es «hoy». No se dibuja y se dice hasta cuándo llega.
        corte = N_RUEDAS - 20
        self.yahoo.precios["MSFT"] = lambda i, d: 100.0 + i
        self.yahoo.precios["KO"] = lambda i, d: (60.0 + i) if i < corte else None
        main._run_velas_diarias_job()
        r = self._comparar("MSFT,KO", "usd", "1a")
        self.assertIsNone(self._serie(r, "KO"))
        self.assertIn({"clave": "KO", "motivo": "vieja", "hasta": self.dias[corte - 1].isoformat()}, r["faltan"])
        self.assertEqual(r["hasta"], self.dias[-1].isoformat())

    def test_la_inflacion_vieja_o_de_manana_no_se_dibuja_como_hoy(self):
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["MSFT"] = lambda i, d: 100.0
        main._run_velas_diarias_job()
        # La UVA se publica por adelantado: lo de mañana no entra.
        with main.db_abierta() as conn:
            for k in range(-400, 40):
                d = (self.hoy + timedelta(days=k)).isoformat()
                conn.execute("INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at) "
                             "VALUES ('UVA', ?, ?, 'test', 'x')", (d, 1000.0 + k))
            conn.commit()
        cer = self._serie(self._comparar("MSFT", "ars", "1a"), "cer")
        self.assertEqual(cer["fecha_final"], self.dias[-1].isoformat(), "termina el último día de mercado")
        # Un CER guardado que dejó de llegar hace meses (la fuente da 404): no
        # se dibuja quieto, se dice hasta cuándo llega.
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM bond_indices_daily")
            for k in range(-400, -90):
                conn.execute("INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at) "
                             "VALUES ('CER', ?, ?, 'test', 'x')", ((self.hoy + timedelta(days=k)).isoformat(), 10.0 + k))
            conn.commit()
        r = self._comparar("MSFT", "ars", "1a")
        self.assertIsNone(self._serie(r, "cer"))
        self.assertIn({"clave": "cer", "motivo": "vieja", "hasta": (self.hoy - timedelta(days=91)).isoformat()},
                      r["faltan"])

    def test_lo_que_no_tiene_precios_se_dice(self):
        # Un activo que Yahoo no tiene: no aparece y dice por qué; el resto sí.
        self.yahoo.precios["MSFT"] = lambda i, d: 100.0
        r = self._comparar("MSFT,ZZZZ", "usd", "1a")
        self.assertIsNotNone(self._serie(r, "MSFT"))
        self.assertIsNone(self._serie(r, "ZZZZ"))
        self.assertIn("ZZZZ", {f["clave"] for f in r["faltan"]})
        # En pesos sin ningún dólar guardado: tu acción argentina sí (es en
        # pesos), pero el dólar y el S&P en pesos no se inventan.
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        main._run_velas_diarias_job()
        r = self._comparar("GGAL", "ars", "1a", local="GGAL")
        self.assertIsNotNone(self._serie(r, "GGAL"))
        self.assertIsNone(self._serie(r, "mep"))
        self.assertIsNone(self._serie(r, "sp500"))
        self.assertIn({"clave": "mep", "motivo": "sin_datos"}, r["faltan"])
        self.assertIn({"clave": "sp500", "motivo": "sin_datos"}, r["faltan"])

    def test_pedidos_invalidos(self):
        self._comparar("A,B,C,D,E", status=400)
        self._comparar("", status=400)
        self._comparar("<x>", status=400)
        self._comparar("MSFT", plazo="5a", status=400)
        self._comparar("MSFT", plazo="compra", status=400)
        self._comparar("MSFT", plazo="compra", desde="2025-13-40", status=400)
        self._comparar("MSFT", plazo="compra", desde=self.hoy.isoformat(), status=400)
        self._comparar("MSFT", local="<y>", status=400)
        r = self.client.get("/api/comparar/precio?activos=MSFT")
        self.assertIn(r.status_code, (401, 403), "sin sesión, nada")


class CompararUnViernes(CompararTest):
    """Las mismas, un viernes: el último precio es del jueves y «1 año» arranca un
    miércoles, con rueda."""
    DIA_DE_LA_SEMANA = 4


class BaseCienTest(unittest.TestCase):
    """La regla de arrancar en 100, suelta."""

    def test_cortada_antes_del_dia_del_100(self):
        # Una serie que se cortó ANTES del día del 100 daba una línea quieta en
        # 100 («hoy son US$ 100»). Ahora queda afuera como vieja.
        viejas = [{"date": "2024-01-02", "close": 10.0}, {"date": "2024-01-03", "close": 11.0}]
        nuevas = [{"date": f"2025-11-{d:02d}", "close": 50.0 + d} for d in range(3, 29)]
        series = {"VIEJ": viejas, "NUEV": nuevas}
        with unittest.mock.patch("tecnico.serie", lambda c, a, m, l, **k: {"velas": series[a]}), \
             unittest.mock.patch("tecnico.indice_con_dolar", lambda c, s, m, d=None: (nuevas, None)):
            r = comparar.comparar(None, [("VIEJ", False), ("NUEV", False)], "usd", "2025-11-03",
                                  hoy=__import__("datetime").date(2025, 11, 29))
        self.assertEqual([s["clave"] for s in r["series"]], ["NUEV", "sp500", "mep"])
        self.assertIn({"clave": "VIEJ", "motivo": "vieja", "hasta": "2024-01-03"}, r["faltan"])

    def test_dia_del_cien(self):
        # LA regla del día del 100 de Comparar y de «Una cartera» (H1, 06/11).
        hasta = "2026-11-05"
        hoy = date(2026, 11, 6)                             # lo viejo se mide contra hoy
        activo = [("2021-11-05", 1.0), (hasta, 2.0)]        # desde un viernes
        sp = [("2021-11-08", 1.0), (hasta, 2.0)]            # desde el lunes
        lejos = [("2021-11-20", 1.0), (hasta, 2.0)]         # no tenemos su historia
        vieja = [("2021-11-08", 1.0), ("2026-10-01", 2.0)]  # dejó de actualizarse
        cien = lambda desde, varas: comparar.dia_del_cien(desde, [activo], varas, hoy)
        self.assertEqual(cien("2019-03-15", [sp]), ("2021-11-08", "2021-11-05"))
        self.assertEqual(cien("2019-03-15", [lejos]), ("2021-11-05", "2021-11-05"), "sin su historia no corre nada")
        self.assertEqual(cien("2019-03-15", [vieja]), ("2021-11-05", "2021-11-05"), "una vieja no corre nada")
        self.assertEqual(cien("2023-01-02", [sp]), ("2023-01-02", "2023-01-02"), "lejos del borde, lo pedido")
        self.assertEqual(cien("2019-03-15", [sp, lejos]), ("2021-11-08", "2021-11-05"))
        # La semana de margen, exacta: 7 días después corre; 8, no.
        siete, ocho = [("2021-11-12", 1.0), (hasta, 2.0)], [("2021-11-13", 1.0), (hasta, 2.0)]
        self.assertEqual(cien("2019-03-15", [siete])[0], "2021-11-12")
        self.assertEqual(cien("2019-03-15", [ocho])[0], "2021-11-05")

    def test_regla(self):
        p = [("2025-01-02", 10.0), ("2025-01-03", 12.0), ("2025-01-06", 9.0)]
        self.assertEqual(comparar.base_cien(p, "2025-01-04"),
                         [{"d": "2025-01-04", "v": 100.0}, {"d": "2025-01-06", "v": 75.0}])
        self.assertEqual(comparar.base_cien(p, "2025-01-01"), [], "antes del primer precio no hay 100")


if __name__ == "__main__":
    unittest.main()
