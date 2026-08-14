"""Ninguna verificación puede apagarse sola por un parámetro que alguien no pasó.

EL PROBLEMA, y es una CATEGORÍA, no un caso. `comparar()` tenía
`tablas_origen: Optional[set] = None`, y el chequeo que lo usaba vivía adentro de
un `if tablas_origen is not None:`. O sea: **la red existía y quedaba sin poner**.
El que no pasaba el parámetro no veía ningún error — veía "ok: sin hallazgos",
que es la respuesta más cara que puede dar una verificación. El docstring decía
"pasalo SIEMPRE", pero eso es una advertencia, no un mecanismo.

Y no era uno: era **dos**, el mismo agujero un piso más abajo (`cols_origen`).
Que es exactamente el motivo de que este test barra la categoría en vez de
mirar esos dos nombres.

QUÉ MARCA COMO MALO. Un parámetro que cumple las tres cosas a la vez:

  1. tiene default, y el default es `None` o `False` (o sea: **apagado**),
  2. gobierna un `if` adentro de la función,
  3. y de ese `if` cuelga un `.append(...)` — un HALLAZGO.

Los tres juntos significan una sola cosa: *si no me pasás esto, no reporto*.

QUÉ NO MARCA, y las distinciones son las que hacen que el test sirva en vez de
ser ruido. Las tres salieron de correrlo, no de imaginarlas:

  · `revisar_secuencias=True` apaga un nivel, pero su default lo deja
    **PRENDIDO**. Apagarlo es un acto explícito de quien llama, no un olvido. La
    regla no es "no se puede apagar nada": es **"lo que se apaga solo, no vale"**.
  · Un parámetro que se REASIGNA antes del `if` (`db_path = db_path or ...`) no
    es un interruptor: el default es un placeholder y nunca llega al chequeo.
  · Un `append` que agrega VERBOSIDAD (las filas que están bien) no es un
    hallazgo. Eso no se puede distinguir leyendo el AST, así que va a
    `PERMITIDOS` con el motivo escrito y a mano.

CÓMO SE ARREGLA UNO QUE SALTE: no le pongas default, o mejor, no lo recibas por
parámetro — leelo vos adentro de la función, de la fuente correcta. Es lo que
hace `comparar()` con `catalogo_origen()`, y por eso ahora es imposible olvidarlo.
"""
import ast
import os
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(RAIZ, "scripts")

# Se barre `scripts/` entero y no sólo `verificar_copia.py` a propósito: el
# COPIADOR todavía no está escrito y va a vivir acá al lado. Cuando exista, ya
# nace cubierto — que es justo lo que no pasó con la verificación.

# (archivo, función, parámetro) → por qué su default apagado NO es una red que
# se cae. Si no podés escribir el motivo, probablemente sea una red que se cae.
PERMITIDOS = {
    ("pg_type_audit.py", "auditar", "incluir_ok"):
        "No esconde ningún problema: lo que agrega esa rama son las columnas "
        "que están BIEN. Los hallazgos reales (`rompen`, `nulls_en_notnull`) se "
        "appendean siempre, en la rama de arriba. Es verbosidad del informe, no "
        "un nivel de verificación.",
}


def _defaults_apagados(fn: ast.FunctionDef):
    """{nombre: linea} de los parámetros cuyo default es None o False.

    Mira los posicionales-con-default y los keyword-only, que es donde este
    proyecto los pone.
    """
    out = {}
    pares = list(zip(fn.args.args[len(fn.args.args) - len(fn.args.defaults):],
                     fn.args.defaults))
    pares += [(a, d) for a, d in zip(fn.args.kwonlyargs, fn.args.kw_defaults)
              if d is not None]
    for arg, default in pares:
        if isinstance(default, ast.Constant) and default.value in (None, False):
            out[arg.arg] = arg.lineno
    return out


def _nombres_en(nodo):
    return {n.id for n in ast.walk(nodo) if isinstance(n, ast.Name)}


def _reasignados(fn):
    """Parámetros que la función pisa antes de usarlos (`x = x or default`).

    Ahí el default no es un interruptor sino un placeholder: para cuando llega
    al `if`, el valor ya no puede ser el default. No es la categoría.
    """
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            out |= {t.id for t in n.targets if isinstance(t, ast.Name)}
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)) and isinstance(n.target, ast.Name):
            out.add(n.target.id)
    return out


def _tiene_append(cuerpo):
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "append"
               for stmt in cuerpo for n in ast.walk(stmt))


def redes_opt_in():
    """[(archivo, función, parámetro, línea)] de cada red que se apaga sola."""
    malos = []
    for nombre in sorted(os.listdir(SCRIPTS)):
        if not nombre.endswith(".py"):
            continue
        ruta = os.path.join(SCRIPTS, nombre)
        try:
            arbol = ast.parse(open(ruta, encoding="utf-8").read())
        except SyntaxError:
            continue
        for fn in ast.walk(arbol):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            apagados = {k: v for k, v in _defaults_apagados(fn).items()
                        if k not in _reasignados(fn)}
            if not apagados:
                continue
            for nodo in ast.walk(fn):
                if not isinstance(nodo, ast.If):
                    continue
                usados = _nombres_en(nodo.test) & set(apagados)
                if not usados:
                    continue
                # El hallazgo cuelga de una sola de las dos ramas: eso es lo que
                # hace que no pasar el parámetro cambie lo que se REPORTA.
                if _tiene_append(nodo.body) != _tiene_append(nodo.orelse):
                    for p in sorted(usados):
                        malos.append((nombre, fn.name, p, apagados[p]))
    return malos


class LaRedNoPuedeSerOptInTest(unittest.TestCase):

    def test_ninguna_verificacion_se_apaga_sola(self):
        malos = [x for x in redes_opt_in() if (x[0], x[1], x[2]) not in PERMITIDOS]
        if malos:
            detalle = "\n".join(
                f"  scripts/{a}:{l}  {f}(..., {p}=None)  → si no lo pasás, no reporta"
                for a, f, p, l in malos)
            self.fail(
                f"{len(malos)} verificación(es) quedan APAGADAS si el que llama se "
                f"olvida de un parámetro.\n"
                f"Ese olvido no da error: da 'ok, sin hallazgos'. Es la forma exacta "
                f"de los últimos errores de este proyecto.\n"
                f"Arreglo: sacale el default, o mejor leé el dato adentro de la "
                f"función desde la fuente correcta (ver catalogo_origen).\n"
                f"{detalle}")

    def test_la_lista_de_permitidos_no_tiene_muertos(self):
        """Un permiso que ya no apunta a nada hace creer que se revisó algo que
        no existe. Es la misma regla del barrido de escritores sólo-SQLite."""
        reales = {(a, f, p) for a, f, p, _l in redes_opt_in()}
        muertos = sorted(k for k in PERMITIDOS if k not in reales)
        self.assertEqual(muertos, [],
                         f"estos permisos ya no apuntan a nada: {muertos}. "
                         f"Sacalos de PERMITIDOS.")

    def test_la_reasignacion_no_tapa_un_interruptor_de_verdad(self):
        """El descarte por `x = x or default` es mecánico, así que puede tapar de
        más. Este test fija que sólo tapa lo que tiene que tapar: si el `if`
        mira el parámetro y NADIE lo reasignó, se marca igual."""
        import tempfile
        # Mismo cuerpo que la sonda mala, pero con el parámetro reasignado antes.
        placeholder = (
            "import os\n"
            "def verificar(cur, ruta=None):\n"
            "    ruta = ruta or os.environ.get('RUTA') or 'x.db'\n"
            "    hallazgos = []\n"
            "    if not os.path.isfile(ruta):\n"
            "        hallazgos.append({'que': 'no existe'})\n"
            "    return hallazgos\n")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         dir=SCRIPTS, prefix="zz_sonda_") as f:
            f.write(placeholder)
            tmp = f.name
        try:
            self.assertEqual(
                [x for x in redes_opt_in() if x[0] == os.path.basename(tmp)], [],
                "un parámetro reasignado no es un interruptor y no se marca")
        finally:
            os.unlink(tmp)

    def test_el_detector_agarra_uno_plantado(self):
        """Sin esto el test de arriba no prueba nada: podría estar mirando mal.

        Se planta en `scripts/` una función con la forma EXACTA que tenía
        `comparar()` antes del arreglo.
        """
        import tempfile
        malo = (
            "def verificar(cur, cosas=None):\n"
            "    hallazgos = []\n"
            "    if cosas is not None:\n"
            "        hallazgos.append({'que': 'falta algo'})\n"
            "    return hallazgos\n")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         dir=SCRIPTS, prefix="zz_sonda_") as f:
            f.write(malo)
            tmp = f.name
        try:
            encontrados = [x for x in redes_opt_in() if x[0] == os.path.basename(tmp)]
            self.assertEqual([(x[1], x[2]) for x in encontrados],
                             [("verificar", "cosas")], encontrados)
        finally:
            os.unlink(tmp)

    def test_el_detector_NO_marca_un_default_que_deja_la_red_PRENDIDA(self):
        """La contracara, y sin ella el detector sería ruido.

        `revisar_secuencias=True` apaga un nivel si se lo pide explícitamente,
        pero su default lo deja funcionando. Eso está bien y no se marca: la
        regla es 'lo que se apaga solo no vale', no 'no se puede apagar nada'.
        """
        import tempfile
        bueno = (
            "def verificar(cur, revisar=True):\n"
            "    hallazgos = []\n"
            "    if revisar:\n"
            "        hallazgos.append({'que': 'falta algo'})\n"
            "    return hallazgos\n")
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                         dir=SCRIPTS, prefix="zz_sonda_") as f:
            f.write(bueno)
            tmp = f.name
        try:
            self.assertEqual(
                [x for x in redes_opt_in() if x[0] == os.path.basename(tmp)], [])
        finally:
            os.unlink(tmp)

    def test_comparar_no_recibe_la_lista_del_origen_por_parametro(self):
        """El arreglo concreto, fijado para que no vuelva de a poco.

        No alcanza con que hoy no haya `if tablas_origen is not None`. Si alguien
        reintroduce el parámetro "para los tests", el default vuelve al camino de
        producción por la puerta de atrás.
        """
        arbol = ast.parse(open(os.path.join(SCRIPTS, "verificar_copia.py"),
                               encoding="utf-8").read())
        fn = next(n for n in ast.walk(arbol)
                  if isinstance(n, ast.FunctionDef) and n.name == "comparar")
        params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        self.assertNotIn("tablas_origen", params,
                         "volvió a ser parámetro: la lista del origen la lee "
                         "`catalogo_origen()` adentro, justamente para que no se "
                         "pueda omitir")
        self.assertNotIn("cols_origen", params, "ídem, un piso más abajo")


if __name__ == "__main__":
    unittest.main()
