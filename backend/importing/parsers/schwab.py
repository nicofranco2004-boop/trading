"""Parser de Charles Schwab — formato CSV oficial.

Cómo descargar (referencia para el wizard):
    1. Entrar a https://client.schwab.com
    2. Accounts → History
    3. Filtros: rango de fechas + "All transactions"
    4. Export → Format: CSV

Estructura del CSV:

    "Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"

Convenciones US:
- Decimales con `.`, miles con `,` ("1,234.56" → 1234.56).
- Currency: USD siempre (Schwab US).
- Date: "MM/DD/YYYY" o "MM/DD/YYYY as of MM/DD/YYYY" — tomamos la "as of"
  como fecha efectiva (es cuando ocurrió la operación; la primera es cuando
  Schwab posteó el registro).
- Quantity: SIEMPRE positiva. El `Action` (Buy/Sell) define dirección.
- Price/Amount: vienen con prefijo `$` o `-$` que strippeamos.

Action types mapeados al modelo Rendi:

    Schwab Action                  → Rendi      Notas
    ─────────────────────────────────────────────────────────────────────
    Buy                            → COMPRA
    Sell                           → VENTA
    Cash Dividend                  → DIVIDENDO  activo = Symbol
    Qualified Dividend             → DIVIDENDO
    Special Qual Div               → DIVIDENDO
    Qual Div Reinvest              → DIVIDENDO  (reinversión, sin qty)
    Credit Interest                → INTERES    cash interest
    Bond Interest                  → INTERES    free balance adjustment
    Wire Received                  → DEPOSITO
    MoneyLink Transfer (positive)  → DEPOSITO   dirección por signo de Amount
    MoneyLink Transfer (negative)  → RETIRO
    NRA Tax Adj                    → FEE        retención fiscal non-resident
    ADR Mgmt Fee                   → FEE        custodia ADR

Skipeados silenciosamente (no impactan cash):
    Expired Warrants     — corporate action informational
    Dist Rgts N-Trans    — distribution rights
    Internal Transfer    — movimientos internos entre cuentas Schwab
    Journaled Shares     — transferencia de securities (típico: migración
                           TDA → Schwab tras la adquisición)

Skipeados con warning visible al user:
    Stock Split          — Rendi no ajusta qty automáticamente. El user
                           debe editar la posición en /posiciones.

Particularidades:
- Schwab tells us QUÉ stock pagó cada dividendo (a diferencia de Cocos que
  dice "Peso argentino"). Preservamos activo=Symbol para dividends.
- Description se preserva como nota (ej.: "Tfr CITIBANK NA, PABLO O...").
- NRA Tax Adj suele acompañar a un Cash Dividend del mismo stock — los
  importamos separados para preservar el detalle.
"""
from __future__ import annotations
import csv
import io
import re
from typing import List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


# Headers requeridos — chequeamos al menos 3 de estos.
_REQUIRED_HEADERS = {"date", "action", "symbol", "amount"}

# Mapping de Action (lowercase) → tipo Rendi canónico.
# MoneyLink Transfer se trata por separado (depende del signo del Amount).
_OP_MAP = {
    "buy":                "COMPRA",
    "sell":               "VENTA",
    "cash dividend":      "DIVIDENDO",
    "qualified dividend": "DIVIDENDO",
    "special qual div":   "DIVIDENDO",
    "qual div reinvest":  "DIVIDENDO",
    "credit interest":    "INTERES",
    "bond interest":      "INTERES",
    "wire received":      "DEPOSITO",
    "nra tax adj":        "FEE",
    "adr mgmt fee":       "FEE",
}

# Skipeados sin reportar (corporate actions / movimientos internos).
_OP_SKIP_SILENT = {
    "expired warrants",
    "dist rgts n-trans",
    "internal transfer",
    "journaled shares",
}

# Skipeados con warning visible para que el user ajuste manualmente.
_OP_SKIP_WARN = {
    "stock split":
        "Stock Split — Rendi no ajusta cantidades automáticamente. "
        "Ajustá la qty del activo manualmente desde /posiciones después "
        "del import.",
}


def _strip(s) -> str:
    return (s or "").strip()


def _norm_header(h: str) -> str:
    """Normaliza header para matching: lowercase, sin espacios/&/comas."""
    if not h:
        return ""
    return (h.strip().lower()
            .replace(" ", "")
            .replace("&", "")
            .replace(",", ""))


def _parse_date(s: str) -> Optional[str]:
    """'05/06/2026' o '02/09/2026 as of 02/06/2026' → '2026-02-06'.

    Si está el "as of", usamos esa fecha (es la efectiva — la primera es
    cuando Schwab posteó el registro en el sistema).
    """
    if not s:
        return None
    s = s.strip()
    if " as of " in s:
        s = s.split(" as of ", 1)[1].strip()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if not m:
        return None
    mo, d, y = m.groups()
    return f"{y}-{mo}-{d}"


def _clean_money(s: str) -> str:
    """'$1,234.56' → '1234.56', '-$1.50' → '-1.50'. Vacío → ''."""
    if not s:
        return ""
    return s.strip().replace("$", "").replace(",", "").strip()


def _clean_qty(s: str) -> str:
    """'1,234' → '1234'. US format strict (no comma decimals)."""
    if not s:
        return ""
    return s.strip().replace(",", "")


def _abs_str(s: str) -> str:
    """Devuelve el valor absoluto en string."""
    s = s.strip()
    return s[1:] if s.startswith("-") else s


class SchwabParser(Parser):
    format_id = "schwab"
    display_name = "Charles Schwab"
    is_supported = True
    platform = "schwab"
    platform_label = "Charles Schwab"
    export_label = "History → Export CSV"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_norm_header(h) for h in headers}
        return len(_REQUIRED_HEADERS & norm) >= 3

    def template_csv(self) -> str:
        # Ejemplo basado en filas reales (anonimizado).
        return (
            '"Date","Action","Symbol","Description","Quantity","Price","Fees & Comm","Amount"\n'
            '"01/15/2024","Buy","AAPL","APPLE INC","100","$180.50","","-$18050.00"\n'
            '"03/15/2024","Cash Dividend","AAPL","APPLE INC","","","","$25.00"\n'
            '"06/20/2024","MoneyLink Transfer","","Tfr CITIBANK NA","","","","$10000.00"\n'
            '"08/15/2024","Sell","AAPL","APPLE INC","50","$220.00","$0.50","$10999.50"\n'
        )

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        if content.startswith("﻿"):
            content = content[1:]
        try:
            reader = csv.DictReader(io.StringIO(content))
            raw_headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(
                0, None, "FILE_UNREADABLE",
                f"No pudimos leer el archivo: {ex}",
            ))
            return result

        norm_to_orig = {_norm_header(h): h for h in raw_headers}
        present = _REQUIRED_HEADERS & set(norm_to_orig.keys())
        if len(present) < 3:
            result.parse_errors.append(RowError(
                0, None, "SCHWAB_HEADERS_MISMATCH",
                "Este archivo no parece un export oficial de Charles Schwab. "
                "Bajalo desde Schwab → Accounts → History → Export CSV.",
            ))
            return result

        def G(row, norm_key: str) -> str:
            col = norm_to_orig.get(norm_key)
            return _strip(row.get(col, "")) if col else ""

        for idx, row in enumerate(reader, start=1):
            action_raw = G(row, "action").lower()
            if not action_raw:
                continue

            # Skip silencioso (sin warning) — corporate actions / migraciones
            if action_raw in _OP_SKIP_SILENT:
                continue

            # Skip con warning visible — stock split, etc.
            if action_raw in _OP_SKIP_WARN:
                result.parse_errors.append(RowError(
                    idx, "Action", "SCHWAB_SPLIT_WARNING",
                    _OP_SKIP_WARN[action_raw],
                ))
                continue

            fecha = _parse_date(G(row, "date"))
            symbol = G(row, "symbol").upper()
            description = G(row, "description")
            qty_raw = _clean_qty(G(row, "quantity"))
            price_raw = _clean_money(G(row, "price"))
            fees_raw = _clean_money(G(row, "feescomm"))
            amount_raw = _clean_money(G(row, "amount"))

            # MoneyLink Transfer: dirección depende del signo del Amount
            if action_raw == "moneylink transfer":
                if not amount_raw:
                    continue  # informational sin valor
                tipo_rendi = "RETIRO" if amount_raw.startswith("-") else "DEPOSITO"
            elif action_raw in _OP_MAP:
                tipo_rendi = _OP_MAP[action_raw]
            else:
                result.parse_errors.append(RowError(
                    idx, "Action", "SCHWAB_OP_UNKNOWN",
                    f"Action no soportada: '{G(row, 'action')}'. "
                    f"Si pensás que debería importarse, mandanos un ejemplo.",
                ))
                continue

            # Computar campos del RawRow
            if tipo_rendi in ("COMPRA", "VENTA"):
                # Buy: amount negativo, lo abs-eamos. Sell: amount positivo.
                # Schwab nos da el monto NETO (Amount = qty*price - fees para
                # buys, qty*price + fees para sells — verificar). Por
                # consistencia con Rendi (que separa monto bruto + fees),
                # usamos qty*price como monto bruto y fees aparte.
                # Si price está vacío (Schwab no lo trae en algunos casos),
                # fallback a abs(amount).
                qty = qty_raw
                precio = price_raw
                if qty_raw and price_raw:
                    try:
                        monto_calc = float(qty_raw) * float(price_raw)
                        monto = f"{monto_calc:.4f}".rstrip("0").rstrip(".")
                    except ValueError:
                        monto = _abs_str(amount_raw)
                else:
                    monto = _abs_str(amount_raw)
                fees = _abs_str(fees_raw) if fees_raw else "0"
            else:
                # Cash flows / dividends / interest / fees: monto = abs(amount)
                qty = ""
                precio = ""
                monto = _abs_str(amount_raw)
                fees = "0"

            # Activo: preservamos symbol para BUY/SELL/DIVIDENDO. Para cash
            # flows va vacío (no aplica un activo a un wire/deposit).
            if tipo_rendi in ("COMPRA", "VENTA", "DIVIDENDO"):
                activo = symbol
            else:
                activo = ""

            # Notas: incluimos description si aporta info (típico Schwab:
            # "Tfr CITIBANK NA", "SCHWAB1 INT MM/DD-MM/DD", security name).
            notas = description[:200] if description else ""

            data = {
                "fecha":      fecha or "",
                "tipo":       tipo_rendi,
                "broker":     "Schwab",
                "activo":     activo,
                "cantidad":   qty,
                "precio":     precio,
                "monto":      monto,
                "monto_usd":  "",
                "tc":         "",
                "comisiones": fees,
                "moneda":     "USD",
                "notas":      notas,
            }
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        return result
