"""Parser de Balanz — export de "Movimientos" (Actividad → Movimientos).

Es el LIBRO DE CAJA real: a diferencia del export de Resultados (informe de
ganancias/tenencias, SIN efectivo) y del de Órdenes (solo trades, sin depósitos),
Movimientos trae TODOS los movimientos de plata — incluidos los depósitos ("Recibo
de Cobro") — así que el cash RECONCILIA. Una hoja, columnas:
  Descripcion, Ticker, Tipo de Instrumento, Concertacion, Cantidad, Precio,
  Liquidacion, Moneda, Importe   (+ `_hoja` que agrega excel.xlsx_to_csv).

Reglas clave (verificadas contra archivo real):
  • Cada fila = un movimiento independiente (cada Boleto es 1 fila; los legs NO se
    parean por número de boleto).
  • `Importe` = el efecto en CASH (− sale, + entra). Es la fuente de verdad del
    cash → `monto = abs(Importe)` SIEMPRE, y el tipo de operación se elige para que
    el signo del cash MATCHEE el de Importe (así reconcilia por construcción).
  • `precio = -1` = sentinela "sin precio unitario" → fila de cash/renta/fee (no
    crea posición). Con precio real → trade/FCI (crea posición).
  • Compra/Venta de un Boleto está en el TEXTO ("Boleto / NNN / COMPRA|VENTA"),
    pero el signo de Importe es el que manda para el cash.
  • Comisiones/impuestos vienen como filas Pesos aparte (precio=-1, importe chico)
    → se emiten como FEE propias (cash correcto; el costo-base del trade no las
    incluye — follow-up menor).

Limitación conocida (follow-up): los fondos money-market "Suscripción/Rescate
desde/a Balanz" (sweeps de cash ocioso) traen el signo de Importe INVERTIDO
respecto del efecto en la cuenta principal (contabilidad del lado del fondo). Se
mapean por signo de Importe → el CASH reconcilia, pero la dirección de la POSICIÓN
del fondo-sweep puede quedar invertida. Los fondos "Liquidación de Suscripción/
Rescate" (los reales) quedan bien.
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
    "descripcion": ["descripcion"],
    "activo":      ["ticker", "especie"],
    "clase":       ["tipo de instrumento", "tipo instrumento", "tipoinstrumento"],
    "fecha":       ["concertacion", "fecha concertacion", "fecha"],
    "cantidad":    ["cantidad"],
    "precio":      ["precio"],
    "moneda":      ["moneda"],
    "importe":     ["importe"],
    "_hoja":       ["_hoja"],
}

# Movimientos se distingue de los otros dos exports de Balanz por traer JUNTAS las
# columnas `Descripcion` + `Importe` (Órdenes no tiene Descripcion; Resultados no
# tiene Importe ni Descripcion como columna de evento).
_REQUIRED = ("descripcion", "importe", "moneda")


def _norm_ccy(s: str) -> str:
    if not s:
        return ""
    v = " ".join(s.strip().lower().replace("ó", "o").split())
    if v.startswith("peso") or v in ("ars", "$"):
        return "ARS"
    if v.startswith("dolar") or "dollar" in v or v in ("usd", "u$s", "us$"):
        return "USD"
    return s.strip().upper()


def _asset_type(clase: str) -> Optional[str]:
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
    return None


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


# Descripciones que NO crean posición y se mapean por significado (el resto cae
# al default por signo de Importe). Match por substring sobre la desc normalizada.
def _classify_desc(desc_norm: str) -> str:
    d = desc_norm
    if d.startswith("transferencia"):
        return "transfer"
    if d.startswith("dividendo en acciones"):
        return "free_lot"
    if d.startswith("recibo de cobro"):
        return "deposito"
    if d.startswith("comprobante de pago"):
        return "retiro"
    if d.startswith("cargo por descubierto"):
        return "fee"
    if (d.startswith("renta") or d.startswith("dividendo")
            or d.startswith("amortizacion") or d.startswith("pago complementario")):
        return "renta"
    if d.startswith("movimiento manual"):
        return "manual"
    if d.startswith("boleto"):
        return "boleto"
    return "otro"


class BalanzMovimientosParser(Parser):
    format_id = "balanz_movimientos"
    display_name = "Balanz — Movimientos"
    is_supported = True
    platform = "balanz"
    platform_label = "Balanz"
    export_label = "Actividad → Movimientos (recomendado)"

    def can_handle(self, headers: List[str]) -> bool:
        cols = _resolve_columns(headers)
        return all(cols.get(f) for f in _REQUIRED)

    def template_csv(self) -> str:
        return (
            "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,Liquidacion,Moneda,Importe\n"
            "Recibo de Cobro / 8801586,,,2025-10-22,0,-1,2025-10-22,Pesos,3493747.27\n"
            "Boleto / 4863167 / COMPRA / 0 / GD46 / usd,AL35,Bonos,2025-10-23,1886,0.658687,2025-10-23,Dólares,-1218.15\n"
            "Boleto / 2452545 / VENTA / 0 / GD46 / usd,AL35,Bonos,2025-11-02,854,0.576364,2025-11-02,Dólares,531.01\n"
            "Dividendo en efectivo / XLE,XLE,Cedears,2025-12-15,0,-1,2025-12-15,Dólares,1.2\n"
            "Comprobante de Pago / 9971834,,,2026-01-10,0,-1,2026-01-10,Pesos,-421757.05\n"
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
                0, None, "BALANZ_MOV_HEADERS_MISMATCH",
                "Este archivo no coincide con el export de Movimientos de Balanz "
                "(Actividad → Movimientos). Asegurate de subir ese Excel — no el de "
                "Resultados ni el de Órdenes."))
            return result

        def _g(row, field_name):
            col = cols.get(field_name)
            return (row.get(col) or "").strip() if col else ""

        ridx = 0

        def _emit(d):
            nonlocal ridx
            ridx += 1
            result.raw_rows.append(RawRow(row_index=ridx, data=d))

        for row in reader:
            desc_raw = _g(row, "descripcion")
            desc = _norm_header(desc_raw)
            if not desc:
                continue
            ticker = _g(row, "activo").upper() or None
            moneda = _norm_ccy(_g(row, "moneda"))
            fecha = _g(row, "fecha")
            importe = _num(_g(row, "importe"))
            precio = _num(_g(row, "precio"))
            qty = _num(_g(row, "cantidad"))
            clase = _asset_type(_g(row, "clase"))
            kind = _classify_desc(desc)

            if importe is None and kind != "free_lot":
                continue  # sin importe no hay efecto de cash; nada que importar

            has_price = precio is not None and precio > 0
            cash_in = (importe or 0) > 0
            notas = desc_raw[:120]

            def base(tipo, **extra):
                d = {"fecha": fecha, "tipo": tipo, "broker": "Balanz",
                     "moneda": moneda, "notas": notas}
                if ticker:
                    d["activo"] = ticker
                if clase:
                    d["asset_type"] = clase
                d.update(extra)
                return d

            # ── Dividendo en acciones: lote gratis (qty>0) ────────────────────
            if kind == "free_lot":
                if qty and ticker:
                    _emit(base("COMPRA", activo=ticker, cantidad=str(abs(qty)),
                               precio="0", monto="0"))
                # Algunas traen ADEMÁS una retención/impuesto en pesos (importe≠0)
                # → emitimos ese efecto de cash para que reconcilie (FEE si sale).
                if importe is not None and abs(importe) > 0.001:
                    _emit(base("FEE" if importe < 0 else "DIVIDENDO", monto=str(abs(importe))))
                continue

            # ── Transferencia Externa: título transferido DESDE OTRO BROKER ───
            # Trae ticker + precio (el costo) pero Importe=0 (no movió plata en
            # Balanz; lo compraste en otro lado). Creamos la posición con su costo
            # + un DEPOSITO por ese valor (la "entrada" del título) → el cash NETEA
            # a 0 y el capital aportado refleja el valor transferido. Sin esto, el
            # normalizer recalculaba el monto y el persister debitaba cash que no
            # se gastó (rompía la reconciliación). Moneda: la del row o ARS (base
            # del broker) — los bonos en dólares transferidos son un follow-up.
            if kind == "transfer":
                if ticker and qty and precio is not None and precio > 0:
                    cost = abs(qty) * precio
                    mon = moneda or "ARS"
                    _emit(base("COMPRA", activo=ticker, cantidad=str(abs(qty)),
                               precio=str(precio), monto=str(round(cost, 4)), moneda=mon))
                    _emit({"fecha": fecha, "tipo": "DEPOSITO", "broker": "Balanz",
                           "moneda": mon, "monto": str(round(cost, 4)),
                           "notas": "Transferencia Externa (entrada de título)"})
                continue

            # ── Trade / FCI con precio real → crea posición ───────────────────
            # El tipo (COMPRA/VENTA) se decide por el SIGNO de Importe (cash), así
            # reconcilia siempre. El texto COMPRA/VENTA del Boleto coincide con
            # esto salvo en los fondos-sweep "desde/a Balanz" (limitación conocida).
            if has_price and ticker:
                tipo = "VENTA" if cash_in else "COMPRA"
                _emit(base(tipo, activo=ticker, cantidad=str(abs(qty or 0)),
                           precio=str(precio), monto=str(abs(importe))))
                continue

            # ── Boleto sin precio (precio=-1) ─────────────────────────────────
            # Dos sub-casos muy distintos: (a) la pata COMISIÓN de un trade
            # (COMPRA/VENTA, importe chico, sale) → FEE; (b) CAUCIÓN colocadora
            # (APCOLCON=contado sale / APCOLFUT=futuro entra, importes grandes) y
            # cualquier otra → flujo de caja por SIGNO (sale→RETIRO, entra→DEPOSITO).
            # Sin esto, la pata de caución que ENTRA se contaba como FEE (sale) →
            # cash mal por millones. El signo de Importe siempre manda para el cash.
            if kind == "boleto":
                op_tok = ""
                _parts = [p.strip() for p in desc_raw.split("/")]
                if len(_parts) >= 3:
                    op_tok = _parts[2].upper()
                if op_tok in ("COMPRA", "VENTA", "LICOMPRA", "LIVENTA"):
                    tipo = "FEE" if not cash_in else "DEPOSITO"
                else:
                    tipo = "DEPOSITO" if cash_in else "RETIRO"
                _emit(base(tipo, monto=str(abs(importe))))
                continue

            # ── Movimientos de efectivo / renta (precio=-1) ──────────────────
            if kind == "deposito":
                _emit(base("DEPOSITO" if cash_in else "RETIRO", monto=str(abs(importe))))
                continue
            if kind == "retiro":
                _emit(base("RETIRO" if not cash_in else "DEPOSITO", monto=str(abs(importe))))
                continue
            if kind == "fee":
                _emit(base("FEE", monto=str(abs(importe))))
                continue
            if kind == "renta":
                # ingreso (cupón/dividendo/amortización) si entra; retención si sale
                _emit(base("DIVIDENDO" if cash_in else "FEE", monto=str(abs(importe))))
                continue
            if kind == "manual":
                _emit(base("INTERES" if cash_in else "FEE", monto=str(abs(importe))))
                continue

            # ── Descripción NO reconocida → la MARCAMOS (no la tragamos en
            # silencio). Aparece vía el Import Guardian para que la soportemos, en
            # vez de mis-importarla como un depósito/retiro genérico. ────────────
            result.parse_errors.append(RowError(
                ridx + 1, ticker, "BALANZ_MOV_DESC_DESCONOCIDA",
                f"Movimiento de Balanz no reconocido: '{desc_raw[:60]}'. Se omitió "
                f"esta fila — escribinos para soportarlo."))

        return result
