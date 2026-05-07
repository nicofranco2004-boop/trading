"""Placeholder para parser de Cocos Capital. Implementación pendiente."""
from typing import Optional
from .base import Parser
from ..schema import ParseResult, RowError


class CocosParser(Parser):
    format_id = "cocos"
    display_name = "Cocos Capital (próximamente)"
    is_supported = False

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        result.parse_errors.append(RowError(
            0, None, "PARSER_NOT_IMPLEMENTED",
            "El parser de Cocos Capital todavía no está implementado. Usá el template genérico de Rendi por ahora.",
        ))
        return result
