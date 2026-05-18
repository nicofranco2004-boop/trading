"""Tests para los endpoints /api/export/*.csv — gate Pro + formato."""
import unittest
import uuid
import csv as _csv
from io import StringIO

import main


def _new_user(conn, is_admin: int = 0) -> int:
    email = f"export-{uuid.uuid4().hex[:12]}@rendi.test"
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, approved, is_admin) VALUES (?, 'x', 1, ?)",
        (email, is_admin),
    )
    return cur.lastrowid


class ExportCsvTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        conn = main.get_db()
        self.uid_free = _new_user(conn)
        self.uid_admin = _new_user(conn, is_admin=1)
        # Una operación cerrada del free user para el export
        conn.execute(
            """INSERT INTO operations (user_id, date, entry_date, asset, broker,
                                       op_type, quantity, entry_price, exit_price,
                                       pnl_usd, pnl_pct, commissions)
               VALUES (?, '2025-08-20', '2025-08-01', 'NVDA', 'Schwab',
                       'LONG', 10, 120.0, 145.0, 250.0, 20.83, 5.0)""",
            (self.uid_free,),
        )
        # Posición abierta + monthly entry para los otros exports
        conn.execute(
            """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                      invested, commissions, entry_date)
               VALUES (?, 'NVDA', 'Schwab', 0, 35, 4988.0, 0, '2025-08-12')""",
            (self.uid_free,),
        )
        conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                                            capital_inicio, capital_final,
                                            deposits, withdrawals, pnl_realized)
               VALUES (?, 2026, 2, 'global', 5557, 5927, 370, 0, 0)""",
            (self.uid_free,),
        )
        # Operaciones para el admin tambien
        conn.execute(
            """INSERT INTO operations (user_id, date, entry_date, asset, broker,
                                       op_type, quantity, entry_price, exit_price,
                                       pnl_usd, pnl_pct, commissions)
               VALUES (?, '2025-08-20', '2025-08-01', 'AAPL', 'Schwab',
                       'LONG', 5, 180.0, 195.0, 75.0, 8.33, 2.0)""",
            (self.uid_admin,),
        )
        conn.commit()
        conn.close()
        self.token_free = main.create_token(self.uid_free)
        self.token_admin = main.create_token(self.uid_admin)
        self.headers_free = {"Authorization": f"Bearer {self.token_free}"}
        self.headers_admin = {"Authorization": f"Bearer {self.token_admin}"}

    # ── Gate: Free is denied ─────────────────────────────────────────────────

    def test_operations_export_blocked_for_free(self):
        r = self.client.get("/api/export/operations.csv", headers=self.headers_free)
        self.assertEqual(r.status_code, 403)
        detail = r.json().get("detail", {})
        self.assertIn("upgrade", detail)
        self.assertEqual(detail["upgrade"]["feature"], "export.csv")

    def test_positions_export_blocked_for_free(self):
        r = self.client.get("/api/export/positions.csv", headers=self.headers_free)
        self.assertEqual(r.status_code, 403)

    def test_monthly_export_blocked_for_free(self):
        r = self.client.get("/api/export/monthly.csv", headers=self.headers_free)
        self.assertEqual(r.status_code, 403)

    # ── Admin can export ─────────────────────────────────────────────────────

    def test_operations_export_admin_returns_csv(self):
        r = self.client.get("/api/export/operations.csv", headers=self.headers_admin)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/csv"))
        self.assertIn("attachment", r.headers["content-disposition"])

        # Parsear CSV y validar header + 1 row
        reader = _csv.reader(StringIO(r.text))
        header = next(reader)
        self.assertEqual(header[0], "Fecha cierre")
        self.assertEqual(header[2], "Activo")
        rows = list(reader)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][2], "AAPL")

    def test_positions_export_admin_returns_csv(self):
        # Insertar una posición para el admin user
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                      invested, commissions)
               VALUES (?, 'NVDA', 'Schwab', 0, 35, 4988.0, 0)""",
            (self.uid_admin,),
        )
        conn.commit()
        conn.close()
        r = self.client.get("/api/export/positions.csv", headers=self.headers_admin)
        self.assertEqual(r.status_code, 200)
        # Validar que la posición está en el CSV
        self.assertIn("NVDA", r.text)
        self.assertIn("Activo", r.text)  # header en español

    def test_monthly_export_admin_returns_csv(self):
        conn = main.get_db()
        conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                                            capital_inicio, capital_final,
                                            deposits, withdrawals, pnl_realized)
               VALUES (?, 2026, 3, 'global', 6000, 6500, 400, 50, 100)""",
            (self.uid_admin,),
        )
        conn.commit()
        conn.close()
        r = self.client.get("/api/export/monthly.csv", headers=self.headers_admin)
        self.assertEqual(r.status_code, 200)
        self.assertIn("2026-03", r.text)
        self.assertIn("Período", r.text)

    # ── Requires auth ────────────────────────────────────────────────────────

    def test_export_requires_auth(self):
        for path in ("operations.csv", "positions.csv", "monthly.csv", "transactions.csv"):
            r = self.client.get(f"/api/export/{path}")
            self.assertIn(r.status_code, (401, 403), f"{path}: esperaba 401/403")

    # ── transactions.csv: export consolidado ─────────────────────────────────

    def test_transactions_export_blocked_for_free(self):
        r = self.client.get("/api/export/transactions.csv", headers=self.headers_free)
        self.assertEqual(r.status_code, 403)

    def test_transactions_export_includes_manual_operations_and_positions(self):
        """El export consolidado debe incluir la venta manual + la posición
        manual del user admin (insertadas en setUp)."""
        r = self.client.get("/api/export/transactions.csv", headers=self.headers_admin)
        self.assertEqual(r.status_code, 200)
        # admin tiene 1 venta manual (AAPL) que debería generar 2 rows: COMPRA + VENTA
        self.assertIn("AAPL", r.text)
        self.assertIn("VENTA", r.text)
        # Header en español
        self.assertIn("Tipo", r.text)
        self.assertIn("Broker", r.text)

    def test_transactions_export_includes_manual_monthly_deposits(self):
        """Depósitos cargados via monthly_entries deben aparecer como DEPÓSITO."""
        conn = main.get_db()
        # Monthly entry no-global con depósito + retiro
        conn.execute(
            """INSERT INTO monthly_entries (user_id, year, month, broker,
                                            capital_inicio, capital_final,
                                            deposits, withdrawals, pnl_realized)
               VALUES (?, 2025, 9, 'Schwab', 5000, 5500, 600, 100, 0)""",
            (self.uid_admin,),
        )
        conn.commit()
        conn.close()
        r = self.client.get("/api/export/transactions.csv", headers=self.headers_admin)
        self.assertEqual(r.status_code, 200)
        self.assertIn("DEPÓSITO", r.text)
        self.assertIn("RETIRO", r.text)

    def test_transactions_export_includes_manual_open_positions(self):
        """Posiciones abiertas manuales (entry_date set, no cash) deben
        aparecer como COMPRA en el export consolidado."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                      invested, buy_price, commissions, entry_date)
               VALUES (?, 'MSFT', 'Schwab', 0, 5, 1500, 300, 0, '2025-06-15')""",
            (self.uid_admin,),
        )
        conn.commit()
        conn.close()
        r = self.client.get("/api/export/transactions.csv", headers=self.headers_admin)
        self.assertEqual(r.status_code, 200)
        # MSFT debe estar en el CSV como COMPRA
        self.assertIn("MSFT", r.text)
        self.assertIn("COMPRA", r.text)
        self.assertIn("2025-06-15", r.text)

    def test_transactions_export_includes_positions_without_entry_date(self):
        """Regression: posiciones legacy sin entry_date deben aparecer en el
        export (no filtrarse). Bug detectado por el user — la mayoría de
        positions manuales viejas no tienen fecha registrada."""
        conn = main.get_db()
        conn.execute(
            """INSERT INTO positions (user_id, asset, broker, is_cash, quantity,
                                      invested, buy_price, commissions)
               VALUES (?, 'NVDA', 'cocos', 0, 28, 306320, 10940, 0)""",
            (self.uid_admin,),
        )
        conn.commit()
        conn.close()
        r = self.client.get("/api/export/transactions.csv", headers=self.headers_admin)
        self.assertEqual(r.status_code, 200)
        self.assertIn("NVDA", r.text)
        self.assertIn("sin fecha registrada", r.text)

    def test_transactions_export_futures_use_pnl_as_monto(self):
        """Regression: operaciones de futuros (sin quantity/precios pero con
        pnl_usd) deben mostrar el pnl_usd como Monto en lugar de 0."""
        conn = main.get_db()
        # Operación SHORT Futuros con pérdida de $20
        conn.execute(
            """INSERT INTO operations (user_id, date, broker, asset, op_type,
                                       pnl_usd, commissions)
               VALUES (?, '2025-06-22', 'Binance', 'BTC/USDT', 'SHORT Futuros', -20.0, 0)""",
            (self.uid_admin,),
        )
        conn.commit()
        conn.close()
        r = self.client.get("/api/export/transactions.csv", headers=self.headers_admin)
        self.assertEqual(r.status_code, 200)
        # Buscar la línea de la futuros
        for line in r.text.split("\n"):
            if "BTC/USDT" in line and "Futuros" in line:
                # Monto debe ser -20, no 0
                self.assertIn("-20", line, f"Esperaba -20 en monto, línea: {line}")
                self.assertIn("VENTA", line)
                return
        self.fail("No se encontró la fila de BTC/USDT Futuros")


if __name__ == "__main__":
    unittest.main()
