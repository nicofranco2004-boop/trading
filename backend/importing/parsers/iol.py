"""Parser de IOL (InvertirOnline) — "Movimientos Históricos".

Cómo bajar el archivo (paso a paso confirmado por usuarios de IOL):
    1. Iniciar sesión en IOL (invertironline.com o la app).
    2. Ir a Mi Cuenta → Movimientos → Detalle de Movimientos.
    3. Elegir fecha de inicio (desde que abrió la cuenta) y fecha actual.
    4. Abajo de todo: "Descargar movimientos históricos" → baja un .xls.

El archivo viene como .xls, pero NO es Excel binario: es una tabla HTML (un
<table>). El reader del pipeline (importing/excel.py: is_html_table /
html_table_to_csv) lo aplana a CSV antes de llegar acá, así que este parser
trabaja sobre texto CSV con las 14 columnas de IOL:

    Nro. de Mov. ; Nro. de Boleto ; Tipo Mov. ; Concert. ; Liquid. ; Est ;
    Cant. titulos ; Precio ; Comis. ; Iva Com. ; Otros Imp. ; Monto ;
    Observaciones ; Tipo Cuenta

`Tipo Mov.` embebe la operación Y el ticker entre paréntesis. Mapeo al modelo
de Rendi (ver _resolve_op):

    IOL `Tipo Mov.`                         → Rendi     Notas
    ─────────────────────────────────────────────────────────────────────────
    Compra(GGAL) / Compra(GGALD)            → COMPRA     Equity/CEDEAR/bono buy
    Venta(GGAL) / Venta(GGALD)              → VENTA      Equity/CEDEAR/bono sell
    Suscripción FCI(PRREMIB)                → COMPRA     Alta de cuotapartes FCI
    Rescate FCI(PRREMIB)                    → VENTA      Baja de cuotapartes FCI
    Pago de Dividendos(EDN)                 → DIVIDENDO  Dividendo cash
    Pago de Renta(AL30)                     → DIVIDENDO  Cupón de bono
    Pago de Amortización(AL30)              → DIVIDENDO  Amortización de bono
    Crédito                                 → INTERES    Interés/acreditación de cuenta
    Depósito de Fondos - Transf... BANCO X  → DEPOSITO   Cash in
    Extracción de Fondos - Transf... BANCO  → RETIRO     Cash out
    Transferencia de Titulos IN/OUT - (X)   → (skip)     Necesita cost basis manual

Moneda: el .xls de IOL trae la moneda en la columna `Tipo Cuenta`
("Cuenta … Pesos" / "Cuenta … Dólares"). La usamos como fuente principal; el
sufijo "US$" en el ticker ("Pago de Dividendos(EDN US$)") fuerza USD. Default
ARS (el broker IOL es ARS y la mayoría de las filas liquidan en pesos).

    OJO (anonimización): en los ejemplos que recibimos, `Tipo Cuenta` venía
    aplastado a "Cuenta Anonimizada", así que NO pudimos validar las etiquetas
    exactas de moneda contra datos reales. El matching es liberal (busca
    "dolar"/"u$s"/"usd" → USD; "peso"/"ars" → ARS). Si un export real usa otra
    etiqueta, agregala en _CUENTA_USD_HINTS / _CUENTA_ARS_HINTS.

Sufijo dólar/cable (D/C): IOL nombra la pata en dólar-MEP/cable con un sufijo
"D"/"C" sobre el ticker base (GGAL→GGALD/GGALC, AL30→AL30D/AL30C, NU→NUD). Es
el MISMO subyacente, así que consolidamos al ticker base para que valúe bien.
PERO hay CEDEARs/cripto que terminan en C/D de forma legítima (AMD, GOLD,
INTC, YPFD, BTC…): esos NO se tocan (_KNOWN_CD_TICKERS, espejo de tickers.js).

Conducto dólar-MEP (_detect_iol_conduits): cuando un bono se usa como PUENTE
para convertir PESOS↔DÓLARES (dólar bolsa), IOL lo exporta como una pata en
PESOS (ticker base) + una pata en DÓLARES (ticker con sufijo C/D) del MISMO
papel, MISMA cantidad, dirección opuesta, MISMO DÍA; la pata dólar viene partida
en 2 filas (monto USD real + un residual en pesos = el impuesto). Si se toma
cada pata como un trade real del bono, queda una posición FANTASMA (ej. AL30
neto −169), P&L basura (el FIFO cruza patas ARS vs USD) y caja fabricada. Por
eso lo colapsamos en UNA conversión FX (FX_ARS_USD / FX_USD_ARS) — sin posición
del bono y sin inflar 'capital aportado' (un DEPOSITO/RETIRO sí lo inflaría); el
residual en pesos se DESCARTA. NO se tocan los round-trips en una sola moneda
(canje D↔C o swing D↔D, ambos USD: quedan como compra/venta reales que netean
por FIFO), ni una pata dólar SUELTA (tenencia genuina en USD).

FCI: las suscripciones/rescates llevan asset_type='FUND', así el normalizer las
mapea a 'FCI:<slug>' (importing/fci_map) y cotizan al VCP live cuando el ticker
está confirmado; si no, quedan al costo (sin inventar precio).

Números: pasamos cantidad/precio/monto como strings crudos — el normalizer
(parse_number) tolera tanto formato es-AR ('1.234,56') como en-US ('1,234.56'),
así que no asumimos un separador decimal acá. Las comisiones (Comis. + Iva Com.
+ Otros Imp.) sí las sumamos, con un parser local que tolera ambos formatos.

Convención de montos (igual que Cocos):
- COMPRA/VENTA/FCI: pasamos `cantidad` y `precio`; dejamos `monto` vacío para
  que el normalizer arme el bruto = cantidad × precio (la columna `Monto` de IOL
  incluye/descuenta fees → no es el bruto). Fees aparte en `comisiones`.
- DEPOSITO/RETIRO/DIVIDENDO/INTERES: usamos `Monto` como el cash neto; sin
  cantidad/precio y con comisiones = 0 (no double-count de fees).
"""
from __future__ import annotations
import csv
import io
import re
from typing import List, Optional
from .base import Parser
from ..schema import ParseResult, RawRow, RowError


# Headers que identifican un export de IOL. Si aparecen al menos 3, asumimos IOL.
_REQUIRED_HEADERS = {"tipomov", "canttitulos", "concert", "monto", "nrodeboleto"}

# Tickers conocidos que terminan en C/D de forma LEGÍTIMA (no son la pata dólar
# de otro). Espejo de los símbolos de frontend/src/utils/tickers.js que terminan
# en C/D — para no estropear AMD→AM, GOLD→GOL, INTC→INT, etc. Si tickers.js suma
# uno nuevo terminado en C/D, agregalo acá.
_KNOWN_CD_TICKERS = {
    "AMC", "AMD", "BAC", "BBD", "BND", "BTC", "CAC", "CARC", "CRWD", "DBC",
    "EGLD", "ETC", "FBTC", "GBTC", "GD", "GILD", "GLD", "GOLD", "HD", "HOOD",
    "INTC", "JD", "KLAC", "LCID", "LQD", "LTC", "MATIC", "MCD", "MPC", "NOC",
    "PDD", "SAND", "SSEC", "TSMC", "USDC", "WBD", "WFC", "WLD", "XLC", "YPFD",
    "ZEC",
}

# Pistas de moneda en la columna Tipo Cuenta.
_CUENTA_USD_HINTS = ("dolar", "u$s", "us$", "usd", "exterior", "cable", "ccl", "mep")
_CUENTA_ARS_HINTS = ("peso", "ars", "comitente $", "pesos")


def _deaccent(s: str) -> str:
    return (s.replace("ó", "o").replace("í", "i").replace("á", "a")
             .replace("é", "e").replace("ú", "u").replace("ñ", "n")
             .replace("Ó", "O").replace("Í", "I").replace("Á", "A")
             .replace("É", "E").replace("Ú", "U").replace("Ñ", "N"))


def _norm_header(h: str) -> str:
    """Lowercase + sin tildes + sin espacios ni puntos para comparar headers.
    'Cant. titulos' → 'canttitulos', 'Tipo Mov.' → 'tipomov'."""
    if not h:
        return ""
    s = _deaccent(h.strip().lower())
    return re.sub(r"[^a-z0-9]", "", s)


def _strip(s) -> str:
    return (s or "").strip()


_NUM_RE = re.compile(r"^-?[\d.,]+$")


def _num(s: str) -> float:
    """Parsea un número en formato es-AR ('1.234,56') o en-US ('1,234.56') a
    float. Devuelve 0.0 si está vacío o no parsea. Espejo simplificado de
    normalizer.parse_number (no lo importamos: los parsers son upstream)."""
    s = _strip(s)
    if not s or not _NUM_RE.match(s):
        return 0.0
    has_comma, has_dot = "," in s, "." in s
    if has_comma and has_dot:
        if s.rfind(",") > s.rfind("."):     # coma es el decimal
            s = s.replace(".", "").replace(",", ".")
        else:                                # punto es el decimal
            s = s.replace(",", "")
    elif has_comma:
        last = s.rfind(",")
        if len(s) - last - 1 in (1, 2):      # coma decimal (1-2 dígitos)
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_date(s: str) -> Optional[str]:
    """Fecha de IOL → ISO 'YYYY-MM-DD'. IOL exporta DD/MM/YYYY ('05/01/2025') o
    DD/MM/YY ('12/06/26', año de 2 dígitos → 20YY). Tolera '-' como separador y
    fechas ya en ISO. None si no parsea."""
    s = _strip(s)
    if not s:
        return None
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2}|\d{4})$", s)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2:                       # 'YY' → '20YY' (movimientos recientes)
            y = f"20{y}"
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):   # ya ISO
        return s
    return None


# Ticker entre paréntesis: 'Compra(GGALD)' → 'GGALD'; 'Pago de Renta(AL30 US$)' → 'AL30 US$'.
_PAREN_RX = re.compile(r"\(([^()]+)\)")


def _extract_raw_ticker(tipo_mov: str) -> Optional[str]:
    """Saca el contenido del ÚLTIMO paréntesis del Tipo Mov. None si no hay."""
    matches = _PAREN_RX.findall(tipo_mov or "")
    return matches[-1].strip() if matches else None


def _has_usd_suffix(raw_ticker: str) -> bool:
    """True si el ticker trae el sufijo de dólar 'US$' / 'U$S' (ej: 'EDN US$')."""
    t = raw_ticker.upper().replace(" ", "")
    return t.endswith("US$") or t.endswith("U$S")


def _clean_ticker(raw_ticker: str, is_fci: bool = False) -> str:
    """Normaliza el ticker del Tipo Mov. al símbolo base de Rendi:
       - quita el sufijo de moneda 'US$' / 'U$S'
       - quita el sufijo dólar/cable 'D'/'C' (consolida la pata dólar con el
         subyacente), salvo que sea un ticker conocido que legítimamente termina
         en C/D (AMD, GOLD, INTC, …).
    NO quita la D/C cuando:
       • es un FCI (`is_fci`): su ticker no es una pata dólar-MEP y suele terminar
         en D/C legítimamente (IOLDOLD, …) → truncarlo lo desalinea de la foto;
       • el ticker tiene un punto (BA.C, BR.K…): el punto ya marca la clase y la
         letra final es parte del símbolo, no un sufijo dólar/cable.
    """
    t = raw_ticker.strip().upper()
    t = re.sub(r"\s*(US\$|U\$S)$", "", t).strip()
    if is_fci or "." in t:
        return t
    if len(t) >= 3 and t[-1] in ("D", "C") and t not in _KNOWN_CD_TICKERS:
        t = t[:-1]
    return t


# Resolución de operación: prefijo del Tipo Mov. (lo de antes del paréntesis,
# deaccented + lowercase) → tipo canónico de Rendi, o None si no se reconoce.
def _resolve_op(tipo_mov: str) -> Optional[str]:
    head = _PAREN_RX.split(tipo_mov, 1)[0]        # texto antes del 1er paréntesis
    p = _deaccent(head.strip().lower())
    if "transferencia de titulos" in p:
        return None                               # necesita cost basis manual → skip
    if p.startswith("compra"):
        return "COMPRA"
    if p.startswith("venta"):
        return "VENTA"
    if "suscripcion" in p:                        # Suscripción FCI → alta de cuotapartes
        return "COMPRA"
    if "rescate" in p:                            # Rescate FCI → baja de cuotapartes
        return "VENTA"
    if "dividendo" in p or "renta" in p or "amortizacion" in p:
        return "DIVIDENDO"
    if "credito" in p:                            # acreditación de interés de cuenta
        return "INTERES"
    if "deposito" in p:
        return "DEPOSITO"
    if "extraccion" in p:
        return "RETIRO"
    return None


# Operaciones que NO mueven cash ni tenencia con cost basis claro → no se
# importan (mejor avisar que adivinar). Devuelve (code, mensaje) o None.
def _skip_reason(tipo_mov: str) -> Optional[tuple]:
    p = _deaccent((tipo_mov or "").lower())
    if "transferencia de titulos" in p:
        return ("IOL_TITLE_TRANSFER",
                "Transferencia de títulos — no se importa automáticamente porque no "
                "trae el cost basis. Cargá la posición a mano desde Cartera.")
    return None


def _has_dollar_suffix(raw_ticker: Optional[str]) -> bool:
    """True si el ticker es una pata DÓLAR del conducto (sufijo C/D que
    _clean_ticker consolida sobre el subyacente), NO un ticker que legítimamente
    termina en C/D (AMD, GOLD, INTC…). Mismo criterio que _clean_ticker."""
    if not raw_ticker:
        return False
    t = re.sub(r"\s*(US\$|U\$S)$", "", raw_ticker.strip().upper()).strip()
    return len(t) >= 3 and t[-1] in ("D", "C") and t not in _KNOWN_CD_TICKERS


def _days_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    if not a or not b:
        return None
    from datetime import date as _date
    try:
        return abs((_date.fromisoformat(a) - _date.fromisoformat(b)).days)
    except ValueError:
        return None


def _detect_iol_conduits(rows: List[dict], G) -> tuple:
    """Detecta la maniobra dólar-MEP de IOL (un bono como PUENTE para convertir
    PESOS↔DÓLARES) y la colapsa en UNA conversión FX, en vez de dos trades del
    bono que dejaban posición FANTASMA (AL30 neto −169), P&L basura y cash
    fabricado.

    Estructura real (verificada contra el export): la conversión es una pata en
    PESOS (fila ÚNICA del ticker base, ej. Compra(AL30)) + una pata en DÓLARES
    PARTIDA en 2 filas (el monto USD real + un residual en pesos = el impuesto,
    MISMO Nro. de Boleto). Mismo papel, MISMA cantidad, dirección OPUESTA, MISMO
    DÍA. La firma de una conversión genuina es exactamente esa: cruza MONEDA
    (pesos↔dólares) y la pata dólar está partida.

    Tratamiento:
      • El residual en pesos de la pata dólar se DESCARTA.
      • La pata pesos + la pata dólar USD se colapsan en UN FX_ARS_USD /
        FX_USD_ARS (sin posición del bono, sin inflar 'capital aportado' como
        haría un DEPOSITO/RETIRO). El persister mueve el cash pesos↔dólares.

    Lo que NO se toca (clave para no romper trades reales):
      • Round-trips en UNA sola moneda (canje D↔C o swing D↔D, ambos USD): quedan
        como compra/venta reales y netean por FIFO con su P&L. Acá NO hay
        conversión de moneda.
      • Una pata dólar SUELTA (sin contraparte pesos) → tenencia genuina en USD.
      • Cualquier trade en pesos normal.
    Guardas para no sobre-colapsar (audit 2026-06-25): exigimos cruce de MONEDA
    (no D↔D/D↔C), que la pata dólar esté PARTIDA (residual mismo boleto) y MISMO
    DÍA — así una compra-pesos + venta-dólar genuinas a días de distancia, o un
    swing USD, no se fusionan por error.

    Devuelve (fx, fee, drop):
      fx:   {row_index → (fx_op, ars_amount, usd_amount)}  en la fila carrier (pesos)
      fee:  set(row_index)  residuales en pesos de patas dólar → emitir como FEE
            (es un costo real; descartarlos inflaría el cash en ARS)
      drop: set(row_index)  la pata dólar USD ya colapsada dentro del FX
    """
    legs = []   # toda fila COMPRA/VENTA con sus atributos
    for i, row in enumerate(rows, start=1):
        tipo_mov = _strip(G(row, "tipomov"))
        op = _resolve_op(tipo_mov)
        if op not in ("COMPRA", "VENTA"):
            continue
        raw = _extract_raw_ticker(tipo_mov)
        if not raw:
            continue
        qty = _num(G(row, "canttitulos"))
        if qty <= 0:
            continue
        cuenta = _deaccent(G(row, "tipocuenta").lower())
        _head = _deaccent(_PAREN_RX.split(tipo_mov, 1)[0].strip().lower())
        _is_fci = "suscripcion" in _head or "rescate" in _head
        legs.append({
            "idx": i, "base": _clean_ticker(raw, is_fci=_is_fci), "qty": qty,
            "dir": "C" if op == "COMPRA" else "V",
            "date": _parse_date(G(row, "concert")),
            "usd": _has_usd_suffix(raw) or any(h in cuenta for h in _CUENTA_USD_HINTS),
            "dc": _has_dollar_suffix(raw),
            "boleto": _strip(G(row, "nrodeboleto")),
            "cash": abs(_num(G(row, "monto"))),
        })

    def _same_boleto_residual(usd_leg):
        """La pata dólar USD está PARTIDA si hay otra fila D/C en ARS del mismo
        papel y mismo Boleto (el residual = el impuesto)."""
        b = usd_leg["boleto"]
        if not b or b == "0":
            return None
        for o in legs:
            if (o["idx"] != usd_leg["idx"] and o["boleto"] == b and o["dc"]
                    and not o["usd"] and o["base"] == usd_leg["base"]):
                return o
        return None

    fx: dict = {}
    fee = set()    # residuales en pesos de patas dólar → FEE (son costo real, no se pierden)
    drop = set()   # pata dólar USD ya fundida en un FX
    used = set()
    # Conversión PESOS↔DÓLARES: pata dólar USD (partida) + pata pesos del base.
    for u in legs:
        if u["idx"] in used or not (u["dc"] and u["usd"]):
            continue
        residual = _same_boleto_residual(u)
        if residual is None:
            continue   # pata dólar suelta (no partida) → no es conversión: trade real
        for p in legs:
            if (p["idx"] in used or p["idx"] == u["idx"] or p["dc"] or p["usd"]):
                continue  # contraparte: pata PESOS del ticker base (no D/C, ARS)
            if not (p["base"] == u["base"] and abs(p["qty"] - u["qty"]) < 1e-6
                    and p["dir"] != u["dir"]
                    and _days_between(p["date"], u["date"]) == 0
                    and p["cash"] > 0 and u["cash"] > 0):
                continue
            # Guarda de tasa: una conversión real tiene un TC plausible. Si el
            # ratio ARS/USD es absurdo (Monto malformado o falso match), NO
            # colapsamos — dejamos las patas como trades reales (reversible y
            # visible) en vez de emitir un FX con tasa basura.
            if not (100.0 <= p["cash"] / u["cash"] <= 100000.0):
                continue
            # peso paga (Compra) → ARS→USD; peso cobra (Venta) → USD→ARS.
            fx[p["idx"]] = ("FX_ARS_USD" if p["dir"] == "C" else "FX_USD_ARS",
                            p["cash"], u["cash"])
            drop.add(u["idx"])           # la pata dólar USD se funde en el FX
            fee.add(residual["idx"])     # el residual en pesos es un costo real → FEE
            used.add(p["idx"]); used.add(u["idx"]); used.add(residual["idx"])
            break

    # Residuales de patas dólar PARTIDAS que NO entraron en un FX (la pata dólar
    # quedó como trade real USD): igual son un costo en pesos → FEE, no se pierden.
    for leg in legs:
        if (leg["idx"] not in drop and leg["idx"] not in fee and leg["dc"]
                and not leg["usd"] and leg["boleto"] and leg["boleto"] != "0"):
            if any(o["idx"] != leg["idx"] and o["boleto"] == leg["boleto"]
                   and o["dc"] and o["usd"] and o["base"] == leg["base"]
                   for o in legs):
                fee.add(leg["idx"])
    return fx, fee, drop


class IolParser(Parser):
    format_id = "iol"
    display_name = "IOL (InvertirOnline)"
    is_supported = True
    platform = "iol"
    platform_label = "IOL (InvertirOnline)"
    export_label = "Mi Cuenta → Movimientos → Detalle de Movimientos"

    def can_handle(self, headers: List[str]) -> bool:
        norm = {_norm_header(h) for h in headers}
        return len(_REQUIRED_HEADERS & norm) >= 3

    def template_csv(self) -> str:
        # Ejemplo anonimizado con una fila de cada tipo. Coma-separated, decimal
        # con punto (como lo entrega el aplanado HTML→CSV).
        return (
            "Nro. de Mov.,Nro. de Boleto,Tipo Mov.,Concert.,Liquid.,Est,"
            "Cant. titulos,Precio,Comis.,Iva Com.,Otros Imp.,Monto,"
            "Observaciones,Tipo Cuenta\n"
            "100001,200001,Compra(GGAL),05/01/2025,07/01/2025,,"
            "100,1500.50,150.05,31.51,5.00,150236.56,,Cuenta Pesos\n"
            "100002,200002,Venta(GGALD),06/02/2025,10/02/2025,,"
            "100,8.20,0.82,0.17,0.00,819.01,,Cuenta Dólares\n"
            "100003,200003,Pago de Dividendos(EDN),03/03/2025,03/03/2025,,"
            ",,0,0,0,5230.00,,Cuenta Pesos\n"
            "100004,200004,Crédito,01/04/2025,01/04/2025,,"
            ",,0,0,0,12.50,,Cuenta Dólares\n"
            "100005,200005,Depósito de Fondos - Transferencia electrónica - BANCO X,"
            "10/04/2025,10/04/2025,,,,0,0,0,500000.00,,Cuenta Pesos\n"
        )

    def parse(self, content: str, file_name: Optional[str] = None) -> ParseResult:
        result = ParseResult()
        if content.startswith("﻿"):
            content = content[1:]
        try:
            reader = csv.DictReader(io.StringIO(content))
            raw_headers = reader.fieldnames or []
        except Exception as ex:
            result.parse_errors.append(RowError(
                0, None, "FILE_UNREADABLE", f"No pudimos leer el archivo: {ex}",
            ))
            return result

        norm_to_orig = {_norm_header(h): h for h in raw_headers}
        if len(_REQUIRED_HEADERS & set(norm_to_orig.keys())) < 3:
            result.parse_errors.append(RowError(
                0, None, "IOL_HEADERS_MISMATCH",
                "Este archivo no parece un export de Movimientos de IOL. "
                "Bajalo desde IOL → Mi Cuenta → Movimientos → Movimientos Históricos.",
            ))
            return result

        def G(row, norm_key: str) -> str:
            col = norm_to_orig.get(norm_key)
            return _strip(row.get(col, "")) if col else ""

        rows = list(reader)
        # Conducto dólar-MEP: un bono usado como puente para convertir
        # pesos↔dólares. Lo colapsamos en UN FX (no dos trades del bono) y
        # descartamos el residual + la pata dólar fundida. Sin esto: posición
        # fantasma del bono + P&L basura + cash fabricado. Ver _detect_iol_conduits.
        conduit_fx, conduit_fee, conduit_drop = _detect_iol_conduits(rows, G)

        for idx, row in enumerate(rows, start=1):
            if idx in conduit_drop:
                continue  # pata dólar USD ya fundida en un FX
            tipo_mov = G(row, "tipomov")
            if not tipo_mov:
                continue  # fila vacía / sin tipo

            # Residual en pesos de una pata dólar (impuesto/comisión del dólar-MEP):
            # es un costo REAL en pesos → FEE. Si lo descartáramos, el cash en ARS
            # quedaría inflado por la suma de los residuales.
            if idx in conduit_fee:
                amt = abs(_num(G(row, "monto")))
                if amt > 0:
                    boleto = G(row, "nrodeboleto")
                    result.raw_rows.append(RawRow(row_index=idx, data={
                        "fecha": _parse_date(G(row, "concert")) or "",
                        "tipo": "FEE", "broker": "IOL", "activo": "",
                        "cantidad": "", "precio": "", "monto": repr(amt),
                        "monto_usd": "", "tc": "", "comisiones": "0", "moneda": "ARS",
                        "notas": f"Impuesto/comisión dólar-MEP ({tipo_mov})"
                                 + (f" · Boleto {boleto}" if boleto and boleto != "0" else ""),
                    }))
                continue

            # Conversión dólar-MEP colapsada: la fila pesos es el carrier del FX.
            fxinfo = conduit_fx.get(idx)
            if fxinfo:
                fx_op, ars_amt, usd_amt = fxinfo
                boleto = G(row, "nrodeboleto")
                result.raw_rows.append(RawRow(row_index=idx, data={
                    "fecha": _parse_date(G(row, "concert")) or "",
                    "tipo": fx_op, "broker": "IOL", "activo": "",
                    "cantidad": "", "precio": "",
                    "monto": repr(ars_amt), "monto_usd": repr(usd_amt), "tc": "",
                    "comisiones": "0", "moneda": "",
                    "notas": f"Conversión dólar-MEP ({tipo_mov})"
                             + (f" · Boleto {boleto}" if boleto and boleto != "0" else ""),
                }))
                continue

            skip = _skip_reason(tipo_mov)
            if skip:
                result.parse_errors.append(RowError(idx, "Tipo Mov.", skip[0], skip[1]))
                continue

            tipo_rendi = _resolve_op(tipo_mov)
            if tipo_rendi is None:
                result.parse_errors.append(RowError(
                    idx, "Tipo Mov.", "IOL_OP_UNKNOWN",
                    f"Tipo de movimiento no soportado: '{tipo_mov}'.",
                ))
                continue

            fecha = _parse_date(G(row, "concert"))
            raw_ticker = _extract_raw_ticker(tipo_mov)

            # Moneda: Tipo Cuenta (pesos/dólares) + sufijo US$ del ticker. Default ARS.
            cuenta = _deaccent(G(row, "tipocuenta").lower())
            if raw_ticker and _has_usd_suffix(raw_ticker):
                moneda = "USD"
            elif any(h in cuenta for h in _CUENTA_USD_HINTS):
                moneda = "USD"
            elif any(h in cuenta for h in _CUENTA_ARS_HINTS):
                moneda = "ARS"
            else:
                moneda = "ARS"

            # asset_type: FCI (Suscripción/Rescate) → FUND, para que el normalizer
            # lo mapee a FCI:<slug> y cotice live (igual que Cocos/Balanz). El
            # resto queda sin hint (el normalizer adivina por símbolo).
            head = _deaccent(_PAREN_RX.split(tipo_mov, 1)[0].strip().lower())
            asset_type = "FUND" if ("suscripcion" in head or "rescate" in head) else ""

            # Ticker (solo para operaciones con activo). Los FCI (asset_type FUND) no
            # se truncan (IOLDOLD ≠ IOLDOL) para que matcheen la foto de tenencia.
            ticker = _clean_ticker(raw_ticker, is_fci=(asset_type == "FUND")) if raw_ticker else ""
            if tipo_rendi in ("DEPOSITO", "RETIRO", "INTERES"):
                ticker = ""   # cash flows sin activo (incluye patas del conducto)

            fees = _num(G(row, "comis")) + _num(G(row, "ivacom")) + _num(G(row, "otrosimp"))

            if tipo_rendi in ("COMPRA", "VENTA"):
                # El cash REAL del trade es la columna `Monto` (neto, con signo),
                # NO cantidad × Precio. Para bonos (cotizan "por 100 nominales") y
                # patas dólar-MEP/cable, IOL pone un Precio en otra escala y
                # cantidad × Precio se infla hasta 10.000× → caja fantasma de
                # millones. Usamos |Monto| como bruto y derivamos precio = |Monto|
                # / cantidad (siempre consistente con la caja), igual que Cocos.
                # Fees=0 porque Monto ya viene neto de comisiones.
                cantidad = G(row, "canttitulos")
                qty_val = _num(cantidad)
                monto_cash = abs(_num(G(row, "monto")))
                if monto_cash > 0 and qty_val:
                    monto = repr(monto_cash)
                    precio = repr(monto_cash / qty_val)
                    comisiones = "0"
                else:
                    # Fallback (sin Monto usable): caemos a cantidad × Precio.
                    precio = G(row, "precio")
                    monto = ""
                    comisiones = f"{fees:.2f}" if fees else "0"
            else:
                # DEPOSITO / RETIRO / DIVIDENDO / INTERES: cash = Monto.
                cantidad = ""
                precio = ""
                comisiones = "0"
                raw_monto = G(row, "monto")
                if tipo_rendi in ("DEPOSITO", "RETIRO"):
                    # La dirección la define el tipo; el Monto de IOL viene con
                    # signo (Extracción negativo) → tomamos el valor absoluto.
                    val = abs(_num(raw_monto))
                    monto = repr(val) if val else ""
                else:
                    # DIVIDENDO / INTERES: mantenemos el signo. Un dividendo NETO
                    # negativo (retención > pago) lo trata el normalizer como FEE.
                    monto = raw_monto
                # Filas sin caja: eventos de bono que IOL parte en una fila de
                # cash + otra NOMINAL (Cant. titulos, Monto vacío) que solo baja
                # VN, y cualquier cash flow con Monto 0. No mueven caja → skip
                # (el importe real entra por la fila hermana). Sin esto: MISSING_AMOUNT.
                if not monto or _num(monto) == 0:
                    continue

            # Notas: tipo original + nro de boleto (auditoría / trazabilidad).
            boleto = G(row, "nrodeboleto")
            notas = tipo_mov + (f" · Boleto {boleto}" if boleto and boleto != "0" else "")

            data = {
                "fecha":      fecha or "",
                "tipo":       tipo_rendi,
                "broker":     "IOL",
                "activo":     ticker,
                "cantidad":   cantidad,
                "precio":     precio,
                "monto":      monto,
                "monto_usd":  "",
                "tc":         "",
                "comisiones": comisiones,
                "moneda":     moneda,
                "notas":      notas,
            }
            # asset_type=FUND (FCI) → habilita el rewrite a FCI:<slug> en el
            # normalizer. asset_name = ticker crudo (popula el campo para auditoría
            # y futuro sweep por nombre).
            if asset_type:
                data["asset_type"] = asset_type
            if ticker:
                data["asset_name"] = raw_ticker
            result.raw_rows.append(RawRow(row_index=idx, data=data))

        return result
