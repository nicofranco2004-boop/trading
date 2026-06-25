"""Parser de Balanz — export de "Resultados" (Actividad → Resultados).

Es un xlsx multi-hoja (lotes_iniciales / por_realizado / lotes_finales). El
pipeline lo aplana a un CSV unión con una columna `_hoja` por fila (ver
excel.xlsx_to_csv). Procesamos SOLO la hoja `por_realizado`, que es el reporte
COMPLETO: trae posiciones abiertas, operaciones cerradas (con precio de compra
Y venta) y la renta (cupones / dividendos / intereses). Las otras dos hojas son
redundantes con esa (lotes_finales = lo "No Realizado", lotes_iniciales =
baseline), así evitamos doble conteo usando una sola.

Dispatch por `Tipo Movimiento`:
  • No Realizado            → COMPRA (lote abierto: Precio Compra, FechaCompra)
  • Orden                   → COMPRA + VENTA (round-trip cerrado → P&L realizado)
  • Cupón                   → INTERÉS (monto = Cupones)
  • Dividendo               → DIVIDENDO (monto = Dividendos)
  • Caución - Pase - Cheque → INTERÉS (monto = Intereses)
  • resto                   → skip

`asset_type` sale de la columna `Tipo` (Bonos/Corporativos/Letras→BOND,
Cedears→CEDEAR, Acciones→STOCK, Fondos→FUND) — más preciso que adivinar por
ticker, y alimenta el guard anti-distorsión de la valuación. Comisiones = Gastos.

Ventaja sobre el export de Órdenes: captura renta (cupones/dividendos) y
comisiones, y no necesita reconstruir vía FIFO (Balanz ya matcheó las cerradas).
"""
from __future__ import annotations
import csv
import io
from typing import Dict, List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


def _norm_header(h: str) -> str:
    if not h:
        return ""
    s = (h.strip().lower()
           .replace("ó", "o").replace("í", "i").replace("á", "a")
           .replace("é", "e").replace("ú", "u").replace("ñ", "n"))
    return " ".join(s.split())


_FIELD_ALIASES: Dict[str, List[str]] = {
    "cantidad":       ["cantidad"],
    "activo":         ["ticker", "especie"],
    "clase":          ["tipo"],
    "tipo_mov":       ["tipo movimiento", "tipomovimiento"],
    "fecha":          ["fecha"],
    "fecha_compra":   ["fechacompra", "fecha compra"],
    "precio_compra":  ["precio compra", "preciocompra"],
    "precio_venta":   ["precioventa", "precio venta"],
    "moneda_compra":  ["moneda compra", "moneda de compra"],
    "moneda_venta":   ["moneda venta", "moneda de venta"],
    "gastos":         ["gastos"],
    "cupones":        ["cupones", "cupon", "cupon"],
    "dividendos":     ["dividendos", "dividendo"],
    "intereses":      ["intereses", "interes"],
    "_hoja":          ["_hoja"],
}

_REQUIRED = ("tipo_mov", "activo", "precio_compra")


def _norm_ccy(s: str) -> str:
    if not s:
        return ""
    v = " ".join(s.strip().lower().replace("ó", "o").split())
    if v.startswith("peso") or v in ("ars", "$"):
        return "ARS"
    if v.startswith("dolar") or "dollar" in v or v in ("usd", "u$s", "us$"):
        return "USD"
    return s.strip().upper()


def _asset_type_from_clase(clase: str) -> Optional[str]:
    """`Tipo` de Balanz → asset_type de Rendi."""
    c = (clase or "").strip().lower().replace("ó", "o")
    if not c:
        return None
    if "cedear" in c:
        return "CEDEAR"
    if "fondo" in c:
        return "FUND"
    if "accion" in c:
        return "STOCK"
    if "bono" in c or "letra" in c or "corporativ" in c or "obligacion" in c:
        return "BOND"
    return None  # Efectivo / desconocido → sin hint


def _num(s) -> Optional[float]:
    if s is None:
        return None
    txt = str(s).strip()
    if not txt or txt.lower() == "none":
        return None
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def _pos(x) -> Optional[float]:
    n = _num(x)
    return n if (n is not None and n > 0) else None


def _resolve_columns(headers: List[str]) -> Dict[str, Optional[str]]:
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


class BalanzResultadosParser(Parser):
    format_id = "balanz_resultados"
    display_name = "Balanz — Resultados"
    is_supported = True
    platform = "balanz"
    platform_label = "Balanz"
    export_label = "Actividad → Resultados (recomendado)"

    def can_handle(self, headers: List[str]) -> bool:
        cols = _resolve_columns(headers)
        return all(cols.get(f) for f in _REQUIRED)

    def template_csv(self) -> str:
        # Balanz exporta esto como xlsx multi-hoja; el template muestra las
        # columnas de la hoja `por_realizado` (la que importamos).
        return (
            "Cantidad,Descripcion,Fecha,FechaCompra,Gastos,Moneda Compra,Moneda Venta,"
            "Operacion Compra,Operacion Venta,Precio Compra,PrecioVenta,Ticker,Tipo,"
            "Tipo Movimiento,Cupones,Dividendos,Intereses\n"
            "1000,BONO GD30,2026-06-25,2025-05-29,4785,Pesos,,Boleto,,66.0,,GD30,Bonos - Dólar,No Realizado,,,\n"
            "2671,BONO AL35,2025-09-18,2025-09-18,14562,Dólares,US Dollar (Cable),Boleto,Boleto,0.46,0.45,AL35,Bonos - Dólar,Orden,,,\n"
            "0,BOPREAL BPC7,2025-10-31,,1037,,Dólares,,Renta,,,BPC7,Bonos - Dólar,Cupón,146726,,\n"
            "0,CEDEAR AMZN,2026-06-17,,0,,Dólares,,Dividendo,,,AMZN,Cedears,Dividendo,,0.13,\n"
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
        if not all(cols.get(f) for f in _REQUIRED):
            result.parse_errors.append(RowError(
                0, None, "BALANZ_RES_HEADERS_MISMATCH",
                "Este archivo no coincide con el reporte de Resultados de Balanz "
                "(Actividad → Resultados). Asegurate de subir el Excel completo."))
            return result

        def _g(row, field_name):
            col = cols.get(field_name)
            return (row.get(col) or "").strip() if col else ""

        has_hoja = bool(cols.get("_hoja"))
        ridx = 0  # contador propio: "Orden" emite 2 filas (compra + venta)

        for row in reader:
            # Multi-hoja: solo procesamos la hoja por_realizado (las otras son
            # redundantes). En CSV de una sola hoja no hay '_hoja' → procesamos todo.
            if has_hoja:
                hoja = _norm_header(_g(row, "_hoja"))
                if "realizado" not in hoja or "lote" in hoja:
                    continue

            mov = _norm_header(_g(row, "tipo_mov"))
            activo = _g(row, "activo").upper()
            clase = _g(row, "clase")
            asset_type = _asset_type_from_clase(clase)
            fecha = _g(row, "fecha")
            gastos = _g(row, "gastos")

            def _emit(d):
                nonlocal ridx
                ridx += 1
                result.raw_rows.append(RawRow(row_index=ridx, data=d))

            # ── Renta (no necesita precio/cantidad) ──────────────────────────
            if mov.startswith("cupon"):
                monto = _pos(_g(row, "cupones"))
                if monto and activo:
                    _emit({"fecha": fecha, "tipo": "INTERES", "broker": "Balanz",
                           "activo": activo, "monto": str(monto),
                           "moneda": _norm_ccy(_g(row, "moneda_venta"))})
                continue
            if mov.startswith("dividendo"):
                monto = _pos(_g(row, "dividendos"))
                if monto and activo:
                    _emit({"fecha": fecha, "tipo": "DIVIDENDO", "broker": "Balanz",
                           "activo": activo, "monto": str(monto),
                           "moneda": _norm_ccy(_g(row, "moneda_venta"))})
                continue
            if mov.startswith("caucion"):
                monto = _pos(_g(row, "intereses"))
                if monto:
                    _emit({"fecha": fecha, "tipo": "INTERES", "broker": "Balanz",
                           "activo": activo or "PESOS", "monto": str(monto),
                           "moneda": _norm_ccy(_g(row, "moneda_venta"))})
                continue

            # ── Posiciones / trades (necesitan ticker + precio + cantidad) ────
            if not activo:
                continue
            cantidad = _pos(_g(row, "cantidad"))
            pc = _pos(_g(row, "precio_compra"))
            if cantidad is None or pc is None:
                continue
            fecha_compra = _g(row, "fecha_compra") or fecha

            # La COMPRA va siempre (abierta o cerrada). Gastos al lote de compra.
            buy = {"fecha": fecha_compra, "tipo": "COMPRA", "broker": "Balanz",
                   "activo": activo, "cantidad": str(cantidad), "precio": str(pc),
                   "comisiones": gastos or "", "moneda": _norm_ccy(_g(row, "moneda_compra"))}
            if asset_type:
                buy["asset_type"] = asset_type
            _emit(buy)

            # Si está cerrada (Orden), emitimos también la VENTA.
            if mov.startswith("orden"):
                pv = _pos(_g(row, "precio_venta"))
                if pv is not None:
                    sell = {"fecha": fecha, "tipo": "VENTA", "broker": "Balanz",
                            "activo": activo, "cantidad": str(cantidad), "precio": str(pv),
                            "comisiones": "", "moneda": _norm_ccy(_g(row, "moneda_venta"))}
                    if asset_type:
                        sell["asset_type"] = asset_type
                    _emit(sell)

        return result
