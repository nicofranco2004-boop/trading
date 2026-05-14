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


# ─── Detector 5: Win rate vs Payoff ratio ────────────────────────────────────


def detect_winrate_payoff(ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Win rate solo es engañoso: 70% wins con payoff 0.3 (gano $30, pierdo $100)
    es PEOR que 40% wins con payoff 2.5. La métrica honesta es la combinación.

    Expectancy = (win_rate × avg_win) − (loss_rate × avg_loss)
    Si expectancy < 0 → estás perdiendo plata en agregado, aunque tengas
    win_rate alto.
    """
    trades = [o for o in ops if _is_trade(o)]
    winners = [o for o in trades if (o.get("pnl_usd") or 0) > 0]
    losers = [o for o in trades if (o.get("pnl_usd") or 0) < 0]

    if len(winners) + len(losers) < 5:
        return _not_enough_data("winrate_payoff", "Necesitás al menos 5 operaciones cerradas para medir win rate.")

    total = len(winners) + len(losers)
    win_rate = len(winners) / total * 100
    avg_win = sum(o["pnl_usd"] for o in winners) / len(winners) if winners else 0
    avg_loss = abs(sum(o["pnl_usd"] for o in losers) / len(losers)) if losers else 0
    payoff = avg_win / avg_loss if avg_loss > 0 else float("inf")
    expectancy = (win_rate / 100) * avg_win - ((100 - win_rate) / 100) * avg_loss

    # Combinación win_rate × payoff define la severidad
    if expectancy < 0:
        severity = "high"
        title = "Tu estrategia pierde plata en agregado"
        one_liner = (
            f"Win rate {win_rate:.0f}% con payoff {payoff:.2f}× resulta en expectancy "
            f"negativo ({expectancy:+.2f} USD/op). Aunque ganás más veces que perdés, "
            "el tamaño de las pérdidas se come las ganancias."
        )
    elif win_rate >= 60 and payoff < 0.7:
        severity = "medium"
        title = "Win rate alto pero pérdidas grandes"
        one_liner = (
            f"Ganás el {win_rate:.0f}% de las veces pero tu payoff es {payoff:.2f}× — "
            "las pocas pérdidas se llevan gran parte de las ganancias."
        )
    elif win_rate < 40 and payoff < 1.5:
        severity = "medium"
        title = "Win rate bajo sin compensación"
        one_liner = (
            f"Ganás solo el {win_rate:.0f}% de las veces y el payoff es {payoff:.2f}×. "
            "Para que funcione un win rate bajo, el payoff debería ser ≥2×."
        )
    elif expectancy > 0 and payoff >= 1.5:
        severity = "positive"
        title = "Combinación win rate + payoff sólida"
        one_liner = (
            f"Win rate {win_rate:.0f}% con payoff {payoff:.2f}× = expectancy "
            f"{expectancy:+.2f} USD por operación. Funciona."
        )
    else:
        severity = "low"
        title = "Win rate y payoff equilibrados"
        one_liner = (
            f"Ganás el {win_rate:.0f}% con payoff {payoff:.2f}×. Expectancy "
            f"{expectancy:+.2f} USD/op — positivo pero ajustado."
        )

    return {
        "code": "winrate_payoff",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, max(0, -expectancy / max(avg_loss, 1) * 100 if expectancy < 0 else 0)), 1),
        "value_label": f"{win_rate:.0f}% · payoff {payoff:.2f}×",
        "one_liner": one_liner,
        "evidence": {
            "win_rate_pct": round(win_rate, 1),
            "winners_count": len(winners),
            "losers_count": len(losers),
            "total_trades": total,
            "avg_win_usd": round(avg_win, 2),
            "avg_loss_usd": round(avg_loss, 2),
            "payoff_ratio": round(payoff, 2) if payoff != float("inf") else None,
            "expectancy_usd": round(expectancy, 2),
        },
        "references": [
            "Van Tharp (1998) — Trade Your Way to Financial Freedom (expectancy formula).",
        ],
    }


# ─── Detector 6: Concentration ───────────────────────────────────────────────


def detect_concentration(positions: List[Dict[str, Any]], prices: Optional[Dict[str, float]] = None,
                          tc_blue: float = 1415.0) -> Dict[str, Any]:
    """Concentración del portfolio: top 1 / top 3 holdings como % del total.
    Top 1 > 40% → high. Top 1 > 25% o Top 3 > 70% → medium.

    Convierte valores ARS al blue para comparar con USD.
    """
    if not positions:
        return _not_enough_data("concentration", "No tenés posiciones para analizar.")

    # Valor en USD por asset (consolidar entre brokers)
    by_asset: Dict[str, float] = {}
    for p in positions:
        if p.get("is_cash"):
            continue
        asset = (p.get("asset") or "").upper()
        if not asset:
            continue
        # Si tengo prices, uso precio actual × quantity. Sino, uso invested.
        price = (prices or {}).get(asset)
        if price is None:
            price = (prices or {}).get(asset + ".BA")
        qty = p.get("quantity") or 0
        if price is not None and qty:
            value_native = price * qty
        else:
            value_native = p.get("invested") or 0
        # Si el broker es ARS, convertir a USD al blue.
        # Detección simple: si el invested original parece estar en pesos
        # (>10000 sin precio en USD razonable), asumimos ARS.
        broker = (p.get("broker") or "").lower()
        if "cocos" in broker or "iol" in broker or "bull" in broker or "balanz" in broker:
            value_usd = value_native / tc_blue
        else:
            value_usd = value_native
        by_asset[asset] = by_asset.get(asset, 0) + value_usd

    if not by_asset:
        return _not_enough_data("concentration", "No pudimos valuar tus posiciones.")

    total = sum(by_asset.values())
    if total <= 0:
        return _not_enough_data("concentration", "Valor del portfolio es cero.")

    sorted_assets = sorted(by_asset.items(), key=lambda x: -x[1])
    top1_asset, top1_value = sorted_assets[0]
    top1_pct = (top1_value / total) * 100
    top3_pct = (sum(v for _, v in sorted_assets[:3]) / total) * 100
    top5_pct = (sum(v for _, v in sorted_assets[:5]) / total) * 100

    if top1_pct >= 40:
        severity = "high"
        title = f"Concentración alta en {top1_asset}"
        one_liner = (
            f"{top1_asset} representa el {top1_pct:.0f}% de tu portfolio. "
            "Una caída fuerte de ese activo te lastima desproporcionadamente."
        )
    elif top1_pct >= 25 or top3_pct >= 70:
        severity = "medium"
        title = f"{top1_asset} pesa fuerte en tu cartera"
        one_liner = (
            f"Top 1 = {top1_pct:.0f}%, Top 3 = {top3_pct:.0f}%. "
            "El portfolio depende mucho de pocos activos."
        )
    elif top1_pct < 15 and top3_pct < 40:
        severity = "positive"
        title = "Portfolio bien diversificado"
        one_liner = (
            f"Tu activo más grande ({top1_asset}) representa {top1_pct:.1f}% — "
            "concentración baja, riesgo individual contenido."
        )
    else:
        severity = "low"
        title = "Concentración moderada"
        one_liner = f"Top 1 = {top1_pct:.0f}%, Top 3 = {top3_pct:.0f}%. Diversificación razonable."

    return {
        "code": "concentration",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, top1_pct * 2), 1),
        "value_label": f"Top 1: {top1_pct:.0f}%",
        "one_liner": one_liner,
        "evidence": {
            "top_asset": top1_asset,
            "top1_pct": round(top1_pct, 1),
            "top3_pct": round(top3_pct, 1),
            "top5_pct": round(top5_pct, 1),
            "total_assets": len(by_asset),
            "total_value_usd": round(total, 2),
            "top_5": [
                {"asset": a, "value_usd": round(v, 2), "pct": round(v / total * 100, 1)}
                for a, v in sorted_assets[:5]
            ],
        },
        "references": [
            "Markowitz (1952) — Portfolio selection.",
        ],
    }


# ─── Detector 7: Home Bias ───────────────────────────────────────────────────


def detect_home_bias(positions: List[Dict[str, Any]], prices: Optional[Dict[str, float]] = None,
                      tc_blue: float = 1415.0) -> Dict[str, Any]:
    """Home bias: tendencia a sobre-exponerse a activos del país propio.
    Para retail AR, >65% en assets locales (CEDEARs, bonos AR, acciones AR)
    es home bias clásico. <10% también es señal: bajo nivel de protección
    en moneda local.
    """
    if not positions:
        return _not_enough_data("home_bias", "No tenés posiciones para analizar.")

    def is_ar_asset(p):
        asset = (p.get("asset") or "").upper()
        broker = (p.get("broker") or "").lower()
        # Heurística: brokers AR + sufijo .BA + bonos AR conocidos
        if "cocos" in broker or "iol" in broker or "bull" in broker or "balanz" in broker:
            return True
        if asset.endswith(".BA"):
            return True
        ar_bonds_prefix = ("AL", "GD", "AE", "TX", "TZ", "PAR", "DIC")
        if any(asset.startswith(p) for p in ar_bonds_prefix) and len(asset) <= 5:
            return True
        return False

    ar_value = 0
    intl_value = 0
    for p in positions:
        if p.get("is_cash"):
            continue
        asset = (p.get("asset") or "").upper()
        if not asset:
            continue
        price = (prices or {}).get(asset) or (prices or {}).get(asset + ".BA")
        qty = p.get("quantity") or 0
        value_native = price * qty if (price and qty) else (p.get("invested") or 0)
        broker = (p.get("broker") or "").lower()
        if "cocos" in broker or "iol" in broker or "bull" in broker or "balanz" in broker:
            value_usd = value_native / tc_blue
        else:
            value_usd = value_native
        if is_ar_asset(p):
            ar_value += value_usd
        else:
            intl_value += value_usd

    total = ar_value + intl_value
    if total <= 0:
        return _not_enough_data("home_bias", "No pudimos valuar tus posiciones.")

    ar_pct = (ar_value / total) * 100

    if ar_pct >= 80:
        severity = "high"
        title = "Home bias fuerte hacia Argentina"
        one_liner = (
            f"{ar_pct:.0f}% de tu portfolio está en activos AR. "
            "Riesgo país concentrado — una crisis local te golpea casi todo el patrimonio."
        )
    elif ar_pct >= 65:
        severity = "medium"
        title = "Sobre-exposición a Argentina"
        one_liner = (
            f"{ar_pct:.0f}% en activos AR. "
            "El riesgo país está concentrado — diversificar a USD/internacional reduce drawdown."
        )
    elif ar_pct < 5 and total > 1000:
        severity = "medium"
        title = "Casi sin exposición a Argentina"
        one_liner = (
            f"Solo el {ar_pct:.1f}% en AR. Si tu vida es en pesos (gastos, salario), "
            "podés sumar algo de exposición ARS/CEDEARs para hedge natural."
        )
    elif 20 <= ar_pct <= 50:
        severity = "positive"
        title = "Balance AR/internacional saludable"
        one_liner = f"{ar_pct:.0f}% AR + {100 - ar_pct:.0f}% internacional — diversificación geográfica equilibrada."
    else:
        severity = "low"
        title = "Balance moderado AR/internacional"
        one_liner = f"{ar_pct:.0f}% AR + {100 - ar_pct:.0f}% internacional."

    return {
        "code": "home_bias",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(abs(ar_pct - 35) * 1.5, 1),  # óptimo ~35%
        "value_label": f"{ar_pct:.0f}% AR",
        "one_liner": one_liner,
        "evidence": {
            "ar_pct": round(ar_pct, 1),
            "intl_pct": round(100 - ar_pct, 1),
            "ar_value_usd": round(ar_value, 2),
            "intl_value_usd": round(intl_value, 2),
            "total_value_usd": round(total, 2),
        },
        "references": [
            "French & Poterba (1991) — Investor diversification and international equity markets.",
        ],
    }


# ─── Detector 8: Cash drag ───────────────────────────────────────────────────


def detect_cash_drag(positions: List[Dict[str, Any]], tc_blue: float = 1415.0) -> Dict[str, Any]:
    """% del portfolio en cash. Cash en USD es razonable defensivo, pero
    cash ARS es destructivo dada la inflación. Tratamos los dos.
    """
    if not positions:
        return _not_enough_data("cash_drag", "No tenés posiciones para analizar.")

    cash_usd = 0
    cash_ars_usd_equiv = 0
    invested_usd = 0
    for p in positions:
        broker = (p.get("broker") or "").lower()
        is_ars_broker = any(s in broker for s in ("cocos", "iol", "bull", "balanz"))
        invested_native = p.get("invested") or 0
        value_usd = (invested_native / tc_blue) if is_ars_broker else invested_native
        if p.get("is_cash"):
            if is_ars_broker:
                cash_ars_usd_equiv += value_usd
            else:
                cash_usd += value_usd
        else:
            invested_usd += value_usd

    total = cash_usd + cash_ars_usd_equiv + invested_usd
    if total <= 0:
        return _not_enough_data("cash_drag", "Portfolio sin valor.")

    cash_total = cash_usd + cash_ars_usd_equiv
    cash_pct = (cash_total / total) * 100
    cash_ars_pct = (cash_ars_usd_equiv / total) * 100

    if cash_pct >= 30 or cash_ars_pct >= 15:
        severity = "high"
        title = "Demasiado cash sin invertir"
        if cash_ars_pct >= 15:
            one_liner = (
                f"{cash_ars_pct:.0f}% de tu portfolio está en cash ARS. "
                "Con inflación del ~3% mensual, ese capital pierde poder de compra todos los días."
            )
        else:
            one_liner = (
                f"{cash_pct:.0f}% de tu portfolio está en cash. "
                "Pierde el costo de oportunidad del mercado: si esperás un crash, asignate plazo."
            )
    elif cash_pct >= 20:
        severity = "medium"
        title = "Cash relevante esperando entrar"
        one_liner = (
            f"Tenés {cash_pct:.0f}% en cash. Si es estratégico para entrar en una corrección, "
            "OK. Si lleva >3 meses esperando, considerá DCA gradual."
        )
    elif cash_pct < 5:
        severity = "low"
        title = "Sin cushion de cash"
        one_liner = (
            f"Solo {cash_pct:.1f}% en cash. Aprovechás todo el capital pero te quedás sin "
            "dry powder para aprovechar caídas."
        )
    else:
        severity = "positive"
        title = "Nivel de cash equilibrado"
        one_liner = f"{cash_pct:.0f}% en cash — cushion razonable para liquidez sin perder oportunidad."

    return {
        "code": "cash_drag",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, abs(cash_pct - 10) * 3), 1),
        "value_label": f"{cash_pct:.0f}% en cash",
        "one_liner": one_liner,
        "evidence": {
            "cash_pct": round(cash_pct, 1),
            "cash_ars_pct": round(cash_ars_pct, 1),
            "cash_usd_amount": round(cash_usd, 2),
            "cash_ars_usd_equiv": round(cash_ars_usd_equiv, 2),
            "invested_usd": round(invested_usd, 2),
            "total_usd": round(total, 2),
        },
        "references": [
            "Cash drag literature — Vanguard research on optimal cash allocation.",
        ],
    }


# ─── Detector 9: Pérdida por inflación AR ────────────────────────────────────


def detect_inflation_loss(positions: List[Dict[str, Any]], inflation_monthly: Optional[Dict[str, float]] = None,
                           tc_blue: float = 1415.0) -> Dict[str, Any]:
    """Cuánto poder de compra perdiste por mantener cash en ARS.

    Args:
        positions: posiciones del user
        inflation_monthly: dict { 'YYYY-MM': pct } con inflación mensual AR del último año
    """
    if not positions:
        return _not_enough_data("inflation_loss", "No tenés posiciones.")

    # Cash ARS total (en ARS)
    cash_ars_pesos = 0
    for p in positions:
        if not p.get("is_cash"):
            continue
        broker = (p.get("broker") or "").lower()
        is_ars = any(s in broker for s in ("cocos", "iol", "bull", "balanz"))
        if is_ars:
            cash_ars_pesos += p.get("invested") or 0

    if cash_ars_pesos <= 0:
        return {
            "code": "inflation_loss",
            "title": "Sin cash ARS afectado por inflación",
            "severity": "positive",
            "detected": False,
            "score": 0,
            "value_label": "—",
            "one_liner": "No tenés cash en pesos en tus brokers — la inflación AR no te está erosionando capital ocioso.",
            "evidence": {"cash_ars_pesos": 0, "inflation_cum_pct": 0, "loss_pesos": 0, "loss_usd": 0},
            "references": ["INDEC — Índice de Precios al Consumidor."],
        }

    # Inflación acumulada últimos 12 meses (multiplicativa)
    if not inflation_monthly:
        # Fallback: estimación conservadora 60% anual si no hay benchmark
        inflation_cum_pct = 60.0
    else:
        keys = sorted(inflation_monthly.keys(), reverse=True)[:12]
        cum = 1
        for k in keys:
            val = inflation_monthly.get(k)
            if val is not None:
                cum *= 1 + val / 100
        inflation_cum_pct = (cum - 1) * 100

    # Pérdida de poder de compra: cash_ars × (inflación / (1 + inflación))
    loss_pesos = cash_ars_pesos * (inflation_cum_pct / (100 + inflation_cum_pct))
    loss_usd = loss_pesos / tc_blue

    if loss_usd >= 500 or inflation_cum_pct >= 100:
        severity = "high"
        title = "Pérdida grande por inflación"
        one_liner = (
            f"Tu cash en pesos perdió ~US$ {loss_usd:,.0f} de poder de compra en los últimos 12 meses "
            f"(inflación acumulada {inflation_cum_pct:.0f}%). Invertir aunque sea en MEP o Lecaps lo hubiera evitado."
        )
    elif loss_usd >= 100:
        severity = "medium"
        title = "Inflación erosionando tu cash ARS"
        one_liner = (
            f"Perdiste ~US$ {loss_usd:,.0f} en poder de compra. "
            "Considerá MEP, Lecaps en pesos o CEDEARs para hedge."
        )
    else:
        severity = "low"
        title = "Impacto bajo de inflación"
        one_liner = f"Tu cash ARS es chico — pérdida estimada US$ {loss_usd:,.0f}."

    return {
        "code": "inflation_loss",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, loss_usd / 50), 1),
        "value_label": f"−US$ {loss_usd:,.0f}",
        "one_liner": one_liner,
        "evidence": {
            "cash_ars_pesos": round(cash_ars_pesos, 2),
            "inflation_cum_pct": round(inflation_cum_pct, 1),
            "loss_pesos": round(loss_pesos, 2),
            "loss_usd": round(loss_usd, 2),
        },
        "references": [
            "INDEC — Índice de Precios al Consumidor (IPC).",
        ],
    }


# ─── Detector 10: Tu yo de hace X meses (no-trade counterfactual) ────────────


def detect_counterfactual(ops: List[Dict[str, Any]], prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Pregunta: ¿qué hubiera pasado si NO hubieras cerrado tus posiciones?

    Para cada venta cerrada (op_type ≠ Compra/Dividendo), comparamos:
    - PnL realizado en USD (el que registraste al vender)
    - PnL hipotético: precio actual del asset × quantity vendido − costo

    Si los precios subieron desde tu venta, hubieras ganado más. Si bajaron,
    bien hiciste. Suma de diferencias = "lo que perdiste por tradear".

    Requiere precios actuales (prices dict).
    """
    trades = [o for o in ops if _is_trade(o)]
    if len(trades) < 3 or not prices:
        return _not_enough_data("counterfactual", "Necesitás al menos 3 trades cerrados + precios actuales.")

    realized_total = 0
    hypothetical_total = 0
    breakdown = []
    for o in trades:
        asset = (o.get("asset") or "").upper()
        if not asset:
            continue
        qty = o.get("quantity") or 0
        exit_price = o.get("exit_price") or 0
        entry_price = o.get("entry_price") or 0
        cur_price = prices.get(asset) or prices.get(asset + ".BA")
        if cur_price is None or qty == 0:
            continue
        realized = (exit_price - entry_price) * qty
        hypothetical = (cur_price - entry_price) * qty
        delta = hypothetical - realized
        realized_total += realized
        hypothetical_total += hypothetical
        breakdown.append({
            "asset": asset,
            "exit_price": exit_price,
            "current_price": cur_price,
            "delta_usd": round(delta, 2),
            "exit_date": o.get("date"),
        })

    if not breakdown:
        return _not_enough_data("counterfactual", "No pudimos cruzar tus ventas con precios actuales.")

    delta_total = hypothetical_total - realized_total

    if delta_total > 1000:
        severity = "high"
        title = "Hubieras ganado más NO vendiendo"
        one_liner = (
            f"Si no hubieras cerrado tus ventas anteriores, hoy tendrías ~US$ {delta_total:,.0f} más. "
            "Vender ganadoras temprano costó plata real."
        )
    elif delta_total > 300:
        severity = "medium"
        title = "Vender temprano te costó algo de upside"
        one_liner = (
            f"Hubieras hecho ~US$ {delta_total:,.0f} más si mantenías. "
            "No siempre pasa, pero es interesante mirar el patrón."
        )
    elif delta_total < -300:
        severity = "positive"
        title = "Vender fue acertado"
        one_liner = (
            f"Hubieras perdido ~US$ {abs(delta_total):,.0f} más si mantenías. "
            "Cerrar a tiempo fue buena decisión."
        )
    else:
        severity = "low"
        title = "Tus ventas fueron neutrales"
        one_liner = f"La diferencia con haber mantenido es de apenas US$ {delta_total:,.0f}."

    # Ordenar breakdown por delta absoluto
    breakdown.sort(key=lambda x: -abs(x["delta_usd"]))
    return {
        "code": "counterfactual",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, abs(delta_total) / 100), 1),
        "value_label": f"{'+' if delta_total >= 0 else '−'}US$ {abs(delta_total):,.0f}",
        "one_liner": one_liner,
        "evidence": {
            "realized_total_usd": round(realized_total, 2),
            "hypothetical_total_usd": round(hypothetical_total, 2),
            "delta_total_usd": round(delta_total, 2),
            "trades_analyzed": len(breakdown),
            "top_misses": breakdown[:5],  # cap
        },
        "references": [
            "Kahneman (2011) — Thinking, Fast and Slow (counterfactual thinking).",
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
    prices: Optional[Dict[str, float]] = None,
    inflation_monthly: Optional[Dict[str, float]] = None,
    tc_blue: float = 1415.0,
) -> Dict[str, Any]:
    """Orchestrator — corre los 10 detectores y devuelve un payload uniforme.

    Args:
        operations: lista de operations crudas del user (todas las cerradas).
        positions: lista de positions activas.
        prices: dict { 'TICKER': precio_actual } para concentration / counterfactual.
        inflation_monthly: dict { 'YYYY-MM': pct } de inflación AR mensual.
        tc_blue: cotización del dólar para convertir valores ARS.

    Returns:
        {
            cards: [<detector output>, ...]  # siempre las 10, algunas con insufficient_data
            summary: { total_detected, total_high, total_medium, total_positive, total_cards },
            generated_at: ISO timestamp,
        }
    """
    ops = operations or []
    pos = positions or []
    cards = [
        # Sprint 3 — los 4 originales
        detect_disposition_effect(ops),
        detect_overtrade(ops, pos),
        detect_loss_aversion(ops),
        detect_averaging_down(ops),
        # Sprint 3.1
        detect_concentration(pos, prices, tc_blue),
        detect_inflation_loss(pos, inflation_monthly, tc_blue),
        detect_counterfactual(ops, prices),
        # Sprint 3.2
        detect_winrate_payoff(ops),
        detect_home_bias(pos, prices, tc_blue),
        detect_cash_drag(pos, tc_blue),
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
