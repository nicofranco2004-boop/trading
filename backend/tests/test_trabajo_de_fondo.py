"""La suite espera a las reconstrucciones de fondo entre una prueba y la siguiente
(tests/_trabajo_de_fondo.py). Contra Supabase, sin esa espera, el hilo de la
prueba anterior pisaba la limpieza de la siguiente: 3 rojos en la corrida de
Railway del 02/11/2026 que en la Mac no aparecían.
"""
import os
import threading
import time
import unittest

from tests import _trabajo_de_fondo

CONFTEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "conftest.py")


class LaEsperaEsperaDeVerdad(unittest.TestCase):

    def test_vuelve_cuando_el_hilo_termino(self):
        h = threading.Thread(target=time.sleep, args=(0.5,), name="mtm-backfill-prueba")
        h.start()
        _trabajo_de_fondo.esperar(10)
        self.assertFalse(h.is_alive())

    def test_espera_tambien_al_que_lanza_otro(self):
        """Una reconstrucción que termina puede haber lanzado otra."""
        hijos = []

        def padre():
            time.sleep(0.2)
            h = threading.Thread(target=time.sleep, args=(0.5,), name="mtm-backfill-hijo")
            hijos.append(h)
            h.start()

        threading.Thread(target=padre, name="mtm-backfill-padre").start()
        _trabajo_de_fondo.esperar(10)
        self.assertTrue(hijos and not hijos[0].is_alive())

    def test_un_hilo_colgado_se_ve_con_su_nombre(self):
        corte = threading.Event()
        h = threading.Thread(target=corte.wait, name="mtm-backfill-colgado")
        h.start()
        try:
            with self.assertRaises(RuntimeError) as e:
                _trabajo_de_fondo.esperar(0.3)
            self.assertIn("mtm-backfill-colgado", str(e.exception))
        finally:
            corte.set()
            h.join()

    def test_no_espera_a_hilos_que_no_son_reconstrucciones(self):
        corte = threading.Event()
        h = threading.Thread(target=corte.wait, name="otra-cosa")
        h.start()
        try:
            t = time.monotonic()
            _trabajo_de_fondo.esperar(5)
            self.assertLess(time.monotonic() - t, 1)
        finally:
            corte.set()
            h.join()


class LaSuiteLaUsa(unittest.TestCase):
    """Que el helper exista no alcanza: el conftest lo tiene que llamar antes de
    cada prueba Y antes de rehacer el esquema de cada archivo."""

    def test_el_conftest_espera_por_prueba_y_por_archivo(self):
        src = open(CONFTEST, encoding="utf-8").read()
        self.assertIn("def _sin_reconstrucciones_de_la_prueba_anterior", src)
        modulo = src.split("def _db_por_modulo", 1)[1].split("_aislar_postgres(", 1)[0]
        self.assertIn("_trabajo_de_fondo.esperar()", modulo,
                      "el esquema se rehace sin esperar a las reconstrucciones del "
                      "archivo anterior")


if __name__ == "__main__":
    unittest.main()
