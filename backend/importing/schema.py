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
OP_FUTURES_PNL = "FUTURES_PNL"   # PnL realizado de un cierre de posición de futuros

OPERATION_TYPES = {
    OP_BUY, OP_SELL, OP_DEPOSIT, OP_WITHDRAW, OP_DIVIDEND, OP_INTEREST,
    OP_TRANSFER, OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS, OP_FEE, OP_FUTURES_PNL,
}

# Aliases que aceptamos en el CSV — castellano + inglés + variantes comunes de brokers
OP_TYPE_ALIASES = {
    # Compra (incluye stock splits y dividend reinvestments — añaden qty / costo)
    "COMPRA": OP_BUY, "BUY": OP_BUY, "PURCHASE": OP_BUY, "BOUGHT": OP_BUY,
    "BUY_TO_OPEN": OP_BUY, "BUY-TO-OPEN": OP_BUY, "BTO": OP_BUY, "B": OP_BUY,
    "REINVEST": OP_BUY, "REINVESTED": OP_BUY, "DRIP": OP_BUY,
    "REINVEST_DIVIDEND": OP_BUY, "REINVEST_SHARES": OP_BUY,
    "DIVIDEND_REINVESTMENT": OP_BUY, "REINVERSION": OP_BUY,
    # Venta (incluye redemptions, asignaciones, llamadas)
    "VENTA": OP_SELL, "SELL": OP_SELL, "SALE": OP_SELL, "SOLD": OP_SELL,
    "SELL_TO_CLOSE": OP_SELL, "SELL-TO-CLOSE": OP_SELL, "STC": OP_SELL, "S": OP_SELL,
    "REDEMPTION": OP_SELL, "REDEEM": OP_SELL, "LIQUIDATION": OP_SELL,
    "CALLED_AWAY": OP_SELL, "ASSIGNED": OP_SELL, "ASSIGNMENT": OP_SELL,
    "RESCATE": OP_SELL, "RESCATE_FCI": OP_SELL,
    "CASH_MERGER": OP_SELL, "TENDER": OP_SELL, "TENDER_OFFER": OP_SELL,
    "MANDATORY_REDEMPTION": OP_SELL, "MANDATORY_TENDER": OP_SELL,
    # Depósito (variantes castellano + inglés + frases comunes en exports AR/US)
    "DEPOSITO": OP_DEPOSIT, "DEPÓSITO": OP_DEPOSIT, "DEPOSIT": OP_DEPOSIT,
    "DEP": OP_DEPOSIT, "INGRESO": OP_DEPOSIT, "FUNDING": OP_DEPOSIT,
    "WIRE_IN": OP_DEPOSIT, "WIRE_TRANSFER_IN": OP_DEPOSIT,
    "INCOMING_WIRE": OP_DEPOSIT, "INCOMING_TRANSFER": OP_DEPOSIT,
    "ACH_IN": OP_DEPOSIT, "ACH_DEPOSIT": OP_DEPOSIT, "CASH_IN": OP_DEPOSIT,
    "CASHIN": OP_DEPOSIT, "TOP_UP": OP_DEPOSIT, "TOPUP": OP_DEPOSIT,
    "ACAT_IN": OP_DEPOSIT, "ACAT_RECEIVE": OP_DEPOSIT,
    "JOURNAL_FROM": OP_DEPOSIT, "JOURNAL_IN": OP_DEPOSIT,
    "TRANSFER_IN": OP_DEPOSIT, "DIRECT_DEPOSIT": OP_DEPOSIT,
    "ELECTRONIC_FUNDS_TRANSFER_IN": OP_DEPOSIT, "EFT_IN": OP_DEPOSIT,
    "BUY_TRANSFER_IN": OP_DEPOSIT, "MONEYLINK_DEPOSIT": OP_DEPOSIT,
    "NET_DEPOSIT": OP_DEPOSIT, "INITIAL_DEPOSIT": OP_DEPOSIT,
    "CASH_RECEIPT": OP_DEPOSIT, "FUNDS_IN": OP_DEPOSIT, "FUNDS_RECEIVED": OP_DEPOSIT,
    "INGRESO_DE_DINERO": OP_DEPOSIT, "INGRESO_DINERO": OP_DEPOSIT,
    "INGRESO_DE_FONDOS": OP_DEPOSIT, "INGRESO_FONDOS": OP_DEPOSIT,
    "APORTE": OP_DEPOSIT, "APORTE_INICIAL": OP_DEPOSIT, "APORTE_DE_CAPITAL": OP_DEPOSIT,
    "DEPOSITO_BANCARIO": OP_DEPOSIT, "ACREDITACION": OP_DEPOSIT, "ACREDITACIÓN": OP_DEPOSIT,
    "TRANSFERENCIA_RECIBIDA": OP_DEPOSIT, "RECIBIDO": OP_DEPOSIT,
    "SUSCRIPCION": OP_DEPOSIT, "SUSCRIPCIÓN": OP_DEPOSIT, "SUSCRIPCION_FCI": OP_DEPOSIT,
    # Retiro (variantes castellano + inglés)
    "RETIRO": OP_WITHDRAW, "WITHDRAW": OP_WITHDRAW, "WITHDRAWAL": OP_WITHDRAW,
    "EGRESO": OP_WITHDRAW, "WD": OP_WITHDRAW, "WIRE_OUT": OP_WITHDRAW,
    "WIRE_TRANSFER_OUT": OP_WITHDRAW, "OUTGOING_WIRE": OP_WITHDRAW,
    "OUTGOING_TRANSFER": OP_WITHDRAW,
    "ACH_OUT": OP_WITHDRAW, "ACH_WITHDRAWAL": OP_WITHDRAW, "CASH_OUT": OP_WITHDRAW,
    "CASHOUT": OP_WITHDRAW,
    "ACAT_OUT": OP_WITHDRAW, "ACAT_DELIVER": OP_WITHDRAW,
    "JOURNAL_TO": OP_WITHDRAW, "JOURNAL_OUT": OP_WITHDRAW,
    "TRANSFER_OUT": OP_WITHDRAW, "ATM_WITHDRAWAL": OP_WITHDRAW,
    "ELECTRONIC_FUNDS_TRANSFER_OUT": OP_WITHDRAW, "EFT_OUT": OP_WITHDRAW,
    "MONEYLINK_WITHDRAWAL": OP_WITHDRAW,
    "NET_WITHDRAWAL": OP_WITHDRAW, "CASH_DISBURSEMENT": OP_WITHDRAW,
    "FUNDS_OUT": OP_WITHDRAW, "FUNDS_SENT": OP_WITHDRAW,
    "EGRESO_DE_DINERO": OP_WITHDRAW, "EGRESO_DINERO": OP_WITHDRAW,
    "EGRESO_DE_FONDOS": OP_WITHDRAW, "EGRESO_FONDOS": OP_WITHDRAW,
    "RETIRO_DE_DINERO": OP_WITHDRAW, "RETIRO_DE_FONDOS": OP_WITHDRAW,
    "EXTRACCION": OP_WITHDRAW, "EXTRACCIÓN": OP_WITHDRAW,
    "TRANSFERENCIA_ENVIADA": OP_WITHDRAW, "ENVIADO": OP_WITHDRAW,
    # Dividendo (incluye variantes calificadas, ordinarias, cash, bonos,
    # distribuciones de fondos, ADRs, dividendos en lugar de pago)
    "DIVIDENDO": OP_DIVIDEND, "DIVIDEND": OP_DIVIDEND, "DIV": OP_DIVIDEND,
    "DIVIDENDS": OP_DIVIDEND, "DIVIDENDOS": OP_DIVIDEND,
    "QUALIFIED_DIVIDEND": OP_DIVIDEND, "ORDINARY_DIVIDEND": OP_DIVIDEND,
    "NON_QUALIFIED_DIV": OP_DIVIDEND, "CASH_DIVIDEND": OP_DIVIDEND,
    "STOCK_DIVIDEND": OP_DIVIDEND, "BOND_DIVIDEND": OP_DIVIDEND,
    "DIVIDEND_PAYOUT": OP_DIVIDEND, "DIV_PAYMENT": OP_DIVIDEND,
    "COUPON": OP_DIVIDEND, "COUPON_PAYMENT": OP_DIVIDEND,
    "RENTA": OP_DIVIDEND, "AMORTIZACION": OP_DIVIDEND, "AMORTIZACIÓN": OP_DIVIDEND,
    # Distribuciones de ETFs / fondos
    "DISTRIBUTION": OP_DIVIDEND, "DISTRIBUCION": OP_DIVIDEND, "DISTRIBUCIÓN": OP_DIVIDEND,
    "CAPITAL_GAIN_DISTRIBUTION": OP_DIVIDEND, "CAPITAL_GAINS_DISTRIBUTION": OP_DIVIDEND,
    "CAP_GAIN_DIST": OP_DIVIDEND, "LONG_TERM_GAIN_DIST": OP_DIVIDEND,
    "SHORT_TERM_GAIN_DIST": OP_DIVIDEND, "LIQUIDATING_DIVIDEND": OP_DIVIDEND,
    "ADR_DISTRIBUTION": OP_DIVIDEND, "ADR_DIVIDEND": OP_DIVIDEND,
    # Payment In Lieu (cuando un broker presta tus acciones, te paga en lugar
    # del dividendo real — fiscalmente diferente pero a efectos de portfolio
    # se trata igual que un dividendo)
    "PIL": OP_DIVIDEND, "PAYMENT_IN_LIEU": OP_DIVIDEND, "PMT_IN_LIEU": OP_DIVIDEND,
    # Interés (ahorro, money market, sweep, staking crypto, airdrops, promos)
    "INTERES": OP_INTEREST, "INTERÉS": OP_INTEREST, "INTEREST": OP_INTEREST,
    "INTERESES": OP_INTEREST, "REWARD": OP_INTEREST, "STAKING": OP_INTEREST,
    "INTEREST_INCOME": OP_INTEREST, "BANK_INTEREST": OP_INTEREST,
    "STAKING_REWARD": OP_INTEREST, "REWARDS": OP_INTEREST,
    "EARN_REWARD": OP_INTEREST, "INTERESES_GANADOS": OP_INTEREST,
    "CASH_SWEEP": OP_INTEREST, "MONEY_MARKET_INTEREST": OP_INTEREST,
    "MARGIN_CREDIT": OP_INTEREST, "CREDIT_INTEREST": OP_INTEREST,
    "AIRDROP": OP_INTEREST, "PROMO": OP_INTEREST, "PROMOTION": OP_INTEREST,
    "BONUS": OP_INTEREST, "REFERRAL_BONUS": OP_INTEREST, "SIGN_UP_BONUS": OP_INTEREST,
    # Transferencia (genérico — el normalizer intentará re-clasificar por signo
    # de monto antes de fallar)
    "TRANSFERENCIA": OP_TRANSFER, "TRANSFER": OP_TRANSFER, "XFER": OP_TRANSFER,
    "WIRE_TRANSFER": OP_TRANSFER, "WIRE": OP_TRANSFER,
    "ACAT": OP_TRANSFER, "JOURNAL": OP_TRANSFER, "JNL": OP_TRANSFER,
    # FX
    "FX_ARS_USD": OP_FX_ARS_TO_USD, "CONVERSION_ARS_USD": OP_FX_ARS_TO_USD,
    "CONVERSIÓN_ARS_USD": OP_FX_ARS_TO_USD, "ARS_TO_USD": OP_FX_ARS_TO_USD,
    "ARS→USD": OP_FX_ARS_TO_USD, "DOLAR_MEP": OP_FX_ARS_TO_USD, "MEP": OP_FX_ARS_TO_USD,
    "FX_USD_ARS": OP_FX_USD_TO_ARS, "CONVERSION_USD_ARS": OP_FX_USD_TO_ARS,
    "CONVERSIÓN_USD_ARS": OP_FX_USD_TO_ARS, "USD_TO_ARS": OP_FX_USD_TO_ARS,
    "USD→ARS": OP_FX_USD_TO_ARS,
    # Fee (comisiones, impuestos, retenciones, fees de ADR/custodia/cuenta)
    "FEE": OP_FEE, "COMISION": OP_FEE, "COMISIÓN": OP_FEE, "FEES": OP_FEE,
    "COMMISSION": OP_FEE, "CHARGE": OP_FEE,
    "MANAGEMENT_FEE": OP_FEE, "ADVISORY_FEE": OP_FEE, "PLATFORM_FEE": OP_FEE,
    "CUSTODY_FEE": OP_FEE, "CUSTODIAN_FEE": OP_FEE,
    "WIRE_FEE": OP_FEE, "ACH_FEE": OP_FEE,
    "INACTIVITY_FEE": OP_FEE, "IRA_FEE": OP_FEE, "ACCOUNT_FEE": OP_FEE,
    "ADR_FEE": OP_FEE, "ADR_MGMT_FEE": OP_FEE, "ADR_MAINT_FEE": OP_FEE,
    "ADR_MAINTENANCE_FEE": OP_FEE, "ADR_MANAGEMENT_FEE": OP_FEE,
    "MARGIN_INTEREST": OP_FEE, "BORROW_FEE": OP_FEE, "STOCK_BORROW_FEE": OP_FEE,
    "TAX": OP_FEE, "WITHHOLDING_TAX": OP_FEE, "IIBB": OP_FEE,
    "WHTAX": OP_FEE, "WH_TAX": OP_FEE, "WITHHOLDING": OP_FEE,
    "FOREIGN_TAX_PAID": OP_FEE, "FOREIGN_TAX": OP_FEE,
    "IMPUESTO": OP_FEE, "IMPUESTOS": OP_FEE, "RETENCION": OP_FEE, "RETENCIÓN": OP_FEE,
    "ARANCEL": OP_FEE, "DERECHO_DE_MERCADO": OP_FEE,
    # Futures PnL (cierre de posición — afecta cash y se registra como operación)
    "FUTURES_PNL": OP_FUTURES_PNL, "FUTURES PNL": OP_FUTURES_PNL,
    "FUTUROS_PNL": OP_FUTURES_PNL, "REALIZED_PNL": OP_FUTURES_PNL,
}


# Operaciones que reconocemos pero NO importamos automáticamente. Necesitan
# lógica especial (ajustar qty de posición existente, crear activo nuevo, etc.).
# Mejor fallar con mensaje claro que adivinar mal.
# Key: alias normalizado (uppercase + space→underscore). Value: mensaje user-facing.
UNSUPPORTED_OP_HINTS = {
    "STOCK_SPLIT": "Stock split — no se importa automáticamente porque necesita ajustar la cantidad de la posición existente por el ratio. Ajustá la qty del activo manualmente desde Posiciones.",
    "SPLIT": "Stock split — no se importa automáticamente. Ajustá la qty del activo manualmente desde Posiciones.",
    "REVERSE_SPLIT": "Reverse stock split — no se importa automáticamente. Ajustá la qty del activo manualmente desde Posiciones.",
    "SPIN_OFF": "Spin-off — crea un activo nuevo con cost basis derivado del original. Cargalo a mano: agregá el activo nuevo en Posiciones y editá el cost basis del original si hace falta.",
    "SPINOFF": "Spin-off — no se importa automáticamente. Cargalo a mano desde Posiciones.",
    "MERGER": "Merger / fusión — reemplaza un activo por otro. Cargalo a mano: borrá la posición vieja y creá la nueva.",
    "ACQUISITION": "Adquisición / merger — reemplaza un activo por otro. Cargalo a mano desde Posiciones.",
    "STOCK_MERGER": "Merger en acciones (sin cash) — reemplaza un activo por otro con un ratio. Cargalo a mano.",
    "CAUCION": "Caución bursátil — instrumento de financiamiento de corto plazo. No se importa automáticamente; cargá el interés ganado como Interés y el movimiento de cash a mano.",
    "CAUCIÓN": "Caución bursátil — instrumento de financiamiento de corto plazo. No se importa automáticamente; cargá el interés ganado como Interés y el movimiento de cash a mano.",
    "PLAZO_FIJO": "Plazo fijo — instrumento de renta fija. No se importa automáticamente; cargá los intereses como Interés y el movimiento de capital a mano.",
    "FIXED_DEPOSIT": "Plazo fijo / fixed deposit — no se importa automáticamente. Cargalo a mano.",
    "CONVERT": "Conversión cripto-a-cripto (ej: BTC→ETH) — necesita un par SELL+BUY atómico. Mejor cargá las dos operaciones por separado.",
    "CONVERSION": "Conversión cripto-a-cripto o entre activos — necesita lógica de SELL+BUY. Cargala a mano como dos operaciones separadas.",
    "CRYPTO_CONVERT": "Conversión cripto-a-cripto — cargala a mano como SELL del activo origen + BUY del activo destino.",
    "FORK": "Fork de cripto — el activo nuevo se crea con cost basis 0. Cargalo a mano agregando una posición nueva en Posiciones.",
    "HARD_FORK": "Hard fork de cripto — cargalo a mano desde Posiciones.",
    "SOFT_FORK": "Soft fork de cripto — cargalo a mano desde Posiciones.",
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
    # Fase 4 audit follow-up (2026-05-30): gross_amount_usd stamped al
    # preview/confirm time (con tc_blue del momento del import). El
    # persister DEBE usar este valor en `_apply_cash_flow` para acumular
    # en monthly_entries — así el USD persistido coincide exactamente con
    # el `import_normalized_tx.gross_amount_usd` stamped. Sin esto, había
    # drift potencial si tc_blue cambiaba entre confirm y persist.
    gross_amount_usd: Optional[float] = None

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
