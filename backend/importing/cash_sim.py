"""Simulación cronológica de cash flow para detectar overdrafts antes del persist.

Ejecuta el mismo razonamiento que el persister pero solo en memoria, sin tocar
la DB. Devuelve un resumen con:
  - balance final por (broker, currency)
  - lista de filas que llevaron el saldo a negativo

Esto se usa en el preview para mostrar warnings al usuario *antes* de que
confirme el import. No bloquea — el persister actual ya permite overdraft
silencioso. La idea es transparencia, no enforcement.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .schema import (
    NormalizedTx,
    OP_BUY, OP_SELL, OP_DEPOSIT, OP_WITHDRAW, OP_DIVIDEND, OP_INTEREST,
    OP_FEE, OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS,
)


@dataclass
class CashWarning:
    row_index: int
    broker: str
    currency: str           # ARS / USDT
    delta: float            # cuánto se restó
    new_balance: float      # saldo después
    op_type: str
    message: str            # texto user-facing


@dataclass
class CashSimResult:
    final_balances: Dict[Tuple[str, str], float]  # (broker, currency) → balance
    warnings: List[CashWarning] = field(default_factory=list)


def simulate(
    txs: List[NormalizedTx],
    *,
    user_brokers: Dict[str, dict],            # name → {currency, parent_broker_id, ...}
    starting_cash: Dict[Tuple[str, str], float],  # (broker, currency) → saldo inicial
    route_by_currency: bool = False,
) -> CashSimResult:
    """Recorre las txs en orden cronológico y simula el cash. Dentro del mismo
    día, BUYs primero — consistente con el sort del persister, así el preview
    no reporta cash flows falsos cuando hay trading intra-día (la Venta sin
    su Compra previa mostraría cash insuficiente)."""
    sorted_txs = sorted(txs, key=lambda t: (
        t.date,
        0 if t.operation_type == OP_BUY else 1,
        t.row_index,
    ))
    balances = dict(starting_cash)
    warnings: List[CashWarning] = []

    # Mapa parent → sibling para simulación de routing.
    # En la realidad el persister llama a _ensure_usd_sibling. Acá no creamos
    # nada — solo proyectamos a un nombre virtual "<parent> · USD".
    sibling_for: Dict[str, str] = {}
    if route_by_currency:
        for broker_name, info in user_brokers.items():
            if info.get("currency") == "ARS":
                # Si ya tiene un sibling existente, usalo; si no, proyectá nombre.
                existing_sibling = next(
                    (n for n, i in user_brokers.items()
                     if i.get("parent_broker_id") == info.get("id") and i.get("currency") == "USDT"),
                    None,
                )
                sibling_for[broker_name] = existing_sibling or f"{broker_name} · USD"

    def _route(tx: NormalizedTx) -> str:
        """Devuelve el broker efectivo donde se aplica el cash flow."""
        if not route_by_currency:
            return tx.broker
        sib = sibling_for.get(tx.broker)
        if not sib:
            return tx.broker
        op = tx.operation_type
        cur = (tx.currency or "").upper()
        if op == OP_FX_ARS_TO_USD:
            return tx.broker  # source = parent ARS
        if op == OP_FX_USD_TO_ARS:
            return sib  # source = sibling USD
        if cur in ("USD", "USDT"):
            return sib
        return tx.broker

    def _broker_currency(broker: str) -> str:
        info = user_brokers.get(broker)
        if info:
            return info.get("currency", "USDT")
        # Sibling proyectado (no existe aún en user_brokers)
        if " · USD" in broker:
            return "USDT"
        return "USDT"

    def _adjust(broker: str, currency: str, delta: float, tx: NormalizedTx, label: str):
        key = (broker, currency)
        prev = balances.get(key, 0.0)
        new = prev + delta
        balances[key] = new
        # Warning si pasa de >=0 a <0 (cruzó el umbral)
        if delta < 0 and new < 0 and prev >= 0:
            warnings.append(CashWarning(
                row_index=tx.row_index,
                broker=broker,
                currency=currency,
                delta=delta,
                new_balance=new,
                op_type=tx.operation_type,
                message=label,
            ))

    for tx in sorted_txs:
        broker = _route(tx)
        currency = _broker_currency(broker)
        op = tx.operation_type

        if op == OP_BUY:
            qty = float(tx.quantity or 0)
            unit = float(tx.unit_price or 0)
            invested = float(tx.gross_amount) if tx.gross_amount is not None else (unit * qty)
            cost = (invested or 0) + float(tx.fees or 0)
            if cost > 0:
                _adjust(broker, currency, -cost, tx,
                        f"Compra de {tx.asset_symbol or 'activo'}: {currency} {cost:,.2f}")

        elif op == OP_SELL:
            qty = float(tx.quantity or 0)
            unit = float(tx.unit_price or 0)
            proceeds = float(tx.gross_amount) if tx.gross_amount is not None else (unit * qty)
            net = (proceeds or 0) - float(tx.fees or 0)
            if net != 0:
                # Sumar (positivo) — no generamos warning de cash en sells
                key = (broker, currency)
                balances[key] = balances.get(key, 0.0) + net

        elif op in (OP_DEPOSIT, OP_DIVIDEND, OP_INTEREST):
            amount = float(tx.gross_amount or 0)
            if amount > 0:
                key = (broker, currency)
                balances[key] = balances.get(key, 0.0) + amount

        elif op in (OP_WITHDRAW, OP_FEE):
            amount = float(tx.gross_amount or 0)
            if amount > 0:
                _adjust(broker, currency, -amount, tx,
                        f"{'Retiro' if op == OP_WITHDRAW else 'Comisión'}: {currency} {amount:,.2f}")

        elif op == OP_FX_ARS_TO_USD:
            ars = float(tx.gross_amount or 0)
            usd = float(tx.quantity or 0)
            sib = sibling_for.get(tx.broker, f"{tx.broker} · USD")
            # Debit ARS del padre
            if ars > 0:
                _adjust(tx.broker, "ARS", -ars, tx,
                        f"Conversión ARS→USD: ARS {ars:,.2f}")
            # Credit USD al sibling
            if usd > 0:
                key = (sib, "USDT")
                balances[key] = balances.get(key, 0.0) + usd

        elif op == OP_FX_USD_TO_ARS:
            ars = float(tx.gross_amount or 0)
            usd = float(tx.quantity or 0)
            sib = sibling_for.get(tx.broker, f"{tx.broker} · USD")
            # Debit USD del sibling
            if usd > 0:
                _adjust(sib, "USDT", -usd, tx,
                        f"Conversión USD→ARS: USD {usd:,.2f}")
            # Credit ARS al padre
            if ars > 0:
                key = (tx.broker, "ARS")
                balances[key] = balances.get(key, 0.0) + ars

    return CashSimResult(final_balances=balances, warnings=warnings)
