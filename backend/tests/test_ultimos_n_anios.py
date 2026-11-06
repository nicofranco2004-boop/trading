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
«Hoy» es un día de la semana elegido (un domingo, un lunes, el sábado después de
un feriado) de hace unas semanas, contado desde el día en que corre la prueba:
no vence con la fecha. Lo fija `fechas.ahora_art`, de donde sale el día
argentino de toda la app.

Corre con: cd backend && python3 -m pytest tests/test_ultimos_n_anios.py
"""
import math
import os
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

import main
import tecnico
import velas_diarias
from fechas import hoy_art_date
from velas_diarias import PERIODO_COMPLETO

LUNES, MIERCOLES, SABADO, DOMINGO = 0, 2, 5, 6


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

    def test_un_lunes_con_tres_anios_tambien_el_numero(self):
        # Con 3 años (1.095 días = 156 semanas y 3 días), desde hoy un lunes caía un
        # viernes con rueda: otro precio de arranque, todos los lunes y domingos.
        hoy = _el_ultimo(LUNES)
        viernes = hoy - timedelta(days=3)
        c, k, b = self._las_tres(hoy, self._mercado(hoy, viernes), 3)
        desde = viernes - timedelta(days=3 * 365 - 1)
        self._arrancan_igual(c, k, b, desde.isoformat(), viernes.isoformat())
        self.assertNotEqual(c["base"], (hoy - timedelta(days=3 * 365)).isoformat(), "no desde hoy")

    def test_despues_de_un_feriado_el_mismo_numero_en_las_tres(self):
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


class UnSoloLugar(unittest.TestCase):
    """Las pantallas que comparan precios no cortan «N años» ni miden «vieja» por
    su cuenta: lo hace `tecnico.primer_dia` / `tecnico.es_vieja`. Tres copias de la
    regla fueron tres respuestas distintas para el mismo activo (H4, 05/11)."""

    PANTALLAS = ("comparar.py", "backtest.py", "cartera_simulada.py")

    def test_ninguna_pantalla_tiene_su_copia_de_la_regla(self):
        for nombre in self.PANTALLAS:
            with open(os.path.join(BACKEND, nombre), encoding="utf-8") as f:
                fuente = f.read()
            self.assertNotIn("timedelta", fuente, f"{nombre}: las fechas, con tecnico.primer_dia")
            self.assertNotIn("DIAS_VIEJA", fuente, f"{nombre}: lo viejo, con tecnico.es_vieja")
            for linea in fuente.splitlines():
                if re.search(r"\bDIAS_ANIO\b", linea) and not linea.lstrip().startswith("#"):
                    self.assertIn("primer_dia(", linea, f"{nombre}: «N años» sólo por primer_dia: {linea.strip()}")

    def test_la_ruta_de_comparar_no_elige_el_dia(self):
        # El día lo elige comparar.comparar, que sabe cuál es el último precio.
        import inspect
        fuente = inspect.getsource(main.get_comparar_precio)
        self.assertNotIn("timedelta", fuente)
        self.assertNotIn("DIAS_ANIO", fuente)


if __name__ == "__main__":
    unittest.main()
