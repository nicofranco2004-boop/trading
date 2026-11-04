"""GUARDIÁN: una limpieza de test no borra una tabla madre antes que su hija.

LA FORMA QUE VIGILA. `for t in ("users", "brokers"): DELETE FROM {t}`. Con
`foreign_keys=ON` (los dos motores) borrar `users` mientras un broker lo apunta
falla siempre. Copiada con `try/except: pass` en ~117 archivos, la falla no se
ve: en SQLite la fila queda viva callada; en Postgres la transacción entera
queda abortada y lo que sigue revienta con `InFailedSqlTransaction` lejos de la
causa. Medido el 30/10/2026: test_audit_bloqueantes B5, rojo sólo en Postgres.

POR QUÉ UN GUARDIÁN. Las 117 copias no se migraron todas a `tests/_limpieza.vaciar`
(que ordena sola): hoy ninguna otra tiene el orden al revés, pero basta con que
un test nuevo inserte un broker para que vuelva a pasar. Esto lo pone en rojo
antes, con la tabla y la línea.

LAS DEPENDENCIAS SE LE PREGUNTAN A LA BASE (en el motor en que corra), no a una
lista escrita acá. Las que tienen `ON DELETE CASCADE` no cuentan.

⚠️ PUNTO CIEGO: si la hija la crea la APP (un endpoint que da de alta un
broker) y el archivo no tiene un `INSERT INTO brokers` escrito, esto no lo ve.
Para eso está `vaciar`, que suma las hijas sola.
"""
import ast
import pathlib
import re
import unittest

import main
from tests._limpieza import _dependencias, vaciar

TESTS = pathlib.Path(__file__).resolve().parent


def _listas_de_limpieza(arbol):
    """(línea, [tablas], ¿completa?) de cada `for t in <lista>:` que borra.

    «Completa» es que todos los elementos sean texto escrito ahí: con un
    `*main._reset_admin_tablas()` adentro no se puede saber qué falta, sólo
    revisar el orden de lo que se ve."""
    constantes = {}
    for a in ast.walk(arbol):
        if isinstance(a, ast.Assign) and isinstance(a.value, (ast.Tuple, ast.List)):
            for destino in a.targets:
                if isinstance(destino, ast.Name):
                    constantes[destino.id] = a.value
    for bucle in ast.walk(arbol):
        if not isinstance(bucle, ast.For):
            continue
        lista = bucle.iter
        if isinstance(lista, ast.Name):
            lista = constantes.get(lista.id, lista)
        if not isinstance(lista, (ast.Tuple, ast.List)):
            continue
        nombres = [e.value for e in lista.elts
                   if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if len(nombres) >= 2 and "DELETE" in ast.unparse(bucle).upper():
            yield bucle.lineno, nombres, len(nombres) == len(lista.elts)


class LimpiezaBorraHijasPrimeroTest(unittest.TestCase):
    def setUp(self):
        self.conn = main.get_db()
        self.addCleanup(self.conn.close)

    def test_ninguna_limpieza_borra_una_madre_antes_que_su_hija(self):
        deps = _dependencias(self.conn)
        self.assertIn("brokers", deps.get("users", ()),
                      "la base dejó de decir que brokers apunta a users: revisá "
                      "_dependencias antes de confiar en este guardián")
        malos = []
        for archivo in sorted(TESTS.glob("test_*.py")):
            texto = archivo.read_text()
            insertadas = {t.lower() for t in re.findall(
                r"INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\w+)", texto, re.I)}
            for linea, nombres, completa in _listas_de_limpieza(ast.parse(texto)):
                for i, madre in enumerate(nombres):
                    for hija in sorted(deps.get(madre, ())):
                        if hija in nombres[i + 1:]:
                            malos.append(f"{archivo.name}:{linea} borra {madre} "
                                         f"antes que {hija}")
                        elif completa and hija not in nombres and hija in insertadas:
                            malos.append(f"{archivo.name}:{linea} borra {madre} y "
                                         f"no {hija}, que el archivo inserta")
        if malos:
            self.fail("Limpiezas que fallan al borrar (en Postgres envenenan la "
                      "transacción):\n  · " + "\n  · ".join(malos) +
                      "\n\nUsá `tests._limpieza.vaciar(conn, *tablas)`, que ordena "
                      "hijas antes que madres y suma las que faltan.")

    def test_vaciar_borra_un_usuario_con_broker(self):
        """El caso que rompía B5, por el camino real: un usuario con un broker."""
        uid = self.conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?,?,1)",
            ("limpieza-hijas@t", "x")).lastrowid
        self.conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                          (uid, "IBKR", "USD"))
        self.conn.commit()
        vaciar(self.conn, "users")
        self.conn.commit()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM brokers").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
