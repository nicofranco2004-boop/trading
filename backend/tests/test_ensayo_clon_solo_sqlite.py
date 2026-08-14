"""El ensayo por clon es sólo-SQLite, y TIENE QUE AVISARLO.

Tres herramientas de admin simulan clonando la base entera con
`sqlite3.Connection.backup()`. En Postgres esa fotocopia no existe. La decisión
tomada (sesión 6) es NO migrarlas ahora: son de admin, no están en el camino de
ningún usuario, y son el único ítem que le quedaba a la migración.

Lo que este test protege es la diferencia entre las dos formas de "no andar":

    ANTES  →  500  "backfill falló: AttributeError: 'Connection' object has
                    no attribute 'backup'"
    AHORA  →  501  "…todavía no funciona con Postgres/Supabase… corré el backend
                    sin la variable DATABASE_URL."

Verificado que FALLA con el comportamiento viejo: sacándole el
`exigir_clon_soportado` a `_clone_db`, el endpoint contesta 500 y el assert de
`status_code == 501` se cae.
"""
import sqlite3
import unittest
import unittest.mock

import dberrors
import main


class ExigirClonSoportadoTest(unittest.TestCase):
    """El helper, aislado. Corre igual en los dos motores."""

    def test_una_conexion_sqlite_pasa(self):
        conn = sqlite3.connect(":memory:")
        try:
            dberrors.exigir_clon_soportado(conn, "lo que sea")   # no levanta
        finally:
            conn.close()

    def test_cualquier_otra_cosa_corta_con_mensaje_accionable(self):
        class ConexionQueNoEsSqlite:
            pass

        with self.assertRaises(dberrors.EnsayoPorClonNoDisponible) as cm:
            dberrors.exigir_clon_soportado(ConexionQueNoEsSqlite(), "Recomputar posiciones")
        msg = str(cm.exception)
        # El mensaje tiene que decir QUÉ herramienta, POR QUÉ y QUÉ hacer. Si no,
        # es tan inútil como el AttributeError que reemplaza.
        self.assertIn("Recomputar posiciones", msg)
        self.assertIn("DATABASE_URL", msg)
        self.assertIn("backup", msg)

    def test_pregunta_por_la_capacidad_y_no_por_la_variable_de_entorno(self):
        """Una conexión sqlite pasa AUNQUE DATABASE_URL esté puesta.

        Es la diferencia entre chequear la precondición real (¿esta conexión sabe
        hacer backup?) y chequear una variable de entorno que puede no describir a
        la conexión que efectivamente llegó.
        """
        conn = sqlite3.connect(":memory:")
        try:
            with unittest.mock.patch.object(main, "USANDO_PG", True):
                dberrors.exigir_clon_soportado(conn, "lo que sea")   # no levanta
        finally:
            conn.close()


@unittest.skipUnless(getattr(main, "USANDO_PG", False),
                     "el aviso sólo se dispara en modo Postgres")
class ElBotonAvisaClaroEnPostgresTest(unittest.TestCase):
    """De punta a punta: el botón "Simular" contra Postgres."""

    def setUp(self):
        from fastapi.testclient import TestClient
        conn = main.get_db()
        try:
            # Email único POR TEST: `users.email` es UNIQUE y los dos tests de
            # esta clase corren su setUp en el mismo esquema.
            email = f"admin-clon-{self._testMethodName}@rendi.test"
            self.admin = conn.execute(
                "INSERT INTO users (email, password_hash, approved, is_admin) "
                "VALUES (?,?,1,1)", (email, "x")).lastrowid
            # Hace falta UNA posición real: `safe_backfill` corta antes de clonar
            # si ningún usuario tiene tenencias (`with_pos` vacío → return). Sin
            # esto el endpoint devuelve 200 sin llegar nunca al clon, y el test
            # pasaría por el motivo equivocado.
            conn.execute(
                "INSERT INTO positions (user_id, broker, asset, is_cash, quantity, "
                "invested, buy_price, entry_date, currency) "
                "VALUES (?,?,?,0,?,?,?,?,?)",
                (self.admin, "Cocos", "AAPL", 10.0, 1500.0, 150.0, "2024-03-15", "ARS"))
            conn.commit()
        finally:
            conn.close()
        self.client = TestClient(main.app)

    def _hdr(self):
        return {"Authorization": f"Bearer {main.create_token(self.admin)}"}

    def test_simular_backfill_contesta_501_y_no_500(self):
        r = self.client.post("/api/admin/backfill-recompute?apply=false",
                             headers=self._hdr())
        # 501 = "este motor no tiene esa capacidad", no 500 = "se rompió algo".
        self.assertEqual(r.status_code, 501, r.text)
        detail = r.json()["detail"]
        self.assertIn("DATABASE_URL", detail)
        # Y NO el error críptico que salía antes.
        self.assertNotIn("AttributeError", detail)

    def test_reparar_snapshots_tambien_avisa(self):
        r = self.client.post("/api/admin/repair-snapshots-all?apply=false",
                             headers=self._hdr())
        self.assertEqual(r.status_code, 501, r.text)
        self.assertIn("DATABASE_URL", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
