"""«Los últimos N años» y «sin precios de la última semana»: UNA regla en las
pantallas que comparan precios (`tecnico.primer_dia` y `tecnico.es_vieja`).

LA DECISIÓN (Nico, 06/11/2026). «1 año» y «3 años» se cuentan desde el último
precio, como ya lo hacían la ficha, el Backtesting de una regla y «Una cartera».
Comparar → Precio contaba desde hoy: un domingo, un lunes o después de un feriado
arrancaba otro día que las otras pantallas para el mismo activo (MU en Pascua de
2026: +465,9 % en Comparar contra +392,7 % en «Una cartera»; auditoría de «Una
cartera» 05/11, H4). Y una línea sin precios de la última semana, contada desde
HOY y no desde el activo más nuevo, no entra y se dice: un activo solo que dejó de
cotizar se mostraba con «el último año» terminando hace meses, sin avisar (H9).

POR EL CAMINO DE PRODUCCIÓN. Las velas las guarda la corrida de la noche
(`main._run_velas_diarias_job`) o la bajada a pedido (`_velas_a_pedido`), con
Yahoo reemplazado en su punto más bajo (`pricing.yahoo._historia`), y las tres
pantallas se piden por HTTP:
  · Comparar → Precio: GET /api/comparar/precio?plazo=1a|3a
  · «Una cartera»:     GET /api/backtest/cartera
  · Una regla:         GET /api/tecnico/{activo}/backtest
  · «Mi cartera de hoy», con la que abre «Una cartera»: GET /api/backtest/cartera/hoy
«Hoy» es un día de la semana elegido (un domingo, un lunes, el sábado después de
un feriado) de hace unas semanas, contado desde el día en que corre la prueba:
no vence con la fecha. Lo fija `fechas.ahora_art`, de donde sale el día
argentino de toda la app.

Corre con: cd backend && python3 -m pytest tests/test_ultimos_n_anios.py
"""
import math
import os
import random
import re
import sys
import unittest
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import pandas as pd
from fastapi.testclient import TestClient

import backtest
import main
import tecnico
import velas_diarias
from ai import resumen_tecnico_hechos as rh
from fechas import hoy_art_date
from velas_diarias import PERIODO_COMPLETO

LUNES, MIERCOLES, SABADO, DOMINGO = 0, 2, 5, 6
CINCO_ANIOS = timedelta(days=5 * 365 + 10)


def _habiles(desde: date, hasta: date, feriados=()) -> list:
    """Los días de lunes a viernes entre `desde` y `hasta` (los dos incluidos), sin `feriados`."""
    out, d = [], desde
    while d <= hasta:
        if d.weekday() < 5 and d not in feriados:
            out.append(d)
        d += timedelta(days=1)
    return out


def _el_ultimo(dia_semana: int) -> date:
    """El último `dia_semana` (0 = lunes) de hace al menos tres semanas."""
    d = hoy_art_date() - timedelta(days=21)
    while d.weekday() != dia_semana:
        d -= timedelta(days=1)
    return d


def _precio(d: date) -> float:
    """Un precio que cambia todos los días (el mismo día da el mismo precio)."""
    k = d.toordinal()
    return 100 * 1.0004 ** (k - 738000) * (1 + 0.03 * math.sin(k / 9))


class Yahoo:
    """Yahoo en su punto más bajo. `series[ticker]`: {fecha: cierre}. La bajada
    entera trae todo lo de antes de hoy y la del mes, el último mes; lo que no
    está en la serie (un feriado, un papel que dejó de cotizar) no lo trae. Cada
    día abre con el cierre de la víspera, como la bolsa: con la apertura igual al
    cierre, «Una regla» (que compra a la apertura) daba lo mismo que «Una cartera»
    (que arranca al cierre) y la prueba tapaba esa diferencia (auditoría 06/11, H2)."""

    def __init__(self, hoy: date):
        self.hoy, self.series = hoy, {}

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        serie = self.series.get(ticker) or {}
        todos = sorted(d for d in serie if d < self.hoy)
        desde = date.min if period == PERIODO_COMPLETO else self.hoy - timedelta(days=31)
        dias = [d for d in todos if d >= desde]
        if not dias:
            return pd.DataFrame()
        c = [serie[d] for d in dias]
        antes = {d: serie[a] for a, d in zip(todos, todos[1:])}
        o = [antes.get(d, serie[d]) for d in dias]
        return pd.DataFrame({"Open": o, "High": [max(a, b) * 1.01 for a, b in zip(o, c)],
                             "Low": [min(a, b) * 0.99 for a, b in zip(o, c)],
                             "Close": c, "Volume": [1000.0] * len(c)},
                            index=pd.DatetimeIndex([pd.Timestamp(d) for d in dias]))


class LasTresPantallas(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "bond_indices_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"anios-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("main._fetch_cer_series", lambda: {}),
                   mock.patch("main._fetch_uva_series", lambda: {})]
        for p in self._p:
            p.start()
        velas_diarias._a_pedido_hechos.clear()
        # MU es de la persona: la ficha y las pantallas lo bajan a pedido.
        r = self.client.post("/api/brokers", json={"name": "Schwab", "currency": "USD"}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "MU", "quantity": 10,
                                                     "buy_price": 100, "asset_type": "STOCK"}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def tearDown(self):
        for p in self._p:
            p.stop()
        with main.db_abierta() as conn:   # tablas globales (sin user_id)
            for t in ("fx_rates_daily", "bond_indices_daily", "velas_diarias", "velas_estado"):
                conn.execute(f"DELETE FROM {t}")
            conn.commit()

    # ─── ayudas ──────────────────────────────────────────────────────────────

    def _mercado(self, hoy, ultimo, feriados=(), mu=None, indices_hasta=None):
        """Yahoo con MU hasta `ultimo` y el S&P 500 y el Nasdaq hasta `indices_hasta`
        (por defecto, lo mismo), de lunes a viernes sin `feriados`, desde hace 5 años."""
        yahoo = Yahoo(hoy)
        desde = hoy - timedelta(days=5 * 365 + 10)
        mu = mu or _precio
        yahoo.series["MU"] = {d: mu(d) for d in _habiles(desde, ultimo, feriados)}
        for t, f in (("^GSPC", lambda d: 4000 + d.toordinal() % 997), ("^IXIC", lambda d: 12000 + d.toordinal() % 613)):
            yahoo.series[t] = {d: float(f(d)) for d in _habiles(desde, indices_hasta or ultimo, feriados)}
        return yahoo

    @contextmanager
    def _un_dia(self, hoy, yahoo):
        """Todo lo de adentro pasa `hoy` (el día argentino de toda la app), con este Yahoo."""
        with mock.patch("fechas.ahora_art", return_value=datetime(hoy.year, hoy.month, hoy.day, 15, 0)), \
             mock.patch("pricing.yahoo._historia", yahoo):
            yield

    def _get(self, url):
        main._freno_reiniciar()
        r = self.client.get(url, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _las_tres(self, hoy, yahoo, anios):
        """Comparar, «Una cartera» y Una regla, con MU solo al 100 %, ese día."""
        with self._un_dia(hoy, yahoo):
            main._run_velas_diarias_job()   # los índices (y lo que se sigue) los guarda la noche
            return (self._get(f"/api/comparar/precio?activos=MU&moneda=usd&plazo={anios}a"),
                    self._get(f"/api/backtest/cartera?activos=MU&pesos=100&anios={anios}"),
                    self._get(f"/api/tecnico/MU/backtest?reglas=rsi&anios={anios}"))

    @staticmethod
    def _serie(res, clave):
        return next((s for s in res["series"] if s["clave"] == clave), None)

    def _arrancan_igual(self, c, k, b, desde, hasta, mu=_precio):
        """Las tres pantallas, el mismo período (lo que unificó este cambio).
        Comparar y «Una cartera» arrancan además con el MISMO precio (el cierre del
        primer día), así que dan el mismo número. «Una regla» compra a la APERTURA
        del primer día: el precio de arranque es otra regla, y todavía distinta
        (auditoría 06/11, H2); acá se afirma la suya, no que coincida."""
        self.assertEqual((c["base"], c["hasta"]), (desde, hasta), "Comparar")
        self.assertEqual((k["desde"], k["hasta"]), (desde, hasta), "«Una cartera»")
        self.assertEqual((b["desde"], b["hasta"]), (desde, hasta), "Una regla")
        self.assertTrue(k["disponible"] and b["disponible"], (k, b))
        d, h = date.fromisoformat(desde), date.fromisoformat(hasta)
        cierre = mu(h) / mu(d) * 100
        self.assertAlmostEqual(self._serie(c, "MU")["final"], cierre, places=2)
        self.assertAlmostEqual(k["cartera"]["final"], cierre, places=2)
        # La apertura del primer día es el cierre de la rueda anterior (Yahoo, arriba).
        apertura = next(mu(x) for x in (d - timedelta(days=j) for j in range(1, 10)) if x.weekday() < 5)
        self.assertAlmostEqual(b["variacion_precio"], (mu(h) / apertura - 1) * 100, places=6)
        sp = next(i for i in k["indices"] if i["clave"] == "sp500")
        self.assertEqual(self._serie(c, "sp500")["final"], round(sp["final"], 2))

    # ─── H4: el mismo día de arranque ────────────────────────────────────────

    def test_un_domingo_las_tres_arrancan_el_viernes_de_hace_un_anio(self):
        # Antes Comparar arrancaba el sábado de hace un año (hoy − 365): «Cada US$ 100
        # del sábado» con el cierre del viernes, y otra fecha que las otras dos.
        hoy = _el_ultimo(DOMINGO)
        viernes = hoy - timedelta(days=2)
        c, k, b = self._las_tres(hoy, self._mercado(hoy, viernes), 1)
        desde = viernes - timedelta(days=364)
        self.assertEqual(desde.weekday(), 4, "52 semanas antes: también un viernes")
        self._arrancan_igual(c, k, b, desde.isoformat(), viernes.isoformat())

    def test_un_lunes_con_tres_anios_tambien_el_mismo_dia(self):
        # Con 3 años (1.095 días = 156 semanas y 3 días), desde hoy un lunes caía un
        # viernes con rueda: otro precio de arranque, todos los lunes y domingos.
        hoy = _el_ultimo(LUNES)
        viernes = hoy - timedelta(days=3)
        c, k, b = self._las_tres(hoy, self._mercado(hoy, viernes), 3)
        desde = viernes - timedelta(days=3 * 365 - 1)
        self._arrancan_igual(c, k, b, desde.isoformat(), viernes.isoformat())
        self.assertNotEqual(c["base"], (hoy - timedelta(days=3 * 365)).isoformat(), "no desde hoy")

    def test_despues_de_un_feriado_las_tres_arrancan_el_mismo_dia(self):
        # El caso de MU en Pascua de 2026: el viernes, feriado en Nueva York; el último
        # precio es del jueves. Hace un año, el viernes el papel cayó 13 %: contado desde
        # hoy, Comparar arrancaba después de la caída y daba otro número.
        hoy = _el_ultimo(SABADO)
        feriado, jueves = hoy - timedelta(days=1), hoy - timedelta(days=2)
        desde = jueves - timedelta(days=364)
        caida = desde + timedelta(days=1)
        mu = lambda d: _precio(d) * (0.87 if d >= caida else 1.0)
        c, k, b = self._las_tres(hoy, self._mercado(hoy, jueves, feriados={feriado}, mu=mu), 1)
        self._arrancan_igual(c, k, b, desde.isoformat(), jueves.isoformat(), mu=mu)

    # ─── H9: los precios viejos se miden contra hoy ─────────────────────────

    def _ninguna_compara(self, c, k, b, hasta):
        vieja = {"motivo": "vieja", "hasta": hasta}
        self.assertIn({"clave": "MU", **vieja}, c["faltan"], "Comparar")
        self.assertEqual([s for s in c["series"] if s["tipo"] == "activo"], [])
        self.assertEqual((k["disponible"], k["motivo"], k["faltan"]), (False, "vieja", [{"asset": "MU", **vieja}]))
        self.assertEqual((b["disponible"], b["motivo"], b["hasta"]), (False, "vieja", hasta))

    def test_un_activo_solo_que_dejo_de_cotizar_no_entra_en_ninguna(self):
        # Antes, solo, se comparaba con «el último año» terminado hace dos meses, sin
        # avisar (contra él mismo nunca estaba viejo). Junto a otro al día, sí avisaba.
        hoy = _el_ultimo(MIERCOLES)
        ultimo = _habiles(hoy - timedelta(days=66), hoy - timedelta(days=60))[-1]
        c, k, b = self._las_tres(hoy, self._mercado(hoy, ultimo, indices_hasta=hoy - timedelta(days=1)), 1)
        self._ninguna_compara(c, k, b, ultimo.isoformat())

    def test_con_la_noche_caida_mas_de_una_semana_no_se_muestra_lo_viejo_como_de_hoy(self):
        # Lo que se le avisó a Nico al elegir: si Yahoo no trae nada en 9 días, ninguna
        # pantalla compara. Antes mostraban números de hace 9 días como si fueran de hoy.
        hoy = _el_ultimo(MIERCOLES)
        ultimo = hoy - timedelta(days=9)
        c, k, b = self._las_tres(hoy, self._mercado(hoy, ultimo), 1)
        self._ninguna_compara(c, k, b, ultimo.isoformat())

    def test_una_semana_justa_todavia_compara(self):
        # El borde: precios de hace 7 días todavía son «de la última semana».
        hoy = _el_ultimo(MIERCOLES)
        ultimo = hoy - timedelta(days=7)
        c, k, b = self._las_tres(hoy, self._mercado(hoy, ultimo), 1)
        desde = ultimo - timedelta(days=364)
        self._arrancan_igual(c, k, b, desde.isoformat(), ultimo.isoformat())

    # ─── En pesos: la inflación también arranca ese día ──────────────────────

    def test_en_pesos_la_inflacion_arranca_el_dia_del_100(self):
        # El CER lo pide la ruta (vive en main) y el día lo sabe la cuenta: con
        # «1 año» desde el último precio, el día del 100 es el viernes, no el sábado.
        hoy = _el_ultimo(DOMINGO)
        viernes = hoy - timedelta(days=2)
        yahoo = self._mercado(hoy, viernes)
        with main.db_abierta() as conn:
            d = hoy - timedelta(days=5 * 365 + 10)
            while d <= hoy + timedelta(days=30):        # el CER se publica adelantado
                conn.execute("INSERT INTO bond_indices_daily (index_name, date, value, source, updated_at) "
                             "VALUES ('CER', ?, ?, 'test', 'x')", (d.isoformat(), 10 + (d - hoy).days * 0.01))
                if d.weekday() < 5:
                    conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                                 (d.isoformat(), 1500.0, 1300.0))
                d += timedelta(days=1)
            conn.commit()
        with self._un_dia(hoy, yahoo):
            main._run_velas_diarias_job()
            r = self._get("/api/comparar/precio?activos=MU&moneda=ars&plazo=1a")
        desde = (viernes - timedelta(days=364)).isoformat()
        self.assertEqual(r["base"], desde)
        cer = self._serie(r, "cer")
        self.assertIsNotNone(cer, r["faltan"])
        self.assertEqual(cer["puntos"][0], {"d": desde, "v": 100.0})
        self.assertEqual(cer["fecha_final"], viernes.isoformat(), "hasta el último precio, no lo adelantado")


    # ─── Los bordes que propuso la auditoría de las pruebas (06/11) ────────────
    # Cada una dio rojo con un error plantado que las de arriba dejaban pasar: una
    # cuenta propia de «viejo» de 8 días, un índice viejo por poco al lado de un
    # activo al día, varios activos con distinto último día, la vara cortada en el
    # último día de los activos (ver ~/Documents/rendi-archivo/auditoria-regla-n-
    # anios-2026-11-06/pruebas.md).

    def test_ocho_dias_ya_es_vieja_en_las_tres(self):
        # Mata: D5, C11, E8 (una pantalla con su propia cuenta de «viejo» > 8 días,
        # sin `timedelta` ni `DIAS_VIEJA`: el guardián por texto no la ve). Las pruebas
        # tienen 7 días («la semana justa», adentro) y 9 («la noche caída»), no el 8.
        hoy = _el_ultimo(MIERCOLES)
        ultimo = hoy - timedelta(days=8)
        c, k, b = self._las_tres(hoy, self._mercado(hoy, ultimo), 1)
        self._ninguna_compara(c, k, b, ultimo.isoformat())

    def test_un_indice_que_dejo_de_llegar_hace_8_dias_no_va_al_lado_de_un_activo_al_dia(self):
        # Mata: C5 (Comparar) y E4 (Una cartera): el índice viejo medido contra el
        # último precio del activo y no contra hoy. Pasa en producción cuando Yahoo
        # deja de mandar un índice (^MERV, 16/10) o la noche falla y el activo se baja
        # a pedido: el activo es de ayer y el S&P de hace 8 días. Contra el activo son
        # 7 días («de la última semana»); contra hoy, 8: no se dibuja.
        hoy = _el_ultimo(MIERCOLES)
        ayer, indices = hoy - timedelta(days=1), hoy - timedelta(days=8)
        c, k, b = self._las_tres(hoy, self._mercado(hoy, ayer, indices_hasta=indices), 1)
        vieja = {"motivo": "vieja", "hasta": indices.isoformat()}
        self.assertIn({"clave": "sp500", **vieja}, c["faltan"], "Comparar")
        self.assertIsNone(self._serie(c, "sp500"), "Comparar no dibuja el S&P de hace 8 días")
        self.assertIsNotNone(self._serie(c, "MU"))
        self.assertTrue(k["disponible"], k)
        self.assertEqual(k["faltan"], [{"clave": "sp500", **vieja}, {"clave": "nasdaq", **vieja}], "«Una cartera»")
        self.assertEqual(k["indices"], [])
        self.assertTrue(b["disponible"], b)

    def test_un_indice_viejo_que_empieza_unos_dias_despues_no_corre_el_dia_del_100(self):
        # Mata: C3 (Comparar) y E3 (Una cartera): a `dia_del_cien` le llega el último
        # precio en vez de hoy. El S&P empieza dos días después que el activo (el borde
        # de lo guardado) y además dejó de llegar hace 8 días: no corre el día del 100.
        # La prueba de `dia_del_cien` tiene una vara vieja, pero de hace un mes: vieja
        # contra hoy Y contra el último precio; no distingue las dos reglas.
        hoy = _el_ultimo(MIERCOLES)
        ayer, indices = hoy - timedelta(days=1), hoy - timedelta(days=8)
        pedido = ayer - timedelta(days=364)                   # el martes de hace un año
        yahoo = Yahoo(hoy)
        yahoo.series["MU"] = {d: _precio(d) for d in _habiles(pedido, ayer)}
        yahoo.series["^GSPC"] = {d: 4000.0 + d.toordinal() % 997
                                 for d in _habiles(pedido + timedelta(days=2), indices)}
        yahoo.series["^IXIC"] = {d: 12000.0 + d.toordinal() % 613 for d in _habiles(hoy - CINCO_ANIOS, ayer)}
        with self._un_dia(hoy, yahoo):
            main._run_velas_diarias_job()
            c = self._get("/api/comparar/precio?activos=MU&moneda=usd&plazo=1a")
            k = self._get("/api/backtest/cartera?activos=MU&pesos=100&anios=1")
        vieja = {"clave": "sp500", "motivo": "vieja", "hasta": indices.isoformat()}
        self.assertEqual(c["base"], pedido.isoformat(), "Comparar")
        self.assertIn(vieja, c["faltan"])
        self.assertTrue(k["disponible"], k)
        self.assertEqual(k["desde"], pedido.isoformat(), "«Una cartera»")
        self.assertIn(vieja, k["faltan"])

    def test_cripto_y_accion_un_domingo_la_cartera_termina_el_sabado_como_comparar(self):
        # Mata: E7 (Una cartera termina en el activo que llega MENOS lejos). Con una
        # cripto, el último precio es del sábado y el de la acción del viernes: las dos
        # pantallas, el mismo período. Ninguna prueba de fd78a8f3 tiene activos con
        # distinto último día (la de cripto + acción termina las dos el mismo viernes).
        hoy = _el_ultimo(DOMINGO)
        sabado, viernes = hoy - timedelta(days=1), hoy - timedelta(days=2)
        yahoo = self._mercado(hoy, viernes)
        inicio = hoy - CINCO_ANIOS
        yahoo.series["BTC-USD"] = {inicio + timedelta(days=i): 30000.0 + 7 * i + 900 * math.sin(i / 11)
                                   for i in range((sabado - inicio).days + 1)}
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "BTC", "quantity": 1,
                                                     "buy_price": 30000, "asset_type": "CRYPTO"}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)
        with self._un_dia(hoy, yahoo):
            main._run_velas_diarias_job()
            c = self._get("/api/comparar/precio?activos=MU,BTC&moneda=usd&plazo=1a")
            k = self._get("/api/backtest/cartera?activos=MU,BTC&pesos=50,50&anios=1")
        self.assertEqual((c["base"], c["hasta"]), ((sabado - timedelta(days=364)).isoformat(), sabado.isoformat()))
        self.assertTrue(k["disponible"], k)
        self.assertEqual((k["desde"], k["hasta"]), (c["base"], c["hasta"]), "«Una cartera» como Comparar")

    def test_una_cripto_de_hace_7_dias_justos_no_deja_afuera_al_sp_que_esta_al_dia(self):
        # Mata: C6 y C10 (prioridad baja: el borde es angosto). Lo viejo de una vara se
        # mide con lo que llegó hasta HOY, no hasta el último precio de los activos. BTC
        # dejó de llegar hace 7 días justos, un sábado (todavía «de la última semana»), y
        # el S&P está al día. Cortado en ese sábado, el último S&P es el viernes anterior:
        # 8 días, y quedaba afuera por «viejo» estando al día.
        hoy = _el_ultimo(SABADO)
        ultimo_btc = hoy - timedelta(days=7)
        yahoo = self._mercado(hoy, hoy - timedelta(days=1))
        inicio = hoy - CINCO_ANIOS
        yahoo.series["BTC-USD"] = {inicio + timedelta(days=i): 30000.0 + 7 * i + 900 * math.sin(i / 11)
                                   for i in range((ultimo_btc - inicio).days + 1)}
        r = self.client.post("/api/positions", json={"broker": "Schwab", "asset": "BTC", "quantity": 1,
                                                     "buy_price": 30000, "asset_type": "CRYPTO"}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)
        with self._un_dia(hoy, yahoo):
            main._run_velas_diarias_job()
            c = self._get("/api/comparar/precio?activos=BTC&moneda=usd&plazo=1a")
        self.assertEqual(c["hasta"], ultimo_btc.isoformat())
        self.assertIsNotNone(self._serie(c, "sp500"), c["faltan"])


class _YahooQueCuenta(Yahoo):
    """El mismo Yahoo, anotando qué se le pidió."""

    def __init__(self, hoy: date):
        super().__init__(hoy)
        self.pedidos = []

    def __call__(self, ticker, *a, **k):
        self.pedidos.append(ticker)
        return super().__call__(ticker, *a, **k)


class MiCarteraDeHoy(unittest.TestCase):
    """«Mi cartera de hoy» (GET /api/backtest/cartera/hoy) deja afuera lo que no
    tiene precios de la última semana, con LA regla (`tecnico.es_vieja`) y LA
    serie con que después simula «Una cartera», y reparte el resto en su
    proporción. Antes lo dejaba adentro y la simulación rechazaba la cartera
    entera: sacarlo dejaba «Faltan 20%», y «Repartir en partes iguales», 50 y 50
    en vez de 62,5 y 37,5 (auditoría de pantalla 06/11, H3; Nico, 06/11: «Sí,
    así»). Cada caso pide después la simulación de lo que trajo, como la pantalla."""

    def setUp(self):
        self.client = TestClient(main.app)
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "bond_indices_daily"):
                conn.execute(f"DELETE FROM {t}")
            uid = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"hoy-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(uid)}"}
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {}),
                   mock.patch("main._fetch_cer_series", lambda: {}),
                   mock.patch("main._fetch_uva_series", lambda: {})]
        for p in self._p:
            p.start()
        velas_diarias._a_pedido_hechos.clear()
        # Sin último precio guardado, cada lote vale lo que costó: 500, 300 y 200 (50, 30 y 20 %).
        for asset, precio in (("AAPL", 50), ("NVDA", 30), ("MU", 20)):
            self._lote("Schwab", "USD", asset, "STOCK", 10, precio)

    def tearDown(self):
        for p in self._p:
            p.stop()
        with main.db_abierta() as conn:   # tablas globales (sin user_id)
            for t in ("fx_rates_daily", "bond_indices_daily", "velas_diarias", "velas_estado"):
                conn.execute(f"DELETE FROM {t}")
            conn.commit()

    def _lote(self, broker, moneda, asset, tipo, cantidad, precio):
        r = self.client.post("/api/brokers", json={"name": broker, "currency": moneda}, headers=self.h)
        self.assertIn(r.status_code, (200, 400), r.text)
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": cantidad,
                                                     "buy_price": precio, "asset_type": tipo}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _mercado(self, hoy, hasta: dict, indices_hasta=None):
        """Yahoo con cada ticker de `hasta` ({ticker: último día}) y el S&P 500 y el
        Nasdaq hasta `indices_hasta` (por defecto, ayer), de lunes a viernes desde hace 5 años."""
        yahoo = _YahooQueCuenta(hoy)
        desde = hoy - CINCO_ANIOS
        for k, (t, ultimo) in enumerate(sorted(hasta.items())):
            yahoo.series[t] = {d: _precio(d) * (1 + k) for d in _habiles(desde, ultimo)}
        for t, f in (("^GSPC", lambda d: 4000 + d.toordinal() % 997), ("^IXIC", lambda d: 12000 + d.toordinal() % 613)):
            yahoo.series[t] = {d: float(f(d)) for d in _habiles(desde, indices_hasta or hoy - timedelta(days=1))}
        return yahoo

    @contextmanager
    def _un_dia(self, hoy, yahoo):
        with mock.patch("fechas.ahora_art", return_value=datetime(hoy.year, hoy.month, hoy.day, 15, 0)), \
             mock.patch("pricing.yahoo._historia", yahoo):
            yield

    def _get(self, url):
        main._freno_reiniciar()
        r = self.client.get(url, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _simular(self, hoy_):
        """Lo que pide la pantalla con «Mi cartera de hoy» recién traída (`consultaDe`)."""
        activos = ",".join(a["asset"] for a in hoy_["activos"])
        pesos = ",".join(str(a["peso"]) for a in hoy_["activos"])
        local = ",".join(a["asset"] for a in hoy_["activos"] if a["local"])
        return self._get(f"/api/backtest/cartera?activos={activos}&pesos={pesos}&local={local}&anios=1")

    def test_el_que_dejo_de_cotizar_queda_afuera_y_el_resto_va_en_su_proporcion(self):
        hoy = _el_ultimo(MIERCOLES)
        ayer, parado = hoy - timedelta(days=1), hoy - timedelta(days=61)
        with self._un_dia(hoy, self._mercado(hoy, {"AAPL": ayer, "NVDA": ayer, "MU": parado})):
            main._run_velas_diarias_job()
            r = self._get("/api/backtest/cartera/hoy")
            k = self._simular(r)
            mu = self._get("/api/backtest/cartera?activos=MU&pesos=100&anios=1")
        self.assertEqual([(a["asset"], a["peso"]) for a in r["activos"]], [("AAPL", 62.5), ("NVDA", 37.5)])
        self.assertEqual(r["afuera"], [{"asset": "MU", "tipo": "STOCK", "motivo": "vieja", "hasta": parado.isoformat()}])
        self.assertEqual((r["parte"], r["efectivo_o_plazos"]), (80, False))
        # La pantalla la simula de entrada, con tus pesos entre los dos.
        self.assertTrue(k["disponible"], k)
        self.assertEqual([(a["asset"], round(a["peso"], 9)) for a in k["activos"]], [("AAPL", 62.5), ("NVDA", 37.5)])
        # Y lo que dice de MU es lo que dice la simulación de MU: la misma fecha.
        self.assertEqual(mu["faltan"], [{"asset": "MU", "motivo": "vieja", "hasta": parado.isoformat()}])

    def test_con_efectivo_dice_que_lo_hay_sin_decir_cuanto(self):
        # US$ 300 de efectivo, cargados por donde los carga la pantalla: la nota tiene que
        # nombrarlo, o parecía que todo lo que faltaba era MU (revisión 06/11).
        hoy = _el_ultimo(MIERCOLES)
        ayer, parado = hoy - timedelta(days=1), hoy - timedelta(days=61)
        with self._un_dia(hoy, self._mercado(hoy, {"AAPL": ayer, "NVDA": ayer, "MU": parado})):
            r = self.client.post("/api/cash/flow", json={"broker_name": "Schwab", "direction": "deposit", "amount": 300},
                                 headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)
            main._run_velas_diarias_job()
            r = self._get("/api/backtest/cartera/hoy")
        self.assertEqual([(a["asset"], a["peso"]) for a in r["activos"]], [("AAPL", 62.5), ("NVDA", 37.5)])
        self.assertEqual((r["parte"], r["efectivo_o_plazos"]), (62, True))
        self.assertEqual([x["asset"] for x in r["afuera"]], ["MU"])

    def test_una_semana_justa_todavia_entra_y_ocho_dias_ya_no(self):
        # El borde de LA regla, por la ruta: MU de hace 7 días entra; NVDA de hace 8, no.
        hoy = _el_ultimo(MIERCOLES)
        siete, ocho = hoy - timedelta(days=7), hoy - timedelta(days=8)
        with self._un_dia(hoy, self._mercado(hoy, {"AAPL": hoy - timedelta(days=1), "MU": siete, "NVDA": ocho})):
            main._run_velas_diarias_job()
            r = self._get("/api/backtest/cartera/hoy")
            k = self._simular(r)
        self.assertEqual([(a["asset"], a["peso"]) for a in r["activos"]], [("AAPL", 71.4), ("MU", 28.6)])
        self.assertEqual(r["afuera"], [{"asset": "NVDA", "tipo": "STOCK", "motivo": "vieja", "hasta": ocho.isoformat()}])
        self.assertTrue(k["disponible"], k)

    def test_una_accion_argentina_sin_mep_reciente_queda_afuera_como_la_rechaza_la_simulacion(self):
        # LA serie con que se simula tu GGAL de IOL es su precio de BYMA ÷ el MEP de cada
        # día, y una vela sin MEP de la última semana se saltea (`tecnico._convertir`).
        # BYMA llega hasta ayer, pero el MEP dejó de llegar hace 16 días: en dólares, GGAL
        # llega hasta 7 días después del último MEP. Con otra serie, «Mi cartera de hoy»
        # la dejaba adentro y la simulación la rechazaba igual: la fecha de lo GUARDADO
        # (ayer), o el ADR de Nueva York, al día porque otra persona lo tiene en Schwab.
        hoy = _el_ultimo(MIERCOLES)
        ayer, mep = hoy - timedelta(days=1), hoy - timedelta(days=16)
        with main.db_abierta() as conn:
            for d in _habiles(hoy - CINCO_ANIOS, mep):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1500.0, 1300.0))
            otra = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"adr-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        self._lote("IOL", "ARS", "GGAL", "ACCION", 1000, 50)
        mia, self.h = self.h, {"Authorization": f"Bearer {main.create_token(otra)}"}
        self._lote("Schwab", "USD", "GGAL", "STOCK", 10, 30)
        self.h = mia
        yahoo = self._mercado(hoy, {"AAPL": ayer, "NVDA": ayer, "MU": ayer, "GGAL.BA": ayer, "GGAL": ayer})
        with self._un_dia(hoy, yahoo):
            main._run_velas_diarias_job()
            r = self._get("/api/backtest/cartera/hoy")
            k = self._simular(r)
            ggal = self._get("/api/backtest/cartera?activos=GGAL&pesos=100&local=GGAL&anios=1")
        hasta = (mep + timedelta(days=7)).isoformat()
        with main.db_abierta() as conn:
            self.assertEqual((velas_diarias.ultima_fecha(conn, "GGAL.BA"), velas_diarias.ultima_fecha(conn, "GGAL")),
                             (ayer.isoformat(), ayer.isoformat()), "lo guardado, y el ADR, están al día")
        self.assertEqual(ggal["faltan"], [{"asset": "GGAL", "motivo": "vieja", "hasta": hasta}])
        self.assertEqual([x for x in r["afuera"] if x["asset"] == "GGAL"],
                         [{"asset": "GGAL", "tipo": "ACCION", "motivo": "vieja", "hasta": hasta}])
        self.assertEqual([a["asset"] for a in r["activos"]], ["AAPL", "NVDA", "MU"])
        self.assertTrue(k["disponible"], k)

    def test_con_la_noche_caida_no_saca_ninguno_y_la_simulacion_dice_desde_cuando(self):
        # Nada tiene precios de la última semana: sacándolos a todos, la tabla quedaba
        # vacía y decía «Todavía no tenés acciones…». Van todos, como antes, y la
        # simulación dice desde cuándo no hay (lo que ve la persona con H4, 06/11).
        hoy = _el_ultimo(MIERCOLES)
        ultimo = hoy - timedelta(days=9)
        yahoo = self._mercado(hoy, dict.fromkeys(("AAPL", "NVDA", "MU"), ultimo), indices_hasta=ultimo)
        with self._un_dia(hoy, yahoo):
            main._run_velas_diarias_job()
            r = self._get("/api/backtest/cartera/hoy")
            k = self._simular(r)
        self.assertEqual([(a["asset"], a["peso"]) for a in r["activos"]], [("AAPL", 50.0), ("NVDA", 30.0), ("MU", 20.0)])
        self.assertEqual((r["afuera"], r["parte"]), ([], 100))
        self.assertEqual((k["disponible"], k["motivo"]), (False, "vieja"))
        self.assertEqual(sorted((f["asset"], f["hasta"]) for f in k["faltan"]),
                         [(s, ultimo.isoformat()) for s in ("AAPL", "MU", "NVDA")])

    def test_con_la_noche_caida_y_uno_comprado_despues_tampoco_saca_ninguno(self):
        # AMD se compró con la noche caída: sin velas guardadas, no dice que haya alguno al
        # día. Quedaba AMD sola al 100 % y AAPL, NVDA y MU afuera, como si hubieran dejado
        # de cotizar, cuando la falla era nuestra (revisión 06/11).
        hoy = _el_ultimo(MIERCOLES)
        ultimo = hoy - timedelta(days=9)
        yahoo = self._mercado(hoy, {**dict.fromkeys(("AAPL", "NVDA", "MU"), ultimo), "AMD": hoy - timedelta(days=1)},
                              indices_hasta=ultimo)
        with self._un_dia(hoy, yahoo):
            main._run_velas_diarias_job()
            self._lote("Schwab", "USD", "AMD", "STOCK", 10, 10)
            r = self._get("/api/backtest/cartera/hoy")
            k = self._simular(r)
        self.assertEqual([a["asset"] for a in r["activos"]], ["AAPL", "NVDA", "MU", "AMD"])
        self.assertEqual(r["afuera"], [])
        self.assertEqual((k["disponible"], k["motivo"]), (False, "vieja"))
        self.assertEqual(sorted(f["asset"] for f in k["faltan"]), ["AAPL", "MU", "NVDA"])

    def test_lo_que_todavia_no_tiene_precios_no_queda_afuera_y_lo_baja_la_simulacion(self):
        # AMD lo compraste después de la corrida de la noche: no tiene velas guardadas.
        # No es «viejo»: «Mi cartera de hoy» no baja nada (no sale a Yahoo), y la
        # simulación lo baja, como a un activo que nadie sigue.
        hoy = _el_ultimo(MIERCOLES)
        ayer = hoy - timedelta(days=1)
        yahoo = self._mercado(hoy, {"AAPL": ayer, "NVDA": ayer, "MU": ayer, "AMD": ayer})
        with self._un_dia(hoy, yahoo):
            main._run_velas_diarias_job()
            self._lote("Schwab", "USD", "AMD", "STOCK", 10, 10)
            yahoo.pedidos.clear()
            r = self._get("/api/backtest/cartera/hoy")
            self.assertEqual(yahoo.pedidos, [], "«Mi cartera de hoy» no sale a buscar precios")
            k = self._simular(r)
        self.assertIn("AMD", yahoo.pedidos, "la simulación lo bajó")
        self.assertEqual([(a["asset"], a["peso"]) for a in r["activos"]],
                         [("AAPL", 45.4), ("NVDA", 27.3), ("MU", 18.2), ("AMD", 9.1)])
        self.assertEqual(r["afuera"], [])
        self.assertTrue(k["disponible"], k)


class LaRegla(unittest.TestCase):

    def test_el_primer_dia_de_los_ultimos_n_anios(self):
        self.assertEqual(tecnico.primer_dia("2026-11-04", 365), "2025-11-05")
        self.assertEqual(tecnico.primer_dia("2026-04-02", 365), "2025-04-03")      # MU en Pascua
        self.assertEqual(tecnico.primer_dia("2026-11-06", 3 * 365), "2023-11-08")
        self.assertEqual(tecnico.primer_dia("2028-03-01", 365), "2027-03-03")      # con un 29 de febrero
        self.assertEqual(tecnico.primer_dia("2026-11-04", 1), "2026-11-04")

    def test_vieja_es_mas_de_una_semana_contada_desde_hoy(self):
        hoy = date(2026, 11, 5)
        self.assertFalse(tecnico.es_vieja("2026-11-04", hoy))
        self.assertFalse(tecnico.es_vieja("2026-10-29", hoy), "7 días: todavía es de la última semana")
        self.assertTrue(tecnico.es_vieja("2026-10-28", hoy))
        self.assertFalse(tecnico.es_vieja("2026-12-01", hoy), "la UVA se publica adelantada")

    def test_la_ventana_de_la_ficha_es_la_misma_regla(self):
        # `_desde_dias` (el año de la ficha, el gráfico, Bollinger) arranca en el primer
        # día de `primer_dia`, con cualquier calendario: de lunes a viernes, todos los
        # días (una cripto) o con huecos.
        import random
        rnd = random.Random(2026)
        for _ in range(300):
            fin = date(2026, 1, 1) + timedelta(days=rnd.randint(0, 700))
            dias = [fin - timedelta(days=k) for k in range(rnd.randint(1, 900))]
            dias = sorted(d for d in dias if rnd.random() < 0.8 or d == fin)
            velas = [{"date": d.isoformat()} for d in dias]
            n = rnd.choice([20, 30, 365, 730, 1095])
            i = tecnico._desde_dias(velas, n)
            desde = tecnico.primer_dia(fin.isoformat(), n)
            self.assertTrue(all(v["date"] < desde for v in velas[:i]))
            self.assertTrue(all(v["date"] >= desde for v in velas[i:]))


def _viernes_antes(d: date) -> date:
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return d


def _habiles_hasta(fin: date, n: int) -> list:
    out, d = [], fin
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


class LaFichaConLaMismaRegla(unittest.TestCase):
    """La ficha cuenta su año con `primer_dia` y da el mismo resultado: sólo
    `_desde_dias` lo probaba (auditoría de las pruebas 06/11). El borde de las otras:
    el máximo del año justo en su primer día, hace 52 semanas."""

    def test_en_maximo_contra_la_cuenta_a_mano(self):
        # Mata: B2 y B3 (`_en_maximo`, el «máximo del año» de las alertas). La misma
        # regla escrita de la forma más simple, en 200 calendarios al azar.
        rnd = random.Random(611)
        for _ in range(200):
            fin = date(2026, 1, 1) + timedelta(days=rnd.randint(0, 700))
            dias = [fin - timedelta(days=k) for k in range(rnd.randint(380, 800))]
            cal = rnd.choice(("habiles", "todos", "huecos"))
            dias = sorted(d for d in dias if d == fin or (cal == "todos") or (cal == "habiles" and d.weekday() < 5)
                          or (cal == "huecos" and rnd.random() < 0.8))
            precio, cierres = 100.0, []
            for _d in dias:
                precio *= 1 + rnd.gauss(0, 0.015)
                cierres.append(round(precio, 2))
            velas = [{"date": d.isoformat(), "close": c} for d, c in zip(dias, cierres)]
            out = tecnico._en_maximo(velas, cierres, 0)
            for i, v in enumerate(velas):
                desde = tecnico.primer_dia(v["date"], tecnico.DIAS_ANIO)
                if velas[0]["date"] >= desde:
                    self.assertNotIn(i, out, "sin un día antes del año entero, no se sabe")
                    continue
                anio = [c for w, c in zip(velas, cierres) if desde <= w["date"] <= v["date"]]
                self.assertEqual(out[i], cierres[i] >= max(anio) * (1 - tecnico.TOLERANCIA_MAXIMO), (v, cal))

    def test_el_maximo_de_hace_52_semanas_cuenta_para_la_alerta(self):
        # Mata: B3. Un pico de 130 justo el primer día del año (hace 52 semanas) y hoy
        # 110, lo más alto de todo lo demás: NO es el máximo del año, no avisa.
        fin = _viernes_antes(date(2026, 10, 30))
        dias = _habiles_hasta(fin, 600)
        pico = fin - timedelta(days=364)
        v = [{"date": d.isoformat(), "close": 130.0 if d == pico else (110.0 if d == fin else 100.0)} for d in dias]
        self.assertIsNone(tecnico.senal_desde(v, "maximo_12m"))

    def _hoy(self, pico: date, fin: date, precio_hoy: float):
        """Lo que da vuelta HOY (lunes, rueda abierta) con lo guardado hasta el viernes
        `fin`: todo en 100 salvo un cierre de 130 el día `pico`."""
        velas = [{"date": d.isoformat(), "close": 130.0 if d == pico else 100.0} for d in _habiles_hasta(fin, 420)]
        lunes = fin + timedelta(days=3)
        nuevas = [{"d": lunes.isoformat(), "c": precio_hoy, "hoy": True}]
        return [x for x in tecnico.hoy_contra_el_cierre(velas, nuevas, True) if x["senal"] == "maximo_12m"]

    def test_lo_que_da_vuelta_hoy_mira_el_mismo_anio_que_la_lectura(self):
        fin = _viernes_antes(date(2026, 10, 30))
        lunes = fin + timedelta(days=3)
        # Mata: B4 y B7. El 130 fue el viernes de hace 52 semanas: es del año de la
        # lectura del viernes (no estaba en su máximo al cierre) pero ya no del año que
        # termina hoy lunes. 110 hoy es un máximo nuevo: se avisa.
        aviso = self._hoy(fin - timedelta(days=364), fin, 110.0)
        self.assertEqual([(x["pasa_a"], x["dist"]) for x in aviso], [("en_maximo", 10.0)])
        # Mata: B5. El 130 fue el lunes de hace 52 semanas: es el primer día del año que
        # termina hoy. 110 no lo pasa: no se avisa un máximo que no es.
        self.assertEqual(self._hoy(lunes - timedelta(days=364), fin, 110.0), [])

    def test_el_resumen_con_el_maximo_justo_hace_52_semanas(self):
        # Mata: B6. El cierre más alto del año fue su primer día (100); el último, 95,
        # es el más alto de todo lo demás. El resumen ✦ no puede decir «cerró en su
        # precio más alto del año».
        hoy = date(2026, 10, 21)
        dias = [hoy - timedelta(days=419 - i) for i in range(420)]
        desde = hoy - timedelta(days=364)
        cierres = [80.0 if d < desde else 100.0 if d == desde else 95.0 if d == hoy
                   else 85.0 + 3 * math.sin(i / 5) for i, d in enumerate(dias)]
        pts = [{"d": d.isoformat(), "c": c} for d, c in zip(dias, cierres)]
        ficha = {"disponible": True, "moneda": "usd", "puntos": pts,
                 "lectura": {"fecha": hoy.isoformat(), "precio": 95.0},
                 "fibonacci": {"disponible": False, "en_curso": {"dir": "suba", "hasta": {"fecha": hoy.isoformat(), "precio": 95.0},
                                                                 "desde": {"fecha": dias[0].isoformat(), "precio": 80.0}}}}
        h = rh.para_el_resumen(ficha, "Prueba")
        self.assertTrue(h["cierre_mas_alto_del_año"].startswith("100 dólares el "), h["cierre_mas_alto_del_año"])
        self.assertNotIn("más alto del año", h.get("para_el_titular", ""))


class UnaReglaVieja(unittest.TestCase):

    def test_lo_viejo_se_mide_despues_de_sacar_las_velas_rotas(self):
        # Mata: D1. Las últimas velas, rotas (cierre 0): el último precio que sirve es
        # de hace 20 días y eso es lo que se mide. (En producción las velas guardadas
        # ya vienen limpias; `velas_que_sirven` existe por si no.)
        hoy = date(2026, 11, 4)
        buenas = _habiles_hasta(hoy - timedelta(days=20), 400)
        velas = [{"date": d.isoformat(), "open": 100.0 + i % 7, "high": 108.0, "low": 99.0, "close": 100.0 + i % 7}
                 for i, d in enumerate(buenas)]
        velas += [{"date": d.isoformat(), "open": 0, "high": 0, "low": 0, "close": 0}
                  for d in _habiles_hasta(hoy - timedelta(days=1), 13) if d > buenas[-1]]
        r = backtest.probar(velas, ["rsi"], 1, hoy=hoy)
        self.assertEqual((r["disponible"], r["motivo"], r.get("hasta")), (False, "vieja", buenas[-1].isoformat()))


class UnSoloLugar(unittest.TestCase):
    """Las pantallas que comparan precios no cortan «N años» ni miden «vieja» por
    su cuenta: lo hace `tecnico.primer_dia` / `tecnico.es_vieja`. Tres copias de la
    regla fueron tres respuestas distintas para el mismo activo (H4, 05/11)."""

    PANTALLAS = ("comparar.py", "backtest.py", "cartera_simulada.py")

    def test_ninguna_pantalla_tiene_su_copia_de_la_regla(self):
        # Una copia de la regla resta días a una fecha (`timedelta`) o compara contra
        # `DIAS_VIEJA`. `DIAS_ANIO` como LARGO de un año sí vale (llevar a «por año», o
        # «un año entero son 358 días o más» de «Año por año»): no elige ningún día.
        for nombre in self.PANTALLAS:
            with open(os.path.join(BACKEND, nombre), encoding="utf-8") as f:
                fuente = f.read()
            self.assertNotIn("timedelta", fuente, f"{nombre}: las fechas, con tecnico.primer_dia")
            self.assertNotIn("DIAS_VIEJA", fuente, f"{nombre}: lo viejo, con tecnico.es_vieja")
            self.assertIsNone(re.search(r"def _?primer_dia\b|def _?es_viej", fuente), f"{nombre}: otra copia de la regla")

    def test_la_ruta_de_comparar_no_elige_el_dia(self):
        # El día lo elige comparar.comparar, que sabe cuál es el último precio.
        import inspect
        fuente = inspect.getsource(main.get_comparar_precio)
        self.assertNotIn("timedelta", fuente)
        self.assertNotIn("DIAS_ANIO", fuente)


if __name__ == "__main__":
    unittest.main()
