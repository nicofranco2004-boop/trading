"""El modo mantenimiento cierra al público y deja pasar al operador.

QUÉ PROTEGE. Hoy "chequear" y "abrir" son el mismo momento: apenas se deploya con
`DATABASE_URL`, los 1.084 ya están adentro — y los chequeos del pasaje incluyen un
import de punta a punta, o sea escrituras. **El punto de no retorno se cruza mientras
todavía estás decidiendo si la copia sirve.**

🔴 **EL DEFAULT CERRADO ES LA MITAD DEL VALOR, y por eso tiene su propio bloque de
tests.** Un mantenimiento que hay que acordarse de prender es una red opt-in, y una
red opt-in no es una red. Las dos fallas no cuestan lo mismo:

    trabado en mantenimiento  → nadie entra, VISIBLE, se sale sacando una variable
    abierto de más            → usuarios operando mientras verificás, SILENCIOSO

Se prueba en las **dos direcciones**, que es lo que pidió el dueño: que frene sin la
marca, y que el bypass funcione con la marca puesta. Un test que sólo probara que
frena pasaría igual con un middleware que frena SIEMPRE — y ése sería inservible.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import mantenimiento as mt  # noqa: E402

_VARS = ("RENDI_MANTENIMIENTO", "RENDI_MANTENIMIENTO_TOKEN",
         "RENDI_PASAJE_COMPLETO", "DATABASE_URL")


class _ConEntorno(unittest.TestCase):
    """Cada test arranca con las cuatro variables limpias y las restaura al salir.
    Sin esto un test le filtra el entorno al siguiente y el resultado depende del
    orden — que es la forma en que un test deja de medir lo que dice medir."""

    def setUp(self):
        self._previo = {k: os.environ.get(k) for k in _VARS}
        for k in _VARS:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._previo.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ElDefaultEsCerradoTest(_ConEntorno):
    """🔴 El corazón del asunto: qué pasa cuando NADIE dijo nada."""

    def test_con_DATABASE_URL_y_sin_la_marca_del_pasaje_esta_CERRADO(self):
        """El caso del día del pasaje: se prende Postgres y se reinicia. Nadie
        se acordó de prender el mantenimiento — y aún así está cerrado."""
        os.environ["DATABASE_URL"] = "postgresql://x/y"
        self.assertTrue(mt.en_mantenimiento())
        self.assertFalse(mt.deja_pasar("/api/positions", None))

    def test_con_la_marca_del_pasaje_puesta_esta_ABIERTO(self):
        """La contracara. Sin esto, el test de arriba pasaría con un middleware
        que cierra siempre — que sería inservible."""
        os.environ["DATABASE_URL"] = "postgresql://x/y"
        os.environ["RENDI_PASAJE_COMPLETO"] = "1"
        self.assertFalse(mt.en_mantenimiento())
        self.assertTrue(mt.deja_pasar("/api/positions", None))

    def test_SIN_DATABASE_URL_la_app_de_hoy_sigue_abierta(self):
        """Lo más importante para no romper producción: mergear esto NO cierra la
        app que corre hoy en SQLite."""
        self.assertFalse(mt.en_mantenimiento())
        self.assertTrue(mt.deja_pasar("/api/positions", None))

    def test_el_interruptor_explicito_le_gana_al_default(self):
        os.environ["RENDI_MANTENIMIENTO"] = "1"
        self.assertTrue(mt.en_mantenimiento())          # sin DATABASE_URL siquiera
        os.environ["RENDI_MANTENIMIENTO"] = "0"
        os.environ["DATABASE_URL"] = "postgresql://x/y"
        self.assertFalse(mt.en_mantenimiento())         # abre a pesar del default

    def test_una_variable_VACIA_no_cuenta_como_puesta(self):
        """Railway deja variables en blanco con facilidad. Una marca vacía que
        contara como 'el pasaje terminó' abriría la app sin que nadie lo decidiera."""
        os.environ["DATABASE_URL"] = "postgresql://x/y"
        os.environ["RENDI_PASAJE_COMPLETO"] = "   "
        self.assertTrue(mt.en_mantenimiento())


class ElBypassTest(_ConEntorno):

    def setUp(self):
        super().setUp()
        os.environ["RENDI_MANTENIMIENTO"] = "1"

    def test_con_el_token_correcto_PASA(self):
        os.environ["RENDI_MANTENIMIENTO_TOKEN"] = "secreto-largo-123"
        self.assertTrue(mt.deja_pasar("/api/positions", "secreto-largo-123"))

    def test_con_el_token_equivocado_NO_pasa(self):
        os.environ["RENDI_MANTENIMIENTO_TOKEN"] = "secreto-largo-123"
        self.assertFalse(mt.deja_pasar("/api/positions", "otro"))

    def test_SIN_token_configurado_NO_hay_bypass_posible(self):
        """Preferimos quedarnos afuera —visible, se arregla poniendo la variable—
        a que un token vacío coincida con un header vacío y abra la puerta."""
        self.assertFalse(mt.deja_pasar("/api/positions", ""))
        self.assertFalse(mt.deja_pasar("/api/positions", None))
        self.assertFalse(mt.bypass_valido(""))

    def test_health_pasa_SIEMPRE(self):
        """Si /api/health no contesta, Railway mata el contenedor y no llegás ni a
        hacer los chequeos que el mantenimiento existe para permitir."""
        self.assertTrue(mt.deja_pasar("/api/health", None))

    def test_pero_health_es_la_UNICA_excepcion(self):
        """Cada excepción es una puerta. Que la lista sea corta es el punto."""
        self.assertEqual(mt.RUTAS_LIBRES, ("/api/health",))
        for ruta in ("/api/positions", "/api/import/confirm", "/", "/api/health/x"):
            self.assertFalse(mt.deja_pasar(ruta, None), ruta)


class ElMiddlewareDeVerdadTest(_ConEntorno):
    """Que la lógica esté bien no sirve si no está CONECTADA al request.

    Levanta una app FastAPI de verdad y le pega. Sin esto, `deja_pasar` podría
    estar perfecta y el middleware no estar instalado — que es exactamente la forma
    en que una red queda decorativa.
    """

    def _cliente(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()

        @app.get("/api/positions")
        def _pos():
            return {"ok": True}

        @app.get("/api/health")
        def _health():
            return {"ok": True}

        mt.instalar(app)
        return TestClient(app)

    def test_cerrado_devuelve_503_con_mensaje_humano(self):
        os.environ["RENDI_MANTENIMIENTO"] = "1"
        r = self._cliente().get("/api/positions")
        self.assertEqual(r.status_code, 503,
                         "503 y no 500: el frontend ya sabe mostrar el 503 lindo")
        self.assertTrue(r.json()["mantenimiento"])
        self.assertIn("mudando", r.json()["error"])

    def test_cerrado_pero_health_contesta_200(self):
        os.environ["RENDI_MANTENIMIENTO"] = "1"
        self.assertEqual(self._cliente().get("/api/health").status_code, 200)

    def test_con_el_header_de_bypass_el_operador_ENTRA(self):
        os.environ["RENDI_MANTENIMIENTO"] = "1"
        os.environ["RENDI_MANTENIMIENTO_TOKEN"] = "abr3-sesamo"
        r = self._cliente().get("/api/positions",
                                headers={mt.CABECERA_BYPASS: "abr3-sesamo"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_abierto_no_molesta_a_nadie(self):
        """La contracara del primero: si esto diera 503, el middleware estaría
        cerrando siempre y los otros tests no lo distinguirían."""
        r = self._cliente().get("/api/positions")
        self.assertEqual(r.status_code, 200)


class NoTocaLaBaseTest(unittest.TestCase):
    """Un mantenimiento que lee un flag de la base se cae junto con la base de la
    que te protege — y el día que lo necesitás es justo el día en que la base
    puede estar rara. Se fija leyendo el módulo: nada de sqlite3, psycopg ni
    get_db."""

    def test_el_modulo_no_habla_con_ninguna_base(self):
        import ast
        ruta = os.path.join(os.path.dirname(HERE), "mantenimiento.py")
        arbol = ast.parse(open(ruta, encoding="utf-8").read())
        importados = set()
        for n in ast.walk(arbol):
            if isinstance(n, ast.Import):
                importados |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                importados.add(n.module.split(".")[0])
        for prohibido in ("sqlite3", "psycopg", "pgshim", "pgsesion", "main"):
            self.assertNotIn(prohibido, importados,
                             f"{prohibido} acopla el mantenimiento a la base")
        fuente = open(ruta, encoding="utf-8").read()
        self.assertNotIn("get_db", fuente)


if __name__ == "__main__":
    unittest.main()
