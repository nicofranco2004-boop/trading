# -*- coding: utf-8 -*-
"""El ✦ "¿Cuál fue mi peor caída y cuánto tardé en recuperarla?" tiene que decir
el MISMO número que la tarjeta "Curva de drawdown" de Métricas.

EL BUG (2026-09-25). La tarjeta muestra "Actual" y "Máx histórico" de
`twr.curva_indexada`, que encadena `dietz`: descuenta aportes y retiros. El
paquete del ✦ (`insights.drawdown`) y el bloque `drawdown` del ✦ general de
Métricas (`insights`) medían sobre el VALOR de la cartera:

    caída = (valor − valor_máximo) / valor_máximo

Así, sacar 10.000 de una cartera de 20.000 con el mercado quieto era "una caída
del 50 %", y la pantalla —al lado— decía 0,0 %.

TODOS LOS TESTS DE ACÁ PASAN POR EL MISMO CAMINO QUE PRODUCCIÓN: el pedido que
arma el botón ✦ entra por /api/ai/chat, el servidor arma el paquete, y se mira lo
que le llega AL MODELO. El número de la pantalla se pide también por su camino de
producción: GET /api/insights/performance, con los mismos parámetros que manda
Insights.jsx. Lo único simulado es lo que sale de la máquina (el modelo, las
cotizaciones).
"""
import json
import os
import unittest
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import main
import snapshots_job
import twr
from fechas import hoy_art


class _TB:
    type = "text"

    def __init__(self, t):
        self.text = t

    def model_dump(self):
        return {"type": "text", "text": self.text}


class _Resp:
    def __init__(self, content, stop="end_turn"):
        self.content, self.stop_reason, self.usage = content, stop, None


def _hace(dias: int) -> str:
    return (date.fromisoformat(hoy_art()) - timedelta(days=dias)).isoformat()


# Lo que manda el ✦ según la versión de la página:
#   · la que está hoy en producción manda sólo `window_days` — el arreglo del
#     servidor tiene que funcionar igual, sin esperar al deploy del frontend;
#   · la nueva manda la moneda del selector y el valor de ahora (`paramsCaidaIA`
#     en Insights.jsx), que es lo que la tarjeta usa para cerrar la curva.
PAGINA_VIEJA = {"window_days": 365}


def pagina_nueva(moneda="usd", valor_live=None):
    return {"moneda": moneda, "valor_live": valor_live}


def _numeros(nodo):
    """Todos los números de un paquete, a cualquier profundidad."""
    if isinstance(nodo, bool):
        return
    if isinstance(nodo, (int, float)):
        yield round(float(nodo), 4)
    elif isinstance(nodo, dict):
        for v in nodo.values():
            yield from _numeros(v)
    elif isinstance(nodo, list):
        for v in nodo:
            yield from _numeros(v)


# Una caída de verdad y un retiro, en ese orden:
#   hace 10 días   20.000   (aportado 20.000)
#   hace  9 días   18.000   el mercado bajó 10 %
#   hace  8 días    9.000   retiró 9.000 — el mercado, quieto
#   hace  7 días    9.900   el mercado sube 10 %: todavía −1 % abajo del pico
#   hace  6 días   10.100   supera el pico: se recuperó
# Medido como rendimiento: la peor caída es −10 % y tardó 4 días en recuperarse
# (3 desde el fondo).
# Medido sobre el valor (lo viejo): −55 % (de 20.000 a 9.000) y "actual −49,5 %".
CAIDA_Y_RETIRO = [(10, 20000, 20000), (9, 18000, 20000), (8, 9000, 11000),
                  (7, 9900, 11000), (6, 10100, 11000)]
LO_QUE_DECIA_EL_VALOR = (-55.0, -49.5)


class _Base(unittest.TestCase):
    TIER = "pro"

    def setUp(self):
        self.conn = main.get_db()
        cur = self.conn.execute(
            "INSERT INTO users (email, password_hash, tier, approved) VALUES (?,?,?,1)",
            ("caida-medida-%s@rendi.test" % os.urandom(4).hex(), "x", self.TIER))
        self.uid = cur.lastrowid
        # Una operación cerrada hace 120 días: sin algo no-cash en la historia,
        # `clasificar_fila` no puede afirmar que un cierre sea una medición. Va como
        # OPERACIÓN y no como posición abierta para que el chat no tenga nada que
        # cotizar.
        self.conn.execute(
            "INSERT INTO operations (user_id, date, entry_date, asset, op_type, broker, "
            "quantity, entry_price, exit_price, pnl_usd) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (self.uid, _hace(119), _hace(120), "AAPL", "Venta", "Schwab",
             1, 100.0, 100.0, 0.0))
        self.conn.execute(
            "INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
            (self.uid, "Schwab", "USD"))
        self.conn.commit()
        self.addCleanup(self._limpiar)
        self.token = main.create_token(self.uid)
        self.client = TestClient(main.app)
        self.visto = {}
        self._fx = []

        def fake_create(**kw):
            self.visto.update(kw)
            return _Resp([_TB("Listo.")])

        mc = MagicMock()
        mc.messages.create.side_effect = fake_create
        precios = lambda syms, *_a, **_k: {s: 100.0 for s in syms}  # noqa: E731
        for p in (
            patch.object(main, "_get_anthropic_client", return_value=mc),
            patch.object(main, "_kick_bench_refresh", lambda: None),
            patch.object(snapshots_job, "fetch_prices_for_symbols", precios),
            patch.object(main, "fetch_prices_for_symbols", precios),
            patch.object(main, "_get_mep_for_scheduler", lambda: 1400.0),
            patch.object(main, "_fetch_batch_quotes", lambda *_a, **_k: {}),
            patch.object(main, "_get_portfolio_events_cached", lambda *_a, **_k: []),
        ):
            p.start()
            self.addCleanup(p.stop)
        snapshots_job._LIVE_VALUE_CACHE.clear()
        main._CHAT_VAL_CACHE.clear()

    def _limpiar(self):
        # La tabla global primero y en su propio try: si falla algo de abajo, no
        # puede dejarle al test siguiente un TC sucio.
        try:
            for f in self._fx:
                self.conn.execute("DELETE FROM fx_rates_daily WHERE date=?", (f,))
            self.conn.commit()
        except Exception:
            pass
        for t in ("snapshots", "operations", "brokers", "monthly_entries",
                  "ai_usage_daily", "ai_analyses_cache"):
            try:
                self.conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
            except Exception:
                pass
        self.conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
        self.conn.commit()
        self.conn.close()

    def cierre(self, dias_atras: int, valor: float, aportado: float):
        """Un cierre del cron, estampado como lo estampa el cron."""
        base, apto = twr.base_y_apto_para(twr.MEDICION)
        self.conn.execute(
            "INSERT INTO snapshots (user_id, date, total_value, total_invested, "
            "net_deposited, fx_to_usd_blue, source, holdings_json, base, apto) "
            "VALUES (?,?,?,?,?,1400,'cron','[{\"a\":1}]',?,?)",
            (self.uid, _hace(dias_atras), valor, valor, aportado, base, apto))
        self.conn.commit()

    def cierres(self, filas):
        for d, v, a in filas:
            self.cierre(d, v, a)

    def contabilidad_del_retiro(self):
        """El retiro de 9.000 en la cadena mensual, en el mes en que ocurrió. Es de
        donde el servidor saca lo aportado HOY para la pata del valor vivo: sin
        esto, "hoy" leería 11.000 de retiro fantasma."""
        d = date.fromisoformat(_hace(8))
        self.conn.execute(
            "INSERT INTO monthly_entries (user_id, year, month, broker, deposits, "
            "withdrawals, pnl_realized, pnl_unrealized, capital_inicio, capital_final) "
            "VALUES (?,?,?,'global',0,?,0,0,?,?)",
            (self.uid, d.year, d.month, 9000.0, 20000.0, 10100.0))
        self.conn.commit()

    def tipo_de_cambio(self):
        """Un dólar que sube 1 % por día, para que la cartera en pesos no sea la de
        dólares con otro rótulo."""
        for i, dias in enumerate(range(12, -1, -1)):
            f = _hace(dias)
            tc = round(1000.0 * (1.01 ** i), 4)
            self.conn.execute("DELETE FROM fx_rates_daily WHERE date=?", (f,))
            self.conn.execute(
                "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta, source) "
                "VALUES (?,?,?,'manual')", (f, tc, tc))
            self._fx.append(f)
        self.conn.commit()

    # ── Lo que ve el usuario ────────────────────────────────────────────────
    def pantalla(self, **q) -> dict:
        """Lo que pide Insights.jsx para la tarjeta: /insights/performance en modo
        certero (la tarjeta de drawdown sólo existe en certero)."""
        qs = "&".join(f"{k}={v}" for k, v in {"bench": "sp500", "modo": "certero", **q}.items())
        r = self.client.get(f"/api/insights/performance?{qs}",
                            headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    # ── Lo que vio el modelo ────────────────────────────────────────────────
    def paquete(self, screen, params) -> dict:
        r = self.client.post(
            "/api/ai/chat",
            headers={"Authorization": f"Bearer {self.token}"},
            json={"messages": [{"role": "user", "content": "✦"}],
                  "snapshot": {"summary": {}, "positions": [], "operations": [],
                               "monthly": [], "brokers": []},
                  "stream": False,
                  "analisis": {"screen": screen, "params": params}})
        self.assertEqual(r.status_code, 200, r.text)
        for m in self.visto.get("messages", []):
            if m.get("role") != "user":
                continue
            c = m["content"]
            texto = c[0]["text"] if isinstance(c, list) else c
            i = texto.index("```json\n") + len("```json\n")
            ctx = json.loads(texto[i:texto.index("\n```", i)])
            self.assertIn("analisis_del_boton", ctx, "el ✦ llegó sin su paquete")
            return ctx["analisis_del_boton"]
        self.fail("el modelo no recibió contexto")


class ElBotonDeLaCaidaTest(_Base):
    """El ✦ de la tarjeta "Curva de drawdown" (topic insights.drawdown)."""

    def test_un_retiro_no_es_una_caida(self):
        """El caso del pedido: 20.000 → 10.000 porque sacó la mitad, con el mercado
        quieto. La pantalla dice 0,0 %; el paquete decía −50 %. Con la página que
        hoy está en producción: el arreglo no depende del frontend."""
        self.cierres([(10, 20000, 20000), (9, 20000, 20000),
                      (8, 10000, 10000), (7, 10000, 10000)])
        p = self.paquete("insights.drawdown", PAGINA_VIEJA)
        numeros = set(_numeros(p))
        self.assertNotIn(-50.0, numeros)
        self.assertNotIn(-0.5, numeros)
        self.assertEqual(p["max_pct"], 0.0)
        self.assertEqual(p["current_pct"], 0.0)
        self.assertEqual(p["dd_events"], [])
        self.assertIs(p["recovered"], True)

    def test_la_caida_de_verdad_se_mide_sin_el_retiro(self):
        """Una caída del 10 % y, en el fondo, un retiro de la mitad. La caída es
        −10 %, no −55 %; y se recuperó: el ✦ tiene que poder decir en cuánto."""
        self.cierres(CAIDA_Y_RETIRO)
        p = self.paquete("insights.drawdown", pagina_nueva())
        for viejo in LO_QUE_DECIA_EL_VALOR:
            self.assertNotIn(viejo, set(_numeros(p)))
        self.assertEqual(p["max_pct"], -10.0)
        self.assertEqual(p["current_pct"], 0.0)
        self.assertEqual(p["max_date"], _hace(9))
        self.assertEqual(p["max_peak_date"], _hace(10))
        self.assertIs(p["recovered"], True)
        self.assertEqual(p["days_since_peak"], 0)
        # El evento: del pico (hace 10) al fondo (hace 9) y de vuelta arriba (hace 6).
        self.assertEqual(p["events_count"], 1)
        ev = p["dd_events"][0]
        self.assertEqual(ev["depth_pct"], -10.0)
        self.assertEqual((ev["start_date"], ev["trough_date"], ev["end_date"]),
                         (_hace(10), _hace(9), _hace(6)))
        self.assertEqual(ev["duration_days"], 4)
        self.assertEqual(ev["recovery_days"], 3)
        self.assertEqual(p["worst_event"], ev)
        # Los valores de la cartera NO viajan: restados, son justo el −55 %.
        self.assertNotIn("peak_value", p)
        self.assertNotIn("trough_value", p)

    def test_dice_el_mismo_numero_que_la_tarjeta(self):
        """Lo que la tarjeta muestra como "Actual" y "Máx histórico"."""
        self.cierres(CAIDA_Y_RETIRO[:3])           # termina en el fondo, sin recuperar
        pant = self.pantalla()
        p = self.paquete("insights.drawdown", pagina_nueva())
        self.assertAlmostEqual(p["current_pct"], pant["drawdown_actual"] * 100, places=2)
        self.assertAlmostEqual(p["max_pct"], pant["drawdown_maximo"] * 100, places=2)
        self.assertEqual(p["current_pct"], -10.0)
        self.assertIs(p["recovered"], False)
        # Sigue abierta: sin fecha de salida, y lleva 2 días desde el pico (hace 10)
        # hasta la última medición (hace 8).
        ev = p["dd_events"][0]
        self.assertIsNone(ev["end_date"])
        self.assertIsNone(ev["recovery_days"])
        self.assertEqual(p["days_since_peak"], 2)

    def test_con_el_valor_de_hoy_dice_lo_mismo_que_la_tarjeta(self):
        """La tarjeta cierra la curva con la cartera de AHORA (`valor_live`): si el
        ✦ no la recibe, a media rueda dice el número de anoche."""
        self.cierres(CAIDA_Y_RETIRO)
        self.contabilidad_del_retiro()
        pant = self.pantalla(valor_live=9595)          # hoy −5 % desde 10.100
        self.assertEqual(pant["curva"][-1]["date"], "hoy")
        p = self.paquete("insights.drawdown", pagina_nueva(valor_live=9595))
        self.assertTrue(p["incluye_hoy"])
        self.assertEqual(p["current_pct"], -5.0)
        self.assertAlmostEqual(p["current_pct"], pant["drawdown_actual"] * 100, places=2)
        self.assertAlmostEqual(p["max_pct"], pant["drawdown_maximo"] * 100, places=2)
        self.assertEqual(p["medido_hasta"], hoy_art())

    def test_en_pesos_dice_lo_mismo_que_la_tarjeta_en_pesos(self):
        """Con el selector en pesos la tarjeta mide en pesos (incluye la
        devaluación). El ✦ tiene que medir en la misma moneda que la pantalla."""
        self.cierres(CAIDA_Y_RETIRO[:3])
        self.tipo_de_cambio()
        pant = self.pantalla(moneda="ars")
        self.assertEqual(pant["moneda"], "ars")
        p = self.paquete("insights.drawdown", pagina_nueva(moneda="ars"))
        self.assertEqual(p["moneda"], "ars")
        self.assertAlmostEqual(p["current_pct"], pant["drawdown_actual"] * 100, places=2)
        self.assertAlmostEqual(p["max_pct"], pant["drawdown_maximo"] * 100, places=2)
        # Y no es el de dólares con otro rótulo.
        en_usd = self.paquete("insights.drawdown", pagina_nueva(moneda="usd"))
        self.assertNotAlmostEqual(p["max_pct"], en_usd["max_pct"], places=2)

    def test_sin_mediciones_no_afirma_nada(self):
        self.cierre(8, 10000, 10000)
        p = self.paquete("insights.drawdown", pagina_nueva())
        self.assertIsNone(p["current_pct"])
        self.assertIsNone(p["max_pct"])
        self.assertIsNone(p["recovered"])
        self.assertTrue(p["insufficient_data"])
        self.assertTrue(p["reason"])


class ElBotonGeneralDeMetricasTest(_Base):
    """El ✦ del encabezado de Métricas (topic insights) trae un bloque `drawdown`
    con el mismo defecto: la tira de KPIs muestra "Drawdown actual" de la misma
    fuente que la tarjeta."""

    def test_un_retiro_no_es_una_caida(self):
        self.cierres([(10, 20000, 20000), (9, 20000, 20000),
                      (8, 10000, 10000), (7, 10000, 10000)])
        dd = self.paquete("insights", PAGINA_VIEJA)["drawdown"]
        self.assertNotIn(-50.0, set(_numeros(dd)))
        self.assertEqual(dd["max_pct"], 0.0)
        self.assertEqual(dd["current_pct"], 0.0)

    def test_dice_el_mismo_numero_que_la_pantalla(self):
        self.cierres(CAIDA_Y_RETIRO[:3])
        pant = self.pantalla()
        dd = self.paquete("insights", {**PAGINA_VIEJA, **pagina_nueva()})["drawdown"]
        self.assertAlmostEqual(dd["current_pct"], pant["drawdown_actual"] * 100, places=2)
        self.assertAlmostEqual(dd["max_pct"], pant["drawdown_maximo"] * 100, places=2)
        self.assertEqual(dd["days_since_peak"], 2)


if __name__ == "__main__":
    unittest.main()
