"""Placeholder honesto para Cocos Capital.

Cocos Capital actualmente NO ofrece un export oficial de operaciones desde su
plataforma. Este parser existe en el dropdown solo para informar al usuario
de esa limitación y redirigirlo al template genérico de Rendi.

Si en el futuro Cocos publica un export oficial, este parser se va a
implementar con headers verificados.
"""
from typing import Optional
from .base import Parser
from ..schema import ParseResult, RowError


class CocosParser(Parser):
    format_id = "cocos"
    display_name = "Cocos Capital (sin export oficial)"
    is_supported = False
    platform = "cocos"
    platform_label = "Cocos Capital (sin export oficial)"
    export_label = ""

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        result.parse_errors.append(RowError(
            0, None, "COCOS_NO_EXPORT",
            "Cocos Capital no ofrece un export oficial de operaciones desde su "
            "plataforma. Para importar tu historial, armá un CSV manualmente con "
            "el template genérico de Rendi (lo podés descargar desde el wizard) "
            "o copialo a mano desde la sección Movimientos."
        ))
        return result
