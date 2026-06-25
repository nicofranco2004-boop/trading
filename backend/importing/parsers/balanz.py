"""Parser de Balanz — export real de "Órdenes" (app/web Balanz).

Headers del export de órdenes (Operaciones → Órdenes → Exportar):

    Operacion, Estado, id Orden, Ticker, Moneda, Fecha, Hora, Cantidad,
    Precio, Monto, Precio Operado, Cantidad Operada

Particularidades del formato y decisiones de importación:

- `Estado`: solo importamos `Ejecutada` y `Parcialmente Cancelada`. Las
  Cancelada / Rechazada / "Finalizada (Cancelando)" son ruido (no son trades).
- `Operacion` trae el plazo de liquidación pegado: "Compra 24hs", "Venta CI",
  "Compra 48hs". Solo importamos compra/venta de TÍTULOS. El resto es plumbing
  de cash/FX que NO mapea limpio y se saltea (ver `_map_operacion`):
    • Transferencia → sin señal de dirección (Monto siempre positivo) → skip.
    • Compra/Venta Dólar Bolsa → MEP ejecutado vía un FCI de liquidez → skip.
    • Suscripción/Rescate (Cuenta/Banco) → fondos de liquidez (parking) → skip.
    • Canje → sin ticker → skip. Caución / Cambio de Fondo → skip.
- Usamos `Cantidad Operada` / `Precio Operado` (lo realmente ejecutado), con
  fallback a `Cantidad` / `Precio` si vienen con el centinela -1.
- Moneda: Pesos→ARS; Dólares / "Dólares C.V. …" / "US Dollar (Cable)"→USD.
- Fecha en ISO (YYYY-MM-DD). Sin columna de comisiones en este export.
- `asset_type`: clasificamos por patrón de ticker (BOND para renta fija, FUND
  para FCI). Esto alimenta el guard anti-distorsión de la valuación, que para
  renta fija usa una banda estrecha (un bono no multibaggea) — así un ticker
  mal-priceado nunca infla la posición ×100.

LIMITACIÓN: construido sobre un export real (2026-01). Si Balanz cambia los
headers, puede requerir ajustes; si no matchean, usá el template genérico.
"""
from __future__ import annotations
import csv
import io
import re
from typing import Dict, List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


def _norm_header(h: str) -> str:
    """lowercase + saca tildes + colapsa espacios. 'Precio Operado' →
    'precio operado'; 'id Orden' → 'id orden'."""
    if not h:
        return ""
    s = (h.strip().lower()
           .replace("ó", "o").replace("í", "i").replace("á", "a")
           .replace("é", "e").replace("ú", "u").replace("ñ", "n"))
    return " ".join(s.split())


# Mapping de campos internos → headers reales del export de órdenes de Balanz.
_FIELD_ALIASES: Dict[str, List[str]] = {
    "operacion":       ["operacion", "operación", "tipo", "tipo de operacion"],
    "estado":          ["estado", "status"],
    "_id_orden":       ["id orden", "id de orden", "nro orden", "n orden", "orden id"],
    "activo":          ["ticker", "especie", "simbolo", "instrumento", "activo"],
    "moneda":          ["moneda", "moneda operacion"],
    "fecha":           ["fecha", "fecha operacion", "fecha concertacion", "fecha de concertacion"],
    "_hora":           ["hora"],
    "cantidad":        ["cantidad", "cantidad ordenada", "nominales", "valor nominal"],
    "precio":          ["precio", "precio ordenado", "precio unitario"],
    "monto":           ["monto", "importe", "importe bruto", "monto bruto"],
    "precio_operado":  ["precio operado", "precio ejecutado", "precio promedio operado"],
    "cantidad_operada": ["cantidad operada", "cantidad ejecutada", "nominales operados"],
}

# Para detectar Balanz-órdenes: operación + estado + ticker + fecha, y al menos
# una columna distintiva del export de órdenes (id orden / precio operado /
# cantidad operada) para no matchear otros brokers AR.
_REQUIRED = ("operacion", "estado", "activo", "fecha")
_DISCRIMINATORS = ("_id_orden", "precio_operado", "cantidad_operada")

# Estados que representan un trade real (consumieron al menos parte de la orden).
_OK_ESTADOS = {"ejecutada", "parcialmente cancelada"}


def _norm_currency(s: str) -> str:
    """Pesos / $ → ARS. Dólares / Dólares C.V. / US Dollar (Cable) → USD."""
    if not s:
        return ""
    v = " ".join(s.strip().lower().replace("ó", "o").split())
    if v.startswith("peso") or v in ("ars", "$", "ar$"):
        return "ARS"
    if v.startswith("dolar") or "dollar" in v or v in ("usd", "u$s", "us$"):
        return "USD"
    return s.strip().upper()


def _map_operacion(op: str) -> Optional[str]:
    """Balanz `Operacion` → token canónico Rendi ('COMPRA'/'VENTA'), o None
    para saltear. Solo compra/venta de títulos; el resto es plumbing de cash/FX
    que no mapea limpio (ver docstring del módulo)."""
    o = " ".join((op or "").strip().lower().replace("ó", "o").split())
    if not o:
        return None
    # Dólar Bolsa (MEP vía FCI) empieza con compra/venta pero NO es un trade
    # de título — excluir antes del match genérico.
    if "dolar bolsa" in o:
        return None
    if o.startswith("compra"):   # Compra CI / 24hs / 48hs
        return "COMPRA"
    if o.startswith("venta"):    # Venta CI / 24hs / 48hs
        return "VENTA"
    # Transferencia, Suscripcion, Rescate, Canje, Caucion, Cambio de Fondo, Deposito → skip
    return None


# ── Clasificación de asset_type por patrón de ticker (renta fija AR) ──────────
# Conservadora: solo marcamos BOND/FUND cuando estamos razonablemente seguros.
# Lo que no matchea queda sin hint (el normalizer cae a OTHER) → guard suelto,
# que es lo correcto para acciones/CEDEARs (pueden multibaggear de verdad).
_AR_BOND_PREFIXES = ("AL", "GD", "AE", "AY", "GE", "BA", "BB", "BP", "PB",
                     "PA", "TX", "TZ", "TT", "DN", "BD")


def _classify_asset(ticker: str) -> Optional[str]:
    t = (ticker or "").strip().upper()
    if not t:
        return None
    if t.startswith("FCI"):
        return "FUND"
    # Letras / Lecaps / Boncer: S/T/X + dígito (S31L5, T2X5, X30N6, TX28).
    if re.match(r"^[STX]\d", t):
        return "BOND"
    # Soberanos / BOPREAL / provinciales: prefijo conocido + algún dígito.
    if any(t.startswith(p) for p in _AR_BOND_PREFIXES) and any(c.isdigit() for c in t):
        return "BOND"
    # ONs corporativas: 5+ chars terminadas en 'O' (TECPO, GNCXO, MGC1O…).
    # Las acciones AR terminadas en O del panel son de ≤4 chars (AUSO, CADO, CTIO).
    if len(t) >= 5 and t.endswith("O"):
        return "BOND"
    return None  # acción / CEDEAR / otro → sin hint


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


def _num(s) -> Optional[float]:
    """Parsea un número tolerando coma decimal. Devuelve None si no parsea."""
    if s is None:
        return None
    txt = str(s).strip()
    if not txt:
        return None
    # Si tiene coma y no punto, es decimal AR (1.234,56 → 1234.56).
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        txt = txt.replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def _val(x) -> Optional[float]:
    """Valor 'operado' válido: número > 0 (el export usa -1 como centinela)."""
    n = _num(x)
    return n if (n is not None and n > 0) else None


class BalanzParser(Parser):
    format_id = "balanz"
    display_name = "Balanz"
    is_supported = True
    platform = "balanz"
    platform_label = "Balanz"
    export_label = "Operaciones → Órdenes → Exportar"

    def can_handle(self, headers: List[str]) -> bool:
        cols = _resolve_columns(headers)
        if not all(cols.get(f) for f in _REQUIRED):
            return False
        return any(cols.get(d) for d in _DISCRIMINATORS)

    def template_csv(self) -> str:
        return (
            "Operacion,Estado,id Orden,Ticker,Moneda,Fecha,Hora,Cantidad,"
            "Precio,Monto,Precio Operado,Cantidad Operada\n"
            "Compra 24hs,Ejecutada,100746376,ALUA,Pesos,2026-01-17,13:37:05,157,3963.2,622222.4,3963.2,157\n"
            "Venta CI,Ejecutada,100746377,GGAL,Pesos,2026-01-20,11:02:10,100,8200,820000,8200,100\n"
            "Compra 48hs,Ejecutada,100599473,GD30,Dólares,2025-12-31,16:06:25,1000,66.04,660.4,66.04,1000\n"
            "Compra CI,Ejecutada,100513140,TECPO,Pesos,2025-12-30,12:21:26,50,98000,4900000,98000,50\n"
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
            missing = [f for f in _REQUIRED if not cols.get(f)]
            result.parse_errors.append(RowError(
                0, None, "BALANZ_HEADERS_MISMATCH",
                f"Este archivo no coincide con el export de Órdenes de Balanz. "
                f"Faltan columnas para: {', '.join(missing)}. Exportá desde "
                f"Operaciones → Órdenes. Si tu export tiene otra estructura, usá "
                f"el template genérico de Rendi."))
            return result

        def _g(row, field_name):
            col = cols.get(field_name)
            return (row.get(col) or "").strip() if col else ""

        for idx, row in enumerate(reader, start=1):
            estado = _norm_header(_g(row, "estado"))
            if estado and estado not in _OK_ESTADOS:
                continue  # Cancelada / Rechazada / etc → no es un trade

            tipo = _map_operacion(_g(row, "operacion"))
            if not tipo:
                continue  # plumbing de cash/FX → skip

            activo = _g(row, "activo").upper()
            if not activo:
                continue  # un trade sin ticker no es importable

            fecha = _g(row, "fecha")
            if not fecha:
                continue

            # Cantidad / precio: preferimos lo OPERADO (ejecutado), con fallback
            # a lo ordenado si trae el centinela -1.
            cantidad = _val(_g(row, "cantidad_operada")) or _val(_g(row, "cantidad"))
            precio = _val(_g(row, "precio_operado")) or _val(_g(row, "precio"))
            if cantidad is None or precio is None:
                continue  # sin cantidad/precio confiable no podemos armar el trade

            data = {
                "fecha": fecha,
                "tipo": tipo,
                "broker": "Balanz",
                "activo": activo,
                "cantidad": str(cantidad),
                "precio": str(precio),
                "monto": _g(row, "monto"),
                "comisiones": "",  # el export de órdenes no trae comisiones
                "moneda": _norm_currency(_g(row, "moneda")),
            }
            asset_type = _classify_asset(activo)
            if asset_type:
                data["asset_type"] = asset_type

            result.raw_rows.append(RawRow(row_index=idx, data=data))

        return result
