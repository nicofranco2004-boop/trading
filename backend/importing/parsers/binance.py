"""Parser de Binance Spot Trade History.

Formato verificado contra la doc oficial y parsers open-source (BittyTax).
Headers esperados: Date(UTC),Pair,Side,Price,Executed,Amount,Fee

Particularidades del formato Binance que este parser maneja:
- Pair concatenado sin separador (BTCUSDT, ETHBTC, ARSBTC). Lo dividimos en
  base + quote usando una lista priorizada de quote assets conocidos.
- Valores numéricos con la unidad pegada al string ("0.02351000BTC", no
  "0.02351000"). Regex separa el número del ticker.
- Fee puede venir en base, quote o BNB (si el usuario tiene "Use BNB to pay
  fees" activado). Convertimos a la quote currency cuando es posible; si está
  en BNB u otra cripto desconocida, dejamos fee=0 y registramos en notas.
- 8 decimales fijos siempre.

Limitaciones conocidas:
- Export limitado a ventanas de 3 meses por archivo. Si el usuario tiene más
  historial, va a tener varios archivos. El dedup por fingerprint detecta
  operaciones repetidas si suben dos archivos con overlap.
- Binance también ofrece un export "Transaction History" con headers
  distintos (UTC_Time, Account, Operation, Asset, Change, Remark) que separa
  cada lado del trade en filas distintas (multi-row por trade, agrupadas por
  Order ID en `Remark`). Ese formato es más comprehensivo pero requiere
  reconstruir trades agrupando filas. NO está soportado en esta versión —
  para Transaction History el usuario debe usar el template genérico.
"""
from __future__ import annotations
import csv
import io
import re
from typing import List, Optional, Tuple
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


# Quote assets conocidos de Binance, ordenados por longitud descendente para
# resolver ambigüedades (FDUSD antes que USD, USDT antes que USD, etc.).
_QUOTE_ASSETS = sorted(
    [
        # Stablecoins USD
        "FDUSD", "BUSD", "USDC", "USDT", "TUSD", "USDP", "DAI",
        # Cripto base pairs
        "BTC", "ETH", "BNB", "TRX", "XRP", "DOT", "DOGE",
        # Fiat
        "USD", "EUR", "GBP", "ARS", "BRL", "AUD", "TRY", "RUB", "JPY",
        "ZAR", "UAH", "RON", "PLN", "CZK", "MXN", "COP", "CHF",
    ],
    key=len, reverse=True,
)

_NUM_WITH_UNIT = re.compile(r"^(-?\d+(?:\.\d+)?)([A-Z][A-Z0-9]*)?$")
# Headers obligatorios. La columna de fecha puede llamarse "Date(UTC)" o "Time"
# según la versión del export de Binance.
_BINANCE_REQUIRED = {"pair", "side", "price", "executed", "amount", "fee"}
_BINANCE_DATE_HEADERS = {"date(utc)", "time"}


def _fix_date(s: str) -> str:
    """Convierte 'YY-MM-DD HH:MM:SS' o 'YYYY-MM-DD HH:MM:SS' al primer 10 chars
    en formato YYYY-MM-DD."""
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


def _split_pair(pair: str) -> Optional[Tuple[str, str]]:
    """BTCUSDT → (BTC, USDT). Devuelve None si no matchea ningún quote conocido."""
    p = (pair or "").strip().upper()
    for q in _QUOTE_ASSETS:
        if p.endswith(q) and len(p) > len(q):
            return p[: -len(q)], q
    return None


def _split_num_unit(s: str) -> Tuple[Optional[float], str]:
    """'0.02351000BTC' → (0.02351, 'BTC'). '999.39867500USDT' → (999.398675, 'USDT')."""
    if s is None:
        return None, ""
    s = str(s).strip()
    if not s:
        return None, ""
    m = _NUM_WITH_UNIT.match(s)
    if not m:
        # Intentar parseo simple sin unidad
        try:
            return float(s), ""
        except ValueError:
            return None, ""
    try:
        return float(m.group(1)), (m.group(2) or "").upper()
    except ValueError:
        return None, ""


class BinanceParser(Parser):
    format_id = "binance"
    display_name = "Binance Spot Trade History"
    is_supported = True
    platform = "binance"
    platform_label = "Binance"
    export_label = "Spot → Trade History"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {(h or "").strip().lower() for h in headers}
        has_date = any(d in norm for d in _BINANCE_DATE_HEADERS)
        return has_date and _BINANCE_REQUIRED.issubset(norm)

    def template_csv(self) -> str:
        # Sample con 4 trades cubriendo BUY/SELL en USDT y ARS
        return (
            "Date(UTC),Pair,Side,Price,Executed,Amount,Fee\n"
            "2024-03-15 14:23:47,BTCUSDT,BUY,68500.50000000,0.02351000BTC,1610.45842500USDT,0.00002351BTC\n"
            "2024-04-02 09:11:22,ETHUSDT,SELL,3520.75000000,1.50000000ETH,5281.12500000USDT,5.28112500USDT\n"
            "2024-05-18 16:45:03,BTCARS,BUY,75000000.00000000,0.00100000BTC,75000.00000000ARS,0.00000100BTC\n"
            "2024-06-22 11:30:58,SOLUSDT,SELL,178.42000000,12.00000000SOL,2141.04000000USDT,0.01200000BNB\n"
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
                0, None, "BINANCE_HEADERS_MISMATCH",
                "Este archivo no parece ser un export de Binance Spot Trade History "
                "(faltan columnas esperadas: Date(UTC), Pair, Side, Price, Executed, "
                "Amount, Fee). Verificá que sea ese formato exacto, o usá el template "
                "genérico de Rendi y mapeá las columnas a mano."))
            return result

        # Mapeo case-insensitive de headers reales → keys esperadas
        h_map = {(h or "").strip().lower(): h for h in headers}
        # La columna fecha puede ser "Date(UTC)" o "Time"
        date_key = "date(utc)" if "date(utc)" in h_map else "time"

        for idx, row in enumerate(reader, start=1):
            date_raw = (row.get(h_map[date_key]) or "").strip()
            pair_raw = (row.get(h_map["pair"]) or "").strip()
            side_raw = (row.get(h_map["side"]) or "").strip().upper()
            price_raw = (row.get(h_map["price"]) or "").strip()
            executed_raw = (row.get(h_map["executed"]) or "").strip()
            amount_raw = (row.get(h_map["amount"]) or "").strip()
            fee_raw = (row.get(h_map["fee"]) or "").strip()

            if not date_raw or not pair_raw:
                continue  # fila vacía

            split = _split_pair(pair_raw)
            if not split:
                # Pair no reconocido — emitir igual con el pair como asset y dejar
                # que el normalizer/validator lo flaguee.
                base, quote = pair_raw, "USDT"
            else:
                base, quote = split

            qty, _ = _split_num_unit(executed_raw)
            amount, _ = _split_num_unit(amount_raw)
            try:
                price = float(price_raw)
            except ValueError:
                price = None
            fee_qty, fee_unit = _split_num_unit(fee_raw)

            # Convertir fee a la quote currency cuando es posible
            fee_in_quote = 0.0
            fee_note = ""
            if fee_qty:
                if fee_unit == quote:
                    fee_in_quote = fee_qty
                elif fee_unit == base and price:
                    fee_in_quote = fee_qty * price
                elif fee_unit and fee_unit not in (quote, base):
                    # Fee pagado en BNB u otra cripto — no podemos convertir
                    # sin tipo de cambio. Lo registramos en notas.
                    fee_note = f"Fee {fee_qty} {fee_unit} (no convertido)"

            # Solo soportamos quotes que se mapeen a una currency válida del
            # motor (USDT, USD, ARS). Quotes cripto (BTC/ETH/BNB) se mapean a
            # USDT como aproximación — el usuario verá el monto en quote
            # cripto pero la moneda interna queda como USDT.
            currency_map = {
                "USDT": "USD", "USDC": "USD", "BUSD": "USD", "FDUSD": "USD",
                "TUSD": "USD", "USDP": "USD", "DAI": "USD", "USD": "USD",
                "ARS": "ARS",
            }
            row_currency = currency_map.get(quote, "USD")

            notes_parts = [f"Pair: {pair_raw}"]
            if fee_note:
                notes_parts.append(fee_note)
            if quote not in currency_map:
                notes_parts.append(f"Quote en {quote}, valuado como USD")

            data = {
                "fecha": _fix_date(date_raw),  # YY-MM-DD → YYYY-MM-DD si hace falta
                "tipo": side_raw,         # BUY / SELL — ya son aliases válidos
                "broker": "Binance",      # default; el wizard puede sobrescribir
                "activo": base,
                "cantidad": str(qty) if qty is not None else "",
                "precio": str(price) if price is not None else "",
                "monto": str(amount) if amount is not None else "",
                "comisiones": str(round(fee_in_quote, 8)) if fee_in_quote else "",
                "moneda": row_currency,
                "notas": " · ".join(notes_parts),
            }
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        return result
