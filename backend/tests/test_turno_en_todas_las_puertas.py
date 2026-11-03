"""El turno de escritura tiene que pedirlo TODA puerta que escribe la plata.

`main._tomar_turno` (`UPDATE users SET tier=tier WHERE id=?`) pone en fila a los
pedidos de un mismo usuario. En SQLite eso pasaba solo: la primera escritura toma
la base entera. En Postgres toma sólo la fila de `users`, así que espera
únicamente quien también la escriba — y 33 puertas que escriben la plata no la
escribían (censo del 29/10/2026). La auditoría de los 14 sitios (audit/turno_14/)
encontró los cruces reales: en los 9 que sobrevivieron, el que se metía en el
medio era siempre una puerta sin turno (importar, depósito/retiro, operación a
mano).

Dos pruebas:
  · comportamiento, en Postgres: borrar un mes mientras entra un depósito;
  · el censo: toda función de main.py que ABRE una conexión y escribe con ella
    (ella o lo que llama pasándole esa conexión) una tabla de la plata, pide el
    turno. Se cuenta al que abre la conexión y no a la puerta HTTP: el turno vale
    por transacción y por conexión, y un ayudante con conexión propia (la
    reconstrucción después de un import, las herramientas del chat) es otra fila.

`PENDIENTES` no es una lista de excepciones: es lo que falta, y sólo puede
achicarse. Falla si aparece una función nueva sin turno (no se puede sumar acá) y
falla si una de la lista ya lo pide (hay que sacarla). Son las que recorren MUCHOS
usuarios con una sola conexión —el turno es por usuario y hay que pedirlo adentro
del recorrido, en orden, para no trabarse entre dos— o las que salen a la red
durante minutos con la cuenta tomada.
"""
import ast
import os
import re
import sys
import threading
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
import main


TABLAS_DE_LA_PLATA = ("monthly_entries", "snapshots", "operations", "positions", "flujos_a_mano")

PIDE_TURNO = re.compile(r"\b_tomar_turno(_de_la_puerta|s_en_orden)?\(")

# Ayudantes que piden el turno ADENTRO de cada una de sus transacciones (porque
# hacen más de una, o recorren varios usuarios): quien los llama queda cubierto.
# `test_los_que_piden_adentro_lo_piden` verifica que cada uno lo pida de verdad.
PIDEN_ADENTRO = {
    "_wipe_broker_data": "tres transacciones; pedirlo una vez en la puerta dejaba dos sin él",
    "_repair_snapshots_summary": "un usuario por transacción",
    "_repair_interes_pf": "varios usuarios, en orden",
    "_repair_caja_1415": "varios usuarios, en orden",
    # Cubre a `init_db`. Su rama de Postgres sólo escribe datos a través de ésta;
    # lo que `init_db` escribe en su propio cuerpo es la rama de SQLite (las
    # migraciones históricas), donde la primera escritura toma la base entera y
    # Railway no superpone copias con volumen.
    "reparaciones_de_arranque": "cada reparación de positions, con los turnos de las cuentas que toca",
    # Los tres que el censo no veía (nombre de tabla en una variable), 30/10/2026:
    "_borrar_usuario_y_datos": "borrar la cuenta: el turno de la cuenta y sus shadows, en orden, "
                               "antes de barrer sus tablas (se trababa con la reconstrucción)",
    "_borrar_en_chunks": "empezar de cero: una tanda por transacción, cada una con su turno",
    "_aplicar_remap_fci": "migración de FCI al arrancar: una cuenta por transacción, con su turno",
}

# Lo que falta, con el motivo. Sólo puede achicarse (ver el docstring del módulo).
# Vacía desde el 30/10/2026: `init_db` (arriba) y `_reconstruir_mtm`, que pide el
# turno después de Yahoo y antes de escribir (tests/test_turno_reconstruccion_y_arranque.py).
PENDIENTES: dict = {}


# Una escritura cuyo nombre de tabla está en una variable que el censo no puede
# resolver (un parámetro, `esquema.items()`…). Cuenta como de la plata: no se
# puede probar que no lo sea, y el error barato es pedir un turno de más.
DESCONOCIDA = "¿tabla en una variable?"

_ESCRITURA_SQL = re.compile(r"(INSERT INTO|UPDATE|DELETE FROM)\s+(?:(\w+)|\{(\w*)\})")


def _textos_sql(fn):
    """Cada texto del cuerpo de `fn`; en los f-strings, la parte variable queda
    como `{nombre}` (o `{}` si no es un nombre suelto)."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.value
        elif isinstance(n, ast.JoinedStr):
            partes = []
            for v in n.values:
                if isinstance(v, ast.Constant):
                    partes.append(str(v.value))
                elif isinstance(v, ast.FormattedValue):
                    partes.append("{%s}" % (v.value.id if isinstance(v.value, ast.Name) else ""))
            yield "".join(partes)


# Lo que devuelve `main._colgadas_de_alerts`: las tablas que cuelgan de `alerts`
# por `alert_id` y NO tienen `user_id`. Ninguna de la plata puede salir de ahí,
# porque todas las de la plata tienen `user_id`; lo prueba
# `test_las_colgadas_de_alerts_no_son_de_la_plata` contra el esquema de verdad.
# Las usan el arranque (`_borrar_marcas_sueltas`) y borrar una alerta
# (`alerts_delete`), que entraron con lo publicado el 03/11.
COLGADAS_DE_ALERTS = "(colgadas de alerts, sin user_id)"


def _textos_de(nodo, constantes):
    """{textos} si `nodo` es un texto, una tupla/lista/conjunto de textos (o de
    tuplas cuyo primer elemento es texto), un nombre de módulo que vale eso, o
    `modulo.CONSTANTE`; None si no se puede saber."""
    if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            and nodo.func.id == "_colgadas_de_alerts"):
        return {COLGADAS_DE_ALERTS}
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return {nodo.value}
    if isinstance(nodo, (ast.Tuple, ast.List, ast.Set)):
        out = set()
        for e in nodo.elts:
            if isinstance(e, ast.Tuple) and e.elts:
                e = e.elts[0]
            v = _textos_de(e, constantes)
            if v is None:
                return None
            out |= v
        return out
    if isinstance(nodo, ast.Name) and nodo.id in constantes:
        return _textos_de(constantes[nodo.id], constantes)
    if isinstance(nodo, ast.Attribute) and isinstance(nodo.value, ast.Name):
        try:
            import importlib
            v = getattr(importlib.import_module(nodo.value.id), nodo.attr)
        except Exception:
            return None
        if isinstance(v, str):
            return {v}
        if isinstance(v, (tuple, list, set, frozenset)) and all(isinstance(x, str) for x in v):
            return set(v)
    return None


def _valores_de(fn, nombre, constantes):
    """Los textos que puede valer la variable `nombre` adentro de `fn`: los de
    los `for nombre in (...)` (también `for nombre, x in ...`) y los de
    `nombre = ...`. None si alguna fuente no se puede leer o no hay ninguna."""
    out, vistas = set(), 0
    for n in ast.walk(fn):
        if isinstance(n, (ast.For, ast.comprehension)):
            t = n.target
            if isinstance(t, ast.Tuple) and t.elts:
                t = t.elts[0]
            if not (isinstance(t, ast.Name) and t.id == nombre):
                continue
            v = _textos_de(n.iter, constantes)
            if (v is None and isinstance(n.iter, ast.Name) and n.iter.id != nombre
                    and n.iter.id not in constantes):
                # `colgadas = _colgadas_de_alerts(...)` y después `for t in colgadas`
                v = _valores_de(fn, n.iter.id, constantes)
        elif isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == nombre for t in n.targets):
            v = _textos_de(n.value, constantes)
        else:
            continue
        vistas += 1
        if v is None:
            return None
        out |= v
    return out if vistas else None


def _tablas_que_escribe(fn, constantes):
    """Las tablas que `fn` escribe, también cuando el nombre va en una variable
    (`for t in (...): conn.execute(f"DELETE FROM {t} ...")`). Las que no se
    pueden resolver vuelven como `DESCONOCIDA`."""
    out = set()
    for texto in _textos_sql(fn):
        for m in _ESCRITURA_SQL.finditer(texto):
            if m.group(2):
                out.add(m.group(2))
                continue
            v = _valores_de(fn, m.group(3), constantes) if m.group(3) else None
            out |= v if v is not None else {DESCONOCIDA}
    return out


def _duenos_de_conexion_sin_turno(src=None, piden_adentro=None, ver_variables=True):
    """Las funciones de main.py que abren una conexión (`get_db()` /
    `db_abierta()`) y escriben con ELLA —en su cuerpo o en lo que llaman sin abrir
    otra— alguna tabla de la plata, sin pedir el turno en su propio cuerpo.

    Ve también el nombre de la tabla en una variable (`_tablas_que_escribe`).
    Hasta el 30/10/2026 buscaba sólo nombres escritos tal cual, y por eso no vio
    a tres que borraban la plata sin turno: borrar la cuenta
    (`_wipe_user_rows`: `f"DELETE FROM {t}"` sobre todo el esquema), empezar de
    cero (`_borrar_en_chunks(conn, uid, tabla, …)`) y la migración de tickers
    de FCI. El primero se trababa en cruz con la reconstrucción
    (`deadlock detected`)."""
    if src is None:
        src = open(os.path.join(BACKEND, "main.py"), encoding="utf-8").read()
    if piden_adentro is None:
        piden_adentro = set(PIDEN_ADENTRO)
    lineas = src.splitlines()
    arbol = ast.parse(src)
    top = {n.name: n for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    constantes = {t.id: n.value for n in arbol.body if isinstance(n, ast.Assign)
                  for t in n.targets if isinstance(t, ast.Name)}
    cuerpo = {k: "\n".join(lineas[v.lineno - 1:v.end_lineno]) for k, v in top.items()}
    escritura = re.compile(r"(INSERT INTO|UPDATE|DELETE FROM)\s+(\w+)")
    escribe = {k: ({m.group(2) for m in escritura.finditer(s)}
                   | (_tablas_que_escribe(top[k], constantes) if ver_variables else set()))
                  & (set(TABLAS_DE_LA_PLATA) | {DESCONOCIDA})
               for k, s in cuerpo.items()}
    abre_conexion = re.compile(r"\bget_db\(\)|\bdb_abierta\(\)")
    duenos = {k for k, s in cuerpo.items()
              if abre_conexion.search(s) and k not in ("get_db", "db_abierta")}
    llama = {k: {c.func.id for c in ast.walk(v)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                 and c.func.id in top and c.func.id != k}
             for k, v in top.items()}

    def con_su_conexion(k):
        vistos, cola = {k}, [k]
        while cola:
            x = cola.pop()
            for y in llama[x]:
                # otro dueño = otra conexión; los que piden el turno adentro ya
                # cubren lo que escriben (lo verifica test_los_que_piden_adentro_lo_piden)
                if y not in vistos and y not in duenos and y not in piden_adentro:
                    vistos.add(y)
                    cola.append(y)
        return vistos

    faltan = {}
    for k in duenos:
        tablas = set().union(*(escribe[x] for x in con_su_conexion(k)))
        if tablas and not PIDE_TURNO.search(cuerpo[k]) and not (llama[k] & piden_adentro):
            faltan[k] = f"{k} (main.py:{top[k].lineno}) escribe {sorted(tablas)}"
    return faltan


class ElCensoDeLasPuertas(unittest.TestCase):

    def test_las_colgadas_de_alerts_no_son_de_la_plata(self):
        """Lo que permite que el censo no cuente como «de la plata» lo que se
        borra recorriendo `_colgadas_de_alerts`: sobre el esquema de verdad, esa
        lista no tiene ninguna tabla de la plata, y no está vacía (si lo
        estuviera, esta prueba no probaría nada)."""
        import main
        conn = main.get_db()
        try:
            colgadas = set(main._colgadas_de_alerts(main._esquema_por_tabla(conn)))
        finally:
            conn.close()
        self.assertIn("alert_symbol_state", colgadas)
        self.assertEqual(colgadas & set(TABLAS_DE_LA_PLATA), set())

    def test_quien_abre_una_conexion_y_escribe_la_plata_pide_el_turno(self):
        faltan = _duenos_de_conexion_sin_turno()
        nuevas = sorted(v for k, v in faltan.items() if k not in PENDIENTES)
        self.assertEqual(nuevas, [], "Escriben la plata sin pedir el turno; en Postgres se "
                                     "meten en el medio de los borrados y los deshacer "
                                     "(audit/turno_14/). Pedí `_tomar_turno_de_la_puerta` "
                                     "primero en cada transacción:\n  " + "\n  ".join(nuevas))

    def test_la_lista_de_pendientes_solo_se_achica(self):
        faltan = _duenos_de_conexion_sin_turno()
        ya_arreglados = sorted(k for k in PENDIENTES if k not in faltan)
        self.assertEqual(ya_arreglados, [], "Ya piden el turno (o ya no existen): sacalos de "
                                            "PENDIENTES para que no vuelvan a entrar sin él.")

    def test_los_que_piden_adentro_lo_piden(self):
        src = open(os.path.join(BACKEND, "main.py"), encoding="utf-8").read()
        lineas = src.splitlines()
        top = {n.name: n for n in ast.parse(src).body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        no_lo_piden = sorted(k for k in PIDEN_ADENTRO
                             if k not in top or not PIDE_TURNO.search(
                                 "\n".join(lineas[top[k].lineno - 1:top[k].end_lineno])))
        self.assertEqual(no_lo_piden, [], "PIDEN_ADENTRO dice que piden el turno y no")

    def test_el_censo_ve_lo_que_tiene_que_ver(self):
        """Contra un caso cuya respuesta ya se conoce: `delete_monthly` abre una
        conexión, escribe monthly_entries y pide el turno. Si el censo dejara de
        verla escribir, el test de arriba pasaría por no mirar."""
        src = open(os.path.join(BACKEND, "main.py"), encoding="utf-8").read()
        sin = src.replace("_tomar_turno(conn, uid)\n            target = conn.execute(",
                          "target = conn.execute(", 1)
        self.assertNotEqual(sin, src, "cambió delete_monthly: actualizá este control")
        import unittest.mock as _m
        real_open = open

        def abrir(ruta, *a, **kw):
            if str(ruta).endswith("main.py"):
                import io
                return io.StringIO(sin)
            return real_open(ruta, *a, **kw)
        with _m.patch("builtins.open", abrir):
            self.assertIn("delete_monthly", _duenos_de_conexion_sin_turno())

    def test_el_censo_ve_las_tablas_en_variables(self):
        """Contra la respuesta conocida del 30/10/2026: borrar la cuenta
        (`_wipe_user_rows`, `f"DELETE FROM {t}"` sobre el esquema), empezar de cero
        (`_borrar_en_chunks(conn, uid, tabla, …)`) y la migración de FCI
        (`for tbl, col in ((…), …)`). Sin los tres de PIDEN_ADENTRO, el censo tiene
        que marcar a sus dueños; el de antes —sólo nombres escritos tal cual— no
        los veía."""
        sin_los_tres = set(PIDEN_ADENTRO) - {"_borrar_usuario_y_datos", "_borrar_en_chunks",
                                             "_aplicar_remap_fci"}
        duenos = {"delete_my_account", "admin_delete_user", "_reset_data_worker",
                  "_migrate_fci_ticker_remap"}
        ahora = _duenos_de_conexion_sin_turno(piden_adentro=sin_los_tres)
        antes = _duenos_de_conexion_sin_turno(piden_adentro=sin_los_tres, ver_variables=False)
        self.assertEqual(duenos - set(ahora), set(), ahora)
        # FCI ya no va acá: su arreglo escribe los nombres tal cual (el patrón
        # `for tbl, col in …` que tenía lo cubre la prueba de abajo, caso `c`).
        dinamicos = duenos - {"_migrate_fci_ticker_remap"}
        self.assertEqual(dinamicos & set(antes), set(),
                         "el censo viejo ya los veía: esta prueba no mide la mejora")

    def test_resuelve_el_nombre_desde_el_bucle_o_lo_declara_desconocido(self):
        arbol = ast.parse(
            "def a(conn):\n"
            "    for t in ('positions', 'config'):\n"
            "        conn.execute(f'DELETE FROM {t} WHERE user_id=?')\n"
            "def b(conn, tabla):\n"
            "    conn.execute(f'DELETE FROM {tabla} WHERE x=1')\n"
            "def c(conn):\n"
            "    for tbl, col in (('operations', 'asset'), ('brokers', 'name')):\n"
            "        conn.execute(f'UPDATE {tbl} SET {col}=?')\n")
        fns = {f.name: f for f in arbol.body}
        self.assertEqual(_tablas_que_escribe(fns["a"], {}), {"positions", "config"})
        self.assertEqual(_tablas_que_escribe(fns["b"], {}), {DESCONOCIDA})
        self.assertEqual(_tablas_que_escribe(fns["c"], {}), {"operations", "brokers"})


@unittest.skipUnless(getattr(main, "USANDO_PG", False),
                     "en SQLite la primera escritura toma la base entera y el cruce no se da")
class BorrarUnMesMientrasEntraUnDeposito(unittest.TestCase):
    """audit/turno_14/delete_monthly.md. El broker tiene un solo mes (noviembre,
    100.000 depositados). Se borra ese mes y, antes de que el borrado confirme,
    entra un depósito de 500 fechado en diciembre. El depósito crea la fila de
    diciembre con el capital inicial «del mes anterior»: si todavía ve noviembre,
    arranca en 100.000 y lo aportado del broker queda inflado para siempre (es la
    primera fila: nada la recalcula)."""

    BROKER = "TurnoMes"

    def setUp(self):
        conn = main.get_db()
        self.uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            (f"turno-{uuid.uuid4().hex[:10]}@rendi.test",)).lastrowid
        conn.execute("INSERT INTO brokers (user_id, name, currency) VALUES (?,?,?)",
                     (self.uid, self.BROKER, "USD"))
        conn.commit()
        conn.close()
        main.cash_flow(main.CashFlowIn(broker_name=self.BROKER, direction="deposit",
                                       amount=100000.0, date="2025-11-05"), uid=self.uid)
        conn = main.get_db()
        self.eid = conn.execute(
            "SELECT id FROM monthly_entries WHERE user_id=? AND broker=? AND year=2025 AND month=11",
            (self.uid, self.BROKER)).fetchone()["id"]
        conn.close()

    def tearDown(self):
        conn = main.get_db()
        for t in ("flujos_a_mano", "monthly_entries", "positions", "snapshots", "brokers"):
            conn.execute(f"DELETE FROM {t} WHERE user_id=?", (self.uid,))
        conn.execute("DELETE FROM users WHERE id=?", (self.uid,))
        conn.commit()
        conn.close()

    def test_el_deposito_no_hereda_el_mes_que_se_esta_borrando(self):
        deposito_listo = threading.Event()
        real = main._repair_monthly_chain
        frenado = {"una_vez": False}

        def repair_que_espera(conn, uid, broker, *a, **kw):
            # La primera reparación es la del borrado: ya borró noviembre y no
            # confirmó. Espera a que el depósito termine (o 3 s, si el depósito
            # está esperando al borrado, que es justo lo que tiene que pasar).
            if not frenado["una_vez"] and broker == self.BROKER:
                frenado["una_vez"] = True
                deposito_listo.wait(timeout=3)
            return real(conn, uid, broker, *a, **kw)

        main._repair_monthly_chain = repair_que_espera
        errores = []
        try:
            def borrar():
                try:
                    main.delete_monthly(self.eid, uid=self.uid)
                except Exception as ex:
                    errores.append(f"borrar: {ex}")

            def depositar():
                try:
                    main.cash_flow(main.CashFlowIn(broker_name=self.BROKER, direction="deposit",
                                                   amount=500.0, date="2025-12-05"), uid=self.uid)
                except Exception as ex:
                    errores.append(f"depositar: {ex}")
                finally:
                    deposito_listo.set()

            a = threading.Thread(target=borrar)
            a.start()
            for _ in range(200):                    # hasta que el borrado esté frenado
                if frenado["una_vez"]:
                    break
                threading.Event().wait(0.02)
            b = threading.Thread(target=depositar)
            b.start()
            a.join(timeout=30)
            b.join(timeout=30)
        finally:
            main._repair_monthly_chain = real

        conn = main.get_db()
        dic = conn.execute(
            "SELECT capital_inicio, deposits FROM monthly_entries "
            "WHERE user_id=? AND broker=? AND year=2025 AND month=12",
            (self.uid, self.BROKER)).fetchone()
        conn.close()
        print(f"\n>>> mes borrado + depósito: diciembre={dict(dic) if dic else None} err={errores}")
        self.assertEqual(errores, [])
        self.assertIsNotNone(dic, "el depósito de diciembre no quedó")
        self.assertAlmostEqual(float(dic["capital_inicio"] or 0), 0.0, places=2,
                               msg="diciembre heredó el capital del mes que se estaba borrando")


if __name__ == "__main__":
    unittest.main()
