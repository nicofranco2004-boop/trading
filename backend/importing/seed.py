"""Seed sintético para CSVs parciales.

Cuando un export CSV cubre solo los últimos N meses, suele faltar el balance
inicial (cash + posiciones que el usuario ya tenía antes de la primera fila).
Eso produce SELLs sin stock previo y BUYs sin cash.

Este módulo genera dos cosas:
  1. `build_suggestions`: detecta qué brokers/activos/monedas necesitarían seed,
     en base a errores de validación y warnings del cash_sim.
  2. `build_seed_txs`: dado un `seed_state` cargado por el usuario, devuelve
     una lista de NormalizedTx sintéticas (DEPOSITs + BUYs) datadas un día
     antes del primer movimiento del CSV. Esas se procesan PRIMERO por el
     persister (orden cronológico), creando el cash y las posiciones que el
     CSV asume que ya existían.

El seed se persiste como filas extra del mismo batch — son auditables y se
revierten junto con el resto del import. El row_index se asigna en negativo
(empezando en -10000) para no colisionar con los row_index reales del CSV.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date as _date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .schema import (
    NormalizedTx, RowError,
    OP_BUY, OP_SELL, OP_DEPOSIT, OP_WITHDRAW, OP_FEE,
    OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS,
)


def _minus_one_day(date_str: str) -> str:
    """'2025-11-11' → '2025-11-10'. Si no podemos parsear, devolvemos el mismo."""
    try:
        y, m, d = (int(x) for x in date_str.split("-"))
        prev = _date(y, m, d) - timedelta(days=1)
        return prev.isoformat()
    except Exception:
        return date_str


def build_suggestions(
    *,
    valid_txs: List[NormalizedTx],
    val_errors: List[RowError],
    cash_warnings: List[Any],          # CashWarning del cash_sim
    user_brokers: Dict[str, dict],
    existing_positions: Dict[Tuple[str, str], float],
    all_normalized: Optional[List[NormalizedTx]] = None,
    final_balances: Optional[Dict[Tuple[str, str], float]] = None,  # (broker,cur)→saldo final del CSV
) -> Optional[Dict[str, Any]]:
    """Devuelve una sugerencia de seed si el CSV parece parcial, o None.

    Se considera "parcial" si:
      - Hay al menos un error INSUFFICIENT_STOCK (SELL de un activo que no existía).
      - O hay warnings de overdraft sobre cash que no fue depositado antes en el CSV.

    La estructura devuelta tiene formato amigable para el frontend:
      {
        "needed": True,
        "earliest_csv_date": "2025-11-11",
        "seed_date": "2025-11-10",
        "brokers": [
          {
            "broker": "Binance",
            "broker_currency": "USDT",
            "assets": [{"symbol": "BTC", "min_qty": 0.05, "reason": "ventas sin compras previas"}],
            "cash_overdraft": {"USDT": 1750.00},
            "trigger_count": 3,
          }
        ],
        "totals": {"sell_errors": 5, "cash_warnings": 2}
      }
    """
    # Recolectar SELL errors por broker+asset
    sell_errors_by_broker: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    sell_error_count = 0
    for err in val_errors:
        if err.code == "INSUFFICIENT_STOCK":
            sell_error_count += 1

    # Para asociar cada INSUFFICIENT_STOCK al broker+asset, necesitamos cruzarlo
    # con las txs originales (errores no traen broker/asset directamente —
    # solo row_index). Iteramos las txs de SELL que están en val_errors.
    err_row_indices = {e.row_index for e in val_errors if e.code == "INSUFFICIENT_STOCK"}

    # Cargar las txs INSUFFICIENT_STOCK desde valid_txs no funciona — están filtradas.
    # Necesitamos otra fuente: pasar las txs *normalizadas* (antes de validar).
    # Se hace en el caller de pipeline.py, no acá.

    # Cash overdrafts por broker+currency
    cash_overdraft: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for w in cash_warnings:
        # Solo nos interesan los warnings de operaciones que asumen cash previo:
        # BUY, FX_ARS_TO_USD/USD_TO_ARS, WITHDRAW, FEE.
        if w.op_type in (OP_BUY, OP_WITHDRAW, OP_FEE, OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS):
            # delta es negativo; new_balance es negativo; magnitud del overdraft
            magnitude = abs(w.new_balance) if w.new_balance < 0 else 0
            if magnitude > 0:
                cash_overdraft[w.broker][w.currency] = max(
                    cash_overdraft[w.broker][w.currency], magnitude,
                )

    if sell_error_count == 0 and not cash_overdraft:
        return None

    # Determinar fecha del seed: 1 día antes del primer movimiento del CSV.
    # Usamos all_normalized (incluye filas inválidas) para no perder la fecha
    # cuando todas las filas son SELLs sin stock.
    date_pool = all_normalized if all_normalized else valid_txs
    all_dates = [t.date for t in date_pool if t.date]
    if not all_dates:
        return None
    earliest = min(all_dates)
    seed_date = _minus_one_day(earliest)

    # Armar lista de brokers afectados — se llena más abajo por el caller con
    # info de assets. Acá solo dejamos los que tenemos por cash overdraft.
    brokers_map: Dict[str, Dict[str, Any]] = {}
    for broker, cur_map in cash_overdraft.items():
        info = brokers_map.setdefault(broker, {
            "broker": broker,
            "broker_currency": (user_brokers.get(broker) or {}).get("currency", ""),
            "assets": [],
            "cash_overdraft": {},
            # Saldo que da el CSV por sí solo (puede ser negativo). El front lo usa
            # para back-calcular el depósito inicial pidiendo el saldo de HOY:
            #   depósito_inicial = saldo_actual_del_usuario − final_balance
            "final_balance": {},
            "trigger_count": 0,
        })
        for cur, amount in cur_map.items():
            info["cash_overdraft"][cur] = round(amount, 2)
            if final_balances is not None:
                fb = final_balances.get((broker, cur))
                if fb is not None:
                    info["final_balance"][cur] = round(fb, 2)
            info["trigger_count"] += 1

    return {
        "needed": True,
        "earliest_csv_date": earliest,
        "seed_date": seed_date,
        "brokers": list(brokers_map.values()),
        "totals": {
            "sell_errors": sell_error_count,
            "cash_warnings": len([w for w in cash_warnings
                                   if w.op_type in (OP_BUY, OP_WITHDRAW, OP_FEE,
                                                     OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS)]),
        },
        "_sell_error_row_indices": list(err_row_indices),  # internal, used to enrich assets
    }


def enrich_with_sell_assets(
    suggestions: Dict[str, Any],
    *,
    all_normalized: List[NormalizedTx],
    err_row_indices: set,
) -> Dict[str, Any]:
    """Cruza los row_indices de errores INSUFFICIENT_STOCK con las txs
    pre-validación para extraer broker+asset+qty. Mutates and returns.
    """
    # Agrupar por broker+asset
    needed_qty: Dict[Tuple[str, str], float] = defaultdict(float)
    for tx in all_normalized:
        if tx.row_index in err_row_indices and tx.operation_type == OP_SELL:
            key = (tx.broker, tx.asset_symbol or "")
            needed_qty[key] += float(tx.quantity or 0)

    # Mergear en suggestions["brokers"]
    brokers_map = {b["broker"]: b for b in suggestions.get("brokers", [])}
    for (broker, asset), qty in needed_qty.items():
        if not asset:
            continue
        info = brokers_map.setdefault(broker, {
            "broker": broker,
            "broker_currency": "",
            "assets": [],
            "cash_overdraft": {},
            "trigger_count": 0,
        })
        info["assets"].append({
            "symbol": asset,
            "min_qty": round(qty, 8),
            "reason": "ventas sin compras previas",
        })
        info["trigger_count"] += 1

    suggestions["brokers"] = list(brokers_map.values())
    suggestions.pop("_sell_error_row_indices", None)
    return suggestions


def enrich_with_transfer_assets(
    suggestions: Dict[str, Any],
    *,
    transfers: List[Tuple[str, str, float]],   # (broker, asset, qty)
    user_brokers: Optional[Dict[str, dict]] = None,
) -> Dict[str, Any]:
    """Agrega al seed las posiciones que entraron por transferencia de securities
    (p.ej. migración TDA→Schwab). A diferencia de las ventas-sin-compra, acá la
    cantidad es EXACTA y conocida (la trae el CSV) — solo falta el precio de
    compra. Marcamos `exact_qty=True` para que el front muestre la cantidad fija
    y pida únicamente el cost basis. Mutates and returns.
    """
    user_brokers = user_brokers or {}
    brokers_map = {b["broker"]: b for b in suggestions.get("brokers", [])}
    agg: Dict[Tuple[str, str], float] = defaultdict(float)
    for broker, asset, qty in transfers:
        if asset and qty > 0:
            agg[(broker, asset)] += qty
    for (broker, asset), qty in agg.items():
        info = brokers_map.setdefault(broker, {
            "broker": broker,
            "broker_currency": (user_brokers.get(broker) or {}).get("currency", ""),
            "assets": [],
            "cash_overdraft": {},
            "final_balance": {},
            "trigger_count": 0,
        })
        if not info.get("broker_currency"):
            info["broker_currency"] = (user_brokers.get(broker) or {}).get("currency", "")
        existing = next((a for a in info["assets"] if a.get("symbol") == asset), None)
        if existing:
            existing["min_qty"] = round(qty, 8)
            existing["exact_qty"] = True
            existing["reason"] = "transferida sin precio de compra"
        else:
            info["assets"].append({
                "symbol": asset,
                "min_qty": round(qty, 8),
                "exact_qty": True,
                "reason": "transferida sin precio de compra",
            })
            info["trigger_count"] += 1
    suggestions["brokers"] = list(brokers_map.values())
    return suggestions


def build_seed_txs(seed_state: Dict[str, Any]) -> List[NormalizedTx]:
    """Convierte el seed_state que mandó el frontend en una lista de NormalizedTx.

    seed_state esperado:
      {
        "seed_date": "2025-11-10",
        "brokers": [
          {
            "broker": "Binance",
            "cash": {"USDT": 1500, "ARS": 0},
            "assets": [
              {"symbol": "BTC", "qty": 0.05, "cost_basis_unit": 65000},
              ...
            ]
          }
        ]
      }

    Generamos:
      - 1 DEPOSIT por (broker, currency) cuyo monto = (cash declarado por el
        usuario) + (suma de costos de las posiciones en esa moneda). Esto deja
        el cash neto = cash declarado después de que los BUYs sintéticos lo
        debiten.
      - 1 BUY por activo, con qty y unit_price del usuario.
    """
    seed_date = seed_state.get("seed_date")
    if not seed_date:
        return []

    out: List[NormalizedTx] = []
    next_idx = -10_000  # row_index ficticio negativo para no colisionar

    for b in seed_state.get("brokers") or []:
        broker = (b.get("broker") or "").strip()
        if not broker:
            continue
        cash_in = b.get("cash") or {}
        assets = b.get("assets") or []

        # Sumar costos por moneda — para auto-aumentar el DEPOSIT
        cost_by_currency: Dict[str, float] = defaultdict(float)
        # Asumimos que el costo de cada activo está en la moneda nativa del broker.
        # Si quisiéramos soportar mezcla, habría que pedirle al usuario la
        # moneda por activo. Para MVP: una moneda por broker.
        # Tomamos la primera moneda con cash declarado; si no hay cash (caso de
        # seed-assets de transferencias sin overdraft), usamos la moneda del
        # broker; último fallback "USDT". Sin esto, una posición transferida a un
        # broker USD (Schwab) se creaba en USDT.
        primary_currency = (
            next(iter(cash_in.keys()), None)
            or (b.get("broker_currency") or "").strip().upper()
            or "USDT"
        )

        valid_assets = []
        for a in assets:
            symbol = (a.get("symbol") or "").strip().upper()
            try:
                qty = float(a.get("qty") or 0)
                cost_unit = float(a.get("cost_basis_unit") or 0)
            except (TypeError, ValueError):
                continue
            if symbol and qty > 0 and cost_unit >= 0:
                valid_assets.append({"symbol": symbol, "qty": qty, "cost_unit": cost_unit})
                cost_by_currency[primary_currency] += qty * cost_unit

        # DEPOSITs: para cada moneda con cash declarado o costos pendientes
        currencies = set(cash_in.keys()) | set(cost_by_currency.keys())
        for cur in currencies:
            user_cash = float(cash_in.get(cur) or 0)
            covered_cost = cost_by_currency.get(cur, 0.0)
            total = user_cash + covered_cost
            # total > 0 → DEPOSIT (faltaba plata previa / fondear seed-assets).
            # total < 0 → WITHDRAW: el cash que estimaron los trades quedó MÁS ALTO
            #   que el real del usuario (típico en imports cross-currency/MEP, donde
            #   las ventas en USD inflan el cash USD). Bajamos el cash al real con un
            #   retiro sintético. Sin esto, la corrección del usuario se ignoraba.
            if abs(total) >= 0.01:
                op_type = OP_DEPOSIT if total > 0 else OP_WITHDRAW
                label = "depósito" if total > 0 else "retiro"
                out.append(NormalizedTx(
                    row_index=next_idx,
                    date=seed_date,
                    broker=broker,
                    operation_type=op_type,
                    gross_amount=round(abs(total), 4),
                    currency=cur,
                    notes=f"Estado inicial — {label} sintético (Rendi)",
                ))
                next_idx += 1

        # BUYs sintéticos
        for a in valid_assets:
            invested = a["qty"] * a["cost_unit"]
            out.append(NormalizedTx(
                row_index=next_idx,
                date=seed_date,
                broker=broker,
                operation_type=OP_BUY,
                asset_symbol=a["symbol"],
                quantity=a["qty"],
                unit_price=a["cost_unit"],
                gross_amount=round(invested, 4),
                currency=primary_currency,
                notes="Estado inicial — compra sintética (Rendi)",
            ))
            next_idx += 1

    return out


def seed_state_to_existing_positions(
    seed_state: Dict[str, Any],
) -> Dict[Tuple[str, str], float]:
    """Mapa (broker, asset) → qty del seed. Sirve para que el validator y el
    cash_sim consideren las posiciones sintéticas ya existentes al re-evaluar
    SELL/cash al confirmar."""
    out: Dict[Tuple[str, str], float] = {}
    for b in (seed_state or {}).get("brokers") or []:
        broker = (b.get("broker") or "").strip()
        if not broker:
            continue
        for a in b.get("assets") or []:
            symbol = (a.get("symbol") or "").strip().upper()
            try:
                qty = float(a.get("qty") or 0)
            except (TypeError, ValueError):
                qty = 0
            if symbol and qty > 0:
                key = (broker, symbol)
                out[key] = out.get(key, 0.0) + qty
    return out


def seed_state_to_starting_cash(
    seed_state: Dict[str, Any],
) -> Dict[Tuple[str, str], float]:
    """Mapa (broker, currency) → balance del seed. El cash declarado por el
    usuario se inyecta en el simulador como saldo inicial."""
    out: Dict[Tuple[str, str], float] = {}
    for b in (seed_state or {}).get("brokers") or []:
        broker = (b.get("broker") or "").strip()
        if not broker:
            continue
        cash_in = b.get("cash") or {}
        for cur, amount in cash_in.items():
            try:
                v = float(amount or 0)
            except (TypeError, ValueError):
                v = 0
            if v > 0:
                out[(broker, cur)] = out.get((broker, cur), 0.0) + v
    return out
