"""El precio de un FCI viaja CON su fecha (pricing.fci.get_prices_detail_for).

Por qué existe: la fuente (CAFCI vía ArgentinaDatos) dejó de publicar entre el
2026-07-21 y el 2026-08-13 — tres semanas — y el VCP viejo se seguía mostrando
como si fuera de hoy. El valor no era falso; presentarlo SIN fecha sí era el bug.

Corre con: cd backend && python3 -m pytest tests/test_fci_price_as_of.py
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

from pricing import fci


class FciPriceAsOfTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        fci.ensure_tables(self.conn)
        self.conn.execute(
            "INSERT INTO fci_prices (symbol, price, moneda, as_of_date, fetched_at) "
            "VALUES ('FCI:FIMA-ACCIONES-A', 277.297694, 'ARS', '2026-07-21', '2026-08-13')")
        self.conn.execute(
            "INSERT INTO fci_prices (symbol, price, moneda, as_of_date, fetched_at) "
            "VALUES ('FCI:SIN-PRECIO', NULL, 'ARS', '2026-08-13', '2026-08-13')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_detalle_trae_precio_y_fecha(self):
        d = fci.get_prices_detail_for(self.conn, ["FCI:FIMA-ACCIONES-A"])
        self.assertAlmostEqual(d["FCI:FIMA-ACCIONES-A"]["price"], 277.297694, places=6)
        self.assertEqual(d["FCI:FIMA-ACCIONES-A"]["as_of"], "2026-07-21")

    def test_get_prices_for_sigue_devolviendo_el_mapa_plano(self):
        # El endpoint /api/prices mergea esto en su respuesta: si cambiara de forma,
        # todas las pantallas dejarían de valuar los fondos.
        p = fci.get_prices_for(self.conn, ["FCI:FIMA-ACCIONES-A"])
        self.assertEqual(p, {"FCI:FIMA-ACCIONES-A": 277.297694})

    def test_sin_precio_no_aparece(self):
        for fn in (fci.get_prices_for, fci.get_prices_detail_for):
            self.assertNotIn("FCI:SIN-PRECIO", fn(self.conn, ["FCI:SIN-PRECIO"]))

    def test_ignora_simbolos_que_no_son_fci(self):
        self.assertEqual(fci.get_prices_detail_for(self.conn, ["AAPL", "GGAL.BA"]), {})


if __name__ == "__main__":
    unittest.main()
