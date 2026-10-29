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

PIDE_TURNO = re.compile(r"\b_tomar_turno(_de_la_puerta)?\(")

# Lo que falta, con el motivo. Sólo puede achicarse (ver el docstring del módulo).
PENDIENTES = {
    "init_db": "el arranque: corre antes de atender pedidos, sin usuario",
    "admin_recompute_snapshots_netdep": "admin: recorre usuarios",
    "admin_repair_user_history": "admin: repara la historia de un usuario ajeno",
    "admin_repair_snapshots_all": "admin: recorre todos los usuarios",
    "admin_cleanup_future_snapshots": "admin: recorre usuarios",
    "admin_repair_comisiones": "admin: recorre usuarios",
    "admin_repair_caja_1415": "admin: recorre usuarios",
    "admin_repair_interes_pf": "admin: recorre usuarios",
    "admin_delete_snapshot": "admin: borra la foto de un usuario ajeno",
    "admin_wipe_broker_data": "admin: limpia el broker de un usuario ajeno",
    "_migrate_snapshots_netdep": "migración: recorre usuarios",
    "_reconstruir_mtm": "sale a Yahoo durante minutos; se protege con su huella (backfill_user)",
    "advisor_tanda_revert": "asesor: escribe en las cuentas de varios clientes",
    "_advisor_group_op_apply": "asesor: escribe en las cuentas de varios clientes",
    "advisor_group_op_undo": "asesor: escribe en las cuentas de varios clientes",
}


def _duenos_de_conexion_sin_turno():
    """Las funciones de main.py que abren una conexión (`get_db()` /
    `db_abierta()`) y escriben con ELLA —en su cuerpo o en lo que llaman sin abrir
    otra— alguna tabla de la plata, sin pedir el turno en su propio cuerpo."""
    src = open(os.path.join(BACKEND, "main.py"), encoding="utf-8").read()
    lineas = src.splitlines()
    arbol = ast.parse(src)
    top = {n.name: n for n in arbol.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    cuerpo = {k: "\n".join(lineas[v.lineno - 1:v.end_lineno]) for k, v in top.items()}
    escritura = re.compile(r"(INSERT INTO|UPDATE|DELETE FROM)\s+(\w+)")
    escribe = {k: {m.group(2) for m in escritura.finditer(s)} & set(TABLAS_DE_LA_PLATA)
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
                if y not in vistos and y not in duenos:   # otro dueño = otra conexión
                    vistos.add(y)
                    cola.append(y)
        return vistos

    faltan = {}
    for k in duenos:
        tablas = set().union(*(escribe[x] for x in con_su_conexion(k)))
        if tablas and not PIDE_TURNO.search(cuerpo[k]):
            faltan[k] = f"{k} (main.py:{top[k].lineno}) escribe {sorted(tablas)}"
    return faltan


class ElCensoDeLasPuertas(unittest.TestCase):

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
