"""Parser de IEB (Invertir en Bolsa S.A.) — export de movimientos (.xlsx → CSV).

Cómo bajar el archivo (SÍ O SÍ desde la WEB, no la app):
    1. Homebanking web de IEB: https://hb.iebmas.com.ar → iniciar sesión.
    2. Actividad → Toda la actividad (Movimientos totales):
       https://hb.iebmas.com.ar/actividad/movimientos-totales
    3. Elegir el rango Desde/Hasta (Desde lo más antiguo posible para historia completa).
    4. Descargar el .xlsx y subirlo tal cual.

Estructura del export (una sola hoja 'Export', el pipeline lo pasa a CSV
point-decimal; los vacíos vienen como '-'):

    Referencia | Operación | Fecha emisión | Fecha liquidación | Nro. de operación
    | Cantidad | Precio | Importe ARS | Importe divisas | Divisa

  - `Referencia`  : ticker (EWZ, AL30, YPFD, BMA…) o bucket especial
                    ('MM Pesos', 'CAUCION', 'DOLAR', 'Ciclo Nova').
  - `Operación`   : código de tipo (ver _OP_MAP / _resolve_op).
  - `Cantidad`    : con signo (+ compra / − venta). Tomamos abs().
  - `Importe ARS` / `Importe divisas` : mutuamente excluyentes; cuál aplica lo
                    dice `Divisa`. Negativo = sale plata (compra/fee), positivo = entra.
  - `Divisa`      : 'ARS' | 'USD' | 'OTHER'. El sufijo del código ('$'/'U$') también
                    define la moneda de los trades.
  - `Nro. de operación` : ID único → lo guardamos en notas (dedup/auditoría).

ALCANCE MVP (igual criterio que Balanz/Cocos — solo lo que se puede mapear seguro):
  ✅ Trades: CPRA/VTAS (pesos) + CPU$/VTU$ (dólares) → COMPRA/VENTA con su moneda.
  ✅ Renta/dividendos: DIV, RTA, RENTA, AMORTIZA, NCCD → DIVIDENDO (monto>0) / FEE (monto<0).
  ✅ Fees: ND, NDMP, DECR, PAGW → FEE.
  ✅ Cash/FX: DOLAR COUW/PAUW → DEPOSITO/RETIRO (USD); COBW/NCMP → DEPOSITO.
  ✅ Caución (repo): CCCD → RETIRO (colocás), CCTE → DEPOSITO (vuelve con interés).
  ⚠️ FCI (MM Pesos / Ciclo Nova, LS*/LR*): por ahora como flujo de caja por signo
     (no como posición de cuotaparte). FUERA de MVP modelarlo como tenencia.
  ⚠️ DIV/RTA con doble pata (bruto ARS negativo + neto 'OTHER' positivo): la
     semántica exacta (bruto/retención/neto) necesita el export real + docs →
     ABIERTO, ver audit. Hoy: monto>0 → DIVIDENDO, monto<0 → FEE.
  ❌ No trae snapshot de tenencia actual → las posiciones se reconstruyen por FIFO
     (rebuild). Si el export es una VENTANA (no toda la cuenta), faltan las posiciones
     previas al primer movimiento → se necesita el "estado inicial/seed".
"""
from __future__ import annotations
import csv
import io
from typing import List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError

BROKER_NAME = "IEB"

# Headers distintivos del export de IEB (normalizados). Pedimos varios para no
# colisionar con otros formatos.
_REQUIRED_HEADERS = {
    "referencia", "operacion", "nrodeoperacion", "importears",
    "importedivisas", "divisa",
}

# Código de `Operación` → tipo canónico Rendi. El match es por código exacto
# (mayúsculas, sin espacios) y, si no, por patrón (_resolve_op).
_OP_MAP = {
    "CPRA": "COMPRA",     # compra en pesos
    "VTAS": "VENTA",      # venta en pesos
    "CPU$": "COMPRA",     # compra en dólares
    "VTU$": "VENTA",      # venta en dólares
    "RENTA": "DIVIDENDO",   # renta (cupón) de bono en USD
    "AMORTIZA": "DIVIDENDO",  # amortización de bono = ingreso de caja
    "NCCD": "DIVIDENDO",  # nota de crédito en cuenta (renta/amort de bono/ON)
    "NCMP": "DEPOSITO",   # nota de crédito mercado de pagos = cash in
    "ND": "FEE",          # nota de débito
    "NDMP": "FEE",        # nota de débito mercado de pagos
    "DECR": "FEE",        # derechos/decreto (cargo)
    "COBW": "DEPOSITO",   # acreditación / cobro a la caja
}

# Códigos que llevan la moneda forzada a USD (sufijo '$' / 'U$').
_USD_OPS = {"CPU$", "VTU$"}

# Códigos de caución (repo): CCCD = constitución (sale plata), CCTE = vencimiento
# (vuelve con interés). Mismo criterio que Cocos.
_CAUCION_OUT = {"CCCD"}   # → RETIRO
_CAUCION_IN = {"CCTE"}    # → DEPOSITO


def _norm_header(h: str) -> str:
    """Lowercase + sin tildes + sin espacios/puntos para comparar headers."""
    if not h:
        return ""
    s = (h.strip().lower()
            .replace("ó", "o").replace("í", "i").replace("á", "a")
            .replace("é", "e").replace("ú", "u").replace("ñ", "n"))
    return s.replace(" ", "").replace(".", "")


def _strip(s) -> str:
    return (s or "").strip()


def _num(s) -> Optional[float]:
    """Parsea un número point-decimal de IEB. '-' / '' / None → None (vacío).
    El export usa '-' como placeholder de celda vacía y punto decimal estándar."""
    s = _strip(s)
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _resolve_op(code: str, amount: Optional[float]) -> Optional[str]:
    """Código de `Operación` (upper, sin espacios) + signo del monto → tipo canónico.

    `amount` es el importe relevante (ARS o divisas) con signo. Se usa para
    discriminar ingresos (DIVIDENDO/DEPOSITO) de cargos (FEE) en los códigos que
    pueden ser ambos (DIV/RTA: bruto vs retención; DOLAR; PAGW).
    """
    if code in _OP_MAP:
        return _OP_MAP[code]

    # Renta/dividendo en pesos: positivo = ingreso, negativo = retención/impuesto.
    if code in ("DIV", "RTA"):
        return "DIVIDENDO" if (amount or 0) >= 0 else "FEE"

    # Caución (repo).
    if code in _CAUCION_OUT:
        return "RETIRO"
    if code in _CAUCION_IN:
        return "DEPOSITO"

    # Pago / cargo (PAGW) → siempre FEE.
    if code == "PAGW":
        return "FEE"
    # Operaciones de dólar (conversión FX, sin tenencia): por signo del importe.
    # COUW (dólares acreditados) = DEPOSITO; PAUW (dólares pagados) = RETIRO;
    # CU$V = otra operación de dólar (ref 'DOLAR') → mismo criterio por signo.
    if code in ("COUW", "PAUW", "CU$V"):
        return "DEPOSITO" if (amount or 0) >= 0 else "RETIRO"

    # FCI (MM Pesos / Ciclo Nova): suscripción (LS*) / rescate (LR*). MVP: flujo de
    # caja por signo (no como posición de cuotaparte).
    if code.startswith("LS") or code.startswith("LR"):
        return "RETIRO" if (amount or 0) < 0 else "DEPOSITO"

    # ── Fallbacks por familia (cubren variantes que no estaban en el demo, para
    #    que el export real no rechace filas por un código nuevo) ───────────────
    # Notas de débito (impuestos / sellados / derechos): ND, NDMP, NDIT, ND… → FEE.
    if code.startswith("ND"):
        return "FEE"
    # Cobros / acreditaciones a la caja: COBW, COBR, COB… → cash in.
    # NOTA: cuando el cobro es sobre un TICKER (ej. dividendo/renta de TGNO4/GGAL)
    # esto debería ser DIVIDENDO, no DEPOSITO — refinamiento pendiente de confirmar
    # con el export real (ver audit). Hoy: DEPOSITO (mantiene el cash correcto).
    if code.startswith("COB"):
        return "DEPOSITO"

    return None


# Buckets de `Referencia` que NO son un activo operable (cash/FX/repo/FCI) → el
# flujo se registra sin asset.
_NON_ASSET_REFS = {"mm pesos", "caucion", "dolar", "ciclo nova"}


class IebParser(Parser):
    format_id = "ieb"
    display_name = "IEB (Invertir en Bolsa)"
    is_supported = True
    platform = "ieb"
    platform_label = "IEB · Invertir en Bolsa"
    export_label = "Movimientos"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_norm_header(h) for h in headers}
        return len(_REQUIRED_HEADERS & norm) >= 4

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        if content.startswith("﻿"):
            content = content[1:]
        try:
            # El pipeline ya pasó el .xlsx a CSV coma-separated.
            reader = csv.DictReader(io.StringIO(content))
            raw_headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(
                0, None, "FILE_UNREADABLE", f"No pudimos leer el archivo: {ex}"))
            return result

        norm_to_orig = {_norm_header(h): h for h in raw_headers}
        if len(_REQUIRED_HEADERS & set(norm_to_orig.keys())) < 4:
            result.parse_errors.append(RowError(
                0, None, "IEB_HEADERS_MISMATCH",
                "Este archivo no parece un export de IEB (Invertir en Bolsa)."))
            return result

        def G(row, norm_key: str) -> str:
            col = norm_to_orig.get(norm_key)
            return _strip(row.get(col, "")) if col else ""

        for idx, row in enumerate(list(reader), start=1):
            ref = G(row, "referencia")
            code = G(row, "operacion").upper().replace(" ", "")
            if not code:
                continue  # fila sin operación

            divisa = G(row, "divisa").upper()
            imp_ars = _num(G(row, "importears"))
            imp_div = _num(G(row, "importedivisas"))
            # Monto relevante (con signo) y moneda nativa de la fila.
            if imp_div is not None:
                amount, moneda = imp_div, "USD"
            else:
                amount, moneda = imp_ars, "ARS"
            # El sufijo del código manda sobre la columna para los trades USD.
            if code in _USD_OPS:
                moneda = "USD"

            tipo = _resolve_op(code, amount)
            if tipo is None:
                result.parse_errors.append(RowError(
                    idx, "Operación", "IEB_OP_UNKNOWN",
                    f"Tipo de operación no soportado: '{G(row, 'operacion')}' (ref '{ref}')."))
                continue

            qty = _num(G(row, "cantidad"))
            price = _num(G(row, "precio"))

            # Activo: para trades es la Referencia (ticker). Para cash/FX/caución/
            # FCI/fees no hay activo asociado.
            ref_low = ref.strip().lower()
            is_asset_trade = tipo in ("COMPRA", "VENTA") and ref_low not in _NON_ASSET_REFS
            ticker = ref.strip().upper() if is_asset_trade else None

            # Notas: nro de operación (ID único) + flags de auditoría.
            nro = G(row, "nrodeoperacion")
            notas_parts = []
            if nro:
                notas_parts.append(f"Op. {nro}")
            notas_parts.append(f"IEB:{code}")
            if divisa == "OTHER":
                notas_parts.append("divisa=OTHER")  # pata neta de DIV/RTA — revisar
            notas = " · ".join(notas_parts)

            data = {
                "fecha":      (G(row, "fechaemision") or G(row, "fechaliquidacion"))[:10],
                "tipo":       tipo,
                "broker":     BROKER_NAME,
                "activo":     ticker or "",
                "cantidad":   "" if qty is None else str(abs(qty)),
                "precio":     "" if price is None else str(abs(price)),
                "monto":      "" if amount is None else str(abs(amount)),
                "monto_usd":  "",
                "tc":         "",
                "comisiones": "0",
                "moneda":     moneda,
                "asset_type": "",   # IEB no distingue CEDEAR/acción/bono en el export
                "asset_name": ref,
                "notas":      notas,
            }
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        return result
