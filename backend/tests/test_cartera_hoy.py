"""¿Qué pasó hoy con mi cartera? — get_portfolio_today.

El caso que da origen a todo, MEDIDO el 2026-10-08 a las 09:32 (BYMA abre a
las 11:00): el feed live de data912 mostraba AAPL c=27.100 pct=+1,04 % y su
última vela histórica era la del 2026-10-07 con c=27.100 dr=+0,0104. O sea, el
"+1,04 %" de las 9:32 era la rueda de AYER. Un chat que lo leyera sin fecha
diría "hoy subiste". Estos tests fijan que:

1. La rueda de BYMA se fecha con el DATO (live vs vela), no con la hora.
2. El cierre anterior viaja con la fecha de su rueda, y bonos/BYMA no se cachean.
3. El resumen NUNCA suma una rueda de hoy con una de ayer, y rotula cada una.
4. El camino de producción (dispatcher de tools → valuación del chat →
   /api/prices/prev-close) da el MISMO monto que la columna "Var. día" de
   Posiciones: (precio − cierre anterior) × cantidad ÷ MEP.
"""
import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
import cartera_hoy

HOY = "2026-10-08"     # jueves
AYER = "2026-10-07"

# Lo medido en vivo el 2026-10-08 09:32 ART.
LIVE_PREAPERTURA = {"AAPL": {"c": 27100.0, "pct": 1.04},
                    "SPY": {"c": 20900.0, "pct": -0.19}}
VELAS_DEL_7 = {"SPY": {"date": AYER, "c": 20900.0, "dr": -0.0019},
               "AL30": {"date": AYER, "c": 85800.0, "dr": -0.0005}}
BONOS_PREAPERTURA = {"AL30": 85800.0}
ART = ZoneInfo("America/Argentina/Buenos_Aires")
A_LAS_932 = datetime(2026, 10, 8, 9, 32, tzinfo=ART)
A_LAS_15 = datetime(2026, 10, 8, 15, 0, tzinfo=ART)
BONOS_PCT_PREAPERTURA = {"AL30": -0.05}


def _lote(asset, valor, previo, mercado, rueda, es_hoy, broker="X", motivo=None):
    return {"asset": asset, "broker": broker, "valor": valor, "valor_previo": previo,
            "motivo": motivo, "mercado": mercado, "rueda": rueda, "es_hoy": es_hoy}


class DiaTxtTest(unittest.TestCase):
    def test_nombres(self):
        self.assertEqual(cartera_hoy.dia_txt(HOY, HOY), "hoy")
        self.assertEqual(cartera_hoy.dia_txt(AYER, HOY), "ayer")
        # Lunes: lo último de BYMA es el viernes, no "ayer".
        self.assertEqual(cartera_hoy.dia_txt("2026-10-09", "2026-10-12"), "el viernes 9/10")
        self.assertEqual(cartera_hoy.dia_txt(None, HOY), "sin fecha confirmada")


class ArmarTest(unittest.TestCase):
    def test_hoy_y_ayer_no_se_suman(self):
        """Antes de las 11: EEUU ya operó hoy (o cripto), BYMA es de ayer. Dos
        grupos, cada uno con su día, y el de hoy primero."""
        r = cartera_hoy.armar([
            _lote("MSFT", 6000, 5900, "eeuu", HOY, True),
            _lote("AAPL", 2000, 1980, "byma", AYER, False),
            _lote("ARS", 1000, None, None, None, False, motivo="efectivo"),
        ], HOY)
        mov = r["movimiento"]
        self.assertEqual([g["dia_txt"] for g in mov], ["hoy", "ayer"])
        self.assertEqual(mov[0]["usd"], 100.0)
        self.assertEqual(mov[1]["usd"], 20.0)
        self.assertFalse(mov[1]["es_hoy"])
        # % sobre TODA la cartera al cierre anterior: 9000 − 120 = 8880.
        self.assertAlmostEqual(mov[0]["pct_sobre_la_cartera"], round(100 / 8880 * 100, 2))
        self.assertEqual(mov[0]["usd_txt"], "+US$ 100,00")
        self.assertEqual(r["efectivo_porcion_de_la_cartera_pct"], round(1000 / 9000 * 100, 1))

    def test_sin_fecha_no_es_hoy(self):
        r = cartera_hoy.armar([_lote("XYZ", 100, 90, "eeuu", None, False)], HOY)
        self.assertEqual(r["movimiento"][0]["dia_txt"], "sin fecha confirmada")
        self.assertFalse(r["movimiento"][0]["es_hoy"])

    def test_cripto_despues_de_las_21_se_rotula_hoy(self):
        """A las 22:00 ART la vela de la cripto ya es del día UTC siguiente."""
        r = cartera_hoy.armar([_lote("BTC", 500, 490, "cripto", "2026-10-09", True)], HOY)
        self.assertEqual(r["movimiento"][0]["rueda"], HOY)
        self.assertEqual(r["movimiento"][0]["dia_txt"], "hoy")

    def test_sin_medir_y_movers_por_plata(self):
        r = cartera_hoy.armar([
            _lote("CHICA", 20, 18.5, "eeuu", HOY, True),        # +8 % pero US$ 1,5
            _lote("GRANDE", 10000, 9900, "eeuu", HOY, True),    # +1 % y US$ 100
            _lote("FCI:X", 500, None, None, None, False, motivo="fci"),
        ], HOY)
        self.assertEqual(r["activos_que_mas_movieron"][0]["asset"], "GRANDE")
        self.assertEqual(r["sin_medir"][0]["asset"], "FCI:X")
        self.assertIn("fondo común", r["sin_medir"][0]["motivo"])

    def test_mismo_activo_en_dos_brokers_es_una_fila(self):
        r = cartera_hoy.armar([
            _lote("AAPL", 1000, 990, "eeuu", HOY, True, broker="Schwab"),
            _lote("AAPL", 500, 495, "eeuu", HOY, True, broker="IBKR"),
        ], HOY)
        filas = r["activos_que_mas_movieron"]
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["usd"], 15.0)
        self.assertEqual(sorted(filas[0]["brokers"]), ["IBKR", "Schwab"])


class RuedaBymaTest(unittest.TestCase):
    def setUp(self):
        self._hist = dict(main._RUEDA_BYMA_HIST)
        self.addCleanup(lambda: (main._RUEDA_BYMA_HIST.clear(),
                                 main._RUEDA_BYMA_HIST.update(self._hist)))

    def _rueda(self, live, velas, ahora=A_LAS_932):
        main._RUEDA_BYMA_HIST.update({"ts": 0, "ultimas": {}, "fallo": 0})
        bonos = BONOS_PREAPERTURA if live else {}
        with patch.object(main, "_fetch_data912_equities", return_value=live), \
             patch.object(main, "_fetch_data912_bonds", return_value=bonos), \
             patch.dict(main._data912_bonds_pct, BONOS_PCT_PREAPERTURA, clear=True), \
             patch.object(main, "_data912_ultima_vela",
                          side_effect=lambda tipo, ticker: velas.get(ticker)), \
             patch("fechas.ahora_art", return_value=ahora):
            return main._rueda_byma(HOY)

    def test_preapertura_es_la_rueda_de_ayer(self):
        """El caso medido: a las 9:32 el live es idéntico a la vela del 7."""
        self.assertEqual(self._rueda(LIVE_PREAPERTURA, VELAS_DEL_7), AYER)

    def test_rueda_en_curso(self):
        live = {"SPY": {"c": 20950.0, "pct": 0.24}}
        self.assertEqual(self._rueda(live, VELAS_DEL_7, ahora=A_LAS_15), HOY)

    def test_vela_atrasada_a_la_manana_no_es_hoy(self):
        """Si data912 todavía no escribió la vela de ayer, a las 9:32 el live
        (= ayer) difiere de la vela (= anteayer). Eso NO puede ser la rueda de
        hoy: BYMA abre a las 11. Antes del veto salía fechada HOY."""
        velas_del_6 = {"SPY": {"date": "2026-10-06", "c": 20800.0, "dr": 0.001}}
        self.assertIsNone(self._rueda(LIVE_PREAPERTURA, velas_del_6, ahora=A_LAS_932))

    def test_sabado_no_es_hoy(self):
        sabado = datetime(2026, 10, 10, 15, 0, tzinfo=ART)
        velas_del_6 = {"SPY": {"date": "2026-10-06", "c": 20800.0, "dr": 0.001}}
        self.assertIsNone(self._rueda(LIVE_PREAPERTURA, velas_del_6, ahora=sabado))

    def test_vela_de_hoy_ya_cerrada(self):
        velas = {"SPY": {"date": HOY, "c": 20950.0, "dr": 0.0024}}
        self.assertEqual(self._rueda({"SPY": {"c": 20950.0, "pct": 0.24}}, velas), HOY)

    def test_sin_datos_no_es_hoy(self):
        self.assertIsNone(self._rueda({}, VELAS_DEL_7))
        self.assertIsNone(self._rueda(LIVE_PREAPERTURA, {}))


def _tabla_yahoo(cierres_por_ticker, fechas):
    """Forma de `_yahoo.descargar(..., group_by='column')`: columnas (dato, ticker)."""
    cols = pd.MultiIndex.from_tuples([("Close", t) for t in cierres_por_ticker],
                                     names=["Price", "Ticker"])
    data = list(zip(*cierres_por_ticker.values()))
    return pd.DataFrame(data, index=pd.to_datetime(fechas), columns=cols)


class PrevCloseConRuedaTest(unittest.TestCase):
    def setUp(self):
        main._PREVCLOSE_CACHE.clear()
        main._PREVCLOSE_RUEDA.clear()
        self.addCleanup(main._PREVCLOSE_CACHE.clear)
        self.addCleanup(main._PREVCLOSE_RUEDA.clear)

    def _core(self, syms, live=None, bonos=None, bond_pct=None, yahoo=None):
        bonos = bonos or {}
        with patch.object(main, "_fetch_data912_equities", return_value=live or {}), \
             patch.object(main, "_resolve_ar_bond_price", side_effect=lambda s: bonos.get(s)), \
             patch.object(main, "_data912_bond_pct", side_effect=lambda s: (bond_pct or {}).get(s)), \
             patch.object(main._yahoo, "descargar", return_value=yahoo if yahoo is not None else pd.DataFrame()), \
             patch.object(main._yahoo, "varios", return_value=({}, [])):
            return main._prev_close_con_rueda(syms, uid=0)

    def test_cedear_de_byma_lleva_rueda_byma_y_no_se_cachea(self):
        cierres, ruedas = self._core(["AAPL.BA"], live=LIVE_PREAPERTURA)
        self.assertAlmostEqual(cierres["AAPL.BA"], 27100 / 1.0104, places=4)
        self.assertEqual(ruedas["AAPL.BA"], main.RUEDA_BYMA)
        # Cachearlo 10 min hacía que, al abrir, el precio nuevo se comparara
        # con el cierre de anteayer.
        self.assertNotIn("AAPL.BA", main._PREVCLOSE_CACHE)

    def test_bono_ahora_tiene_cierre_anterior(self):
        """Antes la renta fija devolvía null y 'Var. día' mostraba '—'."""
        cierres, ruedas = self._core(["AL30"], bonos={"AL30": 0.5575}, bond_pct={"AL30": 0.09})
        self.assertAlmostEqual(cierres["AL30"], 0.5575 / 1.0009, places=6)
        self.assertEqual(ruedas["AL30"], main.RUEDA_BYMA)

    def test_accion_de_eeuu_trae_la_fecha_de_su_vela(self):
        tabla = _tabla_yahoo({"MSFT": [590.0, 600.0]}, [AYER, HOY])
        cierres, ruedas = self._core(["MSFT"], yahoo=tabla)
        self.assertEqual(cierres["MSFT"], 590.0)
        self.assertEqual(ruedas["MSFT"], ("eeuu", HOY))
        # Lo de yfinance sí se cachea, con su fecha al lado.
        self.assertIn("MSFT", main._PREVCLOSE_CACHE)
        self.assertEqual(main._PREVCLOSE_RUEDA["MSFT"], ("eeuu", HOY))

    def test_el_endpoint_sigue_devolviendo_solo_numeros(self):
        tabla = _tabla_yahoo({"MSFT": [590.0, 600.0]}, [AYER, HOY])
        with patch.object(main, "_fetch_data912_equities", return_value=LIVE_PREAPERTURA), \
             patch.object(main, "_fetch_data912_bonds", return_value={}), \
             patch.object(main._yahoo, "descargar", return_value=tabla), \
             patch.object(main._yahoo, "varios", return_value=({}, [])):
            out = main.get_prev_close("MSFT,AAPL.BA", 0)
        self.assertEqual(set(out), {"MSFT", "AAPL.BA"})
        self.assertTrue(all(isinstance(v, float) for v in out.values()))


class CaminoDeProduccionTest(unittest.TestCase):
    """La tool por el dispatcher real, contra la base: CEDEAR en pesos (IOL) +
    acción en dólares (Schwab) + efectivo, a las 9:32 del jueves 8."""

    MEP = 1400.0

    def setUp(self):
        for c in (main._CHAT_VAL_CACHE, main._CHAT_PRECIOS, main._CARTERA_HOY_CACHE,
                  main._PREVCLOSE_CACHE, main._PREVCLOSE_RUEDA, main._PREVCLOSE_VENCE,
                  main._PRICE_CACHE):
            c.clear()
        self.addCleanup(main._PRICE_CACHE.clear)
        self._hist = dict(main._RUEDA_BYMA_HIST)
        self.addCleanup(lambda: (main._RUEDA_BYMA_HIST.clear(),
                                 main._RUEDA_BYMA_HIST.update(self._hist)))
        main._RUEDA_BYMA_HIST.update({"ts": 9e18, "ultimas": VELAS_DEL_7, "fallo": 0})
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        for t in ("positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        self.uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            (f"hoy-{id(self)}@rendi.test", "x")).lastrowid
        for name, ccy in (("IOL", "ARS"), ("Schwab", "USD")):
            self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                              (self.uid, name, ccy))
        ins = ("INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, invested, "
               "quantity, commissions, price_override, currency) VALUES (?,?,?,?,?,?,?,0,NULL,?)")
        self.conn.execute(ins, (self.uid, "IOL", "AAPL", "cedear", 0, 2_500_000, 100, "ARS"))
        self.conn.execute(ins, (self.uid, "Schwab", "MSFT", "stock", 0, 5000, 10, "USD"))
        self.conn.execute(ins, (self.uid, "Schwab", "USD", None, 1, 1000, 1000, "USD"))
        self.conn.commit()

    def tearDown(self):
        for t in ("positions", "brokers", "users"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()

    def _correr(self, live, ahora=A_LAS_932, precios=None):
        tabla = _tabla_yahoo({"MSFT": [590.0, 600.0]}, [AYER, HOY])
        precios = precios or {"AAPL.BA": live["AAPL"]["c"], "MSFT": 600.0}
        with patch("fechas.hoy_art", return_value=HOY), \
             patch("fechas.ahora_art", return_value=ahora), \
             patch.object(main, "_user_tc_blue", return_value=1450.0), \
             patch.object(main, "_user_tc_cedear", return_value=self.MEP), \
             patch.object(main, "fetch_prices_for_symbols", return_value=precios), \
             patch.object(main, "_fetch_data912_equities", return_value=live), \
             patch.object(main, "_fetch_data912_bonds", return_value={}), \
             patch.object(main._yahoo, "descargar", return_value=tabla), \
             patch.object(main._yahoo, "varios", return_value=({}, [])), \
             patch.object(main, "_ensure_news_batch_parallel", return_value=None):
            return main._execute_ai_tool_inner("get_portfolio_today", {}, self.uid)

    def _var_dia_de_posiciones(self, c, pct, qty):
        """La fórmula de Positions.jsx (dayVarOf + dvFor): previo del feed =
        c / (1 + pct/100); monto = (precio − previo) × cantidad ÷ MEP."""
        prev = c / (1 + pct / 100)
        return (c - prev) * qty / self.MEP

    def test_a_las_932_byma_es_ayer_y_eeuu_es_hoy(self):
        r = self._correr(LIVE_PREAPERTURA)
        mov = {g["dia_txt"]: g for g in r["movimiento"]}
        self.assertEqual(set(mov), {"hoy", "ayer"})
        self.assertEqual(mov["hoy"]["mercados"], ["eeuu"])
        self.assertEqual(mov["ayer"]["mercados"], ["byma"])
        self.assertFalse(mov["ayer"]["es_hoy"])
        self.assertAlmostEqual(mov["hoy"]["usd"], 100.0, places=2)          # 10 × (600 − 590)
        self.assertAlmostEqual(mov["ayer"]["usd"],
                               round(self._var_dia_de_posiciones(27100, 1.04, 100), 2), places=2)
        self.assertEqual(r["mercados"]["byma"]["ultima_rueda"], AYER)
        self.assertEqual(r["efectivo_porcion_de_la_cartera_pct"] > 0, True)
        self.assertIn("_note", r)

    def test_con_la_rueda_abierta_todo_es_hoy(self):
        live = {"AAPL": {"c": 27300.0, "pct": 0.74}, "SPY": {"c": 20950.0, "pct": 0.24}}
        r = self._correr(live, ahora=A_LAS_15)
        self.assertEqual([g["dia_txt"] for g in r["movimiento"]], ["hoy"])
        g = r["movimiento"][0]
        self.assertEqual(sorted(g["mercados"]), ["byma", "eeuu"])
        self.assertAlmostEqual(g["usd"], round(100.0 + self._var_dia_de_posiciones(27300, 0.74, 100), 2),
                               places=2)

    def _comprar_hoy(self, asset, broker, invested, qty, ccy, tipo):
        self.conn.execute(
            "INSERT INTO positions (user_id, broker, asset, asset_type, is_cash, invested, "
            "quantity, commissions, price_override, currency, entry_date) "
            "VALUES (?,?,?,?,0,?,?,0,NULL,?,?)",
            (self.uid, broker, asset, tipo, invested, qty, ccy, HOY))
        self.conn.commit()

    def test_lo_comprado_hoy_se_mide_desde_la_compra(self):
        """Cerró ayer a 590, lo compraste hoy a 610 y vale 600: perdiste 10
        por acción. Medido desde el cierre de ayer decía que ganaste 10."""
        self.conn.execute("DELETE FROM positions WHERE asset='MSFT'")
        self._comprar_hoy("MSFT", "Schwab", 6100, 10, "USD", "stock")
        r = self._correr(LIVE_PREAPERTURA)
        hoy = next(g for g in r["movimiento"] if g["es_hoy"])
        self.assertAlmostEqual(hoy["usd"], -100.0, places=2)
        msft = next(f for f in r["activos_que_mas_movieron"] if f["asset"] == "MSFT")
        self.assertTrue(msft["comprado_hoy"])

    def test_lo_comprado_hoy_antes_de_que_abra_no_se_mide(self):
        self.conn.execute("DELETE FROM positions WHERE asset='AAPL'")
        self._comprar_hoy("AAPL", "IOL", 2_710_000, 100, "ARS", "cedear")
        r = self._correr(LIVE_PREAPERTURA)
        self.assertEqual([x["asset"] for x in r["sin_medir"]], ["AAPL"])
        self.assertTrue(all(g["mercados"] != ["byma"] for g in r["movimiento"]))

    def test_precio_y_cierre_que_no_cuadran_no_se_inventan(self):
        """Un precio en otra unidad (×100) no puede salir como un +9.900 %."""
        r = self._correr(LIVE_PREAPERTURA, precios={"AAPL.BA": 2_710_000.0, "MSFT": 600.0})
        self.assertIn("AAPL", [x["asset"] for x in r["sin_medir"]])
        self.assertIn("no cuadran", r["sin_medir"][0]["motivo"])
        self.assertTrue(all(abs(f["pct"]) < 50 for f in r["activos_que_mas_movieron"]))

    def test_el_porcentaje_es_el_de_la_pantalla_aunque_el_chat_use_otro_dolar(self):
        """El caso medido: el chat valúa el CEDEAR a otro dólar que la
        pantalla (caché del dólar frío). El % del día tiene que ser el de la
        pantalla (precio de /api/prices contra su cierre), no la mezcla."""
        r = self._correr(LIVE_PREAPERTURA,
                         precios={"AAPL.BA": 27100.0 * 1.137, "MSFT": 600.0})
        aapl = next(f for f in r["activos_que_mas_movieron"] if f["asset"] == "AAPL")
        self.assertEqual(aapl["pct"], 1.04)

    def test_el_valor_coincide_con_la_valuacion_del_snapshot(self):
        r = self._correr(LIVE_PREAPERTURA)
        with patch.object(main, "_user_tc_blue", return_value=1450.0), \
             patch.object(main, "_user_tc_cedear", return_value=self.MEP), \
             patch.object(main, "fetch_prices_for_symbols",
                          return_value={"AAPL.BA": 27100.0, "MSFT": 600.0}):
            main._CHAT_VAL_CACHE.clear()
            _, totals = main._valuate_positions_for_chat(self.conn, self.uid)
        self.assertAlmostEqual(r["valor_cartera_usd"], totals["total_value_usd"], places=2)


class VencimientoDelCacheTest(unittest.TestCase):
    """Un cierre guardado antes de que abra su mercado no sobrevive la apertura."""

    def test_proxima_apertura(self):
        utc = ZoneInfo("UTC")
        ts = lambda *a: datetime(*a, tzinfo=utc).timestamp()
        # 10:25 ART = 13:25 UTC → Nueva York abre 13:30 UTC (horario de verano).
        self.assertEqual(main._proxima_apertura("eeuu", ts(2026, 10, 8, 13, 25)), ts(2026, 10, 8, 13, 30))
        # BYMA abre 11:00 ART = 14:00 UTC; un viernes a la noche → el lunes.
        self.assertEqual(main._proxima_apertura("byma", ts(2026, 10, 9, 23, 0)), ts(2026, 10, 12, 14, 0))
        self.assertEqual(main._proxima_apertura("cripto", ts(2026, 10, 8, 23, 59)), ts(2026, 10, 9, 0, 0))

    def test_el_cache_vence_al_abrir(self):
        main._PREVCLOSE_CACHE["MSFT"] = (main.time.time(), 590.0)
        main._PREVCLOSE_VENCE["MSFT"] = main.time.time() - 1
        self.addCleanup(main._PREVCLOSE_CACHE.pop, "MSFT", None)
        self.addCleanup(main._PREVCLOSE_VENCE.pop, "MSFT", None)
        cached, faltan = main._prevclose_cache_get(["MSFT"])
        self.assertEqual(faltan, ["MSFT"])


class InvarianteHoyTest(unittest.TestCase):
    def test_hoy_solo_con_es_hoy(self):
        r = cartera_hoy.armar([_lote("BTC", 500, 490, "cripto", HOY, False)], HOY)
        self.assertNotEqual(r["movimiento"][0]["dia_txt"], "hoy")
        self.assertNotEqual(r["activos_que_mas_movieron"][0]["dia_txt"], "hoy")


class RegistroDeLaToolTest(unittest.TestCase):
    def test_pro_la_tiene_y_el_libro_del_asesor_no(self):
        nombres = {t["name"] for t in main._AI_TOOLS}
        self.assertIn("get_portfolio_today", nombres)
        # En el libro uid es la cuenta VACÍA del asesor: diría "no te moviste".
        self.assertNotIn("get_portfolio_today", {t["name"] for t in main._AI_TOOLS_ADVISOR})

    def test_el_prompt_manda_a_usarla_y_prohibe_el_30d(self):
        self.assertIn("get_portfolio_today", main._AI_CHAT_SYSTEM)
        self.assertIn("LA PREGUNTA DEL DÍA", main._AI_CHAT_SYSTEM)
        self.assertIn("delta_30d", main._AI_CHAT_SYSTEM)
        self.assertIn("nunca lo que va a pasar", main._AI_CHAT_SYSTEM)
        # En el libro la tool no existe: el prompt del libro lo tiene que decir.
        self.assertIn("get_portfolio_today NO existe", main._AI_CHAT_SYSTEM_ADVISOR)


if __name__ == "__main__":
    unittest.main()
