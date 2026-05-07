"""Placeholder para parser de Binance. Implementación pendiente."""
from typing import Optional
from .base import Parser
from ..schema import ParseResult, RowError


class BinanceParser(Parser):
    format_id = "binance"
    display_name = "Binance (próximamente)"
    is_supported = False

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        result.parse_errors.append(RowError(
            0, None, "PARSER_NOT_IMPLEMENTED",
            "El parser de Binance todavía no está implementado. Usá el template genérico de Rendi por ahora.",
        ))
        return result
