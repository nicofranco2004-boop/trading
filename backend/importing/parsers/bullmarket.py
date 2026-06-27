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

# Comprobante (lowercase) → categoría Rendi, por PREFIJO (Bull Market tiene muchas
# variantes: COMPRA NORMAL/PARIDAD/EXTERIOR, RENTA Y AMORTIZ, DIVIDENDOS DOLARES
# CABLE, etc.). `Importe` es el efecto en caja → el tipo se elige para que el signo
# matchee y reconcilie por construcción. Las cauciones, conversiones cable↔MEP y
# FCI NO pasan por acá (se manejan antes en parse()).
def _classify_comprobante(comp_lc: str) -> Optional[str]:
    # FCI (fondos): el RESCATE trae cantidad+precio+especie → VENTA del fondo (su
    # cash entra y la tenencia baja). La SUSCRIPCION NO trae cantidad → solo el
    # cash que sale → RETIRO (la tenencia del FCI no se puede reconstruir desde la
    # cuenta corriente; sigue siendo follow-up). Sin esto, el neto FCI no se
    # contaba y la caja no cerraba.
    if comp_lc.startswith("liquidacion rescate fci") or comp_lc.startswith("rescate fci"):
        return "VENTA"
    if comp_lc.startswith("suscripcion fci") or comp_lc.startswith("suscripcion fondo"):
        return "RETIRO"
    if comp_lc.startswith("compra"):            # normal / paridad / exterior
        return "COMPRA"
    if comp_lc.startswith("venta"):             # normal / paridad
        return "VENTA"
    if comp_lc.startswith("recibo de cobro") or comp_lc.startswith("rec cobro"):
        return "DEPOSITO"                       # CREDITO CTA CTE = ingreso de plata
    if comp_lc.startswith("orden de pago"):     # TRANSFERENCIA = egreso
        return "RETIRO"
    # Ingresos por título: cupón + amortización de bono, dividendos (todas las
    # variantes), pago de dividendos. (La amortización baja nominal → follow-up;
    # acá solo cuenta como ingreso de caja, que es lo que reconcilia.)
    if (comp_lc.startswith("renta") or comp_lc.startswith("dividendo")
            or comp_lc.startswith("pago div") or comp_lc.startswith("amortiz")):
        return "DIVIDENDO"
    # Retenciones, gastos y aranceles (notas de débito/crédito): efecto chico de
    # caja → FEE si sale, ingreso si entra (lo decide el signo en parse()).
    if (comp_lc.startswith("retencion") or comp_lc.startswith("nd ")
            or comp_lc.startswith("nc ") or "gasto" in comp_lc or "arancel" in comp_lc):
        return "FEE_SIGNED"
    return None

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


def _currency_from_sheet(hoja: str) -> str:
    """Moneda de la fila según el nombre de la hoja del Excel. Bull Market
    nombra las hojas 'Cuenta Corriente PESOS …' / 'DOLARES …' / 'DOLARES CABLE …'.
    El conversor de xlsx agrega ese nombre como columna sintética '_hoja' a cada
    fila, así la moneda sobrevive a la combinación de varios archivos."""
    return "USD" if "DOLAR" in (hoja or "").upper() else "ARS"


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

        # Cauciones: acumulamos su neto (= interés) POR MONEDA → una fila de
        # INTERÉS por moneda al final. last_idx indexa esas filas sintéticas.
        caucion_net = {}        # moneda → neto
        caucion_last_date = {}  # moneda → última fecha
        last_idx = 0

        for idx, row in enumerate(reader, start=1):
            last_idx = idx
            comprobante = G(row, "comprobante")
            comp_lc = comprobante.lower()
            if not comp_lc:
                continue  # fila vacía

            # Moneda de la fila por el nombre de la hoja (PESOS→ARS, DOLARES→USD).
            moneda = _currency_from_sheet(G(row, "_hoja"))

            # Cauciones (especie VARIAS): manejo de caja, no inversión. Acumulamos
            # su neto = interés ganado (por moneda) → fila de INTERÉS al final.
            # No crea el activo fantasma "VARIAS" ni infla el capital aportado.
            if "caucion" in comp_lc:
                v = _num(G(row, "importe"))
                if v is not None:
                    caucion_net[moneda] = caucion_net.get(moneda, 0.0) + v
                    d = G(row, "operado") or G(row, "liquida")
                    if d > caucion_last_date.get(moneda, ""):
                        caucion_last_date[moneda] = d
                continue

            # Conversiones internas cable↔MEP (NOTA DE CRÉDITO/DÉBITO U$S): mueven
            # los mismos dólares entre sub-cuentas y se cancelan entre archivos →
            # no son ingreso/egreso ni ganancia. Se omiten.
            if "nota de" in comp_lc and "u$s" in comp_lc:
                continue

            # FCI: el cash SÍ se cuenta (RESCATE→VENTA con sus datos, SUSCRIPCION→
            # RETIRO sin cantidad) — ver _classify_comprobante. La SUSCRIPCION no
            # trae unidades → la TENENCIA del FCI no se reconstruye (sigue siendo
            # carga manual / export de tenencias); pero la CAJA ahora reconcilia.
            tipo_rendi = _classify_comprobante(comp_lc)
            if tipo_rendi is None:
                # Tipo no soportado → lo reportamos pero seguimos (lo caza el
                # Import Guardian, no se mis-importa en silencio).
                result.parse_errors.append(RowError(
                    idx, "Comprobante", "BULLMARKET_OP_UNKNOWN",
                    f"Tipo de comprobante no soportado: '{comprobante}'.",
                ))
                continue

            # Reconciliación por SIGNO: `Importe` manda la dirección del cash.
            #  • FEE_SIGNED (retención/gasto/arancel) → FEE si sale, ingreso si entra.
            #  • Un dividendo/depósito/retiro con signo invertido (ej. una fila
            #    "DIVIDENDOS" con Importe NEGATIVO = retención/reverso) va al tipo
            #    opuesto, así el cash emitido siempre matchea el Importe (sin esto,
            #    el abs() contaba esa retención como ingreso → no reconciliaba).
            imp_sign = _num(G(row, "importe")) or 0.0
            if tipo_rendi == "FEE_SIGNED":
                tipo_rendi = "FEE" if imp_sign < 0 else "DIVIDENDO"
            elif tipo_rendi == "DIVIDENDO" and imp_sign < 0:
                tipo_rendi = "FEE"
            elif tipo_rendi == "DEPOSITO" and imp_sign < 0:
                tipo_rendi = "RETIRO"
            elif tipo_rendi == "RETIRO" and imp_sign > 0:
                tipo_rendi = "DEPOSITO"

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
            elif tipo_rendi == "DIVIDENDO":
                # Dividendo en USD: la especie es el activo (GOOGL, EWZ…), el
                # monto es el importe. El persister lo trata como ganancia.
                imp_v = _num(G(row, "importe"))
                monto = f"{abs(imp_v)}" if imp_v is not None else ""
                activo = _norm_ticker(G(row, "especie")) or ""
                qty = ""
                precio = ""
            else:
                # DEPOSITO / RETIRO: solo plata.
                imp_v = _num(G(row, "importe"))
                monto = f"{abs(imp_v)}" if imp_v is not None else ""
                qty = ""
                precio = ""
                activo = ""

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
                "comisiones": "0",
                "moneda":     moneda,
                "notas":      notas,
            }
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        # Interés de cauciones por moneda: el neto positivo (lo que volvió por
        # encima de lo colocado) es interés ganado → una fila de INTERÉS por
        # moneda. Solo si es > 0 (un neto ≤ 0 implicaría una caución abierta al
        # cierre → lo omitimos para no inventar una pérdida fantasma).
        for moneda, net in caucion_net.items():
            if net > 0:
                last_idx += 1
                result.raw_rows.append(RawRow(row_index=last_idx, data={
                    "fecha":      caucion_last_date.get(moneda, "") or "",
                    "tipo":       "INTERES",
                    "broker":     "Bull Market",
                    "activo":     "",
                    "cantidad":   "",
                    "precio":     "",
                    "monto":      f"{net:.2f}",
                    "monto_usd":  "",
                    "tc":         "",
                    "comisiones": "0",
                    "moneda":     moneda,
                    "notas":      "Interés de cauciones",
                }))

        return result

        return result
