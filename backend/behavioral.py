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


def _position_size_usd(op: Dict[str, Any], tc_blue: float = 1415.0) -> float:
    """Notional al entrar (entry_price × quantity), SIEMPRE en USD.

    entry_price está en la moneda nativa de la op (ARS para brokers AR/CEDEAR,
    USD para brokers US). Sin convertir, sumar notionals de distintas monedas
    mezcla pesos con dólares (turnover y loss-aversion daban veredictos
    invertidos). Convertimos ARS→USD con tc_blue."""
    ep = op.get("entry_price")
    qty = op.get("quantity")
    if ep is None or qty is None:
        return 0.0
    notional = float(ep) * float(qty)
    if _native_ccy(op) == "ARS" and tc_blue > 0:
        return notional / tc_blue
    return notional


# ─── Helpers de valuación + clasificación geográfica ─────────────────────────

# Brokers AR-resident — la moneda nativa de las posiciones está en ARS.
_AR_BROKER_HINTS = ("cocos", "iol", "bull", "balanz", "naranja", "pppi", "invertironline")

# Prefijos de bonos soberanos AR. Pattern: 2 letras + dígito al menos.
_AR_BOND_PREFIXES = ("AL", "GD", "AE", "TX", "TZ", "PARY", "DICY", "TZX")

# Acciones AR del Merval/panel local (NO CEDEARs). Lista curada — si aparece
# un ticker AR poco común, cae al fallback más abajo.
_AR_LOCAL_STOCKS = frozenset({
    "GGAL", "YPFD", "BMA", "PAMP", "TEN", "CRES", "COME", "ALUA", "ERAR",
    "MIRG", "CEPU", "EDN", "TGSU2", "TGNO4", "BBAR", "TRAN", "SUPV", "BYMA",
    "VALO", "TXAR", "LOMA", "AGRO", "HARG", "CVH",
})


def _is_ars_broker(broker: Optional[str]) -> bool:
    if not broker:
        return False
    b = broker.lower()
    return any(h in b for h in _AR_BROKER_HINTS)


# Tokens de cash en dólares (stablecoins + dólar). Si el asset es uno de estos,
# la posición está en USD aunque el broker tenga nombre AR.
_USD_CASH_TOKENS = frozenset({"USD", "USDT", "USDC", "USDD", "DAI"})


def _is_usd_subbroker(broker: Optional[str]) -> bool:
    """Sub-broker en dólares: convención '<Padre> · USD' (main.py _ensure_usd_sibling).
    El padre puede ser AR (ej. 'Cocos Capital · USD') pero el sub-broker está
    denominado en USD. _is_ars_broker matchea el nombre del padre y lo trataría
    como ARS — por eso necesitamos detectar el sufijo explícitamente."""
    if not broker:
        return False
    b = broker.lower().strip()
    return b.endswith("· usd") or b.endswith("·usd") or b.endswith("- usd") or b.endswith(" usd")


def _native_ccy(p: Dict[str, Any]) -> str:
    """Moneda nativa REAL de una position/op: 'ARS' o 'USD'.

    CRÍTICO: NO inferir la moneda solo por el nombre del broker. El sub-broker
    'Cocos Capital · USD' contiene 'cocos' (matchea _is_ars_broker) pero está en
    dólares. Prioridad de resolución:
      1. currency explícita de la fila (positions.currency: 'ARS'/'USD'/'USDT'…).
      2. asset = token de cash USD (USDT/USDC/…) → USD; asset == 'ARS' → ARS.
      3. sub-broker '· USD' → USD.
      4. broker AR → ARS.
      5. default → USD.
    """
    c = (p.get("currency") or "").strip().upper()
    if c == "ARS":
        return "ARS"
    if c == "USD" or c in _USD_CASH_TOKENS:
        return "USD"
    asset = (p.get("asset") or "").strip().upper()
    if asset in _USD_CASH_TOKENS:
        return "USD"
    if asset == "ARS":
        return "ARS"
    broker = p.get("broker") or ""
    if _is_usd_subbroker(broker):
        return "USD"
    if _is_ars_broker(broker):
        return "ARS"
    return "USD"


def stamp_positions_currency(positions: List[Dict[str, Any]],
                             broker_ccy: Dict[str, str]) -> List[Dict[str, Any]]:
    """Estampa positions[].currency desde la moneda AUTORITATIVA del broker
    (broker_ccy = {name: 'ARS'|'USD'|'USDT'|…}) cuando la fila no la trae.

    CRÍTICO: _native_ccy cae a una heurística por NOMBRE de broker para las
    posiciones con currency NULL, y esa lista (_AR_BROKER_HINTS) NO cubre todos
    los brokers AR (ej. 'Santander', 'Galicia', 'PPI', 'Mercado Pago'). Sin este
    estampado, un holding en pesos en uno de esos brokers se contaría como USD
    (~tc_blue× inflado). Todo path que cargue positions para análisis debe
    llamar a esta función con brokers.currency antes de valuar."""
    if not broker_ccy:
        return positions
    for p in positions:
        if (p.get("currency") or "").strip():
            continue
        bc = (broker_ccy.get(p.get("broker") or "") or "").strip().upper()
        if bc:
            p["currency"] = "ARS" if bc == "ARS" else "USD"
    return positions


def _is_ar_bond(asset: str) -> bool:
    """True si el ticker matchea un bono soberano AR conocido."""
    if not asset:
        return False
    a = asset.upper()
    # PARY / DICY son nombres específicos
    if a in ("PARY", "DICY"):
        return True
    # Pattern típico: 2-3 letras + dígito (AL30, GD35, TX26, TZX26, AE38, etc.)
    for pref in _AR_BOND_PREFIXES:
        if a.startswith(pref):
            rest = a[len(pref):]
            if rest and rest[0].isdigit():
                return True
    return False


def _is_cedear(asset: str) -> bool:
    """CEDEAR = ticker .BA que NO es un bono ni una acción AR local."""
    if not asset:
        return False
    a = asset.upper()
    if not a.endswith(".BA"):
        return False
    # Bonos AR a veces se exportan con .BA — primero filtrar esos
    base = a[:-3]
    if _is_ar_bond(base):
        return False
    if base in _AR_LOCAL_STOCKS:
        return False
    return True


def _is_ar_economic_exposure(asset: str, broker: Optional[str] = None) -> bool:
    """Exposición económica AR — distinto de "registrado en broker AR".

    Un CEDEAR (AAPL.BA en Cocos) está REGISTRADO en un broker AR pero la
    exposición económica es a Apple, no a Argentina. Para análisis de
    home bias / riesgo país, lo que importa es la exposición económica.

    Lo único que cuenta como AR:
    - Bonos soberanos AR (AL30, GD30, etc.)
    - Acciones del Merval locales (GGAL, YPFD, etc.)
    - Cash ARS en cualquier broker (es exposición a peso)
    """
    if not asset:
        # Sin asset clarificable — si está en broker AR, asumimos cash ARS
        return _is_ars_broker(broker)
    a = asset.upper()
    if a == "ARS":
        return True
    if _is_ar_bond(a):
        return True
    if a in _AR_LOCAL_STOCKS:
        return True
    if _is_cedear(a):
        # CEDEAR es internacional aunque esté en Cocos
        return False
    # Para CEDEARs registrados sin .BA (raro pero posible), si está en broker AR
    # y NO es bono/acción AR conocida, probablemente es algo internacional.
    # Default: NO es AR.
    return False


def _resolve_price(asset: str, broker: Optional[str], prices: Optional[Dict[str, float]]) -> Optional[float]:
    """Resuelve el precio actual del activo en la MONEDA NATIVA del broker.

    CRÍTICO: para brokers AR (Cocos/IOL/etc) los tickers normalmente son
    CEDEARs que cotizan en ARS. El precio del ticker US (ej. META US$ 618)
    NO es comparable con el buy_price del CEDEAR (en ARS, ej. $38.300).

    Heurística:
    - Broker AR + asset con .BA → prices[asset]  (ARS)
    - Broker AR + asset sin .BA → prices[asset + '.BA']  (ARS — siempre buscamos AR)
    - Broker no-AR + asset → prices[asset]  (USD)

    Devuelve None si no hay precio coherente con la moneda del broker.
    No hace fallback cruzado para evitar mezclar monedas.
    """
    if not prices or not asset:
        return None
    a = asset.upper()
    is_ars = _is_ars_broker(broker)
    if is_ars:
        # Broker AR: el precio que buscamos está en ARS. CEDEARs siempre con .BA.
        if a.endswith(".BA"):
            return prices.get(a)
        # Ticker sin .BA en broker AR — probablemente CEDEAR exportado sin sufijo.
        # Buscamos el .BA. NO usamos prices[a] sin sufijo porque sería el ticker
        # US en USD (mezcla de monedas → comparaciones absurdas).
        return prices.get(a + ".BA")
    # Broker no-AR (Schwab/IBKR/Binance): precio en USD directo.
    return prices.get(a)


def _position_value_usd(p: Dict[str, Any], prices: Optional[Dict[str, float]] = None,
                         tc_blue: float = 1415.0) -> float:
    """Valor USD-equivalente de una position. Maneja:
    - Cash (usa invested directo)
    - Posiciones con precio actual disponible (price × quantity)
    - Fallback a invested si no hay precio
    - Conversión ARS → USD para brokers AR
    """
    if not p:
        return 0.0
    asset = (p.get("asset") or "").upper()
    broker = p.get("broker") or ""
    # DOS ejes de moneda, distintos:
    #  - cost_ccy: moneda del cost basis (invested). Resuelta por _native_ccy
    #    (respeta sub-broker '· USD'). Decide si convertir `invested`.
    #  - price_is_ars: _resolve_price devuelve el precio .BA (ARS) para brokers
    #    AR-resident (incluido el sub-broker '· USD', cuyo CEDEAR cotiza en ARS).
    #    Decide si convertir el valor de mercado live.
    cost_ccy = _native_ccy(p)
    price_is_ars = _is_ars_broker(broker)
    qty = p.get("quantity") or 0
    invested_native = float(p.get("invested") or 0)

    # Cash — convertir solo si el cash es en pesos
    if p.get("is_cash"):
        if cost_ccy == "ARS":
            return invested_native / tc_blue if tc_blue > 0 else 0.0
        return invested_native

    # No-cash: preferimos precio actual × quantity.
    if qty:
        price = _resolve_price(asset, broker, prices)
        if price and price > 0:
            value_native = float(price) * float(qty)
            # El precio live de un broker AR está en ARS (.BA) → a USD.
            if price_is_ars and tc_blue > 0:
                return value_native / tc_blue
            return value_native

    # Fallback al cost basis (invested), en su moneda nativa.
    if cost_ccy == "ARS" and tc_blue > 0:
        return invested_native / tc_blue
    return invested_native


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


def detect_overtrade(ops: List[Dict[str, Any]], positions: Optional[List[Dict[str, Any]]] = None,
                     tc_blue: float = 1415.0, prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
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
        # USD-consistente: _position_value_usd convierte ARS→USD por posición.
        # Sumar invested crudo mezclaba pesos con dólares (turnover distorsionado).
        capital_avg = sum(_position_value_usd(p, prices, tc_blue) for p in positions if not p.get("is_cash"))
    if capital_avg <= 0:
        capital_avg = sum(abs(o.get("pnl_usd") or 0) for o in trades) * 5  # fallback

    # Notional total tradeado en el período (cada op convertida a USD)
    total_notional = sum(_position_size_usd(o, tc_blue) for o in trades)

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


def detect_loss_aversion(ops: List[Dict[str, Any]], tc_blue: float = 1415.0) -> Dict[str, Any]:
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

    win_sizes = [_position_size_usd(o, tc_blue) for o in winners]
    loss_sizes = [_position_size_usd(o, tc_blue) for o in losers]
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
        value_usd = _position_value_usd(p, prices, tc_blue)
        if value_usd <= 0:
            continue
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
    """Home bias: exposición económica a Argentina vs internacional.

    CRÍTICO: usamos exposición ECONÓMICA, no nominal por broker. Un CEDEAR
    (AAPL.BA en Cocos) está registrado en un broker AR pero la exposición
    económica es a Apple. Cuenta como INTERNACIONAL.

    Lo que cuenta como AR:
    - Bonos soberanos AR (AL30, GD30, TX26, etc.)
    - Acciones del Merval locales (GGAL, YPFD, BMA, PAMP, etc.)
    - Cash ARS

    Lo que cuenta como internacional:
    - CEDEARs (AAPL.BA, NVDA.BA — el subyacente es US)
    - Acciones / bonos / ETFs / crypto en brokers no-AR
    """
    if not positions:
        return _not_enough_data("home_bias", "No tenés posiciones para analizar.")

    ar_value = 0
    intl_value = 0
    for p in positions:
        if p.get("is_cash"):
            # Cash ARS (peso) = exposición AR; cash USD/USDT = internacional.
            # _native_ccy respeta el asset (USDT→USD) y el sub-broker '· USD'.
            value_usd = _position_value_usd(p, prices, tc_blue)
            if _native_ccy(p) == "ARS":
                ar_value += value_usd
            else:
                intl_value += value_usd
            continue
        asset = (p.get("asset") or "").upper()
        if not asset:
            continue
        value_usd = _position_value_usd(p, prices, tc_blue)
        if value_usd <= 0:
            continue
        if _is_ar_economic_exposure(asset, p.get("broker")):
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


def detect_cash_drag(positions: List[Dict[str, Any]], tc_blue: float = 1415.0,
                      prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """% del portfolio en cash. Cash en USD es razonable defensivo, pero
    cash ARS es destructivo dada la inflación. Tratamos los dos.
    """
    if not positions:
        return _not_enough_data("cash_drag", "No tenés posiciones para analizar.")

    cash_usd = 0
    cash_ars_usd_equiv = 0
    invested_usd = 0
    for p in positions:
        value_usd = _position_value_usd(p, prices, tc_blue)
        if p.get("is_cash"):
            # Cash en pesos vs dólares por moneda REAL (no por nombre de broker):
            # un USDT en 'Cocos · USD' es dólar, no peso.
            if _native_ccy(p) == "ARS":
                cash_ars_usd_equiv += value_usd
            else:
                cash_usd += value_usd
        else:
            invested_usd += value_usd

    total = cash_usd + cash_ars_usd_equiv + invested_usd
    if total <= 0:
        return _not_enough_data("cash_drag", "Portfolio sin valor.")

    cash_total = cash_usd + cash_ars_usd_equiv
    # Cash neto negativo: margen/deuda en USD o débito de registración (dólar-MEP)
    # pendiente. No es "cash drag" (cash ocioso) — evitamos un % sin sentido (−201%).
    if cash_total < 0:
        return {
            "code": "cash_drag",
            "title": "Cash neto negativo",
            "severity": "low",
            "detected": False,
            "score": 0,
            "value_label": "—",
            "one_liner": (
                "Tu balance de cash es negativo (margen/deuda en USD o un débito de "
                "registración pendiente). No aplica el análisis de cash ocioso."
            ),
            "evidence": {
                "cash_pct": 0,
                "cash_ars_pct": 0,
                "cash_usd_amount": round(cash_usd, 2),
                "cash_ars_usd_equiv": round(cash_ars_usd_equiv, 2),
                "invested_usd": round(invested_usd, 2),
                "total_usd": round(total, 2),
            },
            "references": ["Cash drag literature — Vanguard research on optimal cash allocation."],
        }
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

    # Cash ARS total (en ARS) — solo el cash REALMENTE en pesos.
    # _native_ccy excluye USDT/USD y el sub-broker '· USD' (que antes se sumaban
    # como pesos por el substring del nombre y se les aplicaba inflación AR).
    cash_ars_pesos = 0
    for p in positions:
        if not p.get("is_cash"):
            continue
        if _native_ccy(p) == "ARS":
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
    - PnL realizado en USD (`pnl_usd`, ya convertido al cerrar la op)
    - PnL hipotético: precio actual del asset × quantity vendido − costo

    Si los precios subieron desde tu venta, hubieras ganado más. Si bajaron,
    bien hiciste. Suma de diferencias = "lo que perdiste por tradear".

    ── Guard de moneda (crítico) ────────────────────────────────────────────
    `prices` viene de yfinance: precios en USD del ticker US (INTC, TSLA…).
    Solo es comparable contra operaciones denominadas en USD. Las ops en ARS
    (CEDEAR) tienen entry/exit en pesos; restarlas contra un precio en USD da
    basura (ej. INTC vendido a 32.640 ARS vs 134 USD ⇒ −1,3M ficticio, y el
    detector concluía SIEMPRE "vender fue acertado"). Como la columna
    `currency` de operations casi nunca está poblada, inferimos la moneda por
    el FX implícito del `pnl_usd` y omitimos las ventas que no están en USD.

    Requiere precios actuales (prices dict).
    """
    trades = [o for o in ops if _is_trade(o)]
    if len(trades) < 3 or not prices:
        return _not_enough_data("counterfactual", "Necesitás al menos 3 trades cerrados + precios actuales.")

    realized_total = 0.0
    hypothetical_total = 0.0
    breakdown = []
    skipped_fx = 0  # ventas omitidas por no estar en USD (no comparables)
    for o in trades:
        asset = (o.get("asset") or "").upper()
        if not asset:
            continue
        qty = o.get("quantity") or 0
        exit_price = o.get("exit_price") or 0
        entry_price = o.get("entry_price") or 0
        pnl_usd = o.get("pnl_usd")
        cur_price = prices.get(asset)  # solo el precio USD del ticker US; SIN fallback .BA (ARS)
        if cur_price is None or qty == 0 or pnl_usd is None:
            continue
        # Excluir ventas de brokers AR (incluido el sub-broker '· USD'): son
        # CEDEARs/acciones AR cuyo entry está por-UNIDAD-de-CEDEAR, mientras
        # cur_price (yfinance) es la acción US COMPLETA → difieren por el ratio
        # del CEDEAR (INTC 6:1, MELI 30:1…) y la comparación es basura.
        if _is_ars_broker(o.get("broker")):
            skipped_fx += 1
            continue

        # ── ¿Esta venta está en USD (comparable con cur_price)? ──────────────
        # Solo incluimos lo que podemos CONFIRMAR como USD; ante la duda,
        # omitimos (mejor analizar menos trades que mezclar monedas).
        # 1) Si la op declara currency, la respetamos.
        # 2) Si no, inferimos por el FX implícito: pnl_usd / pnl_nativo.
        #    USD ⇒ ≈ 1.0 ; ARS ⇒ ≈ 1/1435 ≈ 0.0007 (separación limpia).
        # 3) Si el PnL nativo es ~0 no hay señal de FX (no podemos descartar un
        #    activo AR cotizado en pesos) ⇒ omitimos por seguridad.
        currency = (o.get("currency") or "").strip().upper()
        raw_native = (exit_price - entry_price) * qty
        implied_fx = (pnl_usd / raw_native) if abs(raw_native) > 0.5 else None
        if currency:
            is_usd = currency == "USD"
        elif implied_fx is not None:
            is_usd = 0.5 <= implied_fx <= 2.0
        else:
            is_usd = False
        if not is_usd:
            skipped_fx += 1
            continue

        realized = pnl_usd  # autoritativo, ya en USD (neto de comisiones)
        # delta = upside de precio puro (cur − exit) × qty. Computar hypothetical
        # DESDE realized cancela el cost-basis y las comisiones, evitando que el
        # delta arrastre la diferencia entre pnl_usd (neto) y entry_price (bruto).
        hypothetical = realized + (cur_price - exit_price) * qty
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

    if len(breakdown) < 3:
        return _not_enough_data(
            "counterfactual",
            "Necesitás al menos 3 ventas en USD con precio actual para comparar. "
            "Las ventas en pesos (CEDEAR) no se pueden cruzar contra el precio en USD.",
        )

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
            "trades_skipped_fx": skipped_fx,
            "top_misses": breakdown[:5],  # cap
        },
        "references": [
            "Kahneman (2011) — Thinking, Fast and Slow (counterfactual thinking).",
        ],
    }


# ─── Detector 11: Recency bias (chase pumps) ─────────────────────────────────


def detect_recency_bias(positions: List[Dict[str, Any]],
                         prices: Optional[Dict[str, float]] = None,
                         tc_blue: float = 1415.0) -> Dict[str, Any]:
    """Variante pragmática del recency bias: detecta "chase the pump" usando
    la relación entre buy_price y precio actual.

    Si compraste a un precio >30% por encima del precio actual, hay una
    chance alta de que hayas comprado después de una corrida (chasing
    performance reciente). Sumamos % del invested actual donde aplica
    el patrón.

    Es heurístico: una posición puede estar drawdowneada por razones
    estructurales (no por recency). Pero a nivel agregado, si gran parte
    del portfolio compró alto, es señal valiosa.
    """
    if not positions or not prices:
        return _not_enough_data("recency_bias", "Necesitamos posiciones + precios actuales para detectar este patrón.")

    chase_pumps_invested = 0
    total_invested = 0
    flagged_assets = []
    for p in positions:
        if p.get("is_cash"):
            continue
        asset = (p.get("asset") or "").upper()
        if not asset:
            continue
        buy_price = p.get("buy_price")
        if buy_price is None or buy_price <= 0:
            continue
        # CRÍTICO: el precio actual tiene que ser en la MISMA moneda que
        # buy_price. _resolve_price() garantiza eso (busca .BA si el broker
        # es AR, evita mezclar US$ con AR$ que daba "drawdown -98%" absurdos).
        broker = p.get("broker")
        current_price = _resolve_price(asset, broker, prices)
        if current_price is None or current_price <= 0:
            continue
        # buy_price y current_price deben estar en la MISMA moneda para que el
        # ratio tenga sentido. _resolve_price devuelve ARS (.BA) para brokers AR;
        # el buy_price de un sub-broker '· USD' está en USD → mismatch → omitir.
        if _is_ars_broker(broker) != (_native_ccy(p) == "ARS"):
            continue
        invested_usd = _position_value_usd(p, prices, tc_blue)
        if invested_usd <= 0:
            continue
        total_invested += invested_usd
        # Pattern: buy_price >= 1.30 × current_price (en la misma moneda)
        ratio = buy_price / current_price
        if ratio >= 1.30:
            chase_pumps_invested += invested_usd
            flagged_assets.append({
                "asset": asset,
                "buy_price": buy_price,
                "current_price": current_price,
                "drawdown_pct": round((1 / ratio - 1) * 100, 1),
                "invested_usd": round(invested_usd, 2),
            })

    if total_invested <= 0:
        return _not_enough_data("recency_bias", "Falta data de precios o buy_price.")

    chase_pct = (chase_pumps_invested / total_invested) * 100

    if chase_pct >= 50:
        severity = "high"
        title = "Gran parte de tu portfolio compró alto"
        one_liner = (
            f"El {chase_pct:.0f}% de tu invested actual está en assets donde compraste >30% más caro "
            "que el precio actual. Patrón clásico de chase the pump."
        )
    elif chase_pct >= 25:
        severity = "medium"
        title = "Algunos activos comprados después de una corrida"
        one_liner = (
            f"{chase_pct:.0f}% del invested está en posiciones que están >30% por debajo de tu compra. "
            "Revisá si la tesis original sigue válida."
        )
    elif chase_pct > 5:
        severity = "low"
        title = "Pocas instancias de compras altas"
        one_liner = f"{chase_pct:.0f}% del invested compró alto. Magnitud baja, no es patrón sistemático."
    else:
        severity = "positive"
        title = "Sin patrón de compras tardías"
        one_liner = "No detectamos compras significativas por encima del precio actual."

    # Ordenar flagged por drawdown más profundo
    flagged_assets.sort(key=lambda x: x["drawdown_pct"])
    return {
        "code": "recency_bias",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, chase_pct * 1.5), 1),
        "value_label": f"{chase_pct:.0f}% del invested",
        "one_liner": one_liner,
        "evidence": {
            "chase_pct": round(chase_pct, 1),
            "chase_pumps_invested_usd": round(chase_pumps_invested, 2),
            "total_invested_usd": round(total_invested, 2),
            "flagged_count": len(flagged_assets),
            "flagged_assets": flagged_assets[:5],  # top 5 por drawdown
        },
        "references": [
            "Barber & Odean (2008) — All that glitters: the effect of attention and news on individual investor behavior.",
        ],
    }


# ─── Detector 12: Sector concentration ───────────────────────────────────────

# Mapping ticker → sector. Cobertura: blue chips US + cripto top + acciones AR
# + bonos AR. Tickers no mapeados caen en "Otros".
_SECTOR_MAP = {
    # Tech US
    'AAPL': 'Tech', 'MSFT': 'Tech', 'NVDA': 'Tech', 'GOOGL': 'Tech', 'GOOG': 'Tech',
    'META': 'Tech', 'AMZN': 'Tech', 'TSLA': 'Tech', 'AMD': 'Tech', 'AVGO': 'Tech',
    'NFLX': 'Tech', 'ORCL': 'Tech', 'ADBE': 'Tech', 'CRM': 'Tech', 'INTC': 'Tech',
    'QCOM': 'Tech', 'CSCO': 'Tech', 'IBM': 'Tech', 'NOW': 'Tech', 'TSM': 'Tech',
    'MU': 'Tech', 'PLTR': 'Tech', 'COIN': 'Tech', 'MELI': 'Tech', 'GLOB': 'Tech',
    # Financials US
    'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials', 'BAC': 'Financials',
    'WFC': 'Financials', 'BLK': 'Financials', 'AXP': 'Financials', 'GS': 'Financials',
    # Healthcare
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'PFE': 'Healthcare',
    'MRK': 'Healthcare', 'ABBV': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    # Consumer
    'WMT': 'Consumer', 'COST': 'Consumer', 'KO': 'Consumer', 'PEP': 'Consumer',
    'PG': 'Consumer', 'MCD': 'Consumer', 'PM': 'Consumer', 'NKE': 'Consumer',
    # Energy
    'XOM': 'Energy', 'CVX': 'Energy',
    # ETFs / Diversified
    'SPY': 'ETF / Diversified', 'VOO': 'ETF / Diversified', 'QQQ': 'ETF / Diversified',
    'IVV': 'ETF / Diversified', 'VTI': 'ETF / Diversified', 'VEA': 'ETF / Diversified',
    'VWO': 'ETF / Diversified', 'DIA': 'ETF / Diversified', 'IWM': 'ETF / Diversified',
    'IEMG': 'ETF / Diversified', 'XLK': 'ETF / Diversified', 'XLF': 'ETF / Diversified',
    'XLE': 'ETF / Diversified', 'ARKK': 'ETF / Diversified', 'AGG': 'ETF / Bonds',
    'BND': 'ETF / Bonds', 'GLD': 'Commodities', 'SLV': 'Commodities',
    # Crypto
    'BTC': 'Crypto', 'ETH': 'Crypto', 'SOL': 'Crypto', 'BNB': 'Crypto',
    'XRP': 'Crypto', 'ADA': 'Crypto', 'DOGE': 'Crypto', 'AVAX': 'Crypto',
    'DOT': 'Crypto', 'MATIC': 'Crypto', 'LINK': 'Crypto', 'LTC': 'Crypto',
    'BCH': 'Crypto', 'TRX': 'Crypto', 'USDT': 'Stablecoin', 'USDC': 'Stablecoin',
    # Argentina — acciones locales
    'GGAL': 'AR · Financials', 'BMA': 'AR · Financials', 'BBAR': 'AR · Financials',
    'SUPV': 'AR · Financials', 'BYMA': 'AR · Financials', 'VALO': 'AR · Financials',
    'YPFD': 'AR · Energy', 'PAMP': 'AR · Energy', 'CEPU': 'AR · Energy',
    'EDN': 'AR · Energy', 'TGSU2': 'AR · Energy', 'TGNO4': 'AR · Energy',
    'TRAN': 'AR · Energy',
    'TEN': 'AR · Materials', 'ALUA': 'AR · Materials', 'ERAR': 'AR · Materials',
    'TXAR': 'AR · Materials', 'LOMA': 'AR · Materials',
    'CRES': 'AR · Consumer', 'COME': 'AR · Consumer', 'MIRG': 'AR · Consumer',
    # Bonos AR
    'AL29': 'AR · Bonos', 'AL30': 'AR · Bonos', 'AL35': 'AR · Bonos', 'AE38': 'AR · Bonos',
    'AL41': 'AR · Bonos', 'GD29': 'AR · Bonos', 'GD30': 'AR · Bonos', 'GD35': 'AR · Bonos',
    'GD38': 'AR · Bonos', 'GD41': 'AR · Bonos', 'GD46': 'AR · Bonos',
    'TX26': 'AR · Bonos', 'TX28': 'AR · Bonos', 'TX31': 'AR · Bonos',
    'TZX26': 'AR · Bonos', 'TZX28': 'AR · Bonos', 'DICY': 'AR · Bonos', 'PARY': 'AR · Bonos',
}


def _sector_for(asset: str) -> str:
    """Resuelve el sector de un ticker. CEDEARs (.BA) usan el sector de la
    contraparte US si está mapeada; sino caen en 'AR · CEDEAR'."""
    if not asset:
        return "Otros"
    a = asset.upper()
    if a in _SECTOR_MAP:
        return _SECTOR_MAP[a]
    # CEDEARs: stripear .BA y buscar
    if a.endswith(".BA"):
        base = a[:-3]
        if base in _SECTOR_MAP:
            # CEDEAR de un ticker US conocido → mismo sector pero con prefijo
            return f"AR · CEDEAR ({_SECTOR_MAP[base]})"
        return "AR · CEDEAR"
    return "Otros"


def detect_sector_concentration(positions: List[Dict[str, Any]],
                                 prices: Optional[Dict[str, float]] = None,
                                 tc_blue: float = 1415.0) -> Dict[str, Any]:
    """Concentración por sector. Si un sector pesa >50% → high. >35% → medium.
    <30% top sector → positive.
    """
    if not positions:
        return _not_enough_data("sector_concentration", "No tenés posiciones para analizar.")

    by_sector: Dict[str, float] = {}
    unmapped = 0
    total_assets = 0
    for p in positions:
        if p.get("is_cash"):
            continue
        asset = (p.get("asset") or "").upper()
        if not asset:
            continue
        value_usd = _position_value_usd(p, prices, tc_blue)
        if value_usd <= 0:
            continue
        sector = _sector_for(asset)
        if sector == "Otros":
            unmapped += 1
        by_sector[sector] = by_sector.get(sector, 0) + value_usd
        total_assets += 1

    total = sum(by_sector.values())
    if total <= 0:
        return _not_enough_data("sector_concentration", "No pudimos valuar tus posiciones.")

    sorted_sectors = sorted(by_sector.items(), key=lambda x: -x[1])
    top_sector, top_value = sorted_sectors[0]
    top_pct = (top_value / total) * 100
    top3_pct = (sum(v for _, v in sorted_sectors[:3]) / total) * 100

    if top_pct >= 50:
        severity = "high"
        title = f"Concentración fuerte en {top_sector}"
        one_liner = (
            f"El sector {top_sector} representa el {top_pct:.0f}% de tu portfolio. "
            "Un shock sectorial te afectaría desproporcionadamente."
        )
    elif top_pct >= 35:
        severity = "medium"
        title = f"{top_sector} pesa fuerte en tu portfolio"
        one_liner = (
            f"{top_sector} = {top_pct:.0f}% · Top 3 sectores = {top3_pct:.0f}%. "
            "Diversificar entre sectores reduce el riesgo idiosincrático."
        )
    elif top_pct < 30:
        severity = "positive"
        title = "Diversificación sectorial saludable"
        one_liner = (
            f"El sector más grande ({top_sector}) representa {top_pct:.0f}% — "
            "diversificación adecuada entre sectores."
        )
    else:
        severity = "low"
        title = "Diversificación sectorial moderada"
        one_liner = f"Top sector {top_sector} = {top_pct:.0f}%. Distribución razonable."

    return {
        "code": "sector_concentration",
        "title": title,
        "severity": severity,
        "detected": severity in ("high", "medium"),
        "score": round(min(100, top_pct * 1.5), 1),
        "value_label": f"{top_sector}: {top_pct:.0f}%",
        "one_liner": one_liner,
        "evidence": {
            "top_sector": top_sector,
            "top1_pct": round(top_pct, 1),
            "top3_pct": round(top3_pct, 1),
            "total_sectors": len(by_sector),
            "total_value_usd": round(total, 2),
            "unmapped_count": unmapped,
            "breakdown": [
                {"sector": s, "value_usd": round(v, 2), "pct": round(v / total * 100, 1)}
                for s, v in sorted_sectors
            ],
        },
        "references": [
            "Markowitz (1952) — Portfolio selection. Sector-level diversification literature.",
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
        detect_overtrade(ops, pos, tc_blue, prices),
        detect_loss_aversion(ops, tc_blue),
        detect_averaging_down(ops),
        # Sprint 3.1
        detect_concentration(pos, prices, tc_blue),
        detect_inflation_loss(pos, inflation_monthly, tc_blue),
        detect_counterfactual(ops, prices),
        # Sprint 3.2
        detect_winrate_payoff(ops),
        detect_home_bias(pos, prices, tc_blue),
        detect_cash_drag(pos, tc_blue),
        # Sprint 3.3
        detect_recency_bias(pos, prices, tc_blue),
        detect_sector_concentration(pos, prices, tc_blue),
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
