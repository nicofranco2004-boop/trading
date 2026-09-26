"""La IA de Rendi se llama Rendi AI: el nombre viejo ("Coach IA") no vuelve.

Del lado del servidor salen textos que la persona lee tal cual: la lista de
beneficios de la tarjeta de "llegaste al límite", los avisos de "está tardando
más de lo normal" del chat y la nota que queda en una compra registrada por
chat. Esos decían "Coach IA" cuando el producto ya se llamaba Rendi AI en el
catálogo, la FAQ y la guía.

Se leen los STRINGS del código con `ast`, no el archivo como texto: así los
comentarios y los docstrings —que sí pueden contar la historia— no cuentan, y
un string partido en varias líneas o armado con f-string sí.

El mismo guard del lado del frontend: `frontend/src/data/nombreDeLaIA.test.js`.

Corre con: cd backend && python3 -m pytest tests/test_nombre_de_la_ia.py
"""
import ast
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)

NOMBRE_VIEJO = re.compile(r"coach\s+(de\s+)?ia\b", re.I)
# Los tests citan el texto viejo a propósito; los scripts no llegan a nadie.
NO_SE_LEEN = {"tests", "scripts", "__pycache__", "node_modules", "venv"}


def _modulos():
    for raiz, dirs, archivos in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in NO_SE_LEEN and not d.startswith(".")]
        for a in archivos:
            if a.endswith(".py"):
                yield os.path.join(raiz, a)


_COMENTARIO_SQL = re.compile(r"^[ \t]*--.*$", re.M)


def _strings_que_se_usan(arbol):
    """Los str del código, menos los que son una sentencia suelta: docstrings y
    "comentarios" de triple comilla, que no llegan a ninguna pantalla."""
    sueltos = {id(n.value) for n in ast.walk(arbol)
               if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    for n in ast.walk(arbol):
        if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in sueltos):
            yield n


def _texto(s: str) -> str:
    """Un string sin sus renglones de comentario SQL: el esquema de la base
    (`init_db`) es un string que se usa, pero sus `-- …` no los lee nadie."""
    return _COMENTARIO_SQL.sub("", s)


class ElNombreViejoNoVuelve(unittest.TestCase):

    def test_el_recorrido_lee_el_backend(self):
        """Contra el falso verde: si el recorrido deja de encontrar archivos,
        el test de abajo pasa sin haber mirado nada."""
        rutas = {os.path.relpath(r, BACKEND) for r in _modulos()}
        self.assertIn("main.py", rutas)
        self.assertIn(os.path.join("billing", "emails.py"), rutas)
        self.assertGreater(len(rutas), 50)

    def test_mira_los_strings_y_no_los_comentarios(self):
        """El guard mira lo que tiene que mirar: el nombre viejo en un string
        lo caza; en un comentario o en un docstring, no."""
        arbol = ast.parse(
            '"""Docstring del Coach IA."""\n'
            '# comentario del Coach IA\n'
            'def f():\n'
            '    """Otro docstring del coach IA."""\n'
            '    db.executescript("""\n'
            '        -- memoria del coach IA\n'
            '        CREATE TABLE t (x TEXT);""")\n'
            '    return "Chat libre con el Coach IA"\n')
        vistos = [n.value for n in _strings_que_se_usan(arbol)
                  if NOMBRE_VIEJO.search(_texto(n.value))]
        self.assertEqual(vistos, ["Chat libre con el Coach IA"])

    def test_ningun_texto_del_servidor_dice_coach_ia(self):
        hallazgos = []
        for ruta in sorted(_modulos()):
            with open(ruta, encoding="utf-8") as f:
                arbol = ast.parse(f.read(), filename=ruta)
            for n in _strings_que_se_usan(arbol):
                m = NOMBRE_VIEJO.search(_texto(n.value))
                if m:
                    hallazgos.append(
                        f"{os.path.relpath(ruta, BACKEND)}:{n.lineno} «{m.group(0)}»")
        self.assertEqual(hallazgos, [], "la IA se llama Rendi AI")


if __name__ == "__main__":
    unittest.main()
