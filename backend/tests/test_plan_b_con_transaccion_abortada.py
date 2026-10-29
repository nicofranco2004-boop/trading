"""El PLAN B que corre después de un error de SQL: en Postgres no corría.

LA FORMA, que es la misma en nueve lugares del backend (barrido con AST el
2026-10-29): se intenta una sentencia, y si falla, el `except` **vuelve a hablar
con la base** — una consulta más corta sin la columna nueva, un INSERT sin la
marca, un SELECT para recuperarse de una carrera. En SQLite eso funciona: la
sentencia que falló no deja secuela. En Postgres la transacción queda ABORTADA y
el plan B revienta con `InFailedSqlTransaction`, un error DISTINTO del original
que el `except` de afuera no reconoce. Resultado: la red escrita para que algo
no se cayera es exactamente lo que se cae.

Los dos casos de acá son los que NO necesitan una base a medio migrar para
aparecer: pasan con el esquema correcto y en el uso normal.

  1. Un email repetido en el registro. El `except` de afuera lo convierte en un
     409 amable ("ese email ya está registrado"); con la transacción abortada
     llegaba otro error y salía un 500. (Lo cubre además
     test_email_verification::…_returns_409_with_code, que estaba ROJO en
     Postgres y verde en SQLite.)
  2. Una columna que todavía no existe, en la consulta que corre en TODOS los
     pedidos con sesión. Es la red puesta después de la caída del 2026-08-02
     (el índice antes que su columna) y era la que no funcionaba.

Entran por el camino real: el endpoint HTTP, no la función de adentro.
"""
import os, sys, unittest, uuid
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path: sys.path.insert(0, BACKEND)
import main


def _motor():
    return "Postgres" if getattr(main, "USANDO_PG", False) else "SQLite"


def setUpModule():
    global _sin_rate_limit
    _sin_rate_limit = patch("main._check_rate_limit")
    _sin_rate_limit.start()


def tearDownModule():
    _sin_rate_limit.stop()


class PlanBTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)
        self.email = f"planb-{uuid.uuid4().hex[:10]}@rendi.test"

    def _alta(self, email=None):
        return self.client.post("/api/auth/register", json={
            "email": email or self.email, "name": "Plan B", "password": "Secreta-123",
        })

    # ── 1) El email repetido tiene que seguir siendo un 409 ──────────────────
    def test_email_repetido_contesta_409_y_no_un_500(self):
        """El segundo alta con el mismo email: 409, no 500.

        En Postgres el INSERT que choca contra el UNIQUE abortaba la
        transacción, y el INSERT de respaldo (el que entra "sin la marca" cuando
        falta la columna `requires_plan`) levantaba `InFailedSqlTransaction` —
        que no es un error de integridad, así que el 409 nunca se armaba.
        """
        r1 = self._alta()
        self.assertEqual(r1.status_code, 200, f"[{_motor()}] el primer alta falló: {r1.text[:200]}")
        r2 = self._alta()
        self.assertEqual(
            r2.status_code, 409,
            f"[{_motor()}] el email repetido tendría que dar 409 y dio {r2.status_code}: "
            f"{r2.text[:300]}")
        self.assertEqual(r2.json()["detail"]["code"], "EMAIL_ALREADY_REGISTERED")

    # ── 2) Falta una columna: los pedidos con sesión siguen andando ──────────
    def test_una_columna_que_falta_no_tumba_los_pedidos_con_sesion(self):
        """Se BORRA `users.requires_plan` de verdad y se pide algo con sesión.

        Es la condición de producción (un deploy a mitad de camino), no una
        condición forzada: la consulta de `get_current_user` pide la columna, se
        cae, y el plan B tiene que traer la versión corta. La columna se
        devuelve al final.
        """
        r = self._alta()
        self.assertEqual(r.status_code, 200, f"[{_motor()}] alta: {r.text[:200]}")
        conn = main.get_db()
        try:
            fila = conn.execute("SELECT id, password_changed_at FROM users WHERE email=?",
                                (self.email,)).fetchone()
            uid = fila["id"]
            token = main.create_token(uid, fila["password_changed_at"])
            cab = {"Authorization": f"Bearer {token}"}

            # Con la columna puesta: la línea base. El endpoint es el del estado
            # del plan a propósito: el recién registrado nace DETRAS del muro de
            # pago (`requires_plan=1`), así que cualquier endpoint de datos da 402
            # con columna y sin ella, y el test no mediría nada. Éste tiene que
            # contestar con el muro puesto — si no, no habría forma de pagar.
            antes = self.client.get("/api/billing/status", headers=cab)
            self.assertEqual(antes.status_code, 200,
                             f"[{_motor()}] con la columna ya fallaba: {antes.text[:200]}")

            conn.execute("ALTER TABLE users DROP COLUMN requires_plan")
            conn.commit()
            try:
                despues = self.client.get("/api/billing/status", headers=cab)
            finally:
                conn.rollback()
                conn.execute("ALTER TABLE users ADD COLUMN requires_plan "
                             + ("smallint DEFAULT 0" if getattr(main, "USANDO_PG", False)
                                else "INTEGER DEFAULT 0"))
                conn.commit()

            self.assertEqual(
                despues.status_code, 200,
                f"[{_motor()}] sin la columna `requires_plan` el pedido con sesión "
                f"dio {despues.status_code} — la red del 2026-08-02 no funcionó: "
                f"{despues.text[:300]}")
        finally:
            try:
                conn.execute("DELETE FROM users WHERE email=?", (self.email,))
                conn.commit()
            except Exception:
                try: conn.rollback()
                except Exception: pass
            conn.close()


if __name__ == "__main__":
    unittest.main()
