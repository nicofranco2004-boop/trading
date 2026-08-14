"""Ninguna conexión puede quedar abierta si el handler levanta una excepción.

POR QUÉ ESTE TEST EXISTE. El patrón viejo era:

    conn = get_db()
    row = conn.execute(...).fetchone()      ← si esto levanta…
    conn.close()                            ← …esta línea no corre nunca

En SQLite casi no se nota. En Postgres la conexión queda **`idle in transaction`**
reteniendo los locks de todo lo que tocó —hasta de un simple SELECT, porque
psycopg abre transacción para leer y sqlite3 no— y el siguiente request que toque
esas filas espera. **Es la misma traba que tiró la app el 12 y el 13/08/2026**, y
la que colgaba la suite de tests. Supabase da bastante menos margen de conexiones
que las 100 del Postgres local.

Eran 33 sitios. Se arreglaron con `main.db_abierta()`, no uno por uno: arreglar 33
a mano deja el problema esperando al 34.

⚠️ **LA TRAMPA, que es el motivo de que el helper se llame distinto.** En este
código `with conn:` YA significa otra cosa: confirmar o deshacer la TRANSACCIÓN.
`Connection.__exit__` hace commit/rollback y **NO cierra** (`pgshim.py:922`, igual
que `sqlite3`). O sea que `with get_db() as conn:` **no cierra nada** y el arreglo
parecería hecho sin estarlo. Hay un test acá abajo que fija esa diferencia, para
que nadie "simplifique" `db_abierta` a `get_db` más adelante.

Este archivo tiene dos tests y hacen falta los dos:
  · el de comportamiento — que `db_abierta` cierre aunque explote el cuerpo;
  · el ESTRUCTURAL — que barre `main.py` con AST y falla si aparece un sitio
    expuesto nuevo. Es el que impide el 34, y no depende de que alguien escriba
    un test para su endpoint.
"""
import ast
import os
import sqlite3
import unittest

import main


# ── El barrido estructural ───────────────────────────────────────────────────
# Mismo criterio que el recuento de la migración: un `X = get_db()` está protegido
# si el `try` que viene después EN SU MISMO BLOQUE lo cierra en su `finally`.
#
# ⚠️ El criterio flojo —"¿hay algún try/finally en la función que cierre esta
# variable?"— da FALSOS PROTEGIDOS: `_execute_ai_tool_inner` abre 6 conexiones y
# las 6 se llaman `conn`, así que alcanza con que UNA esté protegida para que las
# 6 parezcan bien. Por eso se mira la POSICIÓN, no la función entera.
def _cierra(nodos, nombre):
    for b in nodos:
        for n in ast.walk(b):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "close"
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == nombre):
                return True
    return False


def _abre_conexion(stmt):
    if (isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "get_db"):
        for t in stmt.targets:
            if isinstance(t, ast.Name):
                return t.id
    return None


def sitios_expuestos(path):
    """[(linea, funcion, var)] de cada `X = get_db()` cuyo close() se saltea si
    algo levanta antes."""
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    fuera = []

    def recorrer(body, fn, cerradas_por_envolvente=()):
        for i, stmt in enumerate(body):
            nombre = _abre_conexion(stmt)
            if nombre:
                # (a) el try que viene DESPUÉS, en este mismo bloque, la cierra
                protegido = False
                for nxt in body[i + 1:]:
                    if _abre_conexion(nxt) == nombre or isinstance(nxt, ast.Return):
                        break
                    if isinstance(nxt, ast.Try):
                        protegido = _cierra(nxt.finalbody, nombre)
                        break
                # (b) la apertura está ADENTRO de un try cuyo finally la cierra.
                #     Es la forma `conn = None; try: conn = get_db() … finally:
                #     if conn is not None: conn.close()`, que usan los tres
                #     escritores de fx_rates_daily. Sin este caso el barrido los
                #     marca mal — pasó al escribir este test.
                if not protegido and nombre in cerradas_por_envolvente:
                    protegido = True
                if not protegido:
                    fuera.append((stmt.lineno, fn, nombre))
            for campo, valor in ast.iter_fields(stmt):
                if isinstance(valor, list) and valor and isinstance(valor[0], ast.stmt):
                    sub = stmt.name if isinstance(
                        stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                    hereda = cerradas_por_envolvente
                    if isinstance(stmt, ast.Try) and campo == "body":
                        hereda = tuple(n.func.value.id for n in ast.walk(
                            ast.Module(body=stmt.finalbody, type_ignores=[]))
                            if isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Attribute)
                            and n.func.attr == "close"
                            and isinstance(n.func.value, ast.Name))
                    elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        hereda = ()          # otra función, otro alcance
                    recorrer(valor, sub, hereda)

    recorrer(tree.body, "<module>")
    return fuera


class DbAbiertaTest(unittest.TestCase):
    """El comportamiento del helper."""

    def test_cierra_cuando_el_cuerpo_explota(self):
        """El caso que importa: la excepción NO puede dejar la conexión abierta."""
        vistas = []
        original = main.get_db

        def espiar():
            c = original()
            vistas.append(c)
            return c

        main.get_db = espiar
        try:
            with self.assertRaises(ValueError):
                with main.db_abierta() as conn:
                    conn.execute("SELECT 1")
                    raise ValueError("algo explotó a la mitad del handler")
        finally:
            main.get_db = original

        self.assertEqual(len(vistas), 1)
        # Una conexión cerrada levanta al usarla. Es la prueba directa, sin
        # depender de un atributo interno del driver.
        with self.assertRaises(Exception):
            vistas[0].execute("SELECT 1")

    def test_cierra_en_el_camino_feliz(self):
        vistas = []
        original = main.get_db

        def espiar():
            c = original()
            vistas.append(c)
            return c

        main.get_db = espiar
        try:
            with main.db_abierta() as conn:
                conn.execute("SELECT 1")
        finally:
            main.get_db = original
        with self.assertRaises(Exception):
            vistas[0].execute("SELECT 1")

    def test_with_conn_NO_cierra_y_por_eso_hace_falta_db_abierta(self):
        """Fija la trampa: `with conn:` commitea/deshace, NO cierra.

        Si alguien "simplifica" `db_abierta()` a `get_db()` porque "el with ya
        cierra", este test se cae y explica por qué no.
        """
        conn = main.get_db()
        try:
            with conn:
                conn.execute("SELECT 1")
            # Sigue viva después del `with`: eso es lo que se está fijando.
            conn.execute("SELECT 1")
        finally:
            conn.close()

    def test_no_commitea_sola(self):
        """`db_abierta` cierra, no confirma.

        Si commiteara al salir, convertiría en permanente el trabajo a medias de
        cualquier handler que hoy revienta antes de su commit — cambiaría el
        comportamiento de 33 endpoints en vez de arreglarles el cierre.
        """
        email = "no-commitea@rendi.test"
        with main.db_abierta() as conn:
            conn.execute("INSERT INTO users (email, password_hash, approved) "
                         "VALUES (?,?,1)", (email, "x"))
            # sin commit a propósito
        with main.db_abierta() as conn:
            r = conn.execute("SELECT COUNT(*) c FROM users WHERE email=?",
                             (email,)).fetchone()
        self.assertEqual(int(r["c"] or 0), 0,
                         "db_abierta commiteó sola: no debe")


class NingunaConexionExpuestaTest(unittest.TestCase):
    """El barrido. Es el que impide que vuelva el problema."""

    def test_main_no_tiene_ninguna_conexion_expuesta(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "main.py")
        fuera = sitios_expuestos(path)
        if fuera:
            detalle = "\n".join(f"  main.py:{l}  {fn}()  (var={v})" for l, fn, v in fuera)
            self.fail(
                f"{len(fuera)} conexión(es) que no se cierran si el handler levanta "
                f"una excepción. En Postgres cada una queda `idle in transaction` "
                f"reteniendo locks — la misma traba que tiró la app el 12 y 13/08.\n"
                f"Usá `with main.db_abierta() as conn:` (NO `with get_db() as conn:`, "
                f"que commitea pero no cierra).\n{detalle}")

    def test_el_barrido_sabe_encontrar_uno(self):
        """El barrido tiene que fallar con código malo, si no no prueba nada."""
        import tempfile
        malo = (
            "def handler():\n"
            "    conn = get_db()\n"
            "    row = conn.execute('SELECT 1').fetchone()\n"
            "    conn.close()\n"
            "    return row\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(malo)
            tmp = f.name
        try:
            fuera = sitios_expuestos(tmp)
            self.assertEqual(len(fuera), 1, fuera)
            self.assertEqual(fuera[0][1], "handler")
        finally:
            os.unlink(tmp)

    def test_el_barrido_no_marca_el_patron_bueno(self):
        import tempfile
        bueno = (
            "def handler():\n"
            "    conn = get_db()\n"
            "    try:\n"
            "        return conn.execute('SELECT 1').fetchone()\n"
            "    finally:\n"
            "        conn.close()\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(bueno)
            tmp = f.name
        try:
            self.assertEqual(sitios_expuestos(tmp), [])
        finally:
            os.unlink(tmp)

    def test_el_barrido_no_marca_la_apertura_adentro_del_try(self):
        """La otra forma buena, que el barrido marcaba mal en su primera versión.

        La usan los tres escritores de `fx_rates_daily`. El `conn = None` de
        arriba es lo que hace que el `finally` pueda preguntar si llegó a abrirse.
        """
        import tempfile
        bueno = (
            "def handler():\n"
            "    conn = None\n"
            "    try:\n"
            "        conn = get_db()\n"
            "        return conn.execute('SELECT 1').fetchone()\n"
            "    finally:\n"
            "        if conn is not None:\n"
            "            conn.close()\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
            f.write(bueno)
            tmp = f.name
        try:
            self.assertEqual(sitios_expuestos(tmp), [])
        finally:
            os.unlink(tmp)


if __name__ == "__main__":
    unittest.main()
