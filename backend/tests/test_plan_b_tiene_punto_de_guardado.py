"""GUARDIÁN: un «plan B» nuevo que corra sobre una transacción abortada no entra.

LA FORMA QUE VIGILA. Se intenta una sentencia y, si falla, el `except` VUELVE A
HABLAR CON LA BASE: la consulta corta sin la columna nueva, el INSERT sin la
marca, el SELECT para recuperarse de una carrera. En SQLite eso funciona —la
sentencia que falló no deja secuela—. En Postgres la transacción queda ABORTADA y
el plan B levanta `InFailedSqlTransaction`: un error DISTINTO del original, que el
`except` de afuera no reconoce. La red escrita para que algo no se cayera es
exactamente lo que se cae, y sólo del otro lado del motor.

POR QUÉ UN GUARDIÁN Y NO SÓLO LOS ARREGLOS. La cadena de por qués termina en algo
del proceso, no de cada sitio: «si falla, probá de nuevo sin la columna nueva» es
la manera en que este repo se protege de un deploy a mitad de camino, y se
escribió NUEVE veces a mano sin un lugar común. Arreglar los nueve no impide el
décimo. Esto sí: el que agregue uno nuevo ve un rojo que le dice qué poner.

QUÉ CUENTA COMO PROTEGIDO: que el `try` esté envuelto en
`_si_falla_se_deshace_solo_esto` (un SAVEPOINT), o que el plan B haga `rollback()`
antes de volver a escribir. Alcanza con cualquiera de los dos: lo que importa es
que la sentencia que falla no deje la transacción inservible.

⚠️ LA LISTA DE ABAJO NO ES UNA EXCUSA, ES UN CENSO. No falla «abierta»: si
aparece un sitio que no está en la lista, rojo; y si uno de la lista SE ARREGLA,
también rojo, para que se saque de acá y la lista no se vuelva un cementerio.
"""
import ast, os, pathlib, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = pathlib.Path(os.path.dirname(HERE))

# (archivo, función) → por qué sigue así. Censo al 2026-10-29.
#
# Eran 9. Seis se arreglaron con el punto de guardado (register ×2,
# get_current_user, _rollover_to_current_month, _window_floor,
# advisor_set_profile, run_daily_snapshot). Quedan los tres de abajo, y los tres
# por un motivo que NO es «ya lo vemos»: uno no aplica y dos piden una lectura
# que todavía nadie hizo.
CONOCIDOS = {
        ("main.py", "_db_internals"):
        "diagnóstico de admin y SQLite puro (dbstat, sqlite_master): en Postgres "
        "el endpoint entero no aplica. No vale tocarlo.",
    ("main.py", "wallbit_connect"):
        "el `except` atrapa un error de RED (WallbitError), no de base. Si "
        "_wallbit_do_sync dejó una sentencia fallada, el plan B muere igual — "
        "decidirlo pide leer _wallbit_do_sync.",
    ("main.py", "wallbit_sync_endpoint"):
        "mismo caso que wallbit_connect.",
        }


def _nodos(lista):
    for n in lista:
        yield from ast.walk(n)


def _sentencias_sql(cuerpo):
    return [n for n in _nodos(cuerpo)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("execute", "executemany", "executescript")]


def _esta_protegido(intento, plan_b):
    """¿La sentencia que falla corre adentro de un punto de guardado, o el plan B
    limpia antes de escribir?"""
    for cuerpo in (intento, plan_b):
        for n in _nodos(cuerpo):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
               and n.func.attr == "rollback":
                return True
            if isinstance(n, ast.Constant) and isinstance(n.value, str) \
               and ("ROLLBACK" in n.value.upper() or "SAVEPOINT" in n.value.upper()):
                return True
            if isinstance(n, ast.Call):
                nombre = getattr(n.func, "id", "") or getattr(n.func, "attr", "")
                if "se_deshace" in nombre:
                    return True
    return False


_CACHE = {}


def _barrer():
    if _CACHE:
        return _CACHE
    encontrados = {}
    for archivo in sorted(BACKEND.rglob("*.py")):
        rel = str(archivo.relative_to(BACKEND))
        if rel.startswith("tests/") or rel.startswith("scripts/") \
           or os.path.basename(rel).startswith("test_"):
            continue
        try:
            arbol = ast.parse(archivo.read_text(), filename=rel)
        except SyntaxError:
            continue
        funciones = [(f.lineno, f.end_lineno, f.name) for f in ast.walk(arbol)
                     if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for t in ast.walk(arbol):
            if not isinstance(t, ast.Try) or not _sentencias_sql(t.body):
                continue
            for h in t.handlers:
                if not _sentencias_sql(h.body):
                    continue
                if _esta_protegido([t], h.body):
                    continue
                dentro = [n for a, b, n in sorted(funciones) if a <= h.lineno <= b]
                encontrados[(rel, dentro[-1] if dentro else "?")] = h.lineno
    _CACHE.update(encontrados)
    return encontrados


class PlanBConPuntoDeGuardadoTest(unittest.TestCase):
    def test_no_hay_planes_b_nuevos_sin_punto_de_guardado(self):
        nuevos = {k: v for k, v in _barrer().items() if k not in CONOCIDOS}
        if nuevos:
            detalle = "\n".join(f"  · {a} → {f}() (línea {l})"
                                for (a, f), l in sorted(nuevos.items()))
            self.fail(
                "Hay un «plan B» nuevo que en Postgres va a correr sobre una "
                "transacción abortada:\n" + detalle +
                "\n\nEnvolvé la sentencia que puede fallar en "
                "`with _si_falla_se_deshace_solo_esto(conn, \"un_nombre\"):` "
                "(main.py) — o hacé `conn.rollback()` antes de reintentar. Si de "
                "verdad no aplica (SQLite puro, error de red), sumalo al censo "
                "CONOCIDOS de este archivo con el motivo.")

    def test_el_censo_no_tiene_sitios_ya_arreglados(self):
        vivos = _barrer()
        fantasmas = [k for k in CONOCIDOS if k not in vivos]
        if fantasmas:
            self.fail(
                "Estos sitios del censo ya no tienen la forma (se arreglaron o "
                "se movieron). Saquenlos de CONOCIDOS para que la lista no se "
                "vuelva un cementerio:\n" +
                "\n".join(f"  · {a} → {f}()" for a, f in sorted(fantasmas)))


if __name__ == "__main__":
    unittest.main()
