"""Modelo interno normalizado para el importer de CSV.

Cada fila del CSV, después del parser específico del broker, se traduce a una
NormalizedTx. La capa de persistencia consume NormalizedTx y la traduce a las
operaciones del motor existente (positions / operations / cash_flow / conversiones).

NormalizedTx no se persiste tal cual; se guarda una copia en
`import_normalized_tx` solo para auditoría y revert.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


# ─── Enums (strings simples para serializar a SQLite) ────────────────────────

OP_BUY = "BUY"
OP_SELL = "SELL"
OP_DEPOSIT = "DEPOSIT"
OP_WITHDRAW = "WITHDRAW"
OP_DIVIDEND = "DIVIDEND"
OP_INTEREST = "INTEREST"
OP_TRANSFER = "TRANSFER"
OP_FX_ARS_TO_USD = "FX_ARS_TO_USD"
OP_FX_USD_TO_ARS = "FX_USD_TO_ARS"
OP_FEE = "FEE"

OPERATION_TYPES = {
    OP_BUY, OP_SELL, OP_DEPOSIT, OP_WITHDRAW, OP_DIVIDEND, OP_INTEREST,
    OP_TRANSFER, OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS, OP_FEE,
}

# Aliases que aceptamos en el CSV — castellano + inglés + variantes comunes de brokers
OP_TYPE_ALIASES = {
    # Compra
    "COMPRA": OP_BUY, "BUY": OP_BUY, "PURCHASE": OP_BUY, "BOUGHT": OP_BUY,
    "BUY_TO_OPEN": OP_BUY, "BUY-TO-OPEN": OP_BUY, "BTO": OP_BUY, "B": OP_BUY,
    # Venta
    "VENTA": OP_SELL, "SELL": OP_SELL, "SALE": OP_SELL, "SOLD": OP_SELL,
    "SELL_TO_CLOSE": OP_SELL, "SELL-TO-CLOSE": OP_SELL, "STC": OP_SELL, "S": OP_SELL,
    # Depósito
    "DEPOSITO": OP_DEPOSIT, "DEPÓSITO": OP_DEPOSIT, "DEPOSIT": OP_DEPOSIT,
    "DEP": OP_DEPOSIT, "INGRESO": OP_DEPOSIT, "FUNDING": OP_DEPOSIT,
    "WIRE_IN": OP_DEPOSIT, "ACH_IN": OP_DEPOSIT, "CASH_IN": OP_DEPOSIT,
    "CASHIN": OP_DEPOSIT, "TOP_UP": OP_DEPOSIT, "TOPUP": OP_DEPOSIT,
    # Retiro
    "RETIRO": OP_WITHDRAW, "WITHDRAW": OP_WITHDRAW, "WITHDRAWAL": OP_WITHDRAW,
    "EGRESO": OP_WITHDRAW, "WD": OP_WITHDRAW, "WIRE_OUT": OP_WITHDRAW,
    "ACH_OUT": OP_WITHDRAW, "CASH_OUT": OP_WITHDRAW, "CASHOUT": OP_WITHDRAW,
    # Dividendo
    "DIVIDENDO": OP_DIVIDEND, "DIVIDEND": OP_DIVIDEND, "DIV": OP_DIVIDEND,
    "DIVIDENDS": OP_DIVIDEND, "DIVIDENDOS": OP_DIVIDEND,
    # Interés
    "INTERES": OP_INTEREST, "INTERÉS": OP_INTEREST, "INTEREST": OP_INTEREST,
    "INTERESES": OP_INTEREST, "REWARD": OP_INTEREST, "STAKING": OP_INTEREST,
    # Transferencia
    "TRANSFERENCIA": OP_TRANSFER, "TRANSFER": OP_TRANSFER, "XFER": OP_TRANSFER,
    # FX
    "FX_ARS_USD": OP_FX_ARS_TO_USD, "CONVERSION_ARS_USD": OP_FX_ARS_TO_USD,
    "CONVERSIÓN_ARS_USD": OP_FX_ARS_TO_USD, "ARS_TO_USD": OP_FX_ARS_TO_USD,
    "ARS→USD": OP_FX_ARS_TO_USD, "DOLAR_MEP": OP_FX_ARS_TO_USD, "MEP": OP_FX_ARS_TO_USD,
    "FX_USD_ARS": OP_FX_USD_TO_ARS, "CONVERSION_USD_ARS": OP_FX_USD_TO_ARS,
    "CONVERSIÓN_USD_ARS": OP_FX_USD_TO_ARS, "USD_TO_ARS": OP_FX_USD_TO_ARS,
    "USD→ARS": OP_FX_USD_TO_ARS,
    # Fee
    "FEE": OP_FEE, "COMISION": OP_FEE, "COMISIÓN": OP_FEE, "FEES": OP_FEE,
    "COMMISSION": OP_FEE, "CHARGE": OP_FEE,
}

# Asset types
AT_STOCK = "STOCK"
AT_CEDEAR = "CEDEAR"
AT_ETF = "ETF"
AT_CRYPTO = "CRYPTO"
AT_FIAT = "FIAT"
AT_BOND = "BOND"
AT_FUND = "FUND"
AT_OTHER = "OTHER"
ASSET_TYPES = {AT_STOCK, AT_CEDEAR, AT_ETF, AT_CRYPTO, AT_FIAT, AT_BOND, AT_FUND, AT_OTHER}

# Currencies que entendemos hoy
CURRENCIES = {"USD", "USDT", "ARS"}


@dataclass
class RawRow:
    """Una fila tal como vino del CSV, después de normalizar headers a snake_case."""
    row_index: int                     # número de fila visible al usuario (1-based, sin header)
    data: Dict[str, Any]               # columna → valor crudo (string)


@dataclass
class NormalizedTx:
    """Transacción normalizada al modelo común."""
    row_index: int                              # link al RawRow
    date: str                                   # YYYY-MM-DD
    broker: str                                 # mapea a portfolio_id
    operation_type: str                         # OPERATION_TYPES
    asset_symbol: Optional[str] = None
    asset_name: Optional[str] = None
    asset_type: Optional[str] = None            # ASSET_TYPES
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    gross_amount: Optional[float] = None
    fees: float = 0.0
    taxes: float = 0.0
    currency: Optional[str] = None              # moneda del precio/quantity
    settlement_currency: Optional[str] = None   # moneda en que se liquida (cash debit/credit)
    notes: Optional[str] = None

    def to_db_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RowError:
    row_index: int
    field: Optional[str]
    code: str           # 'INVALID_DATE', 'UNKNOWN_BROKER', 'MISSING_QUANTITY', etc.
    message: str        # mensaje en castellano para el usuario

    def to_dict(self) -> Dict[str, Any]:
        return {"row_index": self.row_index, "field": self.field, "code": self.code, "message": self.message}


@dataclass
class ParseResult:
    """Resultado de la etapa de parsing — antes de validación/normalización."""
    raw_rows: List[RawRow] = field(default_factory=list)
    parse_errors: List[RowError] = field(default_factory=list)


@dataclass
class PipelineResult:
    """Resultado final de preview: lo que devolvemos al frontend antes de confirmar."""
    raw_rows: List[RawRow]
    normalized: List[NormalizedTx]              # solo las válidas
    errors_by_row: Dict[int, List[RowError]]    # row_index → errores (parse + validation)
    parser_format: str
    file_name: Optional[str]
    file_hash: str
