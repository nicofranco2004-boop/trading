"""El orden de los tres relojes se cumple SEA CUAL SEA la configuración.

QUÉ PROTEGE. El aislamiento de la suite se apoya en tres relojes, y **el orden
entre ellos ES el arreglo**:

    idle_in_transaction  <  lock_timeout  <  --timeout de pytest

Si `lock_timeout` fuera el más chico, el test que espera se rendiría ANTES de que
Postgres mate a la conexión que quedó con la transacción abierta: seguiría fallando
pudiendo pasar. Y si `--timeout` de pytest fuera menor que `lock_timeout`, en vez de
un error que dice "me bloqueé" quedaría un `Failed: Timeout` que no dice nada.

POR QUÉ AHORA Y NO ANTES. Los valores eran 3s/7s/10s y el 3 quedó corto. Medido, la
misma suite en el mismo commit y sin nada corriendo al lado:

    #1  46 fallas · 68s     #2  49 fallas · 133s     #3  46 fallas · 71s
                                ↑ las 3 extra: IdleInTransactionSessionTimeout

Cuando la máquina se pone lenta, un test LEGÍTIMO pasa más de 3s con la transacción
abierta y Postgres lo mata. El número de la suite volvía a depender de la carga —
el mismo problema de siempre con otra cara. Subieron a 6/12/20 y se pueden ajustar
por entorno.

🔴 **EL RIESGO DEL ARREGLO ES SUBIR UNO SOLO.** Si el idle cruza al lock, la
propiedad se rompe **y la suite igual arranca**: nadie se entera hasta que los
tests bloqueados empiezan a fallar sin motivo visible. Por eso el orden dejó de ser
un comentario de 12 líneas y ahora lo valida `pytest_configure`, que **corta el
arranque**. Este archivo prueba las dos mitades por separado.
"""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from conftest import (revisar_orden_de_relojes, _segundos,   # noqa: E402
                      _IDLE_TX_S, _LOCK_S, _IDLE_TX_S_DEFAULT, _LOCK_S_DEFAULT,
                      _PYTEST_TIMEOUT_SUGERIDO)


class ElOrdenSeCumpleTest(unittest.TestCase):
    """La propiedad, en las dos mitades. Van separadas a propósito: son DOS
    invariantes distintas y un solo test las taparía entre sí."""

    def test_los_valores_QUE_ESTAN_CORRIENDO_cumplen_el_orden(self):
        """No los defaults: los de esta corrida, que pueden venir del entorno."""
        self.assertIsNone(revisar_orden_de_relojes(_IDLE_TX_S, _LOCK_S,
                                                   _PYTEST_TIMEOUT_SUGERIDO))

    def test_los_DEFAULTS_cumplen_el_orden(self):
        """Por si alguien corre con el entorno limpio, que es el caso normal."""
        self.assertIsNone(revisar_orden_de_relojes(
            _IDLE_TX_S_DEFAULT, _LOCK_S_DEFAULT, _PYTEST_TIMEOUT_SUGERIDO))

    # ── mitad 1: idle < lock ─────────────────────────────────────────────────
    def test_el_idle_POR_ENCIMA_del_lock_es_rechazado(self):
        """El error concreto que este cambio viene a evitar: subir sólo el idle."""
        motivo = revisar_orden_de_relojes(12, 7, 20)
        self.assertIsNotNone(motivo, "un idle mayor que el lock tiene que fallar")
        self.assertIn("idle_in_transaction", motivo)

    def test_el_idle_IGUAL_al_lock_tambien(self):
        """Iguales no alcanza: con la carrera pareja no hay garantía de quién
        gana, y la propiedad depende de que gane SIEMPRE el idle."""
        self.assertIsNotNone(revisar_orden_de_relojes(7, 7, 20))

    # ── mitad 2: lock < pytest ───────────────────────────────────────────────
    def test_el_lock_POR_ENCIMA_del_timeout_de_pytest_es_rechazado(self):
        motivo = revisar_orden_de_relojes(3, 20, 10)
        self.assertIsNotNone(motivo, "un lock mayor que el --timeout tiene que fallar")
        self.assertIn("lock_timeout", motivo)

    def test_sin_timeout_de_pytest_solo_se_exige_la_primera_mitad(self):
        """`--timeout` puede no estar. Ahí el tercer reloj no existe: se exige lo
        que se puede exigir, y NO se hace de cuenta que está todo bien."""
        self.assertIsNone(revisar_orden_de_relojes(6, 12, None))
        self.assertIsNotNone(revisar_orden_de_relojes(12, 6, None))

    # ── subir los tres juntos, que es el uso legítimo ────────────────────────
    def test_subir_los_TRES_manteniendo_el_orden_esta_bien(self):
        for idle, lock, tmo in [(3, 7, 10), (6, 12, 20), (30, 60, 120)]:
            self.assertIsNone(revisar_orden_de_relojes(idle, lock, tmo),
                              f"{idle}/{lock}/{tmo} respeta el orden")


class LosRelojesSeConfiguranTest(unittest.TestCase):

    def test_un_valor_invalido_LEVANTA_en_vez_de_caer_al_default(self):
        """Caer al default en silencio es lo peor de los dos mundos: el que quiso
        apretar los relojes creería que los apretó y estaría midiendo con otros."""
        os.environ["RENDI_TEST_RELOJ_PRUEBA"] = "muchos"
        try:
            with self.assertRaises(RuntimeError):
                _segundos("RENDI_TEST_RELOJ_PRUEBA", 6)
        finally:
            del os.environ["RENDI_TEST_RELOJ_PRUEBA"]

    def test_cero_o_negativo_LEVANTA(self):
        for malo in ("0", "-3"):
            os.environ["RENDI_TEST_RELOJ_PRUEBA"] = malo
            try:
                with self.assertRaises(RuntimeError):
                    _segundos("RENDI_TEST_RELOJ_PRUEBA", 6)
            finally:
                del os.environ["RENDI_TEST_RELOJ_PRUEBA"]

    def test_acepta_con_y_sin_la_s(self):
        for crudo, esperado in (("9", 9), ("9s", 9), (" 9s ", 9)):
            os.environ["RENDI_TEST_RELOJ_PRUEBA"] = crudo
            try:
                self.assertEqual(_segundos("RENDI_TEST_RELOJ_PRUEBA", 6), esperado)
            finally:
                del os.environ["RENDI_TEST_RELOJ_PRUEBA"]

    def test_vacio_o_ausente_usa_el_default(self):
        os.environ.pop("RENDI_TEST_RELOJ_PRUEBA", None)
        self.assertEqual(_segundos("RENDI_TEST_RELOJ_PRUEBA", 6), 6)
        os.environ["RENDI_TEST_RELOJ_PRUEBA"] = ""
        try:
            self.assertEqual(_segundos("RENDI_TEST_RELOJ_PRUEBA", 6), 6)
        finally:
            del os.environ["RENDI_TEST_RELOJ_PRUEBA"]


class LaSuiteNoArrancaMalConfiguradaTest(unittest.TestCase):
    """La validación de arriba sirve sólo si de verdad CORTA el arranque.

    Se levanta un pytest de verdad, en un subproceso, con el idle por encima del
    lock. Tiene que negarse a correr. Sin este test, `revisar_orden_de_relojes`
    podría estar perfecta y no estar conectada a nada.
    """

    def test_pytest_se_niega_a_correr_con_el_idle_por_encima_del_lock(self):
        env = dict(os.environ,
                   RENDI_TEST_IDLE_TX_S="20", RENDI_TEST_LOCK_S="7")
        env.pop("DATABASE_URL", None)
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_relojes_del_conftest.py",
             "-q", "--co", "-p", "no:warnings"],
            cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180)
        salida = r.stdout + r.stderr
        self.assertNotEqual(r.returncode, 0,
                            f"pytest arrancó igual con los relojes al revés:\n{salida[-2000:]}")
        self.assertIn("relojes mal configurados", salida)

    def test_y_CON_el_orden_bien_arranca_normal(self):
        """La contracara: sin esto, un `pytest_configure` que rompiera siempre
        también pasaría el test de arriba."""
        env = dict(os.environ, RENDI_TEST_IDLE_TX_S="6", RENDI_TEST_LOCK_S="12")
        env.pop("DATABASE_URL", None)
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_relojes_del_conftest.py",
             "-q", "--co", "-p", "no:warnings"],
            cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-2000:])


if __name__ == "__main__":
    unittest.main()
