"""Los últimos 6 lectores de `pnl_usd` crudo: el CSV del contador, Reportes,
"Todos los movimientos" y 3 builders de la IA.

El CSV va primero por una razón que no es el tamaño del error: es el ÚNICO
lector cuyo número sale de la app hacia un tercero. El usuario lo abre en una
planilla y lo usa para una declaración; después Rendi ya no lo puede corregir.
Los demás los ve en pantalla y los puede volver a mirar mañana.

Escenario de siempre: cupón de $125.000 ARS con el MEP del día (1250) sellado
en fx_to_usd → son US$100. Todos estos tests fallan con el código viejo.

Corre con: cd backend && python3 -m pytest tests/test_pnl_crudo_csv_y_builders.py
"""
import csv as _csv
import os
import sys
import unittest
import uuid
from io import StringIO

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main

CUPON_ARS = 125_000.0
MEP = 1250.0
CUPON_USD = 100.0


def _new_admin(conn):
    """Admin para pasar el gate Pro de los exports."""
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin) "
        "VALUES (?, 'x', 1, 1)",
        (f"csvcupon-{uuid.uuid4().hex[:10]}@rendi.test",),
    )
    return cur.lastrowid


def _cupon(conn, uid, asset='AL35', date='2026-08-16'):
    """Cupón en pesos con el MEP sellado. quantity/precios NULL, como el real."""
    conn.execute(
        """INSERT INTO operations (user_id, date, broker, asset, op_type,
                                   pnl_usd, currency, fx_to_usd)
           VALUES (?, ?, 'Cocos', ?, 'Cupón', ?, 'ARS', ?)""",
        (uid, date, asset, CUPON_ARS, MEP))


def _venta(conn, uid, asset='NVDA', pnl=500.0, date='2026-08-10'):
    conn.execute(
        """INSERT INTO operations (user_id, date, entry_date, broker, asset,
                                   op_type, quantity, entry_price, exit_price,
                                   pnl_usd, pnl_pct, currency, fx_to_usd)
           VALUES (?, ?, '2026-08-01', 'Schwab', ?, 'Venta', 10, 100, 150,
                   ?, 10.0, 'USD', 1.0)""",
        (uid, date, asset, pnl))


class TestCsvDelContador(unittest.TestCase):
    """GET /api/export/operations.csv — la columna dice "P&L USD"."""

    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = _new_admin(conn)
        _cupon(conn, self.uid)
        _venta(conn, self.uid)
        conn.commit()
        conn.close()
        self.headers = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def _filas(self):
        r = self.client.get("/api/export/operations.csv", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        reader = _csv.reader(StringIO(r.text))
        header = next(reader)
        idx_pnl = header.index("P&L USD")
        idx_activo = header.index("Activo")
        return {row[idx_activo]: row[idx_pnl] for row in reader}

    def test_el_cupon_se_exporta_en_dolares(self):
        """Lo que se manda al contador tiene que ser USD de verdad."""
        pnl = float(self._filas()["AL35"])
        self.assertAlmostEqual(
            pnl, CUPON_USD, places=2,
            msg=f"el CSV declara {pnl} bajo un encabezado que dice 'P&L USD'. "
                f"Si es ~125.000 son pesos yéndose a una declaración.",
        )

    def test_la_venta_no_cambia(self):
        self.assertAlmostEqual(float(self._filas()["NVDA"]), 500.0, places=2)


class TestUltimaOperacionEnReportes(unittest.TestCase):
    """portfolio_snapshot.last_op — la tarjeta 'última operación'."""

    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        self.uid = _new_admin(self.conn)
        _venta(self.conn, self.uid, date='2026-08-10')
        _cupon(self.conn, self.uid, date='2026-08-16')   # la más reciente
        self.conn.commit()

    def test_el_cupon_como_ultima_operacion_va_convertido(self):
        out = main._portfolio_snapshot_summary(self.conn, self.uid)
        last = out.get("last_op")
        self.assertIsNotNone(last)
        self.assertEqual(last["asset"], "AL35", "la última debería ser el cupón")
        self.assertAlmostEqual(
            last["pnl_usd"], CUPON_USD, places=2,
            msg=f"Reportes mostraría US${last['pnl_usd']:,.0f}",
        )


class TestTodosLosMovimientos(unittest.TestCase):
    """GET /api/movements — la vista contadora. El monto del cupón cae a `pnl`
    porque la fila no tiene exit_price ni quantity."""

    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid = _new_admin(conn)
        _cupon(conn, self.uid)
        conn.commit()
        conn.close()
        self.headers = {"Authorization": f"Bearer {main.create_token(self.uid)}"}

    def test_amount_usd_y_pnl_usd_van_convertidos(self):
        r = self.client.get("/api/movements", headers=self.headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        movs = data if isinstance(data, list) else (data.get("movements") or [])
        fila = next((m for m in movs if m.get("asset") == "AL35"), None)
        self.assertIsNotNone(fila, f"no encontré la fila del cupón en {len(movs)} movs")
        # El frontend trata amount_usd como USD canónico y sólo MULTIPLICA por
        # fx para mostrar en pesos (useHistoricalMoney.js:61) — nunca divide.
        self.assertAlmostEqual(
            fila["amount_usd"], CUPON_USD, places=2,
            msg=f"amount_usd={fila['amount_usd']}; con el toggle en pesos esto "
                f"se multiplica por {MEP} y muestra ~$156 millones",
        )
        self.assertAlmostEqual(fila["pnl_usd"], CUPON_USD, places=2)


class TestBuildersDeLaIA(unittest.TestCase):
    """Los 3 builders que el barrido encontró después del acuerdo."""

    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)
        self.uid = _new_admin(self.conn)
        _venta(self.conn, self.uid, 'NVDA', 500.0)
        _cupon(self.conn, self.uid, 'AL35')
        self.conn.commit()

    def test_operations_total_y_mejor_trade(self):
        from ai.builders import operations
        out = operations.build(self.conn, self.uid)
        self.assertAlmostEqual(
            out["total_pnl_usd"], 600.0, places=2,
            msg=f"total_pnl_usd={out['total_pnl_usd']} — con el cupón crudo daba 125.500",
        )
        self.assertEqual(
            out["best_trade"]["ticker"], "NVDA",
            "el mejor trade no puede ser un cupón de renta fija en pesos",
        )

    def test_operation_trade_pnl_y_rank(self):
        """El rank usa igualdad exacta de floats: si un lado se convierte y el
        otro no, queda None en silencio."""
        from ai.builders import operation_trade
        op_id = self.conn.execute(
            "SELECT id FROM operations WHERE user_id=? AND asset='AL35'",
            (self.uid,)).fetchone()["id"]
        out = operation_trade.build(self.conn, self.uid, operation_id=op_id)
        self.assertAlmostEqual(out["trade"]["pnl_usd"], CUPON_USD, places=2)
        self.assertIsNotNone(
            out["user_context"]["rank_in_year"],
            "rank_in_year quedó en None — los dos lados no se convirtieron igual",
        )
        # 100 < 500 → el cupón es el 2º del año, no el 1º
        self.assertEqual(out["user_context"]["rank_in_year"], 2)

    def test_position_lots_de_un_bono(self):
        from ai.builders import position_lots
        out = position_lots.build(self.conn, self.uid, asset="AL35")
        con_pnl = [l for l in out["lots"] if l.get("pnl_usd") is not None]
        self.assertTrue(con_pnl, "debería haber al menos un lote con pnl")
        self.assertAlmostEqual(
            con_pnl[0]["pnl_usd"], CUPON_USD, places=2,
            msg="el LLM vería un lote de 125.000 rotulado pnl_usd",
        )


if __name__ == "__main__":
    unittest.main()
