"""La lectura técnica de la ficha del activo (tecnico.py + GET /api/tecnico).

Entra por el camino de producción: las posiciones se cargan por HTTP, las velas
las guarda el trabajo nocturno real (`main._run_velas_diarias_job`) con Yahoo
reemplazado en su punto más bajo, y la ficha se pide por HTTP. Así se prueba lo
que el usuario va a ver, no una función suelta.

Los casos que importan:
  · las cuentas (media, RSI) dan lo mismo que la referencia de pandas;
  · un CEDEAR se lee en dólares con la acción de afuera y en pesos con el CEDEAR;
  · una acción argentina se lee en dólares dividiendo CADA día por el MEP de
    ESE día (con el de hoy, la tendencia en dólares saldría igual a la de pesos);
  · lo que no tiene velas dice "no disponible", nunca inventa;
  · /admin muestra el estado del guardado y sólo lo ve un admin.

Corre con: cd backend && python3 -m pytest tests/test_tecnico.py
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

import time

import pandas as pd
from fastapi.testclient import TestClient

import main
import estructura
import tecnico
# La de verdad: la suite la reemplaza en cada prueba por una vacía (conftest,
# `_byma_en_memoria_vacio`); acá se toma antes, para probarla a ella.
_DATA912_EN_MEMORIA = getattr(main, "_data912_en_memoria", None)
# Lo mismo con la lectura del contado con liqui de argentinadatos (conftest, `_ccl_sin_red`).
_BAJAR_CCL = getattr(main, "_bajar_ccl", None)
# Y con el cierre del día que anota el servidor de dolarapi (conftest, `_ccl_sin_red`).
_CCL_DE_DOLARAPI = getattr(main, "_ccl_cerrado_de_dolarapi", None)
from fechas import hoy_art_date
import velas_diarias
from velas_diarias import PERIODO_COMPLETO


def _ccl_en_la_cache(medio):
    """El contado con liqui como lo tiene la caché del dólar del servidor
    (`main._fetch_dolar`): las dos puntas, el medio y cuándo lo publicó dolarapi.
    Sin la hora, la regla de «el dólar de ahora» (`tecnico.dolar_de_la_cache`) no
    lo usa: no se sabe si es de hoy."""
    from datetime import datetime, timezone
    return {"compra": medio - 1, "venta": medio + 1, "medio": medio,
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}


def _dt_utc(*a):
    from datetime import datetime
    return datetime(*a)


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
        self.hoy, self.precios, self.pedidos = hoy, {}, []

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        # Los índices se guardan todas las noches (velas_diarias.INDICES: el S&P
        # 500 y el Nasdaq): precio fijo salvo que la prueba le dé otro, y fuera de
        # `pedidos`.
        import velas_diarias
        if ticker not in velas_diarias.INDICES:
            self.pedidos.append((ticker, period, auto_adjust))
        f = self.precios.get(ticker) or ((lambda i, d: 5000.0) if ticker in velas_diarias.INDICES else None)
        if f is None:
            return pd.DataFrame()
        # Yahoo tiene 760 ruedas (~3 años) de cada papel de prueba: menos que lo que
        # pide la bajada completa (5 años), como un papel que cotiza hace poco.
        dias = _ruedas(self.hoy, 760 if period == PERIODO_COMPLETO else 22)
        base = _ruedas(self.hoy, 760)
        filas = {}
        for d in dias:
            c = f(base.index(d), d)
            filas[pd.Timestamp(d)] = (c, c * 1.01, c * 0.99, c, 1000.0)
        idx = sorted(filas)
        o, h, l, c, v = zip(*[filas[k] for k in idx])
        return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v},
                            index=pd.DatetimeIndex(idx))


class CuentasTest(unittest.TestCase):
    """Diferencial contra la referencia: pandas."""

    def test_media_igual_a_pandas(self):
        import random
        random.seed(3)
        xs = [100 + random.gauss(0, 5) for _ in range(400)]
        nuestra = tecnico.media(xs, 200)
        ref = pd.Series(xs).rolling(200).mean().tolist()
        for a, b in zip(nuestra, ref):
            if b != b:   # NaN
                self.assertIsNone(a)
            else:
                self.assertAlmostEqual(a, b, places=9)

    def test_rsi_igual_al_de_wilder(self):
        import random
        random.seed(5)
        xs, x = [], 100.0
        for _ in range(300):
            x *= 1 + random.gauss(0, 0.02)
            xs.append(x)
        nuestro = tecnico.rsi(xs, 14)
        # Wilder = media móvil exponencial con alfa 1/14, arrancando del promedio
        # simple de las primeras 14 (así lo calcula TradingView).
        d = pd.Series(xs).diff()
        sube, baja = d.clip(lower=0), (-d).clip(lower=0)
        s, b = sube[1:15].mean(), baja[1:15].mean()
        ref = [None] * 15
        ref[14] = 100 - 100 / (1 + s / b)
        for i in range(15, len(xs)):
            s = (s * 13 + sube[i]) / 14
            b = (baja[i] + b * 13) / 14
            ref.append(100 - 100 / (1 + s / b))
        for a, r in zip(nuestro[14:], ref[14:]):
            self.assertAlmostEqual(a, r, places=9)
        self.assertTrue(all(v is None for v in nuestro[:14]))

    def test_rsi_igual_al_ejemplo_publicado_de_stockcharts(self):
        # La cuenta de arriba la escribimos nosotros: si los dos entendiéramos mal
        # a Wilder, daría verde igual. Ésta no: son los números PUBLICADOS del
        # ejemplo de manual de StockCharts (ChartSchool, QQQQ dic-2009/ene-2010).
        # Nico, 05/11: «¿es malo el indicador o está mal cómo lo calcula Rendi?».
        cierres = [44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433,
                   46.0826, 45.8931, 46.0328, 45.6140, 46.2820, 46.2820, 46.0028, 46.0328, 46.4116,
                   46.2222, 45.6439, 46.2122, 46.2521, 45.7137, 46.4515, 45.7835, 45.3548, 44.0288,
                   44.1783, 44.2181, 44.5672, 43.4205, 42.6628, 43.1314]
        publicado = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71,
                     50.42, 39.99, 41.46, 41.87, 45.46, 37.30, 33.08, 37.77]
        self.assertEqual([round(x, 2) for x in tecnico.rsi(cierres, 14)[14:]], publicado)

    def test_cruce_del_rsi(self):
        # Vuelve a pasar 30 para arriba hace 2 ruedas.
        r = [None, 40, 35, 28, 25, 27, 31, 33, 34]
        self.assertEqual(tecnico.cruce_rsi(r), {"tipo": "salio_de_abajo", "hace": 2})
        # Baja de 70 en la última rueda.
        self.assertEqual(tecnico.cruce_rsi([60, 72, 75, 69]), {"tipo": "salio_de_arriba", "hace": 0})
        # Entrar a la zona (bajar de 30) no es "salir": no se avisa.
        self.assertIsNone(tecnico.cruce_rsi([40, 35, 29, 25]))
        # Un cruce de hace más de 10 ruedas ya no cuenta.
        self.assertIsNone(tecnico.cruce_rsi([25, 35] + [40] * 12))
        # A4 (auditoría 29/10): pasó 30 para arriba y DESPUÉS volvió a bajar.
        # Vale el último cruce, en cualquier sentido (la regla de `senal_desde`):
        # no se avisa «dejó de caer tan rápido» con el RSI en 24.
        self.assertIsNone(tecnico.cruce_rsi([40, 28, 25, 35, 39, 29, 24]))
        # Lo mismo arriba: bajó de 70 y volvió a pasarlo.
        self.assertIsNone(tecnico.cruce_rsi([60, 75, 68, 66, 72, 74]))

    def test_una_sola_regla_de_alcista(self):
        # P6 (auditoría 29/10): la regla estaba escrita tres veces. Ahora es
        # `tendencia_de`; la lectura la manda resuelta y el diario de operaciones
        # (`tendencia_del_dia`) dice lo mismo el mismo día, también en el borde.
        self.assertEqual(tecnico.tendencia_de(100.0, 100.0), "alcista", "igual al promedio cuenta como arriba")
        self.assertEqual(tecnico.tendencia_de(99.99999999999999, 100.0), "bajista")
        self.assertIsNone(tecnico.tendencia_de(100.0, None))
        cierres = [100 + (i % 7) - 3 + i * 0.01 for i in range(260)]
        velas = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "open": c, "high": c, "low": c,
                  "close": c, "volume": 1} for i, c in enumerate(cierres)]
        m200 = tecnico.media(cierres, 200)
        velas[-1]["close"] = cierres[-1] = m200[-1]          # justo en el promedio
        m200 = tecnico.media(cierres, 200)
        l = tecnico.lectura(velas, m200=m200)
        self.assertEqual(l["tendencia"], tecnico.tendencia_de(cierres[-1], m200[-1]))
        self.assertEqual(l["tendencia"], tecnico.tendencia_del_dia(velas, m200, velas[-1]["date"])["tendencia"])

    def test_rsi_extremos(self):
        sube = [float(i) for i in range(1, 40)]
        self.assertEqual(tecnico.rsi(sube)[-1], 100.0)
        baja = [float(i) for i in range(40, 1, -1)]
        self.assertEqual(tecnico.rsi(baja)[-1], 0.0)

    def test_bollinger_igual_a_tradingview_hecho_con_pandas(self):
        # `ta.bb` de TradingView: promedio de 20 ± 2 desvíos POBLACIONALES
        # (ddof=0); con el desvío muestral de pandas por defecto no da igual.
        import random
        random.seed(9)
        xs, x = [], 100.0
        for _ in range(300):
            x *= 1 + random.gauss(0, 0.02)
            xs.append(x)
        bb = tecnico.bollinger(xs)
        s = pd.Series(xs)
        m, d = s.rolling(20).mean(), s.rolling(20).std(ddof=0)
        for k, nombre, ref in (("media", "media", m), ("arriba", "arriba", m + 2 * d), ("abajo", "abajo", m - 2 * d)):
            for i, (a, b) in enumerate(zip(bb[k], ref.tolist())):
                if b != b:
                    self.assertIsNone(a, f"{nombre} {i}")
                else:
                    self.assertAlmostEqual(a, b, places=9, msg=f"{nombre} {i}")
        self.assertIsNone(bb["arriba"][18])
        self.assertIsNotNone(bb["arriba"][19])

    def test_lectura_de_las_bandas(self):
        # 200 días que van y vienen ±1 y al final un salto: el precio queda
        # arriba de la banda de arriba y las bandas se abren.
        cierres = [100 + (1 if i % 2 else -1) for i in range(200)] + [110]
        velas = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "close": c} for i, c in enumerate(cierres)]
        l = tecnico.lectura(velas)
        bb = tecnico.bollinger(cierres)
        self.assertEqual((l["bb_arriba"], l["bb_abajo"]), (bb["arriba"][-1], bb["abajo"][-1]))
        self.assertGreater(l["bb_posicion"], 1, "cerró arriba de la banda de arriba")
        self.assertGreater(l["bb_ancho_relativo"], 1.5, "las bandas, más anchas que de costumbre")
        # Un ir y venir parejo 99/101: promedio 100, desvío 1, bandas 98 a 102;
        # el último cierre es 101 → posición (101−98)/4 = 0,75. Ancho como siempre.
        quieto = tecnico.lectura(velas[:-1])
        self.assertAlmostEqual(quieto["bb_posicion"], 0.75, places=9)
        self.assertAlmostEqual(quieto["bb_ancho_relativo"], 1.0, places=6)
        # Un precio que no se movió: las bandas no se separan, no hay posición.
        # 10,1 y 0,07 dejan un residuo de redondeo (7e-15) que antes contaba como
        # «bandas separadas» y la tarjeta decía «en el medio» (auditoría 28/10).
        for precio in (50.0, 10.1, 0.07, 1234.56):
            plano = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "close": precio} for i in range(100)]
            self.assertIsNone(tecnico.lectura(plano)["bb_posicion"], precio)
            self.assertIsNone(tecnico.lectura(plano)["bb_ancho_relativo"], precio)
        # Pocos días: sin bandas, sin inventar.
        corto = tecnico.lectura(velas[:15])
        self.assertIsNone(corto["bb_arriba"])
        self.assertIsNone(corto["bb_posicion"])

    def test_cuanto_se_mueve_igual_a_pandas(self):
        import random
        random.seed(21)
        xs, x = [], 100.0
        for _ in range(400):
            x *= 1 + random.gauss(0, 0.02)
            xs.append(x)
        velas = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "close": c} for i, c in enumerate(xs)]
        l = tecnico.lectura(velas)
        cambios = pd.Series(xs).pct_change()
        self.assertAlmostEqual(l["mov_dia"], cambios.iloc[-20:].std(ddof=0) * 100, places=9)
        # El año: los cambios desde la primera vela de los últimos 365 días corridos.
        i_anio = tecnico._desde_dias(velas, 365)
        self.assertAlmostEqual(l["mov_dia_anio"], cambios.iloc[i_anio + 1:].std(ddof=0) * 100, places=9)
        # Un mes: estas velas son de todos los días (como una cripto) → √30.
        self.assertAlmostEqual(l["mov_mes"], l["mov_dia"] * 30 ** 0.5, places=9)
        # Con velas sólo de lunes a viernes, el mes son unos 21 o 22 días de mercado.
        habiles = [v for v in velas if date.fromisoformat(v["date"]).weekday() < 5]
        lh = tecnico.lectura(habiles)
        self.assertIn(round((lh["mov_mes"] / lh["mov_dia"]) ** 2), (21, 22, 23))
        # Ganancia por punto de movimiento (pasado): 12 meses ÷ el año de movimiento.
        hace_un_anio = xs[i_anio - 1]
        self.assertAlmostEqual(l["rend_12m"], (xs[-1] / hace_un_anio - 1) * 100, places=9)
        self.assertAlmostEqual(l["mov_anual"], l["mov_dia_anio"] * (len(xs) - i_anio) ** 0.5, places=9)
        self.assertAlmostEqual(l["rend_por_movimiento"], l["rend_12m"] / l["mov_anual"], places=12)
        # Sin un año completo, no hay relación (no se inventa con medio año).
        self.assertIsNone(tecnico.lectura(velas[:300])["rend_por_movimiento"])
        # Pocos días: no inventa.
        corto = tecnico.lectura(velas[:20])
        self.assertIsNone(corto["mov_dia"])
        self.assertIsNone(corto["mov_mes"])
        self.assertIsNone(tecnico.lectura(velas[:100])["mov_dia_anio"])
        # Un cierre en 0 (vela rota) se saltea, no deja «faltan datos».
        roto = [dict(v) for v in velas]
        roto[-5]["close"] = 0.0
        self.assertIsNotNone(tecnico.lectura(roto)["mov_dia"])
        # Después de un hueco largo, «hace 12 meses» no es una vela de hace años.
        hueco = [{"date": (date(2021, 1, 1) + timedelta(days=i)).isoformat(), "close": 50.0 + i} for i in range(100)] \
            + [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "close": 80.0 + i * 0.1} for i in range(300)]
        self.assertIsNone(tecnico.lectura(hueco)["rend_12m"])
        self.assertIsNone(tecnico.lectura(hueco)["rend_por_movimiento"])
        # Un precio quieto se movió 0, no «sin datos».
        plano = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "close": 50.0} for i in range(60)]
        self.assertEqual(tecnico.lectura(plano)["mov_dia"], 0.0)

    def test_las_bandas_de_la_lectura_dan_igual_sobre_la_cola(self):
        # La lectura sola calcula las bandas sobre los últimos 6 meses; la ficha,
        # sobre toda la historia. Tienen que dar idéntico.
        velas = _velas_al_azar(900, 8)
        completo = tecnico.bollinger([v["close"] for v in velas])
        sola, ficha = tecnico.lectura(velas), tecnico.lectura(velas, bb=completo)
        for k in ("bb_arriba", "bb_abajo", "bb_posicion", "bb_ancho_relativo"):
            self.assertEqual(sola[k], ficha[k], k)

    def test_el_squeeze_usa_las_mismas_bandas(self):
        # Una sola cuenta: con el 2 de verdad (sin el error de LazyBear), «apretado»
        # es exactamente «las bandas de la ficha caben dentro de las de Keltner».
        velas = _velas_al_azar(200, 4)
        hs, ls, cs = tecnico._velas_completas(velas)
        bb = tecnico.bollinger(cs)
        tr = tecnico._rango_verdadero(hs, ls, cs)
        sq = tecnico.squeeze(velas, como_lazybear=False)
        for i in range(20, len(cs)):
            rango = sum(tr[i - 19:i + 1]) / 20
            esperado = bb["abajo"][i] > bb["media"][i] - 1.5 * rango and bb["arriba"][i] < bb["media"][i] + 1.5 * rango
            self.assertEqual(sq["activo"][i], esperado, i)


def _velas_al_azar(n, semilla):
    """Velas con máximo, mínimo y apertura de verdad (no un % fijo del cierre),
    para que el ADX y el Squeeze no salgan triviales."""
    import random
    random.seed(semilla)
    out, c = [], 100.0
    for i in range(n):
        o = c * (1 + random.gauss(0, 0.01))
        c = o * (1 + random.gauss(0.0005, 0.02))
        h = max(o, c) * (1 + abs(random.gauss(0, 0.01)))
        lo = min(o, c) * (1 - abs(random.gauss(0, 0.01)))
        out.append({"date": (date(2024, 1, 1) + timedelta(days=i)).isoformat(), "open": o, "high": h, "low": lo, "close": c})
    return out


def _rma_pandas(s, n):
    """Wilder hecho con pandas: el promedio simple de los primeros n como
    semilla y después `ewm` con alfa 1/n (la definición de `ta.rma`)."""
    s = pd.Series(s, dtype=float).reset_index(drop=True)
    i0 = s.first_valid_index()
    resto = s.iloc[i0 + n - 1:].copy()
    resto.iloc[0] = s.iloc[i0:i0 + n].mean()
    out = pd.Series(float("nan"), index=s.index)
    out.iloc[i0 + n - 1:] = resto.ewm(alpha=1 / n, adjust=False).mean().values
    return out


def _tr_pandas(df):
    c0 = df.close.shift()
    return pd.concat([df.high - df.low, (df.high - c0).abs(), (df.low - c0).abs()], axis=1).max(axis=1, skipna=False)


class FuerzaTest(unittest.TestCase):
    """ADX y Squeeze: diferencial contra una cuenta independiente con pandas
    (como la del RSI), pocas velas y un cruce del ADX armado a mano."""

    def setUp(self):
        self.velas = _velas_al_azar(400, 11)
        self.df = pd.DataFrame(self.velas)

    def _igual(self, nuestra, ref, places=8):
        for k, (a, b) in enumerate(zip(nuestra, ref)):
            if b != b:   # NaN
                self.assertIsNone(a, f"posición {k}")
            else:
                self.assertIsNotNone(a, f"posición {k}")
                self.assertAlmostEqual(a, b, places=places, msg=f"posición {k}")

    def test_adx_igual_al_de_tradingview_hecho_con_pandas(self):
        df = self.df
        sube, baja = df.high.diff(), -df.low.diff()
        dm_mas = sube.where((sube > baja) & (sube > 0), 0.0)
        dm_menos = baja.where((baja > sube) & (baja > 0), 0.0)
        # El primer día: 0, no hueco (en el Pine del script, `na > x` es falso).
        dm_mas.iloc[0] = dm_menos.iloc[0] = 0.0
        atr = _rma_pandas(_tr_pandas(df), 14)
        mas, menos = 100 * _rma_pandas(dm_mas, 14) / atr, 100 * _rma_pandas(dm_menos, 14) / atr
        adx_ref = 100 * _rma_pandas((mas - menos).abs() / (mas + menos), 14)

        nuestro = tecnico.adx(self.velas)
        self._igual(nuestro["di_mas"], mas.tolist())
        self._igual(nuestro["di_menos"], menos.tolist())
        self._igual(nuestro["adx"], adx_ref.tolist())
        # El primer ADX sale en la vela 27: 14 para el +DI/−DI y 14 más para su promedio.
        self.assertIsNone(nuestro["adx"][26])
        self.assertIsNotNone(nuestro["adx"][27])

    def test_squeeze_igual_al_de_lazybear_hecho_con_pandas(self):
        import numpy as np
        df, n = self.df, 20
        c = df.close
        prom = c.rolling(n).mean()
        desvio = 1.5 * c.rolling(n).std(ddof=0)   # el script original usa 1,5 también en las Bollinger
        rango = _tr_pandas(df).rolling(n).mean()
        activo = ((prom - desvio > prom - 1.5 * rango) & (prom + desvio < prom + 1.5 * rango)).where(rango.notna())
        base = c - ((df.high.rolling(n).max() + df.low.rolling(n).min()) / 2 + prom) / 2
        valor = base.rolling(n).apply(lambda w: np.polyval(np.polyfit(np.arange(n), w, 1), n - 1), raw=True)

        nuestro = tecnico.squeeze(self.velas)
        self._igual(nuestro["valor"], valor.tolist())
        for k, (a, b) in enumerate(zip(nuestro["activo"], activo.tolist())):
            self.assertEqual(a, None if b != b else bool(b), f"posición {k}")
        self.assertTrue(any(nuestro["activo"]) and not all(x for x in nuestro["activo"] if x is not None),
                        "el caso tiene días apretados y días sueltos")
        # El color, contra el día anterior.
        v = valor.tolist()
        for k in range(len(v)):
            if v[k] != v[k]:
                self.assertIsNone(nuestro["color"][k])
                continue
            antes = v[k - 1] if v[k - 1] == v[k - 1] else 0.0
            esperado = ("verde_fuerte" if v[k] > antes else "verde_apagado") if v[k] > 0 \
                else ("rojo_fuerte" if v[k] < antes else "rojo_apagado")
            self.assertEqual(nuestro["color"][k], esperado, f"posición {k}")
        self.assertEqual({x for x in nuestro["color"] if x},
                         {"verde_fuerte", "verde_apagado", "rojo_fuerte", "rojo_apagado"})

    def test_squeeze_sin_el_error_de_lazybear_usa_el_2(self):
        a = tecnico.squeeze(self.velas)["activo"]
        b = tecnico.squeeze(self.velas, como_lazybear=False)["activo"]
        # Con Bollinger más anchas (2 en vez de 1,5) hay menos días "apretados".
        self.assertLess(sum(1 for x in b if x), sum(1 for x in a if x))

    def test_squeeze_da_identico_sobre_la_cola_y_sobre_la_historia_entera(self):
        # La ficha lo calcula con toda la historia y la lectura (que la
        # radiografía de la Cartera pide por activo) sobre los últimos 60 días.
        # Tienen que dar el MISMO número, no "casi": el color compara contra el
        # día anterior y en un empate decide el redondeo. Una serie que sube en
        # línea recta da empates exactos en el papel (ahí se rompía).
        recta = [{"date": (date(2024, 1, 1) + timedelta(days=i)).isoformat(), "open": 100 + i * 0.37,
                  "high": (100 + i * 0.37) * 1.01, "low": (100 + i * 0.37) * 0.99, "close": 100 + i * 0.37}
                 for i in range(760)]
        for velas in (self.velas, recta):
            completo = tecnico.squeeze(velas)
            for desde in (len(velas) - tecnico.VELAS_SQUEEZE_LECTURA, len(velas) - 41, 0, 123):
                cola = tecnico.squeeze(velas[desde:])
                for k in ("valor", "color", "activo"):
                    self.assertEqual(cola[k][-1], completo[k][-1], f"{k} desde {desde}")
                    self.assertEqual(cola[k][-2], completo[k][-2], f"{k} anteúltimo desde {desde}")
            # Y la lectura sola (como la pide la Cartera) == la de la ficha.
            dmi = tecnico.adx(velas)
            self.assertEqual(tecnico.lectura(velas), tecnico.lectura(velas, dmi=dmi, sqz=completo))

    def test_precio_quieto_no_inventa_empuje(self):
        # Una acción suspendida: 300 días al mismo precio. El ADX no existe (no
        # hay rango) y el Squeeze es 0, no un residuo de redondeo que la
        # pantalla dibujaba como barras verdes enteras.
        quieto = [{"date": (date(2024, 1, 1) + timedelta(days=i)).isoformat(), "open": 228.97,
                   "high": 228.97, "low": 228.97, "close": 228.97} for i in range(300)]
        self.assertTrue(all(x is None for x in tecnico.adx(quieto)["adx"]))
        s = tecnico.squeeze(quieto)
        self.assertTrue(all(x == 0.0 for x in s["valor"][38:]))
        self.assertEqual(tecnico.lectura(quieto)["squeeze"], 0.0)

    def test_vela_rota_se_completa_como_en_la_pantalla(self):
        # Sin máximo ni mínimo (Yahoo mandó la vela rota): se usan apertura y cierre.
        velas = [dict(v) for v in self.velas]
        velas[100]["high"] = velas[100]["low"] = None
        hs, ls, _ = tecnico._velas_completas(velas)
        self.assertEqual(hs[100], max(velas[100]["open"], velas[100]["close"]))
        self.assertEqual(ls[100], min(velas[100]["open"], velas[100]["close"]))
        self.assertIsNotNone(tecnico.adx(velas)["adx"][-1])

    def test_con_pocas_velas_no_inventa(self):
        pocas = self.velas[:27]
        self.assertTrue(all(x is None for x in tecnico.adx(pocas)["adx"]), "el ADX necesita 28 velas")
        self.assertTrue(all(x is None for x in tecnico.squeeze(self.velas[:38])["valor"]), "el Squeeze necesita 39")
        l = tecnico.lectura(pocas)
        for k in ("adx", "adx_pendiente", "adx_cruce", "squeeze", "squeeze_color"):
            self.assertIsNone(l[k], k)
        self.assertIsNone(tecnico.lectura(self.velas[:20])["squeeze_activo"], "las bandas necesitan 21 días")
        self.assertIsNotNone(l["rsi"], "lo demás sigue")

    def test_cruce_del_adx_armado(self):
        # Dos años de serrucho (sin tendencia: ADX bajísimo) y 12 días de suba
        # firme al final: la fuerza pasa 23 en el anteúltimo día, con el Squeeze
        # en verde.
        N = 760

        def f(i):
            return 100 * (1.01 if i % 2 else 0.99) if i < N - 12 else 100 * 1.02 ** (i - N + 13)

        velas = [{"date": (date(2024, 1, 1) + timedelta(days=i)).isoformat(), "open": f(i), "high": f(i) * 1.01, "low": f(i) * 0.99, "close": f(i)}
                 for i in range(N)]
        a = tecnico.adx(velas)["adx"]
        self.assertLess(a[-3], tecnico.ADX_CLAVE)
        self.assertGreaterEqual(a[-2], tecnico.ADX_CLAVE)
        l = tecnico.lectura(velas)
        self.assertEqual(l["adx_cruce"], {"tipo": "paso_arriba", "hace": 1, "squeeze": 1})
        self.assertAlmostEqual(l["adx_pendiente"], a[-1] - a[-4], places=12, msg="el cambio de los últimos 3 días")
        self.assertEqual(l["squeeze_color"], "verde_fuerte")
        # La bajada espejo: el cruce viene con el Squeeze en rojo.
        espejo = [{"date": v["date"], "open": 1e4 / v["open"], "high": 1e4 / v["low"],
                   "low": 1e4 / v["high"], "close": 1e4 / v["close"]} for v in velas]
        self.assertEqual(tecnico.lectura(espejo)["adx_cruce"]["squeeze"], -1)

    def test_cruces_del_adx(self):
        # El signo del Squeeze es el del DÍA DEL CRUCE (rojo), no el de hoy (verde).
        self.assertEqual(tecnico.cruce_adx([None, 18, 21, 24, 26], [0, 0, 0, -2, 3]),
                         {"tipo": "paso_arriba", "hace": 1, "squeeze": -1})
        # Mira exactamente los últimos 10 días de mercado (hace 0 a 9).
        self.assertEqual(tecnico.cruce_adx([20, 25] + [30] * 9)["hace"], 9)
        self.assertIsNone(tecnico.cruce_adx([20, 25] + [30] * 10))
        self.assertEqual(tecnico.cruce_adx([30, 25, 22]), {"tipo": "paso_abajo", "hace": 0, "squeeze": None})
        self.assertIsNone(tecnico.cruce_adx([20, 25] + [30] * 12), "un cruce de hace más de 10 días ya no cuenta")
        self.assertIsNone(tecnico.cruce_adx([30] * 20))


class FichaTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily", "bond_indices_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"tec-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier, is_admin) "
                "VALUES (?, 'x', 1, 1, 'pro', 1)", (f"tec-adm-{tag}@rendi.test",))
            self.admin = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.h_admin = {"Authorization": f"Bearer {main.create_token(self.admin)}"}
        self.hoy = hoy_art_date()
        self.dias = _ruedas(self.hoy, 760)
        self.yahoo = YahooFalso(self.hoy)
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   # La corrida nocturna también arma la lista de cambios de ratio,
                   # que le pregunta a Yahoo sus splits y a data912 la historia:
                   # sin red, la prueba da lo mismo todos los días.
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        # El cupo de la hora de las fichas a pedido vive en memoria: cada
        # prueba arranca con la hora vacía.
        import velas_diarias
        velas_diarias._a_pedido_hechos.clear()

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

    def _mep(self, f):
        """Un MEP por día: `f(i)` para la rueda i, más fines de semana con el
        del viernes (como la tabla real, que tiene huecos)."""
        with main.db_abierta() as conn:
            for i, d in enumerate(self.dias):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), f(i) * 1.1, f(i)))
            conn.commit()

    def _ficha(self, asset, moneda="usd", h=None, local=False):
        r = self.client.get(f"/api/tecnico/{asset}?moneda={moneda}{'&local=1' if local else ''}",
                            headers=h or self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _ccl(self, f, desde=0):
        """El contado con liqui de cada día guardado como lo guarda la app
        (`main._actualizar_ccl`, con la fuente reemplazada): `f(i)` el de la rueda
        i, desde la rueda `desde`, con compra y venta alrededor (el medio es f(i))."""
        filas = [(d.isoformat(), f(i) - 5, f(i) + 5) for i, d in enumerate(self.dias) if i >= desde]
        with mock.patch("main._bajar_ccl", lambda: filas):
            return main._actualizar_ccl()

    def test_cedear_en_dolares_y_en_pesos(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AAPL", "CEDEAR")
        # Afuera, Apple baja de 300 a ~225; el CEDEAR en pesos SUBE porque el
        # dólar sube más rápido: la misma acción, dos tendencias.
        self.yahoo.precios["AAPL"] = lambda i, d: 300 - i * 0.1
        self.yahoo.precios["AAPL.BA"] = lambda i, d: (300 - i * 0.1) * (1000 + i * 2) / 20
        main._run_velas_diarias_job()

        usd = self._ficha("AAPL", "usd")
        self.assertTrue(usd["disponible"])
        self.assertEqual(usd["ticker"], "AAPL")
        self.assertIsNone(usd["convertida"])
        self.assertLess(usd["lectura"]["dist_media200"], 0, "en dólares está debajo de su media")
        self.assertLess(usd["lectura"]["pendiente_media200"], 0)
        # Todo lo guardado, cortado por CALENDARIO (no una cantidad fija de velas).
        piso = (self.dias[-1] - timedelta(days=tecnico.DIAS_GRAFICO)).isoformat()
        self.assertEqual(len(usd["puntos"]), sum(1 for d in self.dias if d.isoformat() > piso))
        # La media de 200 se calcula con TODA la historia: la de hace 2 años ya
        # tiene sus 200 días anteriores; la del primer día guardado no, y no se inventa.
        hace2 = (self.dias[-1] - timedelta(days=2 * tecnico.DIAS_ANIO)).isoformat()
        i2 = next(i for i, p in enumerate(usd["puntos"]) if p["d"] > hace2)
        self.assertIsNotNone(usd["puntos"][i2]["s200"],
                             "la media de 200 de hace 2 años se calcula con la historia anterior")
        self.assertIsNone(usd["puntos"][0]["s200"], "sin 200 días antes, no hay media de 200")

        ars = self._ficha("AAPL", "ars")
        self.assertEqual(ars["ticker"], "AAPL.BA")
        self.assertGreater(ars["lectura"]["dist_media200"], 0, "en pesos parece alcista")

    def test_accion_argentina_en_dolares_con_el_mep_de_cada_dia(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        self._mep(lambda i: 1000 + i)                    # el dólar sube todos los días
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 + i * 5
        main._run_velas_diarias_job()

        f = self._ficha("GGAL", "usd")
        self.assertEqual(f["ticker"], "GGAL.BA")
        self.assertEqual(f["convertida"], "mep")
        ultimo = len(self.dias) - 1
        esperado = (5000 + ultimo * 5) / (1000 + ultimo)
        self.assertAlmostEqual(f["puntos"][-1]["c"], esperado, places=3)
        # La vela entera viaja convertida con el MISMO dólar del día (gráfico de velas).
        self.assertAlmostEqual(f["puntos"][-1]["h"], esperado * 1.01, places=3)
        self.assertAlmostEqual(f["puntos"][-1]["l"], esperado * 0.99, places=3)
        self.assertAlmostEqual(f["puntos"][-1]["o"], esperado, places=3)
        # El volumen del día viaja con la vela (las barras de abajo del gráfico).
        self.assertEqual(f["puntos"][-1]["v"], 1000.0)
        piso = (self.dias[-1] - timedelta(days=tecnico.DIAS_GRAFICO)).isoformat()
        primero = next(i for i, d in enumerate(self.dias) if d.isoformat() > piso)
        self.assertAlmostEqual(f["puntos"][0]["c"], (5000 + primero * 5) / (1000 + primero), places=3,
                               msg="cada día con SU dólar, no con el de hoy")

        p = self._ficha("GGAL", "ars")
        self.assertIsNone(p["convertida"])
        self.assertAlmostEqual(p["puntos"][-1]["c"], 5000 + ultimo * 5, places=3)

    def test_accion_local_no_usa_el_adr_de_otro_usuario(self):
        # Alguien tiene el ADR de Galicia en Schwab (10 acciones, ~US$ 50) y
        # vos tenés la acción local: tu ficha en dólares tiene que ser TU acción.
        with main.db_abierta() as conn:   # dos brokers: plan Pro
            conn.execute("UPDATE users SET tier='pro' WHERE id=?", (self.uid,))
            conn.commit()
        self._broker("IOL", "ARS")
        self._broker("Schwab", "USD")
        self._posicion("IOL", "GGAL", "ACCION")
        self._posicion("Schwab", "GGAL", "STOCK")
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        main._run_velas_diarias_job()
        r = self.client.get("/api/tecnico/GGAL?moneda=usd&local=1", headers=self.h).json()
        self.assertEqual((r["ticker"], r["convertida"]), ("GGAL.BA", "mep"))
        self.assertAlmostEqual(r["puntos"][-1]["c"], 5.0, places=6)
        adr = self.client.get("/api/tecnico/GGAL?moneda=usd", headers=self.h).json()
        self.assertEqual(adr["ticker"], "GGAL", "sin la marca, el ADR (lo que tiene el de Schwab)")

    def test_sin_dolar_ese_dia_no_se_inventa(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        # Sólo hay dólar para los últimos 100 días.
        with main.db_abierta() as conn:
            for d in self.dias[-100:]:
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1100.0, 1000.0))
            conn.commit()
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        main._run_velas_diarias_job()
        f = self._ficha("GGAL", "usd")
        self.assertEqual(f["puntos"][0]["d"], self.dias[-100].isoformat())
        self.assertEqual(f["lectura"]["ruedas"], 100)
        self.assertIsNone(f["lectura"]["media200"], "con 100 ruedas no hay media de 200")

    def test_rsi_que_salio_de_abajo_y_volvio_a_caer(self):
        # A4 por el camino de la ficha (GET /api/tecnico/KO): el RSI baja de 30,
        # sube a 39 dos días y vuelve a caer a ~24. La tarjeta dice «Cayó muy
        # rápido»: el aviso de abajo no puede decir «dejó de caer tan rápido».
        n = len(self.dias)
        c = [100 + i * 0.05 + (1 if i % 2 else -0.8) for i in range(n - 19)]
        x = c[-1]
        for paso, veces in ((-3, 12), (6, 2), (-4, 5)):
            for _ in range(veces):
                x += paso
                c.append(x)
        self.yahoo.precios["KO"] = lambda i, d: c[i]
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "KO", "STOCK")
        main._run_velas_diarias_job()
        l = self._ficha("KO")["lectura"]
        self.assertLess(l["rsi"], 30, "la prueba necesita el RSI abajo de 30 hoy")
        self.assertIsNone(l["rsi_cruce"])

    def test_accion_local_sin_su_serie_no_cambia_de_papel(self):
        # Re-test A1d (29/10): otra persona tiene el ADR de GGAL (se guarda
        # «GGAL»), y la serie de BYMA (GGAL.BA) todavía no está. Pedida como
        # acción argentina (local), la ficha leía el ADR sin avisar: otro papel.
        # Sin su serie, no hay lectura; nunca la de otro papel.
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "GGAL", "STOCK")
        self.yahoo.precios["GGAL"] = lambda i, d: 30 + i * 0.01
        main._run_velas_diarias_job()
        self.assertFalse(self._ficha("GGAL", local=True)["disponible"])
        self.assertFalse(self._ficha("GGAL", moneda="ars", local=True)["disponible"])
        self.assertTrue(self._ficha("GGAL")["disponible"], "el ADR, pedido como ADR, sí")

    def test_bono_y_lo_que_no_tiene_velas(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AL30", "BONO")
        main._run_velas_diarias_job()
        self.assertFalse(self._ficha("AL30")["disponible"])
        self.assertFalse(self._ficha("ZZZZ")["disponible"])
        r = self.client.get("/api/tecnico/<script>", headers=self.h)
        self.assertIn(r.status_code, (400, 404))

    def test_fuerza_de_la_tendencia_llega_a_la_ficha(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AAPL", "CEDEAR")
        self.yahoo.precios["AAPL"] = lambda i, d: 100 * (1.01 if i % 2 else 0.99) if i < 748 else 100 * 1.02 ** (i - 747)
        main._run_velas_diarias_job()
        f = self._ficha("AAPL", "usd")
        p = f["puntos"][-1]
        self.assertIsNotNone(p["adx"])
        # Cada punto del gráfico lleva el ADX y el Squeeze de la historia ENTERA
        # guardada, el de SU día: no los de la ventana dibujada (el ADX arrastra
        # memoria) ni corridos un día. Desde d6ae4dc3 el gráfico trae toda la
        # historia guardada (arranca en la primera vela), así que se mira que cada punto,
        # también los de más adelante, siga siendo el de la historia entera.
        with main.db_abierta() as conn:
            velas = tecnico.serie(conn, "AAPL", "usd")["velas"]
        d, s = tecnico.adx(velas), tecnico.squeeze(velas)
        b = tecnico.bollinger([v["close"] for v in velas])
        por_dia = {v["date"]: i for i, v in enumerate(velas)}
        # Desde ficha-tecnica `DIAS_GRAFICO = DIAS_GUARDADOS`: el gráfico lleva
        # TODA la historia guardada (antes arrancaba después de 200 días).
        self.assertEqual(por_dia[f["puntos"][0]["d"]], 0, "el gráfico lleva toda la historia")
        self.assertEqual(len(f["puntos"]), len(velas), "el gráfico trae toda la historia guardada")
        self.assertIsNone(f["puntos"][0]["adx"], "en la primera vela el ADX todavía no tiene memoria")
        for q in f["puntos"]:
            i = por_dia[q["d"]]
            self.assertEqual(q["adx"], round(d["adx"][i], 2) if d["adx"][i] is not None else None, q["d"])
            self.assertEqual(q["squeeze"], float(f"{s['valor'][i]:.6g}") if s["valor"][i] is not None else None, q["d"])
            self.assertEqual(q["squeeze_color"], s["color"][i], q["d"])
            for k in ("arriba", "abajo"):
                esperado = estructura.precio_redondo(b[k][i])
                self.assertEqual(q[f"bb_{k}"], esperado, q["d"])
        self.assertIsNotNone(p["squeeze"])
        self.assertEqual(p["squeeze_color"], f["lectura"]["squeeze_color"])
        self.assertAlmostEqual(p["adx"], f["lectura"]["adx"], places=2)
        self.assertEqual(f["lectura"]["adx_cruce"]["tipo"], "paso_arriba")
        self.assertEqual(f["lectura"]["adx_cruce"]["squeeze"], 1)

    def test_fuerza_con_pocos_dias_no_inventa(self):
        # Una acción argentina con dólar sólo para los últimos 25 días: 25 velas
        # en dólares. El ADX necesita 28 y el Squeeze 39: van vacíos, no en 0.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        with main.db_abierta() as conn:
            for d in self.dias[-25:]:
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1100.0, 1000.0))
            conn.commit()
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0 + (i % 7) * 30
        main._run_velas_diarias_job()
        f = self._ficha("GGAL", "usd")
        self.assertEqual(f["lectura"]["ruedas"], 25)
        self.assertTrue(all(p["adx"] is None and p["squeeze"] is None and p["squeeze_color"] is None
                            for p in f["puntos"]))
        for k in ("adx", "adx_cruce", "squeeze", "squeeze_color"):
            self.assertIsNone(f["lectura"][k], k)
        # Si las bandas están "apretadas" sí se sabe con 21 días (las bandas
        # son de 20): es un dato real, no inventado.
        self.assertIn(f["lectura"]["squeeze_activo"], (True, False))

    def test_admin_ve_el_estado_y_el_usuario_no(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self._posicion("Schwab", "NOEXISTE", "STOCK")
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        r = self.client.get("/api/admin/velas", headers=self.h)
        self.assertIn(r.status_code, (401, 403))

        antes = self.client.get("/api/admin/velas", headers=self.h_admin).json()
        self.assertEqual(antes["activos"], 0)
        main._run_velas_diarias_job()
        e = self.client.get("/api/admin/velas", headers=self.h_admin).json()
        # MSFT, NOEXISTE y los índices (que se guardan siempre).
        self.assertEqual((e["activos"], e["ok"]), (2 + len(velas_diarias.INDICES), 1 + len(velas_diarias.INDICES)))
        self.assertEqual([f["symbol"] for f in e["fallados"]], ["NOEXISTE"])
        self.assertEqual(e["filas"], (1 + len(velas_diarias.INDICES)) * 760)
        self.assertEqual(e["hasta"], self.dias[-1].isoformat())
        self.assertFalse(e["corriendo"])

    def test_el_boton_no_arranca_dos_corridas(self):
        main._tomar_corrida("velas_diarias")
        try:
            r = self.client.post("/api/admin/velas/correr", headers=self.h_admin)
            self.assertEqual(r.json()["status"], "already_running")
            # Y la de la foto diaria también se saltea mientras tanto.
            with mock.patch("velas_diarias.correr") as correr:
                main._run_velas_diarias_job()
            correr.assert_not_called()
        finally:
            main._soltar_corrida("velas_diarias")


    def test_cripto_de_fracciones_de_centavo_no_llega_en_cero(self):
        # SHIB vale US$ 0,00001: con 4 decimales fijos el gráfico entero llegaba
        # en 0 («último cierre US$ 0»). Abajo de 1 van 6 cifras significativas;
        # arriba de 1, los 4 decimales de siempre.
        self._broker("Binance", "USDT")
        self._posicion("Binance", "SHIB", "CRYPTO")
        self.yahoo.precios["SHIB-USD"] = lambda i, d: 0.0000123456 * (1 + i * 0.001)
        main._run_velas_diarias_job()
        f = self._ficha("SHIB")
        self.assertTrue(f["disponible"])
        ultimo = f["puntos"][-1]
        esperado = f["lectura"]["precio"]
        for k in ("o", "c", "s50", "s200"):
            self.assertGreater(ultimo[k], 0, k)
        self.assertAlmostEqual(ultimo["c"] / esperado, 1, places=5)
        self.assertAlmostEqual(ultimo["h"] / (esperado * 1.01), 1, places=5)
        self.assertEqual(len({p["c"] for p in f["puntos"]}), len(f["puntos"]), "cada día con su precio, no todos iguales")

    def test_cripto_el_anio_son_365_dias(self):
        # Bitcoin cotiza los 7 días: 252 velas son 8 meses. El máximo "del año"
        # tiene que mirar 12 meses de calendario.
        self._broker("Binance", "USDT")
        self._posicion("Binance", "BTC", "CRYPTO")
        hoy = self.hoy
        # Todos los días, y más de lo que se guarda: la poda corta el principio.
        dias = [hoy - timedelta(days=k) for k in range(tecnico.DIAS_GRAFICO + 60, 0, -1)]
        pico = hoy - timedelta(days=300)                               # hace 10 meses

        def btc(ticker, period, interval, auto_adjust, timeout):
            idx = [pd.Timestamp(d) for d in dias]
            c = [120000.0 if d == pico else 80000.0 for d in dias]
            return pd.DataFrame({"Open": c, "High": c, "Low": c, "Close": c, "Volume": [1.0] * len(c)},
                                index=pd.DatetimeIndex(idx))
        with mock.patch("pricing.yahoo._historia", btc):
            main._run_velas_diarias_job()
        f = self._ficha("BTC")
        self.assertEqual(f["lectura"]["maximo_12m"], 120000.0, "el pico de hace 10 meses es del año")
        self.assertAlmostEqual(f["lectura"]["dist_maximo_12m"], -33.33, places=1)
        # El gráfico trae todo lo guardado: 5 años de CALENDARIO, no 5 × 252 velas.
        self.assertGreater(f["puntos"][0]["d"], (hoy - timedelta(days=tecnico.DIAS_GRAFICO + 1)).isoformat())
        self.assertLess(f["puntos"][0]["d"], (hoy - timedelta(days=5 * 365)).isoformat(), "5 años de calendario")

    def test_cedear_en_pesos_sin_el_escalon_del_cambio_de_ratio(self):
        # El 5/12 BYMA pasa XLE de un ratio a otro el doble: el CEDEAR en pesos
        # cae 50 % ese día mientras afuera no se mueve. Yahoo no lo corrige.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "XLE", "CEDEAR")
        cambio = len(self.dias) - 200
        self.yahoo.precios["XLE"] = lambda i, d: 90.0
        self.yahoo.precios["XLE.BA"] = lambda i, d: 9000.0 if i < cambio else 4500.0
        main._run_velas_diarias_job()
        ars = self._ficha("XLE", "ars")
        cierres = {p["c"] for p in ars["puntos"]}
        self.assertEqual(cierres, {4500.0}, "toda la historia en la escala nueva, sin caída falsa")
        self.assertAlmostEqual(ars["lectura"]["dist_media200"], 0.0, places=6)

    def test_precio_roto_de_un_dia_se_saca(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "ETHA", "CEDEAR")
        roto = len(self.dias) - 10
        self.yahoo.precios["ETHA"] = lambda i, d: 20.0
        self.yahoo.precios["ETHA.BA"] = lambda i, d: 6810.0 if i == roto else 19650.0
        main._run_velas_diarias_job()
        ars = self._ficha("ETHA", "ars")
        self.assertNotIn(6810.0, {p["c"] for p in ars["puntos"]})
        self.assertNotIn(self.dias[roto].isoformat(), {p["d"] for p in ars["puntos"]})

    def test_dia_sin_mep_usa_el_ultimo_mep_como_el_resto_de_la_app(self):
        self._broker("IOL", "ARS")
        self._posicion("IOL", "GGAL", "ACCION")
        self._mep(lambda i: 1000.0)
        hueco = self.dias[-3].isoformat()
        with main.db_abierta() as conn:   # ese día hay blue (1.100) pero no MEP
            conn.execute("UPDATE fx_rates_daily SET mep_venta=NULL WHERE date=?", (hueco,))
            conn.commit()
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        main._run_velas_diarias_job()
        f = self._ficha("GGAL", "usd", local=True)
        punto = next(p for p in f["puntos"] if p["d"] == hueco)
        self.assertAlmostEqual(punto["c"], 5.0, places=6, msg="con el MEP de antes, no con el blue de ese día")
        import fx
        with main.db_abierta() as conn:
            self.assertEqual(fx.fx_for_date(conn, hueco), 1000.0)

    def test_acciones_con_clase_se_piden_con_guion(self):
        import velas_diarias
        self.assertEqual(velas_diarias.ticker_de_afuera("BRK.B"), "BRK-B")
        self.assertEqual(velas_diarias.ticker_de_afuera("AAPL"), "AAPL")
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "BRK.B", "STOCK")
        self.yahoo.precios["BRK-B"] = lambda i, d: 480.0
        main._run_velas_diarias_job()
        f = self._ficha("BRK.B")
        self.assertTrue(f["disponible"])
        self.assertEqual(f["ticker"], "BRK-B")

    # Disney es DISN en BYMA y DIS en Nueva York; Berkshire, BRKB y BRK-B; Nokia,
    # NOKA y NOK. Con el código de BYMA Yahoo no tiene la acción de afuera: la
    # noche pedía «DISN», que no existe, y la ficha en dólares era el CEDEAR en
    # pesos ÷ el MEP, con el DISN.BA de Yahoo días enteros clavado en 10.416
    # (auditoría del backtesting, 05/11, H8).
    CODIGO_DE_BYMA = (("DISN", "DIS"), ("BRKB", "BRK-B"), ("NOKA", "NOK"))

    def test_cedear_con_otro_codigo_en_nueva_york(self):
        self._broker("IOL", "ARS")
        self._mep(lambda i: 1000.0)
        for byma, ny in self.CODIGO_DE_BYMA:
            self._posicion("IOL", byma, "CEDEAR")
            self.yahoo.precios[ny] = lambda i, d: 100 + i * 0.1
            self.yahoo.precios[f"{byma}.BA"] = lambda i, d: 10416.0
        main._run_velas_diarias_job()
        for byma, ny in self.CODIGO_DE_BYMA:
            with self.subTest(byma):
                self.assertEqual(self._pedidos(byma), [], "a Yahoo no se le pide un código que no tiene")
                self.assertIn((ny, PERIODO_COMPLETO, False), self._pedidos(ny))
                usd = self._ficha(byma, "usd")
                self.assertEqual((usd["ticker"], usd["convertida"]), (ny, None))
                self.assertEqual(usd["puntos"][-1]["c"], 175.9, "la acción de Nueva York, no 10.416 ÷ el MEP")
                ars = self._ficha(byma, "ars")
                self.assertEqual((ars["ticker"], ars["convertida"]), (f"{byma}.BA", None))

    def test_un_salto_sin_decidir_no_pasa_la_ficha_en_pesos_a_la_accion_entera(self):
        # El CEDEAR en pesos cae a la mitad hace 4 ruedas y la acción de afuera no se
        # mueve: la lista de cambios de ratio todavía no lo decide (`pendientes`) y
        # esconde esos días. La serie GUARDADA está al día: no es «atrasada». Antes, a
        # los `DIAS_ATRASO` días la ficha en pesos pasaba a la acción de afuera × el
        # MEP, que es la acción ENTERA en pesos (el CEDEAR × su ratio): ~20 veces más.
        # Con 4 ruedas escondidas eso pasa cuando hay un fin de semana en el medio
        # (el DISN simulado del 05/11: 6 días); con 3 de tope pasa cualquier día.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "XLE", "CEDEAR")
        self._mep(lambda i: 1000.0)
        n = len(self.dias)
        self.yahoo.precios["XLE"] = lambda i, d: 90.0
        self.yahoo.precios["XLE.BA"] = lambda i, d: 4500.0 if i < n - 4 else 2250.0
        main._run_velas_diarias_job()
        with mock.patch("tecnico.DIAS_ATRASO", 3):
            ars = self._ficha("XLE", "ars")
        self.assertEqual((ars["ticker"], ars["convertida"]), ("XLE.BA", None))
        self.assertEqual(ars["puntos"][-1]["d"], self.dias[n - 5].isoformat(), "hasta el día antes del salto")
        self.assertEqual(ars["puntos"][-1]["c"], 4500.0)

    def test_cedear_con_otro_codigo_a_pedido(self):
        # Nadie tiene Nokia: la ficha la baja en el momento, como NOK.
        self.yahoo.precios["NOK"] = lambda i, d: 4 + i * 0.001
        main._run_velas_diarias_job()
        for asset in ("NOKA", "NOKA.BA"):
            with self.subTest(asset):
                f = self._ficha(asset)
                self.assertTrue(f["disponible"])
                self.assertEqual(f["ticker"], "NOK")
        self.assertEqual(self._pedidos("NOKA"), [])
        self.assertEqual(self._pedidos("NOK"), [("NOK", PERIODO_COMPLETO, False)])

    def test_watchlist_acepta_acciones_con_clase(self):
        # El mapa del S&P manda BRK-B; la estrella de su ficha fallaba siempre
        # porque la watchlist sólo aceptaba letras con '.BA' o '-USD'.
        for t in ("BRK-B", "brk.b"):
            r = self.client.post("/api/watchlist", json={"symbol": t}, headers=self.h)
            self.assertEqual(r.status_code, 200, r.text)
        items = self.client.get("/api/watchlist", headers=self.h).json()["items"]
        self.assertEqual([i["symbol"] for i in items], ["BRK-B"], "una sola, con guión")
        self.yahoo.precios["BRK-B"] = lambda i, d: 480.0
        main._run_velas_diarias_job()
        self.assertIn(("BRK-B", PERIODO_COMPLETO, False), self._pedidos("BRK-B"), "la noche la sigue (historia entera)")
        self.assertEqual(self.client.post("/api/watchlist", json={"symbol": "BRK-BB"}, headers=self.h).status_code, 422)

    def test_lista_de_seguimiento_tiene_tope(self):
        with mock.patch("main.WATCHLIST_TOPE", 3):
            for t in ("AAA", "BBB", "CCC"):
                r = self.client.post("/api/watchlist", json={"symbol": t}, headers=self.h)
                self.assertEqual(r.status_code, 200, r.text)
            r = self.client.post("/api/watchlist", json={"symbol": "DDD"}, headers=self.h)
            self.assertEqual(r.status_code, 400)
            self.assertIn("llegó a 3", r.text)
            # Repetir uno que ya está no es sumar: sigue andando.
            self.assertEqual(self.client.post("/api/watchlist", json={"symbol": "AAA"}, headers=self.h).status_code, 200)

    def test_los_que_fallan_pasan_al_final_de_la_fila(self):
        import velas_diarias
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        for t in ("ZZA", "ZZB"):
            self.client.post("/api/watchlist", json={"symbol": t}, headers=self.h)
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        main._run_velas_diarias_job()                          # noche 1: ZZA y ZZB fallan
        self.yahoo.pedidos = []
        with main.db_abierta() as conn:
            velas_diarias.actualizar(conn, ["ZZA", "ZZB", "MSFT"])
        self.assertEqual(self.yahoo.pedidos[0], ("MSFT", "1mo", False), "los de verdad primero")

    def test_admin_cuenta_solo_lo_que_se_sigue_hoy(self):
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:   # un activo viejo que ya nadie sigue, atrasado y fallado
            conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('VIEJO', '2025-01-02', 1)")
            conn.execute("INSERT INTO velas_estado (symbol, ok, error) VALUES ('VIEJO', 0, 'x')")
            conn.commit()
        e = self.client.get("/api/admin/velas", headers=self.h_admin).json()
        self.assertEqual((e["seguidos"], e["atrasados"], e["fallados"]), (1 + len(velas_diarias.INDICES), [], []),
                         "MSFT y los índices")


    def test_cierre_del_instrumento_de_tu_tenencia(self):
        # La ficha de AAPL en dólares es la acción de afuera, pero tu tenencia se
        # valúa con el CEDEAR en pesos: la ficha necesita SU último cierre para
        # saber cuánto se movió hoy.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "AAPL", "CEDEAR")
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0
        self.yahoo.precios["AAPL.BA"] = lambda i, d: 25000.0
        main._run_velas_diarias_job()
        f = self.client.get("/api/tecnico/AAPL?moneda=usd&ref=AAPL.BA", headers=self.h).json()
        self.assertEqual(f["cierre_ref"], {"fecha": self.dias[-1].isoformat(), "cierre": 25000.0})
        self.assertIsNone(self._ficha("AAPL")["cierre_ref"])
        r = self.client.get("/api/tecnico/AAPL?ref=<x>", headers=self.h)
        self.assertEqual(r.status_code, 400)

    # ─── Ficha de un activo que nadie sigue (mapa de calor, buscador) ────────

    def _pedidos(self, ticker):
        return [p for p in self.yahoo.pedidos if p[0] == ticker]

    def test_activo_que_nadie_sigue_se_baja_al_abrir_la_ficha(self):
        # NVDA no está en ninguna cartera ni watchlist: la noche no la baja.
        self.yahoo.precios["NVDA"] = lambda i, d: 100 + i * 0.2
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos("NVDA"), [], "la noche sólo baja lo que alguien sigue")
        f = self._ficha("NVDA")
        self.assertTrue(f["disponible"])
        self.assertEqual(f["ticker"], "NVDA")
        self.assertEqual(f["puntos"][-1]["d"], self.dias[-1].isoformat())
        self.assertEqual(self._pedidos("NVDA"), [("NVDA", PERIODO_COMPLETO, False)])
        # La segunda vez (o la de otra persona) ya está guardada: no se pide de nuevo.
        self._ficha("NVDA")
        self._ficha("NVDA", "ars")
        self.assertEqual(len(self._pedidos("NVDA")), 1)

    def test_cedear_a_pedido_baja_solo_la_accion_de_afuera(self):
        # La serie en pesos de un CEDEAR necesita la lista de cambios de ratio,
        # que se arma de noche sólo para lo seguido: a pedido va la de afuera y
        # en pesos es un ESTIMADO del CEDEAR: la acción × el MEP de cada día ÷
        # los CEDEARs que hacen una acción (20 en Apple: ratios_cedear). Antes,
        # sin dividir: la acción entera en pesos, $ 250.000 contra un CEDEAR de
        # ~$ 13.000 (Nico eligió el estimado, 06/11/2026).
        self._mep(lambda i: 1000.0 + i)
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0 + i * 0.1
        self.yahoo.precios["AAPL.BA"] = lambda i, d: 13000.0     # el de verdad: a pedido no se baja
        with mock.patch("main._fetch_data912_equities", lambda: {"AAPL": {"mercado": "arg_cedears"}}):
            usd = self._ficha("AAPL.BA")
            ars = self._ficha("AAPL.BA", "ars")
        self.assertEqual((usd["ticker"], usd["convertida"]), ("AAPL", None))
        self.assertEqual((ars["ticker"], ars["convertida"]), ("AAPL", "mep"))
        # Cada día con SU dólar y la misma escala, del primer punto al último.
        dias = [d.isoformat() for d in self.dias]
        for p in (ars["puntos"][0], ars["puntos"][-1]):
            i = dias.index(p["d"])
            self.assertAlmostEqual(p["c"], (250.0 + i * 0.1) * (1000.0 + i) / 20, places=3)
        self.assertEqual(ars["puntos"][-1]["d"], dias[-1])
        self.assertEqual((usd.get("escala"), ars.get("escala")), (None, 20))
        self.assertEqual(self._pedidos("AAPL.BA"), [])

    def test_bac_en_pesos_es_el_cedear_estimado_tambien_para_quien_lo_tiene(self):
        # El '.BA' de BAC cotiza en dólares y roto: la noche baja sólo la acción
        # de afuera aunque alguien lo tenga (velas_diarias._yahoo_de). El gráfico
        # en pesos era BAC × el MEP: 4 veces el CEDEAR, para todos. Ahora ÷ 4, el
        # MISMO ratio con que se valúa (main.CEDEAR_USD_RATIOS sale de la tabla).
        self._broker("IOL", "ARS")
        self._posicion("IOL", "BAC", "CEDEAR")
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["BAC"] = lambda i, d: 50.0
        self.yahoo.precios["BAC.BA"] = lambda i, d: 9.0           # el roto, en dólares
        main._run_velas_diarias_job()
        self.assertEqual(self._pedidos("BAC.BA"), [])
        # Lo que BYMA dice de BAC es su precio roto en dólares (≈ 7): no sirve para
        # controlar la escala y no se usa (`tecnico._escalas_de_hoy`).
        with self._bolsa({"BAC": {"mercado": "arg_cedears", "c": 7.06, "pct": 0.5}}):
            ars = self._ficha("BAC", "ars")
        self.assertEqual((ars["ticker"], ars["convertida"]), ("BAC", "mep"))
        self.assertAlmostEqual(ars["puntos"][-1]["c"], 12_500.0, places=3)
        self.assertEqual(ars.get("escala"), 4)
        self.assertEqual(main.CEDEAR_USD_RATIOS["BAC"], ars["escala"])

    # ─── El dólar de los CEDEARs: el contado con liqui de cada día (Nico, 06/11) ───
    # Con el MEP el estimado quedaba ~5 % abajo de la Bolsa y saltaba sin que se
    # moviera el mercado: los CEDEARs se pagan con el contado con liqui, y la
    # distancia entre los dos dólares cambia (audit/_scripts/medir_ccl.out).

    def test_el_cedear_estimado_va_con_el_contado_con_liqui_de_cada_dia(self):
        # Apple a pedido, en pesos: la acción × el contado con liqui DE CADA DÍA ÷
        # 20, no × el MEP. Los dos dólares se separan con el tiempo, como en
        # 2024–2026: el MEP sube de a 1 y el contado con liqui de a 1,5.
        self._mep(lambda i: 1000.0 + i)
        self._ccl(lambda i: 1000.0 + i * 1.5)
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0 + i * 0.1
        with mock.patch("main._fetch_data912_equities", lambda: {"AAPL": {"mercado": "arg_cedears"}}):
            ars = self._ficha("AAPL.BA", "ars")
        dias = [d.isoformat() for d in self.dias]
        for p in (ars["puntos"][0], ars["puntos"][len(ars["puntos"]) // 2], ars["puntos"][-1]):
            i = dias.index(p["d"])
            self.assertAlmostEqual(p["c"], (250.0 + i * 0.1) * (1000.0 + i * 1.5) / 20, places=3)
        self.assertEqual((ars["ticker"], ars["convertida"], ars.get("escala")), ("AAPL", "ccl", 20))
        self.assertEqual(ars["puntos"][-1]["d"], dias[-1])
        # En dólares no cambia nada: la acción de afuera, sin ningún dólar.
        usd = self._ficha("AAPL.BA")
        self.assertEqual((usd["ticker"], usd["convertida"], usd.get("escala")), ("AAPL", None, None))

    def test_lo_que_no_es_cedear_sigue_con_el_mep(self):
        # Lo que no es un CEDEAR no se paga con el contado con liqui: SCHD (un ETF
        # que no es CEDEAR) y Bitcoin en pesos siguen × el MEP de cada día aunque
        # el contado con liqui esté guardado. El S&P 500 en pesos, en cambio, va con
        # el dólar de los CEDEARs: es contra lo que se los compara, y en la Bolsa se
        # compra con el CEDEAR de SPY (auditoría del contado con liqui, H2 del servidor).
        self._mep(lambda i: 1000.0)
        self._ccl(lambda i: 1100.0)
        self.yahoo.precios["SCHD"] = lambda i, d: 30.0
        self.yahoo.precios["BTC-USD"] = lambda i, d: 90_000.0
        for asset, ticker, esperado in (("SCHD", "SCHD", 30_000.0), ("BTC", "BTC-USD", 90_000_000.0)):
            ars = self._ficha(asset, "ars")
            self.assertEqual((ars["ticker"], ars["convertida"], ars.get("escala")), (ticker, "mep", None))
            self.assertAlmostEqual(ars["puntos"][-1]["c"], esperado, places=3)
        main._run_velas_diarias_job()                          # guarda el S&P 500
        with main.db_abierta() as conn:
            self.assertEqual({v["close"] for v in tecnico.sp500(conn, "ars")}, {5_500_000.0})
            self.assertEqual({v["close"] for v in tecnico.sp500(conn, "ars", "mep")}, {5_000_000.0})

    def test_sin_el_contado_con_liqui_guardado_sigue_con_el_mep_toda_la_serie(self):
        # Una base que todavía no lo bajó (recién publicado, argentinadatos caído):
        # el estimado de antes, con el MEP, y `convertida` lo dice (la nota de la
        # pantalla, del mail y de Mervall-E nombran ese dólar). Nunca mitad y mitad:
        # con sólo el último mes guardado, mezclar los dos dólares haría un escalón
        # de ~10 % en el medio del gráfico.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0
        for guardado in (None, len(self.dias) - 22):
            if guardado is not None:
                self._ccl(lambda i: 1100.0, desde=guardado)
            ars = self._ficha("AAPL", "ars")
            self.assertEqual((ars["convertida"], ars.get("escala")), ("mep", 20), guardado)
            self.assertEqual({p["c"] for p in ars["puntos"]}, {12_500.0}, guardado)
        # Con la historia entera guardada, el contado con liqui de punta a punta.
        self._ccl(lambda i: 1100.0)
        ars = self._ficha("AAPL", "ars")
        self.assertEqual((ars["convertida"], {p["c"] for p in ars["puntos"]}), ("ccl", {13_750.0}))

    def test_la_serie_vieja_no_corre_el_pasado_ni_salta_al_podarse(self):
        # Alguien tuvo MELI y la vendió: su serie de BYMA quedó guardada hasta 14
        # ruedas atrás. El CEDEAR de verdad vale la acción × el contado con liqui ÷
        # 120, y ese dólar se va separando del MEP (de 0 a 6 % en estos 3 años).
        # Con el MEP, el día que la serie quedaba vieja el pasado se corría (hace un
        # año, ~2 % arriba de lo que valió) y el día que la noche la borraba, todo
        # el gráfico bajaba ~6 % de golpe (auditoría 06/11, H4 de la pantalla).
        # Con el contado con liqui de cada día, el estimado ES la historia de verdad.
        n = len(self.dias)
        ccl = lambda i: 1000.0 * (1 + 0.06 * i / (n - 1))
        self._mep(lambda i: 1000.0)
        self._ccl(ccl)
        self.yahoo.precios["MELI"] = lambda i, d: 2000.0 + i
        bolsa = lambda i: (2000.0 + i) * ccl(i) / 120
        with main.db_abierta() as conn:
            for i, d in enumerate(self.dias[:-14]):
                conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('MELI.BA', ?, ?)",
                             (d.isoformat(), bolsa(i)))
            conn.commit()
        with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
            vieja = self._ficha("MELI.BA", "ars")
        puntos = {p["d"]: p["c"] for p in vieja["puntos"]}
        for i in (n - 1 - 250, n - 1 - 125, n - 15):     # hace un año, seis meses, la última guardada
            self.assertAlmostEqual(puntos[self.dias[i].isoformat()] / bolsa(i), 1.0, places=5,
                                   msg=f"rueda {i}: el estimado corre el pasado")
        self.assertEqual((vieja["ticker"], vieja["convertida"]), ("MELI", "ccl"))
        self.assertAlmostEqual(vieja["escala"], 120.0, places=6)
        # La noche borra la serie vieja: queda la escala de la tabla y el MISMO gráfico.
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_diarias WHERE symbol='MELI.BA'")
            conn.commit()
        with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
            podada = self._ficha("MELI.BA", "ars")
        self.assertEqual(podada["escala"], 120)
        for a, b in zip(vieja["puntos"], podada["puntos"]):
            self.assertEqual(a["d"], b["d"])
            self.assertAlmostEqual(b["c"] / a["c"], 1.0, places=5, msg=f"{a['d']}: salta al podar")

    def _precios_de_bac(self, ccl_ahora):
        """`/api/prices` y el cierre anterior (`/api/prices/prev-close` y la
        variación del día) de BAC.BA con `ccl_ahora` como contado con liqui de
        ahora (el caché de dolarapi), sin lo que guardaron pedidos anteriores."""
        for cache in (main._PRICE_CACHE, main._PREVCLOSE_CACHE, main._PREVCLOSE_RUEDA,
                      main._PREVCLOSE_ULTIMO, main._history_cache):
            cache.clear()
        vivo = _ccl_en_la_cache(ccl_ahora)
        # Sin red: un '.BA' se busca también entre los bonos y letras (data912,
        # argentinadatos): sin esto la prueba les pedía la lista de verdad.
        with mock.patch.dict(main._dolar_cache, {"data": {"ccl": vivo}, "ts": 9e18}), \
                mock.patch("main._resolve_ar_bond_price", lambda *a, **k: None):
            precio = self.client.get("/api/prices?symbols=BAC.BA", headers=self.h).json()["BAC.BA"]
            anterior = self.client.get("/api/prices/prev-close?symbols=BAC.BA", headers=self.h).json()["BAC.BA"]
            variacion = main._variacion_del_dia(["BAC.BA"], self.uid)["BAC.BA"]
        return precio, anterior, variacion

    def test_bac_el_grafico_y_la_cartera_con_el_mismo_contado_con_liqui(self):
        # BYMA cotiza BAC roto (en dólares): la Cartera lo valúa con la acción de
        # Nueva York × el contado con liqui ÷ 4, y el gráfico en pesos lo dibujaba
        # × el MEP ÷ 4: dos «BAC en pesos» en la misma ficha (auditoría 06/11, H3 de
        # la serie y H5 de la pantalla). Ahora: el gráfico, cada día con su contado
        # con liqui; el cierre anterior de la Cartera, la vela de ESE día del
        # gráfico (antes, × el de hoy); el precio de ahora, × el de ahora.
        self._broker("IOL", "ARS")
        self._posicion("IOL", "BAC", "CEDEAR")
        n = len(self.dias)
        ccl = lambda i: 1050.0 + i * 0.5
        self._mep(lambda i: 1000.0)
        self._ccl(ccl)
        self.yahoo.precios["BAC"] = lambda i, d: 50.0 + i * 0.01
        self.yahoo.precios["BAC.BA"] = lambda i, d: 9.0          # el roto, en dólares
        main._run_velas_diarias_job()
        ars = self._ficha("BAC", "ars")
        vela = {p["d"]: p["c"] for p in ars["puntos"]}
        dia = lambda i: self.dias[i].isoformat()
        self.assertAlmostEqual(vela[dia(n - 1)], (50.0 + (n - 1) * 0.01) * ccl(n - 1) / 4, places=3)
        self.assertEqual((ars["ticker"], ars["convertida"], ars["escala"]), ("BAC", "ccl", 4))

        precio, anterior, variacion = self._precios_de_bac(1200.0)
        self.assertAlmostEqual(anterior, vela[dia(n - 2)], places=2, msg="el cierre anterior = la vela del gráfico")
        # Nueva York todavía no operó hoy (la última rueda de Yahoo es la de ayer):
        # el precio de ahora es el de esa rueda con el dólar de SU día, la última
        # vela del gráfico, y el mismo número que la variación del inicio. Con el
        # dólar de ahora, esos ratos BAC tenía dos precios (H5 de la pantalla).
        self.assertAlmostEqual(precio, vela[dia(n - 1)], places=2)
        # La variación de la rueda de ayer (la última con precio de Nueva York): la
        # vela de ese día contra la anterior, con el dólar que se movió entre las dos.
        self.assertAlmostEqual(variacion["price"], vela[dia(n - 1)], places=2)
        self.assertAlmostEqual(variacion["prev_close"], vela[dia(n - 2)], places=2)

        # El mini-gráfico de la Cartera: cada día con SU contado con liqui (antes,
        # el mes entero con el de hoy, como si el dólar no se hubiera movido).
        ruedas = self.dias[-22:]

        class _Ticker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, period, interval, auto_adjust):
                return pd.DataFrame({"Close": [50.0 + (n - 22 + k) * 0.01 for k in range(len(ruedas))]},
                                    index=pd.DatetimeIndex([pd.Timestamp(d) for d in ruedas]))
        main._history_cache.clear()
        with mock.patch("main.yf.Ticker", _Ticker), \
                mock.patch.dict(main._dolar_cache, {"data": {"ccl": _ccl_en_la_cache(1200.0)}, "ts": 9e18}):
            mini = self.client.get("/api/prices/history?symbol=BAC.BA&period=1m", headers=self.h).json()
        self.assertEqual(len(mini["points"]), 22)
        for p in mini["points"]:
            self.assertAlmostEqual(p["close"] / vela[p["date"]], 1.0, places=4, msg=p["date"])

    def test_la_noche_guarda_el_contado_con_liqui_de_cada_dia(self):
        # `main._actualizar_ccl` corre antes de las velas de la noche: la primera
        # vez guarda todo lo que manda la fuente; después, lo que falta y los
        # últimos días (el de hoy se publica en vivo y la noche guarda el del
        # cierre). Lo de antes no se reescribe. Un renglón roto no entra.
        dias = [d.isoformat() for d in self.dias]
        fuente = [(d, 1000.0 + i, 1010.0 + i) for i, d in enumerate(dias)]

        def guardado(d):
            with main.db_abierta() as conn:
                r = conn.execute("SELECT value FROM bond_indices_daily WHERE index_name='CCL' AND date=?",
                                 (d,)).fetchone()
            return r["value"] if r else None

        with mock.patch("main._bajar_ccl", lambda: fuente + [("mal", 1.0, 2.0), ("2026-01-0x", 1, 2),
                                                             ("2026-02-30", 1, 2), (None, 1, 2), ("2026-11-06", 0, 0)]):
            main._run_velas_diarias_job()
        self.assertEqual((guardado(dias[0]), guardado(dias[-1])), (1005.0, 1005.0 + len(dias) - 1))
        with main.db_abierta() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM bond_indices_daily WHERE index_name='CCL'")
                             .fetchone()[0], len(dias))
        otra = [(d, 2000.0, 2010.0) for d in dias]          # la fuente «cambió» toda la historia
        with mock.patch("main._bajar_ccl", lambda: otra):
            main._run_velas_diarias_job()
        self.assertEqual(guardado(dias[0]), 1005.0, "lo viejo no se reescribe")
        self.assertEqual(guardado(dias[-1]), 2005.0, "los últimos días sí")
        # Sin respuesta de la fuente, queda lo guardado; y un error del contado con
        # liqui no frena las velas de la noche.
        self.yahoo.precios["SPY"] = lambda i, d: 500.0
        self._broker("IOL", "ARS")
        self._posicion("IOL", "SPY", "CEDEAR")
        with mock.patch("main._actualizar_ccl", side_effect=RuntimeError("se cayó")):
            main._run_velas_diarias_job()
        self.assertEqual(guardado(dias[-1]), 2005.0)
        with main.db_abierta() as conn:
            self.assertGreater(conn.execute("SELECT COUNT(*) FROM velas_diarias WHERE symbol='SPY'").fetchone()[0], 0)

    # ─── Bordes del contado con liqui que no veía ninguna prueba (auditoría de las pruebas, 06/11) ───

    def _cierres_de_bac(self, ccl_ahora):
        """El cierre anterior (`/api/prices/prev-close`) y la variación del día de
        BAC.BA con `ccl_ahora` de contado con liqui de ahora, sin lo que guardaron
        pedidos anteriores (como `_precios_de_bac`, sin /api/prices)."""
        for cache in (main._PRICE_CACHE, main._PREVCLOSE_CACHE, main._PREVCLOSE_RUEDA,
                      main._PREVCLOSE_ULTIMO, main._history_cache):
            cache.clear()
        vivo = _ccl_en_la_cache(ccl_ahora)
        # Sin red: un '.BA' se busca también entre los bonos y letras (data912,
        # argentinadatos); BAC no es ninguno.
        with mock.patch.dict(main._dolar_cache, {"data": {"ccl": vivo}, "ts": 9e18}), \
                mock.patch("main._resolve_ar_bond_price", lambda *a, **k: None):
            anterior = self.client.get("/api/prices/prev-close?symbols=BAC.BA", headers=self.h).json()["BAC.BA"]
            variacion = main._variacion_del_dia(["BAC.BA"], self.uid)["BAC.BA"]
        return anterior, variacion

    def _bac_con_su_grafico(self, ccl):
        """BAC en la Cartera, con el MEP de 1000, el contado con liqui `ccl(i)` de
        cada rueda y la noche corrida. Devuelve {fecha: vela del gráfico en pesos}."""
        self._broker("IOL", "ARS")
        self._posicion("IOL", "BAC", "CEDEAR")
        self._mep(lambda i: 1000.0)
        if ccl:
            self._ccl(ccl)
        self.yahoo.precios["BAC"] = lambda i, d: 50.0 + i * 0.01
        self.yahoo.precios["BAC.BA"] = lambda i, d: 9.0          # el roto, en dólares
        main._run_velas_diarias_job()
        return {p["d"]: p["c"] for p in self._ficha("BAC", "ars")["puntos"]}

    def test_el_contado_con_liqui_tiene_que_cubrir_desde_la_primera_vela(self):
        # `_dolar_de_los_cedears`, el borde de afuera: guardado desde UNA rueda
        # después de la primera vela, es MEP para toda la serie (ninguna vela se
        # pierde ni se mezcla). Desde la primera, contado con liqui de punta a punta.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0
        self._ccl(lambda i: 1100.0, desde=1)
        ars = self._ficha("AAPL", "ars")
        self.assertEqual((ars["convertida"], {p["c"] for p in ars["puntos"]}), ("mep", {12_500.0}))
        self.assertEqual(ars["puntos"][0]["d"], self.dias[0].isoformat())
        self._ccl(lambda i: 1100.0)                       # ahora también el de la primera
        ars = self._ficha("AAPL", "ars")
        self.assertEqual((ars["convertida"], {p["c"] for p in ars["puntos"]}), ("ccl", {13_750.0}))
        self.assertEqual(ars["puntos"][0]["d"], self.dias[0].isoformat())

    def test_el_contado_con_liqui_de_hace_una_semana_todavia_vale_y_el_de_hace_ocho_dias_no(self):
        # Si argentinadatos deja de publicar, cada vela usa el último contado con
        # liqui guardado de hasta `tecnico.MAX_DIAS_SIN_DOLAR` (7) días antes; más
        # viejo, la vela no se dibuja (no se inventa con un dólar viejo). Era la regla
        # del MEP y desde el 06/11 es también la del contado con liqui. Bordes: a 7
        # días todavía; a 8, ya no. (El corte, un día con otro 8 días después.)
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0
        hay = set(self.dias)
        j = max(i for i, d in enumerate(self.dias) if d + timedelta(days=8) in hay)
        tope = self.dias[j]
        filas = [(d.isoformat(), 1099.0, 1101.0) for d in self.dias[:j + 1]]
        with mock.patch("main._bajar_ccl", lambda: filas):
            main._actualizar_ccl()
        ars = self._ficha("AAPL", "ars")
        fechas = [p["d"] for p in ars["puntos"]]
        self.assertEqual(ars["convertida"], "ccl")
        self.assertEqual(fechas[-1], (tope + timedelta(days=7)).isoformat(), "a 7 días del último guardado, todavía")
        self.assertNotIn((tope + timedelta(days=8)).isoformat(), fechas, "a 8, ya no")

    def test_el_cer_de_la_misma_tabla_no_cuenta_como_contado_con_liqui(self):
        # `bond_indices_daily` guarda también el CER y la UVA de cada día (los bajan
        # los bonos y Comparar): para saber desde cuándo hay contado con liqui
        # cuentan SÓLO sus filas. Sin esta prueba, el único que lo veía era
        # `test_sin_escala_lo_que_mira_variaciones_sigue_mirando`, y sólo cuando
        # argentinadatos le contestaba la UVA de verdad en medio de la prueba.
        import fx
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0
        with main.db_abierta() as conn:
            for i, d in enumerate(self.dias):
                conn.execute(fx.SQL_GUARDAR_INDICE, ("CER", d.isoformat(), 700.0 + i, "prueba", "x"))
            conn.commit()
        ars = self._ficha("AAPL", "ars")
        self.assertEqual((ars["convertida"], {p["c"] for p in ars["puntos"]}), ("mep", {12_500.0}))

    def test_bac_el_cierre_anterior_con_un_contado_con_liqui_de_hasta_una_semana(self):
        # `fx.ccl_de_las_fechas` (el cierre anterior y el último de BAC) usa el último
        # guardado de hasta 7 días antes (`tecnico.MAX_DIAS_SIN_DOLAR`, como el
        # gráfico); más viejo ya no es «el de ese día» y va el de ahora. Bordes: de
        # 7 días justos entra; de 8 o más, no.
        n = len(self.dias)
        ccl = lambda i: 1050.0 + i * 0.5
        tope = self.dias[n - 2] - timedelta(days=7)        # el mismo día, una semana antes
        k = self.dias.index(tope)
        self._bac_con_su_grafico(None)
        filas = [(d.isoformat(), ccl(i) - 5, ccl(i) + 5) for i, d in enumerate(self.dias) if i <= k]
        with mock.patch("main._bajar_ccl", lambda: filas):
            main._actualizar_ccl()
        anterior, variacion = self._cierres_de_bac(1200.0)
        self.assertAlmostEqual(anterior, (50.0 + (n - 2) * 0.01) * ccl(k) / 4, places=2,
                               msg="el cierre anterior, con el guardado de hace 7 días justos")
        self.assertAlmostEqual(variacion["price"], (50.0 + (n - 1) * 0.01) * 1200.0 / 4, places=2,
                               msg="el último, a 8 o más días del guardado: el de ahora")

    def test_bac_el_cierre_anterior_del_respaldo_de_a_uno_va_con_el_dolar_de_su_dia(self):
        # Si la bajada en lote no trae BAC, el respaldo de a uno
        # (`_fetch_prev_close_one`) da el cierre anterior SIN su fecha: va con el
        # contado con liqui del día antes del último (`_dia_antes`: la vela anterior
        # del gráfico) y el último con el de SU día.
        n = len(self.dias)
        vela = self._bac_con_su_grafico(lambda i: 1050.0 + i * 0.5)
        ultimo = self.dias[n - 1].isoformat()
        del self.yahoo.precios["BAC"]                      # el lote no la trae
        with mock.patch("main._fetch_prev_close_one",
                        lambda t: (50.0 + (n - 2) * 0.01, 50.0 + (n - 1) * 0.01, ultimo)):
            anterior, variacion = self._cierres_de_bac(1200.0)
        self.assertAlmostEqual(anterior, vela[self.dias[n - 2].isoformat()], places=2)
        self.assertAlmostEqual(variacion["price"], vela[ultimo], places=2)

    def test_bac_el_mini_grafico_de_un_anio_cada_semana_con_el_dolar_de_su_cierre(self):
        # El mini-gráfico de 1 año va en velas SEMANALES (Yahoo las fecha el lunes y
        # cierran el último día de su semana): cada una con el contado con liqui del
        # cierre de su semana (`_cierra`: el lunes + 6, el último guardado hasta ese
        # domingo), o sea la vela del viernes del gráfico. Como en producción, la
        # tabla tiene además el CER de todos los días corridos.
        import fx
        vela = self._bac_con_su_grafico(lambda i: 1050.0 + i * 0.5)
        with main.db_abierta() as conn:
            d = self.dias[0]
            while d <= self.hoy:
                conn.execute(fx.SQL_GUARDAR_INDICE, ("CER", d.isoformat(), 700.0, "prueba", "x"))
                d += timedelta(days=1)
            conn.commit()
        lunes_de_hoy = self.hoy - timedelta(days=self.hoy.weekday())
        viernes = [d for d in self.dias[-250:] if d.weekday() == 4 and d < lunes_de_hoy]
        semanas = [(v - timedelta(days=4), 50.0 + self.dias.index(v) * 0.01) for v in viernes]

        class _Ticker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, period, interval, auto_adjust):
                return pd.DataFrame({"Close": [c for _, c in semanas]},
                                    index=pd.DatetimeIndex([pd.Timestamp(l) for l, _ in semanas]))
        main._history_cache.clear()
        with mock.patch("main.yf.Ticker", _Ticker), \
                mock.patch.dict(main._dolar_cache, {"data": {"ccl": _ccl_en_la_cache(1200.0)}, "ts": 9e18}):
            mini = self.client.get("/api/prices/history?symbol=BAC.BA&period=1y", headers=self.h).json()
        self.assertEqual(len(mini["points"]), len(semanas))
        for (lunes, _), v, p in zip(semanas, viernes, mini["points"]):
            self.assertEqual(p["date"], lunes.isoformat())
            self.assertAlmostEqual(p["close"] / vela[v.isoformat()], 1.0, places=4, msg=p["date"])

    def test_bac_hoy_va_con_el_contado_con_liqui_de_ahora_aunque_haya_uno_guardado_de_hoy(self):
        # Al arrancar durante la rueda, argentinadatos ya publica el de HOY (en vivo):
        # no se guarda (`fx.fechas_de_argentinadatos`), y aunque hubiera uno guardado
        # de hoy, el punto de hoy del mini-gráfico va con el de AHORA
        # (`_ccl_de_las_fechas`: sólo lo de ANTES de hoy sale de lo guardado); el de
        # ayer, con el guardado de ayer.
        hoy = self.hoy.isoformat()
        filas = [(d.isoformat(), 1049.0, 1051.0) for d in self.dias] + [(hoy, 1110.0, 1112.0)]
        with mock.patch("main._bajar_ccl", lambda: filas):
            main._actualizar_ccl()
        ruedas = self.dias[-21:] + [self.hoy]

        class _Ticker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, period, interval, auto_adjust):
                return pd.DataFrame({"Close": [50.0] * len(ruedas)},
                                    index=pd.DatetimeIndex([pd.Timestamp(d) for d in ruedas]))
        main._history_cache.clear()
        with mock.patch("main.yf.Ticker", _Ticker), \
                mock.patch.dict(main._dolar_cache, {"data": {"ccl": _ccl_en_la_cache(1200.0)}, "ts": 9e18}):
            mini = self.client.get("/api/prices/history?symbol=BAC.BA&period=1m", headers=self.h).json()
        por_dia = {p["date"]: p["close"] for p in mini["points"]}
        self.assertAlmostEqual(por_dia[hoy], 50.0 * 1200.0 / 4, places=4, msg="hoy: el de ahora")
        self.assertAlmostEqual(por_dia[self.dias[-1].isoformat()], 50.0 * 1050.0 / 4, places=4, msg="ayer: el guardado")

    def test_la_noche_reescribe_los_ultimos_diez_dias_y_ni_uno_mas(self):
        # `fx.guardar_ccl`: además de lo que falta, vuelve a escribir desde el último
        # guardado menos 10 días (`DIAS_CCL_REVISAR`), ese día incluido. Borde: el de
        # hace 10 días justos se reescribe; el de hace 11, no. (Con días corridos, para
        # que el borde exista cualquier día de la semana.)
        ultimo = self.dias[-1]
        dias = [ultimo - timedelta(days=k) for k in range(30, -1, -1)]
        with mock.patch("main._bajar_ccl", lambda: [(d.isoformat(), 999.0, 1001.0) for d in dias]):
            main._actualizar_ccl()
        with mock.patch("main._bajar_ccl", lambda: [(d.isoformat(), 1999.0, 2001.0) for d in dias]):
            main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            valor = {r["date"]: r["value"] for r in conn.execute(
                "SELECT date, value FROM bond_indices_daily WHERE index_name='CCL'").fetchall()}
        self.assertEqual(valor[(ultimo - timedelta(days=10)).isoformat()], 2000.0, "el de hace 10 días justos")
        self.assertEqual(valor[(ultimo - timedelta(days=11)).isoformat()], 1000.0, "el de hace 11, no")
        self.assertEqual(valor[ultimo.isoformat()], 2000.0)

    def test_el_contado_con_liqui_se_lee_como_lo_publica_argentinadatos(self):
        # La lectura de la fuente (`main._bajar_ccl`, que la suite reemplaza en todas
        # las demás pruebas: conftest, `_ccl_sin_red`): la lista de argentinadatos tal
        # como la publica, y lo guardado es el MEDIO de compra y venta.
        pedidos = []

        class _Respuesta:
            status_code = 200

            def json(self):
                return [{"casa": "contadoconliqui", "compra": 1490.0, "venta": 1510.0, "fecha": "2026-11-04"},
                        {"casa": "contadoconliqui", "compra": 1500.0, "venta": 1520.0, "fecha": "2026-11-05"}]

        def _get(url, timeout=None, **kw):
            pedidos.append(url)
            return _Respuesta()
        with mock.patch("main._bajar_ccl", _BAJAR_CCL), mock.patch("main.requests.get", _get):
            self.assertEqual(main._actualizar_ccl(), 2)
        self.assertEqual(pedidos, ["https://api.argentinadatos.com/v1/cotizaciones/dolares/contadoconliqui"])
        with main.db_abierta() as conn:
            filas = conn.execute("SELECT date, value FROM bond_indices_daily WHERE index_name='CCL' "
                                 "ORDER BY date").fetchall()
        self.assertEqual([(r["date"], r["value"]) for r in filas], [("2026-11-04", 1500.0), ("2026-11-05", 1510.0)])

    @staticmethod
    def _como_argentinadatos(cierres: dict, corrida, hoy: date, en_vivo: float) -> list:
        """Las filas que publicaría argentinadatos para los cierres de cada día hábil
        (`cierres`: {día: valor}), todos los días del calendario hasta `hoy` (la de
        hoy, el valor del momento: `en_vivo`). `corrida(día)`: si esa fila lleva la
        fecha del día SIGUIENTE al cierre que trae, como desde septiembre de 2026."""
        filas, ultimo, d = [], None, min(cierres)
        while d < hoy:
            if d in cierres:
                ultimo_antes, ultimo = ultimo, cierres[d]
            else:
                ultimo_antes = ultimo
            # Corrida: el lunes trae el cierre del viernes; el sábado, también.
            valor = (ultimo_antes if d in cierres else ultimo) if corrida(d) else ultimo
            if valor is not None:
                filas.append((d.isoformat(), valor - 1, valor + 1))
            d += timedelta(days=1)
        filas.append((hoy.isoformat(), en_vivo - 1, en_vivo + 1))
        return filas

    def test_la_fecha_de_argentinadatos_se_corrige_cuando_la_corre(self):
        # Desde septiembre de 2026 argentinadatos fecha cada cierre con el día
        # siguiente: la fila del lunes trae el del viernes (auditoría del contado con
        # liqui, H1 del servidor: medido contra el dólar que implican los CEDEARs). Lo
        # dicen los fines de semana: el sábado igual al viernes, alineada; igual al
        # lunes, corrida. Sin corregirlo, cada vela iba con el dólar de la rueda
        # anterior. Seis semanas: dos alineadas, dos corridas y otras dos alineadas
        # (la fuente puede volver a cambiar). La fila de hoy, el valor del momento,
        # no se usa nunca.
        import fx
        lunes = date(2026, 8, 17)
        habiles = [lunes + timedelta(days=k) for k in range(42) if (lunes + timedelta(days=k)).weekday() < 5]
        cierres = {d: 1500.0 + 3 * i for i, d in enumerate(habiles)}
        corridas = lambda d: date(2026, 8, 31) <= d < date(2026, 9, 14)
        hoy = lunes + timedelta(days=42)
        filas = self._como_argentinadatos(cierres, corridas, hoy, en_vivo=9999.0)
        bien = {f: (c + v) / 2 for f, c, v in fx.fechas_de_argentinadatos(filas, hoy.isoformat())}
        for d, c in cierres.items():
            self.assertEqual(bien.get(d.isoformat()), c, f"{d}: el cierre de ESE día")
        self.assertNotIn(9999.0, bien.values(), "la fila de hoy es el valor del momento")
        # Sin corregir, en las semanas corridas el lunes traía el del viernes.
        crudas = {f: (c + v) / 2 for f, c, v in filas}
        self.assertEqual(crudas["2026-09-07"], cierres[date(2026, 9, 4)])
        # Con datos reales de la fuente (06/11/2026): la fila del martes 27/10 trae
        # el cierre del lunes 26 (el que implican los CEDEARs: 1.678,3).
        reales = [("2026-10-16", 1614.9, 1616.6), ("2026-10-17", 1618.6, 1620.3), ("2026-10-18", 1618.6, 1620.3),
                  ("2026-10-19", 1618.6, 1620.3), ("2026-10-20", 1623.7, 1625.5), ("2026-10-23", 1637.9, 1639.5),
                  ("2026-10-24", 1650.7, 1652.5), ("2026-10-25", 1650.7, 1652.5), ("2026-10-26", 1650.7, 1652.5),
                  ("2026-10-27", 1680.2, 1682.0)]
        reales = {f: (c + v) / 2 for f, c, v in fx.fechas_de_argentinadatos(reales, "2026-11-06")}
        self.assertAlmostEqual(reales["2026-10-26"], 1681.1, places=6)
        self.assertAlmostEqual(reales["2026-10-23"], 1651.6, places=6)
        # En una semana corrida la fila de HOY es el cierre de AYER: queda con la
        # fecha de ayer. Antes se descartaba por tener la de hoy ANTES de corregirla,
        # y el 05/11 quedaba sin su dólar hasta la noche siguiente (la vela de ese
        # día iba con el cierre del 04/11; medido el 06/11 a las 21, con la fuente de
        # esa hora).
        fuente = [("2026-10-30", 1649.8, 1650.3), ("2026-10-31", 1655.3, 1658.5), ("2026-11-01", 1655.3, 1658.5),
                  ("2026-11-02", 1655.3, 1658.5), ("2026-11-03", 1663.2, 1670.0), ("2026-11-04", 1667.2, 1668.8),
                  ("2026-11-05", 1676.7, 1680.4), ("2026-11-06", 1658.4, 1664.9)]
        dias = {f: (c + v) / 2 for f, c, v in fx.fechas_de_argentinadatos(fuente, "2026-11-06")}
        self.assertEqual(max(dias), "2026-11-05", "hoy no: todavía no cerró")
        self.assertAlmostEqual(dias["2026-11-05"], 1661.65, places=6)
        self.assertAlmostEqual(dias["2026-11-04"], 1678.55, places=6)

    def test_el_cierre_de_cada_dia_lo_anota_el_servidor_y_argentinadatos_no_lo_pisa(self):
        # El cierre de cada día lo anota el servidor de dolarapi con la fecha del
        # DATO (no la del reloj ni la de argentinadatos) y manda: la noche siguiente,
        # argentinadatos vuelve a escribir sus últimos 10 días y no lo pisa.
        ayer = self.dias[-1]
        filas = [(d.isoformat(), 1499.0, 1501.0) for d in self.dias[-20:]]
        dolarapi = {"compra": 1599.0, "venta": 1601.0, "medio": 1600.0, "updated_at": f"{ayer.isoformat()}T21:00:00Z"}
        guardado = lambda d: self._valor_ccl(d.isoformat())
        with mock.patch("main._bajar_ccl", lambda: filas), \
                mock.patch("main._ccl_cerrado_de_dolarapi", _CCL_DE_DOLARAPI), \
                mock.patch("main._fetch_dolar", lambda casa: dolarapi if casa == "contadoconliqui" else None):
            main._actualizar_ccl()
            self.assertEqual((guardado(ayer), guardado(self.dias[-2])), (1600.0, 1500.0))
            main._run_velas_diarias_job()                      # la noche siguiente
        self.assertEqual(guardado(ayer), 1600.0, "argentinadatos no pisa el cierre que anotó el servidor")
        with main.db_abierta() as conn:
            fuente = conn.execute("SELECT source FROM bond_indices_daily WHERE index_name='CCL' AND date=?",
                                  (ayer.isoformat(),)).fetchone()["source"]
        self.assertEqual(fuente, "dolarapi")

    def _valor_ccl(self, d):
        with main.db_abierta() as conn:
            r = conn.execute("SELECT value FROM bond_indices_daily WHERE index_name='CCL' AND date=?", (d,)).fetchone()
        return r["value"] if r else None

    def test_al_arrancar_se_baja_el_contado_con_liqui_aunque_falle_lo_del_mep(self):
        # Una base recién publicada no tiene el contado con liqui: lo baja el arranque
        # (`_backfill_fx_rates_on_boot`, en su hilo), aunque lo del MEP falle, y no
        # hay que esperar a la noche con todos los CEDEARs en el MEP.
        import threading
        filas = [(d.isoformat(), 1099.0, 1101.0) for d in self.dias]
        with mock.patch("main._bajar_ccl", lambda: filas), \
                mock.patch("main._backfill_fx_rates_if_empty", side_effect=RuntimeError("argentinadatos caído")), \
                mock.patch("main._backfill_mep_rates_if_missing"), mock.patch("main._backfill_compras_if_missing"):
            main._backfill_fx_rates_on_boot()
            for t in threading.enumerate():
                if t.name == "fx-backfill":
                    t.join(timeout=30)
        with main.db_abierta() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM bond_indices_daily WHERE index_name='CCL'")
                             .fetchone()[0], len(self.dias))

    def test_sin_saber_la_escala_del_cedear_no_hay_grafico_en_pesos(self):
        # Mejor sin gráfico en pesos que uno veinte veces más alto.
        self._mep(lambda i: 1000.0)
        # Cloudflare es CEDEAR (la lista de la app) y la tabla de ratios no lo tiene.
        self.yahoo.precios["NET"] = lambda i, d: 200.0
        with mock.patch("main._fetch_data912_equities", lambda: {"NET": {"mercado": "arg_cedears"}}):
            self.assertTrue(self._ficha("NET.BA")["disponible"], "en dólares, la acción de afuera")
            self.assertFalse(self._ficha("NET.BA", "ars")["disponible"])
        # La serie en pesos que quedó guardada y la tabla no coinciden: MELI.BA en
        # $ 99 daría 20.202 CEDEARs por acción y la tabla dice 120. La tabla quedó
        # vieja o el CEDEAR cambió de ratio después: no se sabe cuál.
        self.yahoo.precios["MELI"] = lambda i, d: 2000.0
        with main.db_abierta() as conn:
            for d in self.dias[-300:-14]:
                conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('MELI.BA', ?, 99.0)",
                             (d.isoformat(),))
            conn.commit()
        with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
            self.assertTrue(self._ficha("MELI.BA")["disponible"])
            self.assertFalse(self._ficha("MELI.BA", "ars")["disponible"])

    def test_en_pesos_lo_que_no_es_cedear_es_el_mismo_por_el_mep(self):
        # Lo que no tiene papel en BYMA no se lleva a ninguna escala: SCHD (un ETF
        # que no es CEDEAR) y Bitcoin, en pesos, son ellos mismos × el MEP.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["SCHD"] = lambda i, d: 30.0
        self.yahoo.precios["BTC-USD"] = lambda i, d: 90_000.0
        for asset, ticker, esperado in (("SCHD", "SCHD", 30_000.0), ("BTC", "BTC-USD", 90_000_000.0)):
            ars = self._ficha(asset, "ars")
            self.assertEqual((ars["ticker"], ars["convertida"], ars.get("escala")), (ticker, "mep", None))
            self.assertAlmostEqual(ars["puntos"][-1]["c"], esperado, places=3)

    def _bolsa(self, datos):
        """Lo que data912 trajo de la Bolsa y el servidor tiene en memoria
        (`main._data912_en_memoria`): con eso `tecnico.serie` reconoce un CEDEAR
        de BYMA y controla la escala del estimado. Fuera de esto, vacío (conftest)."""
        return mock.patch("main._data912_en_memoria", lambda: datos, create=True)

    def test_cedear_de_byma_fuera_de_la_lista_no_es_la_accion_entera(self):
        # Procter & Gamble (PG) es CEDEAR en BYMA y no está en la lista de la app ni
        # en la tabla de ratios. La bajada lo reconoce por la lista de BYMA y baja
        # sólo la acción de afuera; el gráfico en pesos la mostraba ENTERA:
        # $ 265.455 contra $ 18.590 del CEDEAR (auditoría 06/11, H1 de la serie).
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["PG"] = lambda i, d: 150.0
        byma = {"PG": {"mercado": "arg_cedears", "c": 18590.0, "pct": 0.0}}
        with mock.patch("main._fetch_data912_equities", lambda: byma), self._bolsa(byma):
            self.assertTrue(self._ficha("PG.BA")["disponible"], "en dólares, la acción de afuera")
            ars = self._ficha("PG.BA", "ars")
            pelado = self._ficha("PG", "ars")
        self.assertEqual((ars["disponible"], ars.get("motivo")), (False, "sin_escala"))
        self.assertEqual((pelado["disponible"], pelado.get("motivo")), (False, "sin_escala"),
                         "sin el '.BA', lo reconoce la lista de BYMA de data912")
        # Pedido como el papel de BYMA («PG.BA»), es un CEDEAR aunque la lista de BYMA
        # no esté en memoria (recién reiniciado el servidor).
        with mock.patch("main._fetch_data912_equities", lambda: byma):
            self.assertEqual(self._ficha("PG.BA", "ars").get("motivo"), "sin_escala")
        # Sin la lista de BYMA y sin '.BA': una acción de EE.UU. vista en pesos.
        eeuu = self._ficha("PG", "ars")
        self.assertEqual((eeuu["ticker"], eeuu["convertida"], eeuu.get("escala")), ("PG", "mep", None))
        self.assertAlmostEqual(eeuu["puntos"][-1]["c"], 150_000.0, places=3)
        # Con su serie de BYMA vieja guardada (alguien lo tuvo): estimado con su escala.
        with main.db_abierta() as conn:
            for d in self.dias[:-14]:
                conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('PG.BA', ?, 18750.0)",
                             (d.isoformat(),))
            conn.commit()
        with mock.patch("main._fetch_data912_equities", lambda: byma), self._bolsa(byma):
            vieja = self._ficha("PG.BA", "ars")
        self.assertAlmostEqual(vieja["puntos"][-1]["c"], 18_750.0, places=3)
        self.assertAlmostEqual(vieja.get("escala"), 8.0, places=6)

    def test_la_escala_del_estimado_se_controla_con_el_precio_de_la_bolsa(self):
        # La tabla de ratios se creía sin mirar el mercado: Bioceres quedaba 25 %
        # abajo y AstraZeneca 89 % arriba con la nota «unos pocos %» (auditoría
        # 06/11, H1 de la pantalla). Con el precio del CEDEAR que el servidor ya
        # tiene de data912, la escala tiene que cerrar con la Bolsa; si no, en
        # pesos no hay gráfico.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0           # 250 × 1000 ÷ 20 = 12.500
        cedear = {"AAPL": {"mercado": "arg_cedears"}}

        def ficha_con(precio, pct=0.0):
            with mock.patch("main._fetch_data912_equities", lambda: cedear), \
                    self._bolsa({"AAPL": {"mercado": "arg_cedears", "c": precio, "pct": pct}}):
                return self._ficha("AAPL.BA", "ars")
        bien = ficha_con(13000.0)          # ~4 % arriba del estimado: el dólar de los CEDEARs
        self.assertAlmostEqual(bien["puntos"][-1]["c"], 12_500.0, places=3)
        self.assertEqual(bien.get("escala"), 20)
        otro = ficha_con(26000.0)          # la Bolsa dice 10 por acción: la tabla quedó vieja
        self.assertEqual((otro["disponible"], otro.get("motivo")), (False, "sin_escala"))
        # Un día de +30 %: con el cierre anterior (16.900 ÷ 1,30 = 13.000) cierra.
        self.assertTrue(ficha_con(16900.0, 30.0)["disponible"])

    def _guardada(self, symbol, cociente_de, precio=lambda i: 2000.0 + i):
        """Una serie en pesos que quedó guardada hasta 14 ruedas atrás (alguien la
        tuvo y la vendió): el cociente (acción de afuera × MEP ÷ CEDEAR) de la rueda
        i, de n guardadas, es `cociente_de(i, n)`."""
        dias = self.dias[:-14]
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_diarias WHERE symbol=?", (symbol,))
            for i, d in enumerate(dias):
                conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES (?, ?, ?)",
                             (symbol, d.isoformat(), precio(i) * 1000.0 / cociente_de(i, len(dias))))
            conn.commit()

    def test_un_ratio_que_cambio_al_doble_o_a_la_mitad_no_se_dibuja(self):
        # Comafi cambia ratios (SPY 20→60, GM 20→6): la serie guardada queda en la
        # escala vieja y la tabla en la nueva, o al revés. Para los dos lados.
        # (Auditoría 06/11, pruebas: una tolerancia de 150 % o de un solo lado pasaba.)
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["MELI"] = lambda i, d: 2000.0 + i
        for medida in (240.0, 60.0):          # ×2 y ÷2 de la tabla (120)
            self._guardada("MELI.BA", lambda i, n: medida)
            with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
                ars = self._ficha("MELI.BA", "ars")
            self.assertEqual((ars["disponible"], ars.get("motivo")), (False, "sin_escala"), f"{medida} contra 120")

    def test_la_brecha_normal_del_dolar_no_borra_el_grafico(self):
        # El dólar de los CEDEARs estuvo hasta ~8,6 % arriba del MEP en el último año
        # (medir_cedear_estimado.out, «A peor año»): eso no es un cambio de ratio.
        # (Auditoría 06/11, pruebas: una tolerancia de 4,5 % pasaba.)
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["MELI"] = lambda i, d: 2000.0 + i
        self._guardada("MELI.BA", lambda i, n: 120.0 * 1.08)
        with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
            ars = self._ficha("MELI.BA", "ars")
        self.assertTrue(ars["disponible"])
        self.assertAlmostEqual(ars["escala"], 129.6, places=6)

    def test_la_escala_es_la_mediana_de_las_ultimas_ruedas_guardadas(self):
        # La brecha cambia con el tiempo: hace años el cociente era 115 y en las
        # últimas ruedas guardadas 125. De las últimas 5 (por fecha), la del medio es
        # un cierre suelto (100): la mediana no lo toma; «la del medio», sí. (Auditoría
        # 06/11, pruebas: las primeras 5, 60 ruedas o sin ordenar pasaban.)
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["MELI"] = lambda i, d: 2000.0 + i
        ultimas = [125.0, 125.0, 100.0, 125.0, 125.0]
        self._guardada("MELI.BA", lambda i, n: ultimas[i - (n - 5)] if i >= n - 5 else 115.0)
        with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
            ars = self._ficha("MELI.BA", "ars")
        self.assertTrue(ars["disponible"])
        self.assertAlmostEqual(ars["escala"], 125.0, places=6)

    def test_una_accion_argentina_con_el_mismo_codigo_afuera_no_se_estima(self):
        # AGRO es Agrometal en BYMA y Adecoagro en Nueva York. Quien tiene Adecoagro
        # afuera mira su ficha en pesos (sin la marca de acción argentina) y quedó
        # guardada una serie vieja de Agrometal: «estimar» mezclaba las dos empresas,
        # $ 31 en vez de $ 14.440 (auditoría 06/11, H2 de la serie). Es Adecoagro × MEP.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["AGRO"] = lambda i, d: 10.0 + i * 0.01
        with main.db_abierta() as conn:
            for d in self.dias[:-14]:
                conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('AGRO.BA', ?, 1500.0)",
                             (d.isoformat(),))
            conn.commit()
        ars = self._ficha("AGRO", "ars")
        n = len(self.dias) - 1
        self.assertEqual((ars["ticker"], ars["convertida"], ars.get("escala")), ("AGRO", "mep", None))
        self.assertAlmostEqual(ars["puntos"][-1]["c"], (10.0 + n * 0.01) * 1000.0, places=3)

    def test_sin_escala_lo_que_mira_variaciones_sigue_mirando(self):
        # Cloudflare (NET): CEDEAR de la lista de la app, sin ratio en la tabla. La
        # ficha en pesos no tiene gráfico (y lo dice así), pero Comparar arranca todo
        # en 100 y una alerta de su promedio no depende de la escala: desaparecía de
        # Comparar y su alerta en pesos dejaba de mirar sin avisar (auditoría 06/11,
        # H4 de la serie). El mail de la alerta dice de dónde sale el precio.
        import alerts_engine as ae
        self._mep(lambda i: 1000.0 + i)
        self.yahoo.precios["NET"] = lambda i, d: 100.0 + i * 0.1
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0 + i * 0.1
        self.assertTrue(self._ficha("NET")["disponible"])
        self.assertTrue(self._ficha("AAPL")["disponible"])
        ficha = self._ficha("NET", "ars")
        self.assertEqual((ficha["disponible"], ficha.get("motivo")), (False, "sin_escala"))
        r = self.client.get("/api/comparar/precio?activos=NET,AAPL&moneda=ars&plazo=1a", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(sorted(s["clave"] for s in r.json()["series"] if s["tipo"] == "activo"), ["AAPL", "NET"])
        self.assertNotIn("NET", [f["clave"] for f in r.json()["faltan"]])
        n = len(self.dias) - 1
        with main.db_abierta() as conn:
            net = ae._serie_tecnica(conn, {"symbol": "NET", "currency": "ARS", "accion_local": 0})
            aapl = ae._serie_tecnica(conn, {"symbol": "AAPL", "currency": "ARS", "accion_local": 0})
            usd = ae._serie_tecnica(conn, {"symbol": "AAPL", "currency": "USD", "accion_local": 0})
        self.assertEqual(net.precio_de, "afuera")
        self.assertAlmostEqual(net[-1]["close"], (100.0 + n * 0.1) * (1000.0 + n), places=3)
        self.assertEqual(aapl.precio_de, "estimado")
        self.assertAlmostEqual(aapl[-1]["close"], (250.0 + n * 0.1) * (1000.0 + n) / 20, places=3)
        self.assertIsNone(usd.precio_de)
        ev = {"fecha": self.dias[-1].isoformat(), "sentido": "arriba", "cierre": 100.0, "referencia": 95.0}
        alerta = {"currency": "ARS", "senal": "media200", "accion_local": 0}
        # El aviso lleva lo que el motor le pone (`_VelasDeAlerta`): de dónde sale el
        # precio y con qué dólar. Esta base no tiene el contado con liqui: el MEP.
        self.assertEqual((net.dolar, aapl.dolar), ("mep", "mep"))
        del_net = ae._detalle_tecnico(alerta, "NET", {**ev, "precio_de": net.precio_de, "dolar": net.dolar})
        del_aapl = ae._detalle_tecnico(alerta, "AAPL", {**ev, "precio_de": aapl.precio_de, "dolar": aapl.dolar})
        self.assertIn("los de la acción de Nueva York pasados con el MEP de cada día, no los del CEDEAR", del_net)
        self.assertIn("un estimado del CEDEAR: la acción de Nueva York pasada a pesos con el MEP de cada día", del_aapl)
        self.assertNotIn("contado con liqui", del_net + del_aapl)
        self.assertNotIn("CEDEAR", ae._detalle_tecnico(alerta, "AAPL", ev))
        # Y el chat de Mervall-E no dice «no hay historia de precios»: dice qué falta.
        lect = main._lectura_tecnica_para_el_chat({"ticker": "NET.BA", "moneda": "ars"}, self.uid)
        self.assertFalse(lect["available"])
        self.assertIn("cuántos CEDEARs hacen una acción", lect["reason"])

    def test_lo_de_byma_en_memoria_vence(self):
        # `_data912_en_memoria` lee lo último que trajo data912 sin salir a la red,
        # y no lo usa si es de hace más de `DATA912_EN_MEMORIA_SEG`.
        guardado = dict(main._data912_eq_cache)
        try:
            main._data912_eq_cache.update({"data": {"AAPL": {"c": 1.0}}, "ts": time.time()})
            self.assertEqual(_DATA912_EN_MEMORIA(), {"AAPL": {"c": 1.0}})
            main._data912_eq_cache["ts"] = time.time() - main.DATA912_EN_MEMORIA_SEG - 1
            self.assertEqual(_DATA912_EN_MEMORIA(), {})
            main._data912_eq_cache.update({"data": None, "ts": time.time()})
            self.assertEqual(_DATA912_EN_MEMORIA(), {})
        finally:
            main._data912_eq_cache.clear()
            main._data912_eq_cache.update(guardado)

    def test_accion_argentina_a_pedido(self):
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0      # el ADR: otra cosa
        f = self._ficha("GGAL.BA", local=True)
        self.assertEqual((f["ticker"], f["convertida"]), ("GGAL.BA", "mep"))
        self.assertAlmostEqual(f["puntos"][-1]["c"], 5.0, places=6)
        self.assertEqual(self._pedidos("GGAL"), [], "el ADR no se baja para la acción local")
        # Un '.BA' con data912 caído (en esta prueba): un CEDEAR de la lista fija
        # de la app (XLE) se reconoce igual y se lee por su acción de afuera; su
        # serie en pesos cruda no se baja (re-test A1c, 29/10: antes no se sabía
        # que era un CEDEAR y no había lectura).
        self.yahoo.precios["XLE"] = lambda i, d: 90.0
        g = self._ficha("XLE.BA")
        self.assertEqual((g["disponible"], g["ticker"]), (True, "XLE"))
        self.assertEqual(self._pedidos("XLE.BA"), [])
        # Un '.BA' que no está en ninguna lista ni es del panel argentino: no se baja.
        z = self._ficha("ZZZZ.BA")
        self.assertEqual((z["disponible"], z["motivo"]), (False, "sin_serie"))
        self.assertEqual(self._pedidos("ZZZZ.BA"), [])
        self.yahoo.precios["YPFD.BA"] = lambda i, d: 40000.0
        self.assertTrue(self._ficha("YPFD.BA")["disponible"])

    def test_cupo_por_persona_y_por_hora(self):
        import velas_diarias
        for t in ("AMD", "INTC", "ORCL", "QCOM"):
            self.yahoo.precios[t] = lambda i, d: 10.0
        with mock.patch.object(velas_diarias, "A_PEDIDO_POR_PERSONA_HORA", 2):
            self.assertTrue(self._ficha("AMD")["disponible"])
            self.assertTrue(self._ficha("INTC")["disponible"])
            f = self._ficha("ORCL")
            self.assertEqual((f["disponible"], f["motivo"]), (False, "tope"))
            self.assertEqual(self._pedidos("ORCL"), [], "pasado el cupo no se le pide nada a Yahoo")
            # Lo ya bajado se sigue viendo: el cupo frena descargas, no lecturas.
            self.assertTrue(self._ficha("AMD")["disponible"])
        with mock.patch.object(velas_diarias, "A_PEDIDO_TODOS_HORA", 2):
            otro = self.h_admin
            r = self.client.get("/api/tecnico/ORCL", headers=otro).json()
            self.assertEqual(r.get("motivo"), "tope", "el cupo de todos juntos también frena")
        # Y el del día por persona: pasada la hora, 30 por hora no alcanzan para
        # llenar la base de a miles.
        velas_diarias._a_pedido_hechos.clear()
        with mock.patch.object(velas_diarias, "A_PEDIDO_POR_PERSONA_DIA", 3):
            velas_diarias._a_pedido_hechos.extend([(0.0, self.uid)] * 0)
            import time as _t
            hace_2h = _t.monotonic() - 7200
            velas_diarias._a_pedido_hechos.extend([(hace_2h, self.uid)] * 3)
            f = self._ficha("QCOM")
            self.assertEqual(f["motivo"], "tope")
            self.assertEqual(self._pedidos("QCOM"), [])

    def test_lo_que_falla_no_se_reintenta_enseguida(self):
        # Un ticker que la app conoce pero Yahoo no devuelve (caído, deslistado).
        f = self._ficha("SNAP")
        self.assertEqual((f["disponible"], f["motivo"]), (False, "sin_datos"))
        self._ficha("SNAP")
        self.assertEqual(len(self._pedidos("SNAP")), 1)

    def test_solo_se_baja_lo_que_la_app_conoce(self):
        # Un símbolo que ningún buscador ni el mapa ofrecen, y que no tenés ni
        # seguís, no se baja: sin esto se podía llenar la base de a miles.
        self.yahoo.precios["ZZZZ"] = lambda i, d: 5.0
        f = self._ficha("ZZZZ")
        self.assertEqual((f["disponible"], f["motivo"]), (False, "sin_datos"))
        self.assertEqual(self._pedidos("ZZZZ"), [])
        # Si lo tenés (recién cargado, antes de la noche), sí.
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "ZZZZ", "STOCK")
        self.assertTrue(self._ficha("ZZZZ")["disponible"])
        # Una cripto del mapa de calor que llega como BTC: la app la conoce.
        self.yahoo.precios["BTC-USD"] = lambda i, d: 80000.0
        self.assertTrue(self._ficha("BTC")["disponible"])
        self.assertEqual(self._ficha("AL30")["motivo"], "sin_serie")
        self.assertEqual(self._pedidos("AL30"), [], "un bono no tiene velas: ni se pide")

    def test_velas_viejas_se_ponen_al_dia_al_abrir(self):
        import velas_diarias
        self.yahoo.precios["NVDA"] = lambda i, d: 100.0
        self._ficha("NVDA")
        # Pasaron días: las últimas velas no están y el último intento fue ayer.
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_diarias WHERE symbol='NVDA' AND date >= ?",
                         (self.dias[-3].isoformat(),))
            hace = (velas_diarias._ahora_utc() - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol='NVDA'", (hace,))
            conn.commit()
        f = self._ficha("NVDA")
        self.assertEqual(f["puntos"][-1]["d"], self.dias[-1].isoformat())
        self.assertEqual(self._pedidos("NVDA")[-1], ("NVDA", "1mo", False), "sólo el último mes")

    def test_la_noche_borra_lo_que_nadie_sigue_ni_mira(self):
        import velas_diarias
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        # MELI y no NVDA: las empresas del S&P 500 son el universo del termómetro
        # (termometro.py), que baja su propio trabajo todos los días: no son
        # «lo bajado a pedido» y la noche no las poda.
        self.yahoo.precios["MELI"] = lambda i, d: 100.0
        self.yahoo.precios["AMD"] = lambda i, d: 100.0
        self._ficha("MELI")
        self._ficha("AMD")
        viejo = (velas_diarias._ahora_utc() - timedelta(days=50)).strftime("%Y-%m-%d %H:%M:%S")
        with main.db_abierta() as conn:
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol IN ('MELI')", (viejo,))
            conn.commit()
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            hay = {r["symbol"] for r in conn.execute("SELECT DISTINCT symbol FROM velas_diarias")}
            # Lo seguido nunca se borra, aunque su último intento sea viejo.
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol='MSFT'", (viejo,))
            conn.commit()
            self.assertEqual(velas_diarias._podar_a_pedido(conn, {"MSFT"}), 0)
        # Los índices se guardan siempre (velas_diarias.INDICES).
        self.assertEqual(hay, {"MSFT", "AMD", *velas_diarias.INDICES}, "MELI nadie la miró en 50 días; AMD sí")

    def test_dos_a_la_vez_bajan_una_sola_vez(self):
        import threading
        import time as _t
        import velas_diarias
        pedidos = []

        def lento(t, periodo):
            pedidos.append(t)
            _t.sleep(0.3)
            return self.yahoo(t, periodo, "1d", False, 10.0)
        self.yahoo.precios["NVDA"] = lambda i, d: 100.0

        resultados = []

        def abrir_y_anotar(uid):
            with main.db_abierta() as conn:
                resultados.append(velas_diarias.asegurar(conn, ["NVDA"], uid, bajar=lento))
        hilos = [threading.Thread(target=abrir_y_anotar, args=(u,)) for u in (1, 2, 3)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        self.assertEqual(pedidos, ["NVDA"])
        # Los que llegan mientras se baja no esperan (no ocupan un hilo del
        # servidor 10 s): la ficha dice "trayendo la historia" y vuelve a pedir.
        self.assertEqual(sorted(resultados, key=str), [None, "bajando", "bajando"])
        self.assertTrue(self._ficha("NVDA")["disponible"])


    def test_fin_de_semana_no_se_vuelve_a_bajar_lo_que_la_noche_puso_al_dia(self):
        # Lunes antes del cierre: la última vela es del viernes (3 días) y la
        # noche ya lo intentó HOY. Abrir la ficha no le pide nada a Yahoo.
        import velas_diarias
        from datetime import date as _d
        lunes = _d(2026, 10, 26)
        viernes = "2026-10-23"
        llamados = []

        def bajar(t, periodo):
            llamados.append(t)
            return pd.DataFrame()
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('MSFT', ?, 400)", (viernes,))
            conn.execute("INSERT INTO velas_estado (symbol, ultima_corrida, ultima_completa, ok) "
                         "VALUES ('MSFT', '2026-10-26 04:10:00', '2026-10-20 04:00:00', 1)")
            conn.commit()
            with mock.patch.object(velas_diarias, "_ahora_utc", lambda: _dt_utc(2026, 10, 26, 15)):
                self.assertIsNone(velas_diarias.asegurar(conn, ["MSFT"], self.uid, bajar=bajar,
                                                         hoy=lunes.isoformat()))
            self.assertEqual(llamados, [], "otra descarga hoy no puede traer nada nuevo")
            # Si la noche NO corrió hoy (último intento: el sábado), sí se baja.
            conn.execute("UPDATE velas_estado SET ultima_corrida='2026-10-24 04:00:00' WHERE symbol='MSFT'")
            conn.commit()
            with mock.patch.object(velas_diarias, "_ahora_utc", lambda: _dt_utc(2026, 10, 26, 15)):
                velas_diarias.asegurar(conn, ["MSFT"], self.uid, bajar=bajar, hoy=lunes.isoformat())
            self.assertEqual(llamados, ["MSFT"])

    def test_pesos_de_un_cedear_que_nadie_sigue_no_usa_una_serie_vieja(self):
        # Alguien tuvo MELI y la vendió: quedó MELI.BA guardada, 14 ruedas atrás.
        # La ficha en pesos no muestra esa lectura vieja: estima el CEDEAR con la
        # acción de afuera × el MEP, en la escala que tenía la serie guardada en
        # sus últimas ruedas (125: los CEDEARs se pagaban con un dólar ~4 % arriba
        # del MEP; la tabla dice 120). El estimado arranca donde terminó el
        # precio de verdad. Antes: la acción entera en pesos, 120 veces más.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["MELI"] = lambda i, d: 2000.0 + i
        guardadas = self.dias[:-14]
        with main.db_abierta() as conn:
            for i, d in enumerate(guardadas):
                # La última rueda guardada, un cierre suelto 20 % abajo (un CEDEAR
                # poco operado): la escala es la mediana de las últimas, no ese día.
                raro = 0.8 if i == len(guardadas) - 1 else 1.0
                conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('MELI.BA', ?, ?)",
                             (d.isoformat(), (2000.0 + i) * 1000.0 / 125 * raro))
            conn.commit()
        with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
            ars = self._ficha("MELI.BA", "ars")
        self.assertEqual((ars["ticker"], ars["convertida"]), ("MELI", "mep"))
        n = len(self.dias) - 1
        self.assertEqual(ars["puntos"][-1]["d"], self.dias[-1].isoformat())
        self.assertAlmostEqual(ars["puntos"][-1]["c"], (2000.0 + n) * 1000.0 / 125, places=3)
        self.assertAlmostEqual(ars.get("escala"), 125.0, places=6)
        # Podada la serie vieja (45 días sin uso: velas_diarias._podar_a_pedido),
        # queda la escala de la tabla.
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM velas_diarias WHERE symbol='MELI.BA'")
            conn.commit()
        with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
            ars = self._ficha("MELI.BA", "ars")
        self.assertAlmostEqual(ars["puntos"][-1]["c"], (2000.0 + n) * 1000.0 / 120, places=3)
        self.assertEqual(ars.get("escala"), 120)

    def test_local_a_mano_con_data912_caido_no_baja_un_cedear_en_pesos(self):
        # `local=1` lo manda la pantalla sólo para acciones argentinas, pero se
        # puede escribir a mano. Sin la lista de CEDEARs de BYMA, XLE.BA cruda
        # (sin sus cambios de ratio) quedaría guardada para todos.
        self.yahoo.precios["XLE.BA"] = lambda i, d: 30000.0
        f = self._ficha("XLE", local=True)
        self.assertFalse(f["disponible"])
        self.assertEqual(self._pedidos("XLE.BA"), [])
        # Una acción argentina conocida sí, aunque data912 no conteste.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["BMA.BA"] = lambda i, d: 9000.0
        self.assertTrue(self._ficha("BMA", local=True)["disponible"])

    def test_accion_argentina_a_pedido_ya_viene_corregida_como_de_noche(self):
        # Un precio roto de un día: la noche lo saca con la lista de cambios
        # (cambios_ratio). Bajada a pedido, la ficha tiene que mostrar LO MISMO
        # que mostraría después de la noche, no el salto hasta mañana.
        # TGSU2 pasa a valer un décimo (10 nuevas por cada vieja, como YPFD el
        # 03/08/2026): Yahoo lo anota en sus splits pero no corrige la serie en
        # pesos. La noche lo empalma con la lista de cambios (cambios_ratio).
        self._mep(lambda i: 1000.0)
        corte = len(self.dias) - 40
        self.yahoo.precios["TGSU2.BA"] = lambda i, d: 60000.0 if i < corte else 6000.0
        splits = mock.patch("cambios_ratio._splits_de_yahoo",
                            lambda t: [(self.dias[corte].isoformat(), 10.0)] if t == "TGSU2.BA" else [])
        splits.start()
        self.addCleanup(splits.stop)
        a_pedido = self._ficha("TGSU2.BA", local=True)
        # La misma serie, por el camino de la noche (alguien la tiene).
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio"):
                conn.execute(f"DELETE FROM {t}")
            conn.commit()
        self._broker("IOL", "ARS")
        self._posicion("IOL", "TGSU2", "ACCION")
        main._run_velas_diarias_job()
        de_noche = self._ficha("TGSU2", local=True)
        cierres = [p["c"] for p in de_noche["puntos"]]
        self.assertLess(max(cierres) / min(cierres), 1.5, "de noche, sin el salto falso")
        self.assertEqual([p["c"] for p in a_pedido["puntos"]], cierres)

    def test_admin_muestra_la_corrida_de_la_noche_no_la_ultima_ficha(self):
        import velas_diarias
        self._broker("Schwab", "USD")
        self._posicion("Schwab", "MSFT", "STOCK")
        self.yahoo.precios["MSFT"] = lambda i, d: 400.0
        self.yahoo.precios["NVDA"] = lambda i, d: 100.0
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            conn.execute("UPDATE velas_estado SET ultima_corrida='2026-01-01 03:00:00' WHERE symbol=?",
                         (velas_diarias.MARCA_CORRIDA_NOCHE,))
            conn.commit()
        self._ficha("NVDA")                      # una ficha a pedido, hoy
        self._ficha("ZZZZ")                      # un símbolo que no existe
        e = self.client.get("/api/admin/velas", headers=self.h_admin).json()
        self.assertEqual(e["ultima_corrida"], "2026-01-01 03:00:00",
                         "si la noche dejó de correr, la última ficha abierta no lo tapa")
        # MSFT y los índices, que se guardan siempre (velas_diarias.INDICES:
        # contra el S&P 500 se compara «Cuánto se mueve»; contra los dos,
        # «Simular una cartera»); ni NVDA ni ZZZZ, que sólo se abrieron.
        self.assertEqual((e["activos"], e["sin_historia"]), (1 + len(velas_diarias.INDICES), 0),
                         "sólo lo que se sigue")


if __name__ == "__main__":
    unittest.main()
