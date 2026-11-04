"""El arranque no congela a la copia vieja de la app.

En Postgres, al publicar, la copia nueva arranca mientras la vieja atiende
(docs.railway.com/reference/deployments, «Deployment Teardown»). El arranque
corría los ~800 cambios de `schema_pg.sql` en CADA publicación, y cada
`ALTER TABLE … ADD COLUMN IF NOT EXISTS` traba su tabla entera aunque la
columna exista: con un pedido de la copia vieja abierto en esa tabla, el ALTER
espera, y detrás de él quedan en fila todos los pedidos nuevos de la tabla
(medido el 30/10/2026; en producción `lock_timeout` = 0, o sea para siempre).

Lo que se fija acá, por `main.init_db()` / `main._init_db_postgres()` de verdad:
  · con la huella al día, el segundo arranque corre 0 cambios de estructura;
  · un pedido viejo abierto en `positions` no frena a ese arranque;
  · si la huella no coincide, corre todo una vez y la guarda;
  · si el catálogo no tiene algo (alguien borró una columna a mano), corre
    aunque la huella coincida;
  · cuando corre y la tabla está ocupada: cada intento la traba un rato corto,
    un lector que llega mientras tanto pasa, y al final se aplica;
  · si no se pudo aplicar, NO queda huella nueva (el próximo vuelve a correr);
  · `/api/health` contesta 503 hasta que terminó el arranque, y es lo que
    `railway.toml` le da a Railway como chequeo de salud.
"""
import logging
import os
import re
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test-secret")

import main  # noqa: E402
import pgsesion  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PG = bool(getattr(main, "USANDO_PG", False))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SOLO_PG = unittest.skipUnless(PG, "el esquema de Postgres; SQLite tiene volumen y no se superpone")


def _sin_huella():
    c = pgsesion.conectar(main.DATABASE_URL, autocommit=True)
    try:
        c.execute(f"DELETE FROM {pgsesion.TABLA_DEL_ARRANQUE} WHERE clave = 'schema_pg'")
    finally:
        c.close()


def _huella_guardada():
    c = pgsesion.conectar(main.DATABASE_URL, autocommit=True)
    try:
        r = c.execute(f"SELECT huella FROM {pgsesion.TABLA_DEL_ARRANQUE} "
                      "WHERE clave = 'schema_pg'").fetchone()
        return r[0] if r else None
    finally:
        c.close()


def _primera_tabla_que_altera():
    """La tabla del primer ALTER del archivo: la que el arranque va a querer
    trabar enseguida."""
    for s in main._sentencias_esquema_pg():
        m = re.match(r"ALTER TABLE (\w+)", s)
        if m:
            return m.group(1)


class _PedidoViejoAbierto:
    """Un pedido de la copia vieja, a medio camino: una escritura sin confirmar
    en `tabla`. La retiene (no en exclusiva) hasta `soltar()`."""

    def __init__(self, tabla="positions"):
        self.c = pgsesion.conectar(main.DATABASE_URL)
        self.c.execute(f"LOCK TABLE {tabla} IN ROW EXCLUSIVE MODE")

    def soltar(self):
        try:
            self.c.rollback()
        finally:
            self.c.close()


@SOLO_PG
class ConLaHuellaAlDiaNoSeTocaLaEstructura(unittest.TestCase):

    def test_el_segundo_arranque_corre_cero_cambios(self):
        _sin_huella()
        primero = main._init_db_postgres()
        segundo = main._init_db_postgres()
        print(f"\n>>> primero={primero} segundo={segundo}")
        self.assertGreater(primero["corridas"], 700)
        self.assertEqual(primero["motivo"], "la base no tiene huella")
        self.assertEqual(segundo["corridas"], 0)
        self.assertTrue(segundo["salteado"])
        self.assertEqual(_huella_guardada(),
                         main._huella_esquema_pg(main._sentencias_esquema_pg()))

    def test_init_db_entero_lo_dice_en_el_registro(self):
        main._init_db_postgres()                     # deja la huella al día
        with self.assertLogs(main.log, level=logging.WARNING) as reg:
            main.init_db()
        self.assertTrue(any("0 cambios de estructura" in m for m in reg.output), reg.output)

    def test_un_pedido_viejo_abierto_no_frena_al_arranque(self):
        main._init_db_postgres()
        viejo = _PedidoViejoAbierto()
        try:
            t = time.monotonic()
            main.init_db()                           # el lock_timeout de las pruebas es 12 s
            tardo = time.monotonic() - t
        finally:
            viejo.soltar()
        print(f"\n>>> arranque con un pedido viejo abierto en positions: {tardo:.2f} s")
        self.assertLess(tardo, 5.0, "el arranque esperó al pedido de la copia vieja")


@SOLO_PG
class LaHuellaNoEsUnActoDeFe(unittest.TestCase):

    def test_si_falta_una_columna_se_vuelve_a_aplicar(self):
        main._init_db_postgres()
        c = pgsesion.conectar(main.DATABASE_URL, autocommit=True)
        try:
            c.execute("ALTER TABLE alerts DROP COLUMN last_fired_price")
        finally:
            c.close()
        r = main._init_db_postgres()
        print(f"\n>>> con una columna borrada a mano: {r}")
        self.assertGreater(r["corridas"], 0)
        self.assertIn("columna alerts.last_fired_price", r["motivo"])
        c = pgsesion.conectar(main.DATABASE_URL, autocommit=True)
        try:
            self.assertEqual(main._lo_que_falta_del_esquema(c, main._sentencias_esquema_pg()), [])
        finally:
            c.close()

    def test_el_control_ve_lo_que_el_archivo_crea(self):
        """Contra lo que se sabe que el archivo tiene: si el control dejara de
        reconocer las sentencias, «no falta nada» sería por no mirar."""
        s = main._sentencias_esquema_pg()
        c = pgsesion.conectar(main.DATABASE_URL, autocommit=True)
        try:
            vacio = main._lo_que_falta_del_esquema(c, s + [
                "CREATE TABLE IF NOT EXISTS no_existe_t (a int)",
                "ALTER TABLE alerts ADD COLUMN IF NOT EXISTS no_existe_c text",
                "CREATE INDEX IF NOT EXISTS no_existe_i ON alerts(id)",
                "ALTER TABLE alerts ADD CONSTRAINT no_existe_fk FOREIGN KEY (user_id) REFERENCES users(id)",
                "CREATE OR REPLACE VIEW no_existe_v AS SELECT 1"])
        finally:
            c.close()
        self.assertEqual(vacio, ["tabla no_existe_t", "columna alerts.no_existe_c",
                                 "columna no_existe_t.a", "índice no_existe_i",
                                 "clave foránea no_existe_fk", "vista no_existe_v"])


@SOLO_PG
class CuandoSiCorreNoDejaLaTablaEnFila(unittest.TestCase):

    def setUp(self):
        for nombre, valor in (("_DDL_ESPERA_MAX", "400ms"), ("_DDL_PAUSA_S", 0.2)):
            p = mock.patch.object(main, nombre, valor)
            p.start()
            self.addCleanup(p.stop)

    def test_reintenta_un_lector_pasa_y_al_final_se_aplica(self):
        _sin_huella()
        tabla = _primera_tabla_que_altera()
        viejo = _PedidoViejoAbierto(tabla)
        lector = {}

        def leer():
            c = main.get_db()
            t = time.monotonic()
            try:
                c.execute(f"SELECT count(*) FROM {tabla}").fetchone()
                lector["ok"] = time.monotonic() - t
            except Exception as ex:
                lector["error"] = repr(ex)
            finally:
                c.close()

        def la_vieja_termina():
            time.sleep(0.5)
            threading.Thread(target=leer, daemon=True).start()   # un pedido nuevo, mientras
            time.sleep(1.5)
            viejo.soltar()

        threading.Thread(target=la_vieja_termina, daemon=True).start()
        r = main._init_db_postgres()
        time.sleep(0.2)
        print(f"\n>>> esquema con la tabla ocupada: {r}; lector: {lector}")
        self.assertGreater(r["reintentos"], 0, "no esperó nunca: la prueba no midió nada")
        self.assertIn("ok", lector, lector)
        self.assertLess(lector["ok"], 1.5, "el lector quedó en fila detrás del cambio de estructura")
        self.assertIsNotNone(_huella_guardada())

    def test_si_no_se_pudo_aplicar_no_queda_huella(self):
        _sin_huella()
        viejo = _PedidoViejoAbierto(_primera_tabla_que_altera())
        try:
            with mock.patch.object(main, "_DDL_REINTENTOS", 1):
                import psycopg
                with self.assertRaises(psycopg.errors.LockNotAvailable):
                    main._init_db_postgres()
        finally:
            viejo.soltar()
        self.assertIsNone(_huella_guardada(), "quedó huella de un esquema a medio aplicar")
        r = main._init_db_postgres()                 # el próximo arranque lo termina
        self.assertGreater(r["corridas"], 0)
        self.assertIsNotNone(_huella_guardada())


@SOLO_PG
class LaCopiaALaMudanzaNoLaCompara(unittest.TestCase):

    def test_el_verificador_de_la_copia_no_ve_la_tabla_del_arranque(self):
        """El preflight de la copia SQLite→Postgres aborta ante UNA tabla que
        esté en un lado y no en el otro (le pasó con la vista `snapshots_medibles`).
        La tabla de la huella sólo existe en Postgres."""
        from scripts import verificar_copia as vc
        main._init_db_postgres()
        c = pgsesion.conectar(main.DATABASE_URL, autocommit=True)
        try:
            existe = c.execute("SELECT 1 FROM information_schema.tables WHERE "
                               "table_schema = current_schema() AND table_name = %s",
                               (pgsesion.TABLA_DEL_ARRANQUE,)).fetchone()
            vistas = vc.esquema_pg(c)
        finally:
            c.close()
        self.assertIsNotNone(existe, "la prueba no midió nada: la tabla no está")
        self.assertNotIn(pgsesion.TABLA_DEL_ARRANQUE, vistas)


class LoQueCorreAlImportarEstaDefinido(unittest.TestCase):
    """`init_db()` corre al IMPORTAR main.py, en la línea donde está escrito: todo
    lo que llama tiene que estar definido ARRIBA. Si no, es un NameError que el
    `except` de cada reparación se traga (deja un WARNING) y la reparación no corre
    nunca en un arranque de verdad. Las demás pruebas no lo ven: vuelven a llamar
    a `init_db()` con el archivo ya cargado entero. Pasó dos veces el 30/10/2026:
    el turno (lo agarró la revisión) y los tokens de reseteo y de links de asesor
    a huella (no corrían desde que salieron a `reparaciones_de_arranque`).

    Por el camino real: un proceso aparte que hace `import main` contra una base
    SQLite vacía, y se lee lo que dice."""

    def test_el_arranque_de_verdad_no_tira_nameerror(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
            env.update(DB_PATH=os.path.join(d, "arranque.db"), SECRET_KEY="test-secret")
            p = subprocess.run([sys.executable, "-c", "import main"], cwd=os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))), env=env, capture_output=True,
                text=True, timeout=180)
        salida = p.stdout + p.stderr
        self.assertEqual(p.returncode, 0, salida[-2000:])
        self.assertIn("tokens de reseteo:", salida, "la reparación de tokens no dijo nada: "
                      "¿cambió el mensaje o no corrió?")
        malos = [l for l in salida.splitlines() if "is not defined" in l]
        self.assertEqual(malos, [], "algo que corre al importar llama a una función "
                                    "definida más abajo en main.py")


class ElChequeoDeSalud(unittest.TestCase):

    def test_contesta_503_hasta_que_termina_el_arranque(self):
        http = TestClient(main.app)
        with mock.patch.object(main, "_ARRANQUE_LISTO", False):
            antes = http.get("/api/health")
        despues = http.get("/api/health")
        self.assertEqual(antes.status_code, 503)
        self.assertEqual(despues.status_code, 200)
        self.assertTrue(despues.json()["ok"])

    def test_init_db_lo_marca_listo(self):
        with mock.patch.object(main, "_ARRANQUE_LISTO", False):
            main.init_db()
            self.assertTrue(main._ARRANQUE_LISTO)

    def test_railway_consulta_esa_ruta(self):
        """railway.toml es lo que manda (pisa al panel). Si la ruta cambia en un
        lado y no en el otro, Railway marca fallida cada publicación."""
        toml = open(os.path.join(RAIZ, "railway.toml"), encoding="utf-8").read()
        ruta = re.search(r'^healthcheckPath\s*=\s*"([^"]+)"', toml, re.M)
        tope = re.search(r"^healthcheckTimeout\s*=\s*(\d+)", toml, re.M)
        self.assertIsNotNone(ruta, "railway.toml sin healthcheckPath")
        self.assertIn(ruta.group(1), {getattr(r, "path", None) for r in main.app.routes})
        self.assertIsNotNone(tope, "railway.toml sin healthcheckTimeout")
        self.assertGreaterEqual(int(tope.group(1)), 120,
                                "un tope corto marca fallida una copia sana que aplica el esquema")

    def test_railway_le_da_tiempo_al_apagado_ordenado(self):
        """Por defecto Railway mata a la copia vieja a los 0 s del aviso, y
        `_cerrar_al_apagar` (precios en memoria, corridas, mails en fila) no corre.
        `drainingSeconds` tiene que cubrir la espera de las corridas y dejar margen
        para los pedidos en curso."""
        toml = open(os.path.join(RAIZ, "railway.toml"), encoding="utf-8").read()
        m = re.search(r"^drainingSeconds\s*=\s*(\d+)", toml, re.M)
        self.assertIsNotNone(m, "railway.toml sin drainingSeconds: Railway mata a la copia vieja en el acto")
        self.assertGreaterEqual(int(m.group(1)), main.CORRIDAS_ESPERA_AL_APAGAR_SEG + 5,
                                "drainingSeconds no alcanza para que terminen las corridas al apagar")


if __name__ == "__main__":
    unittest.main()
