"""`/api/health` dice con qué motor corre la app (hallazgo A1 de la auditoría final).

QUÉ PROTEGE. El paso 8 del día del pasaje empieza por «¿la app está en Postgres?», y
hasta ahora la respuesta era una deducción (un renglón del registro, o que todo diera
503). `/api/health` no toca la base y no pide llave: es lo único que contesta con el
mantenimiento prendido, así que es el lugar donde preguntarlo.

LA PRUEBA NO PUEDE USAR LA MISMA FUENTE QUE EL CÓDIGO. `health_check` lee `USANDO_PG`; si
el test también, un `USANDO_PG` equivocado daría verde. Acá el motor esperado sale de la
`DATABASE_URL` que tiene el proceso —lo que de verdad decide el motor—, y se confirma
además mirando la conexión que abre la app.

Corre en los DOS motores: `python3 -m pytest tests/test_health_dice_el_motor.py` (SQLite)
y con `DATABASE_URL=… python3 -m pytest tests/test_health_dice_el_motor.py` (Postgres).
"""
import os
import unittest

from fastapi.testclient import TestClient

import main


class HealthDiceElMotor(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(main.app)
        self.esperado = "postgres" if os.environ.get("DATABASE_URL", "").strip() else "sqlite"

    def test_dice_el_motor_de_este_proceso(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["motor"], self.esperado)

    def test_es_el_motor_de_la_conexion_que_abre_la_app(self):
        """No se fía de la bandera: le pregunta a la base."""
        conn = main.get_db()
        try:
            if self.esperado == "postgres":
                self.assertIn("PostgreSQL", conn.execute("SELECT version()").fetchone()[0])
            else:
                self.assertTrue(conn.execute("SELECT sqlite_version()").fetchone()[0])
        finally:
            conn.close()

    def test_el_resto_de_la_respuesta_sigue_igual(self):
        j = self.client.get("/api/health").json()
        self.assertEqual({"ok", "timestamp", "service", "motor", "commit"}, set(j))
        self.assertEqual(j["service"], "rendi-api")

    def test_contesta_aun_con_la_app_cerrada_por_mantenimiento(self):
        """Es lo que se mira ANTES de abrir: sin llave, sólo /api/health pasa."""
        previo = {k: os.environ.get(k) for k in ("RENDI_MANTENIMIENTO", "RENDI_MANTENIMIENTO_TOKEN")}
        os.environ["RENDI_MANTENIMIENTO"] = "1"
        os.environ.pop("RENDI_MANTENIMIENTO_TOKEN", None)
        try:
            r = self.client.get("/api/health")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["motor"], self.esperado)
            self.assertEqual(self.client.get("/api/positions").status_code, 503)
        finally:
            for k, v in previo.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
