"""La IA de Rendi se llama Rendi AI: el nombre viejo ("Coach IA") no vuelve.

Del lado del servidor salen textos que la persona lee tal cual: la lista de
beneficios de la tarjeta de "llegaste al límite", los avisos de "está tardando
más de lo normal" del chat, los mails y la nota que queda en una compra
registrada por chat. Esos decían "Coach IA" cuando el producto ya se llamaba
Rendi AI en el catálogo, la FAQ y la guía. Y las instrucciones del chat decían
"Sos el coach de inversiones de Rendi": si alguien le preguntaba cómo se
llamaba, el modelo no tenía de dónde sacar "Rendi AI".

Se leen los STRINGS del código con `ast`, no el archivo como texto: así los
comentarios y los docstrings —que sí pueden contar la historia— no cuentan, y
un string partido en varias líneas o sumado con `+` sí.

Lo que aprendió auditándose (2026-09-26, mismo día): la primera versión tenía
un solo patrón y pasaba en verde con "el Coach" + "IA", con "Registrado por el
Coach" y con "Coach&nbsp;IA" adentro de un mail. Ahora usa los mismos tres
patrones que el guard del frontend (`frontend/src/__guards__/nombre-de-la-ia.test.js`).
Límite declarado: un texto con un hueco en el medio (f"Coach {x} IA") no se
puede leer entero sin correr el código.

Corre con: cd backend && python3 -m pytest tests/test_nombre_de_la_ia.py
"""
import ast
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

import main  # noqa: E402

# Entre dos palabras puede haber más que un espacio y en un mail se lee igual:
# un espacio duro (`&nbsp;`) o una etiqueta (`Coach <b>IA</b>`).
_ENTRE = r"(?:\s|&nbsp;|&#160;|<[^<>]*>)+"
NOMBRE_VIEJO = re.compile(
    rf"coach{_ENTRE}(de{_ENTRE})?ia\b"        # "Coach IA", "coach de IA"
    rf"|\b(el|al|del){_ENTRE}coach\b"         # "Memoria del Coach", "Sos el coach…"
    rf"|\bai{_ENTRE}coach\b", re.I)          # "AI Coach"
# Los tests citan el texto viejo a propósito; los scripts no llegan a nadie.
NO_SE_LEEN = {"tests", "scripts", "__pycache__", "node_modules", "venv"}
# El único lugar donde el nombre viejo TIENE que estar: el valor que init_db
# busca para reemplazarlo en las notas viejas. Por nombre de constante, no por
# renglón: si se mueve sigue exceptuado, y en cualquier otro lado es un rojo.
EXCEPCIONES = {("main.py", "_NOTA_COMPRA_POR_CHAT_VIEJA")}

_COMENTARIO_SQL = re.compile(r"^[ \t]*--.*$", re.M)
_ES_SQL = re.compile(r"\b(CREATE|ALTER|INSERT|SELECT|UPDATE|DELETE|DROP)\b")


def _modulos():
    for raiz, dirs, archivos in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in NO_SE_LEEN and not d.startswith(".")]
        for a in archivos:
            if a.endswith(".py"):
                yield os.path.join(raiz, a)


def _suma(n):
    """El texto de una suma de strings ("el Coach " + "IA"). Lo que no es un
    string fijo (una variable) queda como un carácter nulo, que no arma palabras."""
    if isinstance(n, ast.Constant) and isinstance(n.value, str):
        return n.value
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
        return _suma(n.left) + _suma(n.right)
    return "\x00"


def _strings_que_se_usan(arbol, rel=""):
    """(renglón, texto) de cada str del código, menos los que son una sentencia
    suelta —docstrings y "comentarios" de triple comilla, que no llegan a
    ninguna pantalla— y las EXCEPCIONES. Las sumas de strings se leen enteras."""
    sueltos = {id(n.value) for n in ast.walk(arbol)
               if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    exceptuados = {id(n.value) for n in ast.walk(arbol)
                   if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and (rel, t.id) in EXCEPCIONES
                           for t in n.targets)}
    for n in ast.walk(arbol):
        if (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in sueltos and id(n) not in exceptuados):
            yield n.lineno, n.value
        elif isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            texto = _suma(n)
            if texto.strip("\x00"):
                yield n.lineno, texto


def _texto(s: str) -> str:
    """Un string sin sus renglones de comentario SQL: el esquema de la base
    (`init_db`) es un string que se usa, pero sus `-- …` no los lee nadie. Sólo
    en SQL: en un mail o en el contexto que se le manda a la IA, un renglón
    "--- MENSAJE ---" es texto."""
    return _COMENTARIO_SQL.sub("", s) if _ES_SQL.search(s) else s


def _vistos(fuente: str, rel: str = "") -> list:
    """Los strings de `fuente` que el guard marcaría, enteros."""
    return [s for _, s in _strings_que_se_usan(ast.parse(fuente), rel)
            if NOMBRE_VIEJO.search(_texto(s))]


class ElNombreViejoNoVuelve(unittest.TestCase):

    def test_el_recorrido_lee_el_backend(self):
        """Contra el falso verde: si el recorrido deja de encontrar archivos,
        el test de abajo pasa sin haber mirado nada."""
        rutas = {os.path.relpath(r, BACKEND) for r in _modulos()}
        self.assertIn("main.py", rutas)
        self.assertIn(os.path.join("billing", "emails.py"), rutas)
        self.assertIn(os.path.join("billing", "plan_textos.py"), rutas)
        self.assertGreater(len(rutas), 50)

    def test_mira_los_strings_y_no_los_comentarios(self):
        """El nombre viejo en un string lo caza; en un comentario, un docstring
        o un comentario de SQL, no."""
        fuente = (
            '"""Docstring del Coach IA."""\n'
            '# comentario del Coach IA\n'
            'def f():\n'
            '    """Otro docstring del coach IA."""\n'
            '    db.executescript("""\n'
            '        -- memoria del coach IA\n'
            '        CREATE TABLE t (x TEXT);""")\n'
            '    return "Chat libre con el Coach IA"\n')
        self.assertEqual(_vistos(fuente), ["Chat libre con el Coach IA"])

    def test_caza_las_formas_que_se_le_escapaban(self):
        """Los casos que pasaban en verde con la primera versión."""
        for fuente in ('x = "el Coach " + "IA"',
                       'x = "Registrado por el Coach"',
                       'x = "<p>Coach&nbsp;IA</p>"',
                       'x = "<p>Coach <b>IA</b></p>"',
                       'x = "Tip: AI Coach"',
                       'x = """--- CONTEXTO ---\n-- lo dice el Coach IA\n"""'):
            self.assertTrue(_vistos(fuente), fuente)

    def test_la_excepcion_es_una_sola_y_con_nombre(self):
        """La nota vieja se puede nombrar en SU constante de main.py; la misma
        frase en cualquier otra constante, u otro archivo, es un rojo."""
        fuente = ('_NOTA_COMPRA_POR_CHAT_VIEJA = "Registrado por Coach IA"\n'
                  'OTRA = "Registrado por Coach IA"\n')
        self.assertEqual(_vistos(fuente, "main.py"), ["Registrado por Coach IA"])
        self.assertEqual(len(_vistos(fuente, "otro.py")), 2)

    def test_ningun_texto_del_servidor_dice_coach_ia(self):
        hallazgos = []
        for ruta in sorted(_modulos()):
            rel = os.path.relpath(ruta, BACKEND)
            with open(ruta, encoding="utf-8") as f:
                arbol = ast.parse(f.read(), filename=ruta)
            for renglon, s in _strings_que_se_usan(arbol, rel):
                m = NOMBRE_VIEJO.search(_texto(s))
                if m:
                    hallazgos.append(f"{rel}:{renglon} «{m.group(0)}»")
        self.assertEqual(sorted(set(hallazgos)), [], "la IA se llama Rendi AI")


class ElChatSabeComoSeLlama(unittest.TestCase):
    """Las dos instrucciones del chat —la del Pro (también el asesor y los días
    Pro de la prueba) y la de Free/Plus— le dicen al modelo su nombre en la
    primera oración, que es lo que lee antes que nada."""

    def test_los_dos_prompts_le_dicen_su_nombre(self):
        for nombre in ("_AI_CHAT_SYSTEM", "_AI_CHAT_SYSTEM_FREE"):
            primera = getattr(main, nombre).split("\n", 1)[0]
            self.assertIn("Sos Rendi AI", primera,
                          f"{nombre} no le dice al modelo cómo se llama")
            self.assertIn("cómo te llamás, sos Rendi AI", primera, nombre)


@unittest.skipIf(getattr(main, "USANDO_PG", False),
                 "Sólo SQLite: en Postgres init_db() aplica schema_pg.sql y no corre "
                 "las correcciones de datos (los datos llegan ya corregidos de SQLite).")
class LasNotasDeLasComprasViejasPorChat(unittest.TestCase):
    """Las compras registradas por chat antes del 2026-09-26 guardaron la nota
    con el nombre viejo. init_db() —el camino que corre en cada arranque de
    producción— la renombra una vez, y sólo cuando es la nota exacta del
    sistema: lo que alguien escribió a mano queda como lo dejó."""

    def test_init_db_renombra_la_nota_del_sistema_y_nada_mas(self):
        conn = main.get_db()
        uid = conn.execute(
            "INSERT INTO users (email, password_hash, approved) VALUES (?, 'x', 1)",
            ("notas-chat@rendi.test",)).lastrowid
        ids = {}
        for clave, nota in (
                ("del_sistema", main._NOTA_COMPRA_POR_CHAT_VIEJA),
                ("a_mano", main._NOTA_COMPRA_POR_CHAT_VIEJA + " y la revisé"),
                ("vacia", None)):
            ids[clave] = conn.execute(
                "INSERT INTO positions (user_id, broker, asset, quantity, buy_price, "
                "is_cash, notes) VALUES (?, 'Cocos', 'GGAL', 1, 100, 0, ?)",
                (uid, nota)).lastrowid
        conn.commit()
        conn.close()

        main.init_db()
        main.init_db()   # la segunda no encuentra nada que cambiar

        conn = main.get_db()
        try:
            notas = {k: conn.execute("SELECT notes FROM positions WHERE id=?",
                                     (i,)).fetchone()[0] for k, i in ids.items()}
        finally:
            conn.close()
        self.assertEqual(notas["del_sistema"], main._NOTA_COMPRA_POR_CHAT)
        self.assertEqual(notas["a_mano"], main._NOTA_COMPRA_POR_CHAT_VIEJA + " y la revisé")
        self.assertIsNone(notas["vacia"])


if __name__ == "__main__":
    unittest.main()
