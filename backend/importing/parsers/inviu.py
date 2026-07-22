"""Parser de inviu — export "Reporte de cuenta corriente" (historial de movimientos).

Es el LIBRO DE CAJA de inviu: una grilla con preámbulo (título + metadata) y el
header real más abajo (excel.xlsx_to_csv lo detecta y re-emite desde ahí, ver el
guard anti-preámbulo). Trae TODOS los movimientos de plata agrupados en SECCIONES
por moneda — "PESOS - $" y "Dólar MEP - U$S" — cada una con su saldo corrido.

Columnas:
  Fecha de Concertación · Fecha de Liquidación · Descripción · Tipo de Operación ·
  Ticker · Cantidad VN · Precio · Import Bruto · Importe Neto · Saldo

Reglas clave (verificadas contra un export real):
  • La MONEDA sale de la sección vigente (fila marcador "PESOS - $" / "Dólar MEP").
  • `Importe Neto` = efecto real en el saldo (Saldo[i] = Saldo[i-1] + Neto).
  • Trades (CPRA/VENTA): `Import Bruto` = Cantidad×Precio; la comisión/impuesto está
    en la diferencia |Neto|−|Bruto| → emitimos monto=|Bruto| + comisiones=|Neto|−|Bruto|.
    `Cantidad VN` viene negativa en las VENTAS → usamos abs.
  • Movimientos de caja (sin ticker/precio): monto = |Importe Neto|.

Taxonomía (columna "Tipo de Operación"):
  • CPRA                  → COMPRA
  • VENTA                 → VENTA
  • Recibo de Cobro       → DEPOSITO
  • Comprobante de Pago   → RETIRO
  • Dividendo en efectivo → DIVIDENDO (ticker en la desc)
  • Renta                 → DIVIDENDO (cupón de bono)
  • Amortización          → DIVIDENDO (devolución de capital; v1 cuenta el cash y la
        foto de tenencia reconcilia el nominal — el ajuste del nominal es follow-up)
  • "-" (genéricos)       → por descripción:
        Rendimiento diario → INTERES ; Retención Impositiva → IMPUESTO ;
        Fee/Comisión/Arancel → FEE ; Acreencia → INTERES ;
        Interest payment / resto → por signo (entra INTERES / sale FEE)

Follow-ups: amortización no baja el nominal del bono (lo corrige la foto); asset_type
no viene por fila → lo infiere la valuación/rebuild (como Bull Market / PPI).
"""
from __future__ import annotations
import csv
import io
import re
from typing import Dict, List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


def _norm(s: str) -> str:
    if not s:
        return ""
    t = (s.strip().lower()
           .replace("ó", "o").replace("í", "i").replace("á", "a")
           .replace("é", "e").replace("ú", "u").replace("ñ", "n"))
    return " ".join(t.split())


_FIELD_ALIASES: Dict[str, List[str]] = {
    "fecha":  ["fecha de concertacion", "concertacion", "fecha"],
    "desc":   ["descripcion"],
    "tipo":   ["tipo de operacion"],
    "ticker": ["ticker"],
    "cant":   ["cantidad vn", "cantidad"],
    "precio": ["precio"],
    "bruto":  ["import bruto", "importe bruto"],
    "neto":   ["importe neto"],
    "saldo":  ["saldo"],
}

# inviu se distingue por traer JUNTAS estas columnas (ningún otro export las tiene
# todas): Tipo de Operación + Import Bruto + Importe Neto + Saldo.
_REQUIRED = ("tipo", "bruto", "neto", "saldo")

_DATE_RE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


def _num(s) -> Optional[float]:
    if s is None:
        return None
    txt = str(s).strip()
    if not txt or txt in ("-", "none", "None"):
        return None
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        last = txt.rfind(",")
        if len(txt) - last - 1 in (1, 2):
            txt = txt.replace(",", ".")
        else:
            txt = txt.replace(",", "")
    try:
        return float(txt)
    except ValueError:
        return None


def _to_iso(d: str) -> str:
    m = _DATE_RE.match(d or "")
    if not m:
        return (d or "").strip()
    dd, mm, yy = m.groups()
    return f"{yy}-{int(mm):02d}-{int(dd):02d}"


def _section_ccy(cell: str) -> Optional[str]:
    """Si `cell` es un marcador de sección de moneda devuelve ARS/USD, si no None."""
    u = (cell or "").upper()
    if "PESOS" in u and "-" in u:
        return "ARS"
    if ("DOLAR" in u or "DÓLAR" in u) and "-" in u:
        return "USD"
    return None


def _resolve_columns(headers: List[str]) -> Dict[str, Optional[str]]:
    norm_to_orig: Dict[str, str] = {}
    for h in headers:
        norm_to_orig.setdefault(_norm(h), h)
    resolved: Dict[str, Optional[str]] = {}
    for field_name, aliases in _FIELD_ALIASES.items():
        match = None
        for alias in aliases:
            key = _norm(alias)
            if key in norm_to_orig:
                match = norm_to_orig[key]
                break
        resolved[field_name] = match
    return resolved


class InviuParser(Parser):
    format_id = "inviu"
    display_name = "inviu — Cuenta corriente (movimientos)"
    is_supported = True
    platform = "inviu"
    platform_label = "inviu"
    export_label = "Reporte de cuenta corriente (Excel)"

    def can_handle(self, headers: List[str]) -> bool:
        cols = _resolve_columns(headers)
        return all(cols.get(f) for f in _REQUIRED)

    def template_csv(self) -> str:
        return (
            "Fecha de Concertación,Fecha de Liquidación,Descripción,Tipo de Operación,"
            "Ticker,Cantidad VN,Precio,Import Bruto,Importe Neto,Saldo\n"
            "PESOS - $,,,,,,,,,\n"
            "13/3/2024,13/3/2024,Recibo de Cobro / 103382,Recibo de Cobro,-,-,0,300000,300000,300000\n"
            "13/3/2024,15/3/2024,Boleto / 378418 / CPRA / 2 / NVDA / $,CPRA,NVDA,4,39316.5,-157266,-159321.15,141254.65\n"
            "14/1/2025,15/1/2025,Boleto / 104377 / VENTA / 1 / AL30 / $,VENTA,AL30,-68,796.6,54168.8,53621.69,386.44\n"
            "23/5/2024,23/5/2024,Dividendo en efectivo / GGAL,Dividendo en efectivo,GGAL,-,0,2715.64,2715.64,2853.61\n"
            "Dólar MEP - U$S,,,,,,,,,\n"
            "5/6/2024,5/6/2024,Amortización / MRCAO,Amortización,MRCAO,-,0,25.89,25.89,26.38\n"
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
                0, None, "INVIU_HEADERS_MISMATCH",
                "Este archivo no coincide con el Reporte de cuenta corriente de inviu. "
                "Bajalo desde inviu (movimientos) en Excel."))
            return result

        def _g(row, field_name):
            col = cols.get(field_name)
            return (row.get(col) or "").strip() if col else ""

        ridx = 0

        def _emit(d):
            nonlocal ridx
            ridx += 1
            result.raw_rows.append(RawRow(row_index=ridx, data=d))

        moneda = "ARS"  # sección vigente; el marcador de sección la actualiza

        for row in reader:
            fecha_raw = _g(row, "fecha")

            # Marcador de sección de moneda ("PESOS - $" / "Dólar MEP - U$S"): cae en
            # la primera columna. Actualiza la moneda y sigue.
            sec = _section_ccy(fecha_raw)
            if sec:
                moneda = sec
                continue

            # Solo procesamos filas con fecha real (d/m/aaaa). Descarta subtítulos
            # ("Disponible - Cartera monetaria"), "Saldo al …" y filas vacías.
            if not _DATE_RE.match(fecha_raw):
                continue

            fecha = _to_iso(fecha_raw)
            tipo_raw = _g(row, "tipo")
            desc_raw = _g(row, "desc")
            desc = _norm(desc_raw)
            ticker = _g(row, "ticker").upper().strip()
            if ticker in ("-", ""):
                ticker = None
            cant = _num(_g(row, "cant"))
            precio = _num(_g(row, "precio"))
            bruto = _num(_g(row, "bruto"))
            neto = _num(_g(row, "neto"))

            has_cash = neto is not None and abs(neto) > 0.001
            cash_in = (neto or 0) > 0
            notas = desc_raw[:120]

            def base(t, **extra):
                d = {"fecha": fecha, "tipo": t, "broker": "inviu",
                     "moneda": moneda, "notas": notas}
                d.update(extra)
                return d

            t = tipo_raw.strip().upper()

            # ── Trades (Boleto) ──────────────────────────────────────────────
            if t in ("CPRA", "VENTA") and ticker and cant is not None:
                tipo = "COMPRA" if t == "CPRA" else "VENTA"
                gross = abs(bruto) if bruto is not None else 0.0
                comision = abs((abs(neto) - gross)) if (neto is not None and gross) else 0.0
                _emit(base(tipo, activo=ticker, cantidad=str(abs(cant)),
                           precio=str(abs(precio)) if precio is not None else "",
                           monto=str(gross),
                           comisiones=str(round(comision, 4)) if comision > 1e-9 else ""))
                continue

            # De acá para abajo son movimientos de caja: necesitan neto.
            if not has_cash:
                continue

            # ── Cobros / pagos ───────────────────────────────────────────────
            if _norm(tipo_raw) == "recibo de cobro":
                _emit(base("DEPOSITO" if cash_in else "RETIRO", monto=str(abs(neto))))
                continue
            if _norm(tipo_raw) == "comprobante de pago":
                _emit(base("RETIRO" if not cash_in else "DEPOSITO", monto=str(abs(neto))))
                continue

            # ── Renta de títulos (dividendo / cupón / amortización) ──────────
            if _norm(tipo_raw) in ("dividendo en efectivo", "renta", "amortizacion"):
                extra = {"activo": ticker} if (ticker and cash_in) else {}
                _emit(base("DIVIDENDO" if cash_in else "IMPUESTO",
                           monto=str(abs(neto)), **extra))
                continue

            # ── Genéricos (Tipo = "-"): clasificar por descripción ───────────
            if "rendimiento" in desc:
                _emit(base("INTERES", monto=str(abs(neto))))
            elif "retencion" in desc or "impositiva" in desc or "impuesto" in desc:
                _emit(base("IMPUESTO", monto=str(abs(neto))))
            elif "fee" in desc or "comision" in desc or "arancel" in desc:
                _emit(base("FEE", monto=str(abs(neto))))
            elif "acreencia" in desc:
                _emit(base("INTERES", monto=str(abs(neto))))
            else:
                # Interest payment y cualquier otro genérico → por signo.
                _emit(base("INTERES" if cash_in else "FEE", monto=str(abs(neto))))

        return result
