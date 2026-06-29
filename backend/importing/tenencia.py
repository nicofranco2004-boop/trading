"""Parser de la "Tenencia valorizada" de Bull Market — la FOTO de posiciones a
una fecha (Mi cuenta → Otras consultas → Tenencia valorizada a una fecha).

A diferencia de la Cuenta Corriente (libro de caja de movimientos), esto es un
SNAPSHOT: lista cada activo con su cantidad, precio y valuación de HOY, agrupado
por clase de activo. NO trae costo/PPC — solo valor actual. Se usa para COMPLETAR
las tenencias que la Cuenta Corriente no pudo reconstruir (las compradas antes de
su ventana), reconciliando por activo (no duplica lo que ya existe).

Bull Market no exporta este reporte a Excel → llega en PDF impreso. Acá parseamos
el TEXTO ya extraído del PDF (ver `excel.pdf_to_text`), así esta lógica es
testeable sin un PDF de por medio.

Formato del texto (una sección por clase, con su total, luego filas):
    Tenencias al 26/06/2026 ARS 25.354.380,78
    Cuenta Corriente ARS -343,21
      Pesos 1 1,00 -1.561,65
      U$S 0,51 1.468,00 748,68
    Acciones ARS 3.355.162,50
    Ticker Nombre de la Especie Cantidad Precio Importe Total
      BMA BANCO MACRO 30,00 14.110,00 423.300,00
    Titulos Publicos ARS …      → BOND
    Obligaciones Negociables …  → BOND
    Cedears ARS …               → CEDEAR
Cada fila de tenencia: TICKER  <nombre variable>  cantidad precio importe
(los 3 últimos en formato AR: '.' miles, ',' decimal).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional


# Encabezado de sección (lowercase, sin tildes) → asset_type Rendi.
_SECTION_TYPE = {
    "acciones": "STOCK",
    "titulos publicos": "BOND",
    "obligaciones negociables": "BOND",
    "cedears": "CEDEAR",
    "letras": "BOND",
    "fondos": "FUND",
    "fcis": "FUND",
}

# Número AR: '1.234.567,89' → 1234567.89 ; también '702,90' / '1,00'.
_AR_NUM = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
_SECTION_RE = re.compile(
    r"^(Acciones|Titulos Publicos|T\xedtulos P\xfablicos|Obligaciones Negociables|"
    r"Cedears|CEDEARs|Letras|Fondos|FCIs?)\s+(ARS|U\$S|USD|Dolares?)\s+(" + _AR_NUM + r")\s*$",
    re.IGNORECASE)
# Fila de tenencia: ticker (2-8 alfanum), nombre (lazy), 3 números AR al final.
_ROW_RE = re.compile(
    r"^([A-Z0-9]{2,8})\s+(.+?)\s+(" + _AR_NUM + r")\s+(" + _AR_NUM + r")\s+(" + _AR_NUM + r")\s*$")
_DATE_RE = re.compile(r"Tenencias?\s+al\s+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
_TOTAL_RE = re.compile(r"Tenencias?\s+al\s+\d{2}/\d{2}/\d{4}\s+ARS\s+(" + _AR_NUM + r")", re.IGNORECASE)


def _num(s: str) -> float:
    return float(s.strip().replace(".", "").replace(",", "."))


def _norm(s: str) -> str:
    return (s or "").strip().lower().replace("\xed", "i").replace("\xfa", "u").replace("\xe1", "a")


@dataclass
class Holding:
    ticker: str
    asset_type: str           # STOCK / BOND / CEDEAR / FUND
    quantity: float
    value: float              # importe total (valuación de hoy) — LA VERDAD
    currency: str             # moneda de la sección (ARS por defecto en Bull Market)
    price_per1: float = 0.0   # precio por 1 unidad = value/quantity (auto-resuelve per-100)
    per100: bool = False      # True si la columna Precio venía per-100 (bonos)
    name: str = ""


@dataclass
class TenenciaSnapshot:
    holdings: List[Holding] = field(default_factory=list)
    date: Optional[str] = None          # YYYY-MM-DD
    total_ars: Optional[float] = None    # "Tenencias al … ARS X" (incluye cash)
    cash_ars: Optional[float] = None     # saldo en pesos (Estado de Cuenta Cocos)
    cash_usd: Optional[float] = None     # saldo en dólares
    warnings: List[str] = field(default_factory=list)


def _to_iso(d: str) -> Optional[str]:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", d or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


@dataclass
class ReconcileResult:
    matched: List[str] = field(default_factory=list)              # ya en la cantidad correcta → no se toca (no duplica)
    to_seed: List[tuple] = field(default_factory=list)            # [(Holding, gap_qty)] huecos a crear como lote de apertura
    over: List[tuple] = field(default_factory=list)              # [(ticker, rendi_qty, snap_qty)] Rendi tiene de MÁS → revisar
    not_in_snapshot: List[tuple] = field(default_factory=list)   # [(ticker, rendi_qty)] en Rendi pero no en la foto (vendido?)


def compute_reconcile(current_qty_by_asset: dict, snapshot: "TenenciaSnapshot",
                      eps: float = 1e-6) -> ReconcileResult:
    """Concilia la foto (Tenencia = verdad) contra lo que Rendi YA tiene por activo
    (sumando broker padre + sibling '· USD'). Por activo de la foto:
      • Rendi == foto  → matched (no se toca → NO duplica).
      • Rendi <  foto  → seedea SOLO la diferencia (el hueco comprado antes de la
                         ventana de la Cuenta Corriente) como lote de apertura.
      • Rendi >  foto  → over (la foto manda; se flaggea para ajustar).
    Lo que Rendi tiene y la foto NO → not_in_snapshot (vendido / a revisar)."""
    res = ReconcileResult()
    snap_tickers = set()
    for h in snapshot.holdings:
        snap_tickers.add(h.ticker)
        rq = current_qty_by_asset.get(h.ticker, 0.0)
        gap = h.quantity - rq
        if abs(gap) <= eps:
            res.matched.append(h.ticker)
        elif gap > 0:
            res.to_seed.append((h, round(gap, 6)))
        else:
            res.over.append((h.ticker, rq, h.quantity))
    for asset, q in current_qty_by_asset.items():
        if asset not in snap_tickers and abs(q) > eps:
            res.not_in_snapshot.append((asset, q))
    return res


def build_tenencia_seed_txs(broker: str, reconcile: ReconcileResult,
                            seed_date: str, currency: str = "ARS"):
    """Txs sintéticas (DEPOSITO + COMPRAs) que crean los lotes de APERTURA del
    hueco — lo que la Cuenta Corriente no reconstruyó (comprado antes de su
    ventana). El DEPOSITO financia las compras → net cash 0. Cada COMPRA lleva:
      • el asset_type de la foto (STOCK/BOND/CEDEAR) → se valúa bien (no OTHER);
      • el precio PER-1 (= valor/cantidad) como costo → P&L 0 en la apertura.
    Se persisten como un batch propio (auditable y revertible, como el seed).
    NO duplica: `reconcile.to_seed` ya trae SOLO la diferencia por activo."""
    from .schema import NormalizedTx, OP_BUY, OP_DEPOSIT
    txs = []
    idx = -20000  # negativo, no colisiona con row_index reales (igual que el seed)
    total = round(sum(gap * h.price_per1 for h, gap in reconcile.to_seed), 4)
    if total > 0:
        txs.append(NormalizedTx(
            row_index=idx, date=seed_date, broker=broker,
            operation_type=OP_DEPOSIT, gross_amount=total, currency=currency,
            notes="Tenencia — aporte inicial sintético (Rendi)"))
        idx += 1
    for h, gap in reconcile.to_seed:
        txs.append(NormalizedTx(
            row_index=idx, date=seed_date, broker=broker, operation_type=OP_BUY,
            asset_symbol=h.ticker, asset_type=h.asset_type,
            quantity=gap, unit_price=h.price_per1,
            gross_amount=round(gap * h.price_per1, 4), currency=currency,
            notes=f"Tenencia — apertura {h.ticker} a precio de {seed_date} (P&L 0)"))
        idx += 1
    return txs


def looks_like_tenencia(text: str) -> bool:
    """Heurística para autodetectar este reporte (vs Cuenta Corriente u otro PDF)."""
    t = _norm(text)
    return "tenencia valorizada" in t or ("tenencias al" in t and "nombre de la especie" in t)


def parse_bullmarket_tenencia(text: str) -> TenenciaSnapshot:
    snap = TenenciaSnapshot()
    md = _DATE_RE.search(text)
    if md:
        snap.date = _to_iso(md.group(1))
    mt = _TOTAL_RE.search(text)
    if mt:
        snap.total_ars = _num(mt.group(1))

    cur_type: Optional[str] = None
    cur_ccy = "ARS"
    seen_tickers = set()
    in_cc = False            # dentro de la sección "Cuenta Corriente" (cash)
    cash_ars = 0.0
    cash_usd = 0.0
    has_cash = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        sm = _SECTION_RE.match(line)
        if sm:
            in_cc = False
            cur_type = _SECTION_TYPE.get(_norm(sm.group(1)))
            ccy = _norm(sm.group(2))
            cur_ccy = "USD" if ("u$s" in ccy or "usd" in ccy or "dolar" in ccy) else "ARS"
            continue
        # Sección "Cuenta Corriente ARS …": trae el CASH (Pesos = saldo ARS;
        # U$S / DOLAR MEP = saldo USD). Lo capturamos para cerrar el cash, no solo
        # las posiciones. Pesos → último número (importe ARS); USD → primer número
        # (cantidad en dólares; el resto es su valuación en pesos).
        if _norm(line).startswith("cuenta corriente"):
            in_cc = True
            cur_type = None
            continue
        if in_cc:
            ln = _norm(line)
            nums = re.findall(_AR_NUM, line)
            if ln.startswith("pesos") and nums:
                cash_ars += _num(nums[-1]); has_cash = True
            elif (ln.startswith("u$s") or ln.startswith("dolar") or ln.startswith("dolares")) and nums:
                cash_usd += _num(nums[0]); has_cash = True
            continue
        if line.startswith("Ticker") or cur_type is None:
            continue
        rm = _ROW_RE.match(line)
        if not rm:
            continue
        tk = rm.group(1).upper()
        # Evita falsos positivos con encabezados/pies que empiezan en mayúscula.
        if tk in ("ARS", "USD", "TICKER"):
            continue
        qty, price, value = _num(rm.group(3)), _num(rm.group(4)), _num(rm.group(5))
        if qty <= 0:
            continue
        # El `importe` (value) es la VERDAD. La columna Precio viene per-1 para
        # acciones/CEDEARs (qty×precio ≈ importe) y per-100 para bonos (qty×precio
        # ≈ 100×importe). Detectamos cuál y derivamos el precio per-1 = importe/qty
        # (uniforme), así el downstream no se preocupa por la convención.
        prod = qty * price
        tol = max(1.0, 0.01 * abs(value))
        per100 = False
        if abs(prod - value) <= tol:
            pass                       # per-1 (acción/CEDEAR)
        elif abs(prod / 100.0 - value) <= tol:
            per100 = True              # per-100 (bono) — esperado, no es error
        else:
            snap.warnings.append(
                f"{tk}: importe ({value:,.2f}) no es cantidad×precio ni /100 — revisar")
        key = (tk, cur_ccy)
        if key in seen_tickers:
            continue
        seen_tickers.add(key)
        snap.holdings.append(Holding(
            ticker=tk, asset_type=cur_type, quantity=qty, value=value,
            currency=cur_ccy, price_per1=value / qty, per100=per100,
            name=rm.group(2).strip()[:60]))
    if has_cash:
        snap.cash_ars = round(cash_ars, 2)
        snap.cash_usd = round(cash_usd, 2)
    return snap


# ─── PPI — "Estado de Cuenta" (Excel, foto de tenencia) ──────────────────────
# Mismo rol que la Tenencia de Bull Market: completa las posiciones de apertura
# que los Movimientos (ventana) no reconstruyen. Reusa Holding/TenenciaSnapshot
# + compute_reconcile + build_tenencia_seed_txs. Estructura del Excel: preámbulo
# (TITULAR/COMITENTE/FECHA/TOTAL CARTERA) + "POR TIPO DE ACTIVO" + secciones
# (MONEDAS, ACCIONES, BONOS, CEDEARS, FCI, ONS), cada una con un row de nombre,
# un row de headers de columna, filas de tenencia y un SUBTOTAL.

# Encabezado de sección (deaccent+lower) → asset_type. MONEDAS = cash → se saltea.
_PPI_SECTION_TYPE = {
    "acciones": "STOCK",
    "bonos": "BOND",
    "ons": "BOND",
    "obligaciones negociables": "BOND",
    "cedears": "CEDEAR",
    "fci": "FUND",
    "fcis": "FUND",
    "fondos": "FUND",
    "letras": "BOND",
    "titulos publicos": "BOND",
}
_PPI_SECTION_NAMES = set(_PPI_SECTION_TYPE.keys()) | {"monedas"}


def _deaccent(s: str) -> str:
    return ("" if s is None else str(s)).translate(str.maketrans("áéíóúüÁÉÍÓÚÜ", "aeiouuAEIOUU"))


def _cell_s(v) -> str:
    return "" if v is None else str(v).strip()


def _ppi_num(v):
    """Número de una celda cruda de openpyxl: int/float directo, o string que
    puede venir point-decimal ('845320.75') o formato AR ('1.234.567,89')."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    if "," in s:                      # formato AR: '.' miles, ',' decimal
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _ppi_extract_date(rows) -> Optional[str]:
    """Fecha de la foto: la celda bajo 'FECHA' (DD/MM/YYYY) o un datetime, en el
    preámbulo. Más confiable que el título de la hoja o el nombre del archivo."""
    for r in rows[:8]:
        for c in r:
            if hasattr(c, "strftime"):          # datetime/date de openpyxl
                try:
                    return c.strftime("%Y-%m-%d")
                except Exception:
                    pass
            m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", _cell_s(c))
            if m:
                d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if 1 <= mo <= 12 and 1 <= d <= 31:   # ignora fechas imposibles (31/13/…)
                    return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def looks_like_ppi_tenencia(rows) -> bool:
    """Heurística para el Estado de Cuenta de PPI (xlsx → filas crudas)."""
    flat = " ".join(_deaccent(_cell_s(c)).lower() for r in rows[:30] for c in r)
    return "estado de cuenta" in flat and "por tipo de activo" in flat


def _ppi_currency(section_type: str, ticker: str, name: str,
                  vmc: Optional[float], vc: Optional[float]) -> str:
    """Moneda de un holding. FCI: el tag del nombre/especie manda (.DOL./Dólar →
    USD; .PESOS/Pesos → ARS). El resto: si VALOR MONEDA COTIZACIÓN difiere de
    VALOR CORRIENTE, la fila está valuada en USD (col6 = equivalente en ARS);
    si coinciden, está en ARS. (En este export PPI cotiza los bonos en pesos,
    así que casi todo da ARS salvo ONS y FCI dólar.)"""
    tag = _deaccent(f"{ticker} {name}").upper()
    if section_type == "FUND":
        # El tag del nombre/especie manda. PESOS primero (un FCI "Dólar Linked"
        # dice "Dólar" pero cotiza en PESOS), después dólar. Sin tag → ARS por
        # defecto (los FCI dólar de PPI SIEMPRE traen .DOL/USD/Dólar). NO aplicamos
        # la regla numérica a FCI: ahí la VMC suele venir por-cuotaparte y difiere
        # de VC aunque el fondo sea en pesos → mal-clasificaría ARS como USD.
        # PESOS y "Dólar LINKED" (dolar-linked = se suscribe/cotiza en PESOS) van
        # primero, después el dólar genuino.
        if "PESO" in tag or "LINKED" in tag:
            return "ARS"
        if "DOL" in tag or "USD" in tag:
            return "USD"
        return "ARS"
    # Acciones/CEDEARs/bonos/ONs: USD si VALOR MONEDA COTIZACIÓN difiere de VALOR
    # CORRIENTE (col6 = equivalente en ARS), o si sólo vino la cotización (sin VC).
    if vmc is not None and vc:
        return "USD" if abs(vmc - vc) / max(abs(vc), 1.0) > 0.005 else "ARS"
    if vmc is not None and not vc:
        return "USD"
    return "ARS"


def parse_ppi_tenencia(rows) -> TenenciaSnapshot:
    """Parsea el Estado de Cuenta de PPI (filas crudas de `excel.xlsx_to_rows`)
    a un TenenciaSnapshot de posiciones. NO seedea la sección MONEDAS (cash) —
    eso lo reconstruyen los Movimientos. La moneda de cada holding se resuelve
    por sección + (VALOR MONEDA COTIZACIÓN vs VALOR CORRIENTE) + tag del FCI."""
    snap = TenenciaSnapshot()
    snap.date = _ppi_extract_date(rows)

    section_type: Optional[str] = None   # asset_type, "SKIP" (monedas) o None
    cols: dict = {}                      # clave canónica → índice de columna
    seen = set()
    cash_ars = 0.0                       # sección MONEDAS: saldo de efectivo por moneda
    cash_usd = 0.0
    has_cash = False                     # vimos la sección MONEDAS (para cerrar el cash)

    for raw in rows:
        cells = list(raw)
        svals = [_cell_s(c) for c in cells]
        nonempty = [v for v in svals if v]
        if not nonempty:
            continue
        c0 = _deaccent(svals[0]).lower() if svals else ""
        c0u = c0.strip()

        # Total cartera (preámbulo) — para reconciliación/aviso.
        if c0u.startswith("total cartera"):
            for v in svals[1:]:
                n = _ppi_num(v)
                if n is not None:
                    snap.total_ars = n
                    break
            continue

        # Row de nombre de sección: UNA sola celda no vacía y es una sección conocida.
        if len(nonempty) == 1 and c0u in _PPI_SECTION_NAMES:
            section_type = "SKIP" if c0u == "monedas" else _PPI_SECTION_TYPE[c0u]
            cols = {}
            continue

        # Row de SUBTOTAL → cierra la sección.
        if c0u == "subtotal":
            section_type = None
            cols = {}
            continue

        # Row de headers de columna (ESPECIE/MONEDA + DESCRIPCIÓN).
        if c0u in ("especie", "moneda") and any(_deaccent(v).lower() == "descripcion" for v in svals):
            cols = {}
            for i, v in enumerate(svals):
                h = _deaccent(v).lower().strip().rstrip(".")
                if h in ("especie", "moneda"):
                    cols["especie"] = i
                elif h == "descripcion":
                    cols["descripcion"] = i
                elif h == "cant. disponible" or h == "cant disponible":
                    cols["cant_disp"] = i
                elif h == "cant. garantia" or h == "cant garantia":
                    cols["garantia"] = i
                elif h == "precio":
                    cols["precio"] = i
                elif h == "valor moneda cotizacion":
                    cols["vmc"] = i
                elif h == "valor corriente":
                    cols["vc"] = i
            continue

        # Sección MONEDAS (cash): capturamos el saldo por moneda (CANT. DISPONIBLE
        # = monto nativo) para que el Estado de Cuenta pueda cerrar el cash, no solo
        # las posiciones. '$'/Peso → ARS; USD → USD.
        if section_type == "SKIP":
            esp_i, disp_i = cols.get("especie"), cols.get("cant_disp")
            if esp_i is not None and disp_i is not None and esp_i < len(svals):
                mon = _deaccent(svals[esp_i]).upper().strip()
                amt = _ppi_num(cells[disp_i]) if disp_i < len(cells) else None
                if amt is not None:
                    if mon in ("$", "PESO", "PESOS", "ARS"):
                        cash_ars += amt; has_cash = True
                    elif mon.startswith("USD") or mon in ("U$S", "US$", "DOLAR", "DOLARES"):
                        cash_usd += amt; has_cash = True
            continue
        # Filas de datos: necesitan sección activa de posiciones + mapa de columnas.
        if not section_type or "especie" not in cols:
            continue
        esp_i = cols.get("especie")
        disp_i = cols.get("cant_disp")
        if esp_i is None or disp_i is None:
            continue
        ticker = (svals[esp_i] if esp_i < len(svals) else "").upper()
        if not ticker or ticker in ("ESPECIE", "MONEDA", "SUBTOTAL"):
            continue
        # Cantidad = DISPONIBLE + GARANTÍA: los valores (VALOR CORRIENTE / MONEDA
        # COTIZACIÓN) reflejan la tenencia TOTAL, incluida la parte dada en garantía
        # (caución/margen). Tomar sólo DISPONIBLE subvalúa la qty e infla price_per1.
        gar_i = cols.get("garantia")
        disp = _ppi_num(cells[disp_i] if disp_i < len(cells) else None)
        gar = _ppi_num(cells[gar_i]) if gar_i is not None and gar_i < len(cells) else None
        qty = (disp or 0) + (gar or 0)
        if qty <= 0:
            continue
        name_i, precio_i = cols.get("descripcion"), cols.get("precio")
        vmc_i, vc_i = cols.get("vmc"), cols.get("vc")
        name = (svals[name_i] if name_i is not None and name_i < len(svals) else "")
        price = _ppi_num(cells[precio_i]) if precio_i is not None and precio_i < len(cells) else None
        vmc = _ppi_num(cells[vmc_i]) if vmc_i is not None and vmc_i < len(cells) else None
        vc = _ppi_num(cells[vc_i]) if vc_i is not None and vc_i < len(cells) else None

        ccy = _ppi_currency(section_type, ticker, name, vmc, vc)
        # Valor en la moneda nativa: USD → VALOR MONEDA COTIZACIÓN; ARS → VALOR
        # CORRIENTE (== cotización para ARS). Fallback al otro / a qty×precio.
        value = (vmc if (ccy == "USD" and vmc) else vc)
        if not value:
            value = vmc or (qty * price if price else None)
        if not value:
            snap.warnings.append(f"{ticker}: sin valor — se omitió")
            continue
        key = (ticker, ccy)
        if key in seen:
            continue
        seen.add(key)
        snap.holdings.append(Holding(
            ticker=ticker, asset_type=section_type, quantity=qty, value=value,
            currency=ccy, price_per1=value / qty, per100=False, name=name[:60]))
    if has_cash:
        snap.cash_ars = round(cash_ars, 2)
        snap.cash_usd = round(cash_usd, 2)
    return snap


# ─── Cocos — "Estado de Cuenta" / portfolio_report (CSV, foto de tenencia) ────
# Mismo rol que la Tenencia de Bull Market y el Estado de Cuenta de PPI: completa
# las posiciones de apertura que los Movimientos no reconstruyen. Reusa el
# _extract_ticker / clasificación asset_type del parser de Movimientos (cocos.py)
# → ticker y tipo coinciden, así reconcile() no inventa huecos falsos. Estructura
# del CSV (delimitado por ';'):
#     instrumento;cantidad;precio;moneda;total
#     Dólar estadounidense ();0,18;0;0;0           → polvo USD → cash
#     CEDEAR NVIDIA CORPORATION (NVDA);28;12450;ARS;348600
#     BANCO MACRO S.A. B  1 V. ESCRIT (BMA);39;14110;ARS;550290   → acción AR → ""
#     ARS;48763,5;1;ARS;48763,5                    → saldo en pesos → cash
#     USD;2,03;1;USD;2,03                          → saldo en dólares → cash
_COCOS_TEN_HEADER = ("instrumento", "cantidad", "precio", "moneda", "total")


def looks_like_cocos_tenencia(text: str) -> bool:
    """Heurística para el Estado de Cuenta de Cocos (CSV ';' con el header
    instrumento;cantidad;precio;moneda;total)."""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # Match EXACTO (set igual, no subconjunto): el header de Movimientos de
        # Cocos (nroTicket;…;instrumento;…;cantidad;precio;…;total) CONTIENE estos
        # 5 tokens → un chequeo de subconjunto confundiría Movimientos con la foto.
        cells = set(c for c in (_deaccent(x).strip().lower() for x in line.split(";")) if c)
        return cells == set(_COCOS_TEN_HEADER)
    return False


def parse_cocos_tenencia(text: str) -> TenenciaSnapshot:
    """Parsea el Estado de Cuenta de Cocos (CSV) a un TenenciaSnapshot (holdings +
    cash). asset_type igual que el parser de Movimientos (cocos.py): CEDEAR →
    CEDEAR; FCI → FUND; bono/ON/letra → BOND; acción AR → "" (se valúa por su .BA)."""
    from .parsers.cocos import _extract_ticker, _is_bond_instrument, _clean_ar_number

    def num(s: str) -> float:
        try:
            return float(_clean_ar_number(s or "0"))
        except (ValueError, TypeError):
            return 0.0

    snap = TenenciaSnapshot()
    cash_ars = 0.0
    cash_usd = 0.0
    seen = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        cells = [c.strip() for c in line.split(";")]
        if len(cells) < 5:
            continue
        instr, qty_s, _price_s, moneda, total_s = cells[0], cells[1], cells[2], cells[3], cells[4]
        iu = instr.upper().strip()
        if iu == "INSTRUMENTO":            # header
            continue
        # Filas de CASH: el instrumento ES la moneda ('ARS' / 'USD'), sin ticker.
        if iu in ("ARS", "PESOS", "PESO ARGENTINO", "$"):
            cash_ars += num(qty_s); continue
        if iu in ("USD", "U$S", "US$", "DOLARES", "DÓLARES"):
            cash_usd += num(qty_s); continue
        ticker = _extract_ticker(instr)
        if not ticker:
            # 'Dólar estadounidense ()' (paréntesis vacío) = polvo en USD → al cash.
            if "dolar" in _deaccent(instr).lower():
                cash_usd += num(qty_s)
            continue
        qty = num(qty_s)
        value = num(total_s)
        if qty <= 0:
            continue
        if iu.startswith("CEDEAR"):
            at = "CEDEAR"
        elif "FCI" in iu:
            at = "FUND"
        elif _is_bond_instrument(instr):
            at = "BOND"
        else:
            at = ""
        ccy = "USD" if moneda.strip().upper() in ("USD", "U$S", "US$") else "ARS"
        key = (ticker, ccy)
        if key in seen:
            continue
        seen.add(key)
        snap.holdings.append(Holding(
            ticker=ticker, asset_type=at, quantity=qty, value=value,
            currency=ccy, price_per1=(value / qty if qty else 0.0),
            name=instr[:60]))
    snap.cash_ars = round(cash_ars, 2)
    snap.cash_usd = round(cash_usd, 2)
    if snap.holdings:
        snap.total_ars = round(
            sum(h.value for h in snap.holdings if h.currency == "ARS") + cash_ars, 2)
    return snap
