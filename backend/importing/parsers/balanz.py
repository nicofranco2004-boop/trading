"""Placeholder para parser de Balanz. Implementación pendiente."""
from typing import Optional
from .base import Parser
from ..schema import ParseResult, RowError


class BalanzParser(Parser):
    format_id = "balanz"
    display_name = "Balanz (próximamente)"
    is_supported = False

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        result.parse_errors.append(RowError(
            0, None, "PARSER_NOT_IMPLEMENTED",
            "El parser de Balanz todavía no está implementado. Usá el template genérico de Rendi por ahora.",
        ))
        return result
