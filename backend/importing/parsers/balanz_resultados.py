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
  • resto (desconocido)     → skip + RowError (evita COMPRA espuria)

Acciones societarias (vía Operacion Compra / Operacion Venta):
  • "Dividendo en acciones" / "Split" con Precio Compra=0 → COMPRA a costo CERO
    (lote válido de acciones recibidas gratis; sin esto se tiraba en silencio).
  • "Reducción/Devolución de capital" con PrecioVenta=0 en una Orden → VENTA a 0
    para CERRAR la posición (no deja tenencia fantasma; el capital devuelto entra
    por la fila de Dividendo asociada).

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
    "asset_name":     ["descripcion"],
    "clase":          ["tipo"],
    "tipo_mov":       ["tipo movimiento", "tipomovimiento"],
    "fecha":          ["fecha"],
    "fecha_compra":   ["fechacompra", "fecha compra"],
    "precio_compra":  ["precio compra", "preciocompra"],
    "precio_venta":   ["precioventa", "precio venta"],
    "op_compra":      ["operacion compra", "operacioncompra"],
    "op_venta":       ["operacion venta", "operacionventa"],
    "moneda_compra":  ["moneda compra", "moneda de compra"],
    "moneda_venta":   ["moneda venta", "moneda de venta"],
    "gastos":         ["gastos"],
    "cupones":        ["cupones", "cupon", "cupon"],
    "dividendos":     ["dividendos", "dividendo"],
    "intereses":      ["intereses", "interes"],
    "_dolar":         ["operacionventadolarccl", "operacionventadolarmep", "dolarccl", "dolarmep"],
    "_hoja":          ["_hoja"],
}

# Detectamos el reporte de Resultados por: TipoMovimiento + Ticker + alguna
# columna distintiva (precio de compra, cupones, o el TC del dólar por operación).
_REQUIRED = ("tipo_mov", "activo")
_DISCRIMINATORS = ("precio_compra", "cupones", "_dolar")


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
    export_label = "Actividad → Resultados"

    def can_handle(self, headers: List[str]) -> bool:
        cols = _resolve_columns(headers)
        return all(cols.get(f) for f in _REQUIRED) and any(cols.get(d) for d in _DISCRIMINATORS)

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
        if not (all(cols.get(f) for f in _REQUIRED) and any(cols.get(d) for d in _DISCRIMINATORS)):
            result.parse_errors.append(RowError(
                0, None, "BALANZ_RES_HEADERS_MISMATCH",
                "Este archivo no coincide con el reporte de Resultados de Balanz "
                "(Actividad → Resultados). Asegurate de subir el Excel completo."))
            return result

        # Variante CSV "sin precios": trae movimientos pero NO las columnas de
        # precio (Precio Compra / PrecioVenta). Sin precio no hay posición ni
        # P&L — solo cupones, que no alcanzan para una cartera. Mejor cortar con
        # un mensaje accionable que importar una cartera vacía.
        if not cols.get("precio_compra"):
            result.parse_errors.append(RowError(
                0, None, "BALANZ_RES_NO_PRICES",
                "Este export de Balanz no incluye precios, así que no podemos "
                "reconstruir posiciones ni P&L. Exportá el EXCEL de Resultados "
                "(Actividad → Resultados → Excel/.xlsx), que sí trae los precios "
                "de compra y venta — o usá el export de Operaciones → Órdenes."))
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
            # asset_type va al dict de renta para que la categorización por clase
            # de activo funcione (sin el hint, el normalizer cae a OTHER para todo
            # ticker AR). No afecta P&L ni cash — es solo para reporting.
            if mov.startswith("cupon"):
                monto = _pos(_g(row, "cupones"))
                if monto and activo:
                    d = {"fecha": fecha, "tipo": "INTERES", "broker": "Balanz",
                         "activo": activo, "monto": str(monto),
                         "moneda": _norm_ccy(_g(row, "moneda_venta"))}
                    if asset_type:
                        d["asset_type"] = asset_type
                    _emit(d)
                continue
            if mov.startswith("dividendo"):
                monto = _pos(_g(row, "dividendos"))
                if monto and activo:
                    d = {"fecha": fecha, "tipo": "DIVIDENDO", "broker": "Balanz",
                         "activo": activo, "monto": str(monto),
                         "moneda": _norm_ccy(_g(row, "moneda_venta"))}
                    if asset_type:
                        d["asset_type"] = asset_type
                    _emit(d)
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

            # Solo "No Realizado" (lote abierto) y "Orden" (round-trip cerrado)
            # crean posiciones. Un Tipo Movimiento desconocido (ej. Balanz agrega
            # "Rescate"/"Suscripcion"/"Canje" en otro período) caería acá y, si trae
            # precio+cantidad, generaría una COMPRA ESPURIA → posición fantasma.
            # Mejor avisar al usuario que tragarlo en silencio.
            if mov and not (mov.startswith("no realizado") or mov.startswith("orden")):
                result.parse_errors.append(RowError(
                    ridx + 1, activo, "BALANZ_RES_TIPO_DESCONOCIDO",
                    f"Tipo de movimiento no reconocido para {activo}: "
                    f"'{_g(row, 'tipo_mov')}'. Se omitió la fila — escribinos si "
                    f"creés que debería importarse."))
                continue

            op_compra = _norm_header(_g(row, "op_compra"))
            op_venta = _norm_header(_g(row, "op_venta"))
            asset_name = _g(row, "asset_name") or None

            cantidad = _pos(_g(row, "cantidad"))
            if cantidad is None:
                continue

            # Acción societaria que entrega acciones a costo CERO ("Dividendo en
            # acciones" / "Split"): Precio Compra=0 es un lote VÁLIDO de costo-cero,
            # no un precio faltante. Sin esto _pos(0)=None tiraba el lote en silencio
            # (BYMA y SPY quedaban con menos nominales de los reales).
            is_free_lot = op_compra.startswith("dividendo en acciones") or op_compra.startswith("split")
            pc = _pos(_g(row, "precio_compra"))
            if pc is None:
                if is_free_lot:
                    pc = 0.0
                else:
                    continue
            fecha_compra = _g(row, "fecha_compra") or fecha

            # La COMPRA va siempre (abierta o cerrada). Gastos al lote de compra.
            buy = {"fecha": fecha_compra, "tipo": "COMPRA", "broker": "Balanz",
                   "activo": activo, "cantidad": str(cantidad), "precio": str(pc),
                   "comisiones": gastos or "", "moneda": _norm_ccy(_g(row, "moneda_compra"))}
            if asset_type:
                buy["asset_type"] = asset_type
            if asset_name:
                buy["asset_name"] = asset_name
            _emit(buy)

            # Si está cerrada (Orden), emitimos también la VENTA.
            if mov.startswith("orden"):
                pv = _pos(_g(row, "precio_venta"))
                # Acción societaria que CIERRA la posición sin precio de venta:
                # "Reducción/Devolución de capital" cancela el papel. PrecioVenta=0
                # → emitimos la VENTA a 0 igual, para NO dejar la posición FANTASMA
                # abierta (DESP quedaba abierto a 22600 ARS, inflando la cartera).
                # Trade-off conciente: vender a 0 NO acredita cash (proceeds=0, no
                # infla el saldo) pero registra una pérdida realizada = costo del
                # lote. El capital devuelto entra por SEPARADO (p.ej. como Dividendo,
                # a veces en USD en el sub-broker), así que el P&L neto se aproxima
                # en agregado pero la línea de DESP queda en -100% compensada por ese
                # ingreso, no 1:1. Priorizamos cash y valuación correctos (la queja
                # real de los usuarios) sobre la prolijidad de la atribución del P&L.
                is_capital_return = ("reduccion de capital" in op_venta
                                     or "devolucion de capital" in op_venta)
                if pv is None and is_capital_return:
                    pv = 0.0
                if pv is not None:
                    sell = {"fecha": fecha, "tipo": "VENTA", "broker": "Balanz",
                            "activo": activo, "cantidad": str(cantidad), "precio": str(pv),
                            "comisiones": "", "moneda": _norm_ccy(_g(row, "moneda_venta"))}
                    if asset_type:
                        sell["asset_type"] = asset_type
                    if asset_name:
                        sell["asset_name"] = asset_name
                    # Venta a proceeds 0 por acción societaria → marcar para que el
                    # validador la acepte (si no, MISSING_PRICE la descartaría y la
                    # posición quedaría fantasma abierta).
                    if is_capital_return and pv == 0.0:
                        sell["_corporate_close"] = True
                    _emit(sell)

        return result
