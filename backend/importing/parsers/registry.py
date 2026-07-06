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
from .balanz_internacional import BalanzInternacionalParser
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
    # Movimientos PRIMERO entre los de Balanz: es el export recomendado (reconstruye
    # cartera + P&L + caja) y el wizard arranca en el PRIMER export soportado del grupo
    # → así el default de Balanz es Movimientos, no Órdenes (que rechazaba el archivo
    # pidiendo la columna `estado`). No pisa a Órdenes/Resultados en autodetect: sus
    # can_handle no se solapan (Movimientos exige Descripción+Importe; Órdenes exige
    # Estado; Resultados no trae Importe). PPI sigue antes (exige `Saldo`).
    BalanzMovimientosParser(),
    # Balanz INTERNACIONAL (cuenta exterior en USD): mismas columnas que Movimientos
    # local → NO autodetecta (can_handle=False), se elige explícito en el wizard bajo
    # el grupo "Balanz". Va después de Movimientos para que el autodetect siga cayendo
    # en el local ante ambigüedad de headers.
    BalanzInternacionalParser(),
    BalanzParser(),
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
