"""Normalizer: traduce RawRow → NormalizedTx.

Reglas:
- Determinístico. Nunca adivina datos financieros.
- Errores de normalización son no-fatales: se devuelven en `errors` y la fila
  se descarta, pero las demás filas siguen procesándose.
- Fechas: acepta YYYY-MM-DD, DD/MM/YYYY, YYYY/MM/DD. Cualquier otro formato → error.
- Montos: acepta decimal con coma o punto, separador de miles opcional.
- Tipos de operación: acepta los aliases definidos en schema.OP_TYPE_ALIASES.
"""
from __future__ import annotations
import re
from typing import List, Optional, Tuple
from .schema import (
    RawRow, NormalizedTx, RowError,
    OPERATION_TYPES, OP_TYPE_ALIASES, UNSUPPORTED_OP_HINTS,
    OP_BUY, OP_SELL, OP_DEPOSIT, OP_WITHDRAW, OP_DIVIDEND, OP_INTEREST,
    OP_TRANSFER, OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS, OP_FEE,
    AT_STOCK, AT_CEDEAR, AT_ETF, AT_CRYPTO, AT_FIAT, AT_BOND, AT_OTHER,
)
from .fci_map import resolve_fci_symbol


# Día y mes aceptan 1 o 2 dígitos (\d{1,2}): muchos exports / CSV editados en
# Excel traen "1/6/2026" o "2026-1-6" (sin zero-pad). _validate_ymd normaliza a
# 2 dígitos. Antes exigíamos \d{2} y esas filas (días/meses 1-9) fallaban con
# "Fecha inválida". El año sí queda en \d{4}.
_DATE_FORMATS = [
    re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$"),
    re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$"),
]
_DATE_DDMMYYYY = re.compile(r"^(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})$")


def parse_date(s: str) -> Optional[str]:
    """Devuelve la fecha en YYYY-MM-DD o None si no se puede parsear."""
    if not s:
        return None
    s = s.strip()
    for rx in _DATE_FORMATS:
        m = rx.match(s)
        if m:
            y, mo, d = m.groups()
            return _validate_ymd(y, mo, d)
    m = _DATE_DDMMYYYY.match(s)
    if m:
        d, mo, y = m.groups()
        return _validate_ymd(y, mo, d)
    return None


def _validate_ymd(y: str, mo: str, d: str) -> Optional[str]:
    try:
        yi, moi, di = int(y), int(mo), int(d)
        if not (1900 <= yi <= 2100 and 1 <= moi <= 12 and 1 <= di <= 31):
            return None
        return f"{yi:04d}-{moi:02d}-{di:02d}"
    except ValueError:
        return None


# Acepta formatos típicos: 1234, 1234.56, 1.234,56, -1234.56, 1.5e-05, 2.3E+10
_NUM_RE = re.compile(r"^-?[\d\.,]+(?:[eE][+-]?\d+)?$")


def parse_number(s: str) -> Optional[float]:
    """Acepta '1.234,56' (es-AR), '1,234.56' (en-US), '1234.56', '1234,56', '1234'.
    Devuelve None si está vacío o no parsea."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    if not _NUM_RE.match(s):
        return None
    has_comma, has_dot = "," in s, "." in s
    if has_comma and has_dot:
        # El último separador es el decimal; el otro es de miles
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        # Si la coma aparece como decimal (1 o 2 dígitos después)
        last = s.rfind(",")
        if len(s) - last - 1 in (1, 2):
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    # Si solo hay punto, asumimos que es decimal (no separador de miles)
    try:
        return float(s)
    except ValueError:
        return None


# Fallback por keyword cuando ni el tipo exacto ni el alias matchean.
# Cubre frases libres que el usuario o un broker pueden traer en castellano,
# ej.: "TRANSFERENCIA INGRESO BANCARIO", "RETIRO DE FONDOS A CUENTA", etc.
# Lista priorizada: el primer match gana (los más específicos primero).
_OP_KEYWORD_FALLBACKS = [
    # Ventas (tienen prioridad sobre las palabras genéricas como "DINERO")
    (("VENTA", "VENDID", "SOLD", "SELL", "RESCATE", "REDEMPTION", "REDEEM",
      "LIQUIDACION", "LIQUIDATION"), OP_SELL),
    # Compras (incluye reinversión de dividendos, suscripciones FCI)
    (("COMPRA", "COMPRAD", "BOUGHT", "BUY", "REINVEST", "DRIP",
      "SUSCRIPCION", "SUSCRIPCIÓN"), OP_BUY),
    # Conversiones (antes que ingreso/egreso porque pueden contener esas palabras)
    (("ARS_USD", "ARS→USD", "ARSUSD", "MEP_COMPRA", "DOLAR_MEP"), OP_FX_ARS_TO_USD),
    (("USD_ARS", "USD→ARS", "USDARS", "MEP_VENTA"), OP_FX_USD_TO_ARS),
    # Dividendos / cupones / amortizaciones de bonos
    (("DIVIDEN", "COUPON", "RENTA", "AMORTIZA"), OP_DIVIDEND),
    (("INTERES", "INTERÉS", "INTEREST", "STAKING", "REWARD", "EARN"), OP_INTEREST),
    # Cash flows (las más genéricas, al final)
    (("INGRESO", "DEPOSIT", "APORTE", "ACREDIT", "RECIB", "FUNDING", "TOPUP",
      "TOP_UP", "MONEYLINK_DEP"), OP_DEPOSIT),
    (("EGRESO", "RETIRO", "WITHDRAW", "EXTRACC", "ENVIAD", "MONEYLINK_W"), OP_WITHDRAW),
    # Comisiones / fees / impuestos
    (("COMISION", "COMISIÓN", "COMMISSION", "FEE", "CHARGE", "ARANCEL",
      "IMPUEST", "RETENC", "TAX", "MARGIN_INT", "BORROW_F"), OP_FEE),
    # Transferencias genéricas — quedan como TRANSFER y se re-clasifican
    # por signo del monto en normalize_rows().
    (("WIRE", "ACAT", "JOURNAL", "JNL", "TRANSF", "XFER"), OP_TRANSFER),
]


def _coerce_op_type(s: str) -> Optional[str]:
    if not s:
        return None
    key = s.strip().upper().replace(" ", "_")
    if key in OPERATION_TYPES:
        return key
    if key in OP_TYPE_ALIASES:
        return OP_TYPE_ALIASES[key]
    # Fallback por keyword: si contiene una raíz reconocida, asignar.
    for needles, op_type in _OP_KEYWORD_FALLBACKS:
        if any(n in key for n in needles):
            return op_type
    return None


# Heurísticas de asset_type. Conservadoras: si no estamos seguros, OTHER.
_CRYPTO_HINTS = {"BTC", "ETH", "USDT", "USDC", "SOL", "ADA", "BNB", "DOGE", "MATIC", "ARB",
                 "AVAX", "DOT", "LINK", "LTC", "XRP", "ATOM", "NEAR", "OP", "TRX"}
_FIAT_HINTS = {"USD", "ARS", "EUR", "BRL", "CLP", "MXN"}


def _is_known_ar_bond(symbol: str) -> bool:
    """True si el ticker es un bono/letra AR conocido. Import lazy con fallback
    (igual que rebuild.py): si el módulo de metadata no está, no rompemos."""
    try:
        from ai.ar_bonds_metadata import is_known_ar_bond
    except Exception:
        return False
    return bool(is_known_ar_bond(symbol))


def guess_asset_type(symbol: Optional[str]) -> str:
    if not symbol:
        return AT_OTHER
    s = symbol.strip().upper()
    if s in _CRYPTO_HINTS or s.endswith("USDT"):
        return AT_CRYPTO
    if s in _FIAT_HINTS:
        return AT_FIAT
    # Bonos/letras AR por ticker. Crítico para IEB, que NO etiqueta el tipo en su
    # export (asset_type='') → sin esto, AL30/GD30/etc. caían a OTHER y no recibían
    # el tratamiento de renta fija (guard de valuación, normalización de unidad,
    # reporting). El precio se resuelve por ticker igual, pero el tipo importa.
    if _is_known_ar_bond(s):
        return AT_BOND
    return AT_OTHER  # Sin más contexto del broker, no asumimos STOCK/CEDEAR


def _norm_currency(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    c = s.strip().upper()
    if c in {"USD", "USDT"}:
        return c
    if c in {"ARS", "$ARS", "PESOS"}:
        return "ARS"
    return None


def normalize_rows(raw_rows: List[RawRow]) -> Tuple[List[NormalizedTx], List[RowError]]:
    """Convierte filas crudas a NormalizedTx. Devuelve también los errores
    no-fatales (filas que no pudimos normalizar). Las filas con error NO se
    incluyen en el output normalizado."""
    out: List[NormalizedTx] = []
    errors: List[RowError] = []

    for row in raw_rows:
        d = row.data
        ridx = row.row_index

        # Fecha
        date = parse_date(d.get("fecha", ""))
        if not date:
            errors.append(RowError(ridx, "fecha", "INVALID_DATE",
                                   f"Fecha inválida: '{d.get('fecha', '')}'. Formatos aceptados: YYYY-MM-DD, DD/MM/YYYY."))
            continue

        # Tipo
        op_raw = d.get("tipo", "")
        op_type = _coerce_op_type(op_raw)
        if not op_type:
            # Detectar si es una operación reconocida-pero-no-soportada
            # (stock split, spin-off, merger, caución, etc.) y dar un mensaje
            # accionable en vez de UNKNOWN_OP_TYPE genérico.
            key = (op_raw or "").strip().upper().replace(" ", "_").replace("-", "_")
            unsupported_msg = UNSUPPORTED_OP_HINTS.get(key)
            # Match parcial — busca si el key contiene alguna palabra clave
            if not unsupported_msg:
                for hint_key, hint_msg in UNSUPPORTED_OP_HINTS.items():
                    if hint_key in key or key in hint_key:
                        unsupported_msg = hint_msg
                        break
            if unsupported_msg:
                errors.append(RowError(ridx, "tipo", "OP_NOT_SUPPORTED", unsupported_msg))
            else:
                errors.append(RowError(ridx, "tipo", "UNKNOWN_OP_TYPE",
                                       f"Tipo de operación desconocido: '{op_raw}'. "
                                       f"Si tu broker usa otro nombre, mapealo a "
                                       f"COMPRA/VENTA/DEPOSITO/RETIRO/DIVIDENDO/etc en el wizard."))
            continue

        # Re-clasificación de TRANSFER ambiguo (Wire Transfer, ACAT, Journal)
        # según el signo del monto: positivo → DEPOSIT, negativo → WITHDRAW.
        # Si el monto es cero o no se puede determinar, queda como TRANSFER y
        # el validator lo rechaza con TRANSFER_NOT_SUPPORTED.
        if op_type == OP_TRANSFER:
            raw_monto = d.get("monto", "") or d.get("monto_usd", "")
            try:
                monto_val = parse_number(str(raw_monto)) if raw_monto != "" else None
            except Exception:
                monto_val = None
            if monto_val is not None:
                if monto_val > 0:
                    op_type = OP_DEPOSIT
                elif monto_val < 0:
                    op_type = OP_WITHDRAW
                    # Para WITHDRAW el motor espera monto positivo (el signo
                    # negativo solo nos sirvió para la clasificación). Vamos a
                    # tomar el valor absoluto al parsearlo abajo.
                    d = {**d, "monto": str(abs(monto_val))}

        broker = (d.get("broker") or "").strip()
        if not broker:
            errors.append(RowError(ridx, "broker", "MISSING_BROKER",
                                   "Falta el broker en esta fila."))
            continue

        asset_raw = (d.get("activo") or "").strip().upper() or None
        # Símbolo de CLASE de acción US con espacio ('BRK B', Schwab/IBKR) → guión
        # ('BRK-B', forma canónica de yfinance). Sin esto el símbolo no cotiza (el
        # gate _SYMBOL_RE de /api/prices lo descarta y el ' '.join de snapshots lo
        # parte). No tocar FCI ('FCI:...'). Los tickers reales no tienen espacios.
        if asset_raw and not asset_raw.startswith("FCI:") and " " in asset_raw:
            asset_raw = re.sub(r"\s+", "-", asset_raw)

        # Helper local para parsear cada campo numérico y registrar errores
        row_errors: List[RowError] = []

        def _num(field: str) -> Optional[float]:
            raw = d.get(field, "")
            if raw is None or raw == "":
                return None
            n = parse_number(raw)
            if n is None:
                row_errors.append(RowError(ridx, field, "INVALID_NUMBER",
                                           f"Valor numérico inválido en '{field}': '{raw}'."))
            return n

        quantity = _num("cantidad")
        unit_price = _num("precio")
        gross_amount = _num("monto")
        usd_amount = _num("monto_usd")
        tc = _num("tc")
        fees = _num("comisiones") or 0.0

        if row_errors:
            errors.extend(row_errors)
            continue

        currency = _norm_currency(d.get("moneda"))
        notes = (d.get("notas") or "").strip() or None
        # asset_name: nombre completo del instrumento si el parser lo pasa (ej.
        # Cocos manda "BONO TESORO ... V.14/02/25 (T2X5)"). Sirve para derivar el
        # vencimiento de bonos cuyo ticker no lo codifica (sweep de vencimientos).
        asset_name = (d.get("asset_name") or "").strip() or None

        # asset_type: el parser puede pasar un hint explícito en data["asset_type"]
        # (útil para Schwab donde "ETH" significa Grayscale Ethereum Mini ETF,
        # no la crypto raw que la heurística genérica detectaría). Si no hay
        # hint, caemos al guess_asset_type por símbolo.
        asset_type_hint = (d.get("asset_type") or "").strip().upper()
        if asset_type_hint in {"STOCK", "CEDEAR", "ETF", "CRYPTO", "FIAT", "BOND", "FUND", "OTHER"}:
            asset_type = asset_type_hint
        else:
            asset_type = guess_asset_type(asset_raw)

        # FCI propietarios: el parser emite el ticker CRUDO del broker (COCOA,
        # COCOACCA…) + asset_type=FUND. Lo traducimos al símbolo del catálogo
        # (FCI:<slug>) para que valúe con el VCP live, igual que un FCI cargado a
        # mano. Si el ticker no está en el mapa curado, queda crudo (= al costo,
        # sin regresión). Solo toca filas FUND, así nunca pisa un ticker normal.
        asset_symbol = asset_raw
        if asset_type == "FUND" and asset_raw:
            _fci_sym = resolve_fci_symbol(asset_raw)
            if _fci_sym:
                asset_symbol = _fci_sym

        # Construcción específica por op_type
        tx = NormalizedTx(
            row_index=ridx,
            date=date,
            broker=broker,
            operation_type=op_type,
            asset_symbol=asset_symbol,
            asset_name=asset_name,
            asset_type=asset_type,
            quantity=quantity,
            unit_price=unit_price,
            gross_amount=gross_amount,
            fees=fees or 0.0,
            currency=currency,
            settlement_currency=currency,
            notes=notes,
        )

        # Marca del parser: la fila aporta una posición pero el CSV no trae el
        # precio de compra (securities transferidas, p.ej. TDA→Schwab). El
        # pipeline la deriva al flujo de "estado inicial" (seed) en vez de
        # persistirla como compra normal.
        tx.cost_basis_pending = bool(d.get("_cost_basis_pending"))

        # Cierre por acción societaria a proceeds cero (ej. "Reducción de
        # capital" de Balanz): el validador debe aceptar el precio 0 de la VENTA
        # (que en general rechaza con MISSING_PRICE).
        tx.corporate_close = bool(d.get("_corporate_close"))

        # Transferencia/retiro del activo fuera de la cuenta (retiro de cripto de
        # un exchange, polvo→BNB): cierre a costo (P&L 0), no una venta. El
        # validador acepta su precio 0; el persister no bookea pérdida.
        tx.transfer_out = bool(d.get("_transfer_out"))

        # Fallback de monto para filas non-FX en CSVs con columnas separadas
        # por moneda (típico en Argentina: monto_ars + monto_usd). Si la fila
        # tiene monto_usd pero no monto, usamos monto_usd como el monto en
        # la moneda de la fila. Para FX no aplica — ahí ARS y USD son ambos
        # significativos por separado.
        if op_type not in (OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS):
            if tx.gross_amount is None and usd_amount is not None:
                tx.gross_amount = usd_amount
            # Para cash flows (DEPOSIT/WITHDRAW/DIVIDEND/INTEREST/FEE), si no
            # hay monto pero hay quantity * unit_price, calcularlo. Cubre CSVs
            # donde el broker pone "Quantity=cantidad de cash" + "Price=1".
            if (tx.gross_amount is None
                    and op_type in (OP_DEPOSIT, OP_WITHDRAW, OP_DIVIDEND,
                                     OP_INTEREST, OP_FEE)):
                if tx.quantity is not None and tx.unit_price is not None:
                    tx.gross_amount = tx.quantity * tx.unit_price
                elif tx.quantity is not None and tx.unit_price is None:
                    # Schwab/Fidelity típicamente ponen el monto en "Amount"
                    # sin precio — interpretamos quantity como el monto.
                    tx.gross_amount = tx.quantity
                    tx.quantity = None  # No es una compra, es cash directo
            # Para WITHDRAW, FEE: aceptar monto negativo como positivo
            # (algunos brokers exportan retiros como -100 en la columna monto).
            if (tx.gross_amount is not None and tx.gross_amount < 0
                    and op_type in (OP_WITHDRAW, OP_FEE)):
                tx.gross_amount = abs(tx.gross_amount)
            # Para DEPOSIT/DIVIDEND/INTEREST: si llegó negativo, lo convertimos
            # en WITHDRAW/FEE (el broker mezcla in y out en la misma columna).
            elif (tx.gross_amount is not None and tx.gross_amount < 0
                  and op_type in (OP_DEPOSIT, OP_DIVIDEND, OP_INTEREST)):
                tx.gross_amount = abs(tx.gross_amount)
                tx.operation_type = OP_WITHDRAW if op_type == OP_DEPOSIT else OP_FEE
                op_type = tx.operation_type

        # Auto-completar el triángulo (cantidad × precio = monto) para BUY/SELL
        # cuando el usuario aportó solo dos de los tres valores. Es matemática
        # determinística: equivale a lo que haría el usuario con una calculadora.
        # NO sobrescribe valores que el usuario ya proveyó — solo rellena vacíos.
        if op_type in (OP_BUY, OP_SELL):
            q, p, a = tx.quantity, tx.unit_price, tx.gross_amount
            if q and p and not a:
                tx.gross_amount = round(q * p, 8)
            elif q and a and not p:
                if q != 0:
                    tx.unit_price = round(a / q, 8)
            elif p and a and not q:
                if p != 0:
                    tx.quantity = round(a / p, 8)

            # tc de la compra (ARS/USD) para la vista "costo al dólar de la
            # compra": del CSV (columna 'tc'), o derivado monto_ARS/monto_usd.
            # Solo lotes en pesos (currency ARS) — el guard evita el tc≈1
            # espurio cuando el fallback de arriba igualó gross_amount=usd_amount
            # en un lote USD. Solo BUY crea fila en positions.
            if tc and tc > 0:
                tx.tc_compra = tc
            elif ((currency or "").upper() == "ARS"
                  and tx.gross_amount and usd_amount and usd_amount > 0):
                tx.tc_compra = round(tx.gross_amount / usd_amount, 8)

        # Para FX usamos los campos específicos (ars_amount = gross_amount, usd_amount, tc)
        # y los exponemos vía gross_amount (ARS) y unit_price (TC) por compactness;
        # el persister los lee así.
        if op_type in (OP_FX_ARS_TO_USD, OP_FX_USD_TO_ARS):
            # Triángulo FX: ars = usd × tc. Con dos de los tres, calculamos el tercero.
            # Determinístico — equivale a la calculadora del usuario.
            ars, usd, rate = gross_amount, usd_amount, tc
            if ars and rate and usd is None:
                if rate != 0:
                    usd = round(ars / rate, 8)
            elif usd and rate and ars is None:
                ars = round(usd * rate, 8)
            elif ars and usd and rate is None:
                if usd != 0:
                    rate = round(ars / usd, 8)

            if ars is None or usd is None or rate is None:
                errors.append(RowError(ridx, None, "MISSING_FX_FIELDS",
                                       "Una conversión necesita al menos dos de estos tres: "
                                       "'monto' (ARS), 'monto_usd' y 'tc'. Con dos, calculamos el tercero."))
                continue
            if ars <= 0 or usd <= 0 or rate <= 0:
                errors.append(RowError(ridx, None, "INVALID_FX",
                                       "Los valores de la conversión deben ser positivos."))
                continue
            tx.gross_amount = ars               # ARS
            tx.quantity = usd                   # USD (reusamos quantity)
            tx.unit_price = rate                # TC

        out.append(tx)

    return out, errors
