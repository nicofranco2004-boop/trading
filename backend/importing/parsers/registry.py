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
from .schwab import SchwabParser


_PARSERS: List[Parser] = [
    RendiGenericParser(),
    BinanceParser(),
    BinanceFuturesTradeHistoryParser(),
    BinanceTransactionHistoryParser(),
    CocosParser(),
    BalanzParser(),
    SchwabParser(),
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
