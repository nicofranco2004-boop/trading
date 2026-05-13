"""Parser de Balanz (BETA — reconstrucción no verificada).

Balanz no tiene documentación pública del export CSV. Esta implementación se
basa en una reconstrucción razonable del formato típico de un ALYC argentino,
con tolerancia para variantes que aparecen en distintas pantallas/exports
("Fecha Concertación" vs "Fecha de Liquidación", "Tipo" vs "Tipo de
Operación", "Cantidad" vs "Valor Nominal", "Comisiones" vs "Arancel", etc.).

Particularidades manejadas:
- Fechas DD/MM/YYYY (formato AR).
- Tipo en español: Compra/Venta/Suscripción FCI/Rescate FCI/Dividendo/etc.
  El normalizer ya tiene fallback por keyword para estos casos.
- Moneda con valores ARS / USD / Pesos / Dólares / $ / U$S — normalizamos.
- Decimales con coma (es-AR) — el normalizer ya los maneja.
- Plazo (CI/24hs/48hs/72hs) — ignorado, no aplica al modelo Rendi.
- N° Boleto / Comprobante → notas como referencia.

LIMITACIÓN IMPORTANTE: este parser es una hipótesis. Si los headers reales de
tu export de Balanz no coinciden con los aliases de abajo, el parser va a
fallar. En ese caso, usá el template genérico de Rendi y mapeá las columnas
a mano. Si nos pasás un export real anonimizado, lo ajustamos.
"""
from __future__ import annotations
import csv
import io
from typing import Dict, List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


def _norm_header(h: str) -> str:
    """Normaliza headers para comparación: lowercase + saca tildes/eñe + reemplaza
    `°` y separadores raros (/, -) por espacios."""
    if not h:
        return ""
    s = (h.strip().lower()
           .replace("ó", "o").replace("í", "i").replace("á", "a")
           .replace("é", "e").replace("ú", "u").replace("ñ", "n")
           .replace("°", "").replace("/", " ").replace("-", " "))
    # Colapsar espacios múltiples
    return " ".join(s.split())


# Cada campo interno de Rendi se puede mapear desde varios headers reales.
# Los aliases están normalizados (sin tildes, lowercase, "/" y "-" como espacios).
_FIELD_ALIASES: Dict[str, List[str]] = {
    "fecha":      ["fecha concertacion", "fecha de concertacion",
                   "fecha liquidacion", "fecha de liquidacion",
                   "fecha operacion", "fecha de operacion", "fecha"],
    "tipo":       ["tipo", "tipo de operacion", "tipo operacion",
                   "operacion", "movimiento"],
    "activo":     ["especie", "ticker", "simbolo", "instrumento"],
    "cantidad":   ["cantidad", "valor nominal", "cantidad valor nominal",
                   "nominales", "vn"],
    "precio":     ["precio", "precio unitario", "precio promedio"],
    "moneda":     ["moneda", "moneda operacion", "moneda de la operacion"],
    "monto":      ["importe bruto", "monto bruto", "bruto",
                   "importe neto", "monto neto", "neto", "monto", "importe"],
    "comisiones": ["comisiones", "comision", "arancel", "arancel comision",
                   "arancel comisiones", "comision total"],
    "_descripcion": ["descripcion", "detalle"],
    "_boleto":    ["n boleto", "nro boleto", "numero boleto", "boleto",
                   "n operacion", "nro operacion", "comprobante"],
}

_REQUIRED_FIELDS = ("fecha", "tipo", "activo")


def _norm_currency(s: str) -> str:
    """ARS / Pesos / $ → ARS. USD / Dólares / U$S → USD. Otro → tal cual."""
    if not s:
        return ""
    v = s.strip().upper().replace("Ó", "O").replace("É", "E")
    if v in ("ARS", "PESOS", "PESO", "$", "AR$"):
        return "ARS"
    if v in ("USD", "USDT", "DOLARES", "DOLAR", "U$S", "US$"):
        return "USD"
    return v


def _resolve_columns(headers: List[str]) -> Dict[str, Optional[str]]:
    """Para cada campo de Rendi, encuentra el header real del archivo (o None).
    Devuelve dict con la primera columna que matchea cada alias."""
    norm_to_orig: Dict[str, str] = {}
    for h in headers:
        norm_to_orig.setdefault(_norm_header(h), h)
    resolved: Dict[str, Optional[str]] = {}
    used: set = set()
    for field, aliases in _FIELD_ALIASES.items():
        match = None
        for alias in aliases:
            key = _norm_header(alias)
            if key in norm_to_orig and key not in used:
                match = norm_to_orig[key]
                used.add(key)
                break
        resolved[field] = match
    return resolved


class BalanzParser(Parser):
    format_id = "balanz"
    display_name = "Balanz (beta)"
    # TEMP: oculto en la UI hasta estabilizar. Cuando se rehabilite, flipear a
    # True y validar con export reciente de Balanz.
    is_supported = False
    platform = "balanz"
    platform_label = "Balanz (beta)"
    export_label = ""

    def can_handle(self, headers: List[str]) -> bool:
        resolved = _resolve_columns(headers)
        return all(resolved.get(f) for f in _REQUIRED_FIELDS)

    def template_csv(self) -> str:
        return (
            "Fecha Concertación,Fecha Liquidación,Tipo,Especie,Descripción,"
            "Cantidad,Precio,Moneda,Importe Bruto,Comisiones,Importe Neto,Plazo,N° Boleto\n"
            "15/01/2025,17/01/2025,Compra,GGAL,Grupo Galicia,100,4850.00,ARS,485000.00,2425.00,487425.00,48hs,001234567\n"
            "22/01/2025,24/01/2025,Venta,AAPL,Apple CEDEAR,50,12340.50,ARS,617025.00,3085.13,613939.87,48hs,001234890\n"
            "05/02/2025,07/02/2025,Compra,AL30,Bonar 2030,1000,68.45,USD,684.50,3.42,687.92,48hs,001235012\n"
            "14/02/2025,18/02/2025,Venta,GD30,Global 2030,500,72.10,USD,360.50,1.80,358.70,48hs,001235234\n"
        )

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        if content.startswith("﻿"):
            content = content[1:]
        try:
            sample = content[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(io.StringIO(content), dialect=dialect)
            headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(0, None, "FILE_UNREADABLE",
                                                f"No pudimos leer el archivo: {ex}"))
            return result

        cols = _resolve_columns(headers)
        missing = [f for f in _REQUIRED_FIELDS if not cols.get(f)]
        if missing:
            result.parse_errors.append(RowError(
                0, None, "BALANZ_HEADERS_MISMATCH",
                f"Este archivo no coincide con la estructura esperada de Balanz. "
                f"No encontré columnas para: {', '.join(missing)}. Aceptamos varias "
                f"variantes de nombre (Fecha Concertación / Fecha de Liquidación / "
                f"Tipo / Tipo de Operación / Especie / etc.). Si tu export tiene "
                f"otros headers, usá el template genérico y mapeá manualmente."))
            return result

        def _g(row, field):
            col = cols.get(field)
            return (row.get(col) or "").strip() if col else ""

        for idx, row in enumerate(reader, start=1):
            fecha = _g(row, "fecha")
            tipo = _g(row, "tipo")
            activo = _g(row, "activo")
            if not fecha or not tipo:
                continue

            descripcion = _g(row, "_descripcion")
            boleto = _g(row, "_boleto")
            notes_parts = []
            if descripcion:
                notes_parts.append(descripcion)
            if boleto:
                notes_parts.append(f"Boleto {boleto}")

            data = {
                "fecha": fecha,
                "tipo": tipo,
                "broker": "Balanz",
                "activo": activo.upper() if activo else "",
                "cantidad": _g(row, "cantidad"),
                "precio": _g(row, "precio"),
                "monto": _g(row, "monto"),
                "comisiones": _g(row, "comisiones"),
                "moneda": _norm_currency(_g(row, "moneda")),
                "notas": " · ".join(notes_parts),
            }
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        return result
