"""Parser de Binance Futures Trade History.

Formato: cada fila es una ejecución (parcial) de una orden. Una sola orden
de cierre puede generar 4-5 filas con el mismo Order ID si Binance la ejecutó
en partes. Agrupamos por Order ID para emitir UN registro por orden lógica.

Headers: Time, Symbol, Side, Price, Quantity, Amount, Fee, Realized Profit,
         Buyer, Maker, Trade ID, Order ID

Particularidades:
- Fechas en formato YY-MM-DD HH:MM:SS (e.g., 26-05-11 23:19:34).
- Fee con espacio y unit: "1.03657610 USDT".
- Realized Profit es 0 en aperturas, y tiene valor real en cierres.
- Todas las quantities están en base currency, prices en quote.

Mapeo a Rendi:
- Por cada Order ID con net != 0 (PnL realizado − fees), emitimos un
  FUTURES_PNL con asset=Symbol, monto=net, notas con TradeID y dirección.
- Aperturas puras (todas las filas con Realized Profit=0) emiten una fila
  con monto = −Σfees (refleja correctamente el costo de operar).
"""
from __future__ import annotations
import csv
import io
import re
from collections import defaultdict
from typing import List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


_REQUIRED = {"symbol", "side", "price", "quantity", "amount", "fee", "realized_profit"}
# Obligatoria — la fecha puede llamarse "Time" o "Date(UTC)" según versión
_DATE_HEADERS = {"time", "date(utc)"}


def _norm_header(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "_")


def _parse_num_with_optional_unit(s: str) -> float:
    """'1.03657610 USDT' → 1.03657610 · '0.5' → 0.5 · '-25.575' → -25.575"""
    if s is None:
        return 0.0
    s = str(s).strip()
    if not s:
        return 0.0
    # Strip trailing unit (after space or pegada)
    m = re.match(r"^(-?\d+(?:\.\d+)?)(?:\s*[A-Z][A-Z0-9]*)?$", s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fix_date(s: str) -> str:
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


class BinanceFuturesTradeHistoryParser(Parser):
    format_id = "binance_futures_trade_history"
    display_name = "Binance Futures Trade History"
    is_supported = True
    platform = "binance"
    platform_label = "Binance"
    export_label = "Futures → Trade History"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_norm_header(h) for h in headers}
        has_date = any(d in norm for d in _DATE_HEADERS)
        return has_date and _REQUIRED.issubset(norm)

    def template_csv(self) -> str:
        return (
            "Time,Symbol,Side,Price,Quantity,Amount,Fee,Realized Profit,Buyer,Maker,Trade ID,Order ID\n"
            "25-04-20 15:00:00,BTCUSDT,BUY,68000,0.1,6800,3.4 USDT,0,true,false,1001,5001\n"
            "25-04-22 09:30:00,BTCUSDT,SELL,69500,0.1,6950,3.475 USDT,150,false,false,1002,5002\n"
            "25-05-01 12:00:00,SOLUSDT,SELL,155,10,1550,0.775 USDT,0,false,false,1003,5003\n"
            "25-05-05 18:45:00,SOLUSDT,BUY,148,10,1480,0.74 USDT,70,true,false,1004,5004\n"
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
                0, None, "BINANCE_FUTURES_HEADERS_MISMATCH",
                "Este archivo no parece ser un Binance Futures Trade History "
                "(faltan columnas: Time/Date, Symbol, Side, Price, Quantity, "
                "Amount, Fee, Realized Profit). Verificá el formato."))
            return result

        h_map = {_norm_header(h): h for h in headers}
        date_key = "time" if "time" in h_map else "date(utc)"
        # Order ID puede venir como "Order ID" o "order_id" tras normalizar
        order_id_key = "order_id" if "order_id" in h_map else None

        def _g(row, key):
            return (row.get(h_map[key]) or "").strip() if key in h_map else ""

        # Agrupar por Order ID. Si no hay order_id, cada fila se trata sola.
        groups: dict = defaultdict(list)
        for raw in reader:
            oid = _g(raw, order_id_key) if order_id_key else ""
            if not oid:
                # fila sola — clave única
                oid = f"_solo_{id(raw)}"
            groups[oid].append(raw)

        out_idx = 0
        for oid, rows in groups.items():
            sum_qty = 0.0
            sum_amount = 0.0
            sum_fee = 0.0
            sum_pnl = 0.0
            symbol = ""
            side = ""
            time_val = ""
            for r in rows:
                sum_qty += _parse_num_with_optional_unit(_g(r, "quantity"))
                sum_amount += _parse_num_with_optional_unit(_g(r, "amount"))
                sum_fee += _parse_num_with_optional_unit(_g(r, "fee"))
                sum_pnl += _parse_num_with_optional_unit(_g(r, "realized_profit"))
                if not symbol:
                    symbol = _g(r, "symbol")
                if not side:
                    side = _g(r, "side")
                if not time_val:
                    time_val = _g(r, date_key)

            net = sum_pnl - sum_fee
            if abs(net) < 1e-8:
                continue  # apertura sin fee neta? skip

            avg_price = (sum_amount / sum_qty) if sum_qty else None
            notes_parts = [f"{side} {symbol}"]
            if sum_qty:
                notes_parts.append(f"qty {sum_qty:g}")
            if avg_price:
                notes_parts.append(f"@ {avg_price:.4f}")
            if oid and not oid.startswith("_solo_"):
                notes_parts.append(f"OrderID {oid}")

            out_idx += 1
            result.raw_rows.append(RawRow(row_index=out_idx, data={
                "fecha": _fix_date(time_val),
                "tipo": "FUTURES_PNL",
                "broker": "Binance",
                "activo": symbol,    # ej.: "BTCUSDT" — el usuario puede editar después
                "cantidad": "",
                "precio": "",
                "monto": str(round(net, 8)),
                "comisiones": "",    # ya descontadas en `net`
                "moneda": "USD",
                "notas": " · ".join(notes_parts),
            }))

        return result
