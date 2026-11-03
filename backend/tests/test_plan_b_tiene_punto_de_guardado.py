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

QUÉ CUENTA COMO «HABLAR CON LA BASE». Una sentencia escrita ahí (`execute`,
`commit`) o una llamada que RECIBE la conexión (`helper(conn)`): la mayoría de
los planes B pasan por otra función, y el censo que sólo buscaba `execute` no
veía 8 sitios (medido el 31/10/2026: créditos, mails, Wallbit…).

QUÉ CUENTA COMO PROTEGIDO, cualquiera de estas (lo que importa es que la
sentencia que falla no deje la transacción inservible para el plan B):
  · el `try` envuelto en `_si_falla_se_deshace_solo_esto` (un SAVEPOINT);
  · un `rollback()` —escrito ahí o adentro de una función del mismo archivo
    que se llama ahí, como `main._deshacer_transaccion`—;
  · el `try` es un solo `with conn:`: al salir con error deshace ANTES del
    `except` (`billing/credits.grant_payment_credit`).

⚠️ LAS LISTAS DE ABAJO NO SON UNA EXCUSA, SON UN CENSO. No fallan «abiertas»: si
aparece un sitio que no está, rojo; y si uno de la lista ya no tiene la forma,
también rojo, para que se saque y no se vuelva un cementerio. Dos listas:
  · `NO_APLICA`: el plan B corre sobre una transacción SANA, y la prueba que lo
    MIDE por el camino real está nombrada (sobre todo tests/test_plan_b_medido.py).
    Un razonamiento no alcanza: si nombra una prueba que no existe, rojo.
  · `PENDIENTES`: lo que falta arreglar. Sólo puede achicarse.
"""
import ast, os, pathlib, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = pathlib.Path(os.path.dirname(HERE))

# (archivo, función) → (por qué no aplica, la prueba que lo mide). Censo al 2026-10-31.
#
# Eran 9 (29/10); seis se arreglaron con el punto de guardado (register ×2,
# get_current_user, _rollover_to_current_month, _window_floor,
# advisor_set_profile, run_daily_snapshot). Los 3 que quedaban «por leer» se
# midieron el 31/10 y no aplican; el censo nuevo (que ve los planes B que pasan
# por otra función) sumó 8: 4 están protegidos y 4 no aplican.
NO_APLICA = {
    ("main.py", "_db_internals"): (
        "diagnóstico de admin que lee las tripas de SQLite (PRAGMA, dbstat, "
        "sqlite_master): en Postgres falla la PRIMERA sentencia y el panel "
        "contesta con el error adentro; el plan B no llega a correr.",
        "tests/test_plan_b_medido.py::DiagnosticoDeLaBaseTest"),
    ("main.py", "wallbit_connect"): (
        "el `except` atrapa WallbitError, que nace de la RED o de una validación "
        "después de una lectura sana (`_wallbit_ensure_broker`), nunca de SQL: el "
        "plan B (anotar el error del sync) corre sobre una transacción sana.",
        "tests/test_plan_b_medido.py::WallbitPlanBTest"),
    ("main.py", "wallbit_sync_endpoint"): (
        "mismo caso que wallbit_connect.",
        "tests/test_plan_b_medido.py::WallbitPlanBTest"),
    ("main.py", "sell_position_fifo"): (
        "el `except` atrapa la HTTPException que `_pata_de_la_moneda` levanta en "
        "Python (no hay caja en esa moneda) después de lecturas sanas; un error de "
        "SQL ahí adentro sale como error de psycopg, que ese `except` no atrapa. "
        "Medido 03/11/2026: con un punto de guardado alrededor, en SQLite el "
        "RELEASE confirmaba la pata creada y la venta que rebotaba la dejaba "
        "(test_venta_en_dolares_no_alcanza_no_usa_los_de_pesos en rojo); sin él, "
        "el plan B da su mensaje en los dos motores.",
        "tests/test_pata_de_la_moneda.py::PataDeLaMonedaTest"),
    ("main.py", "_rebill_activate"): (
        "lo que puede fallar en grant_payment_credit es una lectura SUELTA (lo "
        "anterior ya se confirmó, y pgshim no abre transacción para una lectura) o "
        "algo adentro de su `with conn:`, que deshace: la red de seguridad corre "
        "sobre una transacción sana.",
        "tests/test_plan_b_medido.py::ActivarConElLedgerRotoTest"),
    ("importing/pipeline.py", "run_preview"): (
        "el `except` atrapa _BrokersCambiaron, un aviso de Python que se lanza "
        "después de sentencias que salieron bien: la vista previa se rehace sobre "
        "una transacción sana.",
        "tests/test_renombrar_broker_durante_import.py::RenombrarDuranteLaVistaPreviaTest"),
    ("pgshim.py", "tomar"): (
        "si el «¿seguís viva?» de una conexión guardada falla, el `except` CIERRA "
        "esa conexión y prueba con otra: nunca vuelve a usar la que falló. (Sin "
        "prueba propia: leído, no medido.)",
        None),
}

# Lo que falta arreglar. Sólo puede achicarse.
PENDIENTES = {}


def _nodos(lista):
    for n in lista:
        yield from ast.walk(n)


def _sentencias_sql(cuerpo):
    return [n for n in _nodos(cuerpo)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in ("execute", "executemany", "executescript")]


def _conexiones(fn):
    """Los nombres que en esta función son la conexión: los que reciben un
    `execute`, y el parámetro `conn`."""
    out = {n.func.value.id for n in _sentencias_sql([fn]) if isinstance(n.func.value, ast.Name)}
    args = getattr(fn, "args", None)
    if args is not None and any(a.arg == "conn" for a in args.args + args.kwonlyargs):
        out.add("conn")
    return out


def _habla(cuerpo, cx):
    """¿Esto habla con la base? Una sentencia escrita ahí, o una llamada que
    recibe la conexión (el SQL vive en otra función)."""
    for n in _nodos(cuerpo):
        if not isinstance(n, ast.Call):
            continue
        if isinstance(n.func, ast.Attribute) and n.func.attr in (
                "execute", "executemany", "executescript", "commit"):
            return True
        argumentos = list(n.args) + [k.value for k in n.keywords]
        if any(isinstance(a, ast.Name) and a.id in cx for a in argumentos):
            return True
    return False


def _deshacen(arbol):
    """Las funciones de primer nivel del archivo que hacen `rollback()`."""
    return {f.name for f in arbol.body
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "rollback" for n in ast.walk(f))}


def _esta_protegido(intento, plan_b, cx=(), deshacen=()):
    """¿La sentencia que falla corre adentro de un punto de guardado, el plan B
    limpia antes de escribir, o un `with conn:` deshace antes del `except`?"""
    cuerpo_try = intento[0].body
    if len(cuerpo_try) == 1 and isinstance(cuerpo_try[0], ast.With) and any(
            isinstance(i.context_expr, ast.Name) and i.context_expr.id in cx
            for i in cuerpo_try[0].items):
        return True
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
                if "se_deshace" in nombre or nombre in deshacen:
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
        funciones = sorted(((f.lineno, f.end_lineno, id(f), f) for f in ast.walk(arbol)
                            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))),
                           key=lambda x: (x[0], -x[1]))
        deshacen = _deshacen(arbol)
        for t in ast.walk(arbol):
            if not isinstance(t, ast.Try):
                continue
            # La función MÁS de adentro que contiene al `try`.
            dentro = [f for a, b, _, f in funciones if a <= t.lineno <= b]
            fn = dentro[-1] if dentro else arbol
            cx = _conexiones(fn)
            if not _habla(t.body, cx):
                continue
            for h in t.handlers:
                if not _habla(h.body, cx):
                    continue
                if _esta_protegido([t], h.body, cx, deshacen):
                    continue
                encontrados[(rel, getattr(fn, "name", "?"))] = h.lineno
    _CACHE.update(encontrados)
    return encontrados


class PlanBConPuntoDeGuardadoTest(unittest.TestCase):
    def test_no_hay_planes_b_nuevos_sin_punto_de_guardado(self):
        nuevos = {k: v for k, v in _barrer().items()
                  if k not in NO_APLICA and k not in PENDIENTES}
        if nuevos:
            detalle = "\n".join(f"  · {a} → {f}() (línea {l})"
                                for (a, f), l in sorted(nuevos.items()))
            self.fail(
                "Hay un «plan B» nuevo que en Postgres va a correr sobre una "
                "transacción abortada:\n" + detalle +
                "\n\nEnvolvé la sentencia que puede fallar en "
                "`with pgsesion.si_falla_se_deshace_solo_esto(conn, \"un_nombre\"):` "
                "(en main.py, `_si_falla_se_deshace_solo_esto`). Si de verdad no "
                "aplica, MEDILO (tests/test_plan_b_medido.py) y sumalo a NO_APLICA "
                "con el motivo y esa prueba.")

    def test_el_censo_no_tiene_sitios_ya_arreglados(self):
        vivos = _barrer()
        fantasmas = [k for k in (*NO_APLICA, *PENDIENTES) if k not in vivos]
        if fantasmas:
            self.fail(
                "Estos sitios del censo ya no tienen la forma (se arreglaron o "
                "se movieron). Saquenlos de la lista para que no se vuelva un "
                "cementerio:\n" +
                "\n".join(f"  · {a} → {f}()" for a, f in sorted(fantasmas)))

    def test_cada_no_aplica_nombra_una_prueba_que_existe(self):
        """«No aplica» es una medición, no una opinión: la prueba tiene que estar."""
        faltan = []
        for clave, (_, prueba) in sorted(NO_APLICA.items()):
            if prueba is None:
                continue
            archivo, clase = prueba.split("::")
            ruta = BACKEND / archivo
            if not ruta.exists() or f"class {clase}(" not in ruta.read_text():
                faltan.append(f"  · {clave[0]} → {clave[1]}(): {prueba}")
        self.assertEqual(faltan, [], "Pruebas nombradas en NO_APLICA que no existen:\n"
                         + "\n".join(faltan))


if __name__ == "__main__":
    unittest.main()
