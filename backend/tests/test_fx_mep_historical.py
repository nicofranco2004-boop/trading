"""Fase B — MEP histórico en fx_rates_daily.

Columna `mep_venta` (nullable) + forward write del MEP del día + backfill
idempotente desde argentinadatos /bolsa. NINGÚN consumer la lee todavía (el
switch de consumers + el recompute van junto con el fix de bonos); esto sólo
acumula el dato sin cambiar ningún número que el usuario ve hoy.

Corre con: cd backend && python3 -m pytest tests/test_fx_mep_historical.py
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
TMP_DB.close()
os.environ["DB_PATH"] = TMP_DB.name

import main


def _bolsa_resp(rows):
    """Simula la respuesta de argentinadatos /bolsa (= dólar-MEP)."""
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = [
        {"casa": "bolsa", "compra": v, "venta": v, "fecha": f} for f, v in rows
    ]
    return m


def _read():
    """Lee fx_rates_daily en una conexión FRESCA (las fns abren la suya y commitean)."""
    c = main.get_db()
    try:
        return {r["date"]: r["mep_venta"] for r in
                c.execute("SELECT date, mep_venta FROM fx_rates_daily").fetchall()}
    finally:
        c.close()


class FxMepHistoricalTest(unittest.TestCase):
    def setUp(self):
        c = main.get_db()
        c.execute("DELETE FROM fx_rates_daily")
        c.commit()
        c.close()

    def test_schema_has_mep_venta_column(self):
        # _table_cols tiene allowlist (fx_rates_daily no está) → PRAGMA directo.
        c = main.get_db()
        try:
            cols = {r[1] for r in c.execute("PRAGMA table_info(fx_rates_daily)").fetchall()}
        finally:
            c.close()
        self.assertIn("mep_venta", cols)

    def test_forward_write_persists_mep(self):
        ok = main._persist_blue_for_date("2026-06-27", 1450.0, source="dolarapi", mep=1490.0)
        self.assertTrue(ok)
        self.assertAlmostEqual(_read()["2026-06-27"], 1490.0)

    def test_forward_write_without_mep_leaves_null(self):
        main._persist_blue_for_date("2026-06-27", 1450.0, source="dolarapi")  # mep=None
        self.assertIsNone(_read()["2026-06-27"])

    def test_forward_write_does_not_clobber_existing_mep(self):
        # COALESCE: re-escribir el blue sin mep NO debe borrar el mep ya guardado.
        main._persist_blue_for_date("2026-06-27", 1450.0, mep=1490.0)
        main._persist_blue_for_date("2026-06-27", 1460.0)  # mep=None
        self.assertAlmostEqual(_read()["2026-06-27"], 1490.0)  # preservado

    def test_backfill_fills_nulls_only(self):
        c = main.get_db()
        c.executemany(
            "INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
            [("2024-01-01", 1000.0, None),
             ("2024-01-02", 1010.0, None),
             ("2024-01-03", 1020.0, 1234.0)])  # ya tiene mep → NO se pisa
        c.commit()
        c.close()
        resp = _bolsa_resp([("2024-01-01", 1100.0), ("2024-01-02", 1111.0),
                            ("2024-01-03", 9999.0),   # existe pero ya tiene mep
                            ("2023-12-31", 990.0)])   # sin fila blue → no se inserta
        with patch.object(main.requests, "get", return_value=resp):
            main._backfill_mep_rates_if_missing()
        rows = _read()
        self.assertAlmostEqual(rows["2024-01-01"], 1100.0)  # NULL → llenado
        self.assertAlmostEqual(rows["2024-01-02"], 1111.0)  # NULL → llenado
        self.assertAlmostEqual(rows["2024-01-03"], 1234.0)  # ya tenía → intacto
        self.assertNotIn("2023-12-31", rows)                # sin fila blue → no inserta

    def test_backfill_idempotent_no_api_when_no_nulls(self):
        c = main.get_db()
        c.execute("INSERT INTO fx_rates_daily (date, blue_venta, mep_venta) VALUES (?,?,?)",
                  ("2024-01-01", 1000.0, 1100.0))
        c.commit()
        c.close()
        with patch.object(main.requests, "get") as mock_get:
            main._backfill_mep_rates_if_missing()
            mock_get.assert_not_called()  # sin NULLs → no pega a la API

    def test_backfill_survives_api_failure(self):
        c = main.get_db()
        c.execute("INSERT INTO fx_rates_daily (date, blue_venta) VALUES (?,?)",
                  ("2024-01-01", 1000.0))
        c.commit()
        c.close()
        bad = MagicMock(); bad.status_code = 500
        with patch.object(main.requests, "get", return_value=bad):
            main._backfill_mep_rates_if_missing()  # no debe romper
        self.assertIsNone(_read()["2024-01-01"])  # sigue NULL (fallback blue luego)


if __name__ == "__main__":
    unittest.main()
