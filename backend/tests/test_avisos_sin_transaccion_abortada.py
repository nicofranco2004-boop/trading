"""Guardián (auditoría C1, 29/10): en los motores de avisos, un `except` que
sigue con la próxima vuelta tiene que deshacer lo suyo.

La forma: `for … : try: <usa la base> except: log; continue`. En SQLite anda
(una sentencia que falla no deja secuela). En Postgres un error de base deja la
transacción ENTERA abortada: la vuelta siguiente revienta en su primera
consulta, y el commit de después es un ROLLBACK callado que se lleva lo de las
vueltas sanas: una alerta rota hacía que OTRA mandara el mismo mail cada 10
minutos (medido en la auditoría C1, 29/10), y una alerta de
precio rota cortaba la pasada entera (B-P1).

El guardián de la migración (`test_plan_b_tiene_punto_de_guardado`) busca SQL
adentro del `except`; ésta es la otra cara (el `except` no habla con la base,
habla la vuelta siguiente) y no la veía. Este barre los archivos de avisos y
pide, para cada `try` adentro de un `for` que usa `conn` y cuyo `except` no
corta (raise/return): un punto de guardado en el `try`
(`si_falla_se_deshace_solo_esto`, o `_guarda_por_alerta` que lo usa) o un
`rollback()` en el `except`.

Alcance: los motores de avisos (lo de esta ronda). El censo grueso de la
auditoría C marca ~45 sitios más con la misma forma en el resto del backend
(muchos falsos): no se revisaron uno por uno, quedan anotados.
"""
import ast
import os
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVOS = ("alerts_engine.py", "advisor_alerts.py")
GUARDAS = ("si_falla_se_deshace_solo_esto", "_guarda_por_alerta")


def _usa_conn(nodos) -> bool:
    return any(isinstance(m, ast.Name) and m.id == "conn" for n in nodos for m in ast.walk(n))


def _llama(nodos, nombres) -> bool:
    for n in nodos:
        for m in ast.walk(n):
            if isinstance(m, ast.Call):
                f = m.func
                nombre = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if nombre in nombres:
                    return True
    return False


def sitios_sin_guarda(fuente: str, archivo: str) -> list:
    out = []
    for bucle in ast.walk(ast.parse(fuente)):
        if not isinstance(bucle, (ast.For, ast.While)):
            continue
        for t in [n for n in ast.walk(bucle) if isinstance(n, ast.Try)]:
            if not _usa_conn(t.body):
                continue
            for h in t.handlers:
                if any(isinstance(x, (ast.Raise, ast.Return)) for x in h.body):
                    continue
                # (un `try: conn.rollback()` es el propio deshacer)
                if _llama(t.body, GUARDAS + ("rollback",)) or _llama(h.body, ("rollback",)):
                    continue
                out.append(f"{archivo}:{t.lineno}")
    return sorted(set(out))


class AvisosSinTransaccionAbortadaTest(unittest.TestCase):

    def test_ningun_except_sigue_de_largo_sin_deshacer_lo_suyo(self):
        malos = []
        for a in ARCHIVOS:
            with open(os.path.join(BACKEND, a), encoding="utf-8") as f:
                malos += sitios_sin_guarda(f.read(), a)
        self.assertEqual(malos, [], "un except que sigue con la próxima vuelta sin punto de guardado "
                                    "ni rollback: en Postgres la vuelta siguiente corre sobre la "
                                    "transacción abortada (ver el docstring)")

    def test_el_guardian_ve_la_forma(self):
        """Que no esté ciego: la forma de antes del arreglo la marca."""
        viejo = '''
def evaluar(conn, alerts):
    for a in alerts:
        try:
            r = _una(conn, a)
        except Exception as ex:
            log.error("x %s", ex)
            continue
'''
        self.assertEqual(sitios_sin_guarda(viejo, "x.py"), ["x.py:4"])
        bien = viejo.replace("r = _una(conn, a)", "r = _guarda_por_alerta(conn, a)")
        self.assertEqual(sitios_sin_guarda(bien, "x.py"), [])


if __name__ == "__main__":
    unittest.main()
