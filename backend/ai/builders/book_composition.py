"""builders.book_composition — packet de las tortas del LIBRO del asesor.
═══════════════════════════════════════════════════════════════════════════
Topics: book.composition_type · book.composition_sector

Los PRIMEROS topics de asesor del registry: hasta acá los 35 topics eran
todos per-cuenta (la cartera de una persona). Estos miran el libro entero —
la suma de las carteras que el asesor administra.

── El nombre: por qué `composition` y no `distribution` ───────────────────
`distribution` YA está tomado del lado asesor y significa otra cosa:
`book.distribution` es la distribución de PERFORMANCE (cuántos clientes en
verde y cuántos en rojo), la dibuja DistributionCard con el título "¿Cómo
vienen tus clientes?" y el prompt del libro ya se la describe al modelo con
ese significado. Un topic `book.distribution_*` acá haría que dos cosas
distintas compartan palabra en el mismo contexto.

── Por qué el packet lo manda el frontend ─────────────────────────────────
Mismo motivo que builders/distribution.py, y acá con más fuerza: la
clasificación por clase y por sector vive en el frontend (utils/assetClass.js,
utils/assetSector.js) y el libro se clasifica con ESE código, corriendo sobre
las filas ya valuadas que devuelve /api/advisor/book/composition. Recalcular
en Python sería una segunda implementación de la misma regla — y el repo ya
tiene el caso: advisor_groups.classify() manda 9,4% de las posiciones reales
a "otro". El modelo comentaría números que no son los de la pantalla.

Lo que SÍ hace este builder es sanear la entrada y calcular la lectura,
reusando el motor de builders/distribution (mismo saneo, mismos rankings,
mismos topes de tamaño) y agregándole lo que solo tiene sentido en un libro:

    clientes         — sobre cuántas carteras está medido esto
    mas_difundidos   — en qué están CASI TODOS, más allá de cuánto pese.
                       Es la otra pregunta del asesor: un activo chico que
                       está en 20 de 25 carteras es una decisión suya, no del
                       mercado. La torta pondera por valor; esto no.
    mas_dispersos    — dónde más se abren los clientes entre sí. El % de cada
                       porción es AGRUPADO (Σresultado ÷ Σcosto), que es el
                       número correcto para el titular pero esconde lo que al
                       asesor le importa: "+9,8% en AAPL" puede ser un cliente
                       en −20% y otro en +40%. El libro se ve bien y hay
                       alguien enojado.

Params esperados (los manda AskAIAbout desde BookComposition.jsx):
    total_usd, slices, unclassified_pct   — igual que distribution
    clientes            — int
    mas_difundidos      — [{a: ticker, c: clientes}]
    mas_dispersos       — [{a: ticker, c: clientes, min: %, max: %}]
"""

from __future__ import annotations
from typing import Any, Dict, List

from .distribution import _build, _num

MAX_DIFUNDIDOS = 6
MAX_DISPERSOS = 4


def _clean_difundidos(raw) -> List[Dict[str, Any]]:
    out = []
    for d in (raw or [])[:MAX_DIFUNDIDOS]:
        if not isinstance(d, dict):
            continue
        ticker = str(d.get("a") or d.get("asset") or "")[:24]
        n = _num(d.get("c") if d.get("c") is not None else d.get("clients"))
        if not ticker or n is None or n < 2:
            continue
        out.append({"ticker": ticker, "clientes": int(n)})
    return out


def _clean_dispersos(raw) -> List[Dict[str, Any]]:
    # El tope se aplica DESPUÉS de filtrar: acá el cap es por tamaño del
    # prompt, y perder una fila válida porque una inválida le ocupó el lugar
    # sería recortar señal para dejar entrar ruido.
    out = []
    for d in (raw or []):
        if not isinstance(d, dict):
            continue
        ticker = str(d.get("a") or d.get("asset") or "")[:24]
        n = _num(d.get("c"))
        lo, hi = _num(d.get("min")), _num(d.get("max"))
        if not ticker or n is None or n < 2 or lo is None or hi is None:
            continue
        item = {"ticker": ticker, "clientes": int(n),
                "peor_cliente_pct": round(lo, 1), "mejor_cliente_pct": round(hi, 1)}
        # El rango puede no cubrir a todos los que tienen el activo: hay
        # clientes cuya tasa no es publicable (el capital que generó su
        # resultado ya no está en la posición). Sin este dato el modelo
        # llamaría "el peor de tus clientes" a un mínimo que deja gente afuera.
        ct = _num(d.get("ct"))
        if ct is not None and ct > n:
            item["clientes_con_el_activo"] = int(ct)
        out.append(item)
        if len(out) >= MAX_DISPERSOS:
            break
    return out


def _build_book(axis_key: str, axis_label: str, **params) -> Dict[str, Any]:
    pkt = _build(axis_key, axis_label, **params)
    # El eje es el mismo, el objeto medido no: que el modelo no lea esto como
    # la cartera de una persona.
    pkt["screen"] = f"book.composition_{axis_key}"
    pkt["objeto"] = "el libro del asesor (todas las carteras que administra)"

    clientes = _num(params.get("clientes"))
    if clientes is not None and clientes > 0:
        pkt["clientes"] = int(clientes)

    difundidos = _clean_difundidos(params.get("mas_difundidos"))
    if difundidos:
        pkt["mas_difundidos"] = difundidos

    dispersos = _clean_dispersos(params.get("mas_dispersos"))
    if dispersos:
        pkt["mas_dispersos"] = dispersos

    return pkt


def build_type(conn, user_id: int, **params) -> Dict[str, Any]:
    return _build_book("type", "tipo de activo", **params)


def build_sector(conn, user_id: int, **params) -> Dict[str, Any]:
    return _build_book("sector", "sector económico", **params)
