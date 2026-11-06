"""Simular una cartera (cartera_simulada.py): US$ 100 repartidos, comprados el
primer día y sin tocar, al lado del S&P 500 y del Nasdaq.

Lo que importa:
  · La cuenta: cada activo en 100 con LA regla del comparador (`comparar.base_cien`)
    y la cartera, la suma de cada uno por su peso. Un activo solo, al 100 %, da
    exactamente su serie en 100 (diferencial contra el canónico).
  · Sin tocarla: el que sube más que el resto pesa cada vez más; los aportes
    suman el resultado (también con pesos que suman 99,99: se llevan a 100).
  · Los días son los de cualquier activo; el que no cotizó vale su último cierre.
  · Arranca cuando existe el último en llegar, y lo dice; un activo sin precios
    de la última semana no se simula; un índice que falta no frena la cartera.
  · Sin comisiones ni dividendos: un activo quieto da 0 %.
  · La ruta pasa por el freno y simula sobre LAS series de la ficha.
"""
import json
import math
import os
import random
import sys
import unittest
import uuid
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fastapi.testclient import TestClient

import cartera_simulada as cs
import comparar
import main
import tecnico
import velas_diarias
from fechas import hoy_art_date
from tests.test_tecnico import YahooFalso, _ruedas

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
FIN = date(2026, 10, 30)
# El día siguiente al último precio de `_habiles`: «hoy», contra el que se mide si un
# precio es viejo (`tecnico.es_vieja`).
HOY = FIN + timedelta(days=1)


def _habiles(n: int, f, fin: date = FIN) -> list:
    """`n` ruedas de lunes a viernes que terminan en `fin`; cierre = f(i)."""
    dias, d = [], fin
    while len(dias) < n:
        if d.weekday() < 5:
            dias.append(d)
        d -= timedelta(days=1)
    dias.reverse()
    return [{"date": x.isoformat(), "open": f(i), "high": f(i) * 1.01, "low": f(i) * 0.99, "close": f(i)}
            for i, x in enumerate(dias)]


def _todos(n: int, f, fin: date = FIN) -> list:
    """`n` días corridos (una cripto: también sábados y domingos)."""
    dias = [fin - timedelta(days=n - 1 - i) for i in range(n)]
    return [{"date": x.isoformat(), "open": f(i), "high": f(i), "low": f(i), "close": f(i)} for i, x in enumerate(dias)]


def _activo(asset, peso, velas, local=False):
    return {"asset": asset, "local": local, "peso": peso, "velas": velas, "ticker": asset, "convertida": None}


def _indices(sp=None, nq=None):
    return {"sp500": sp if sp is not None else _habiles(800, lambda i: 4000 + i),
            "nasdaq": nq if nq is not None else _habiles(800, lambda i: 12000 + 5 * i)}


class YahooDeCincoAnios:
    """Como Yahoo de verdad: «5y» es desde el mismo día de hace 5 años (aunque sea
    un sábado) hasta ayer, y «1mo», el último mes. De lunes a viernes; una cripto
    (-USD), todos los días. `precios[ticker](i, fecha)`: i, los días desde el
    primero de los 5 años (el mismo día da el mismo precio en las dos bajadas).
    `indices_desde`: la bajada entera de los índices arranca ese día y no hace 5
    años, como el día de su bajada entera del mes, que borra y reescribe toda su
    historia (velas_diarias: cada serie tiene su día; auditoría de código 06/11, 3)."""

    def __init__(self, hoy, precios, indices_desde=None):
        self.hoy, self.precios, self.indices_desde = hoy, precios, indices_desde
        try:
            self.origen = hoy.replace(year=hoy.year - 5)
        except ValueError:      # un 29 de febrero
            self.origen = hoy.replace(year=hoy.year - 5, day=28)

    def __call__(self, ticker, period, interval, auto_adjust, timeout):
        import pandas as pd
        f = self.precios.get(ticker) or ((lambda i, d: 5000.0) if ticker in velas_diarias.INDICES else None)
        if f is None:
            return pd.DataFrame()
        desde = self.origen if period == velas_diarias.PERIODO_COMPLETO else self.hoy - timedelta(days=31)
        if self.indices_desde and ticker in velas_diarias.INDICES and period == velas_diarias.PERIODO_COMPLETO:
            desde = self.indices_desde
        dias = [desde + timedelta(days=k) for k in range((self.hoy - desde).days)]
        dias = [d for d in dias if ticker.endswith("-USD") or d.weekday() < 5]
        c = [float(f((d - self.origen).days, d)) for d in dias]
        return pd.DataFrame({"Open": c, "High": [x * 1.01 for x in c], "Low": [x * 0.99 for x in c],
                             "Close": c, "Volume": [1000.0] * len(c)},
                            index=pd.DatetimeIndex([pd.Timestamp(d) for d in dias]))


class Cuentas(unittest.TestCase):

    def test_dos_activos_cada_uno_por_su_peso_y_sin_tocarla(self):
        a = _habiles(800, lambda i: 100 + i * 0.25)     # sube
        b = _habiles(800, lambda i: 50.0)               # quieto
        r = cs.simular([_activo("A", 60, a), _activo("B", 40, b)], _indices(), 1, HOY)
        self.assertTrue(r["disponible"], r)
        base = next(v for v in a if v["date"] >= r["desde"])["close"]
        va = a[-1]["close"] / base * 100
        final = 60 * va / 100 + 40
        self.assertAlmostEqual(r["cartera"]["final"], final, places=2)
        self.assertAlmostEqual(r["cartera"]["resultado"], final - 100, places=2)
        x, y = r["activos"]
        self.assertAlmostEqual(x["resultado"], va - 100, places=2)
        self.assertEqual(y["resultado"], 0.0, "sin comisiones ni dividendos: un activo quieto da 0 %")
        # Sin rebalancear, el que sube pesa cada vez más; los aportes suman el resultado.
        # (La serie en 100 del comparador va con 4 decimales: `comparar.base_cien`.)
        self.assertAlmostEqual(x["peso_final"], 60 * va / final, places=4)
        self.assertGreater(x["peso_final"], 60)
        self.assertAlmostEqual(x["peso_final"] + y["peso_final"], 100, places=6)
        self.assertAlmostEqual(x["aporte"] + y["aporte"], r["cartera"]["resultado"], places=6)
        self.assertEqual(r["curva"][0]["cartera"], 100.0)

    def test_un_activo_al_cien_es_su_serie_en_cien(self):
        """Diferencial contra el canónico: la regla de «arrancar en 100» del
        comparador de precios (`comparar.base_cien`), día por día."""
        rnd = random.Random(7)
        precio, cierres = 100.0, []
        for _ in range(900):
            precio *= 1 + rnd.gauss(0, 0.02)
            cierres.append(precio)
        a = _habiles(900, lambda i: cierres[i])
        r = cs.simular([_activo("A", 100, a)], _indices(), 2, HOY)
        canonico = comparar.base_cien([(v["date"], v["close"]) for v in a], r["desde"])
        self.assertEqual([p["d"] for p in r["curva"]], [p["d"] for p in canonico])
        for p, c in zip(r["curva"], canonico):
            self.assertAlmostEqual(p["cartera"], c["v"], delta=0.006, msg=p["d"])

    def test_los_dias_son_los_de_cualquier_activo_y_el_que_no_cotizo_vale_su_ultimo_cierre(self):
        accion = _habiles(800, lambda i: 100 + i)
        cripto = _todos(1100, lambda i: 30000 + 50 * i)
        r = cs.simular([_activo("ACC", 50, accion), _activo("BTC", 50, cripto)], _indices(), 1, HOY)
        sabados = [p for p in r["curva"] if date.fromisoformat(p["d"]).weekday() == 5]
        self.assertTrue(sabados, "con una cripto en la cartera, también los fines de semana")
        sab = sabados[-1]
        viernes = (date.fromisoformat(sab["d"]) - timedelta(days=1)).isoformat()
        acc = {v["date"]: v["close"] for v in accion}
        btc = {v["date"]: v["close"] for v in cripto}
        b_acc = acc[next(d for d in sorted(acc) if d >= r["desde"])]
        b_btc = btc[r["desde"]]
        esperado = 50 * acc[viernes] / b_acc + 50 * btc[sab["d"]] / b_btc
        self.assertAlmostEqual(sab["cartera"], esperado, places=1)
        # El S&P 500 de ese sábado es el del viernes.
        vie = next(p for p in r["curva"] if p["d"] == viernes)
        self.assertEqual(sab["sp500"], vie["sp500"])

    def test_arranca_cuando_existe_el_ultimo_en_llegar_y_lo_dice(self):
        viejo = _habiles(800, lambda i: 100 + i)
        nuevo = _habiles(150, lambda i: 20 + i * 0.1)        # cotiza hace ~7 meses
        r = cs.simular([_activo("VIEJO", 50, viejo), _activo("NUEVO", 50, nuevo)], _indices(), 1, HOY)
        self.assertTrue(r["disponible"], r)
        self.assertEqual((r["recortado"], r["recorte_por"], r["desde"]), (True, "NUEVO", nuevo[0]["date"]))
        # Unos días después del pedido no es un recorte (el borde de lo guardado).
        casi = _habiles(258, lambda i: 20 + i * 0.1)
        r2 = cs.simular([_activo("VIEJO", 50, viejo), _activo("CASI", 50, casi)], _indices(), 1, HOY)
        self.assertLessEqual(comparar._dias(r2["pedido_desde"], r2["desde"]), comparar.DIAS_MARGEN)
        self.assertEqual((r2["recortado"], r2["recorte_por"]), (False, None))

    def test_un_activo_sin_precios_de_la_ultima_semana_no_se_simula(self):
        al_dia = _habiles(800, lambda i: 100 + i)
        parado = _habiles(800, lambda i: 100 + i, fin=FIN - timedelta(days=12))
        r = cs.simular([_activo("AL_DIA", 50, al_dia), _activo("PARADO", 50, parado)], _indices(), 1, HOY)
        self.assertEqual((r["disponible"], r["motivo"]), (False, "vieja"))
        self.assertEqual(r["faltan"], [{"asset": "PARADO", "motivo": "vieja", "hasta": parado[-1]["date"]}])

    def test_sin_precios_o_con_poca_historia(self):
        r = cs.simular([_activo("A", 50, _habiles(800, lambda i: 100.0)), _activo("FCI", 50, [])], _indices(), 1, HOY)
        self.assertEqual((r["disponible"], r["motivo"], r["faltan"]),
                         (False, "sin_serie", [{"asset": "FCI", "motivo": "sin_serie"}]))
        r = cs.simular([_activo("A", 50, _habiles(800, lambda i: 100.0)),
                        _activo("NUEVITO", 50, _habiles(20, lambda i: 10.0))], _indices(), 1, HOY)
        self.assertEqual((r["disponible"], r["motivo"], r["recorte_por"]), (False, "poca_historia", "NUEVITO"))
        # Con pocas ruedas SIN recorte (una acción poco negociada, una vela por
        # semana) no hay a quién culpar de «cotiza hace muy poco» (auditoría 05/11, H10).
        semanal = [v for k, v in enumerate(_habiles(600, lambda i: 10.0)) if k % 5 == 0]
        r = cs.simular([_activo("SUELTA", 100, semanal)], _indices(), 1, HOY)
        self.assertEqual((r["disponible"], r["motivo"], r["recortado"], r["recorte_por"]),
                         (False, "poca_historia", False, None))

    def test_los_pesos_que_casi_suman_cien_se_llevan_a_cien(self):
        # 33,33 × 3 suma 99,99 y la ruta lo acepta: la cartera arranca en US$ 100 y
        # no en 99,99, y los «aportó» suman su resultado (auditoría 05/11, H5).
        a = _habiles(300, lambda i: 100 + i * 0.2)
        b = _habiles(300, lambda i: 50 + i * 0.05)
        c = _habiles(300, lambda i: 80 - i * 0.03)
        r = cs.simular([_activo("A", 33.33, a), _activo("B", 33.33, b), _activo("C", 33.33, c)], _indices(), 1, HOY)
        self.assertTrue(r["disponible"], r)
        self.assertEqual(r["curva"][0]["cartera"], 100.0)
        self.assertAlmostEqual(sum(x["aporte"] for x in r["activos"]), r["cartera"]["resultado"], places=9)
        self.assertAlmostEqual(sum(x["peso_final"] for x in r["activos"]), 100.0, places=9)
        self.assertAlmostEqual(sum(x["peso"] for x in r["activos"]), 100.0, places=9)

    def test_los_indices_al_lado_y_el_que_falta_no_frena_la_cartera(self):
        a = _habiles(800, lambda i: 100 + i)
        r = cs.simular([_activo("A", 100, a)], _indices(nq=[]), 2, HOY)
        self.assertTrue(r["disponible"], r)
        self.assertEqual([x["clave"] for x in r["indices"]], ["sp500"])
        self.assertEqual(r["faltan"], [{"clave": "nasdaq", "motivo": "sin_datos"}])
        self.assertEqual(set(r["curva"][0]), {"d", "cartera", "sp500"})
        sp = _indices()["sp500"]
        base = next(v for v in sp if v["date"] >= r["desde"])["close"]
        self.assertAlmostEqual(r["indices"][0]["resultado"], (sp[-1]["close"] / base - 1) * 100, places=2)
        # Un índice que dejó de actualizarse no se muestra como si fuera hoy.
        r = cs.simular([_activo("A", 100, a)], _indices(nq=_habiles(800, lambda i: 1.0, fin=FIN - timedelta(days=20))), 1, HOY)
        self.assertEqual([f["motivo"] for f in r["faltan"]], ["vieja"])

    def test_cinco_anios_con_el_primer_dia_en_un_fin_de_semana(self):
        # Con 5 años lo que se pide es justo lo guardado. Si ese día cae un domingo,
        # el S&P 500 y el Nasdaq empiezan el lunes, y quedaban afuera de la
        # comparación («todavía no tenemos la historia»). Arranca el lunes, sin
        # llamarlo recorte.
        fin = date(2026, 11, 5)
        pedido = (fin - timedelta(days=5 * tecnico.DIAS_ANIO - 1)).isoformat()
        self.assertEqual(date.fromisoformat(pedido).weekday(), 6)       # domingo
        sabado = (date.fromisoformat(pedido) - timedelta(days=1)).isoformat()
        cripto = [v for v in _todos(2000, lambda i: 30000 + 10 * i, fin=fin) if v["date"] >= sabado]
        idx = {c: [v for v in _habiles(1400, f, fin=fin) if v["date"] > pedido]
               for c, f in (("sp500", lambda i: 4000 + i), ("nasdaq", lambda i: 12000 + 5 * i))}
        lunes = idx["sp500"][0]["date"]
        r = cs.simular([_activo("BTC", 100, cripto)], idx, 5, fin + timedelta(days=1))
        self.assertTrue(r["disponible"], r)
        self.assertEqual(r["faltan"], [])
        self.assertEqual([x["clave"] for x in r["indices"]], ["sp500", "nasdaq"])
        self.assertEqual((r["pedido_desde"], r["desde"], r["recortado"]), (pedido, lunes, False))
        self.assertEqual(r["curva"][0], {"d": lunes, "cartera": 100.0, "sp500": 100.0, "nasdaq": 100.0})
        # Uno que empieza más de una semana después (no se bajó su historia) sigue
        # afuera y no corre el primer día de la cartera.
        diez = (date.fromisoformat(pedido) + timedelta(days=10)).isoformat()
        r = cs.simular([_activo("BTC", 100, cripto)], {**idx, "nasdaq": [v for v in idx["nasdaq"] if v["date"] > diez]}, 5, fin + timedelta(days=1))
        self.assertEqual(r["faltan"], [{"clave": "nasdaq", "motivo": "sin_datos"}])
        self.assertEqual((r["desde"], r["recortado"]), (lunes, False))
        # Con el lunes feriado en Nueva York, el martes: la semana de margen no es un día.
        martes = [v for v in idx["sp500"] if v["date"] > lunes]
        r = cs.simular([_activo("BTC", 100, cripto)], {"sp500": martes, "nasdaq": martes}, 5, fin + timedelta(days=1))
        self.assertEqual((r["desde"], r["faltan"]), (martes[0]["date"], []))
        # Uno que dejó de llegar no corre el primer día, aunque empiece después que el
        # otro: queda afuera, «sin precios desde el…» (auditoría de código 06/11, 3 y 6).
        viejo = [v for v in idx["sp500"] if martes[0]["date"] <= v["date"] <= (fin - timedelta(days=20)).isoformat()]
        r = cs.simular([_activo("BTC", 100, cripto)], {"sp500": viejo, "nasdaq": idx["nasdaq"]}, 5, fin + timedelta(days=1))
        self.assertEqual(r["desde"], lunes)
        self.assertEqual(r["faltan"], [{"clave": "sp500", "motivo": "vieja", "hasta": viejo[-1]["date"]}])

    def test_la_peor_caida_y_el_resultado_de_una_que_arranca_tarde(self):
        # Cotiza hace ~9 meses: la prueba de 1 año arranca en su primer día. (Contar la
        # caída desde los 100 o desde el primer cierre da lo mismo en una cartera: el
        # primer día vale 100 por construcción; auditoría de las pruebas 05/11, B11.)
        cierres = [100, 80, 90, 120] + [120] * 196
        a = _habiles(len(cierres), lambda i: float(cierres[i]))
        r = cs.simular([_activo("A", 100, a)], _indices(), 1, HOY)
        self.assertEqual((r["desde"], r["recortado"]), (a[0]["date"], True))
        self.assertAlmostEqual(r["cartera"]["peor_caida"], -20.0, places=6)
        self.assertAlmostEqual(r["cartera"]["resultado"], 20.0, places=6)


class AnioPorAnio(unittest.TestCase):
    """«Año por año» (Nico, 06/11/2026): el período abierto en años de LA regla del
    período, con la misma cartera sin tocar. Por `simular`, el camino de la ruta."""

    def _cartera(self, anios=3, indices=None, activos=None):
        sube = _habiles(800, lambda i: 100 + 30 * math.sin(i / 50) + i * 0.1)
        baja = _habiles(800, lambda i: 80 - i * 0.02 + 5 * math.sin(i / 30))
        return cs.simular(activos or [_activo("SUBE", 60, sube), _activo("BAJA", 40, baja)],
                          indices if indices is not None else _indices(), anios, HOY)

    def test_cada_anio_es_el_de_la_regla_del_periodo_y_juntos_dan_el_total(self):
        r = self._cartera()
        apa, hasta = r["anio_por_anio"], r["hasta"]
        uno, dos = tecnico.primer_dia(hasta, tecnico.DIAS_ANIO), tecnico.primer_dia(hasta, 2 * tecnico.DIAS_ANIO)
        self.assertEqual([(t["desde"], t["hasta"]) for t in apa["tramos"]],
                         [(r["desde"], dos), (dos, uno), (uno, hasta)])
        self.assertTrue(all(t["completo"] for t in apa["tramos"]))
        dias = comparar._dias(r["desde"], hasta)
        for clave, total in [("cartera", r["cartera"]["resultado"])] + [(i["clave"], i["resultado"]) for i in r["indices"]]:
            with self.subTest(clave=clave):
                # Uno detrás del otro dan el total, y el promedio es el compuesto.
                encadenados = math.prod(1 + t[clave] / 100 for t in apa["tramos"])
                self.assertAlmostEqual((encadenados - 1) * 100, total, places=6)
                self.assertAlmostEqual(apa["por_anio"][clave], ((1 + total / 100) ** (365 / dias) - 1) * 100, places=6)
        self.assertAlmostEqual(sum(t["aporte"] for t in apa["tramos"]), r["cartera"]["resultado"], places=6)
        # Es la cartera del gráfico, sin tocar: cada año, lo que vale ese día en la curva.
        curva = {p["d"]: p["cartera"] for p in r["curva"]}
        al = lambda d: curva[max(x for x in curva if x <= d)]
        for t in apa["tramos"]:
            self.assertAlmostEqual(t["cartera"], (al(t["hasta"]) / al(t["desde"]) - 1) * 100, delta=0.05)
            self.assertAlmostEqual(t["aporte"], al(t["hasta"]) - al(t["desde"]), delta=0.02)

    def test_el_ultimo_anio_de_un_indice_da_lo_mismo_que_elegir_un_anio(self):
        r = self._cartera()
        for n in (1, 2):
            ultimos = r["anio_por_anio"]["tramos"][-n:]
            for i in self._cartera(anios=n)["indices"]:
                with self.subTest(anios=n, indice=i["clave"]):
                    # Hasta el redondeo de `comparar.base_cien` (4 decimales, cada uno
                    # sobre su día del 100): en la pantalla, que muestra uno, es igual.
                    encadenados = math.prod(1 + t[i["clave"]] / 100 for t in ultimos)
                    self.assertAlmostEqual((encadenados - 1) * 100, i["resultado"], places=3)
        # La cartera no: «1 año» la compra de nuevo con tus pesos; acá es la de los
        # tres años, sin tocar, que ya cambió de pesos.
        self.assertGreater(abs(r["anio_por_anio"]["tramos"][-1]["cartera"]
                               - self._cartera(anios=1)["cartera"]["resultado"]), 0.1)

    def test_con_un_solo_anio_no_hay_anio_por_anio(self):
        self.assertIsNone(self._cartera(anios=1)["anio_por_anio"])

    def test_lo_de_antes_del_primer_anio_entero(self):
        hasta = FIN.isoformat()
        uno, dos = tecnico.primer_dia(hasta, tecnico.DIAS_ANIO), tecnico.primer_dia(hasta, 2 * tecnico.DIAS_ANIO)
        nueva = lambda desde: [_activo("NUEVA", 100, [v for v in _habiles(800, lambda i: 10 + i * 0.01) if v["date"] >= desde])]
        # Cotiza hace un año y siete meses: un tramo corto, con sus días, y un año entero.
        r = self._cartera(activos=nueva((FIN - timedelta(days=580)).isoformat()))
        self.assertEqual([(t["desde"], t["hasta"], t["completo"], t["dias"]) for t in r["anio_por_anio"]["tramos"]],
                         [(r["desde"], uno, False, comparar._dias(r["desde"], uno)), (uno, hasta, True, 364)])
        # Menos de un mes antes de un año entero va con ese año.
        r = self._cartera(activos=nueva((date.fromisoformat(dos) - timedelta(days=20)).isoformat()))
        self.assertEqual([(t["desde"], t["hasta"], t["completo"]) for t in r["anio_por_anio"]["tramos"]],
                         [(r["desde"], uno, True), (uno, hasta, True)])

    def test_un_indice_que_falta_no_tiene_columna(self):
        apa = self._cartera(indices=_indices(nq=[]))["anio_por_anio"]
        self.assertTrue(all("sp500" in t and "nasdaq" not in t for t in apa["tramos"]))
        self.assertEqual(set(apa["por_anio"]), {"cartera", "sp500"})

    # Las que siguen las propuso la auditoría de las pruebas de «Año por año» (06/11):
    # cada una da rojo con su copia rota de cartera_simulada.py, y las de arriba
    # quedaban en verde. Con fechas escritas, no con `tecnico.primer_dia`: si LA regla
    # del período se corre un día, lo esperado no se corre con ella.

    def test_un_activo_que_llega_unos_dias_despues_no_achica_el_primer_anio(self):
        # Hasta una semana después de lo pedido no es un recorte (`comparar.DIAS_MARGEN`):
        # arriba dice «Los 3 años», y el primero de los tres es un año (360 días), no un
        # renglón de «12 meses» que el veredicto no cuenta.
        nueva = [_activo("NUEVA", 100, [v for v in _habiles(800, lambda i: 10 + i * 0.01) if v["date"] >= "2023-11-06"])]
        r = self._cartera(activos=nueva)
        self.assertEqual((r["pedido_desde"], r["desde"], r["recortado"]), ("2023-11-01", "2023-11-06", False))
        self.assertEqual([(t["desde"], t["hasta"], t["dias"], t["completo"]) for t in r["anio_por_anio"]["tramos"]],
                         [("2023-11-06", "2024-10-31", 360, True), ("2024-10-31", "2025-10-31", 365, True),
                          ("2025-10-31", "2026-10-30", 364, True)])

    def test_cinco_semanas_antes_del_primer_anio_van_aparte(self):
        # «Menos de un mes» va con el año que sigue (`TRAMO_MIN_DIAS`: los 20 días de
        # arriba); cinco semanas ya son su renglón. Las dos puntas de la regla.
        nueva = [_activo("NUEVA", 100, [v for v in _habiles(800, lambda i: 10 + i * 0.01) if v["date"] >= "2024-09-26"])]
        r = self._cartera(activos=nueva)
        self.assertEqual([(t["desde"], t["hasta"], t["dias"], t["completo"]) for t in r["anio_por_anio"]["tramos"]],
                         [("2024-09-26", "2024-10-31", 35, False), ("2024-10-31", "2025-10-31", 365, True),
                          ("2025-10-31", "2026-10-30", 364, True)])

    def test_un_anio_que_empieza_un_domingo_vale_el_cierre_del_viernes(self):
        # Con el último precio un lunes, el año de hace dos arranca un domingo (365 días
        # son 52 semanas y uno). Ese día vale el último cierre, el del viernes: LA regla
        # del gráfico y de elegir «2 años» (`comparar.base_cien`), no la rueda del lunes.
        # Arriba todos los bordes caían en días con rueda, y no se veía.
        lunes = date(2026, 11, 2)
        sube = _habiles(800, lambda i: 100 + 30 * math.sin(i / 50) + i * 0.1, fin=lunes)
        baja = _habiles(800, lambda i: 80 - i * 0.02 + 5 * math.sin(i / 30), fin=lunes)
        indices = {"sp500": _habiles(800, lambda i: 4000 + i, fin=lunes),
                   "nasdaq": _habiles(800, lambda i: 12000 + 5 * i, fin=lunes)}
        simular = lambda anios: cs.simular([_activo("SUBE", 60, sube), _activo("BAJA", 40, baja)], indices, anios,
                                           lunes + timedelta(days=1))
        r = simular(3)
        tramos = r["anio_por_anio"]["tramos"]
        self.assertEqual([t["desde"] for t in tramos], ["2023-11-04", "2024-11-03", "2025-11-03"])  # sábado, domingo, lunes
        # Cada índice: los últimos años encadenados dan lo mismo que elegir «1 año» y «2 años».
        for n in (1, 2):
            for i in simular(n)["indices"]:
                with self.subTest(anios=n, indice=i["clave"]):
                    encadenados = math.prod(1 + t[i["clave"]] / 100 for t in tramos[-n:])
                    self.assertAlmostEqual((encadenados - 1) * 100, i["resultado"], places=3)
        # La cartera, contra la cuenta hecha a mano: 60 y 40 comprados el primer día, cada
        # uno con su último cierre en cada borde.
        cierre = lambda velas, d: max((v["date"], v["close"]) for v in velas if v["date"] <= d)[1]
        valor = lambda d: (60 * cierre(sube, d) / cierre(sube, r["desde"]) + 40 * cierre(baja, d) / cierre(baja, r["desde"]))
        for t in tramos:
            with self.subTest(tramo=t["desde"]):
                self.assertAlmostEqual(t["cartera"], (valor(t["hasta"]) / valor(t["desde"]) - 1) * 100, places=3)

    def test_un_anio_y_dos_semanas_es_un_solo_tramo_y_no_hay_anio_por_anio(self):
        # «2 años» de un activo que cotiza hace un año y dos semanas: lo de antes del año
        # entero dura menos de un mes y va con él. Queda UN tramo, que sería el total otra
        # vez: no hay «Año por año» (con 1 año la regla ni llegaba a unir nada).
        nueva = [_activo("NUEVA", 100, [v for v in _habiles(800, lambda i: 10 + i * 0.01) if v["date"] >= "2025-10-17"])]
        r = self._cartera(anios=2, activos=nueva)
        self.assertEqual((r["disponible"], r["recortado"], r["desde"]), (True, True, "2025-10-17"))
        self.assertIsNone(r["anio_por_anio"])

    def test_sin_recorte_el_primero_es_un_anio_aunque_el_primer_dia_se_corra(self):
        # El activo arranca hasta 7 días después del pedido (no es recorte) y los índices,
        # 7 días después de él (corren el primer día): el primer año dura menos de 358
        # días. Salía «12 meses» debajo de «Los 2 años» (auditoría de método 06/11, H2).
        hasta = FIN.isoformat()
        pedido = date.fromisoformat(tecnico.primer_dia(hasta, 2 * tecnico.DIAS_ANIO))
        desde_idx = next(d for d in (pedido + timedelta(days=12 + k) for k in range(3)) if d.weekday() < 5)
        activo = [v for v in _todos(900, lambda i: 100 + i * 0.1) if v["date"] >= (desde_idx - timedelta(days=7)).isoformat()]
        idx = {c: [v for v in _habiles(800, f) if v["date"] >= desde_idx.isoformat()]
               for c, f in (("sp500", lambda i: 4000 + i), ("nasdaq", lambda i: 12000 + 5 * i))}
        r = cs.simular([_activo("A", 100, activo)], idx, 2, HOY)
        self.assertEqual((r["recortado"], r["desde"], r["faltan"]), (False, desde_idx.isoformat(), []))
        t = r["anio_por_anio"]["tramos"]
        self.assertLess(t[0]["dias"], tecnico.DIAS_ANIO - comparar.DIAS_MARGEN)
        self.assertEqual([x["completo"] for x in t], [True, True])

    def test_con_recorte_un_anio_entero_es_desde_358_dias(self):
        hasta = FIN.isoformat()
        dos = date.fromisoformat(tecnico.primer_dia(hasta, 2 * tecnico.DIAS_ANIO))
        for dias, completo in ((358, True), (357, False)):
            with self.subTest(dias=dias):
                desde = (dos - timedelta(days=dias)).isoformat()
                a = [v for v in _todos(1500, lambda i: 100 + i * 0.1) if v["date"] >= desde]
                r = self._cartera(anios=4, activos=[_activo("A", 100, a)])
                self.assertTrue(r["recortado"])
                t = r["anio_por_anio"]["tramos"][0]
                self.assertEqual((t["desde"], t["dias"], t["completo"]), (desde, dias, completo))

    def test_un_activo_que_se_va_a_cero_en_un_corte_no_rompe_la_simulacion(self):
        # Con el redondeo de `comparar.base_cien` (4 decimales) vale 0 justo en el corte:
        # el año que arranca ahí queda vacío. Dividía por cero y la ruta contestaba un
        # error (auditoría de método 06/11, H1).
        corte = tecnico.primer_dia(FIN.isoformat(), tecnico.DIAS_ANIO)
        cerca = (date.fromisoformat(corte) - timedelta(days=6)).isoformat()
        velas = [{**v, **dict.fromkeys(("open", "high", "low", "close"),
                                       1e-5 if cerca <= v["date"] <= corte else 50.0 if v["date"] > corte else 100.0)}
                 for v in _habiles(800, lambda i: 100.0)]
        r = cs.simular([_activo("A", 100, velas)], _indices(), 2, HOY)
        self.assertTrue(r["disponible"], r)
        t = r["anio_por_anio"]["tramos"]
        self.assertEqual([x["hasta"] for x in t], [corte, r["hasta"]])
        self.assertAlmostEqual(t[0]["cartera"], -100.0, places=6)
        self.assertIsNone(t[1]["cartera"])
        self.assertAlmostEqual(t[1]["aporte"], 50.0, places=6)


class DeHoy(unittest.TestCase):
    """«Mi cartera de hoy»: lo que se puede simular, sobre 100 entre ellos."""

    def _car(self, tenencias):
        return {"tenencias": {(a, l): v for a, l, v, _ in tenencias},
                "tipos": {(a, l): t for a, l, _, t in tenencias}}

    def test_solo_lo_que_tiene_precio_de_todos_los_dias_y_sobre_cien(self):
        r = cs.de_hoy(self._car([("AAPL", False, 600.0, "STOCK"), ("GGAL", True, 300.0, "ACCION"),
                                 ("AL30", False, 50.0, "BOND"), ("FCI:AHORRO", False, 30.0, "FCI"),
                                 ("USDT", False, 20.0, "CRYPTO"), ("BTC", False, 100.0, "CRYPTO"),
                                 ("USD", False, 500.0, None)]))
        self.assertEqual([(a["asset"], a["local"], a["peso"]) for a in r["activos"]],
                         [("AAPL", False, 60.0), ("GGAL", True, 30.0), ("BTC", False, 10.0)])
        self.assertEqual([(x["asset"], x["motivo"]) for x in r["afuera"]],
                         [("AL30", "sin_serie"), ("FCI:AHORRO", "sin_serie"), ("USD", "sin_serie"), ("USDT", "sin_serie")])
        self.assertEqual(set(json.dumps(r)) & set("$"), set())
        self.assertNotIn("valor", json.dumps(r), "sólo porcentajes: nunca la plata")

    def test_suman_exactamente_cien_y_mas_de_diez_quedan_los_que_mas_pesan(self):
        r = cs.de_hoy(self._car([(f"T{i:02d}", False, float(20 - i), "STOCK") for i in range(12)]))
        self.assertEqual(len(r["activos"]), cs.MAX_ACTIVOS)
        self.assertAlmostEqual(sum(a["peso"] for a in r["activos"]), 100.0, places=9)
        self.assertEqual([x["asset"] for x in r["afuera"]], ["T10", "T11"])
        self.assertEqual({x["motivo"] for x in r["afuera"]}, {"tope"})
        tercios = cs.de_hoy(self._car([("A", False, 1.0, "STOCK"), ("B", False, 1.0, "STOCK"), ("C", False, 1.0, "STOCK")]))
        self.assertEqual(sorted(a["peso"] for a in tercios["activos"]), [33.3, 33.3, 33.4])

    def test_el_mismo_papel_en_byma_y_en_nueva_york_va_junto_con_la_marca_de_la_ficha(self):
        # LA regla de la ficha (`esAccionLocal`): acción argentina sólo si TODOS sus
        # lotes son de BYMA; con el ADR de Schwab al lado, el ADR. En cualquier orden
        # en que lleguen los lotes: en Postgres la consulta no los ordena (auditoría
        # 05/11, H3 y D3b).
        lotes = [("GGAL", True, 300.0, "ACCION"), ("GGAL", False, 100.0, "STOCK"), ("AAPL", False, 400.0, "STOCK")]
        for orden in (lotes, lotes[::-1], [lotes[1], lotes[0], lotes[2]]):
            with self.subTest(primero=orden[0][:2]):
                r = cs.de_hoy(self._car(orden))
                self.assertEqual([(a["asset"], a["local"], a["peso"]) for a in r["activos"]],
                                 [("AAPL", False, 50.0), ("GGAL", False, 50.0)])
        solo_byma = cs.de_hoy(self._car([("GGAL", True, 300.0, "ACCION"), ("AAPL", False, 100.0, "STOCK")]))
        self.assertEqual([(a["asset"], a["local"]) for a in solo_byma["activos"]], [("GGAL", True), ("AAPL", False)])

    def test_un_fondo_con_su_codigo_crudo_y_la_renta_fija_quedan_afuera_por_su_tipo(self):
        # COCOSPPA: el importador no lo encontró en el catálogo y quedó sin «FCI:»
        # (frenaba la simulación entera); S30N6 (LECAP) e YMCXO (ON) no se reconocen
        # por el nombre, sólo por el tipo (auditoría 05/11, H2 y D1).
        r = cs.de_hoy(self._car([("AAPL", False, 900.0, "STOCK"), ("COCOSPPA", True, 50.0, "FUND"),
                                 ("S30N6", True, 30.0, "LECAP"), ("YMCXO", True, 20.0, "ON")]))
        self.assertEqual([(a["asset"], a["peso"]) for a in r["activos"]], [("AAPL", 100.0)])
        self.assertEqual([(x["asset"], x["motivo"]) for x in r["afuera"]],
                         [("COCOSPPA", "sin_serie"), ("S30N6", "sin_serie"), ("YMCXO", "sin_serie")])

    def test_dice_que_parte_de_tu_plata_se_simula(self):
        # Mitad en acciones y mitad en bonos y efectivo: lo simulado es la mitad de tu
        # plata, y se dice (auditoría de producto 05/11, A4). Un porcentaje, nunca plata.
        car = self._car([("AAPL", False, 600.0, "STOCK"), ("AL30", False, 400.0, "BOND")])
        car["total"] = 1200.0   # + US$ 200 de efectivo, que no es una tenencia
        r = cs.de_hoy(car)
        self.assertEqual(r["parte"], 50)
        self.assertEqual(cs.de_hoy(self._car([("AL30", False, 400.0, "BOND")]))["parte"], None)

    def test_ninguno_queda_en_cero(self):
        # US$ 20 de BTC al lado de US$ 100.000 en acciones: con 0 % la fila quedaba
        # vacía y la ruta lo rechazaba. Lleva un décimo, sacado del que más pesa
        # (auditoría 05/11, H7).
        r = cs.de_hoy(self._car([("AAPL", False, 50000.0, "STOCK"), ("MSFT", False, 50000.0, "STOCK"),
                                 ("BTC", False, 20.0, "CRYPTO")]))
        pesos = {a["asset"]: a["peso"] for a in r["activos"]}
        self.assertEqual(pesos["BTC"], 0.1)
        self.assertAlmostEqual(sum(pesos.values()), 100.0, places=9)
        self.assertTrue(all(x > 0 for x in pesos.values()), pesos)


def _casos_de_la_pantalla():
    """Las respuestas que leen las pruebas de la pantalla (utils/carteraSimulada.test.js,
    pages/SimularCartera.render.test.jsx), sin la curva, que es larga."""
    sube = _habiles(800, lambda i: 150 + 40 * math.sin(i / 40) + i * 0.12)
    baja = _habiles(800, lambda i: 60 - i * 0.03 + 4 * math.sin(i / 25))
    cripto = _todos(1150, lambda i: 40000 + 9000 * math.sin(i / 90) + i * 8)
    sp = _habiles(800, lambda i: 4200 + i * 1.4 + 120 * math.sin(i / 60))
    nq = _habiles(800, lambda i: 13000 + i * 6 + 500 * math.sin(i / 55))
    activos = [_activo("AAPL", 50, sube), _activo("GGAL", 30, baja, local=True), _activo("BTC", 20, cripto)]
    casos = {
        "tres": cs.simular(activos, {"sp500": sp, "nasdaq": nq}, 2, HOY),
        "sin_nasdaq": cs.simular(activos, {"sp500": sp, "nasdaq": []}, 2, HOY),
        "recortada": cs.simular(activos[:2] + [_activo("NUEVA", 20, _habiles(200, lambda i: 10 + i * 0.05))],
                                {"sp500": sp, "nasdaq": nq}, 2, HOY),
        "vieja": cs.simular(activos[:2] + [_activo("PARADA", 20, _habiles(800, lambda i: 5.0, fin=FIN - timedelta(days=30)))],
                            {"sp500": sp, "nasdaq": nq}, 2, HOY),
        # Todos restan: la pantalla nombra al que MÁS restó (auditoría de las pruebas, F9).
        "todos_restan": cs.simular([_activo("BAJA1", 60, _habiles(800, lambda i: 50 - i * 0.004)),
                                    _activo("BAJA2", 40, _habiles(800, lambda i: 100 - i * 0.04))],
                                   {"sp500": sp, "nasdaq": nq}, 1, HOY),
        # «Año por año»: tres años enteros, y uno que arranca con un tramo corto.
        "tres_anios": cs.simular(activos, {"sp500": sp, "nasdaq": nq}, 3, HOY),
        "tramo_corto": cs.simular(activos[:2] + [_activo("NUEVA", 20, _habiles(420, lambda i: 10 + i * 0.02))],
                                  {"sp500": sp, "nasdaq": nq}, 3, HOY),
    }
    for r in casos.values():
        r.pop("curva", None)
    return json.loads(json.dumps(casos))


class LoQueLeeLaPantalla(unittest.TestCase):

    def test_las_pruebas_de_la_pantalla_leen_lo_que_da_el_servidor(self):
        """fixtures/cartera_simulada.json tiene que ser la salida de ESTE código, no
        una armada a mano. Para rearmarlo: CARTERA_REESCRIBIR=1."""
        ruta = os.path.join(FIXTURES, "cartera_simulada.json")
        casos = _casos_de_la_pantalla()
        if os.environ.get("CARTERA_REESCRIBIR"):
            with open(ruta, "w") as f:
                json.dump(casos, f, ensure_ascii=False, indent=1)
        with open(ruta) as f:
            self.assertEqual(json.load(f), casos)
        self.assertTrue(casos["tres"]["disponible"])
        self.assertEqual(casos["sin_nasdaq"]["faltan"], [{"clave": "nasdaq", "motivo": "sin_datos"}])
        self.assertTrue(casos["recortada"]["recortado"])
        self.assertEqual(casos["vieja"]["motivo"], "vieja")
        self.assertTrue(all(a["aporte"] < 0 for a in casos["todos_restan"]["activos"]))
        self.assertIsNone(casos["todos_restan"]["anio_por_anio"])
        self.assertEqual([t["completo"] for t in casos["tres_anios"]["anio_por_anio"]["tramos"]], [True] * 3)
        self.assertEqual([t["completo"] for t in casos["tramo_corto"]["anio_por_anio"]["tramos"]], [False, True])

    def test_los_indices_de_la_cartera_se_bajan_todas_las_noches(self):
        # Dos listas: contra cuáles se compara y cuáles baja la noche. Uno que se
        # sumara a la primera y no a la segunda no se bajaría nunca y la pantalla lo
        # omitiría callada (auditoría de regresiones 05/11, B4).
        self.assertLessEqual({s for _, _, s in cs.INDICES}, set(velas_diarias.INDICES))


class Ruta(unittest.TestCase):
    """GET /api/backtest/cartera: LAS series de la ficha, los índices de cada noche
    y el freno."""

    def setUp(self):
        main._freno_reiniciar()
        self.client = TestClient(main.app)
        tag = uuid.uuid4().hex[:8]
        with main.db_abierta() as conn:
            for t in ("velas_diarias", "velas_estado", "cambios_ratio", "watchlist", "positions",
                      "brokers", "fx_rates_daily"):
                conn.execute(f"DELETE FROM {t}")
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"cs-{tag}@rendi.test",))
            self.uid = cur.lastrowid
            conn.commit()
        self.h = {"Authorization": f"Bearer {main.create_token(self.uid)}"}
        self.hoy = hoy_art_date()
        self.yahoo = YahooFalso(self.hoy)
        self.yahoo.precios["AAPL"] = lambda i, d: 200 + 40 * math.sin(i / 12) + i * 0.05
        self.yahoo.precios["MSFT"] = lambda i, d: 300 + i * 0.1
        self.yahoo.precios[velas_diarias.SP500] = lambda i, d: 4000 + i
        self.yahoo.precios[velas_diarias.NASDAQ] = lambda i, d: 12000 + 3 * i
        self._p = [mock.patch("main._check_rate_limit"),
                   mock.patch("pricing.yahoo._historia", self.yahoo),
                   mock.patch("cambios_ratio._splits_de_yahoo", lambda t: []),
                   mock.patch("cambios_ratio._historia_byma", lambda c: {}),
                   mock.patch("main._fetch_data912_equities", lambda: {})]
        for p in self._p:
            p.start()
        velas_diarias._a_pedido_hechos.clear()
        with main.db_abierta() as conn:
            for d in _ruedas(self.hoy, 760):
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1100.0, 1000.0))
            conn.commit()
        self._posicion("Schwab", "USD", "AAPL", "STOCK")
        self._posicion("Schwab", "USD", "MSFT", "STOCK")
        main._run_velas_diarias_job()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _posicion(self, broker, moneda, asset, tipo):
        r = self.client.post("/api/brokers", json={"name": broker, "currency": moneda}, headers=self.h)
        self.assertIn(r.status_code, (200, 400), r.text)
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": 10,
                                                     "buy_price": 100, "asset_type": tipo}, headers=self.h)
        self.assertIn(r.status_code, (200, 201), r.text)

    def _get(self, q):
        return self.client.get(f"/api/backtest/cartera?{q}", headers=self.h)

    def _persona(self):
        """Otra persona, sin nada: cada caso arranca de cero."""
        with main.db_abierta() as conn:
            uid = conn.execute(
                "INSERT INTO users (email, password_hash, approved, email_verified, tier) "
                "VALUES (?, 'x', 1, 1, 'pro')", (f"cs-{uuid.uuid4().hex[:8]}@rendi.test",)).lastrowid
            conn.commit()
        return {"Authorization": f"Bearer {main.create_token(uid)}"}

    def _lote(self, h, broker, moneda, asset, tipo, cantidad, precio):
        r = self.client.post("/api/brokers", json={"name": broker, "currency": moneda}, headers=h)
        self.assertIn(r.status_code, (200, 400), r.text)
        r = self.client.post("/api/positions", json={"broker": broker, "asset": asset, "quantity": cantidad,
                                                     "buy_price": precio, "asset_type": tipo}, headers=h)
        self.assertIn(r.status_code, (200, 201), r.text)

    # Las que siguen las propuso la auditoría de las pruebas (05/11): cada una
    # atrapa un error que ninguna otra veía, por el mismo camino que producción.

    def test_sin_recorte_arranca_el_mismo_dia_que_el_backtesting_de_una_regla(self):
        # Diferencial contra el canónico: el primer día no es «cuando empieza lo
        # guardado» (B3: «los últimos 2 años» al lado de un gráfico de 3).
        for anios in (1, 2):
            with self.subTest(anios=anios):
                regla = self.client.get(f"/api/tecnico/AAPL/backtest?reglas=rsi&anios={anios}", headers=self.h).json()
                res = self._get(f"activos=AAPL&pesos=100&anios={anios}").json()
                self.assertTrue(res["disponible"], res)
                self.assertEqual(res["pedido_desde"], regla["pedido_desde"])
                self.assertEqual((res["recortado"], res["desde"], res["curva"][0]["d"]),
                                 (False, res["pedido_desde"], res["pedido_desde"]))

    def test_mi_cartera_de_hoy_deja_afuera_lecaps_obligaciones_y_fondos_por_su_tipo(self):
        h = self._persona()
        self._lote(h, "Schwab", "USD", "AAPL", "STOCK", 10, 100)
        self._lote(h, "IOL", "ARS", "S30N6", "LECAP", 100000, 1.2)
        self._lote(h, "IOL", "ARS", "YMCXO", "ON", 1000, 1050)
        self._lote(h, "Cocos", "ARS", "COCOSPPA", "FUND", 1000, 1.5)
        res = self.client.get("/api/backtest/cartera/hoy", headers=h).json()
        self.assertEqual([a["asset"] for a in res["activos"]], ["AAPL"])
        self.assertEqual(sorted((x["asset"], x["motivo"]) for x in res["afuera"]),
                         [("COCOSPPA", "sin_serie"), ("S30N6", "sin_serie"), ("YMCXO", "sin_serie")])
        self.assertIsNotNone(res["parte"])
        self.assertLess(res["parte"], 100)   # lo que quedó afuera también es tu plata
        # Y la noche ya no le pide a Yahoo el fondo crudo (lo pedía todos los días).
        with main.db_abierta() as conn:
            seguidos = velas_diarias.simbolos_a_seguir(conn)
        self.assertNotIn("COCOSPPA.BA", seguidos)
        self.assertNotIn("COCOSPPA", seguidos)

    def test_mi_cartera_de_hoy_junta_byma_y_ny_con_la_marca_de_la_ficha_en_cualquier_orden(self):
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000.0
        chico_ny = ("Schwab", "USD", "GGAL", "STOCK", 1, 50)
        grande_ny = ("Schwab", "USD", "GGAL", "STOCK", 1000, 50)
        chica_byma = ("IOL", "ARS", "GGAL", "ACCION", 1, 5000)
        grande_byma = ("IOL", "ARS", "GGAL", "ACCION", 1000, 5000)
        # Con un lote en Nueva York, el ADR (como la ficha), pese cuanto pese el de BYMA.
        for primero, segundo in ((chico_ny, grande_byma), (chica_byma, grande_ny),
                                 (grande_byma, chico_ny), (grande_ny, chica_byma)):
            with self.subTest(primero=primero[0], cuanto=primero[4]):
                h = self._persona()
                self._lote(h, *primero)
                self._lote(h, *segundo)
                res = self.client.get("/api/backtest/cartera/hoy", headers=h).json()
                self.assertEqual([(a["asset"], a["local"]) for a in res["activos"]], [("GGAL", False)])
        h = self._persona()
        self._lote(h, *grande_byma)
        res = self.client.get("/api/backtest/cartera/hoy", headers=h).json()
        self.assertEqual([(a["asset"], a["local"]) for a in res["activos"]], [("GGAL", True)])

    def test_una_accion_argentina_que_nadie_sigue_se_baja_con_su_precio_de_byma(self):
        # `local` llega también a la bajada a pedido (R4b).
        self.yahoo.precios["YPFD.BA"] = lambda i, d: 30000 + 400 * math.sin(i / 9)
        res = self._get("activos=YPFD,AAPL&pesos=50,50&local=YPFD&anios=1").json()
        self.assertTrue(res["disponible"], res)
        ypfd = res["activos"][0]
        self.assertEqual((ypfd["asset"], ypfd["local"], ypfd["ticker"], ypfd["convertida"]),
                         ("YPFD", True, "YPFD.BA", "mep"))

    def test_si_otra_persona_lo_esta_bajando_o_se_llego_al_tope_lo_dice(self):
        # La pantalla reintenta sola con 'bajando'; con 'sin_serie' invitaba a sacar
        # un activo que sí tiene precios (R6).
        self.yahoo.precios["NVDA"] = lambda i, d: 100 + i * 0.1
        with mock.patch.object(velas_diarias, "_a_pedido_en_curso", {"NVDA"}):
            res = self._get("activos=AAPL,NVDA&pesos=50,50&anios=1").json()
        self.assertEqual((res["disponible"], res["motivo"]), (False, "bajando"))
        with mock.patch("velas_diarias._hay_cupo", lambda uid, n: False):
            res = self._get("activos=AAPL,NVDA&pesos=50,50&anios=1").json()
        self.assertEqual((res["disponible"], res["motivo"]), (False, "tope"))

    def test_un_activo_viejo_que_no_se_pudo_volver_a_bajar_dice_por_que(self):
        # Su historia llega hasta hace 20 días y otra persona lo está bajando: antes
        # decía «vieja» (sacalo) en vez de «bajando» (esperá unos segundos), y la
        # pantalla no reintentaba (auditoría de seguridad 05/11, hallazgo 6).
        self._cvx_viejo()
        with mock.patch.object(velas_diarias, "_a_pedido_en_curso", {"CVX"}):
            res = self._get("activos=AAPL,CVX&pesos=50,50&anios=1").json()
        self.assertEqual((res["disponible"], res["motivo"]), (False, "bajando"))

    def _cvx_viejo(self):
        """CVX con historia hasta hace 20 días: lo que la bajada a pedido quiere poner al día."""
        self._posicion("Schwab", "USD", "CVX", "STOCK")
        with main.db_abierta() as conn:
            for d in _ruedas(self.hoy - timedelta(days=20), 300):
                conn.execute("INSERT INTO velas_diarias (symbol, date, open, high, low, close, volume) "
                             "VALUES ('CVX', ?, 150, 151, 149, 150, 1000)", (d.isoformat(),))
            conn.commit()

    def test_comparar_y_una_regla_tambien_dicen_que_lo_estan_bajando(self):
        # La misma regla (`_motivo_de_la_bajada`) en las otras dos rutas técnicas, que
        # ninguna prueba recorría (auditoría de verificación 05/11, V12): antes
        # Comparar decía «sus precios llegan hasta…» y «Una regla», «vieja».
        self._cvx_viejo()
        with mock.patch.object(velas_diarias, "_a_pedido_en_curso", {"CVX"}):
            cmp = self.client.get("/api/comparar/precio?activos=CVX,AAPL&plazo=1a", headers=self.h).json()
        self.assertIn({"clave": "CVX", "motivo": "bajando"},
                      [{"clave": f["clave"], "motivo": f["motivo"]} for f in cmp["faltan"]], cmp["faltan"])
        # «Una regla», con un activo que todavía no tiene precios: antes decía que no
        # los tenemos («sin_serie»), aunque otra persona los estaba bajando.
        self.yahoo.precios["NVDA"] = lambda i, d: 100 + i * 0.1
        with mock.patch.object(velas_diarias, "_a_pedido_en_curso", {"NVDA"}):
            regla = self.client.get("/api/tecnico/NVDA/backtest?reglas=rsi&anios=1", headers=self.h).json()
        self.assertEqual((regla["disponible"], regla["motivo"]), (False, "bajando"))
        with mock.patch("velas_diarias._hay_cupo", lambda uid, n: False):
            regla = self.client.get("/api/tecnico/NVDA/backtest?reglas=rsi&anios=1", headers=self.h).json()
        self.assertEqual((regla["disponible"], regla["motivo"]), (False, "tope"))

    def test_la_suma_del_100_es_la_que_ve_la_pantalla(self):
        # La tolerancia que importa es la de la RUTA (F2), y con la suma redondeada a
        # centavos como la pantalla: 50,03 + 50,02 es 100,05000000000001 (H6).
        for pesos, codigo in (("50,49.96", 200), ("50,49.94", 400), ("50.03,50.02", 200),
                              ("49.98,49.97", 200), ("50.04,50.02", 400)):
            with self.subTest(pesos=pesos):
                self.assertEqual(self._get(f"activos=AAPL,MSFT&pesos={pesos}&anios=1").status_code, codigo)
        self.assertEqual(self._get("activos=AAPL&pesos=nan&anios=1").status_code, 400)

    def _cinco_anios(self, q, indices_desde=None):
        """La noche baja «5y» como Yahoo y poda lo de más de `DIAS_GUARDADOS`; lo
        que nadie sigue se baja en el momento; y se simula por la ruta."""
        cinco = YahooDeCincoAnios(self.hoy, self.yahoo.precios, indices_desde)
        with mock.patch("pricing.yahoo._historia", cinco):
            with main.db_abierta() as conn:
                conn.execute("DELETE FROM velas_diarias")
                conn.execute("DELETE FROM velas_estado")
                conn.commit()
            main._run_velas_diarias_job()
            r = self._get(q)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_cinco_anios_entran_en_lo_que_se_guarda(self):
        # Por el camino de producción, 5 años se simulan enteros, al lado de los dos
        # índices (producto 05/11, A5: «probarlo con lo guardado»).
        self.yahoo.precios["BTC-USD"] = lambda i, d: 30000 + 10 * i
        res = self._cinco_anios("activos=AAPL,MSFT,BTC&pesos=40,40,20&anios=5")
        self.assertTrue(res["disponible"], res)
        self.assertEqual((res["recortado"], res["faltan"]), (False, []))
        self.assertEqual([x["clave"] for x in res["indices"]], ["sp500", "nasdaq"])
        self.assertLessEqual(comparar._dias(res["pedido_desde"], res["desde"]), comparar.DIAS_MARGEN)
        self.assertEqual(res["anios"], 5)

    def test_cinco_anios_con_los_indices_bajados_enteros_despues_del_pedido(self):
        # El caso de producción que la prueba de arriba no armaba (auditoría de código
        # 06/11, 3): el día de su bajada entera del mes, cada índice borra y reescribe
        # su historia y arranca justo 5 años atrás; BTC tiene la suya de antes. Si eso
        # cae después del primer día pedido, los índices quedaban AFUERA. Acá arrancan
        # el primer día hábil después del pedido: con el código de antes da rojo
        # cualquier día del año.
        self.yahoo.precios["BTC-USD"] = lambda i, d: 30000 + 10 * i
        pedido = self.hoy - timedelta(days=1) - timedelta(days=5 * tecnico.DIAS_ANIO - 1)
        habil = next(pedido + timedelta(days=k) for k in range(1, 8) if (pedido + timedelta(days=k)).weekday() < 5)
        res = self._cinco_anios("activos=BTC&pesos=100&anios=5", indices_desde=habil)
        self.assertTrue(res["disponible"], res)
        self.assertEqual(res["pedido_desde"], pedido.isoformat())
        self.assertEqual((res["desde"], res["recortado"], res["faltan"]), (habil.isoformat(), False, []))
        self.assertEqual([x["clave"] for x in res["indices"]], ["sp500", "nasdaq"])

    def test_simula_sobre_las_series_de_la_ficha_y_los_indices_de_cada_noche(self):
        r = self._get("activos=AAPL,MSFT&pesos=60,40&anios=2")
        self.assertEqual(r.status_code, 200, r.text)
        res = r.json()
        self.assertTrue(res["disponible"], res)
        with main.db_abierta() as conn:
            esperado = cs.simular(
                [{"asset": s, "local": False, "peso": p, "velas": tecnico.serie(conn, s, "usd")["velas"],
                  "ticker": s, "convertida": None} for s, p in (("AAPL", 60.0), ("MSFT", 40.0))],
                {c: tecnico.indice(conn, t) for c, _, t in cs.INDICES}, 2, hoy_art_date())
        self.assertEqual(res, json.loads(json.dumps(esperado)))
        self.assertEqual([x["clave"] for x in res["indices"]], ["sp500", "nasdaq"])
        self.assertEqual(res["faltan"], [])

    def test_accion_argentina_con_su_precio_de_byma(self):
        self._posicion("IOL", "ARS", "GGAL", "ACCION")
        # El ADR, guardado (otra persona lo tiene en Schwab): sin él, la ficha caía sola en
        # BYMA ÷ MEP y esta prueba daba verde aunque la cartera perdiera la marca de acción
        # argentina (lo mismo que encontró la auditoría de las pruebas de «Año por año»,
        # 06/11, en la de abajo).
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0
        self._lote(self._persona(), "Schwab", "USD", "GGAL", "STOCK", 10, 100)
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 + 800 * math.sin(i / 10)
        main._run_velas_diarias_job()
        res = self._get("activos=GGAL,AAPL&pesos=50,50&local=GGAL&anios=1").json()
        self.assertTrue(res["disponible"], res)
        ggal = res["activos"][0]
        self.assertEqual((ggal["asset"], ggal["local"], ggal["ticker"], ggal["convertida"]),
                         ("GGAL", True, "GGAL.BA", "mep"))

    def test_una_accion_argentina_se_mide_en_dolares_tambien_anio_por_anio(self):
        # Nico, 06/11: una acción argentina sube en pesos con la inflación aunque a la
        # empresa no le vaya mejor. Se mide en dólares, el precio de BYMA ÷ el MEP de
        # cada día, también el primero de cada año. Acá los pesos suben ~60 % por año
        # y el MEP igual: en dólares no se movió. Y el dólar salta 30 % justo en el
        # corte de un año: con el MEP de otro día (el de antes o el de después), ese
        # año daría ±30 % (auditoría de método 06/11, H5).
        ruedas = _ruedas(self.hoy, 760)
        borde = max(r for r in ruedas if r <= date.fromisoformat(tecnico.primer_dia(ruedas[-1].isoformat(), tecnico.DIAS_ANIO)))
        inflacion = lambda d: 1.04 ** ((d - ruedas[0]).days / 30) * (1.3 if d >= borde else 1.0)
        with main.db_abierta() as conn:
            conn.execute("DELETE FROM fx_rates_daily")
            for d in ruedas:
                conn.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                             (d.isoformat(), 1100.0 * inflacion(d), 1000.0 * inflacion(d)))
            conn.commit()
        self._posicion("IOL", "ARS", "GGAL", "ACCION")
        # El ADR, guardado (otra persona lo tiene en Schwab) y subiendo (~29 % por año):
        # si la cartera usara su serie y no la de BYMA ÷ MEP, cada año daría eso y no 0 %.
        # Sin el ADR guardado, la ficha cae sola en BYMA ÷ MEP y la prueba no lo distinguía
        # (auditoría de las pruebas de «Año por año», 06/11).
        self.yahoo.precios["GGAL"] = lambda i, d: 50.0 * 1.001 ** i
        self.yahoo.precios["GGAL.BA"] = lambda i, d: 5000 * inflacion(d)
        self._lote(self._persona(), "Schwab", "USD", "GGAL", "STOCK", 10, 100)
        main._run_velas_diarias_job()
        res = self._get("activos=GGAL&pesos=100&local=GGAL&anios=2").json()
        self.assertTrue(res["disponible"], res)
        self.assertEqual(res["hasta"], ruedas[-1].isoformat())
        with main.db_abierta() as conn:
            en_pesos = [r[0] for r in conn.execute(
                "SELECT close FROM velas_diarias WHERE symbol='GGAL.BA' AND date BETWEEN ? AND ? ORDER BY date",
                (res["desde"], res["hasta"])).fetchall()]
        self.assertGreater(en_pesos[-1] / en_pesos[0], 2)       # en pesos, más del doble
        apa = res["anio_por_anio"]
        self.assertEqual(len(apa["tramos"]), 2)
        for t in apa["tramos"]:
            self.assertAlmostEqual(t["cartera"], 0.0, delta=0.5)
        self.assertAlmostEqual(apa["por_anio"]["cartera"], 0.0, delta=0.5)
        self.assertAlmostEqual(res["cartera"]["resultado"], 0.0, delta=0.5)

    def test_mi_cartera_de_hoy_sale_de_tu_plata_sin_mostrarla(self):
        r = self.client.get("/api/backtest/cartera/hoy", headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        res = r.json()
        self.assertEqual(sorted(a["asset"] for a in res["activos"]), ["AAPL", "MSFT"])
        self.assertAlmostEqual(sum(a["peso"] for a in res["activos"]), 100.0, places=9)
        self.assertEqual(res["afuera"], [])
        self.assertEqual(set(res), {"activos", "afuera", "parte"})
        self.assertEqual(res["parte"], 100)   # sólo acciones: se simula toda tu plata
        self.assertEqual({k for a in res["activos"] for k in a}, {"asset", "local", "peso", "tipo"})
        # Y lo que arma se puede simular tal cual.
        q = (f"activos={','.join(a['asset'] for a in res['activos'])}"
             f"&pesos={','.join(str(a['peso']) for a in res['activos'])}&anios=1")
        self.assertTrue(self._get(q).json()["disponible"])

    def test_lo_que_no_se_puede_simular_dice_por_que(self):
        res = self._get("activos=AAPL,ZZZZ&pesos=50,50&anios=1").json()
        self.assertEqual((res["disponible"], res["motivo"]), (False, "sin_serie"))
        self.assertEqual(res["faltan"], [{"asset": "ZZZZ", "motivo": "sin_serie"}])

    def test_lo_que_no_se_ofrece_da_400(self):
        for q in ("activos=&pesos=", "activos=AAPL&pesos=60", "activos=AAPL,AAPL&pesos=50,50",
                  "activos=AAPL,MSFT&pesos=50", "activos=AAPL,MSFT&pesos=70,40", "activos=AAPL,MSFT&pesos=0,100",
                  "activos=AAPL,MSFT&pesos=50,x", "activos=AAPL&pesos=100&anios=6", "activos=AAPL&pesos=100&anios=0",
                  "activos=A%20B&pesos=100", "activos=AAPL&pesos=100&local=A%20B",
                  "activos=" + ",".join(f"T{i}" for i in range(cs.MAX_ACTIVOS + 1))
                  + "&pesos=" + ",".join(["10"] * (cs.MAX_ACTIVOS + 1))):
            with self.subTest(q=q):
                self.assertEqual(self._get(q).status_code, 400)
        # Decimales que suman 100 sí.
        self.assertEqual(self._get("activos=AAPL,MSFT&pesos=33.33,66.67&anios=1").status_code, 200)


if __name__ == "__main__":
    unittest.main()
