"""Parser de Balanz — formato de export real de la app móvil.

Headers del CSV "Resultados del período" de Balanz (Actividad → Reportes →
Resultados del período):

    Tipo, Ticker, Descripcion, Fecha, FechaLote, Cantidad, PrecioCompra,
    Gastos, Moneda, Operacion, DolarMEP, DolarCCL, DolarOficial

Distinción clave del formato actual de Balanz:
  • `Tipo`      = tipo de INSTRUMENTO (Acción / Bono / CEDEAR / FCI / Letra…)
  • `Operacion` = tipo de OPERACIÓN  (Compra / Venta / Dividendo / Cupón / …)

Particularidades manejadas:
- Fechas DD/MM/YYYY (formato AR) — el normalizer convierte a YYYY-MM-DD.
- Decimales con coma o punto (toleramos ambos).
- Moneda: ARS / USD / Pesos / Dólares — normalizamos.
- `DolarMEP/CCL/Oficial` stampados por operación → los guardamos en `notas`
  para que el persister tenga referencia histórica del FX.
- `FechaLote`: identifica el lote consumido en ventas. Lo guardamos en
  `notas` (audit-only); el FIFO interno de Rendi sigue su propia lógica.

COMPAT con formato viejo (hipotético): si en algún momento Balanz cambió el
export y "Tipo" cumplía el rol de "Operacion" (Compra/Venta directamente),
el parser cae a ese fallback automáticamente.

LIMITACIÓN: este parser fue construido a partir de un export muestra. Si
Balanz cambia el formato (renombres, columnas nuevas), puede requerir
ajustes. Si los headers no matchean, usá el template genérico de Rendi.
"""
from __future__ import annotations
import csv
import io
from typing import Dict, List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


def _norm_header(h: str) -> str:
    """Normaliza headers para comparación: lowercase + saca tildes/eñe + reemplaza
    separadores raros (°, /, -) por espacios. Caracteres camelCase pegados como
    PrecioCompra → preciocompra (sin separador)."""
    if not h:
        return ""
    s = (h.strip().lower()
           .replace("ó", "o").replace("í", "i").replace("á", "a")
           .replace("é", "e").replace("ú", "u").replace("ñ", "n")
           .replace("°", "").replace("/", " ").replace("-", " "))
    return " ".join(s.split())


# Mapping de campos internos → posibles headers reales del CSV.
# Cubre el formato actual de la app de Balanz (camelCase pegados como
# "PrecioCompra", "FechaLote", "DolarMEP") y variantes con separadores.
_FIELD_ALIASES: Dict[str, List[str]] = {
    "fecha": [
        "fecha", "fecha operacion", "fecha de operacion",
        "fecha concertacion", "fecha de concertacion",
        "fecha liquidacion", "fecha de liquidacion",
    ],
    "fecha_lote": [
        "fechalote", "fecha lote", "fecha de lote", "fecha del lote",
    ],
    "operacion": [
        "operacion", "tipo de operacion", "tipo operacion", "movimiento",
    ],
    "tipo_instrumento": [
        "tipo", "tipo instrumento", "tipo de instrumento", "clase",
    ],
    "activo": [
        "ticker", "especie", "simbolo", "instrumento",
    ],
    "cantidad": [
        "cantidad", "valor nominal", "cantidad valor nominal",
        "nominales", "vn", "qty", "quantity",
    ],
    "precio": [
        # Header real del export actual: "PrecioCompra" → norm "preciocompra".
        # Aliases adicionales por si Balanz cambia el wording.
        "preciocompra", "precio compra", "precio",
        "precio unitario", "precio promedio", "preciopromedio",
    ],
    "moneda": [
        "moneda", "moneda operacion", "moneda de la operacion",
    ],
    "monto": [
        "importe bruto", "monto bruto", "bruto",
        "importe neto", "monto neto", "neto", "monto", "importe",
    ],
    "comisiones": [
        # Header real del export actual: "Gastos".
        "gastos", "gastos comisiones", "gastos y comisiones",
        "comisiones", "comision", "arancel",
    ],
    "dolar_mep":     ["dolarmep", "dolar mep"],
    "dolar_ccl":     ["dolarccl", "dolar ccl"],
    "dolar_oficial": ["dolaroficial", "dolar oficial"],
    "_descripcion":  ["descripcion", "detalle"],
    "_boleto": [
        "n boleto", "nro boleto", "numero boleto", "boleto",
        "n operacion", "nro operacion", "comprobante",
    ],
}

# Para detectar Balanz exigimos al menos: fecha + ticker + una indicación de op
# (Operacion en formato nuevo, o Tipo en formato viejo hipotético).
_REQUIRED_NEW = ("fecha", "operacion", "activo")
_REQUIRED_OLD = ("fecha", "tipo_instrumento", "activo")


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
    """Para cada campo de Rendi, encuentra el header real del archivo (o None)."""
    norm_to_orig: Dict[str, str] = {}
    for h in headers:
        norm_to_orig.setdefault(_norm_header(h), h)
    resolved: Dict[str, Optional[str]] = {}
    used: set = set()
    for field_name, aliases in _FIELD_ALIASES.items():
        match = None
        for alias in aliases:
            key = _norm_header(alias)
            if key in norm_to_orig and key not in used:
                match = norm_to_orig[key]
                used.add(key)
                break
        resolved[field_name] = match
    return resolved


class BalanzParser(Parser):
    format_id = "balanz"
    display_name = "Balanz"
    is_supported = True
    platform = "balanz"
    platform_label = "Balanz"
    export_label = "Actividad → Reportes → Resultados del período"

    def can_handle(self, headers: List[str]) -> bool:
        resolved = _resolve_columns(headers)
        # Acepta formato actual (con Operacion separada) O formato viejo
        # (con Tipo cumpliendo el rol de op-type).
        new_ok = all(resolved.get(f) for f in _REQUIRED_NEW)
        old_ok = all(resolved.get(f) for f in _REQUIRED_OLD)
        if not (new_ok or old_ok):
            return False

        # Discriminator: al menos UNA columna única de Balanz para no
        # matchear archivos de otros brokers AR (Cocos, IOL) que también
        # tienen Fecha + Operación + Especie/Ticker.
        # DolarMEP/CCL/Oficial y FechaLote son específicas del export de Balanz.
        has_balanz_unique = bool(
            resolved.get("dolar_mep") or
            resolved.get("dolar_ccl") or
            resolved.get("dolar_oficial") or
            resolved.get("fecha_lote")
        )
        return has_balanz_unique

    def template_csv(self) -> str:
        # Template con los headers EXACTOS del export real de Balanz
        # (Actividad → Reportes → Resultados del período, snapshot 2026-05).
        return (
            "Tipo,Ticker,Descripcion,Fecha,FechaLote,Cantidad,PrecioCompra,"
            "Gastos,Moneda,Operacion,DolarMEP,DolarCCL,DolarOficial\n"
            "Acción,GGAL,Grupo Galicia,15/01/2026,,100,4850.00,2425.00,ARS,Compra,1180,1195,1050\n"
            "Acción,GGAL,Grupo Galicia,22/01/2026,15/01/2026,100,5200.00,2600.00,ARS,Venta,1210,1230,1075\n"
            "Bono,AL30,Bonar 2030,05/02/2026,,1000,68.45,3.42,USD,Compra,,,\n"
            "CEDEAR,AAPL,Apple Inc CEDEAR,10/02/2026,,50,12340.50,3085.13,ARS,Compra,1245,1265,1085\n"
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
        new_ok = all(cols.get(f) for f in _REQUIRED_NEW)
        old_ok = all(cols.get(f) for f in _REQUIRED_OLD)
        if not (new_ok or old_ok):
            missing_new = [f for f in _REQUIRED_NEW if not cols.get(f)]
            result.parse_errors.append(RowError(
                0, None, "BALANZ_HEADERS_MISMATCH",
                f"Este archivo no coincide con la estructura esperada de Balanz. "
                f"Faltan columnas para: {', '.join(missing_new)}. Aceptamos los "
                f"exports de la app de Balanz (Actividad → Reportes → Resultados "
                f"del período). Si tu export tiene headers distintos, usá el "
                f"template genérico de Rendi y mapeá manualmente."))
            return result

        def _g(row, field_name):
            col = cols.get(field_name)
            return (row.get(col) or "").strip() if col else ""

        for idx, row in enumerate(reader, start=1):
            fecha = _g(row, "fecha")
            # Formato nuevo: Operacion = Compra/Venta/Dividendo/etc.
            # Formato viejo (fallback): Tipo cumplía ese rol.
            operacion = _g(row, "operacion") or _g(row, "tipo_instrumento")
            activo = _g(row, "activo")
            if not fecha or not operacion:
                continue

            # Notas: metadata útil para audit + reconciliación con la app de Balanz.
            descripcion = _g(row, "_descripcion")
            boleto = _g(row, "_boleto")
            fecha_lote = _g(row, "fecha_lote")
            dolar_mep = _g(row, "dolar_mep")
            dolar_ccl = _g(row, "dolar_ccl")
            tipo_instr = _g(row, "tipo_instrumento")

            notes_parts = []
            if descripcion:
                notes_parts.append(descripcion)
            # Solo incluir tipo_instrumento si NO duplica con operacion (en
            # formato viejo apuntan al mismo header → noise).
            if tipo_instr and tipo_instr.lower() != operacion.lower():
                notes_parts.append(f"Tipo: {tipo_instr}")
            if fecha_lote:
                notes_parts.append(f"Lote {fecha_lote}")
            if boleto:
                notes_parts.append(f"Boleto {boleto}")
            if dolar_mep:
                notes_parts.append(f"MEP {dolar_mep}")
            if dolar_ccl:
                notes_parts.append(f"CCL {dolar_ccl}")

            data = {
                "fecha": fecha,
                "tipo": operacion,
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
