"""foto_cartera — el `summary` de la foto que viaja al chat, calculado en UN lugar.
═══════════════════════════════════════════════════════════════════════════
Hasta el 26/11/2026 este resumen lo armaba el navegador (frontend/src/utils/
aiSummary.js, `buildAiSummary`) y viajaba adentro del snapshot. Con el bot de
WhatsApp aparece una segunda puerta sin navegador, y la regla de la casa es
que dos puertas NO calculan lo mismo por separado: se muda al servidor y las
dos lo leen de acá.

Lo que se encontró al mudarlo: el navegador mandaba `months_tracked`,
`realized_pnl_usd_lifetime`, `deposits_lifetime` y `withdrawals_lifetime`, y el
servidor (`main._sanitize_chat_snapshot`) sólo deja pasar `months_count`,
`sum_pnl_realized`, `sum_deposits` y `sum_withdrawals`. O sea que esos cuatro
números NUNCA llegaban al modelo. Acá se calculan con los nombres que el
servidor sí acepta, y se recalculan SIEMPRE del lado del servidor (en
`_enrich_chat_snapshot_valuation`), venga la foto de la app o de WhatsApp.

Sólo cuentan las filas `broker == 'global'` del mensual: esa fila ya es la suma
de las de cada broker; sumar todas contaría cada peso dos veces.
"""
from __future__ import annotations


def es_fila_global(m) -> bool:
    return isinstance(m, dict) and m.get("broker") == "global"


def contar_posiciones(positions) -> int:
    return sum(1 for p in (positions or []) if isinstance(p, dict) and not p.get("is_cash"))


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def resumen(positions, monthly) -> dict:
    """El mismo cálculo que hacía `buildAiSummary`, con las llaves que el
    servidor acepta en el snapshot."""
    pos = [p for p in (positions or []) if isinstance(p, dict)]
    invertido = sum(_num(p.get("invested")) for p in pos if not p.get("is_cash"))
    globales = [m for m in (monthly or []) if es_fila_global(m)]
    return {
        "total_invested_usd": round(invertido, 2),
        "open_positions_count": contar_posiciones(pos),
        "cash_lines_count": sum(1 for p in pos if p.get("is_cash")),
        "months_count": len(globales),
        "sum_pnl_realized": round(sum(_num(m.get("pnl_realized")) for m in globales), 2),
        "sum_deposits": round(sum(_num(m.get("deposits")) for m in globales), 2),
        "sum_withdrawals": round(sum(_num(m.get("withdrawals")) for m in globales), 2),
    }


# Las operaciones se capean como en el navegador (aiSnapshot.MAX_OPERATIONS): el
# servidor corta el snapshot en 200 KB.
MAX_OPERACIONES = 100


def armar(positions, monthly, brokers, operations) -> dict:
    """La foto entera con la forma que espera `_sanitize_chat_snapshot`."""
    ops = [o for o in (operations or []) if isinstance(o, dict)]
    return {
        "summary": resumen(positions, monthly),
        "positions": [p for p in (positions or []) if isinstance(p, dict)],
        "operations": ops[:MAX_OPERACIONES],
        "monthly": [m for m in (monthly or []) if isinstance(m, dict)],
        "brokers": [b for b in (brokers or []) if isinstance(b, dict)],
    }
