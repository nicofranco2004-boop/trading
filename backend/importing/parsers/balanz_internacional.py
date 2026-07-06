"""Parser de Balanz INTERNACIONAL — export de "Movimientos" de la cuenta exterior
(Balanz Capital International Inc., Panamá).

Mismas COLUMNAS que el Movimientos de Balanz local (Descripcion, Ticker, Tipo de
Instrumento, Concertacion, Cantidad, Precio, Liquidacion, Moneda, Importe), pero es
una cuenta en DÓLARES que opera instrumentos del EXTERIOR — acciones US REALES (no
CEDEARs), ETFs, bonos/ISINs, US Treasuries y fondos Balanz USD. Por eso NO se puede
reusar el parser local: sus posiciones se valúan por el ticker US (no `.BA`) y viven
en un broker USD, no en el "Balanz" (ARS).

Diferencias vs Balanz local (verificadas contra archivo real, 418 filas):
  • Trades: "Boleto / N / COMPRAEXT|VENTAEXT|CSBNG|VSBNG / cant / TICKER / U$S". El
    op-token trae sufijo EXT (acciones/ETFs) o SBNG (bonos/treasuries). Igual que el
    local, el SIGNO de Importe manda para el cash → COMPRA (sale) / VENTA (entra).
  • Tickers con PUNTO final ("ADBE.", "MSFT.", "NU.", "MELI.") → se limpia el punto.
    Son símbolos US reales → se valúan por el ticker US (broker USD, no `.BA`).
  • Todo en "US Dollar (Cable)" → USD (moneda vacía → USD, base de la cuenta).
  • FCI "Liquidación de Suscripción/Rescate": Balanz manda Precio = -1 (sin VCP) →
    la dirección se decide por NOMBRE (suscripción=COMPRA, rescate=VENTA) y el precio
    se deriva (monto/cantidad). En el local venía con precio → acá NO exigimos precio.
  • Tipos de instrumento nuevos: "US Treasuries" (→ BOND).
  • Eventos nuevos: "Reverse Split" (canje que cambia cantidad, importe 0),
    "Tax Withholding / Tax Witholding Reversal" (retención en inglés + su reverso),
    "Liquidación de Transferencia Crédito" (entrada de título por transferencia).

`Importe` = efecto en CASH (− sale, + entra) → `monto = abs(Importe)` SIEMPRE y el
tipo se elige para que el signo del cash matchee → reconcilia por construcción.
`Precio = -1` = sentinela "sin precio unitario".
"""
from __future__ import annotations
import csv
import io
from typing import List, Optional

from .base import Parser
from ..schema import ParseResult, RawRow, RowError
# Reusamos los helpers PUROS del parser local (mismo formato de columnas) sin tocarlo.
from .balanz_movimientos import (
    _norm_header, _norm_ccy, _num, _resolve_columns, _REQUIRED, _is_tax,
)

BROKER = "Balanz Internacional"


def _asset_type_intl(clase: str) -> Optional[str]:
    """Tipo de Instrumento → asset_type. Igual que el local + 'US Treasuries'→BOND.
    En la cuenta internacional 'Acciones' son acciones US REALES (no CEDEARs)."""
    c = (clase or "").strip().lower().replace("ó", "o")
    if not c:
        return None
    if "cedear" in c:
        return "CEDEAR"
    if "fondo" in c:
        return "FUND"
    if "accion" in c:
        return "STOCK"
    if ("bono" in c or "letra" in c or "corporativ" in c or "obligacion" in c
            or "treasur" in c or "treasury" in c):
        return "BOND"
    return None


def _clean_ticker(raw: str) -> Optional[str]:
    """Limpia el ticker del export internacional: saca el PUNTO final ('ADBE.' →
    'ADBE'), espacios de borde y colapsa espacios internos. Devuelve None si vacío."""
    if not raw:
        return None
    t = " ".join(raw.strip().split())
    t = t.rstrip(".").strip()
    return t.upper() or None


def _classify_desc(desc_norm: str) -> str:
    """Clasifica el evento por su descripción (substring sobre desc normalizada).
    Adaptado del local + los tipos propios del internacional."""
    d = desc_norm
    if d.startswith("transferencia") or d.startswith("liquidacion de transferencia"):
        return "transfer"
    # Acciones societarias que cambian CANTIDAD (con o sin cash): split / reverse
    # split (consolidación: sale el viejo qty−, entra el nuevo qty+, importe 0),
    # dividendo en acciones/especie, cambio de ratio, rescate parcial de bono, canje,
    # reducción de capital, conversión especie.
    if (d.startswith("reverse split") or d.startswith("split")
            or d.startswith("dividendo en acciones") or d.startswith("dividendo en especie")
            or d.startswith("acreditacion cambio de ratio") or d.startswith("rescate parcial")
            or d.startswith("canje s/aviso") or d.startswith("reduccion de capital")
            or d.startswith("conversion especie")):
        return "corporate"
    # Retención de impuesto (inglés, cuenta exterior) + su reverso. Por signo:
    # sale → IMPUESTO, entra (reversal) → ingreso que reconcilia el cash.
    if d.startswith("tax withholding") or d.startswith("tax witholding"):
        return "tax"
    if d.startswith("recibo de cobro") or d.startswith("acreditacion de cheque"):
        return "deposito"
    if d.startswith("comprobante de pago"):
        return "retiro"
    if d.startswith("cargo por descubierto") or d.startswith("debito de aranceles"):
        return "fee"
    # Ingresos por título (entra) / retención (sale): cupón, dividendo, amortización
    # (devuelve capital → baja nominal), intereses, prima/rescate de bono.
    if (d.startswith("renta") or d.startswith("dividendo") or d.startswith("amortizacion")
            or d.startswith("pago complementario") or d.startswith("prima por rescate")
            or d.startswith("intereses devengados") or d.startswith("rescate")
            or d.startswith("baja derecho")):
        return "renta"
    if d.startswith("movimiento manual"):
        return "manual"
    if d.startswith("boleto"):
        return "boleto"
    return "otro"


class BalanzInternacionalParser(Parser):
    format_id = "balanz_internacional"
    display_name = "Balanz Internacional — Movimientos"
    is_supported = True
    platform = "balanz"
    platform_label = "Balanz"
    export_label = "Movimientos — cuenta Internacional (exterior, USD)"

    # NO autodetecta: el export internacional tiene EXACTAMENTE las mismas columnas
    # que el Movimientos local → indistinguible por headers. La selección es
    # explícita en el wizard (el user elige "Internacional" bajo Balanz).
    def can_handle(self, headers: List[str]) -> bool:
        return False

    def template_csv(self) -> str:
        return (
            "Descripcion,Ticker,Tipo de Instrumento,Concertacion,Cantidad,Precio,Liquidacion,Moneda,Importe\n"
            "Boleto / 66388 / COMPRAEXT / 1 / ADBE. / U$S,ADBE.,Acciones,2026-06-30,1,202.79,2026-07-01,US Dollar (Cable),-212.8\n"
            "Boleto / 57092 / VENTAEXT / 1 / SMR. / U$S,SMR.,Acciones,2026-06-05,-48,10.7301,2026-06-08,US Dollar (Cable),505.04\n"
            "Liquidación de Suscripción / 4791 / BALANZ GLOBAL EQUITY,BGLOBALE.,Fondos,2026-06-12,1000,-1,2026-06-16,US Dollar (Cable),-1227.14\n"
            "Dividendo en efectivo / MSFT.,MSFT.,Acciones,2026-06-11,0,-1,2026-06-11,US Dollar (Cable),10.19\n"
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
                0, None, "BALANZ_INTL_HEADERS_MISMATCH",
                "Este archivo no coincide con el export de Movimientos de Balanz "
                "(Actividad → Movimientos). Subí ese Excel de tu cuenta Internacional."))
            return result

        def _g(row, field_name):
            col = cols.get(field_name)
            return (row.get(col) or "").strip() if col else ""

        ridx = 0

        def _emit(d):
            nonlocal ridx
            ridx += 1
            result.raw_rows.append(RawRow(row_index=ridx, data=d))

        _amort_closed = set()

        for row in reader:
            desc_raw = _g(row, "descripcion")
            desc = _norm_header(desc_raw)
            if not desc:
                continue
            ticker = _clean_ticker(_g(row, "activo"))
            moneda = _norm_ccy(_g(row, "moneda")) or "USD"   # cuenta USD
            fecha = _g(row, "fecha")
            importe = _num(_g(row, "importe"))
            precio = _num(_g(row, "precio"))
            qty = _num(_g(row, "cantidad"))
            clase = _asset_type_intl(_g(row, "clase"))
            kind = _classify_desc(desc)

            has_price = precio is not None and precio > 0
            has_qty = qty is not None and abs(qty) > 1e-9
            has_cash = importe is not None and abs(importe) > 0.001
            cash_in = (importe or 0) > 0
            notas = desc_raw[:120]

            if not has_cash and not has_qty:
                continue

            def base(tipo, **extra):
                d = {"fecha": fecha, "tipo": tipo, "broker": BROKER,
                     "moneda": moneda or "USD", "notas": notas}
                if ticker:
                    d["activo"] = ticker
                if clase:
                    d["asset_type"] = clase
                d.update(extra)
                return d

            # ── Acción societaria (split / reverse split / dividendo en acciones /
            # canje): cambia CANTIDAD. qty>0 → entran (COMPRA precio 0, baja promedio);
            # qty<0 → salen (VENTA precio 0, cierra nominal). El cash que traiga (raro)
            # va por signo (DIVIDENDO/IMPUESTO).
            if kind == "corporate":
                if has_qty and ticker:
                    if qty > 0:
                        _emit(base("COMPRA", activo=ticker,
                                   cantidad=str(abs(qty)), precio="0", monto="0"))
                    else:
                        _emit(base("VENTA", activo=ticker, cantidad=str(abs(qty)),
                                   precio="0", monto="0", _corporate_close=True))
                if has_cash:
                    _emit(base("DIVIDENDO" if cash_in else "IMPUESTO", monto=str(abs(importe))))
                continue

            # ── Transferencia de título (entrada/salida). Con precio → COMPRA a su
            # costo + DEPOSITO por el valor (cash netea 0, capital aportado refleja el
            # título). Sin precio (Liquidación de Transferencia de un fondo, importe 0)
            # → COMPRA precio 0 (crea la posición; la foto de tenencia la valúa).
            if kind == "transfer":
                if ticker and has_qty and has_price:
                    cost = abs(qty) * precio
                    _emit(base("COMPRA", activo=ticker, cantidad=str(abs(qty)),
                               precio=str(precio), monto=str(round(cost, 4))))
                    _emit({"fecha": fecha, "tipo": "DEPOSITO", "broker": BROKER,
                           "moneda": moneda or "USD", "monto": str(round(cost, 4)),
                           "notas": "Transferencia (entrada de título)"})
                elif ticker and has_qty:
                    if qty > 0:
                        _emit(base("COMPRA", activo=ticker, cantidad=str(abs(qty)),
                                   precio="0", monto="0"))
                    else:
                        _emit(base("VENTA", activo=ticker, cantidad=str(abs(qty)),
                                   precio="0", monto="0", _corporate_close=True))
                if has_cash:
                    _emit(base("DEPOSITO" if cash_in else "RETIRO", monto=str(abs(importe))))
                continue

            # ── FCI (fondos): Suscripción/Rescate. Balanz manda Precio = -1 (sin VCP)
            # → NO exigimos precio (lo deriva el normalizer: monto/cantidad). Dirección
            # por NOMBRE: suscripción=COMPRA (cash out), rescate=VENTA (cash in). El
            # cash reconcilia por construcción (monto=|Importe|). También cubre la
            # forma directa "Suscripción/Rescate" sin "Liquidación de".
            _is_fci = (clase == "FUND"
                       or desc.startswith("liquidacion de suscrip")
                       or desc.startswith("liquidacion de rescate")
                       or desc.startswith("suscrip") or desc.startswith("rescate"))
            if _is_fci and has_qty and has_cash and ticker:
                if desc.startswith("rescate") or desc.startswith("liquidacion de rescate"):
                    tipo = "VENTA"
                elif desc.startswith("suscrip") or desc.startswith("liquidacion de suscrip"):
                    tipo = "COMPRA"
                else:
                    tipo = "VENTA" if cash_in else "COMPRA"
                emit = base(tipo, activo=ticker, cantidad=str(abs(qty)), monto=str(abs(importe)))
                if has_price:
                    emit["precio"] = str(precio)
                _emit(emit)
                continue

            # ── Trade con precio real (acciones US / bonos / ETFs / treasuries) →
            # crea posición. Tipo por SIGNO de Importe. monto = |Importe| (incluye la
            # comisión ~US$10 embebida en el cash → costo-base correcto). El op-token
            # COMPRAEXT/VENTAEXT/CSBNG/VSBNG es informativo (el signo manda).
            if has_price and ticker:
                tipo = "VENTA" if cash_in else "COMPRA"
                _emit(base(tipo, activo=ticker, cantidad=str(abs(qty or 0)),
                           precio=str(precio), monto=str(abs(importe))))
                continue

            # ── Retención de impuesto (inglés) + reverso. Por signo: sale → IMPUESTO,
            # entra (reversal) → ingreso que reconcilia el cash devuelto.
            if kind == "tax":
                _emit(base("DIVIDENDO" if cash_in else "IMPUESTO", monto=str(abs(importe))))
                continue

            # ── Movimiento manual que CAMBIA cantidad sin cash (ej. "Cambio notas
            # estructuradas a fondos": el título viejo SALE) → cierre corporate, para
            # no dejar una posición fantasma. El destino (fondo) entra por su propia
            # fila "Liquidación de Transferencia Crédito".
            if kind == "manual" and has_qty and ticker and not has_cash:
                if qty > 0:
                    _emit(base("COMPRA", activo=ticker, cantidad=str(abs(qty)),
                               precio="0", monto="0"))
                else:
                    _emit(base("VENTA", activo=ticker, cantidad=str(abs(qty)),
                               precio="0", monto="0", _corporate_close=True))
                continue

            # ── Movimientos de caja / renta (precio = -1) ────────────────────
            if kind in ("deposito", "retiro", "fee", "renta", "manual") and not has_cash:
                continue
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
                # Amortización que DEVUELVE CAPITAL (baja nominal): el cobro (entra)
                # cierra ese nominal como VENTA a su valor de rescate (proceeds) → P&L
                # correcto. Dedup por (ticker, fecha, |cantidad|).
                if has_qty and ticker and "amortizacion" in desc:
                    sig = (ticker, fecha, round(abs(qty), 3))
                    if cash_in and sig not in _amort_closed:
                        _amort_closed.add(sig)
                        _emit(base("VENTA", activo=ticker, cantidad=str(abs(qty)),
                                   monto=str(abs(importe))))
                        continue
                _emit(base("DIVIDENDO" if cash_in else "IMPUESTO", monto=str(abs(importe))))
                continue
            if kind == "manual":
                if "conversion" in desc:
                    continue
                if cash_in:
                    _emit(base("INTERES", monto=str(abs(importe))))
                elif _is_tax(desc):
                    _emit(base("IMPUESTO", monto=str(abs(importe))))
                else:
                    _emit(base("FEE", monto=str(abs(importe))))
                continue

            # ── Boleto sin precio (precio = -1): comisión de trade (sale) → FEE, o
            # flujo de caja por signo.
            if kind == "boleto":
                _emit(base("DEPOSITO" if cash_in else "FEE", monto=str(abs(importe))))
                continue

            # ── Descripción no reconocida → la marcamos (Import Guardian). ───────
            result.parse_errors.append(RowError(
                ridx + 1, ticker, "BALANZ_INTL_DESC_DESCONOCIDA",
                f"Movimiento de Balanz Internacional no reconocido: '{desc_raw[:60]}'. "
                f"Se omitió esta fila — escribinos para soportarlo."))

        return result
