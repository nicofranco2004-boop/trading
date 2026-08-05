"""El dólar de VALUACIÓN es el punto medio (compra+venta)/2, no la punta de venta.

Reporte (2026-08-05): un usuario vio su cartera en US$ 6.884 en Rendi y US$ 6.933
en Cocos — 0,71% pareja en TODO el total, la firma de un tipo de cambio, no de un
precio. Despejado: Rendi dividía los ~10,53 M de pesos por 1.529,71 (mep venta, la
punta cara) y Cocos por ~1.518,4 (el medio de su propio spread 1.507,14/1.529,71).
Ni un precio de activo estaba mal.

`_val_rate` es la SSoT de esa tasa: el medio con fallback a venta. La regla de oro
es que frontend (pickFinancialRate) y backend (_current_*) lean el MISMO campo, o
vuelve el bug de fila≠total.

Corre con: cd backend && python3 -m pytest tests/test_dolar_medio.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ.setdefault("DB_PATH", TMP_DB.name)

import main


class ValRateTest(unittest.TestCase):
    def test_medio_de_compra_y_venta(self):
        # El caso real del usuario: 1.507,14 / 1.529,71 → medio 1.518,43.
        self.assertAlmostEqual(
            main._val_rate({"compra": 1507.14, "venta": 1529.71, "medio": 1518.43}),
            1518.43, places=2)

    def test_fallback_a_venta_sin_medio(self):
        # Caché viejo (de antes de este cambio) o casa sin `compra`: cae a venta,
        # así una cuenta no se queda sin tasa mientras el caché se repuebla.
        self.assertEqual(main._val_rate({"venta": 1529.71}), 1529.71)

    def test_numero_pelado_y_vacios(self):
        self.assertEqual(main._val_rate(1529.71), 1529.71)
        self.assertIsNone(main._val_rate(None))
        self.assertIsNone(main._val_rate({}))
        self.assertIsNone(main._val_rate({"venta": 0}))

    def test_fetch_dolar_estampa_el_medio(self):
        # `_fetch_dolar` tiene que agregar `medio` sin tocar compra/venta crudas
        # (que alimentan el display "Vendés a / Comprás a").
        import types
        fake = types.SimpleNamespace(
            status_code=200,
            json=lambda: {"compra": 1507.14, "venta": 1529.71,
                          "fechaActualizacion": "2026-08-05T14:00:00Z"})
        _orig = main.requests.get
        main.requests.get = lambda *a, **k: fake
        try:
            out = main._fetch_dolar("bolsa")
        finally:
            main.requests.get = _orig
        self.assertEqual(out["compra"], 1507.14)
        self.assertEqual(out["venta"], 1529.71)          # cruda intacta
        self.assertAlmostEqual(out["medio"], 1518.43, places=2)

    def test_sin_compra_medio_es_venta(self):
        # dolarapi a veces manda compra=0/None (cripto en ciertos momentos): sin
        # spread, el medio ES la venta.
        import types
        fake = types.SimpleNamespace(
            status_code=200,
            json=lambda: {"compra": None, "venta": 1600.0})
        _orig = main.requests.get
        main.requests.get = lambda *a, **k: fake
        try:
            out = main._fetch_dolar("cripto")
        finally:
            main.requests.get = _orig
        self.assertEqual(out["medio"], 1600.0)

    def test_current_cedear_rate_usa_el_medio(self):
        # El resolvedor de valuación del backend (snapshots/análisis/IA) tiene que
        # leer el medio, o la curva de evolución diverge de la tabla live.
        _prev = main._dolar_cache.get("data")
        _prevts = main._dolar_cache.get("ts")
        main._dolar_cache["data"] = {
            "mep": {"compra": 1507.14, "venta": 1529.71, "medio": 1518.43}}
        main._dolar_cache["ts"] = 9e18
        try:
            self.assertAlmostEqual(main._current_cedear_rate(), 1518.43, places=2)
        finally:
            main._dolar_cache["data"] = _prev
            main._dolar_cache["ts"] = _prevts or 0.0


if __name__ == "__main__":
    unittest.main()
