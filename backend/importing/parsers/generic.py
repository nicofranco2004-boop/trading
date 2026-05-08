"""Parser del template genérico de Rendi.

Formato: CSV con headers en castellano. Acepta una mezcla de operaciones
(compras, ventas, depósitos, retiros, conversiones, dividendos) en un mismo
archivo. La validación semántica vive en el normalizer/validator — este
parser solo se preocupa por extraer estructura.
"""
from __future__ import annotations
import csv
import io
from typing import List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


# Headers esperados (en orden — el template descargable los respeta).
GENERIC_HEADERS = [
    "fecha",
    "tipo",
    "broker",
    "activo",
    "cantidad",
    "precio",
    "monto",
    "monto_usd",
    "tc",
    "comisiones",
    "moneda",
    "notas",
]

# Headers obligatorios. Si falta alguno → error de parseo a nivel archivo.
REQUIRED_HEADERS = ["fecha", "tipo", "broker"]


def _normalize_header(h: str) -> str:
    return (h or "").strip().lower().lstrip("﻿")


class RendiGenericParser(Parser):
    format_id = "rendi_generic"
    display_name = "Template Rendi (genérico)"
    is_supported = True
    platform = "generic"
    platform_label = "Genérico (cualquier broker)"
    export_label = "Template Rendi"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_normalize_header(h) for h in headers}
        return all(h in norm for h in REQUIRED_HEADERS)

    def template_csv(self) -> str:
        # Ejemplos cubriendo cada tipo de operación
        rows = [
            GENERIC_HEADERS,
            ["2024-03-15", "COMPRA",    "Cocos",  "GGAL", "100", "1500", "", "", "", "10",  "ARS", "Compra inicial"],
            ["2024-05-20", "VENTA",     "Cocos",  "GGAL", "60",  "1900", "", "", "", "8",   "ARS", "Venta parcial"],
            ["2024-04-10", "DEPOSITO",  "Cocos",  "",     "",    "",     "500000", "", "", "", "ARS", "Aporte mensual"],
            ["2024-06-01", "CONVERSION_ARS_USD", "Cocos", "", "", "", "1200000", "1000", "1200", "", "", "Compra MEP"],
            ["2024-07-08", "DIVIDENDO", "IBKR",   "AAPL", "",    "",     "12.50",  "", "", "", "USD", "Dividendo trimestral"],
            ["2024-08-15", "RETIRO",    "Cocos",  "",     "",    "",     "200000", "", "", "", "ARS", ""],
        ]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerows(rows)
        return buf.getvalue()

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        # Manejar BOM y normalizar EOL
        if content.startswith("﻿"):
            content = content[1:]
        try:
            # Auto-detectar separador (coma o punto-y-coma)
            sample = content[:2048]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(io.StringIO(content), dialect=dialect)
            raw_headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(0, None, "FILE_UNREADABLE",
                                                f"No pudimos leer el archivo: {ex}"))
            return result

        if not raw_headers:
            result.parse_errors.append(RowError(0, None, "EMPTY_FILE",
                                                "El archivo no tiene encabezados."))
            return result

        # Mapear headers reales a snake_case
        header_map = {h: _normalize_header(h) for h in raw_headers}
        normalized_headers = set(header_map.values())
        missing = [h for h in REQUIRED_HEADERS if h not in normalized_headers]
        if missing:
            result.parse_errors.append(RowError(
                0, None, "MISSING_COLUMNS",
                f"Faltan columnas obligatorias: {', '.join(missing)}",
            ))
            return result

        for idx, row in enumerate(reader, start=1):
            data = {header_map[k]: (v.strip() if isinstance(v, str) else v)
                    for k, v in row.items() if k is not None}
            # Saltar filas completamente vacías
            if not any((v or "").strip() for v in data.values() if isinstance(v, str)):
                continue
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        return result
