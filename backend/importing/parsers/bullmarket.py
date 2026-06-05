"""Parser de Bull Market Brokers — export "Cuenta Corriente".

Bull Market solo exporta este reporte en Excel (.xlsx); el pipeline lo convierte
a CSV (ver importing/excel.py) antes de llegar acá. También acepta CSV nativo.

Cómo bajarlo (referencia para el wizard):
    MI CUENTA → CUENTA CORRIENTE → pestaña Pesos → Buscar → Exportar (Excel)

Estructura (una hoja por moneda; esta versión asume PESOS = ARS):

    Liquida | Operado | Comprobante | Numero | Cantidad | Especie | Precio |
    Importe | Saldo | Referencia

Mapeo de `Comprobante` al modelo Rendi:

    Bull Market                  → Rendi      Notas
    ─────────────────────────────────────────────────────────────────────
    COMPRA NORMAL                → COMPRA     Acción / CEDEAR
    VENTA                        → VENTA
    RECIBO DE COBRO              → DEPOSITO   Ingreso de plata (CREDITO CTA CTE)
    ORDEN DE PAGO                → RETIRO     Egreso (TRANSFERENCIA VIA MEP)

Cauciones (COMPRA CAUCION CONTADO / VENTA CAUCION TERMINO, especie "VARIAS"):
    NO se cargan como activo (manejo de caja, no inversión). Pero su NETO (lo
    que volvió por encima de lo colocado) es interés real ganado → lo sumamos
    como UNA fila de INTERÉS (cuenta como ganancia realizada, no como depósito).
    Así no se pierde esa ganancia ni se crea el activo fantasma "VARIAS".

FCI (SUSCRIPCION FCI / LIQUIDACION RESCATE FCI, especie "PPII"):
    Se DESCARTAN. El export trae la suscripción sin unidades → no se puede
    reconstruir ni la ganancia ni la tenencia. Si el usuario tiene un FCI
    abierto hoy, lo carga manualmente desde Posiciones (aviso en el wizard).

Particularidades:
- Fecha = `Operado` (fecha de la operación, no la de liquidación). Ya viene ISO
  desde la conversión del xlsx.
- `Cantidad` e `Importe` vienen con signo (negativo en ventas / egresos);
  tomamos abs() y el `Comprobante` define la dirección.
- `Importe` = cantidad × precio (sin comisiones desglosadas) → comisiones = 0.
- Tickers: Bull Market usa el símbolo BYMA salvo algún caso (YPF → YPFD). Los
  CEDEARs (AAPL, AMZN) se guardan como vienen; la valuación les agrega .BA.
- Moneda: ARS (hoja Pesos). El export de Dólares es un follow-up.
"""
from __future__ import annotations
import csv
import io
import re
from typing import List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


# Headers mínimos para reconocer un export de Cuenta Corriente de Bull Market.
_REQUIRED_HEADERS = {"liquida", "operado", "comprobante", "especie", "importe"}

# Comprobante (lowercase) → tipo Rendi.
_OP_MAP = {
    "compra normal":   "COMPRA",
    "venta":           "VENTA",
    "recibo de cobro": "DEPOSITO",
    "orden de pago":   "RETIRO",
}

# FCI: descartados (solo aviso al user para cargar el abierto manual). Las
# cauciones NO van acá — se detectan por substring "caucion" y se netean a
# interés (ver parse()).
_SKIP_FCI = ("suscripcion fci", "liquidacion rescate fci", "rescate fci", "suscripcion fondo")

# Normalización de tickers Bull Market → símbolo BYMA/Rendi. Pass-through si no
# está en el mapa. Crecé este dict si aparecen precios que no resuelven.
_TICKER_MAP = {
    "YPF": "YPFD",   # en BYMA la acción local de YPF cotiza como YPFD
}


def _strip(s) -> str:
    return (s or "").strip()


def _norm_header(h: str) -> str:
    if not h:
        return ""
    s = (h.strip().lower()
            .replace("ó", "o").replace("í", "i").replace("á", "a")
            .replace("é", "e").replace("ú", "u").replace("ñ", "n"))
    return s.replace(" ", "")


def _num(s: str) -> Optional[float]:
    """Parsea un número que puede venir point-decimal (xlsx → '3744.87') o en
    formato AR ('3.744,87'). Devuelve None si no parsea."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        if "," in s:
            # Formato AR: '.' miles, ',' decimal.
            s = s.replace(".", "").replace(",", ".")
        return float(s)
    except (ValueError, TypeError):
        return None


def _detect_delimiter(first_line: str) -> str:
    """xlsx→csv usa ','. CSV nativo podría usar ';'. Elegimos el más frecuente."""
    counts = {d: first_line.count(d) for d in (",", ";", "\t")}
    return max(counts, key=counts.get) if max(counts.values()) > 0 else ","


def _norm_ticker(especie: str) -> Optional[str]:
    t = (especie or "").strip().upper()
    if not t or t == "VARIAS":
        return None
    return _TICKER_MAP.get(t, t)


class BullMarketParser(Parser):
    format_id = "bullmarket"
    display_name = "Bull Market"
    is_supported = True
    platform = "bullmarket"
    platform_label = "Bull Market"
    export_label = "Cuenta Corriente (Excel)"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_norm_header(h) for h in headers}
        return len(_REQUIRED_HEADERS & norm) >= 4

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        if content.startswith("﻿"):
            content = content[1:]
        first_line = content.split("\n", 1)[0] if content else ""
        delim = _detect_delimiter(first_line)
        try:
            reader = csv.DictReader(io.StringIO(content), delimiter=delim)
            raw_headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(
                0, None, "FILE_UNREADABLE", f"No pudimos leer el archivo: {ex}",
            ))
            return result

        norm_to_orig = {_norm_header(h): h for h in raw_headers}
        if len(_REQUIRED_HEADERS & set(norm_to_orig.keys())) < 4:
            result.parse_errors.append(RowError(
                0, None, "BULLMARKET_HEADERS_MISMATCH",
                "Este archivo no parece un export de Cuenta Corriente de Bull Market. "
                "Bajalo desde Mi Cuenta → Cuenta Corriente → pestaña Pesos → Exportar.",
            ))
            return result

        def G(row, norm_key: str) -> str:
            col = norm_to_orig.get(norm_key)
            return _strip(row.get(col, "")) if col else ""

        # Cauciones: acumulamos su neto (= interés) para cargarlo como UNA fila
        # de INTERÉS al final. last_idx para indexar esa fila sintética.
        caucion_net = 0.0
        caucion_last_date = ""
        last_idx = 0

        for idx, row in enumerate(reader, start=1):
            last_idx = idx
            comprobante = G(row, "comprobante")
            comp_lc = comprobante.lower()
            if not comp_lc:
                continue  # fila vacía

            # Cauciones (especie VARIAS): manejo de caja, no inversión en un
            # activo. Acumulamos su neto = interés ganado y lo cargamos al final
            # como una sola fila de INTERÉS (ganancia, NO depósito → no infla el
            # capital aportado). Evita crear el activo fantasma "VARIAS".
            if "caucion" in comp_lc:
                v = _num(G(row, "importe"))
                if v is not None:
                    caucion_net += v
                    d = G(row, "operado") or G(row, "liquida")
                    if d > caucion_last_date:
                        caucion_last_date = d
                continue
            # FCI: descartados. El export no trae las unidades de la suscripción
            # → no se puede reconstruir ni la ganancia ni la posición. El usuario
            # carga el FCI que tenga abierto hoy manualmente desde Posiciones
            # (aviso en las instrucciones del wizard).
            if comp_lc in _SKIP_FCI:
                continue

            tipo_rendi = _OP_MAP.get(comp_lc)
            if tipo_rendi is None:
                # Tipo no soportado → lo reportamos pero seguimos.
                result.parse_errors.append(RowError(
                    idx, "Comprobante", "BULLMARKET_OP_UNKNOWN",
                    f"Tipo de comprobante no soportado: '{comprobante}'.",
                ))
                continue

            fecha = G(row, "operado") or G(row, "liquida")
            numero = G(row, "numero")

            if tipo_rendi in ("COMPRA", "VENTA"):
                ticker = _norm_ticker(G(row, "especie"))
                if not ticker:
                    # Trade sin ticker válido (ej. "VARIAS" que se nos escapó) → skip.
                    continue
                qty_v = _num(G(row, "cantidad"))
                imp_v = _num(G(row, "importe"))
                price_v = _num(G(row, "precio"))
                qty = f"{abs(qty_v)}" if qty_v is not None else ""
                monto = f"{abs(imp_v)}" if imp_v is not None else ""
                precio = f"{abs(price_v)}" if price_v is not None else ""
                activo = ticker
                fees = "0"
            else:
                # DEPOSITO / RETIRO: solo plata.
                imp_v = _num(G(row, "importe"))
                monto = f"{abs(imp_v)}" if imp_v is not None else ""
                qty = ""
                precio = ""
                activo = ""
                fees = "0"

            notas = f"Op. {numero}" if numero else ""

            data = {
                "fecha":      fecha or "",
                "tipo":       tipo_rendi,
                "broker":     "Bull Market",
                "activo":     activo,
                "cantidad":   qty,
                "precio":     precio,
                "monto":      monto,
                "monto_usd":  "",
                "tc":         "",
                "comisiones": fees,
                "moneda":     "ARS",
                "notas":      notas,
            }
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        # Interés de cauciones: el neto positivo (lo que volvió por encima de lo
        # colocado) es interés ganado → una fila de INTERÉS. Solo si es > 0
        # (un neto ≤ 0 implicaría una caución abierta al cierre → lo omitimos
        # para no inventar una pérdida fantasma).
        if caucion_net > 0:
            result.raw_rows.append(RawRow(row_index=last_idx + 1, data={
                "fecha":      caucion_last_date or "",
                "tipo":       "INTERES",
                "broker":     "Bull Market",
                "activo":     "",
                "cantidad":   "",
                "precio":     "",
                "monto":      f"{caucion_net:.2f}",
                "monto_usd":  "",
                "tc":         "",
                "comisiones": "0",
                "moneda":     "ARS",
                "notas":      "Interés de cauciones",
            }))

        return result
