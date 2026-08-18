"""Los lectores de `pnl_usd` fuera de la IA: Wrapped, behavioral y Reportes.

Misma mentira que el bug del chat, en otras pantallas. `operations.pnl_usd`
guarda el monto en MONEDA DEL BROKER cuando el op_type es Cupón o Amortización,
así que un cupón de $125.000 en pesos entra como 125.000 dólares.

El caso más feo es el Wrapped: `_slide_best_trade` ORDENA por pnl_usd, así que
el cupón le gana a cualquier operación real y sale como "tu mejor trade del
año". El número es enorme y convincente, y el usuario no tiene forma de dudarlo.

Todos estos tests están escritos para FALLAR con el código viejo. El escenario
es el caso real de producción: cupón de $125.000 ARS con el MEP del día (1250)
sellado en fx_to_usd → son US$100, no US$125.000.

Corre con: cd backend && python3 -m pytest tests/test_pnl_crudo_otros_lectores.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from wrapped import build_wrapped, _slide_best_trade, _operations_for_year
from behavioral import build_behavioral_insights
from reporting.builder import fetch_operations_in_range

CUPON_ARS = 125_000.0
MEP = 1250.0
CUPON_USD = 100.0


def _cupon(date='2026-08-16', asset='AL35'):
    """Cupón en pesos con el MEP del día sellado. Vale US$100."""
    return {
        'date': date, 'asset': asset, 'op_type': 'Cupón', 'broker': 'Cocos',
        'pnl_usd': CUPON_ARS, 'currency': 'ARS', 'fx_to_usd': MEP,
        'quantity': 0, 'entry_price': None, 'exit_price': None, 'pnl_pct': None,
    }


def _venta(date, asset, pnl, qty=10, entry=100, exit_=150):
    """Venta normal en dólares. El helper NO la toca."""
    return {
        'date': date, 'asset': asset, 'op_type': 'Venta', 'broker': 'Schwab',
        'pnl_usd': pnl, 'currency': 'USD', 'fx_to_usd': 1.0,
        'quantity': qty, 'entry_price': entry, 'exit_price': exit_, 'pnl_pct': 10.0,
    }


class TestWrappedMejorTrade(unittest.TestCase):
    """El Wrapped: un cupón en pesos NO puede ser "tu mejor trade del año"."""

    def test_el_cupon_no_le_gana_a_la_venta_real(self):
        ops = [
            _venta('2026-03-10', 'NVDA', 500.0),
            _cupon('2026-08-16', 'AL35'),
        ]
        slide = _slide_best_trade(_operations_for_year(ops, 2026))
        self.assertIsNotNone(slide)
        self.assertEqual(
            slide['metric']['label'], 'NVDA',
            f"el mejor trade debería ser NVDA (+500), no el cupón. "
            f"Slide: {slide['metric']}",
        )

    def test_el_cupon_se_muestra_convertido_si_es_el_unico(self):
        """Si el cupón es lo único del año, al menos que muestre US$100."""
        slide = _slide_best_trade(_operations_for_year([_cupon()], 2026))
        self.assertIsNotNone(slide)
        self.assertIn(
            '100', slide['metric']['value'],
            f"debería mostrar US$100, muestra {slide['metric']['value']!r}",
        )
        self.assertNotIn('125.000', slide['metric']['value'])
        self.assertNotIn('125,000', slide['metric']['value'])

    def test_operations_for_year_normaliza(self):
        out = _operations_for_year([_cupon()], 2026)
        self.assertAlmostEqual(out[0]['pnl_usd'], CUPON_USD, places=2)

    def test_no_toca_las_ventas(self):
        out = _operations_for_year([_venta('2026-01-05', 'AAPL', 250.0)], 2026)
        self.assertEqual(out[0]['pnl_usd'], 250.0)

    def test_fila_vieja_sin_fx_queda_igual(self):
        viejo = {**_cupon(), 'fx_to_usd': None}
        out = _operations_for_year([viejo], 2026)
        self.assertEqual(out[0]['pnl_usd'], CUPON_ARS)

    def test_wrapped_completo_no_corona_al_cupon(self):
        """End-to-end del Wrapped, como lo ve el usuario."""
        monthly = [{
            'year': 2026, 'month': m, 'broker': 'global',
            'capital_inicio': 10000, 'capital_final': 10500,
            'deposits': 0, 'withdrawals': 0, 'pnl_realized': 500,
            'pnl_unrealized': 0,
        } for m in range(1, 13)]
        ops = [_venta('2026-03-10', 'NVDA', 500.0), _cupon()]
        out = build_wrapped(2026, monthly, ops)
        best = next((s for s in out['slides'] if s['code'] == 'best_trade'), None)
        self.assertIsNotNone(best, "debería haber slide de mejor trade")
        self.assertEqual(best['metric']['label'], 'NVDA')


class TestBehavioralWinratePayoff(unittest.TestCase):
    """behavioral: avg_win promedia pnl_usd — un cupón en pesos lo dispara."""

    def _ops(self):
        # 3 ganadoras + 2 perdedoras reales (mínimo 5) + el cupón.
        return [
            _venta('2026-01-10', 'AAPL', 300.0),
            _venta('2026-02-10', 'MSFT', 200.0),
            _venta('2026-03-10', 'NVDA', 400.0),
            _venta('2026-04-10', 'TSLA', -150.0, entry=150, exit_=100),
            _venta('2026-05-10', 'AMD', -250.0, entry=150, exit_=100),
            _cupon('2026-06-10'),
        ]

    def _card(self, ops):
        """Vamos por el orchestrator a propósito: en producción los detectores
        NO se llaman de otra forma, y la normalización vive ahí (un solo punto
        para los 12 detectores, en vez de repetir la condición en cada uno)."""
        out = build_behavioral_insights(ops, [], {}, {}, 1250.0)
        return next(c for c in out['cards'] if c['code'] == 'winrate_payoff')

    def test_avg_win_no_se_dispara_por_el_cupon(self):
        avg_win = self._card(self._ops())['evidence']['avg_win_usd']
        # Con el cupón crudo: (300+200+400+125000)/4 ≈ 31.475
        # Convertido:        (300+200+400+100)/4     = 250
        self.assertLess(
            avg_win, 1000,
            f"avg_win_usd={avg_win} — el cupón entró en pesos y disparó el promedio",
        )
        self.assertAlmostEqual(avg_win, 250.0, places=2)

    def test_expectancy_no_queda_falseada(self):
        """expectancy es lo que el usuario lee como "ganás X por operación"."""
        ev = self._card(self._ops())['evidence']
        self.assertLess(
            ev['expectancy_usd'], 1000,
            f"expectancy_usd={ev['expectancy_usd']} — inflada por el cupón en pesos",
        )

    def test_las_ventas_no_cambian(self):
        """Sin cupones el resultado tiene que ser idéntico al de siempre."""
        solo_ventas = [o for o in self._ops() if o['op_type'] == 'Venta']
        self.assertAlmostEqual(
            self._card(solo_ventas)['evidence']['avg_win_usd'], 300.0, places=2)


class TestReportingFetchOps(unittest.TestCase):
    """Reportes: la query que alimenta realized / win-loss / mejor-peor."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE operations (
                id INTEGER PRIMARY KEY, user_id INT, date TEXT, broker TEXT,
                asset TEXT, op_type TEXT, quantity REAL, entry_price REAL,
                exit_price REAL, pnl_usd REAL, pnl_pct REAL,
                currency TEXT, fx_to_usd REAL
            )""")
        self.conn.executemany(
            "INSERT INTO operations (user_id, date, broker, asset, op_type, "
            "quantity, entry_price, exit_price, pnl_usd, pnl_pct, currency, fx_to_usd) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (1, '2026-08-16', 'Cocos', 'AL35', 'Cupón', 0, None, None,
                 CUPON_ARS, None, 'ARS', MEP),
                (1, '2026-08-10', 'Schwab', 'NVDA', 'Venta', 10, 100, 150,
                 500.0, 10.0, 'USD', 1.0),
                # fila vieja: sin FX sellado, no se toca
                (1, '2026-08-12', 'Cocos', 'AL30', 'Cupón', 0, None, None,
                 42.0, None, 'ARS', None),
            ],
        )
        self.conn.commit()
        self.addCleanup(self.conn.close)

    def _ops(self):
        return fetch_operations_in_range(
            self.conn, 1, '2026-08-01', '2026-08-31', 'global')

    def test_el_cupon_llega_convertido(self):
        cupon = next(o for o in self._ops() if o['asset'] == 'AL35')
        self.assertAlmostEqual(cupon['pnl_usd'], CUPON_USD, places=2)

    def test_la_venta_no_se_toca(self):
        venta = next(o for o in self._ops() if o['asset'] == 'NVDA')
        self.assertEqual(venta['pnl_usd'], 500.0)

    def test_la_fila_vieja_queda_como_esta(self):
        vieja = next(o for o in self._ops() if o['asset'] == 'AL30')
        self.assertEqual(vieja['pnl_usd'], 42.0)

    def test_el_realized_del_periodo(self):
        """Es la suma que muestra el reporte: 500 + 100 + 42 = 642."""
        realized = sum(float(o.get("pnl_usd") or 0) for o in self._ops())
        self.assertAlmostEqual(realized, 642.0, places=2,
                               msg=f"realized={realized} — con el cupón crudo daba ~125.542")

    def test_el_mejor_del_periodo_no_es_el_cupon(self):
        """Alimenta best/worst del reporte (builder.py ~line 591)."""
        ops = [o for o in self._ops() if o.get('pnl_usd') is not None]
        best = max(ops, key=lambda o: o['pnl_usd'])
        self.assertEqual(best['asset'], 'NVDA')


if __name__ == "__main__":
    unittest.main()
