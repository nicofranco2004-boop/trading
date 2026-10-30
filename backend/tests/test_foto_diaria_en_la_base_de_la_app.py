"""La foto diaria se guarda en la MISMA base que lee la app.

`run_daily_snapshot` abría `sqlite3.connect(db_path)` por su cuenta. En SQLite
daba igual (es el mismo archivo), pero con DATABASE_URL puesta la foto de cada
noche se leía y se guardaba en el archivo SQLite congelado, y la app —que lee de
Postgres— se quedaba sin la foto de ayer: la variación diaria, los resúmenes, el
TWR y los informes del asesor dejaban de cerrar sin un error a la vista
(MIGRACION_POSTGRES.md, c-2). Estaba marcado como deuda en
`test_escritores_solo_sqlite.py`; acá se prueba por la puerta real: el mismo
`_run_daily_snapshot_job` que dispara el reloj de las 02:59, el cron externo y,
con la misma llamada, el botón del admin.
"""
import os
import sys
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
import main  # noqa: E402
from fechas import hoy_art  # noqa: E402


class LaFotoDeLaNocheLaVeLaApp(unittest.TestCase):
    BROKER = "FotoNoche"

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"foto-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, self.BROKER, "USD"))
        conn.commit()
        conn.close()
        main.cash_flow(main.CashFlowIn(broker_name=self.BROKER, direction="deposit",
                                       amount=1000.0, date="2025-11-05"), uid=self.uid)

    def tearDown(self):
        conn = main.get_db()
        for t in ("flujos_a_mano", "monthly_entries", "positions", "snapshots", "brokers"):
            conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
        conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
        conn.commit()
        conn.close()

    def test_el_job_de_la_noche_guarda_la_foto_donde_la_app_la_lee(self):
        with mock.patch.object(main, "_get_blue_for_scheduler", lambda: 1500.0), \
                mock.patch.object(main, "_get_mep_for_scheduler", lambda: 1450.0), \
                mock.patch.object(main, "_run_velas_diarias_job", lambda: None):
            main._run_daily_snapshot_job()
        conn = main.get_db()
        foto = conn.execute("SELECT total_value FROM snapshots WHERE user_id=? AND date=?",
                            (self.uid, hoy_art())).fetchone()
        conn.close()
        self.assertIsNotNone(foto, "la foto de la noche no está en la base que lee la app")
        self.assertAlmostEqual(float(foto["total_value"]), 1000.0, places=2)


if __name__ == "__main__":
    unittest.main()
