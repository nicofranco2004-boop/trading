"""builders.distribution — packet de las tortas de distribución (tipo y sector).
═══════════════════════════════════════════════════════════════════════════
Topics: portfolio.distribution_type · portfolio.distribution_sector

── Por qué este builder NO recalcula desde la DB ──────────────────────────
Todos los demás builders leen `positions` y agregan server-side. Éste recibe
el corte ya calculado del frontend, a propósito.

La clasificación por clase de activo y por sector vive en el frontend
(utils/assetClass.js, utils/assetSector.js, utils/assetPnl.js) y no es
trivial: decide el mercado antes que el instrumento, hereda asset_type para
las operaciones cerradas, despeja el costo en USD del par (pnl_usd, pnl_pct)
y suma tres patas de resultado. Portarlo a Python sería una SEGUNDA
implementación de la misma regla, y el día que diverjan la IA va a comentar
números distintos a los que la persona tiene en pantalla. Eso es peor que
cualquier ventaja de recalcular acá: destruye la confianza en las dos cosas.

Precedente en el repo: el chat del Coach también arma su contexto con el
snapshot del frontend.

Lo que SÍ hace este builder — y por eso no es un passthrough — es sanear la
entrada (clamp, coerción numérica, tope de tamaño) y calcular la LECTURA:
quién rinde y quién no, quién aporta el resultado en plata, cuánta cartera no
tiene rendimiento medible. El modelo recibe conclusiones ordenadas, no una
tabla cruda para que las derive él.

Params esperados (los manda AskAIAbout):
    axis          — 'tipo' | 'sector' (lo fija el topic, no el cliente)
    total_usd     — total de la torta
    slices        — [{label, value_usd, weight_pct, pnl_usd, pnl_pct, assets}]
    unclassified_pct

Shape (~600 bytes):
{
  "screen": "portfolio.distribution_type",
  "eje": "tipo de activo",
  "total_usd": int,
  "porciones": [{"nombre", "peso_pct", "valor_usd", "resultado_usd", "resultado_pct", "activos": [...]}],
  "mejores": [...],           # por rendimiento %, solo las medibles
  "menos_rinden": [...],      # la cola del ranking — puede ser positiva
  "mas_aporta_usd": [...],    # quién puso la plata, que no siempre es quien más rindió
  "concentracion": {"top1_pct", "top3_pct"},
  "sin_rendimiento_medible_pct": float,
  "sin_clasificar_pct": float,
}
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

MAX_SLICES = 12
MAX_ASSETS_PER_SLICE = 6
# Debajo de este peso una porción no entra en los rankings destacados: un
# +400% sobre el 0,3% de la cartera es ruido, y arriba de un análisis se lee
# como señal. Ojo: la porción SIGUE en `porciones`, así que el modelo la ve —
# lo único que no hace es encabezar la lectura.
MIN_WEIGHT_FOR_RANKING = 2.0


def _num(v, default=None) -> Optional[float]:
    try:
        if v is None:
            return default
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else default
    except (TypeError, ValueError):
        return default


def _clean_assets(raw) -> List[Dict[str, Any]]:
    out = []
    for a in (raw or [])[:MAX_ASSETS_PER_SLICE]:
        if not isinstance(a, dict):
            continue
        nombre = str(a.get("a") or a.get("asset") or "")[:24]
        if not nombre:
            continue
        item = {"ticker": nombre, "peso_pct": round(_num(a.get("w"), 0) or 0, 1)}
        pct = _num(a.get("p"))
        if pct is not None:
            item["resultado_pct"] = round(pct, 1)
        out.append(item)
    return out


def _build(axis_key: str, axis_label: str, **params) -> Dict[str, Any]:
    raw_slices = params.get("slices")
    if not isinstance(raw_slices, list):
        raw_slices = []

    porciones: List[Dict[str, Any]] = []
    for s in raw_slices[:MAX_SLICES]:
        if not isinstance(s, dict):
            continue
        nombre = str(s.get("label") or "")[:40]
        peso = _num(s.get("weight_pct"))
        if not nombre or peso is None:
            continue
        p: Dict[str, Any] = {
            "nombre": nombre,
            "peso_pct": round(peso, 1),
            "valor_usd": int(round(_num(s.get("value_usd"), 0) or 0)),
        }
        pnl_usd = _num(s.get("pnl_usd"))
        pnl_pct = _num(s.get("pnl_pct"))
        if pnl_usd is not None:
            p["resultado_usd"] = int(round(pnl_usd))
        # El % puede faltar aunque el monto exista: cuando alguna venta no trae
        # con qué despejar el costo, el frontend oculta la tasa en vez de
        # inflarla. Si no vino, acá tampoco se inventa.
        if pnl_pct is not None:
            p["resultado_pct"] = round(pnl_pct, 1)
        activos = _clean_assets(s.get("assets"))
        if activos:
            p["activos"] = activos
        porciones.append(p)

    # ── La lectura ────────────────────────────────────────────────────────
    medibles = [
        p for p in porciones
        if "resultado_pct" in p and p["peso_pct"] >= MIN_WEIGHT_FOR_RANKING
    ]
    por_tasa = sorted(medibles, key=lambda p: p["resultado_pct"], reverse=True)
    con_monto = [p for p in porciones if "resultado_usd" in p]
    por_monto = sorted(con_monto, key=lambda p: abs(p["resultado_usd"]), reverse=True)

    def _resumen(p):
        d = {"nombre": p["nombre"], "peso_pct": p["peso_pct"]}
        if "resultado_pct" in p:
            d["resultado_pct"] = p["resultado_pct"]
        if "resultado_usd" in p:
            d["resultado_usd"] = p["resultado_usd"]
        return d

    pesos = sorted((p["peso_pct"] for p in porciones), reverse=True)
    # Cuánta cartera no tiene rendimiento medible (efectivo, o porciones sin
    # precio). Sin este número el modelo lee el % como si cubriera todo.
    sin_medir = round(
        sum(p["peso_pct"] for p in porciones if "resultado_pct" not in p), 1
    )

    return {
        "screen": f"portfolio.distribution_{axis_key}",
        "eje": axis_label,
        "total_usd": int(round(_num(params.get("total_usd"), 0) or 0)),
        "porciones": porciones,
        "mejores": [_resumen(p) for p in por_tasa[:3]],
        # La cola del ranking, excluyendo a las que ya entraron en `mejores`
        # (si no, con 4 o 5 porciones medibles la del medio salía en las dos).
        # Se llama "menos_rinden" y no "peores" a propósito: en una cartera
        # que anda bien, la última del ranking puede seguir siendo positiva, y
        # "peores" empujaría al modelo a comentarla como si fuera una pérdida.
        "menos_rinden": [_resumen(p) for p in reversed(por_tasa[3:])][:3],
        "mas_aporta_usd": [_resumen(p) for p in por_monto[:3]],
        "concentracion": {
            "top1_pct": pesos[0] if pesos else 0,
            "top3_pct": round(sum(pesos[:3]), 1) if pesos else 0,
        },
        "sin_rendimiento_medible_pct": sin_medir,
        "sin_clasificar_pct": round(_num(params.get("unclassified_pct"), 0) or 0, 1),
    }


def build_type(conn, user_id: int, **params) -> Dict[str, Any]:
    return _build("type", "tipo de activo", **params)


def build_sector(conn, user_id: int, **params) -> Dict[str, Any]:
    return _build("sector", "sector económico", **params)
