"""El pozo de conexiones: nunca más de N a la vez, y lo que vuelve vuelve limpio.

Contra el Supabase real (HANDOFF 5.F, 30/10/2026) un envío masivo con hilos llenó
el cupo del session pooler: `EMAXCONNSESSION max clients reached`. Cada
`get_db()` abría una conexión nueva. Ahora salen de un pozo con tope
(`pgshim._Pozo`); estos tests pasan por `main.get_db()`, la misma puerta que la
app, y miden en el servidor cuántas conexiones hubo de verdad.
"""
import os
import sys
import threading
import time
import unittest
import uuid
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
import main  # noqa: E402


@unittest.skipUnless(getattr(main, "USANDO_PG", False), "el pozo es sólo de Postgres")
class PozoDeConexiones(unittest.TestCase):

    def _con_pozo(self, maximo, espera=30):
        import pgshim
        pgshim.cerrar_pozos()
        self.addCleanup(pgshim.cerrar_pozos)
        p = mock.patch.dict(os.environ, {"RENDI_PG_POOL_MAX": str(maximo),
                                         "RENDI_PG_POOL_ESPERA": str(espera)})
        p.start()
        self.addCleanup(p.stop)

    def _conexiones_en_el_servidor(self, marca):
        import pgsesion
        with pgsesion.conectar(main.DATABASE_URL, autocommit=True) as c:
            return c.execute("SELECT count(*) FROM pg_stat_activity WHERE query LIKE %s "
                             "AND pid <> pg_backend_pid()", (f"%{marca}%",)).fetchone()[0]

    def test_diez_pedidos_a_la_vez_con_tope_tres_no_abren_mas_de_tres(self):
        self._con_pozo(3)
        marca = f"pozo_{uuid.uuid4().hex[:8]}"
        errores, pico = [], [0]
        listos = threading.Event()

        def pedido():
            try:
                conn = main.get_db()
                try:
                    conn.execute(f"SELECT pg_sleep(0.3), '{marca}'").fetchone()
                finally:
                    conn.close()
            except Exception as e:  # noqa: BLE001
                errores.append(repr(e))

        def medir():
            while not listos.is_set():
                pico[0] = max(pico[0], self._conexiones_en_el_servidor(marca))
                time.sleep(0.05)
        m = threading.Thread(target=medir)
        m.start()
        hilos = [threading.Thread(target=pedido) for _ in range(10)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(30)
        listos.set()
        m.join()
        self.assertEqual(errores, [])
        self.assertGreater(pico[0], 0, "la medición no vio ninguna conexión: no midió nada")
        self.assertLessEqual(pico[0], 3)

    def test_la_conexion_devuelta_se_vuelve_a_prestar(self):
        self._con_pozo(3)
        a = main.get_db()
        pid_a = a.execute("SELECT pg_backend_pid() AS p").fetchone()["p"]
        a.close()
        b = main.get_db()
        pid_b = b.execute("SELECT pg_backend_pid() AS p").fetchone()["p"]
        b.close()
        self.assertEqual(pid_a, pid_b)

    def test_un_ajuste_de_sesion_no_lo_hereda_el_siguiente(self):
        self._con_pozo(3)
        a = main.get_db()
        normal = a.execute("SHOW lock_timeout").fetchone()[0]
        a.execute("SET lock_timeout = '123ms'")
        a.commit()
        a.close()
        b = main.get_db()
        try:
            self.assertEqual(b.execute("SHOW lock_timeout").fetchone()[0], normal)
        finally:
            b.close()

    def test_lo_que_no_se_confirmo_no_pasa_al_siguiente(self):
        self._con_pozo(1)
        email = f"pozo-{uuid.uuid4().hex[:10]}@rendi.test"
        a = main.get_db()
        a.execute("INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)", (email,))
        self.assertTrue(a.in_transaction)
        a.close()                     # sin commit: se descarta, como antes
        b = main.get_db()
        try:
            self.assertFalse(b.in_transaction)
            self.assertIsNone(b.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone())
        finally:
            b.close()

    def test_pozo_agotado_espera_y_despues_avisa(self):
        import pgshim
        self._con_pozo(1, espera=0.5)
        a = main.get_db()
        try:
            t0 = time.monotonic()
            with self.assertRaises(pgshim.PozoAgotado):
                main.get_db()
            self.assertGreaterEqual(time.monotonic() - t0, 0.4)
        finally:
            a.close()
        main.get_db().close()         # devuelta la primera, se puede pedir de nuevo


if __name__ == "__main__":
    unittest.main()
