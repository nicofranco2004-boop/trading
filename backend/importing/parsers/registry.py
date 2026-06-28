"""Registro central de parsers. Cualquier parser nuevo se agrega acá."""
from __future__ import annotations
from typing import List, Optional
from .base import Parser
from .generic import RendiGenericParser
from .binance import BinanceParser
from .binance_futures import BinanceFuturesTradeHistoryParser
from .binance_transaction import BinanceTransactionHistoryParser
from .cocos import CocosParser
from .balanz import BalanzParser
from .balanz_resultados import BalanzResultadosParser
from .balanz_movimientos import BalanzMovimientosParser
from .iol import IolParser
from .schwab import SchwabParser
from .bullmarket import BullMarketParser
from .ieb import IebParser
from .ppi import PpiParser


_PARSERS: List[Parser] = [
    RendiGenericParser(),
    BinanceParser(),
    BinanceFuturesTradeHistoryParser(),
    BinanceTransactionHistoryParser(),
    CocosParser(),
    # PPI antes de los parsers de Balanz: un export de PPI tiene Descripción +
    # Moneda + Importe (que BalanzMovimientos también pediría), pero solo PPI trae
    # `Saldo`. PpiParser.can_handle exige Saldo → no roba archivos de Balanz; y al
    # ir primero, agarra los de PPI antes de que BalanzMovimientos los matchee.
    PpiParser(),
    BalanzParser(),
    BalanzMovimientosParser(),
    BalanzResultadosParser(),
    IolParser(),
    SchwabParser(),
    BullMarketParser(),
    IebParser(),
]


def list_parsers() -> List[Parser]:
    return _PARSERS


def get_parser(format_id: str) -> Optional[Parser]:
    for p in _PARSERS:
        if p.format_id == format_id:
            return p
    return None


def autodetect(headers: List[str]) -> Optional[Parser]:
    """Devuelve el primer parser soportado que diga can_handle(headers).
    Si ninguno match, devuelve None y el caller debe pedirle al usuario que elija."""
    for p in _PARSERS:
        if p.is_supported and p.can_handle(headers):
            return p
    return None
