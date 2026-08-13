"""Referencias ambiguas adentro de `ON CONFLICT … DO UPDATE SET`.

LA CATEGORÍA. Adentro de un DO UPDATE SET hay DOS filas a la vista: la que ya
estaba en la tabla y la que se quiso insertar (`excluded`). Una referencia PELADA
no dice cuál es. SQLite elige la de la tabla y sigue; **Postgres corta** con
`column reference "x" is ambiguous`.

    last_fired_date = COALESCE(excluded.last_fired_date, last_fired_date)
    count           = count + 1

POR QUÉ ES DE LAS PEORES. Los sitios que la usan suelen estar adentro de un
`try/except Exception` que loguea y sigue (advisor_alerts.py, main.py). En
Postgres eso NO sale como error: sale como "la alerta del asesor no se mandó" o
"el contador de IA no subió". Número equivocado, no pantalla de error — y no lo
agarra ningún test que mire el resultado de la función, sólo el log.

Fue la QUINTA categoría que no estaba en el plan de la migración (después de
fechas con modificador, MIN/MAX de dos argumentos, placeholders con nombre y
fechas mal formadas). Por eso el shim la detecta: para que no se cuele una nueva.
"""
import unittest

from pgshim import _columnas_ambiguas, traducir


class DetectaAmbiguasTest(unittest.TestCase):
    def _es_ambigua(self, sql):
        return bool(_columnas_ambiguas(sql))

    # ── las que TIENEN que saltar ────────────────────────────────────────────
    def test_coalesce_con_la_columna_pelada(self):
        """El caso real de advisor_alerts.py, que dejaba de mandar alertas."""
        self.assertTrue(self._es_ambigua(
            "INSERT INTO advisor_alert_state (advisor_uid, client_uid, armed, last_fired_date) "
            "VALUES (?,?,?,?) ON CONFLICT(advisor_uid, client_uid) DO UPDATE SET "
            "armed=excluded.armed, "
            "last_fired_date=COALESCE(excluded.last_fired_date, last_fired_date)"))

    def test_contador_que_se_suma_a_si_mismo(self):
        """El caso real de ai/quota.py y main.py: `count = count + 1`."""
        self.assertTrue(self._es_ambigua(
            "INSERT INTO ai_tool_usage (user_id, date, count) VALUES (?,?,1) "
            "ON CONFLICT(user_id, date) DO UPDATE SET count = count + 1"))

    def test_el_mensaje_dice_qué_columna_y_cómo_arreglarlo(self):
        with self.assertRaises(NotImplementedError) as ctx:
            traducir("INSERT INTO t (a, count) VALUES (?,?) "
                     "ON CONFLICT(a) DO UPDATE SET count = count + 1")
        msg = str(ctx.exception)
        self.assertIn("count", msg)
        self.assertIn("ambigua", msg.lower())
        self.assertIn("Calificala", msg)

    # ── las que NO tienen que saltar (los falsos positivos que romperían todo) ─
    def test_calificada_con_la_tabla_esta_bien(self):
        self.assertFalse(self._es_ambigua(
            "INSERT INTO advisor_alert_state (advisor_uid, client_uid, armed, last_fired_date) "
            "VALUES (?,?,?,?) ON CONFLICT(advisor_uid, client_uid) DO UPDATE SET "
            "armed=excluded.armed, last_fired_date=COALESCE(excluded.last_fired_date, "
            "advisor_alert_state.last_fired_date)"))

    def test_solo_excluded_esta_bien(self):
        self.assertFalse(self._es_ambigua(
            "INSERT INTO t (a,b) VALUES (?,?) ON CONFLICT(a) DO UPDATE SET b=excluded.b"))

    def test_un_update_comun_no_es_ambiguo(self):
        """Afuera de un DO UPDATE SET hay UNA sola fila a la vista: no hay ambigüedad.
        Marcarlo rompería medio backend."""
        self.assertFalse(self._es_ambigua("UPDATE ai_usage_daily SET chat_count = chat_count + 1 WHERE user_id=?"))

    def test_una_funcion_no_es_una_columna(self):
        self.assertFalse(self._es_ambigua(
            "INSERT INTO t (a,b) VALUES (?,?) ON CONFLICT(a) DO UPDATE SET "
            "b=excluded.b, fetched_at=datetime('now')"))

    def test_el_where_del_do_update_no_cuenta(self):
        """El WHERE va DESPUÉS del SET y puede traer subconsultas con su propio FROM:
        una columna de ahí resuelve contra ESE from, no contra la tabla del conflicto."""
        self.assertFalse(self._es_ambigua(
            "INSERT INTO ai_usage_daily (user_id, date, chat_count) VALUES (?,?,1) "
            "ON CONFLICT(user_id, date) DO UPDATE SET chat_count = ai_usage_daily.chat_count + 1 "
            "WHERE (SELECT COALESCE(SUM(chat_count),0) FROM ai_usage_daily "
            "WHERE user_id = ? AND date >= ?) < ?"))

    def test_el_backfill_de_fx_que_ya_convertimos_sigue_limpio(self):
        import main
        self.assertFalse(self._es_ambigua(main.SQL_BACKFILL_FX_BLUE))


class NingunSitioDelBackendQuedaAmbiguoTest(unittest.TestCase):
    """Guardarraíl de repo: barre TODO el backend y falla si alguien agrega una.

    El shim ya la rechaza en tiempo de ejecución, pero eso sólo se ve si un test
    pasa por esa línea. Esto la encuentra aunque nadie la ejecute — que es
    justamente el caso de los sitios metidos adentro de un try/except.
    """

    def test_no_hay_referencias_ambiguas_en_el_backend(self):
        import ast
        import os
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Este archivo se excluye a sí mismo: sus fixtures son SQL ambiguo A
        # PROPÓSITO (y hasta el docstring de arriba trae los dos ejemplos).
        yo = os.path.basename(__file__)
        malas = []
        for base, _, archivos in os.walk(raiz):
            if any(x in base for x in (os.sep + ".", "node_modules", "__pycache__")):
                continue
            for nombre in archivos:
                if not nombre.endswith(".py") or nombre in ("pgshim.py", yo):
                    continue
                ruta = os.path.join(base, nombre)
                try:
                    arbol = ast.parse(open(ruta, encoding="utf-8", errors="ignore").read())
                except SyntaxError:
                    continue
                for n in ast.walk(arbol):
                    if not (isinstance(n, ast.Constant) and isinstance(n.value, str)):
                        continue
                    if "do update set" not in n.value.lower():
                        continue
                    amb = _columnas_ambiguas(n.value)
                    if amb:
                        rel = os.path.relpath(ruta, raiz)
                        malas.append(f"{rel}:{n.lineno} -> {sorted(set(amb))}")
        self.assertEqual(malas, [], "referencias ambiguas nuevas (SQLite las acepta, "
                                    "Postgres las rechaza y el error se puede tragar "
                                    "un try/except):\n  " + "\n  ".join(malas))


if __name__ == "__main__":
    unittest.main()
