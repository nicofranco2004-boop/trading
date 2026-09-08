"""Una operación mal fechada no congela el calendario mensual.

CONTEXTO. `_rollover_to_current_month` garantiza que exista la fila de
`monthly_entries` del mes en curso, caminando hacia adelante desde la última
fila. Esa fila es la que `sync-unrealized` necesita para escribir el P&L no
realizado del mes.

EL BUG (auditoría 1B, casos borde). Tomaba la última fila EN ABSOLUTO
(`ORDER BY year DESC, month DESC LIMIT 1`) y cortaba con
`>= (año actual, mes actual)`. Una sola operación con fecha futura —un cupón con
año 2030, un typo— crea una fila en 2030, y a partir de ahí el rollover devuelve
0 filas creadas PARA SIEMPRE: el usuario se queda sin la fila del mes en curso
hasta que llegue 2030.

En este repo ya pasó una vez con cupones de AL35 fechados en 2027. Aquella vez se
arregló el endpoint de cupones, no la causa: cualquier otro camino que escriba
una fecha futura vuelve a congelar el calendario.

Corre con: cd backend && python3 -m pytest tests/test_rollover_fecha_futura.py
"""
import unittest
from datetime import datetime

import main


class RolloverFechaFuturaTest(unittest.TestCase):
    BROKER = "TestRollover"

    def setUp(self):
        conn = main.get_db()
        for t in ("operations", "positions", "monthly_entries", "brokers", "users"):
            try:
                conn.execute(f"DELETE FROM {t}")
            except Exception:
                pass
        self.uid = conn.execute(
            "INSERT INTO users (email,password_hash,approved,email_verified) "
            "VALUES ('roll@rendi.test','x',1,1)").lastrowid
        conn.execute("INSERT INTO brokers (user_id,name,currency) VALUES (?,?,'USDT')",
                     (self.uid, self.BROKER))
        ahora = datetime.utcnow()
        self.anio, self.mes = ahora.year, ahora.month
        # Historia real: un mes cerrado, bastante antes del actual.
        self._fila(conn, self.anio - 1, 1, capital_final=1000)
        conn.commit()
        conn.close()

    def _fila(self, conn, year, month, capital_final=0):
        conn.execute(
            """INSERT INTO monthly_entries
               (user_id,year,month,broker,deposits,withdrawals,pnl_realized,
                pnl_unrealized,capital_inicio,capital_final)
               VALUES (?,?,?,?,0,0,0,0,0,?)""",
            (self.uid, year, month, self.BROKER, capital_final))

    def _existe_mes_actual(self):
        conn = main.get_db()
        row = conn.execute(
            "SELECT 1 FROM monthly_entries WHERE user_id=? AND broker=? "
            "AND year=? AND month=?",
            (self.uid, self.BROKER, self.anio, self.mes)).fetchone()
        conn.close()
        return row is not None

    def _rollover(self):
        conn = main.get_db()
        n = main._rollover_to_current_month(conn, self.uid, self.BROKER)
        conn.commit()
        conn.close()
        return n

    def test_sin_fila_futura_crea_el_mes_actual(self):
        """El comportamiento normal, para que el fix no lo rompa."""
        self.assertGreater(self._rollover(), 0)
        self.assertTrue(self._existe_mes_actual())

    def test_una_fila_futura_no_congela_el_calendario(self):
        """REGRESIÓN: con una fila en 2030 el rollover devolvía 0 para siempre."""
        conn = main.get_db()
        self._fila(conn, 2030, 6, capital_final=51200)
        conn.commit()
        conn.close()
        self.assertGreater(self._rollover(), 0)
        self.assertTrue(self._existe_mes_actual())

    def test_la_fila_futura_no_se_toca(self):
        """Es un dato del usuario: el rollover no la borra ni la mueve. Que esté
        mal fechada se resuelve en otro lado, no acá."""
        conn = main.get_db()
        self._fila(conn, 2030, 6, capital_final=51200)
        conn.commit()
        conn.close()
        self._rollover()
        conn = main.get_db()
        row = conn.execute(
            "SELECT capital_final FROM monthly_entries WHERE user_id=? AND broker=? "
            "AND year=2030 AND month=6", (self.uid, self.BROKER)).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(float(row["capital_final"]), 51200.0, places=2)

    def test_es_idempotente(self):
        """Correr dos veces no duplica ni vuelve a crear."""
        conn = main.get_db()
        self._fila(conn, 2030, 6)
        conn.commit()
        conn.close()
        self._rollover()
        self.assertEqual(self._rollover(), 0)


if __name__ == "__main__":
    unittest.main()
