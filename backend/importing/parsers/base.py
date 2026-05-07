"""Contrato base para parsers de CSV."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from ..schema import ParseResult


class Parser(ABC):
    # Identificador estable: 'rendi_generic' | 'binance' | 'cocos' | 'balanz'.
    format_id: str = ""
    # Nombre legible (para el dropdown en la UI).
    display_name: str = ""
    # Si False, aparece en la UI como "Próximamente" y no procesa.
    is_supported: bool = True

    @abstractmethod
    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        """Parsea el contenido textual del CSV. Devuelve filas crudas + errores de parsing.

        Esta etapa NO valida semánticamente — solo extrae estructura. Errores
        típicos acá: encoding, columnas faltantes, headers ilegibles.
        """
        ...

    def can_handle(self, headers: List[str]) -> bool:
        """Heurística para autodetección. Default: False. Cada parser puede sobrescribir."""
        return False

    def template_csv(self) -> str:
        """CSV de ejemplo para descargar. Vacío por default."""
        return ""
