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

import pandas as pd
from fastapi.testclient import TestClient

import main
import estructura
import tecnico
from fechas import hoy_art_date


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
        self.pedidos.append((ticker, period, auto_adjust))
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
        # En el medio de un ir y venir parejo: posición ~0,5, ancho como siempre.
        quieto = tecnico.lectura(velas[:-1])
        self.assertAlmostEqual(quieto["bb_posicion"], 0.5, delta=0.3)
        self.assertAlmostEqual(quieto["bb_ancho_relativo"], 1.0, places=6)
        # Un precio que no se movió: las bandas no se separan, no hay posición.
        plano = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "close": 50.0} for i in range(100)]
        self.assertIsNone(tecnico.lectura(plano)["bb_posicion"])
        self.assertIsNone(tecnico.lectura(plano)["bb_ancho_relativo"])
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
        # Pocos días: no inventa.
        corto = tecnico.lectura(velas[:20])
        self.assertIsNone(corto["mov_dia"])
        self.assertIsNone(corto["mov_mes"])
        self.assertIsNone(tecnico.lectura(velas[:100])["mov_dia_anio"])
        # Un precio quieto se movió 0, no «sin datos».
        plano = [{"date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "close": 50.0} for i in range(60)]
        self.assertEqual(tecnico.lectura(plano)["mov_dia"], 0.0)

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
                      "brokers", "fx_rates_daily"):
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
        # memoria) ni corridos un día. Desde d6ae4dc3 el gráfico trae los 3 años
        # guardados (arranca en la primera vela), así que se mira que cada punto,
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
        self.assertEqual((e["activos"], e["ok"]), (2, 1))
        self.assertEqual([f["symbol"] for f in e["fallados"]], ["NOEXISTE"])
        self.assertEqual(e["filas"], 760)
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
        dias = [hoy - timedelta(days=k) for k in range(1200, 0, -1)]  # todos los días
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
        # El gráfico trae todo lo guardado: 3 años de CALENDARIO, no 3 × 252 velas.
        self.assertGreater(f["puntos"][0]["d"], (hoy - timedelta(days=tecnico.DIAS_GRAFICO + 1)).isoformat())
        self.assertLess(f["puntos"][0]["d"], (hoy - timedelta(days=3 * 365 - 5)).isoformat(), "3 años de calendario")

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
        self.assertIn(("BRK-B", "3y", False), self._pedidos("BRK-B"), "la noche la sigue (3 años de velas)")
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
        self.assertEqual((e["seguidos"], e["atrasados"], e["fallados"]), (1, [], []))


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
        self.assertEqual(self._pedidos("NVDA"), [("NVDA", "3y", False)])
        # La segunda vez (o la de otra persona) ya está guardada: no se pide de nuevo.
        self._ficha("NVDA")
        self._ficha("NVDA", "ars")
        self.assertEqual(len(self._pedidos("NVDA")), 1)

    def test_cedear_a_pedido_baja_solo_la_accion_de_afuera(self):
        # La serie en pesos de un CEDEAR necesita la lista de cambios de ratio,
        # que se arma de noche sólo para lo seguido: a pedido va la de afuera y
        # en pesos se multiplica por el MEP de cada día.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["AAPL"] = lambda i, d: 250.0
        self.yahoo.precios["AAPL.BA"] = lambda i, d: 25000.0
        with mock.patch("main._fetch_data912_equities", lambda: {"AAPL": {"mercado": "arg_cedears"}}):
            usd = self._ficha("AAPL.BA")
            ars = self._ficha("AAPL.BA", "ars")
        self.assertEqual((usd["ticker"], usd["convertida"]), ("AAPL", None))
        self.assertEqual((ars["ticker"], ars["convertida"]), ("AAPL", "mep"))
        self.assertAlmostEqual(ars["puntos"][-1]["c"], 250_000.0, places=3)
        self.assertEqual(self._pedidos("AAPL.BA"), [])

    def test_accion_argentina_a_pedido(self):
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0      # el ADR: otra cosa
        f = self._ficha("GGAL.BA", local=True)
        self.assertEqual((f["ticker"], f["convertida"]), ("GGAL.BA", "mep"))
        self.assertAlmostEqual(f["puntos"][-1]["c"], 5.0, places=6)
        self.assertEqual(self._pedidos("GGAL"), [], "el ADR no se baja para la acción local")
        # Un '.BA' sin saber si es CEDEAR (data912 caído en esta prueba) no se
        # baja, salvo que sea una acción argentina conocida.
        g = self._ficha("XLE.BA")
        self.assertEqual((g["disponible"], g["motivo"]), (False, "sin_serie"))
        self.assertEqual(self._pedidos("XLE.BA"), [])
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
        self.yahoo.precios["NVDA"] = lambda i, d: 100.0
        self.yahoo.precios["AMD"] = lambda i, d: 100.0
        self._ficha("NVDA")
        self._ficha("AMD")
        viejo = (velas_diarias._ahora_utc() - timedelta(days=50)).strftime("%Y-%m-%d %H:%M:%S")
        with main.db_abierta() as conn:
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol IN ('NVDA')", (viejo,))
            conn.commit()
        main._run_velas_diarias_job()
        with main.db_abierta() as conn:
            hay = {r["symbol"] for r in conn.execute("SELECT DISTINCT symbol FROM velas_diarias")}
            # Lo seguido nunca se borra, aunque su último intento sea viejo.
            conn.execute("UPDATE velas_estado SET ultima_corrida=? WHERE symbol='MSFT'", (viejo,))
            conn.commit()
            self.assertEqual(velas_diarias._podar_a_pedido(conn, {"MSFT"}), 0)
        self.assertEqual(hay, {"MSFT", "AMD"}, "NVDA nadie la miró en 50 días; AMD sí")

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
        # Alguien tuvo MELI y la vendió: quedó MELI.BA guardada, 20 días atrás.
        self._mep(lambda i: 1000.0)
        self.yahoo.precios["MELI"] = lambda i, d: 2000.0
        with main.db_abierta() as conn:
            for d in self.dias[-300:-14]:
                conn.execute("INSERT INTO velas_diarias (symbol, date, close) VALUES ('MELI.BA', ?, 99.0)",
                             (d.isoformat(),))
            conn.commit()
        with mock.patch("main._fetch_data912_equities", lambda: {"MELI": {"mercado": "arg_cedears"}}):
            ars = self._ficha("MELI.BA", "ars")
        self.assertEqual((ars["ticker"], ars["convertida"]), ("MELI", "mep"))
        self.assertEqual(ars["puntos"][-1]["d"], self.dias[-1].isoformat())
        self.assertAlmostEqual(ars["puntos"][-1]["c"], 2_000_000.0, places=3)

    def test_local_a_mano_con_data912_caido_no_baja_un_cedear_en_pesos(self):
        # `local=1` lo manda la pantalla sólo para acciones argentinas, pero se
        # puede escribir a mano. Sin la lista de CEDEARs de BYMA, XLE.BA cruda
        # (sin sus cambios de ratio) quedaría guardada para todos.
        self.yahoo.precios["XLE.BA"] = lambda i, d: 30000.0
        f = self._ficha("XLE", local=True)
        self.assertEqual((f["disponible"], f["motivo"]), (False, "sin_serie"))
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
        self.assertEqual((e["activos"], e["sin_historia"]), (1, 0), "sólo lo que se sigue")


if __name__ == "__main__":
    unittest.main()
