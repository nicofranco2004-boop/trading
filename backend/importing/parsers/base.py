"""Contrato base para parsers de CSV."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from ..schema import ParseResult


class Parser(ABC):
    # Identificador estable: 'rendi_generic' | 'binance' | 'cocos' | 'balanz'.
    format_id: str = ""
    # Nombre legible completo (para fallback en la UI).
    display_name: str = ""
    # Si False, aparece en la UI como "Próximamente" y no procesa.
    is_supported: bool = True
    # Agrupación a 2 niveles en el wizard:
    #   platform: "generic" | "binance" | "cocos" | "balanz"
    #   platform_label: cómo se muestra el nivel 1 en el dropdown
    #   export_label: cómo se muestra el nivel 2 (tipo de export dentro de la plataforma)
    # Cuando una plataforma tiene un solo parser, el segundo dropdown no aparece.
    platform: str = "generic"
    platform_label: str = "Genérico"
    export_label: str = ""
    # ¿Este broker tiene FOTO DE TENENCIA que se pueda subir para verificar el
    # import? El `parser_format` de esa foto, o None.
    #
    # Existe porque la reconciliación contra la foto es el mejor chequeo que
    # tiene el sistema —no depende de conocer el bug, la referencia es el
    # broker— pero sólo el 57,8% de la gente elegible la sube (medido: 160 de
    # 277 usuarios). El 42% restante no tiene ninguna verificación, y un
    # detector que no corre no detecta nada.
    #
    # 🔴 LA VERDAD VIVE ACÁ Y NO EN EL FRONTEND. Hasta ahora el único mapeo
    # movimientos→foto era un dict a mano en `ImportWizard.jsx`
    # (TENENCIA_BROKER_BY_FORMAT), y ya se desincronizó: tiene una entrada para
    # `balanz_internacional`, cuya foto NO existe. Un aviso manejado por ese
    # dict le pediría al usuario un archivo que ningún parser sabe leer.
    tenencia_format: Optional[str] = None

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
