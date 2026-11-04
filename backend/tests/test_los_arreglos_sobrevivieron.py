"""Los seis arreglos de concurrencia siguen puestos. Guardián del MERGE.

🔴 POR QUÉ EXISTE, y es la historia de este repo más que de esta tanda.

Esta rama trae seis arreglos de concurrencia y quedó 48 commits atrás de lo
publicado, con 8 de esos commits tocando `main.py`, que es donde viven tres de
los seis. **Un merge sin conflictos igual te pisa un arreglo** — está medido en
este proyecto y pasó más de una vez: el merge resuelve texto, no intención, y
cuando dos ramas reescribieron la misma zona por motivos distintos, git elige
una sin avisar.

Lo que este archivo NO es: un test de que los arreglos funcionen. Para eso están
`test_auditoria_pg_carrera.py`, `test_caja_una_sola_puerta.py`,
`test_tope_sin_tope.py` y `test_turno_por_la_conexion.py`, que miden el
comportamiento. Esto es más barato y más tonto a propósito: comprueba que las
PIEZAS sigan en su lugar, para que si un merge se lleva una, el rojo diga
exactamente cuál y no haya que deducirlo de un test de concurrencia que falla
por quince motivos posibles.

⚠️ **Se corrió ANTES del merge y dio verde.** Eso importa: un verificador
escrito después de la operación que quiere vigilar no distingue «el merge lo
pisó» de «el verificador está mal». Éste tiene su verde de referencia.

Es un guardián por TEXTO y tiene los puntos ciegos de los guardianes por texto
(no ve si una función cambió de significado, sólo si su forma sigue ahí). Está
bien que sea así: para el significado están los otros cuatro archivos.
"""
import io
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)


def _codigo(*partes):
    with io.open(os.path.join(BACKEND, *partes), encoding="utf-8") as f:
        return f.read()


def _codigo_sin_comentarios(*partes):
    """El código SIN comentarios ni textos, reusando el quitador del repo.

    🔴 HACE FALTA, y lo descubrí con este archivo en rojo antes del merge: el
    control de que no vuelva el `? IS NULL OR` se disparaba con MI PROPIO
    COMENTARIO, el que explica por qué ese patrón no se puede usar. Un guardián
    por texto que lee los comentarios encuentra el bug en su propia
    documentación. Es el punto ciego que este repo ya tiene anotado, y
    `test_un_solo_calendario.py` ya tenía la solución escrita.
    """
    from tests.test_un_solo_calendario import _sin_comentarios_ni_textos
    return _sin_comentarios_ni_textos(_codigo(*partes))


class LosSeisArreglosSiguenPuestos(unittest.TestCase):

    # ── 1 · Los cuatro topes de IA, unificados en UNO ────────────────────────
    def test_1_las_cuatro_reservas_de_cuota_van_por_un_solo_lugar(self):
        t = _codigo("ai", "quota.py")
        self.assertIn("def _reservar_un_slot(", t,
                      "desapareció el helper único de las reservas de cuota")
        for columna in ("chat_count", "analyses_count",
                        "listen_count", "diag_dismiss_count"):
            self.assertIn(f'_reservar_un_slot(conn, user_id, "{columna}"', t,
                          f"la reserva de {columna} dejó de ir por el helper: "
                          "¿volvió la copia de la sentencia?")
        # Y que no haya vuelto a aparecer la sentencia copiada. Lo que define a
        # una RESERVA no es el INSERT —hay 6 que escriben esa tabla, los
        # `record_*` legados entre ellos— sino el chequeo del tope adentro:
        # `WHERE (SELECT COALESCE(SUM(...)) ...) < ?`. Ésa es la que tiene que
        # existir UNA sola vez.
        copias = len(re.findall(r"WHERE \(SELECT COALESCE\(SUM\(", t))
        self.assertEqual(
            copias, 2,
            f"hay {copias} chequeos de tope en las reservas y tienen que haber 2 "
            "(los dos de la MISMA sentencia de `_reservar_un_slot`: el del INSERT "
            "y el del DO UPDATE). Si hay más, volvieron las copias")

    def test_1b_el_helper_pide_el_turno_antes_de_contar(self):
        t = _codigo("ai", "quota.py")
        cuerpo = t[t.index("def _reservar_un_slot("):]
        cuerpo = cuerpo[:cuerpo.index("\ndef ", 10)]
        turno = cuerpo.index("TURNO_CUOTA_IA_POR_USUARIO")
        insert = cuerpo.index("INSERT INTO ai_usage_daily")
        self.assertLess(turno, insert,
                        "el turno quedó DESPUÉS de la sentencia que cuenta: "
                        "así no protege nada")

    # ── 2 · Los dos topes del plan: la regla en el INSERT + el turno ─────────
    def test_2_la_condicion_de_tope_vive_en_un_solo_lugar(self):
        t = _codigo("ai", "plan.py")
        self.assertIn("def condicion_de_tope(", t)
        self.assertIn("SQL_BROKERS_QUE_CUENTAN", t,
                      "se perdió la definición única de «qué cuenta como cuenta»")
        self.assertIn("_turno_del_tope(conn, user_id)", t,
                      "los chequeos del plan dejaron de pedir el turno")

    def test_2b_el_sin_tope_se_decide_en_python_y_no_en_sql(self):
        """Dos controles y CADA UNO sobre una versión distinta del archivo.

        El quitador del repo reemplaza comentarios **y textos entre comillas**
        por espacios, así que `return ("1=1", ())` queda `return (     , ())`:
        buscar un literal ahí no puede funcionar nunca. Y al revés, buscar un
        patrón de SQL en el crudo lo encuentra en los comentarios.

        · lo que TIENE que estar (un literal)  → sobre el crudo
        · lo que NO puede estar (un patrón)    → sobre el limpio
        """
        self.assertIn('return ("1=1", ())', _codigo("ai", "plan.py"),
                      "volvió a preguntarle a SQL si el tope está vacío: eso "
                      "revienta en Postgres para TODOS los que pagan")
        self.assertNotRegex(
            _codigo_sin_comentarios("ai", "plan.py"), r"\?\s+IS\s+NULL\s+OR",
            "reapareció el `? IS NULL OR` que voltea a los planes sin tope")

    def test_2c_los_dos_endpoints_hacen_cumplir_el_tope_en_el_INSERT(self):
        t = _codigo("main.py")
        self.assertIn('condicion_de_tope("brokers"', t,
                      "el endpoint de brokers dejó de hacer cumplir el tope en el INSERT")
        self.assertIn('condicion_de_tope("alerts"', t,
                      "el endpoint de alertas dejó de hacer cumplir el tope en el INSERT")
        # Y que el INSERT siga siendo condicional, no un VALUES pelado.
        self.assertRegex(
            t, r"INSERT INTO brokers[^;]*?SELECT \?,\?,\?,\? WHERE",
            "el INSERT de brokers volvió a ser incondicional")

    # ── 3 · El turno se decide por la CONEXIÓN ───────────────────────────────
    def test_3_el_turno_mira_la_conexion_en_tres_pasos(self):
        t = _codigo("pgsesion.py")
        self.assertIn("def habla_postgres(", t)
        self.assertIn("if not habla_postgres(conn):", t,
                      "`turno_exclusivo` volvió a decidir por la bandera del proceso")
        self.assertIn("total_changes", t,
                      "se perdió el paso que reconoce SQLite A TRAVÉS de un "
                      "envoltorio: sin eso, un envoltorio pierde el candado")
        self.assertIn('callable(getattr(conn, "execute", None))', t,
                      "se perdió el control de que el objeto parezca una conexión")

    def test_3b_las_claves_del_turno_no_se_arman_sumando(self):
        t = _codigo("main.py")
        self.assertNotIn("TURNO_TOPE_FACTS_POR_USUARIO + ", t,
                         "volvió la clave armada sumando el uid: para el usuario 1 "
                         "choca con la clave de la caja")
        self.assertIn("TURNO_TOPE_FACTS_POR_USUARIO, int(uid)", t,
                      "el turno de los facts dejó de usar la forma de dos claves")

    # ── 4 · La caja: el turno siempre y primero, y una sola puerta ───────────
    def test_4_leer_la_caja_pide_el_turno(self):
        t = _codigo("efectivo.py")
        cuerpo = t[t.index("def caja("):]
        cuerpo = cuerpo[:cuerpo.index("\ndef ", 10)]
        self.assertIn("tomar_saldo(conn, uid, broker)", cuerpo,
                      "`caja()` dejó de pedir el turno: el que decide con ese "
                      "saldo puede estar leyendo un número que otro ya cambió")

    def test_4b_el_turno_de_la_caja_va_antes_del_UPDATE(self):
        t = _codigo("efectivo.py")
        cuerpo = t[t.index("def tomar_saldo("):]
        cuerpo = cuerpo[:cuerpo.index("\ndef ", 10)]
        turno = cuerpo.index("TURNO_CAJA_DEL_BROKER")
        update = cuerpo.index("UPDATE positions")
        self.assertLess(
            turno, update,
            "el turno volvió a quedar después del UPDATE (o dentro de su `if`): "
            "así el orden de candados se vuelve variable y aparece el bloqueo mutuo")
        self.assertNotIn(
            "rowcount", cuerpo,
            "el turno volvió a estar condicionado al rowcount del UPDATE")

    def test_4c_crear_la_caja_tiene_una_sola_puerta(self):
        self.assertIn("def asegurar_caja(", _codigo("efectivo.py"))
        p = _codigo("importing", "persister.py")
        self.assertIn("_efectivo.asegurar_caja(", p,
                      "el importador volvió a crear la caja por su cuenta")
        for m in re.finditer(r"INSERT\s+INTO\s+positions[^;]{0,400}", p, re.I | re.S):
            self.assertNotRegex(
                m.group(0), r"is_cash[^)]*\)\s*\n?\s*VALUES\s*\([^)]*,\s*1\b",
                "el importador volvió a insertar una fila de caja por su cuenta")

    # ── 5 · La fila del mes: el ON CONFLICT que suma ─────────────────────────
    def test_5_la_fila_del_mes_tiene_su_ON_CONFLICT(self):
        t = _codigo("main.py")
        cuerpo = t[t.index("def _update_monthly_flow("):]
        cuerpo = cuerpo[:cuerpo.index("\ndef ", 10)]
        self.assertIn("ON CONFLICT (user_id, year, month, broker) DO UPDATE SET", cuerpo,
                      "se perdió el ON CONFLICT de la fila del mes: vuelve el 500 "
                      "al usuario cuando dos pedidos abren el mes a la vez")
        # Tolerante a los espacios de alineación del SQL real
        # (`deposits    = monthly_entries.deposits    + EXCLUDED.deposits`).
        self.assertRegex(
            cuerpo, r"monthly_entries\.deposits\s+\+\s+EXCLUDED\.deposits",
            "el ON CONFLICT dejó de SUMAR los depósitos")

    # ── 6 · El día de la cuota, en un solo lugar ─────────────────────────────
    def test_6_el_dia_de_la_cuota_sale_de_una_sola_funcion(self):
        self.assertIn("def dia_de_la_cuota(", _codigo("ai", "quota.py"))
        self.assertIn("_q.dia_de_la_cuota()", _codigo("billing", "trial.py"),
                      "el paso a Plus volvió a calcular el día por su cuenta")
        # Ningún escritor de producción puede calcularlo suelto.
        sueltos = []
        for raiz, dirs, files in os.walk(BACKEND):
            dirs[:] = [d for d in dirs
                       if d not in ("tests", "__pycache__", "venv", ".venv", "backups")]
            for f in files:
                if not f.endswith(".py"):
                    continue
                ruta = os.path.join(raiz, f)
                t = _codigo(os.path.relpath(ruta, BACKEND))
                for m in re.finditer(r"quota_window_from\s*=\s*\?", t):
                    # la llamada tiene que estar en las ~12 líneas siguientes
                    ventana = t[m.end():m.end() + 700]
                    if "dia_de_la_cuota()" not in ventana:
                        sueltos.append(os.path.relpath(ruta, BACKEND))
        self.assertEqual(
            sueltos, [],
            f"estos escriben el día de la cuota sin pedirlo a la función única: {sueltos}")


if __name__ == "__main__":
    unittest.main()
