"""Guardián (re-test de la auditoría B, 29/10): los avisos mandan por UNA puerta.

Decisión de Nico: un aviso que no sale no se reintenta, pero queda en el
registro con la persona y el motivo. Se aplicó primero sólo al resumen del
sábado; el re-test encontró el mismo hueco en las alertas y en el libro del
asesor, porque cada lugar que mandaba decidía qué anotar. Ahora todos mandan
por `alerts_engine.enviar`, que anota lo que no sale.

Este guardián barre el backend con AST y pide que `_send_push_to_user(` y
`send_alert_email(` se llamen SÓLO desde `alerts_engine.enviar`, salvo las
excepciones de abajo, cada una con su motivo. Un aviso nuevo que mande por su
cuenta da rojo (y así tampoco puede saltearse `entrega`, que arma el destino).
"""
import ast
import os
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENVIOS = ("_send_push_to_user", "send_alert_email")
PUERTA = ("alerts_engine.py", "enviar")

# (archivo, función que llama): por qué no pasa por `enviar`.
EXCEPCIONES = {
    ("main.py", "push_test"): "el botón «probar notificaciones»: la respuesta le muestra a la persona a cuántos "
                              "dispositivos llegó; no es un aviso",
    ("market_brief.py", "avisar_por_push"): "el push del resumen del mercado se intenta para todos los "
                                            "suscriptos, hayan elegido notificaciones o no: 0 dispositivos es lo "
                                            "normal, no una falla. Su mail tiene su propio registro "
                                            "(market_brief_log)",
}


def llamadas_a_envios(fuente: str, archivo: str) -> set:
    """{(archivo, función que contiene la llamada)} de cada envío directo."""
    out = set()
    arbol = ast.parse(fuente)
    for fn in ast.walk(arbol):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call):
                f = n.func
                nombre = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if nombre in ENVIOS:
                    out.add((archivo, fn.name))
    return out


def _fuentes():
    for raiz, dirs, archivos in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in ("tests", "scripts", "__pycache__", "node_modules")]
        for a in archivos:
            if a.endswith(".py"):
                ruta = os.path.join(raiz, a)
                with open(ruta, encoding="utf-8") as f:
                    yield os.path.relpath(ruta, BACKEND), f.read()


class AvisosPorUnaPuertaTest(unittest.TestCase):

    def test_solo_enviar_manda(self):
        sitios = set()
        for archivo, fuente in _fuentes():
            sitios |= llamadas_a_envios(fuente, archivo)
        # Las definiciones mismas no son llamadas, pero `_send_push_to_user` se
        # llama a sí misma en ningún lado: si apareciera, se ve acá.
        fuera = sorted(s for s in sitios if s != PUERTA and s not in EXCEPCIONES)
        self.assertEqual(fuera, [], "un aviso manda por su cuenta: pasalo por alerts_engine.enviar "
                                    "(o, si de verdad no es un aviso, sumalo a EXCEPCIONES con su motivo)")
        self.assertIn(PUERTA, sitios, "la puerta tiene que seguir mandando")

    def test_las_excepciones_siguen_existiendo(self):
        """Que la lista no se vuelva un cementerio: una excepción que ya no
        manda se borra de la lista."""
        sitios = set()
        for archivo, fuente in _fuentes():
            sitios |= llamadas_a_envios(fuente, archivo)
        self.assertEqual(sorted(e for e in EXCEPCIONES if e not in sitios), [])

    def test_el_guardian_ve_la_forma(self):
        viejo = '''
def _deliver(conn, uid, channel, title, items):
    import main
    from billing import emails
    main._send_push_to_user(uid, {"title": title})
    emails.send_alert_email(to="x", heading="h", detail="d")
'''
        self.assertEqual(llamadas_a_envios(viejo, "advisor_alerts.py"), {("advisor_alerts.py", "_deliver")})


if __name__ == "__main__":
    unittest.main()
