"""Behavioral Insights — detección automática de sesgos comportamentales.
═══════════════════════════════════════════════════════════════════════════
Las cuatro detecciones de Sprint 3-4 del plan post-auditoría. Cada detector
es una función pura que toma `operations` (closed trades) + opcionalmente
`positions` y devuelve un dict con la métrica + severidad + evidencia.

El moat real de Rendi vive acá: ningún broker AR (Cocos, IOL, Bull, Balanz)
muestra "vendiste tus winners 3.5x más rápido que tus losers" — lo único
que requiere parsing del historial es de Rendi.

Inputs comunes:
  - ops: List[dict] con keys: date, asset, op_type, entry_date, entry_price,
    exit_price, quantity, pnl_usd, broker, commissions
  - positions: List[dict] con keys actualizadas al momento (para size relativo)

Outputs comunes (shape uniforme para que el frontend renderee genérico):
  {
    code: str,             # 'disposition_effect' | 'overtrade' | etc.
    title: str,            # "Vendés ganadoras antes que perdedoras"
    severity: 'high' | 'medium' | 'low' | 'positive' | 'neutral',
    detected: bool,        # True si el sesgo es relevante para mostrar
    score: float,          # 0-100 magnitud
    value_label: str,      # "3.5x más rápido"
    one_liner: str,        # explicación 1 frase para card
    evidence: dict,        # números crudos para el modal detalle
    references: List[str], # citas académicas
  }
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


# ─── Helpers compartidos ─────────────────────────────────────────────────────


def _is_trade(op: Dict[str, Any]) -> bool:
    """True si es una operación cerrada (venta con pnl), no un aporte ni dividendo."""
    op_type = (op.get("op_type") or "").strip()
    if op_type in ("Compra", "Dividendo", "Interés", ""):
        return False
    if op_type.startswith("CONVERSION") or op_type.startswith("Conversión"):
        return False
    return op.get("pnl_usd") is not None


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _holding_days(op: Dict[str, Any]) -> Optional[int]:
    """Días entre entry_date y exit_date. None si falta data."""
    entry = _parse_date(op.get("entry_date"))
    exit_d = _parse_date(op.get("date"))
    if not entry or not exit_d:
        return None
    diff = (exit_d - entry).days
    return diff if diff >= 0 else None


def _position_size_usd(op: Dict[str, Any]) -> float:
    """Notional al momento de entrar (entry_price × quantity)."""
    ep = op.get("entry_price")
    qty = op.get("quantity")
    if ep is None or qty is None:
        return 0.0
    return float(ep) * float(qty)


# ─── Detector 1: Disposition Effect ──────────────────────────────────────────


def detect_disposition_effect(ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    """El sesgo más famoso del retail: vender winners temprano, aguantar losers.

    Definición de Shefrin & Statman (1985):
    - Holding time avg de winners < holding time avg de losers → disposition effect.
    - Ratio winner/loser < 0.7 → fuerte.
    - Ratio > 1.3 → "diamond hands" (anti-disposition, también puede ser problema).
    - Entre 0.7 y 1.3 → comportamiento equilibrado.

    Requiere ≥10 ops cerradas con entry_date/exit_date válidos para ser fiable.
    """
    trades = [o for o in ops if _is_trade(o)]
    valid = []
    for o in trades:
        days = _holding_days(o)
        if days is None:
            continue
        pnl = o.get("pnl_usd") or 0
        if pnl == 0:
            continue
        valid.append({"days": days, "pnl": pnl, "asset": o.get("asset"), "date": o.get("date")})

    if len(valid) < 5:
        return _not_enough_data("disposition_effect", "Necesitás al menos 5 operaciones cerradas con fechas completas.")

    winners = [v for v in valid if v["pnl"] > 0]
    losers = [v for v in valid if v["pnl"] < 0]

    if len(winners) < 2 or len(losers) < 2:
        return _not_enough_data("disposition_effect", "Necesitás al menos 2 ganadoras y 2 perdedoras para comparar.")

    win_avg = sum(v["days"] for v in winners) / len(winners)
    loss_avg = sum(v["days"] for v in losers) / len(losers)
    ratio = win_avg / loss_avg if loss_avg > 0 else 1.0

    if ratio < 0.5:
        severity = "high"
        title = "Vendés ganadoras mucho más rápido que perdedoras"
        one_liner = (
            f"Mantenés tus perdedoras {1/ratio:.1f}× más tiempo que tus ganadoras. "
            "Es el patrón clásico del disposition effect."
        )
    elif ratio < 0.7:
        severity = "medium"
        title = "Tendencia a vender ganadoras temprano"
        one_liner = (
            f"En promedio aguantás {1/ratio:.1f}× más tus perdedoras que tus ganadoras. "
            "Vale la pena revisar criterios de salida."
        )
    elif ratio < 1.3:
        severity = "positive"
        title = "Tiempo de holding equilibrado"
        one_liner = "Ganadoras y perdedoras se mantienen tiempos similares. Sin disposition effect detectado."
    elif ratio < 2.0:
        severity = "medium"
        title = "Aguantás ganadoras más tiempo que perdedoras"
        one_liner = (
            f"Mantenés ganadoras {ratio:.1f}× más que perdedoras. "
            "Es lo opuesto al disposition effect (positivo), pero verificá que no haya posiciones \"diamond hands\" sin tesis."
        )
    else:
        severity = "low"
        title = "Diamond hands: muy poca rotación"
        one_liner = (
            f"Ganadoras: {win_avg:.0f} días vs perdedoras: {loss_avg:.0f} días. "
            "Estás aguantando mucho — revisá si las ganadoras siguen teniendo upside."
        )

    return {
        "code": "disposition_effect",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, abs(1 - ratio) * 100), 1),
        "value_label": f"{ratio:.2f}× (winners/losers)",
        "one_liner": one_liner,
        "evidence": {
            "winners_count": len(winners),
            "losers_count": len(losers),
            "winners_avg_days": round(win_avg, 1),
            "losers_avg_days": round(loss_avg, 1),
            "ratio": round(ratio, 2),
            "sample_winners": [{"asset": v["asset"], "days": v["days"], "pnl": round(v["pnl"], 2)}
                               for v in sorted(winners, key=lambda x: x["days"])[:3]],
            "sample_losers": [{"asset": v["asset"], "days": v["days"], "pnl": round(v["pnl"], 2)}
                              for v in sorted(losers, key=lambda x: -x["days"])[:3]],
        },
        "references": [
            "Shefrin & Statman (1985) — The disposition to sell winners too early and ride losers too long.",
        ],
    }


# ─── Detector 2: Overtrade Ratio ─────────────────────────────────────────────


def detect_overtrade(ops: List[Dict[str, Any]], positions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Frecuencia de trades vs capital. Excede ~2x/año implica que el portfolio
    está siendo rotado más de dos veces — generalmente destruye returns netos
    una vez que descontás comisiones, spreads y mistiming.

    Benchmark: retail prudente ~0.3-1x/año. Active trader ~2-3x. Day trader >5x.
    """
    trades = [o for o in ops if _is_trade(o)]
    if len(trades) < 3:
        return _not_enough_data("overtrade", "Necesitás al menos 3 operaciones cerradas para medir frecuencia.")

    # Capital promedio: usa positions actuales como proxy (suma de invested).
    # Alternativa: tomar el invested promedio mensual de monthly_entries — más
    # preciso pero requiere otro fetch. Esta aproximación está OK para MVP.
    capital_avg = 0
    if positions:
        capital_avg = sum((p.get("invested") or 0) for p in positions if not p.get("is_cash"))
    if capital_avg <= 0:
        capital_avg = sum(abs(o.get("pnl_usd") or 0) for o in trades) * 5  # fallback

    # Notional total tradeado en el período
    total_notional = sum(_position_size_usd(o) for o in trades)

    # Período: días entre primera y última op (mínimo 30 días para no inflar)
    dates = [_parse_date(o.get("date")) for o in trades]
    dates = [d for d in dates if d]
    if len(dates) < 2:
        return _not_enough_data("overtrade", "Fechas insuficientes.")
    period_days = max(30, (max(dates) - min(dates)).days)
    period_years = period_days / 365

    # Turnover anualizado: notional total / capital promedio / años
    annual_turnover = (total_notional / capital_avg / period_years) if capital_avg > 0 and period_years > 0 else 0
    annual_ops = len(trades) / period_years if period_years > 0 else 0

    if annual_turnover >= 4:
        severity = "high"
        title = "Estás operando muy alto"
        one_liner = (
            f"Tu portfolio rota {annual_turnover:.1f}× por año. "
            "Comisiones y spreads pueden estar comiendo gran parte del rendimiento."
        )
    elif annual_turnover >= 2:
        severity = "medium"
        title = "Frecuencia de trades elevada"
        one_liner = (
            f"Tu portfolio rota {annual_turnover:.1f}× por año. "
            "Es activo — verificá que las comisiones netas justifiquen el ritmo."
        )
    elif annual_turnover >= 0.3:
        severity = "positive"
        title = "Frecuencia de trades razonable"
        one_liner = f"Tu portfolio rota {annual_turnover:.1f}× por año. Estás en el rango del inversor a mediano plazo."
    else:
        severity = "positive"
        title = "Estilo buy & hold"
        one_liner = f"Tu portfolio rota apenas {annual_turnover:.2f}× por año. Estilo pasivo, comisiones mínimas."

    return {
        "code": "overtrade",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, annual_turnover * 25), 1),
        "value_label": f"{annual_turnover:.1f}× / año",
        "one_liner": one_liner,
        "evidence": {
            "total_trades": len(trades),
            "period_days": period_days,
            "period_years": round(period_years, 2),
            "annual_ops": round(annual_ops, 1),
            "annual_turnover": round(annual_turnover, 2),
            "total_notional": round(total_notional, 2),
            "capital_avg": round(capital_avg, 2),
        },
        "references": [
            "Barber & Odean (2000) — Trading is hazardous to your wealth.",
        ],
    }


# ─── Detector 3: Loss Aversion (size winners vs losers) ──────────────────────


def detect_loss_aversion(ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compara el tamaño promedio (en USD notional) de winners vs losers.

    Si el size promedio de tus losers es 1.5×+ más grande que tus winners,
    estás aguantando posiciones grandes "para no realizar la pérdida".
    El comportamiento típico: agrandás posiciones que están en rojo esperando
    que reviertan, mientras achicás las que están en verde.
    """
    trades = [o for o in ops if _is_trade(o)]
    winners = [o for o in trades if (o.get("pnl_usd") or 0) > 0]
    losers = [o for o in trades if (o.get("pnl_usd") or 0) < 0]

    if len(winners) < 3 or len(losers) < 3:
        return _not_enough_data("loss_aversion", "Necesitás al menos 3 ganadoras y 3 perdedoras para comparar tamaños.")

    win_sizes = [_position_size_usd(o) for o in winners]
    loss_sizes = [_position_size_usd(o) for o in losers]
    win_avg = sum(win_sizes) / len(win_sizes)
    loss_avg = sum(loss_sizes) / len(loss_sizes)

    if win_avg == 0 and loss_avg == 0:
        return _not_enough_data("loss_aversion", "Falta entry_price o quantity para calcular tamaños.")

    ratio = loss_avg / win_avg if win_avg > 0 else 0

    if ratio >= 2.0:
        severity = "high"
        title = "Tus perdedoras son más grandes que tus ganadoras"
        one_liner = (
            f"En promedio tus losers son {ratio:.1f}× más grandes (en USD) que tus winners. "
            "Patrón clásico de loss aversion: aguantás posiciones grandes en rojo."
        )
    elif ratio >= 1.5:
        severity = "medium"
        title = "Tendencia a aguantar perdedoras grandes"
        one_liner = (
            f"Tus losers tienen tamaño promedio {ratio:.1f}× tus winners. "
            "Vale revisar criterios de salida — un stop loss firme ayudaría."
        )
    elif ratio >= 0.7:
        severity = "positive"
        title = "Tamaños equilibrados entre ganadoras y perdedoras"
        one_liner = "Los tamaños promedio son similares. No hay loss aversion fuerte detectada."
    else:
        severity = "positive"
        title = "Tus ganadoras son más grandes que tus perdedoras"
        one_liner = (
            f"Patrón saludable: tus winners ({ratio:.1f}× ratio inverso) son más grandes que tus losers. "
            "Cortás pérdidas chicas y dejás correr ganadoras."
        )

    return {
        "code": "loss_aversion",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, max(0, (ratio - 1) * 50)), 1),
        "value_label": f"losers {ratio:.1f}× winners",
        "one_liner": one_liner,
        "evidence": {
            "winners_count": len(winners),
            "losers_count": len(losers),
            "winners_avg_size_usd": round(win_avg, 2),
            "losers_avg_size_usd": round(loss_avg, 2),
            "ratio": round(ratio, 2),
        },
        "references": [
            "Kahneman & Tversky (1979) — Prospect theory: an analysis of decision under risk.",
        ],
    }


# ─── Detector 4: Averaging Down sin tesis ────────────────────────────────────


def detect_averaging_down(ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compras del mismo ticker a precios cada vez más bajos en una ventana
    de < 60 días. Sin un catalizador o tesis explícita, suele indicar que
    el inversor está intentando "salvar" la posición original (otro síntoma
    de loss aversion).

    Detección: para cada ticker, agrupar las COMPRAS. Si hay ≥2 compras en
    < 60 días con precio descendente, flag.
    """
    # Tomamos COMPRAS — generalmente registradas como op_type='Compra' o
    # 'COMPRA' o las que tienen entry_price pero no exit_price.
    buys = []
    for o in ops:
        op_type = (o.get("op_type") or "").lower()
        if "compra" in op_type or "buy" in op_type:
            d = _parse_date(o.get("date"))
            price = o.get("entry_price")
            if d and price is not None and price > 0:
                buys.append({"asset": o.get("asset"), "date": d, "price": float(price)})

    if not buys:
        # Sin compras detectables → no es "data insuficiente" sino "no aplica".
        # Devolvemos un positivo con total_instances=0 para que el shape sea
        # consistente con las otras ramas del detector.
        return {
            "code": "averaging_down",
            "title": "Sin promedios a la baja detectados",
            "severity": "positive",
            "detected": False,
            "score": 0,
            "value_label": "0 instancias",
            "one_liner": "No detectamos compras del mismo ticker a precios decrecientes.",
            "evidence": {
                "instances": [],
                "total_instances": 0,
                "avg_drop_pct": 0,
                "total_assets_checked": 0,
            },
            "references": [
                "Odean (1998) — Are investors reluctant to realize their losses?",
            ],
        }

    # Agrupar por asset y ordenar cronológicamente
    by_asset: Dict[str, List[Dict[str, Any]]] = {}
    for b in buys:
        by_asset.setdefault(b["asset"], []).append(b)
    for asset, group in by_asset.items():
        group.sort(key=lambda x: x["date"])

    # Detectar secuencias de compras descendentes en < 60 días
    instances = []
    for asset, group in by_asset.items():
        if len(group) < 2:
            continue
        for i in range(1, len(group)):
            prev = group[i - 1]
            cur = group[i]
            gap_days = (cur["date"] - prev["date"]).days
            if gap_days > 60:
                continue
            if cur["price"] < prev["price"] * 0.95:  # ≥5% más bajo
                drop_pct = (cur["price"] / prev["price"] - 1) * 100
                instances.append({
                    "asset": asset,
                    "first_buy": {"date": prev["date"].isoformat()[:10], "price": prev["price"]},
                    "second_buy": {"date": cur["date"].isoformat()[:10], "price": cur["price"]},
                    "gap_days": gap_days,
                    "price_drop_pct": round(drop_pct, 2),
                })

    if not instances:
        return {
            "code": "averaging_down",
            "title": "Sin promedios a la baja detectados",
            "severity": "positive",
            "detected": False,
            "score": 0,
            "value_label": "0 instancias",
            "one_liner": "No detectamos compras del mismo ticker a precios decrecientes en ventanas cortas.",
            "evidence": {
                "instances": [],
                "total_instances": 0,
                "avg_drop_pct": 0,
                "total_assets_checked": len(by_asset),
            },
            "references": [
                "Odean (1998) — Are investors reluctant to realize their losses?",
            ],
        }

    # Severidad: cuántas instancias y qué tan profundo el average down
    instances_count = len(instances)
    avg_drop = sum(abs(i["price_drop_pct"]) for i in instances) / instances_count

    if instances_count >= 5 or avg_drop >= 20:
        severity = "high"
        title = "Promedio a la baja recurrente"
        one_liner = (
            f"Detectamos {instances_count} instancias de promediar a la baja en <60 días "
            f"(caída promedio {avg_drop:.1f}%). Asegurate de tener tesis para cada compra."
        )
    elif instances_count >= 2:
        severity = "medium"
        title = "Algunos promedios a la baja sin tesis aparente"
        one_liner = (
            f"{instances_count} compras del mismo ticker a precios decrecientes en <60 días. "
            "Verificá que cada una tenga catalizador, no solo \"está más barato\"."
        )
    else:
        severity = "low"
        title = "Una instancia de promediar a la baja"
        one_liner = f"1 compra reciente a precio menor en <60 días. Asegurate que sea por tesis, no por anchoring."

    return {
        "code": "averaging_down",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, instances_count * 15 + avg_drop * 1.5), 1),
        "value_label": f"{instances_count} instancia{'s' if instances_count != 1 else ''}",
        "one_liner": one_liner,
        "evidence": {
            "instances": instances[:10],  # cap por payload
            "total_instances": instances_count,
            "avg_drop_pct": round(avg_drop, 2),
            "total_assets_checked": len(by_asset),
        },
        "references": [
            "Odean (1998) — Are investors reluctant to realize their losses?",
        ],
    }


# ─── Orchestrator ────────────────────────────────────────────────────────────


def _not_enough_data(code: str, reason: str) -> Dict[str, Any]:
    """Shape uniforme para "data insuficiente" — el frontend lo trata como
    "skeleton" sin alarma."""
    return {
        "code": code,
        "title": "Datos insuficientes",
        "severity": "neutral",
        "detected": False,
        "score": 0,
        "value_label": "—",
        "one_liner": reason,
        "evidence": {},
        "references": [],
        "insufficient_data": True,
    }


def build_behavioral_insights(
    operations: List[Dict[str, Any]],
    positions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Orchestrator — corre los 4 detectores y devuelve un payload uniforme.

    Args:
        operations: lista de operations crudas del user (todas las cerradas).
        positions: lista de positions activas (para overtrade ratio si está disponible).

    Returns:
        {
            cards: [<detector output>, ...]  # siempre las 4, aunque algunas
                                              # tengan insufficient_data=True
            summary: {
                total_detected: int,
                total_high: int,
                total_medium: int,
                total_positive: int,
            },
            generated_at: ISO timestamp,
        }
    """
    ops = operations or []
    cards = [
        detect_disposition_effect(ops),
        detect_overtrade(ops, positions),
        detect_loss_aversion(ops),
        detect_averaging_down(ops),
    ]

    high = sum(1 for c in cards if c["severity"] == "high")
    medium = sum(1 for c in cards if c["severity"] == "medium")
    positive = sum(1 for c in cards if c["severity"] == "positive")
    detected = sum(1 for c in cards if c.get("detected"))

    return {
        "cards": cards,
        "summary": {
            "total_detected": detected,
            "total_high": high,
            "total_medium": medium,
            "total_positive": positive,
            "total_cards": len(cards),
        },
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
