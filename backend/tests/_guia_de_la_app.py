"""La guía de la app (BROKER_GUIDES), leída como TEXTO desde las pruebas.

La guía vive en `frontend/src/components/import/BrokerInstructions.jsx` y es la
fuente de cómo bajar cada archivo de cada broker. Leer JavaScript desde Python
es la única forma de que una prueba del servidor vigile que el servidor dice lo
mismo (mismo recurso que `test_promesas_vs_producto.py` con el catálogo).
"""
import os
import re

GUIA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "src", "components", "import", "BrokerInstructions.jsx")

_TEXTO_JS = re.compile(r"'((?:[^'\\]|\\.)*)'")


def _bloques():
    """El código de cada broker de BROKER_GUIDES, por id."""
    fuente = open(GUIA, encoding="utf-8").read()
    ini = fuente.index("const BROKERS = [")
    fin = fuente.index("\n]\n", ini)
    partes = re.split(r"\n  \{\n    id: '", fuente[ini:fin])[1:]
    return {p.split("'", 1)[0]: p for p in partes}


def pasos():
    """{id: [paso, paso, …]} — los `steps` de cada broker, en orden."""
    out = {}
    for gid, bloque in _bloques().items():
        m = re.search(r"\n    steps: \[\n(.*?)\n    \],\n", bloque, re.S)
        assert m, f"la guía de «{gid}» no tiene steps donde los buscamos"
        out[gid] = _TEXTO_JS.findall(m.group(1))
    return out


def pasos_de_la_foto():
    """{id: [índices]} — `pasosFoto` de cada broker."""
    out = {}
    for gid, bloque in _bloques().items():
        m = re.search(r"\n    pasosFoto: \[([^\]]*)\],", bloque)
        assert m, f"la guía de «{gid}» no declara pasosFoto"
        out[gid] = [int(x) for x in re.findall(r"\d+", m.group(1))]
    return out
