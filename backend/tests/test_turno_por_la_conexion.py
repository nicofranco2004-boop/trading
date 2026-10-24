"""El turno se decide por LA CONEXIÓN, no por una bandera del proceso.

🔴 QUÉ VIGILA. `pgsesion.turno_exclusivo` pide un candado que sólo existe en
Postgres (`pg_advisory_xact_lock`). La primera versión decidía si pedirlo
mirando `main.USANDO_PG`, que es una bandera de PROCESO: dice «este proceso
arrancó con DATABASE_URL puesta». Eso no es lo mismo que «la conexión que me
dieron habla Postgres».

Hay código que abre una base SQLite propia aunque el proceso tenga DATABASE_URL:
los tests con `sqlite3.connect(":memory:")` son el caso evidente, y un script
suelto es el que importa de verdad. Ahí la bandera decía «Postgres» y el turno
mandaba la función de Postgres por una conexión de SQLite:

    sqlite3.OperationalError: no such function: pg_advisory_xact_lock

Reventaba, no fallaba callado. Medido: **13 tests rojos** en `test_ai_plan`,
`test_ai_quota`, `test_alerts` y `test_efectivo_una_puerta`.

⚠️ Y POR QUÉ LA SUITE DE SQLITE NO PODÍA ENCONTRARLO: allá la bandera está en
falso, así que el turno no se pide nunca y el error no existe. Este archivo
**sólo mide algo cuando `DATABASE_URL` está puesta** — contra SQLite pasa con y
sin el arreglo, y eso está dicho acá para que nadie lea el verde como prueba.

LA REGLA GENERAL, que vale más que el arreglo: una decisión sobre QUÉ SABE HACER
un objeto se le pregunta al objeto, no a una variable global que habla del
proceso. Y falla CERRADA: si no se reconoce el tipo, no se pide el candado.
Pedirlo donde no corresponde revienta; no pedirlo deja el tope como estaba antes
—malo, pero no una caída.
"""
import os
import sqlite3
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main
import pgsesion as _ps

CON_POSTGRES = bool(getattr(main, "USANDO_PG", False))


class QuienHablaPostgres(unittest.TestCase):
    def test_sqlite_no_habla_postgres(self):
        c = sqlite3.connect(":memory:")
        try:
            self.assertFalse(_ps.habla_postgres(c))
        finally:
            c.close()

    def test_la_conexion_de_la_app_si_habla_postgres_cuando_corresponde(self):
        c = main.get_db()
        try:
            self.assertEqual(
                _ps.habla_postgres(c), CON_POSTGRES,
                "la conexión que usa la app tiene que coincidir con el motor "
                "con el que se está corriendo")
        finally:
            c.close()

    def test_cualquier_otra_cosa_dice_que_no(self):
        # Falla cerrada: un objeto que no se reconoce NO recibe el candado.
        class Cualquiera:
            pass
        self.assertFalse(_ps.habla_postgres(Cualquiera()))
        self.assertFalse(_ps.habla_postgres(None))


class ElTurnoPorUnaConexionDeSqlite(unittest.TestCase):
    """El caso que reventaba. Sin el arreglo y con DATABASE_URL puesta, las dos
    formas del turno levantan `no such function: pg_advisory_xact_lock`."""

    @unittest.skipUnless(
        CON_POSTGRES,
        "sin DATABASE_URL la bandera ya estaba en falso: acá no se mide nada")
    def test_no_revienta_con_una_base_sqlite_propia(self):
        c = sqlite3.connect(":memory:")
        try:
            # Una clave
            _ps.turno_exclusivo(c, _ps.TURNO_TOPE_TRIALS_DEL_MES)
            # Dos claves
            _ps.turno_exclusivo(c, _ps.TURNO_CAJA_DEL_BROKER, 1)
            _ps.turno_exclusivo(c, _ps.TURNO_CUOTA_IA_POR_USUARIO, 1)
            _ps.turno_exclusivo(c, _ps.TURNO_TOPE_DEL_PLAN_POR_USUARIO, 1)
        finally:
            c.close()

    @unittest.skipUnless(CON_POSTGRES, "el candado sólo existe en Postgres")
    def test_por_la_conexion_de_la_app_el_turno_SI_se_pide(self):
        """El contraste: que arreglar el caso de SQLite no haya apagado el
        candado donde sí hace falta.

        Se comprueba por el EFECTO y no por el string: después de pedir el
        turno, Postgres tiene que listar ese candado como tomado por esta
        sesión. Si `habla_postgres` empezara a decir «no» para la conexión de la
        app, el candado no aparecería y el tope quedaría sin protección sin que
        nada avise.
        """
        c = main.get_db()
        try:
            _ps.turno_exclusivo(c, _ps.TURNO_CAJA_DEL_BROKER, 424242)
            fila = c.execute(
                "SELECT COUNT(*) AS n FROM pg_locks "
                " WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
                "   AND classid = ? AND objid = ?",
                (_ps.TURNO_CAJA_DEL_BROKER, 424242)).fetchone()
            self.assertEqual(
                int(fila["n"]), 1,
                "el turno no quedó tomado: la conexión de la app dejó de pedirlo")
        finally:
            try: c.rollback()      # suelta el candado
            except Exception: pass
            c.close()


if __name__ == "__main__":
    unittest.main()
