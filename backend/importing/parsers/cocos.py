"""Parser de Cocos Capital — formato CSV oficial.

Cómo bajar el archivo (referencia para el wizard):
    1. Entrar a https://app.cocos.capital
    2. Ir a Actividad → Movimientos
    3. Seleccionar el rango (típicamente un año) y descargar el CSV

Estructura del CSV (semicolon-separated, decimal con coma, miles con punto):

    nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;tipoOperacion;
    instrumento;moneda;mercado;cantidad;precio;montoBruto;comision;ddmm;iva;
    otros;total

Tipos de operación mapeados al modelo Rendi (ver _resolve_op: exacto + patrón):

    Cocos                              → Rendi    Notas
    ─────────────────────────────────────────────────────────────────────
    Compra / Compra Trading            → COMPRA    Equity buy
    Venta / Venta Trading              → VENTA     Equity sell
    Compra / Venta Dolar Mep           → COMPRA/VENTA   Forzamos moneda=USD
    Compra / Venta Registracion        → COMPRA/VENTA   Bono dólar-MEP (compra
                                         ARS + venta USD del mismo bono → neto 0,
                                         es conversión de moneda). Moneda por fila.
    (Liq/Liquidacion) Suscripcion Fci  → COMPRA    Ticker del instrumento (FCI)
    (Liq/Liquidacion) Rescate Fci      → VENTA     Ticker del instrumento (FCI)
    Recibo De Cobro [Dolares]          → DEPOSITO  Cash in (ARS o USD por columna)
    Orden De Pago                      → RETIRO    Cash out
    Dividendos                         → DIVIDENDO Sin asset (el CSV no lo dice)
    Nota De Credito Conversion         → DEPOSITO  Ajuste/conversión

    El match es por patrón, así que las variantes de Cocos (sufijos "Dolares"/
    "Usd", abreviatura "Liq", etc.) se reconocen sin tener que enumerarlas todas.

Tipos que skipeamos silenciosamente (no aportan cash al portfolio):
    DIVIDENDOS EN ESPECIE — el USD real entra después como "Nota De Credito
                            Conversion", evitamos doble-conteo.

Particularidades:
- `cantidad` puede venir con signo (negativo en ventas) — tomamos abs() y el
  tipo de operación define la dirección.
- `montoBruto` es el bruto antes de fees; `total` es el neto. Para trades
  usamos `montoBruto` (gross) y la suma de fees por separado; para cash
  flows usamos `total` (neto).
- Fees = |comision| + |ddmm| + |iva| + |otros|.
- Para `Dividendos` en pesos, el CSV no indica qué activo pagó → asset queda
  vacío (cash dividend al broker).
"""
from __future__ import annotations
import csv
import io
import re
from typing import List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError
from ..maturity import is_bond_like_name, maturity_from_name, synth_letra_ticker


# Headers requeridos para detectar formato Cocos. Si al menos 3 de estos
# aparecen, asumimos que es un export Cocos válido.
_REQUIRED_HEADERS = {"nroticket", "fechaejecucion", "tipooperacion", "instrumento"}

# Mapping de tipoOperacion (lowercase) → tipo Rendi canónico.
_OP_MAP = {
    "compra":                      "COMPRA",
    "compra trading":              "COMPRA",
    "compra dolar mep":            "COMPRA",
    "venta":                       "VENTA",
    "venta trading":               "VENTA",
    "venta dolar mep":             "VENTA",
    "liquidacion suscripcion fci": "COMPRA",
    "liquidacion rescate fci":     "VENTA",
    "recibo de cobro":             "DEPOSITO",
    "orden de pago":               "RETIRO",
    "dividendos":                  "DIVIDENDO",
    "nota de credito conversion":  "DEPOSITO",
}

# Tipos reconocidos pero que skipeamos (evitar doble conteo / ruido). El caso
# "dividendos/renta en especie" ya NO se skipea en bloque: se discrimina en
# parse() según el instrumento (USD/acciones en especie → skip; pesos → ingreso),
# porque había maduraciones de bonos acreditadas "en especie" por millones de
# pesos que se estaban perdiendo.
_OP_SKIP: set = set()


def _resolve_op(tipo: str) -> Optional[str]:
    """tipoOperacion (lowercase, stripped) → tipo canónico de Rendi, o None si no
    se reconoce.

    Primero intenta el match EXACTO (_OP_MAP, explícito y rápido) y, si no, cae a
    PATRONES. Cocos usa variantes del mismo tipo que rompían el match exacto:
    sufijos de moneda ("Recibo De Cobro Dolares", "Liq Suscripcion Fci Usd"),
    abreviaturas ("Liq" vs "Liquidacion") y la maniobra dólar-MEP con bonos
    ("Compra/Venta Registracion"). El patrón cubre las que vengan en el futuro.
    """
    if tipo in _OP_MAP:
        return _OP_MAP[tipo]
    # Dividendos PRIMERO (antes que las notas de crédito/débito genéricas, así
    # "Nota Credito Dividendos ARS" cae como dividendo y no como depósito).
    if "dividendo" in tipo:
        return "DIVIDENDO"
    # Renta (cupón) y/o amortización de bonos y LECAPs = ingreso de caja. Sin
    # esto, "Renta Y Amortizacion" (maduración/amortización) se dropeaba y se
    # perdían millones de pesos de ingresos para carteras de bonos.
    if "amortizacion" in tipo or tipo.startswith("renta"):
        return "DIVIDENDO"
    if tipo.startswith("recibo de cobro"):    # incluye "...dolares"
        return "DEPOSITO"
    if tipo.startswith("orden de pago"):
        return "RETIRO"
    if "suscripcion fci" in tipo:             # liq/liquidacion suscripcion fci [usd]
        return "COMPRA"
    if "rescate fci" in tipo:                 # liq/liquidacion rescate fci [usd]
        return "VENTA"
    if "registracion" in tipo:
        # Maniobra dólar-MEP/CCL con un bono dual: se "compra" el bono en pesos y
        # se "vende" en dólares el mismo día (neto CERO como tenencia) — es una
        # CONVERSIÓN de moneda, no un trade de activo. La tratamos como flujo de
        # caja: la compra es plata que sale (RETIRO en ARS), la venta plata que
        # entra (DEPOSITO en USD). Sin esto, el ruteo por moneda partía las dos
        # patas en brokers distintos y quedaba una tenencia FANTASMA del bono.
        return "DEPOSITO" if tipo.startswith("venta") else "RETIRO"
    if "caucion" in tipo:
        # Caución colocadora: "contado/apertura" saca plata (la prestás) y
        # "término/cierre" la devuelve con interés. La tratamos como flujo de
        # caja por el signo del par (el neto es el interés ganado). Sin esto la
        # fila se dropeaba y el saldo no cuadraba.
        return "DEPOSITO" if ("termino" in tipo or "cierre" in tipo) else "RETIRO"
    if "nota" in tipo and "credito" in tipo:
        # Notas de crédito (devoluciones, ajustes, conversiones cable) = cash in.
        return "DEPOSITO"
    if "nota" in tipo and ("debito" in tipo or "débito" in tipo):
        # Notas de débito (impuestos Bienes Personales / Ganancias, ajustes) = cash out.
        return "FEE"
    if tipo.startswith("compra"):             # compra dolar mep / trading / etc.
        return "COMPRA"
    if tipo.startswith("venta"):
        return "VENTA"
    return None

# Ticker entre paréntesis al final de instrumento: 'CEDEAR TESLA, INC. (TSLA)' → 'TSLA'
_TICKER_RX = re.compile(r'\(([A-Z0-9.]+)\)\s*$')


def _strip(s) -> str:
    return (s or "").strip()


def _norm_header(h: str) -> str:
    """Lowercase + sin tildes + sin espacios para comparar headers."""
    if not h:
        return ""
    s = (h.strip().lower()
            .replace("ó", "o").replace("í", "i").replace("á", "a")
            .replace("é", "e").replace("ú", "u").replace("ñ", "n"))
    return s.replace(" ", "")


def _parse_date_ddmmyyyy(s: str) -> Optional[str]:
    """'06-01-2026' → '2026-01-06'. None si no parsea."""
    s = (s or "").strip()
    m = re.match(r'^(\d{2})[-/](\d{2})[-/](\d{4})$', s)
    if not m:
        return None
    d, mo, y = m.groups()
    return f"{y}-{mo}-{d}"


def _extract_ticker(instrumento: str) -> Optional[str]:
    """Saca el ticker que aparece entre paréntesis al final de instrumento.
    Devuelve None si no hay paréntesis o el contenido no parece ticker."""
    if not instrumento:
        return None
    m = _TICKER_RX.search(instrumento.upper())
    return m.group(1) if m else None


def _clean_ar_number(s: str) -> str:
    """Normaliza un número en formato AR estricto a formato estándar:

       Convención AR: '.' = miles, ',' = decimal (cualquier cantidad de dígitos).

       '1.948.815'     → '1948815'
       '-1.557.122,07' → '-1557122.07'
       '-7.049,7'      → '-7049.7'
       '-800,688'      → '-800.688'   (3 decimales — Cocos los usa)
       '2.723,4286'    → '2723.4286'  (4 decimales — precio FCI)
       '41.580'        → '41580'      (Cocos nunca usa decimal sin coma)
       '0,86'          → '0.86'
       '100'           → '100'
       ''              → ''

    Diseñada para CSV Cocos exclusivamente — NO usar para parsear en-US.
    """
    if not s:
        return s
    s = s.strip()
    negative = s.startswith("-")
    if negative:
        s = s[1:]
    # AR estricto: si hay coma, es decimal (cualquier nro de dígitos). Los
    # puntos son siempre miles. Si no hay coma, no hay decimal.
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(".", "")
    return ("-" + s) if negative else s


def _abs_number_str(s: str) -> str:
    """'-1.557,07' → '1557.07'. Pasa por _clean_ar_number primero."""
    cleaned = _clean_ar_number(s)
    return cleaned[1:] if cleaned.startswith("-") else cleaned


def _sum_fees(*raw_values: str) -> str:
    """Suma valores en formato AR (todos como abs) y devuelve string limpio."""
    total = 0.0
    for v in raw_values:
        if not v:
            continue
        cleaned = _clean_ar_number(v)
        try:
            total += abs(float(cleaned))
        except (ValueError, TypeError):
            continue
    # Devolvemos siempre con 2 decimales si hay valor, sino "0"
    return f"{total:.2f}" if total else "0"


def _safe_div_str(num_str: str, den_str: str) -> str:
    """Computa num/den como float y devuelve string limpio. Sirve para
    derivar precio=monto/qty evitando la ambigüedad de la columna precio del
    CSV de Cocos. Devuelve "" si no parsea o den es 0.

       _safe_div_str('762560', '280') → '2723.4285714285716'
       _safe_div_str('1948815', '193057.1677') → '10.094497..."
    """
    if not num_str or not den_str:
        return ""
    try:
        n = float(num_str)
        d = float(den_str)
        if d == 0:
            return ""
        return repr(n / d)
    except (ValueError, TypeError):
        return ""


class CocosParser(Parser):
    format_id = "cocos"
    display_name = "Cocos Capital"
    is_supported = True
    platform = "cocos"
    platform_label = "Cocos Capital"
    export_label = "Actividad → Movimientos"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_norm_header(h) for h in headers}
        return len(_REQUIRED_HEADERS & norm) >= 3

    def template_csv(self) -> str:
        # Ejemplo con filas representativas de cada tipo (anonimizado).
        return (
            "nroTicket;nroComprobante;fechaEjecucion;fechaLiquidacion;"
            "tipoOperacion;instrumento;moneda;mercado;cantidad;precio;"
            "montoBruto;comision;ddmm;iva;otros;total\n"
            "10001;100001;06-01-2026;07-01-2026;Compra;"
            "CEDEAR TESLA, INC. (TSLA);ARS;BYMA;10;41.580;-415.800;"
            "-1.871,1;-207,9;-436,59;0;-418.315,59\n"
            "10002;100002;26-01-2026;26-01-2026;Recibo De Cobro;;ARS;;;;"
            "100.000;0;0;0;0;100.000\n"
            "10003;100003;30-03-2026;30-03-2026;Dividendos;"
            "Peso argentino;ARS;;;;2.548,26;0;-2,5483;-0,5351;0;2.366,81\n"
        )

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        if content.startswith("﻿"):
            content = content[1:]
        try:
            reader = csv.DictReader(io.StringIO(content), delimiter=";")
            raw_headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(
                0, None, "FILE_UNREADABLE",
                f"No pudimos leer el archivo: {ex}",
            ))
            return result

        norm_to_orig = {_norm_header(h): h for h in raw_headers}
        present = _REQUIRED_HEADERS & set(norm_to_orig.keys())
        if len(present) < 3:
            result.parse_errors.append(RowError(
                0, None, "COCOS_HEADERS_MISMATCH",
                "Este archivo no parece un export oficial de Cocos. "
                "Bajalo desde https://app.cocos.capital → Actividad → Movimientos.",
            ))
            return result

        def G(row, norm_key: str) -> str:
            col = norm_to_orig.get(norm_key)
            return _strip(row.get(col, "")) if col else ""

        for idx, row in enumerate(reader, start=1):
            tipo_raw = G(row, "tipooperacion").lower()
            if not tipo_raw:
                continue  # fila vacía o sin tipo
            instrumento = G(row, "instrumento")
            moneda_raw = G(row, "moneda").upper()

            # Moneda no soportada (EXT = cable/exterior, "Concepto EXT migracion",
            # "Nota De Credito Conversion Cable"): montos marginales (centavos) que
            # no podemos representar en ARS/USD → skip silencioso.
            if moneda_raw not in ("ARS", "USD", ""):
                continue
            # Canje (split / cambio de especie por reorg): no mueve caja y la qty
            # la maneja una corporate action que no importamos → skip silencioso.
            if "canje" in tipo_raw:
                continue

            # "En especie": Cocos lo usa para DOS cosas muy distintas —
            #  (a) retención de un dividendo USD pagado en especie (instrumento
            #      "Dólar estadounidense", total chico/negativo): el cash real
            #      entra después como "Nota De Credito Conversion" → SKIP (evita
            #      doble conteo); idem dividendo en ACCIONES (instrumento = ticker).
            #  (b) amortización/maduración de un bono o LECAP acreditada EN PESOS
            #      (instrumento "Peso argentino", total grande positivo): es CASH
            #      real → la tomamos como ingreso (dividendo). Sin esto dropeábamos
            #      millones de pesos de maduraciones acreditadas "en especie".
            if "en especie" in tipo_raw:
                instr_low = instrumento.lower()
                if "peso argentino" in instr_low or not instrumento.strip():
                    tipo_rendi = "DIVIDENDO"
                else:
                    continue
            else:
                tipo_rendi = _resolve_op(tipo_raw)
            if tipo_rendi is None:
                # Tipo desconocido — lo reportamos pero seguimos con las demás.
                result.parse_errors.append(RowError(
                    idx, "tipoOperacion", "COCOS_OP_UNKNOWN",
                    f"Tipo de operación no soportado: '{G(row, 'tipooperacion')}'.",
                ))
                continue
            fecha = _parse_date_ddmmyyyy(G(row, "fechaejecucion"))
            comprobante = G(row, "nrocomprobante")

            # Currency: Compra/Venta Dolar Mep son siempre USD; el resto desde la columna.
            if "dolar mep" in tipo_raw:
                moneda = "USD"
            elif moneda_raw in ("ARS", "USD"):
                moneda = moneda_raw
            else:
                moneda = moneda_raw  # dejamos pasar para que el normalizer lo flagee

            # Asset (ticker)
            ticker = _extract_ticker(instrumento)
            if not ticker and is_bond_like_name(instrumento):
                # Letra/LECAP que Cocos exporta SIN ticker entre paréntesis
                # ("LT REP ARGENTINA CAP V11/11/24 $ CG"): sintetizamos un ticker
                # decodable desde la fecha de vencimiento del nombre. Si no, todas
                # caerían en un activo VACÍO (se mergean varias letras distintas en
                # una posición fantasma sin símbolo) y el sweep no podría cerrarlas.
                mat = maturity_from_name(instrumento)
                if mat:
                    ticker = synth_letra_ticker(mat)
            if tipo_rendi in ("DEPOSITO", "RETIRO", "DIVIDENDO", "INTERES", "FEE"):
                # Cash flows / dividendos / fees sin asset asociado (incluye
                # variantes como "Recibo De Cobro Dolares", sin instrumento, y las
                # notas de débito de impuestos, que sí traen ticker pero no son
                # una operación sobre el activo).
                ticker = None
            # asset_type hint: los CEDEARs de BYMA cotizan en pesos y se valúan por
            # su precio LOCAL (.BA), NO por la acción US del mismo ticker (el CEDEAR
            # de MELI ≈ US$14; la acción ≈ US$2.400). Cocos lo dice explícito en el
            # instrumento ("CEDEAR …"). Sin este hint la posición quedaría OTHER y se
            # valuaría como acción US → precio inflado.
            asset_type = "CEDEAR" if instrumento.strip().upper().startswith("CEDEAR") else ""

            # Monto y campos numéricos
            if tipo_rendi in ("COMPRA", "VENTA"):
                # Bruto (qty * price); fees por separado.
                monto = _abs_number_str(G(row, "montobruto"))
                qty = _abs_number_str(G(row, "cantidad"))
                # IMPORTANTE: NO usamos la columna `precio` del CSV — el formato
                # de Cocos es ambiguo (ej: '10.094,497' interpretado AR-strict
                # da 10094.497, pero el valor real para FCI es 10.094). El
                # persister hace `proceeds = unit_price × qty` en SELLs, y un
                # precio inflado x1000 genera P&L falso millonario.
                # Computamos precio = monto/qty → siempre consistente con monto.
                precio = _safe_div_str(monto, qty)
                fees = _sum_fees(
                    G(row, "comision"),
                    G(row, "ddmm"),
                    G(row, "iva"),
                    G(row, "otros"),
                )
            else:
                # Cash flow / dividendo: usamos `total` (ya descontado de fees)
                monto = _abs_number_str(G(row, "total"))
                qty = ""
                precio = ""
                fees = "0"

            # Notas: nro comprobante + flags útiles para auditoría
            notas_parts = []
            if comprobante:
                notas_parts.append(f"Comp. {comprobante}")
            if tipo_raw.endswith(" trading"):
                notas_parts.append("trading")
            if "dolar mep" in tipo_raw:
                notas_parts.append("MEP")
            if "fci" in tipo_raw:
                notas_parts.append("FCI")
            if tipo_raw == "nota de credito conversion":
                notas_parts.append("conversión")
            notas = " · ".join(notas_parts)

            data = {
                "fecha":      fecha or "",
                "tipo":       tipo_rendi,
                "broker":     "Cocos",
                "activo":     ticker or "",
                "cantidad":   qty,
                "precio":     precio,
                "monto":      monto,
                "monto_usd":  "",
                "tc":         "",
                "comisiones": fees,
                "moneda":     moneda,
                "asset_type": asset_type,  # "CEDEAR" → se valúa por .BA, no como acción US
                "notas":      notas,
            }
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        return result
