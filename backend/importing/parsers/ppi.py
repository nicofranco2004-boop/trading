"""Parser de PPI (Portafolio Personal Inversiones) — export de "Movimientos".

PPI exporta los movimientos en un Excel con UNA HOJA POR SUB-CUENTA DE MONEDA
(Pesos, Dolar MEP, Dolar Cable, DolarCV7000/CV10000, variantes "… - COM 7340") +
una hoja `Instrumentos` (movimientos de títulos sin cash). El conversor de Excel
(importing/excel.py) une las columnas de todas las hojas y agrega `_hoja` = título
de la hoja a cada fila → acá ruteamos por `_hoja` (igual que Bull Market rutea por
nombre de hoja).

Columnas de las hojas de moneda:
  Fecha · Descripción · Cantidad · Precio · Importe · Saldo · Moneda
Columnas de la hoja Instrumentos:
  Fecha · Descripción · Especie · Cantidad · Precio · Moneda

Regla de oro (igual que Balanz Movimientos): `Importe` = efecto en CASH → siempre
`monto = abs(Importe)`, y el TIPO de operación define la dirección del cash. Para
TRADES y FONDOS la dirección sale del TEXTO (COMPRA/VENTA, Suscripción/Rescate),
no del signo de Importe — así es robusto aun si un export trae los signos rotos
(verificado: un archivo anonimizado tenía las VENTAS con Importe negativo). Para
los movimientos de caja bidireccionales (dividendo/renta/manual) sí mandamos por
el signo de Importe.

Moneda: la columna `Moneda` (o `_hoja`) dice "Pesos" / "Dolar MEP" / "DolarCV…" →
ARS si no contiene "DOLAR", USD si lo contiene. TODAS las sub-cuentas en dólares
colapsan a USD; el pipeline rutea esas filas al sub-broker "PPI · USD". El detalle
MEP/cable/CV es de liquidación, no de tenencia.

Taxonomía decodificada (verificada contra 2 exports reales de 2 usuarios):
  • COMPRA <ticker> / VENTA <ticker>          → trade (dirección por token)
  • COMPRA SPOT / VENTA SPOT                   → conducto dólar-MEP, ticker real
        vive en Instrumentos y la qty no matchea → se FLAGGEA (follow-up).
  • Liquidación de Suscripción / id / <Fondo>  → COMPRA del FCI (cash out)
  • Liquidación de Rescate / id / <Fondo>      → VENTA del FCI (cash in)
  • Bloqueo / Desbloqueo Monetario             → hold contable que se aparea y
        netea; la Liquidación es el cash real → SKIP (no doble-contar).
  • Ingreso de Fondos / Retiro de Fondos       → DEPOSITO / RETIRO
  • Dividendo en efectivo / <ticker>           → DIVIDENDO (+) / FEE (−)
  • Dividendo en acciones                      → acción societaria (lote gratis)
  • Renta / Amortización / Interest payment    → DIVIDENDO (+) / FEE (−)
  • Retenciones / Ret Ganancias / Comisión     → FEE
  • Débito (aranceles / monedas)               → por signo
  • Caución colocadora / Liquidación caución   → NETO por moneda = INTERÉS
  • Movimiento Manual (canje/compensación de
        monedas, vencimiento Plazo Com. A, …)  → por signo (INTERÉS/FEE)
  • Instrumentos → "Retiro de Títulos"         → transfer_out (cierra a costo)
  • Instrumentos → COMPRA/VENTA                → SKIP (redundante con la hoja $)

Follow-ups conocidos (no bloquean el cash; flaggeados o documentados):
  - SPOT (conducto dólar-MEP) — necesita un export real para mapear bien.
  - Instrumentos "Ingreso de Títulos" / "Canje" / "Traspaso" → se flaggean.
  - Canjes internos USD↔USD caen como INTERÉS/FEE que netean (ruido de P&L menor,
    igual que Balanz) — detectarlos y saltarlos es un follow-up.
  - Amortización baja el nominal del bono (acá solo cuenta como ingreso de caja).
  - asset_type no viene en el export → lo infiere la valuación/rebuild (como BM).
"""
from __future__ import annotations
import csv
import io
import re
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
    "fecha":       ["fecha"],
    "descripcion": ["descripcion"],
    "cantidad":    ["cantidad"],
    "precio":      ["precio"],
    "importe":     ["importe"],
    "saldo":       ["saldo"],
    "moneda":      ["moneda"],
    "especie":     ["especie"],   # solo hoja Instrumentos
    "_hoja":       ["_hoja"],
}

# PPI se distingue de Balanz Movimientos (no trae `saldo`) y de Bull Market (no
# trae `descripcion`/`moneda`) por traer JUNTAS descripcion + moneda + importe +
# saldo. Ese cuarteto es único de PPI.
_REQUIRED = ("descripcion", "moneda", "importe", "saldo")


def _num(s) -> Optional[float]:
    if s is None:
        return None
    txt = str(s).strip()
    if not txt or txt.lower() == "none":
        return None
    if "," in txt and "." in txt:
        txt = txt.replace(".", "").replace(",", ".")
    elif "," in txt:
        # coma decimal solo si hay 1-2 dígitos después; sino es separador de miles
        last = txt.rfind(",")
        if len(txt) - last - 1 in (1, 2):
            txt = txt.replace(",", ".")
        else:
            txt = txt.replace(",", "")
    try:
        return float(txt)
    except ValueError:
        return None


def _ccy(s: str) -> str:
    """Moneda de la fila. PPI usa 'Pesos' / 'Dolar MEP' / 'DolarCV7000 …' tanto en
    la columna Moneda como en el nombre de la hoja. Todo lo que contiene 'DOLAR'
    es USD; el resto, ARS."""
    return "USD" if "DOLAR" in (s or "").upper() else "ARS"


def _last_segment(desc_raw: str) -> str:
    """Último segmento de una descripción con '/' — el ticker en
    'Dividendo en efectivo / MSFT' o 'Renta / BPOB7'."""
    return desc_raw.split("/")[-1].strip().upper()


def _resolve_columns(headers: List[str]) -> Dict[str, Optional[str]]:
    norm_to_orig: Dict[str, str] = {}
    for h in headers:
        norm_to_orig.setdefault(_norm_header(h), h)
    resolved: Dict[str, Optional[str]] = {}
    for field_name, aliases in _FIELD_ALIASES.items():
        match = None
        for alias in aliases:
            key = _norm_header(alias)
            if key in norm_to_orig:
                match = norm_to_orig[key]
                break
        resolved[field_name] = match
    return resolved


# kind de cada descripción (sobre la desc normalizada: lowercase, sin acentos).
def _classify(desc_norm: str) -> str:
    d = desc_norm
    # Caución (colocadora + "liquidación caución colocadora N días"): antes que
    # cualquier "liquidacion de…" para no confundir con FCI.
    if "caucion" in d:
        return "caucion"
    if d.startswith("liquidacion de suscripcion"):
        return "fund_sub"
    if d.startswith("liquidacion de rescate"):
        return "fund_red"
    if d.startswith("bloqueo") or d.startswith("desbloqueo"):
        return "hold"   # se aparea y netea con la Liquidación → skip
    if d.startswith("compra ") or d.startswith("venta "):
        return "trade"
    if d.startswith("ingreso de fondos"):
        return "deposito"
    if d.startswith("retiro de fondos"):
        return "retiro"
    if d.startswith("dividendo en acciones"):
        return "corporate"
    if d.startswith("dividendo"):
        return "income"   # dividendo en efectivo
    if (d.startswith("renta") or d.startswith("amortizacion")
            or d.startswith("interest payment")):
        return "income"
    if (d.startswith("retencion") or d.startswith("ret ganancias")
            or d.startswith("ret. ganancias") or d.startswith("comision")):
        return "fee"
    if d.startswith("debito"):
        return "signed"   # débito de aranceles (−) / débito-crédito de monedas
    if d.startswith("split"):
        return "corporate"
    if d.startswith("movimiento manual"):
        return "signed"
    return "unknown"


class PpiParser(Parser):
    format_id = "ppi"
    display_name = "PPI — Portafolio Personal"
    is_supported = True
    platform = "ppi"
    platform_label = "PPI (Portafolio Personal)"
    export_label = "Movimientos (Excel)"

    def can_handle(self, headers: List[str]) -> bool:
        cols = _resolve_columns(headers)
        return all(cols.get(f) for f in _REQUIRED)

    def template_csv(self) -> str:
        return (
            "Fecha,Descripción,Cantidad,Precio,Importe,Saldo,Moneda,Especie,_hoja\n"
            "18/06/2026,Ingreso de Fondos ,0,0,846.26,1581.98,Dolar MEP,,Dolar MEP\n"
            "29/05/2026,COMPRA NU,367,8730.42,-3204064.14,2446147.83,Pesos,,Pesos\n"
            "08/04/2026,VENTA AL30,69152,0.93,64311.36,51279.49,Dolar MEP,,Dolar MEP\n"
            "12/06/2026,Dividendo en efectivo / MSFT,0,0,5.48,10.67,DolarCV7000 Ext.,,DolarCV7000 Ext.\n"
            "22/05/2026,Liquidación de Rescate / 603074 / Balanz Capital Ahorro - Clase A,41610,241.53,10050063.3,4835226.32,Pesos,,Pesos\n"
            "02/06/2026,Retiro de Títulos,0,0,,,,GGAL,Instrumentos\n"
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
                0, None, "PPI_HEADERS_MISMATCH",
                "Este archivo no coincide con el export de Movimientos de PPI. "
                "Bajalo desde la web de PPI (Mi cuenta → Movimientos) en Excel."))
            return result

        def _g(row, field_name):
            col = cols.get(field_name)
            return (row.get(col) or "").strip() if col else ""

        ridx = 0

        def _emit(d):
            nonlocal ridx
            ridx += 1
            result.raw_rows.append(RawRow(row_index=ridx, data=d))

        # Caución: acumulamos su neto (= interés ganado) POR MONEDA → una fila de
        # INTERÉS por moneda al final (no crea el activo fantasma de la caución).
        caucion_net: Dict[str, float] = {}
        caucion_last_date: Dict[str, str] = {}

        # Necesitamos materializar las filas para poder pasar dos veces si hiciera
        # falta; pero con el routing por kind alcanza una sola pasada.
        for row in reader:
            desc_raw = _g(row, "descripcion")
            desc = _norm_header(desc_raw)
            if not desc:
                continue
            hoja = _g(row, "_hoja")
            fecha = _g(row, "fecha")
            importe = _num(_g(row, "importe"))
            precio = _num(_g(row, "precio"))
            qty = _num(_g(row, "cantidad"))
            especie = _g(row, "especie").upper() or None
            moneda = _ccy(_g(row, "moneda") or hoja)

            has_cash = importe is not None and abs(importe) > 0.001
            has_qty = qty is not None and abs(qty) > 1e-9
            cash_in = (importe or 0) > 0
            notas = desc_raw[:120]

            def base(tipo, **extra):
                d = {"fecha": fecha, "tipo": tipo, "broker": "PPI",
                     "moneda": moneda, "notas": notas}
                d.update(extra)
                return d

            # ── Hoja Instrumentos: movimientos de títulos SIN cash ───────────
            # Los COMPRA/VENTA de acá son redundantes con la hoja de moneda (que
            # trae el precio) → se saltan. "Retiro de Títulos" = el título SALIÓ
            # de la cuenta (transferencia a otro broker) → transfer_out: cierra
            # el lote a costo (P&L 0), sin generar cash.
            if _norm_header(hoja) == "instrumentos":
                if desc.startswith("retiro de titulos") and especie and has_qty:
                    _emit({"fecha": fecha, "tipo": "VENTA", "broker": "PPI",
                           "activo": especie, "cantidad": str(abs(qty)),
                           "precio": "0", "monto": "0", "notas": notas,
                           "_transfer_out": "1"})
                elif desc.startswith("compra ") or desc.startswith("venta "):
                    continue  # redundante con la hoja de moneda
                else:
                    # Ingreso de Títulos / Canje / Traspaso / etc → follow-up.
                    result.parse_errors.append(RowError(
                        ridx + 1, especie, "PPI_INSTRUMENTO_NO_SOPORTADO",
                        f"Movimiento de títulos de PPI no soportado aún: "
                        f"'{desc_raw[:50]}'. Se omitió — escribinos para soportarlo."))
                continue

            if not has_cash and not has_qty:
                continue  # ni cash ni cantidad → nada que importar

            kind = _classify(desc)

            # ── Caución: acumular neto por moneda (interés) ──────────────────
            if kind == "caucion":
                if importe is not None:
                    caucion_net[moneda] = caucion_net.get(moneda, 0.0) + importe
                    if fecha > caucion_last_date.get(moneda, ""):
                        caucion_last_date[moneda] = fecha
                continue

            # ── Holds contables de FCI: netean con la Liquidación → skip ──────
            if kind == "hold":
                continue

            # ── Trade (COMPRA/VENTA <ticker>) — dirección por el TOKEN ────────
            if kind == "trade":
                parts = desc_raw.split(None, 1)
                tok = parts[0].strip().upper()        # COMPRA / VENTA
                ticker = (parts[1].strip().upper() if len(parts) > 1 else "")
                if ticker == "SPOT" or not ticker:
                    # Conducto dólar-MEP: el ticker real vive en Instrumentos y la
                    # qty no matchea → lo flaggeamos para soportarlo con dato real.
                    result.parse_errors.append(RowError(
                        ridx + 1, None, "PPI_SPOT_REVIEW",
                        f"Operación SPOT (dólar MEP) de PPI: '{desc_raw[:50]}'. "
                        f"Se omitió — la soportamos con un export real."))
                    continue
                tipo = "COMPRA" if tok == "COMPRA" else "VENTA"
                _emit(base(tipo, activo=ticker, cantidad=str(abs(qty or 0)),
                           precio=str(abs(precio)) if precio is not None else "",
                           monto=str(abs(importe)) if has_cash else ""))
                continue

            # ── FCI: Suscripción → COMPRA, Rescate → VENTA (dir. por keyword) ─
            # El fondo está en el último segmento ("… / Allaria Dolar Ahorro -
            # Clase A"). qty + precio reconstruyen la tenencia del fondo.
            if kind in ("fund_sub", "fund_red"):
                fondo = desc_raw.split("/")[-1].strip() if "/" in desc_raw else desc_raw
                tipo = "COMPRA" if kind == "fund_sub" else "VENTA"
                _emit(base(tipo, activo=fondo.upper(), asset_type="FUND",
                           asset_name=fondo,
                           cantidad=str(abs(qty or 0)),
                           precio=str(abs(precio)) if precio else "",
                           monto=str(abs(importe)) if has_cash else ""))
                continue

            # ── Acción societaria (dividendo en acciones / split): lote gratis o
            # ajuste de cantidad sin (o casi sin) cash. qty>0 → entran nominales.
            if kind == "corporate":
                tk = _last_segment(desc_raw) if "/" in desc_raw else especie
                if has_qty and tk:
                    _emit(base("COMPRA" if qty > 0 else "VENTA", activo=tk,
                               cantidad=str(abs(qty)), precio="0", monto="0"))
                if has_cash:
                    _emit(base("DIVIDENDO" if cash_in else "FEE",
                               monto=str(abs(importe))))
                continue

            # ── Movimientos de caja ──────────────────────────────────────────
            if not has_cash:
                continue  # los que siguen son puro cash

            if kind == "deposito":
                _emit(base("DEPOSITO" if cash_in else "RETIRO", monto=str(abs(importe))))
            elif kind == "retiro":
                _emit(base("RETIRO" if not cash_in else "DEPOSITO", monto=str(abs(importe))))
            elif kind == "income":
                # cupón / dividendo / amortización / interés: ingreso si entra,
                # retención si sale. Ticker (si lo hay) en el último segmento.
                tk = _last_segment(desc_raw) if "/" in desc_raw else ""
                extra = {"activo": tk} if tk and cash_in else {}
                _emit(base("DIVIDENDO" if cash_in else "FEE",
                           monto=str(abs(importe)), **extra))
            elif kind == "fee":
                _emit(base("FEE", monto=str(abs(importe))))
            elif kind in ("signed", "manual"):
                # débito/crédito de monedas, canje, compensación, vencimiento
                # Plazo Com. A, traspaso: por signo (igual que Balanz "manual").
                _emit(base("INTERES" if cash_in else "FEE", monto=str(abs(importe))))
            else:
                result.parse_errors.append(RowError(
                    ridx + 1, None, "PPI_DESC_DESCONOCIDA",
                    f"Movimiento de PPI no reconocido: '{desc_raw[:60]}'. Se omitió "
                    f"esta fila — escribinos para soportarlo."))

        # ── Interés de cauciones por moneda ──────────────────────────────────
        # Neto positivo (lo que volvió por encima de lo colocado) = interés ganado.
        # Neto ≤ 0 ⇒ caución abierta al cierre → omitimos (no inventamos pérdida).
        for moneda, net in caucion_net.items():
            if net > 0.001:
                _emit({"fecha": caucion_last_date.get(moneda, "") or "",
                       "tipo": "INTERES", "broker": "PPI", "moneda": moneda,
                       "monto": f"{net:.2f}", "notas": "Interés de cauciones"})

        return result
