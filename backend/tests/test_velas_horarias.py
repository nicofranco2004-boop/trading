"""Velas de 1 hora y de 4 horas del gráfico técnico (velas_horarias.py +
GET /api/tecnico/{asset}/horas).

Entra por el camino de producción: la ficha pide primero su gráfico diario
(GET /api/tecnico/{asset}, que baja las velas diarias a pedido) y después, al
elegir 1H o 4H, el pedido de horas. Yahoo se reemplaza en su punto más bajo
(`pricing.yahoo._historia`), así pasan por `pricing.yahoo.descargar` como en
producción. El reloj del módulo (`velas_horarias._ahora`) queda fijo.

Lo que importa:
  · las velas se cortan como TradingView: Nueva York 9:30–13:30 y 13:30–16:00
    (también después del cambio de hora); BYMA desde la pre-apertura de las
    10:30 (1 hora: 10:30, 11:30…; 4 horas: 10:30–14:30 y 14:30–17:00), con las
    de 30 minutos de Yahoo; cripto cada 4 horas desde las 00:00 UTC;
  · la vela en curso es la ÚLTIMA y sólo ella lleva `enCurso`;
  · la media de 200 cuenta 200 HORAS (velas), no días;
  · una acción argentina en dólares va dividida por el MEP de SU día;
  · a Yahoo se le pide una vez por ticker y se comparte: la historia cada 10
    minutos, lo reciente cada 60 s; `desde` trae sólo la cola.

Corre con: cd backend && python3 -m pytest tests/test_velas_horarias.py
"""
import os
import sys
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
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
import velas_horarias
from fechas import hoy_art_date

NY, BA = "America/New_York", "America/Argentina/Buenos_Aires"
# El momento de las pruebas: jueves 29/10/2026, 18:10 UTC = 15:10 en Buenos
# Aires = 14:10 en Nueva York (todavía en horario de verano).
AHORA = datetime(2026, 10, 29, 18, 10, tzinfo=timezone.utc).timestamp()


def _ruedas(hasta, n):
    out, d = [], hasta - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _hora(dia, hh, mm, zona):
    return pd.Timestamp(datetime(dia.year, dia.month, dia.day, hh, mm)).tz_localize(zona)


class YahooFalso:
    """Velas diarias de precio fijo para el gráfico diario y, para las de 1
    hora y las de 30 minutos, las que la prueba ponga en `horas[ticker]` y
    `medias[ticker]`: [(Timestamp, o, h, l, c, v)]."""

    def __init__(self, hoy):
        self.hoy, self.horas, self.medias, self.pedidos = hoy, {}, {}, []

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        self.pedidos.append((ticker, period, interval))
        if interval == "1d":
            dias = _ruedas(self.hoy, 760 if period == "3y" else 22)
            c = 5000.0 if ticker.endswith(".BA") else 100.0
            idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dias])
            return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1000.0},
                                index=idx)
        filas = sorted((self.medias if interval == "30m" else self.horas).get(ticker, []), key=lambda f: f[0])
        if period == "2d":
            # Yahoo: las dos últimas ruedas (en cripto, desde ayer a las 00:00 UTC).
            dias = sorted({f[0].date() for f in filas})[-2:]
            filas = [f for f in filas if f[0].date() in dias]
        if not filas:
            return pd.DataFrame()
        idx = pd.DatetimeIndex([f[0] for f in filas])
        o, h, l, c, v = zip(*[f[1:] for f in filas])
        return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c, "Volume": v}, index=idx)


def _horas_ny(dias, hasta_ultimo=None):
    """De 9:30 a 15:30 hora de Nueva York, una por hora; el último día hasta
    `hasta_ultimo` (hora local, inclusive). Precio: sube 1 por vela."""
    out, k = [], 0
    for n, dia in enumerate(dias):
        for hh in range(9, 16):
            if n == len(dias) - 1 and hasta_ultimo is not None and hh > hasta_ultimo:
                break
            o = 100.0 + k
            out.append((_hora(dia, hh, 30, NY), o, o + 2, o - 1, o + 1, 10.0))
            k += 1
    return out


class HorasTest(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'free')", (f"horas-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.yahoo = YahooFalso(hoy_art_date())
        self.ahora = AHORA
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("velas_horarias._ahora", lambda: self.ahora),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        import velas_diarias
        velas_diarias._a_pedido_hechos.clear()
        velas_horarias._CACHE.clear()
        velas_horarias._ARMADAS.clear()
        velas_horarias._FALLAS.clear()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _ficha(self, asset, local=False, moneda="usd"):
        """Lo que hace la pantalla al abrir la ficha: el gráfico diario primero."""
        r = self.client.get(f"/api/tecnico/{asset}?moneda={moneda}{'&local=1' if local else ''}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["disponible"], r.json())

    def _horas(self, asset, cada, local=False, moneda="usd", desde=None):
        q = f"cada={cada}&moneda={moneda}{'&local=1' if local else ''}{f'&desde={desde}' if desde is not None else ''}"
        r = self.client.get(f"/api/tecnico/{asset}/horas?{q}", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _mep(self, por_dia):
        with main.db_abierta() as conn:
            hoy = hoy_art_date()
            # Un dólar para los últimos días, así el gráfico diario en dólares existe.
            for k in range(15):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?, ?, ?) "
                             "ON CONFLICT(date) DO NOTHING", ((hoy - timedelta(days=k)).isoformat(), 1100.0, 1000.0))
            for d, mep in por_dia.items():
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?, ?, ?) "
                             "ON CONFLICT(date) DO UPDATE SET mep_venta = excluded.mep_venta, "
                             "blue_venta = excluded.blue_venta", (d, mep * 1.1, mep))
            conn.commit()

    # ── Nueva York ───────────────────────────────────────────────────────────

    def test_nueva_york_1h_y_4h_como_tradingview(self):
        dias = [date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29)]
        self.yahoo.horas["AAPL"] = _horas_ny(dias, hasta_ultimo=13)   # el 29, hasta la de 13:30
        self._ficha("AAPL")

        h1 = self._horas("AAPL", "1h")
        self.assertTrue(h1["disponible"])
        self.assertEqual((h1["ticker"], h1["mercado"], h1["convertida"]), ("AAPL", "us", None))
        self.assertEqual(len(h1["puntos"]), 7 + 7 + 5)
        p0 = h1["puntos"][0]
        self.assertEqual(p0["d"], "2026-10-27")
        self.assertEqual(p0["t"], int(_hora(dias[0], 9, 30, NY).timestamp()))
        self.assertEqual((p0["o"], p0["h"], p0["l"], p0["c"], p0["v"]), (100.0, 102.0, 99.0, 101.0, 10.0))
        # La hora en curso (13:30 a 14:30 de Nueva York; son las 14:10) es la
        # última y la única marcada.
        self.assertTrue(h1["puntos"][-1].get("enCurso"))
        self.assertEqual(h1["puntos"][-1]["t"], int(_hora(dias[2], 13, 30, NY).timestamp()))
        self.assertEqual([p for p in h1["puntos"] if p.get("enCurso")], [h1["puntos"][-1]])
        self.assertEqual(h1["sesion"]["velas_por_dia"], 7)
        self.assertEqual(h1["sesion"]["desfase"], -240, "Nueva York en verano: UTC−4")

        h4 = self._horas("AAPL", "4h")
        inicios = [(p["d"], datetime.fromtimestamp(p["t"], timezone.utc).astimezone(
            pd.Timestamp.now(tz=NY).tz).strftime("%H:%M")) for p in h4["puntos"]]
        self.assertEqual(inicios, [("2026-10-27", "09:30"), ("2026-10-27", "13:30"),
                                   ("2026-10-28", "09:30"), ("2026-10-28", "13:30"),
                                   ("2026-10-29", "09:30"), ("2026-10-29", "13:30")])
        # 9:30–13:30 del 27: las horas 0 a 3 (apertura 100, cierres 101..104).
        b = h4["puntos"][0]
        self.assertEqual((b["o"], b["h"], b["l"], b["c"], b["v"]), (100.0, 105.0, 99.0, 104.0, 40.0))
        # 13:30–16:00 del 27: las horas 4 a 6 (tres, la última de media hora).
        b = h4["puntos"][1]
        self.assertEqual((b["o"], b["h"], b["l"], b["c"], b["v"]), (104.0, 108.0, 103.0, 107.0, 30.0))
        # El bloque en curso del 29 tiene sólo la hora en curso, y es el último.
        b = h4["puntos"][-1]
        self.assertTrue(b.get("enCurso"))
        self.assertEqual((b["o"], b["c"], b["v"]), (118.0, 119.0, 10.0))
        self.assertFalse(h4["puntos"][-2].get("enCurso"))
        self.assertEqual(h4["sesion"]["velas_por_dia"], 2)
        # Una sola descarga de 1 hora sirvió para 1H y para 4H.
        self.assertEqual([p for p in self.yahoo.pedidos if p[2] == "1h"], [("AAPL", "730d", "1h")])

    def test_nueva_york_despues_del_cambio_de_hora(self):
        # El 1/11/2026 Nueva York pasa a UTC−5: los bloques siguen arrancando a
        # las 9:30 de allá (14:30 UTC en vez de 13:30).
        dias = [date(2026, 10, 30), date(2026, 11, 2)]
        self.yahoo.horas["AAPL"] = _horas_ny(dias)
        self.ahora = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc).timestamp()   # antes de abrir
        self._ficha("AAPL")
        h4 = self._horas("AAPL", "4h")
        utc = [datetime.fromtimestamp(p["t"], timezone.utc).strftime("%d %H:%M") for p in h4["puntos"]]
        self.assertEqual(utc, ["30 13:30", "30 17:30", "02 14:30", "02 18:30"])
        self.assertFalse(any(p.get("enCurso") for p in h4["puntos"]), "con la rueda cerrada no hay vela en curso")
        self.assertEqual(h4["sesion"]["desfase"], -300)

    # ── BYMA ─────────────────────────────────────────────────────────────────

    def test_byma_cortada_como_tradingview_desde_las_10_30(self):
        # Medido el 30/10 contra BCBA:GGAL: TradingView corta BYMA desde la
        # pre-apertura de las 10:30. Yahoo da 1 hora a la hora en punto, así que
        # lo que hay de a 30 minutos (60 días) se junta desde las 10:30. Los
        # días de antes (el 26) quedan con las de 1 hora.
        self.yahoo.horas["GGAL.BA"] = [(_hora(date(2026, 10, 26), hh, 0, BA), 4000.0 + hh, 4010.0 + hh, 3990.0 + hh, 4005.0 + hh, 10.0)
                                       for hh in range(11, 17)]
        # De a 30 minutos, el 28 entero y el 29 hasta la de 15:00 (son las 15:10).
        medias, k = [], 0
        for dia, hasta in ((date(2026, 10, 28), 17 * 60), (date(2026, 10, 29), 15 * 60 + 1)):
            for m in range(11 * 60, hasta, 30):
                o = 5000.0 + k
                medias.append((_hora(dia, m // 60, m % 60, BA), o, o + 5, o - 5, o + 1, 100.0))
                k += 1
        self.yahoo.medias["GGAL.BA"] = medias
        # (Yahoo también tiene esos días de a 1 hora: no se usan.)
        self.yahoo.horas["GGAL.BA"] += [(_hora(d, hh, 0, BA), 1.0, 1.0, 1.0, 1.0, 1.0)
                                        for d in (date(2026, 10, 28), date(2026, 10, 29)) for hh in range(11, 16)]
        self._ficha("GGAL", local=True, moneda="ars")
        hora_ar = lambda p: (p["d"], datetime.fromtimestamp(p["t"] - 3 * 3600, timezone.utc).strftime("%H:%M"))   # noqa: E731

        h1 = self._horas("GGAL", "1h", local=True, moneda="ars")
        self.assertEqual((h1["ticker"], h1["mercado"], h1["convertida"]), ("GGAL.BA", "byma", None))
        self.assertEqual([hora_ar(p) for p in h1["puntos"]],
                         [("2026-10-26", f"{hh}:00") for hh in range(11, 17)]
                         + [("2026-10-28", x) for x in ("10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:30")]
                         + [("2026-10-29", x) for x in ("10:30", "11:30", "12:30", "13:30", "14:30")])
        p = {hora_ar(x): x for x in h1["puntos"]}
        # 10:30–11:30: sólo la de 11:00 (la subasta de 10:30 no viene en Yahoo).
        b = p[("2026-10-28", "10:30")]
        self.assertEqual((b["o"], b["h"], b["l"], b["c"], b["v"]), (5000.0, 5005.0, 4995.0, 5001.0, 100.0))
        # 11:30–12:30: la de 11:30 y la de 12:00.
        b = p[("2026-10-28", "11:30")]
        self.assertEqual((b["o"], b["h"], b["l"], b["c"], b["v"]), (5001.0, 5007.0, 4996.0, 5003.0, 200.0))
        # 16:30–17:00: media hora.
        b = p[("2026-10-28", "16:30")]
        self.assertEqual((b["o"], b["c"], b["v"]), (5011.0, 5012.0, 100.0))
        self.assertTrue(h1["puntos"][-1].get("enCurso"), "son las 15:10: la hora de 14:30 a 15:30 está en curso")
        self.assertEqual(h1["sesion"]["abre"], 10 * 60 + 30)
        self.assertEqual(h1["sesion"]["velas_por_dia"], 7)
        self.assertEqual(h1["sesion"]["desfase"], -180)

        h4 = self._horas("GGAL", "4h", local=True, moneda="ars")
        self.assertEqual([hora_ar(p) for p in h4["puntos"]],
                         [("2026-10-26", "10:30"), ("2026-10-26", "14:30"),
                          ("2026-10-28", "10:30"), ("2026-10-28", "14:30"),
                          ("2026-10-29", "10:30"), ("2026-10-29", "14:30")])
        b = h4["puntos"][3]   # 28/10 de 14:30 a 17:00: de a 30 min, de las 14:30 a las 16:30
        self.assertEqual((b["o"], b["h"], b["l"], b["c"], b["v"]), (5007.0, 5016.0, 5002.0, 5012.0, 500.0))
        self.assertTrue(h4["puntos"][-1].get("enCurso"), "el bloque de 14:30 a 17:00 está en curso")
        self.assertEqual(h4["sesion"]["velas_por_dia"], 2)
        # Lo reciente (cada 60 s) también viene de a 30 minutos, con el mismo corte.
        self.ahora += 61
        self._horas("GGAL", "1h", local=True, moneda="ars")
        self.assertIn(("GGAL.BA", "2d", "30m"), self.yahoo.pedidos)

    def test_accion_argentina_en_dolares_con_el_mep_de_su_dia(self):
        dias = [date(2026, 10, 27), date(2026, 10, 28)]
        self.yahoo.horas["GGAL.BA"] = [(_hora(d, hh, 0, BA), 6000.0, 6060.0, 5940.0, 6000.0, 1.0)
                                       for d in dias for hh in range(11, 17)]
        self._mep({"2026-10-27": 1000.0, "2026-10-28": 1200.0})
        self._ficha("GGAL", local=True)
        h1 = self._horas("GGAL", "1h", local=True)
        self.assertEqual((h1["ticker"], h1["convertida"]), ("GGAL.BA", "mep"))
        por_dia = {p["d"]: p for p in h1["puntos"]}
        self.assertAlmostEqual(por_dia["2026-10-27"]["c"], 6.0, places=6)
        self.assertAlmostEqual(por_dia["2026-10-28"]["c"], 5.0, places=6)
        self.assertAlmostEqual(por_dia["2026-10-28"]["h"], 5.05, places=6, msg="la vela entera, con el dólar de su día")

    # ── Cripto ───────────────────────────────────────────────────────────────

    def test_cripto_cada_4_horas_desde_las_0_utc_y_la_media_de_200_horas(self):
        inicio = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)   # empieza a las 3 UTC, a mitad de un bloque
        n = int((AHORA - inicio.timestamp()) // 3600) + 1            # hasta la hora en curso (18:00 del 29)
        self.yahoo.horas["BTC-USD"] = [(pd.Timestamp(inicio + timedelta(hours=k)), k + 1.0, k + 1.5, k + 0.5, k + 1.0, 1.0)
                                       for k in range(n)]
        self._ficha("BTC")
        h1 = self._horas("BTC", "1h")
        self.assertEqual((h1["mercado"], len(h1["puntos"])), ("cripto", n))
        self.assertTrue(h1["puntos"][-1].get("enCurso"))
        self.assertEqual(h1["puntos"][-1]["t"], int(datetime(2026, 10, 29, 18, tzinfo=timezone.utc).timestamp()))
        # La media de 200 de 1 hora son 200 HORAS: la de la vela 200 es el
        # promedio de los cierres 1..200; antes no hay.
        self.assertIsNone(h1["puntos"][198]["s200"])
        self.assertAlmostEqual(h1["puntos"][199]["s200"], 100.5, places=6)
        self.assertAlmostEqual(h1["puntos"][-1]["s200"], sum(range(n - 199, n + 1)) / 200, places=4)
        self.assertAlmostEqual(h1["puntos"][-1]["s50"], sum(range(n - 49, n + 1)) / 50, places=4)
        self.assertIsNotNone(h1["puntos"][-1]["rsi"])
        self.assertIsNotNone(h1["puntos"][-1]["bb_arriba"])
        self.assertEqual(h1["sesion"], {"abre": 0, "cierra": 1440, "desfase": 0, "todos_los_dias": True,
                                        "velas_por_dia": 24})

        h4 = self._horas("BTC", "4h")
        horas = {datetime.fromtimestamp(p["t"], timezone.utc).hour for p in h4["puntos"]}
        self.assertEqual(horas, {0, 4, 8, 12, 16, 20})
        # El primer bloque (0 a 4 UTC del 17) arranca a las 3: tiene sólo esa hora.
        self.assertEqual((h4["puntos"][0]["o"], h4["puntos"][0]["c"]), (1.0, 1.0))
        # El último (16 a 20 UTC del 29) tiene las horas 16, 17 y 18, en curso.
        ultimo = h4["puntos"][-1]
        self.assertEqual(datetime.fromtimestamp(ultimo["t"], timezone.utc).hour, 16)
        self.assertEqual((ultimo["o"], ultimo["c"], ultimo["v"]), (float(n - 2), float(n), 3.0))
        self.assertTrue(ultimo.get("enCurso"))
        # 4H: la media de 200 cuenta bloques; con ~75 bloques no hay.
        self.assertTrue(all(p["s200"] is None for p in h4["puntos"]))

    # ── Memoria compartida, refresco y `desde` ───────────────────────────────

    def test_se_pide_una_vez_y_lo_reciente_cada_60_s(self):
        dias = [date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29)]
        self.yahoo.horas["AAPL"] = _horas_ny(dias, hasta_ultimo=13)
        self._ficha("AAPL")
        a = self._horas("AAPL", "1h")
        b = self._horas("AAPL", "4h")
        de_horas = lambda: [p for p in self.yahoo.pedidos if p[2] == "1h"]   # noqa: E731
        self.assertEqual(de_horas(), [("AAPL", "730d", "1h")], "1H y 4H, una sola descarga")
        self.assertEqual(a["actualizada"], b["actualizada"])

        # Pasan 61 s: la hora en curso se movió (Yahoo la manda con otro cierre).
        ult = self.yahoo.horas["AAPL"][-1]
        self.yahoo.horas["AAPL"][-1] = (ult[0], ult[1], ult[2] + 3, ult[3], ult[4] + 3, 25.0)
        self.ahora += 61
        c = self._horas("AAPL", "1h")
        self.assertEqual(de_horas()[-1], ("AAPL", "2d", "1h"), "lo reciente, no la historia")
        self.assertEqual(len(de_horas()), 2)
        self.assertEqual(c["puntos"][-1]["c"], ult[4] + 3)
        self.assertEqual(c["puntos"][-1]["v"], 25.0)
        self.assertEqual(len(c["puntos"]), len(a["puntos"]), "reemplaza la hora en curso, no la duplica")
        self.assertNotEqual(c["actualizada"], a["actualizada"])

        # Empieza la hora siguiente: aparece una vela nueva y la anterior deja de estar en curso.
        nueva = _hora(dias[2], 14, 30, NY)
        self.yahoo.horas["AAPL"].append((nueva, 200.0, 201.0, 199.0, 200.5, 5.0))
        self.ahora = nueva.timestamp() + 30
        d = self._horas("AAPL", "1h", desde=c["puntos"][-1]["t"])
        self.assertEqual([p["t"] for p in d["puntos"]], [c["puntos"][-1]["t"], int(nueva.timestamp())],
                         "`desde`: la vela que tenía la pantalla y la nueva")
        self.assertFalse(d["puntos"][0].get("enCurso"))
        self.assertTrue(d["puntos"][1].get("enCurso"))

        # A los 10 minutos se vuelve a bajar la historia entera.
        self.ahora += velas_horarias.TTL_HISTORIA_SEG
        self._horas("AAPL", "1h")
        self.assertEqual(de_horas()[-1], ("AAPL", "730d", "1h"))

    def test_las_cuentas_dan_lo_mismo_que_con_toda_la_historia_y_se_comparten(self):
        # ~2.900 horas de una cripto: se manda las últimas 1.000 y se calcula con
        # 600 de antes. Tiene que dar lo MISMO que calcular con todo (el RSI y el
        # ADX arrastran memoria: con pocas de antes darían otro número).
        import math
        import tecnico
        inicio = datetime(2026, 7, 1, tzinfo=timezone.utc)
        n = int((AHORA - inicio.timestamp()) // 3600) + 1
        precio = lambda k: 100 + 10 * math.sin(k / 30) + 4 * math.sin(k / 7) + k * 0.01   # noqa: E731
        self.yahoo.horas["BTC-USD"] = [(pd.Timestamp(inicio + timedelta(hours=k)), precio(k), precio(k) * 1.01,
                                        precio(k) * 0.99, precio(k), 1.0) for k in range(n)]
        self._ficha("BTC")
        with mock.patch("tecnico.indicadores", wraps=tecnico.indicadores) as cuentas:
            r = self._horas("BTC", "1h")
            self._horas("BTC", "1h")                                   # otra persona, el mismo minuto
            cola = self._horas("BTC", "1h", desde=r["puntos"][-2]["t"])  # el refresco de la pantalla
        self.assertEqual(cuentas.call_count, 1, "lo armado se comparte mientras Yahoo no traiga nada nuevo")
        self.assertEqual([p["t"] for p in cola["puntos"]], [p["t"] for p in r["puntos"][-2:]])
        self.assertTrue(cola["puntos"][-1].get("enCurso"))
        self.assertEqual(len(r["puntos"]), velas_horarias.VELAS_A_LA_PANTALLA)
        todas = [{"date": "x", "open": precio(k), "high": precio(k) * 1.01, "low": precio(k) * 0.99,
                  "close": precio(k), "volume": 1.0} for k in range(n)]
        esperado = tecnico.puntos_del_grafico(todas, tecnico.indicadores(todas), n - velas_horarias.VELAS_A_LA_PANTALLA)
        sin = lambda p: {k: v for k, v in p.items() if k not in ("d", "t", "enCurso")}   # noqa: E731
        self.assertEqual([sin(p) for p in r["puntos"]], [sin(p) for p in esperado])
        self.assertIsNotNone(r["puntos"][0]["s200"], "la primera que se ve ya tiene sus 200 horas de antes")

    def test_un_dibujo_hecho_en_1h_guarda_su_hora(self):
        # Lo dibujado en 1H/4H guarda el día (para las diarias y los avisos) y
        # el momento exacto (`t`). Sin `t` en el servidor, al volver a abrir la
        # ficha la línea caía a la primera hora de ese día.
        t = int(_hora(date(2026, 10, 28), 10, 30, NY).timestamp())
        linea = {"id": "d1", "tipo": "tendencia", "a": {"d": "2026-10-27", "mas": 0, "t": t - 86400, "precio": 100.0},
                 "b": {"d": "2026-10-28", "mas": 0, "t": t, "precio": 110.0}}
        r = self.client.put("/api/tecnico/AAPL/dibujos?moneda=usd", json={"dibujos": [linea]}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        vuelta = self.client.get("/api/tecnico/AAPL/dibujos?moneda=usd", headers=self.h).json()["dibujos"]
        self.assertEqual(vuelta[0]["b"], {"d": "2026-10-28", "mas": 0, "t": t, "precio": 110.0})
        for malo in (-5, 1.5, "ayer", 10**12):
            mal = {**linea, "b": {**linea["b"], "t": malo}}
            r = self.client.put("/api/tecnico/AAPL/dibujos?moneda=usd", json={"dibujos": [mal]}, headers=self.h)
            self.assertEqual(r.status_code, 422, malo)

    def test_lo_que_no_hay_no_se_inventa(self):
        # Sin gráfico diario (un activo que no existe): nada.
        r = self._horas("ZZZZ", "1h")
        self.assertEqual((r["disponible"], r["motivo"]), (False, "sin_serie"))
        # Con gráfico diario pero Yahoo sin velas de 1 hora: tampoco, y no se
        # le vuelve a pedir en el minuto siguiente.
        self._ficha("AAPL")
        r = self._horas("AAPL", "1h")
        self.assertEqual((r["disponible"], r["motivo"]), (False, "sin_datos"))
        self._horas("AAPL", "4h")
        self.assertEqual(len([p for p in self.yahoo.pedidos if p[2] == "1h"]), 1)
        # Una hora con el máximo roto (por debajo del cierre) va sólo con el cierre.
        self.ahora += velas_horarias.ESPERA_TRAS_FALLA_SEG + velas_horarias.TTL_HISTORIA_SEG
        self.yahoo.horas["AAPL"] = [(_hora(date(2026, 10, 28), 9, 30, NY), 100.0, 99.0, 98.0, 101.0, 1.0),
                                    (_hora(date(2026, 10, 28), 10, 30, NY), float("nan"), float("nan"), float("nan"), float("nan"), 0.0)]
        r = self._horas("AAPL", "1h")
        self.assertEqual(len(r["puntos"]), 1, "sin cierre no hay vela")
        self.assertEqual((r["puntos"][0]["h"], r["puntos"][0]["l"], r["puntos"][0]["c"]), (None, None, 101.0))
        # Pedidos inválidos.
        self.assertEqual(self.client.get("/api/tecnico/AAPL/horas?cada=15m", headers=self.h).status_code, 400)
        self.assertEqual(self.client.get("/api/tecnico/<x>/horas?cada=1h", headers=self.h).status_code, 400)
        self.assertEqual(self.client.get("/api/tecnico/AAPL/horas?cada=1h&desde=-5", headers=self.h).status_code, 400)
        self.assertEqual(self.client.get("/api/tecnico/AAPL/horas?cada=1h").status_code, 401)


if __name__ == "__main__":
    unittest.main()
