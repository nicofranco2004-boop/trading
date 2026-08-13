"""`import_confirm` no puede tener el lock de escritura durante todo el import.

EL PROBLEMA. El confirm era UNA sola transacción de 177 líneas: cargaba, deduplicaba,
persistía, y después hacía el rebuild FIFO de TODO el historial del usuario, dos
sweeps, cuatro normalizaciones, el recalc de P&L y el backfill de snapshots — todo
con el lock de ESCRITURA de SQLite tomado. Y el lock es por BASE, no por usuario:
mientras UNA persona importaba, NADIE en Rendi podía guardar nada.

Peor todavía: `tag_bonds_from_data912` hace un HTTP a data912 (timeout 8 s) y estaba
adentro. Con la caché fría, el lock duraba lo que tardara la red.

Lo llamativo es que ese post-proceso NUNCA necesitó estar ahí: las nueve etapas ya
venían envueltas en try/except con traceback, y el propio código las declara
"Best-effort: si falla, el batch ya está persistido". O sea que su fallo jamás hizo
rollback — estaban dentro de la transacción sin ningún motivo, alargándola.

Estos tests fijan la forma, no el comportamiento: son estructurales a propósito.
Un test de comportamiento acá exigiría un import real de punta a punta, y lo que hay
que impedir es que alguien vuelva a meter trabajo largo —o una llamada de red—
adentro de la transacción.

Corre con: cd backend && python3 -m pytest tests/test_import_confirm_lock.py
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
MAIN = os.path.join(BACKEND, "main.py")

if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def _fn(nombre):
    src = open(MAIN).read()
    tree = ast.parse(src)
    for f in ast.walk(tree):
        if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name == nombre:
            return f, src.split("\n")
    raise AssertionError(f"no encontré {nombre} en main.py")


def _transacciones(fn, lineas):
    """Los `with conn:` de la función, como (desde, hasta)."""
    return sorted(
        (n.lineno, n.end_lineno) for n in ast.walk(fn)
        if isinstance(n, ast.With) and "conn" in lineas[n.lineno - 1]
    )


def test_la_transaccion_atomica_es_corta():
    """El bloque atómico cubre load + dedup + persist. Nada más.

    El umbral no es estético: cada línea adentro es tiempo con el lock tomado y
    con toda la app sin poder escribir. Si alguien vuelve a meter el rebuild o un
    sweep acá, este test lo frena.
    """
    fn, lineas = _fn("import_confirm")
    txs = _transacciones(fn, lineas)
    assert txs, "import_confirm no tiene ninguna transacción explícita"

    largo = txs[0][1] - txs[0][0]
    assert largo < 80, (
        f"La transacción atómica del import creció a {largo} líneas. Antes del fix "
        "eran 177 e incluían el post-proceso entero: con eso, mientras un usuario "
        "importaba, NADIE en Rendi podía guardar nada. Si agregaste trabajo, "
        "ponelo DESPUÉS del `with conn:`, en su propia transacción."
    )


def test_el_post_proceso_va_en_transacciones_separadas():
    """Cada etapa best-effort con la suya: así el lock se suelta entre medio."""
    fn, lineas = _fn("import_confirm")
    txs = _transacciones(fn, lineas)
    assert len(txs) >= 8, (
        f"Sólo hay {len(txs)} transacciones en import_confirm. El post-proceso "
        "(rebuild, 2 sweeps, 4 normalizaciones, recalc, backfill) tiene que ir "
        "cada uno en la suya, no todos dentro de una."
    )


def test_ninguna_llamada_de_red_adentro_de_una_transaccion():
    """EL test. Una llamada de red con el lock tomado hace que el lock dure lo
    que tarde el servidor del otro lado.

    `_fetch_data912_bonds()` (HTTP, timeout 8 s) tiene que estar FUERA del
    `with conn:` — precalentando la caché— para que la transacción se abra con el
    dato ya en memoria.
    """
    fn, lineas = _fn("import_confirm")
    txs = _transacciones(fn, lineas)

    RED = ("_fetch_data912_bonds", "requests.get", "requests.post", "urlopen", "yf.download")
    adentro = []
    for i in range(fn.lineno, (fn.end_lineno or fn.lineno) + 1):
        linea = lineas[i - 1]
        if linea.lstrip().startswith("#"):
            continue
        if any(r in linea for r in RED) and any(a <= i <= b for a, b in txs):
            adentro.append(f"main.py:{i}: {linea.strip()[:70]}")

    assert not adentro, (
        "Hay llamadas de red DENTRO de una transacción de escritura. El lock de "
        "SQLite va a durar lo que tarde la red, y bloquea a todos los usuarios:\n  "
        + "\n  ".join(adentro)
    )


def test_el_precalentado_de_data912_sigue_estando():
    """Si alguien borra el warm-up, el fetch vuelve a caer adentro de la tx —
    pero el test de arriba NO lo vería, porque la llamada quedaría implícita
    dentro de `tag_bonds_from_data912`. Por eso lo fijamos explícito."""
    fn, lineas = _fn("import_confirm")
    # Sin los comentarios: el bloque que explica ESTE fix nombra
    # `tag_bonds_from_data912` bastante antes de la llamada real, y comparar
    # posiciones sobre el texto crudo daba un falso positivo.
    cuerpo = "\n".join(l for l in lineas[fn.lineno - 1:fn.end_lineno]
                       if not l.lstrip().startswith("#"))
    assert "_fetch_data912_bonds()" in cuerpo, (
        "Desapareció el precalentado de la caché de data912. Sin él, el HTTP "
        "vuelve a ocurrir con el lock de escritura tomado."
    )
    # y tiene que venir ANTES del tag
    i_warm = cuerpo.index("_fetch_data912_bonds()")
    i_tag = cuerpo.index("tag_bonds_from_data912")
    assert i_warm < i_tag, "el precalentado tiene que ir ANTES de abrir la transacción"
