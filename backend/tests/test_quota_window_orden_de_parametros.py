"""El día de la cuota tiene que caer en SU columna, en los SEIS sitios.

POR QUÉ EXISTE (auditoría 23/10/2026). Seis `UPDATE users` de cobros pasaron de
escribir el día dentro del SQL (`date('now','localtime')`, que el shim de
Postgres rechaza) a recibirlo como parámetro. Eso cambia el riesgo de lugar:

  · Antes: la sentencia se rechazaba y el `tier = ?` de la MISMA sentencia se
    caía con ella — el usuario no cambiaba de plan. Ruidoso.
  · Ahora: si los valores viajan en otro orden, la base guarda el día en la
    columna del plan y el plan en la del día **sin dar ningún error**. Silencioso.

Y no había quién lo vigilara: el único test que compara `quota_window_from`
contra hoy (`test_quota_window_corte.py`) cubre el cron de vencimiento, que es
otro camino. `admin_billing_grant_comp` —el de más columnas, y por eso el de más
riesgo— no tenía NINGÚN test.

Este guard no corre los seis caminos (dos son webhooks y dos son endpoints de
admin): lee el código. Para cada `conn.execute(SQL, params)` que escriba
`quota_window_from`, cuenta los `?` hasta el de esa columna y mira qué expresión
le toca. Es un guard por TEXTO y tiene el punto ciego de siempre: no ve un orden
armado en runtime (un `sets.append()` como el de `_update_monthly_flow`). Para
esos hay un chequeo aparte abajo, que exige que no existan.
"""
import ast
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)

ARCHIVOS = ("main.py", "billing/credits.py", "billing/trial.py", "ai/quota.py",
            "billing/subscriptions.py")

# El día lo tiene que poner UNA función. Si alguien vuelve a escribir un reloj
# suelto acá, este nombre deja de aparecer y el test lo dice.
FUENTE_DEL_DIA = "dia_de_la_cuota"


def _sql_y_params(nodo):
    """(sql, lista de params) de un `algo.execute(SQL_literal, tupla_literal)`,
    o None si no tiene esa forma."""
    if not isinstance(nodo, ast.Call) or not isinstance(nodo.func, ast.Attribute):
        return None
    if nodo.func.attr not in ("execute", "executemany"):
        return None
    if not nodo.args or not isinstance(nodo.args[0], ast.Constant):
        return None
    sql = nodo.args[0].value
    if not isinstance(sql, str):
        return None
    params = None
    if len(nodo.args) > 1 and isinstance(nodo.args[1], (ast.Tuple, ast.List)):
        params = list(nodo.args[1].elts)
    return sql, params


def _indice_del_placeholder(sql, columna):
    """En qué posición (0-based) viaja el `?` de `columna = ?` contando TODOS los
    `?` de la sentencia de izquierda a derecha. None si la columna no se escribe
    con parámetro."""
    m = re.search(rf"\b{columna}\s*=\s*\?", sql)
    if not m:
        return None
    return sql.count("?", 0, m.start())


def _recolectar():
    hallados = []
    for rel in ARCHIVOS:
        ruta = os.path.join(BACKEND, rel)
        if not os.path.exists(ruta):
            continue
        fuente = open(ruta, encoding="utf-8").read()
        arbol = ast.parse(fuente)
        for nodo in ast.walk(arbol):
            par = _sql_y_params(nodo)
            if not par:
                continue
            sql, params = par
            if "quota_window_from" not in sql:
                continue
            if not re.search(r"\bUPDATE\s+users\b", sql, re.I):
                continue
            hallados.append((rel, nodo.lineno, sql, params))
    return hallados


class ElDiaCaeEnSuColumna(unittest.TestCase):
    def setUp(self):
        self.sitios = _recolectar()

    def test_los_encontre_a_todos(self):
        """Si este número BAJA, alguien borró un sitio o lo armó en runtime (y
        entonces el guard dejó de verlo). Si SUBE, hay un sitio nuevo: miralo."""
        self.assertGreaterEqual(
            len(self.sitios), 7,
            "esperaba al menos 7 `UPDATE users … quota_window_from` con SQL "
            f"literal y encontré {len(self.sitios)}: "
            + ", ".join(f"{a}:{l}" for a, l, _, _ in self.sitios))

    def test_la_cantidad_de_parametros_coincide(self):
        """Una consulta que pide N y recibe N−1 revienta en producción."""
        malos = []
        for rel, linea, sql, params in self.sitios:
            if params is None:
                continue
            if sql.count("?") != len(params):
                malos.append(f"{rel}:{linea} pide {sql.count('?')} y recibe {len(params)}")
        self.assertEqual(malos, [], "\n".join(malos))

    def test_el_dia_viaja_en_la_posicion_del_dia(self):
        """El `?` de `quota_window_from` tiene que recibir el día, no el plan.

        Es el único error de esta familia que NO da error: la base acepta un
        plan en la columna de la fecha y una fecha en la del plan."""
        malos = []
        for rel, linea, sql, params in self.sitios:
            idx = _indice_del_placeholder(sql, "quota_window_from")
            if idx is None or params is None:
                continue
            if idx >= len(params):
                malos.append(f"{rel}:{linea} el día iría en la posición {idx} "
                             f"y sólo hay {len(params)} valores")
                continue
            expr = ast.unparse(params[idx])
            if FUENTE_DEL_DIA not in expr and "date.today" not in expr \
                    and "datetime.now" not in expr:
                malos.append(
                    f"{rel}:{linea} en la posición de `quota_window_from` "
                    f"viaja {expr!r} — ¿se cruzó con otra columna?")
        self.assertEqual(malos, [], "\n".join(malos))

    def test_el_plan_viaja_en_la_posicion_del_plan(self):
        """La otra mitad del cruce: si el día se corriera al lugar del `tier`,
        el usuario quedaría con el plan '2026-10-23'."""
        malos = []
        for rel, linea, sql, params in self.sitios:
            idx = _indice_del_placeholder(sql, "tier")
            if idx is None or params is None or idx >= len(params):
                continue
            expr = ast.unparse(params[idx])
            if FUENTE_DEL_DIA in expr or "date.today" in expr:
                malos.append(f"{rel}:{linea} en la posición de `tier` viaja el "
                             f"DÍA ({expr!r})")
        self.assertEqual(malos, [], "\n".join(malos))

    def test_nadie_volvio_a_meter_el_reloj_adentro_del_SQL(self):
        """`date('now', …)` con modificador lo rechaza el shim, y se cae con él
        el `tier = ?` de la misma sentencia: el usuario no cambia de plan."""
        malos = []
        for rel, linea, sql, _ in self.sitios:
            if re.search(r"date\s*\(\s*'now'\s*,", sql):
                malos.append(f"{rel}:{linea}")
        self.assertEqual(
            malos, [],
            "el día volvió a calcularse dentro del SQL en: " + ", ".join(malos))

    def test_el_dia_sale_de_un_solo_lugar(self):
        """La función existe para que el día se calcule en UN lugar. Un reloj
        suelto en estos sitios la vuelve decorativa."""
        sueltos = []
        for rel, linea, sql, params in self.sitios:
            idx = _indice_del_placeholder(sql, "quota_window_from")
            if idx is None or params is None or idx >= len(params):
                continue
            expr = ast.unparse(params[idx])
            if FUENTE_DEL_DIA not in expr:
                sueltos.append(f"{rel}:{linea} usa {expr!r} en vez de "
                               f"`{FUENTE_DEL_DIA}()`")
        # Al 23/10/2026 queda UNO: el paso a Plus del trial (billing/trial.py),
        # que ya recibía el día como parámetro y por eso no entró en la tanda.
        # Si este número SUBE, apareció otra copia; si BAJA, bajalo acá.
        self.assertLessEqual(
            len(sueltos), 1,
            "más copias del día de las esperadas:\n" + "\n".join(sueltos))


class ElDiaDeLaCuotaNoCambio(unittest.TestCase):
    """`dia_de_la_cuota()` tiene que devolver LO MISMO que devolvía el SQL que
    reemplazó: el día del reloj del proceso, no el día argentino. Mover el
    bloque de cuota al día argentino es una decisión de producto pendiente."""

    def test_devuelve_el_dia_del_proceso(self):
        if BACKEND not in sys.path:
            sys.path.insert(0, BACKEND)
        from datetime import date
        from ai import quota
        self.assertEqual(quota.dia_de_la_cuota(), date.today().isoformat())

    def test_tiene_forma_de_fecha(self):
        if BACKEND not in sys.path:
            sys.path.insert(0, BACKEND)
        from ai import quota
        self.assertRegex(quota.dia_de_la_cuota(), r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
