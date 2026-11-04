"""GUARDIÁN: ninguna consulta sobre la plata ordena SÓLO por fecha.

Las fechas no tienen hora: todo un día empata, y el empate lo resuelve el motor.
SQLite lo resolvía sin que nadie lo pidiera (por su índice); Postgres no
garantiza nada y puede cambiar entre dos corridas. Y hay números que dependen
del empate (`tests/test_empate_de_fecha.py`: 10 % contra 18,18 % de caída, «a la
baja» contra «a la alza»). El criterio está en `orden_estable.py`.

QUÉ VIGILA: en todo el backend (no tests ni scripts), un `ORDER BY` cuya ÚLTIMA
clave es una columna de fecha, en una consulta que lee una tabla de la plata
donde un día puede repetirse. Las tablas con la fecha en una clave única (fotos
por usuario y día, cotizaciones por día, velas) no empatan y no se miran.

También vigila el error de tipeo que este arreglo invita: un
`{operaciones_por_fecha(...)}` adentro de un texto que NO es f-string queda
literal en el SQL.
"""
import ast
import os
import pathlib
import re
import unittest

BACKEND = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tablas de la plata donde un mismo día puede tener varias filas.
CON_EMPATE = {"operations", "positions", "import_normalized_tx", "flujos_a_mano",
              "deleted_ops_journal", "archived_positions"}
# Lo que se interpola en el FROM y es una de ellas.
ALIAS_DE_TABLA = {"TX_VIVAS": "import_normalized_tx"}

_ORDEN = re.compile(r"ORDER BY\s+([\w.]*(?:date|fecha)\w*)\s*(?:ASC|DESC)?", re.I)
_TABLA = re.compile(r"(?:FROM|JOIN)\s+\{?([\w.]+)\}?", re.I)


def _textos(arbol):
    """(línea, texto) de cada string del archivo; lo interpolado de un f-string
    aparece como `{expresión}`."""
    for n in ast.walk(arbol):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            yield n.lineno, n.value
        elif isinstance(n, ast.JoinedStr):
            yield n.lineno, "".join(
                v.value if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}"
                for v in n.values)


def _barrer():
    sin_desempate, sin_interpolar = [], []
    for f in sorted(BACKEND.rglob("*.py")):
        rel = str(f.relative_to(BACKEND))
        if rel.startswith(("tests/", "scripts/")) or "/tests/" in rel:
            continue
        try:
            arbol = ast.parse(f.read_text())
        except SyntaxError:
            continue
        en_f = {id(v) for n in ast.walk(arbol) if isinstance(n, ast.JoinedStr) for v in n.values}
        for n in ast.walk(arbol):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in en_f \
               and re.search(r"\{(_?ops_por_fecha|operaciones_por_fecha|_?por_fecha)\(", n.value):
                sin_interpolar.append(f"{rel}:{n.lineno}")
        for linea, texto in _textos(arbol):
            if "ORDER BY" not in texto.upper():
                continue
            for m in _ORDEN.finditer(texto):
                if texto[m.end():].lstrip().startswith(","):
                    continue
                antes = texto[:m.start()]
                tablas = {ALIAS_DE_TABLA.get(t.split(".")[-1], t.split(".")[-1])
                          for t in _TABLA.findall(antes)}
                if tablas & CON_EMPATE:
                    sin_desempate.append(f"{rel}:{linea}  {m.group(0).strip()}  "
                                         f"({', '.join(sorted(tablas & CON_EMPATE))})")
    return sin_desempate, sin_interpolar


class OrdenConDesempateTest(unittest.TestCase):
    def test_ninguna_consulta_de_la_plata_ordena_solo_por_fecha(self):
        malos, _ = _barrer()
        self.assertEqual(malos, [], "Consultas que dejan el empate del mismo día al motor:\n  · "
                         + "\n  · ".join(malos) +
                         "\n\nUsá `orden_estable.operaciones_por_fecha()` (operaciones de un "
                         "usuario) o `orden_estable.por_fecha(...)` (lo demás), o desempatá a "
                         "mano con la columna que daba el orden en SQLite.")

    def test_el_desempate_no_quedo_como_texto_literal(self):
        _, malos = _barrer()
        self.assertEqual(malos, [], "Textos con `{..._por_fecha(...)}` que NO son f-string "
                         "(el SQL lo recibiría literal):\n  · " + "\n  · ".join(malos))


if __name__ == "__main__":
    unittest.main()
