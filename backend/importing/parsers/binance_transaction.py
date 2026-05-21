"""Parser de Binance Transaction History (export completo).

El export más completo de Binance — incluye Spot, Futures, Funding, P2P,
Deposits, Withdraws en un solo archivo.

Headers: User_ID, Time, Account, Operation, Coin, Change, Remark

Particularidades:
1. Cada trade de Spot ocupa MÚLTIPLES filas con el mismo timestamp
   (Transaction Sold + Transaction Revenue + Transaction Fee, a veces
   con varias filas Sold/Revenue cuando el trade se ejecuta en partes).
   Agrupamos por Time para reconstruir el trade.
2. Cada cierre de posición de futuros genera una fila Realized Profit and
   Loss + una fila Fee con el mismo TradeID. Agrupamos por TradeID y
   producimos un único registro de PnL neto (op_type FUTURES_PNL).
3. Las fechas vienen en formato YY-MM-DD que convertimos a YYYY-MM-DD.

Mapeo al modelo de Rendi:
- Spot trades (grupo por timestamp) → COMPRA / VENTA
- Futures Realized PnL + Fee (grupo por TradeID) → FUTURES_PNL
- Funding Fee positivo → INTERES
- Funding Fee negativo → COMISION
- Deposit → DEPOSITO
- Withdraw → RETIRO
- P2P Trading positivo → DEPOSITO con notas P2P
- P2P Trading negativo → RETIRO con notas P2P
- Transfer Between Main and Funding Wallet → IGNORADO (interno entre
  wallets del mismo usuario, no afecta patrimonio)
"""
from __future__ import annotations
import csv
import io
import re
from collections import defaultdict
from typing import Dict, List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


# Quote assets ESTABLES — siempre actúan como quote en cualquier par donde
# aparecen. Si una operación tiene una de estas en un lado, esa es la moneda
# de cotización; el otro lado es el activo de la operación.
_STABLE_QUOTES = {
    # Stablecoins atadas a USD
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "USD",
    # Fiat
    "EUR", "GBP", "ARS", "BRL", "AUD", "TRY", "RUB", "JPY",
    "ZAR", "UAH", "RON", "PLN", "CZK", "MXN", "COP", "CHF",
}

# Cripto que pueden actuar como quote en pares cripto-cripto (BTC/ETH/BNB),
# pero usualmente son base. Solo se consideran quote si ninguna stable está
# involucrada en la operación (caso ETH→BTC, por ejemplo).
_CRYPTO_QUOTES = {"BTC", "ETH", "BNB", "TRX", "XRP", "DOT", "DOGE"}

_REQUIRED = {"user_id", "time", "account", "operation", "coin", "change"}

_SPOT_TRADE_OPS = {
    "Transaction Sold", "Transaction Revenue", "Transaction Fee",
    "Transaction Spend", "Transaction Buy",
}
_FUTURES_TRADE_OPS = {"Realized Profit and Loss", "Fee"}

_TRADEID_RE = re.compile(r"TradeID\s*-\s*(\d+)", re.IGNORECASE)


def _norm_header(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "_")


def _parse_num(s) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fix_date(s: str) -> str:
    """Convierte 'YY-MM-DD HH:MM:SS' a 'YYYY-MM-DD'. Si ya es YYYY-MM-DD, pasa."""
    s = (s or "").strip().split(" ")[0]
    parts = s.split("-")
    if len(parts) == 3 and len(parts[0]) == 2:
        try:
            yy = int(parts[0])
        except ValueError:
            return s
        year = 2000 + yy if yy < 70 else 1900 + yy
        return f"{year:04d}-{parts[1]}-{parts[2]}"
    return s


def _is_stable_quote(coin: str) -> bool:
    return coin in _STABLE_QUOTES


def _is_crypto_quote(coin: str) -> bool:
    return coin in _CRYPTO_QUOTES


def _currency_for(coin: str) -> str:
    if coin in ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "USD"):
        return "USD"
    if coin == "ARS":
        return "ARS"
    return "USD"


class BinanceTransactionHistoryParser(Parser):
    format_id = "binance_transaction_history"
    display_name = "Binance Transaction History (completo)"
    is_supported = True
    platform = "binance"
    platform_label = "Binance"
    export_label = "Asset History → Transaction History (completo)"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_norm_header(h) for h in headers}
        return _REQUIRED.issubset(norm)

    def template_csv(self) -> str:
        return (
            "User_ID,Time,Account,Operation,Coin,Change,Remark\n"
            "12345,25-01-15 14:30:00,Spot,Deposit,USDT,1000,\n"
            "12345,25-02-01 10:15:30,Spot,Transaction Sold,SOL,-2,\n"
            "12345,25-02-01 10:15:30,Spot,Transaction Revenue,USDT,400,\n"
            "12345,25-02-01 10:15:30,Spot,Transaction Fee,USDT,-0.4,\n"
            "12345,25-03-10 16:45:00,USD-M Futures,Realized Profit and Loss,USDT,50.5,TradeID - 12345\n"
            "12345,25-03-10 16:45:00,USD-M Futures,Fee,USDT,-0.5,TradeID - 12345\n"
            "12345,25-04-05 09:00:00,USD-M Futures,Funding Fee,USDT,-0.15,\n"
            "12345,25-05-20 18:00:00,Spot,Withdraw,USDT,-500,Withdraw fee is included\n"
            "12345,25-06-10 11:30:00,Funding,P2P Trading,USDT,-280,P2P - 22825\n"
        )

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        if content.startswith("﻿"):
            content = content[1:]
        try:
            reader = csv.DictReader(io.StringIO(content))
            headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(0, None, "FILE_UNREADABLE",
                                                f"No pudimos leer el archivo: {ex}"))
            return result

        if not self.can_handle(headers):
            result.parse_errors.append(RowError(
                0, None, "BINANCE_TX_HEADERS_MISMATCH",
                "Este archivo no parece ser un Binance Transaction History "
                "(faltan columnas: User_ID, Time, Account, Operation, Coin, "
                "Change). Verificá el formato — Binance Spot Trade History "
                "tiene otra estructura distinta."))
            return result

        h_map = {_norm_header(h): h for h in headers}

        def _g(row, key):
            return (row.get(h_map[key]) or "").strip() if key in h_map else ""

        all_rows = list(reader)
        spot_groups: Dict[str, list] = defaultdict(list)
        futures_groups: Dict[str, list] = defaultdict(list)
        single_rows: list = []

        for raw in all_rows:
            time_val = _g(raw, "time")
            account = _g(raw, "account")
            operation = _g(raw, "operation")
            remark = _g(raw, "remark")

            if account == "Spot" and operation in _SPOT_TRADE_OPS:
                spot_groups[time_val].append(raw)
            elif account in ("USD-M Futures", "COIN-M Futures") and operation in _FUTURES_TRADE_OPS:
                m = _TRADEID_RE.search(remark)
                tid = m.group(1) if m else f"NO_TID_{time_val}"
                futures_groups[tid].append(raw)
            else:
                single_rows.append(raw)

        out_idx = 0

        # ── Spot trades ──────────────────────────────────────
        for time_key in sorted(spot_groups.keys()):
            group = spot_groups[time_key]
            sold_by_coin = defaultdict(float)
            revenue_by_coin = defaultdict(float)
            fee_by_coin = defaultdict(float)
            for r in group:
                op = _g(r, "operation")
                coin = _g(r, "coin")
                change = _parse_num(_g(r, "change")) or 0
                if op in ("Transaction Sold", "Transaction Spend"):
                    sold_by_coin[coin] += change
                elif op in ("Transaction Revenue", "Transaction Buy"):
                    revenue_by_coin[coin] += change
                elif op == "Transaction Fee":
                    fee_by_coin[coin] += change

            if not sold_by_coin or not revenue_by_coin:
                continue
            sold_asset = max(sold_by_coin, key=lambda k: -sold_by_coin[k])
            revenue_asset = max(revenue_by_coin, key=lambda k: revenue_by_coin[k])
            sold_qty = abs(sold_by_coin[sold_asset])
            rev_qty = revenue_by_coin[revenue_asset]
            if sold_qty == 0 or rev_qty == 0:
                continue

            fee_total = sum(abs(v) for v in fee_by_coin.values())

            # Reglas de detección BUY vs SELL:
            # 1. Si una moneda es stable quote (USDT/USDC/USD/ARS/...) y la otra no,
            #    la stable es la quote y la otra es el activo.
            # 2. Si ambas son stable (ej.: USDT→USDC), se trata como conversión FX
            #    sintética — registramos como SELL del sold_asset por simpleza.
            # 3. Si ninguna es stable (ej.: ETH→BTC), usamos crypto_quote como
            #    desempate: BTC > ETH > BNB > otros (la moneda más "quote-like").
            if _is_stable_quote(revenue_asset) and not _is_stable_quote(sold_asset):
                # SELL: vendiste el activo, recibiste stable
                tipo = "VENTA"; activo = sold_asset
                cantidad = sold_qty; monto = rev_qty
                precio = rev_qty / sold_qty
                quote_for_curr = revenue_asset
            elif _is_stable_quote(sold_asset) and not _is_stable_quote(revenue_asset):
                # BUY: pagaste con stable, recibiste el activo (incluye Convert USDT→ETH)
                tipo = "COMPRA"; activo = revenue_asset
                cantidad = rev_qty; monto = sold_qty
                precio = sold_qty / rev_qty
                quote_for_curr = sold_asset
            elif _is_crypto_quote(revenue_asset) and not _is_crypto_quote(sold_asset):
                # cripto-cripto: revenue es BTC/ETH/BNB → se considera quote
                tipo = "VENTA"; activo = sold_asset
                cantidad = sold_qty; monto = rev_qty
                precio = rev_qty / sold_qty
                quote_for_curr = revenue_asset
            elif _is_crypto_quote(sold_asset) and not _is_crypto_quote(revenue_asset):
                tipo = "COMPRA"; activo = revenue_asset
                cantidad = rev_qty; monto = sold_qty
                precio = sold_qty / rev_qty
                quote_for_curr = sold_asset
            else:
                # Ambos cripto sin distinción clara, o ambos stable. Default: SELL.
                tipo = "VENTA"; activo = sold_asset
                cantidad = sold_qty; monto = rev_qty
                precio = rev_qty / sold_qty
                quote_for_curr = revenue_asset

            out_idx += 1
            result.raw_rows.append(RawRow(row_index=out_idx, data={
                "fecha": _fix_date(time_key),
                "tipo": tipo,
                "broker": "Binance",
                "activo": activo,
                "cantidad": str(cantidad),
                "precio": str(precio),
                "monto": str(monto),
                "comisiones": str(fee_total),
                "moneda": _currency_for(quote_for_curr),
                "notas": f"Spot {time_key} ({sold_asset}/{revenue_asset})",
            }))

        # ── Futures trades agrupados por TradeID ─────────────
        # Micro-trades de futuros (|net| < $0.5): los emitimos como COMISION
        # en vez de FUTURES_PNL. Razón: cuando un trade es chiquito (apertura
        # rápida + cierre con leverage bajo), el "PnL" termina siendo casi todo
        # fee, no ganancia/pérdida real de mercado. Tratarlos como comisión
        # evita que ensucien stats (win rate, profit factor) y el operador no
        # los percibe como "trades perdidos" — son costos operativos.
        MICRO_FUTURES_THRESHOLD = 0.5
        for tid, group in futures_groups.items():
            net = 0.0
            time_val = ""
            for r in group:
                change = _parse_num(_g(r, "change")) or 0
                net += change
                if not time_val:
                    time_val = _g(r, "time")
            if abs(net) < 1e-8:
                continue
            out_idx += 1
            is_micro = abs(net) < MICRO_FUTURES_THRESHOLD
            if is_micro:
                tipo = "COMISION"
                monto_str = str(abs(net))
                notas = f"Futures TradeID {tid} (micro: <${MICRO_FUTURES_THRESHOLD:.2f}, tratado como fee)"
            else:
                tipo = "FUTURES_PNL"
                monto_str = str(net)
                notas = f"Futures TradeID {tid}"
            result.raw_rows.append(RawRow(row_index=out_idx, data={
                "fecha": _fix_date(time_val),
                "tipo": tipo,
                "broker": "Binance",
                "activo": "",
                "cantidad": "",
                "precio": "",
                "monto": monto_str,
                "comisiones": "",
                "moneda": "USD",
                "notas": notas,
            }))

        # ── Single rows: deposits, withdraws, P2P, funding fees ──
        for r in single_rows:
            op = _g(r, "operation")
            coin = _g(r, "coin")
            change = _parse_num(_g(r, "change")) or 0
            time_val = _g(r, "time")
            remark = _g(r, "remark")

            if op == "Transfer Between Main and Funding Wallet":
                continue

            if op == "Deposit":
                tipo = "DEPOSITO"; monto = abs(change)
            elif op == "Withdraw":
                tipo = "RETIRO"; monto = abs(change)
            elif op == "P2P Trading":
                tipo = "DEPOSITO" if change > 0 else "RETIRO"
                monto = abs(change)
            elif op == "Funding Fee":
                tipo = "INTERES" if change > 0 else "COMISION"
                monto = abs(change)
            else:
                continue  # Operation no soportada

            if monto == 0:
                continue

            notes_parts = [op]
            if remark:
                notes_parts.append(remark)

            out_idx += 1
            result.raw_rows.append(RawRow(row_index=out_idx, data={
                "fecha": _fix_date(time_val),
                "tipo": tipo,
                "broker": "Binance",
                "activo": "",
                "cantidad": "",
                "precio": "",
                "monto": str(monto),
                "comisiones": "",
                "moneda": _currency_for(coin),
                "notas": " · ".join(notes_parts),
            }))

        return result
