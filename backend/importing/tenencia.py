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


def _canon_fund_ticker(ticker: str) -> str:
    """FCI: mapea el ticker del broker al símbolo del catálogo (`FCI:<slug>`) para
    que matchee lo que el normalizer escribió desde los Movimientos (normalizer
    canonicaliza TODO FUND a FCI:<slug>). Si el ticker no está en el mapa curado,
    deja el crudo (mismo criterio que el normalizer). Sin esto, la foto siembra el
    fondo con el ticker crudo ('COCOA') mientras Rendi lo tiene como
    'FCI:COCOS-AHORRO-A' → mismatch de string → duplicado en to_seed + falso
    'vendido?' en not_in_snapshot."""
    try:
        from .fci_map import resolve_fci_symbol
        return resolve_fci_symbol(ticker) or ticker
    except Exception:
        return ticker


def _synth_letra_ticker(name: str) -> Optional[str]:
    """Letra/LECAP que el broker exporta SIN ticker entre paréntesis: sintetiza el
    mismo ticker decodable desde el vencimiento que usa el parser de Movimientos
    (cocos.py) → ambos lados matchean. Devuelve None si el nombre no es de bono/letra
    o no tiene fecha parseable."""
    try:
        from .maturity import is_bond_like_name, maturity_from_name, synth_letra_ticker
        if not is_bond_like_name(name):
            return None
        mat = maturity_from_name(name)
        return synth_letra_ticker(mat) if mat else None
    except Exception:
        return None



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
                            seed_date: str, currency: str = "ARS",
                            override: bool = False, complete: bool = False,
                            override_date: Optional[str] = None):
    """Txs sintéticas (DEPOSITO + COMPRAs) que crean los lotes de APERTURA del
    hueco — lo que la Cuenta Corriente no reconstruyó (comprado antes de su
    ventana). El DEPOSITO financia las compras → net cash 0. Cada COMPRA lleva:
      • el asset_type de la foto (STOCK/BOND/CEDEAR) → se valúa bien (no OTHER);
      • el precio PER-1 (= valor/cantidad) como costo → P&L 0 en la apertura.
    Se persisten como un batch propio (auditable y revertible, como el seed).
    NO duplica: `reconcile.to_seed` ya trae SOLO la diferencia por activo.

    Si `override=True` la foto PISA el estado (no sólo completa): además de las
    COMPRAs del hueco emite VENTAS sintéticas que llevan cada activo EXACTO a la
    foto —
      • over (Rendi > foto)                → VENTA de (rendi − foto);
      • not_in_snapshot (sólo si complete) → VENTA de todo (la foto no lo lista → se fue).
    Las ventas van a precio/monto 0 con `transfer_out=True`: el persister y el
    rebuild cierran el lote A COSTO (P&L 0, sin pérdida fantasma) y NO generan cash
    (el efectivo lo fija aparte el true-up contra la foto → no se doble-cuenta). El
    flag `complete` exige que la foto sea TOTAL (todas las clases + monedas); si es
    parcial, `not_in_snapshot` NO debe borrar posiciones legítimas (queda en gap-fill).
    El caller (endpoint) ya filtró `over`/`not_in_snapshot` por seguridad
    (safe-to-rebuild + cap de sanidad) antes de llamar acá."""
    from .schema import NormalizedTx, OP_BUY, OP_SELL, OP_DEPOSIT
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
    if override:
        # Reducciones que llevan el estado EXACTO a la foto. Precio/monto 0 +
        # transfer_out → cierre a costo (P&L 0), sin cash (el true-up fija el
        # efectivo con la foto). CRÍTICO: la VENTA debe ordenarse DESPUÉS de TODAS
        # las compras reales del activo en el replay del rebuild (tie-break: mismo
        # día = BUY antes que SELL). Si la foto es MÁS VIEJA que algún movimiento,
        # `seed_date` (= fecha de la foto) sortearía la venta ANTES de esa compra →
        # consumiría un lote-semilla fantasma y la reducción fallaría en silencio.
        # Por eso el caller pasa `override_date` = max(fecha_foto, última fecha de
        # BUY/SELL del par); acá cae a seed_date si no vino.
        red_date = override_date or seed_date
        reductions = [(tk, rq - sq) for tk, rq, sq in reconcile.over if rq - sq > 1e-9]
        if complete:
            reductions += [(tk, rq) for tk, rq in reconcile.not_in_snapshot if rq > 1e-9]
        for tk, qty in reductions:
            txs.append(NormalizedTx(
                row_index=idx, date=red_date, broker=broker, operation_type=OP_SELL,
                asset_symbol=tk, quantity=round(qty, 6), unit_price=0.0,
                gross_amount=0.0, currency=currency, transfer_out=True,
                notes=f"Tenencia — ajuste a foto de {seed_date}: cierre de {tk} a costo (P&L 0)"))
            idx += 1
    return txs


def build_cash_trueup_txs(adjustments, seed_date, start_idx: int = -21000):
    """Ajusta el EFECTIVO al valor de la foto (la foto es la verdad de HOY). Por
    cada moneda con |target − current| ≥ eps emite un DEPOSITO (si falta plata) o
    RETIRO (si sobra) sintético — auditable, revertible y sobrevive el rebuild
    (mismo patrón que el seed de holdings). Silencioso: el usuario no ve la
    diferencia, la foto manda.

    `adjustments`: lista de (broker, currency, current_cash, target_cash, eps).
    Devuelve (txs, applied) con applied = [(broker, ccy, current, target, diff)]
    para que el caller loguee la diferencia (detección interna de bugs del parser)."""
    from .schema import NormalizedTx, OP_DEPOSIT, OP_WITHDRAW
    txs, applied = [], []
    idx = start_idx
    for broker, ccy, cur, target, eps in adjustments:
        if target is None:
            continue
        cur = cur or 0.0
        diff = round(target - cur, 2)
        if abs(diff) < eps:
            continue
        txs.append(NormalizedTx(
            row_index=idx, date=seed_date, broker=broker,
            operation_type=(OP_DEPOSIT if diff > 0 else OP_WITHDRAW),
            gross_amount=abs(diff), currency=ccy,
            notes=f"Ajuste de cash a Estado de Cuenta ({ccy})"))
        applied.append((broker, ccy, cur, target, diff))
        idx -= 1
    return txs, applied


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
        if section_type == "FUND":
            ticker = _canon_fund_ticker(ticker)   # FCI:<slug> → matchea Movimientos
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
            # Letra/LECAP que Cocos exporta SIN ticker entre paréntesis: sintetizamos
            # el mismo ticker que el parser de Movimientos (así matchea, no cae en
            # not_in_snapshot como falso 'vendido?').
            ticker = _synth_letra_ticker(instr)
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
        if at == "FUND":
            ticker = _canon_fund_ticker(ticker)   # FCI:<slug> → matchea Movimientos
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


# ─── Balanz — "Resumen de Cuenta" / Posición consolidada (PDF, foto de tenencia) ─
# Igual rol que las otras fotos: la VERDAD de HOY. Pero para Balanz la aplicamos en
# modo OVERRIDE (la foto PISA el estado): además de completar huecos, REDUCE lo que
# Rendi tiene de más y ELIMINA lo que la foto no lista (ver build_tenencia_seed_txs
# override / el endpoint). El PDF ("Posición consolidada por concertación") lista
# Acciones/Bonos/Cedears/Fondos — TODO valuado en $ (pesos) → currency ARS para todos
# los holdings — más un bloque "Monedas" con el cash (Pesos / Dólares / US Dollar Cable).
# Cada fila:  ESPECIE  <descripción>  CANTIDAD  GARANTÍA  $ PRECIO  $ VALOR ACTUAL
# El ancla robusta son los DOS últimos '$' (precio, valor) + la Garantía en formato
# PUNTO ('0.00'), que discrimina de la Cantidad (coma) y evita ambigüedad.
_BAL_AR = r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?"   # AR flexible: '1.284,40','287,27','13.930','1,00'
# Garantía: la usamos SÓLO como separador de columna (ignoramos su valor), así que
# aceptamos cualquier número (punto '0.00', AR '1.234,00', US '1,234.00'). Antes
# exigía punto ('0.00') → una tenencia con garantía ≠ 0 en otro formato se caía de
# la foto y, en modo override, se VENDÍA por error. Requiere ≥1 dígito.
_BAL_GAR = r"-?\d[\d.,]*"
_BAL_ROW_RE = re.compile(
    r"^(\S+)\s+(.+?)\s+(" + _BAL_AR + r")\s+(" + _BAL_GAR + r")\s+\$\s+("
    + _BAL_AR + r")\s+\$\s+(" + _BAL_AR + r")\s*$")
_BAL_SECTION_TYPE = {"acciones": "STOCK", "bonos": "BOND", "cedears": "CEDEAR", "fondos": "FUND"}
_BAL_DATE_RE = re.compile(r"fecha resumen\s+(\d{2})/(\d{2})/(\d{4})")
_BAL_TOTAL_RE = re.compile(r"^total\s+\$\s+(" + _BAL_AR + r")\s*$")
# Cash: el bloque "Monedas" viene en 2 columnas → estos tokens caen a mitad de línea
# (p.ej. "Acciones $ 1.108.291 Pesos $ 837,14") → search, no startswith.
_BAL_CASH_RE = [
    (re.compile(r"pesos\s+\$\s+(" + _BAL_AR + r")"), "ARS"),
    (re.compile(r"dolares\s+usd\s+(" + _BAL_AR + r")"), "USD"),
    (re.compile(r"us dollar \(cable\)\s+usd\s+(" + _BAL_AR + r")"), "USD"),
]


def _bal_norm(s: str) -> str:
    return _deaccent("" if s is None else str(s)).lower().strip()


def looks_like_balanz_tenencia(text: str) -> bool:
    """Autodetecta el Resumen de Cuenta de Balanz (vs la Tenencia de Bull Market u
    otro PDF). Exige varias señales del formato para no robarse otra foto (ni el
    export de Órdenes/Movimientos de Balanz)."""
    t = _bal_norm(text)
    return ("posicion consolidada" in t
            and "fecha resumen" in t
            and "especie descripcion cantidad garantia precio valor actual" in t)


def parse_balanz_tenencia(text: str) -> TenenciaSnapshot:
    """Parsea el Resumen de Cuenta de Balanz (texto del PDF) a un TenenciaSnapshot.
    Todo cotiza en $ (pesos) → currency ARS para TODOS los holdings (incluido el FCI
    'BAHUSDA', cuya cuotaparte viene en pesos: no inferir USD por el nombre). Cash:
    Pesos → ARS; Dólares + US Dollar (Cable) → USD (mismo criterio que Bull Market
    junta U$S). value (Valor Actual) es la VERDAD; price_per1 = value/qty."""
    snap = TenenciaSnapshot()
    md = _BAL_DATE_RE.search(_bal_norm(text))
    if md:
        snap.date = f"{md.group(3)}-{md.group(2)}-{md.group(1)}"

    cur_type: Optional[str] = None
    seen = set()
    cash_ars = 0.0
    cash_usd = 0.0
    has_cash = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        n = _bal_norm(line)
        # Cash (bloque Monedas, 2 columnas) — search en cualquier parte de la línea.
        for rx, ccy in _BAL_CASH_RE:
            m = rx.search(n)
            if m:
                v = _num(m.group(1))
                if ccy == "ARS":
                    cash_ars += v
                else:
                    cash_usd += v
                has_cash = True
        # Total de cartera (preámbulo).
        mt = _BAL_TOTAL_RE.match(n)
        if mt:
            snap.total_ars = _num(mt.group(1))
            continue
        # Reset de sección al salir de las tablas de posiciones (footer, header de
        # página, disclaimer p4, titulares p5) → el parser de filas nunca las toca.
        if (n.startswith("balanz capital") or "posicion consolidada" in n
                or n.startswith("informacion de") or n.startswith("distribucion por")
                or n.startswith("la informacion")):
            cur_type = None
            continue
        # Título de sección = UNA sola palabra (Acciones/Bonos/Cedears/Fondos). La
        # línea-resumen "Acciones $ 1.108.291 …" es multi-palabra → no matchea.
        if n in _BAL_SECTION_TYPE and len(line.split()) == 1:
            cur_type = _BAL_SECTION_TYPE[n]
            continue
        if n.startswith("especie"):     # header de columnas
            continue
        if cur_type is None:            # sólo parseamos filas dentro de una sección
            continue
        rm = _BAL_ROW_RE.match(line)
        if not rm:
            continue
        tk = rm.group(1).upper()
        if tk in ("ARS", "USD", "ESPECIE", "TICKER"):
            continue
        qty = _num(rm.group(3))
        price = _num(rm.group(5))
        value = _num(rm.group(6))
        if qty <= 0:
            continue
        # per-1 vs per-100 (bonos), igual que Bull Market. En este export Balanz
        # cotiza los bonos per-1; la detección queda por robustez.
        prod = qty * price
        tol = max(1.0, 0.01 * abs(value))
        per100 = False
        if abs(prod - value) <= tol:
            pass
        elif abs(prod / 100.0 - value) <= tol:
            per100 = True
        else:
            snap.warnings.append(
                f"{tk}: importe ({value:,.2f}) no es cantidad×precio ni /100 — revisar")
        key = (tk, "ARS")
        if key in seen:
            continue
        seen.add(key)
        snap.holdings.append(Holding(
            ticker=tk, asset_type=cur_type, quantity=qty, value=value,
            currency="ARS", price_per1=value / qty, per100=per100,
            name=rm.group(2).strip()[:60]))
    if has_cash:
        snap.cash_ars = round(cash_ars, 2)
        snap.cash_usd = round(cash_usd, 2)
    return snap


# ═══════════════════════════════════════════════════════════════════════════
# IEB — Portafolio (Excel). La FOTO de tenencia de IEB (export "Portafolio ARS" /
# "Portafolio USD"). Mismo rol que PPI/Cocos/BullMarket, con un PLUS: trae PPP
# (precio promedio ponderado = COSTO) → sembramos el costo real, no P&L 0. La
# tenencia es la VERDAD de posiciones/cash de HOY y PISA lo que el historial
# (Movimientos) dejó: si el historial duplicó, la foto lo corrige (ver `over`).
#
# Excel con hojas: Patrimonio (tenencias), Saldos (cash ARS/USD), Cauciones,
# Títulos de crédito. Patrimonio: secciones (Cedears, Acciones, Bonos, Títulos
# públicos, ONs, Otros, FCI); cada una con row de nombre, row de headers
# (Especie|Moneda de emisión|Cantidad|Precio|%|PPP|Var%|Resultado|Actualizado|
# Posición total), filas de tenencia, "Disponible", "Subtotal". Números en
# formato US ('22,680.00' = coma miles, punto decimal). "DOLARUSA" (sección
# Otros) = dólares (cash), no un activo.
#
# Hay DOS archivos (ARS/USD) = la MISMA cartera en dos monedas (mismas especies y
# cantidades). Con UNO alcanza: el que matchea la moneda nativa de la mayoría
# (ARS para carteras de CEDEARs) da precio y PPP en esa moneda.

_IEB_SECTION_TYPE = {
    "cedears": "CEDEAR", "acciones": "STOCK", "bonos": "BOND",
    "titulos publicos": "BOND", "obligaciones negociables": "BOND", "ons": "BOND",
    "letras": "BOND", "fci": "FUND", "fcis": "FUND", "fondos": "FUND",
}

# Encabezados que arrancan la tabla de datos de una sección (prende in_data).
# Tolerante a sinónimos y ':' final: si un 2do bloque de la MISMA clase trae el
# header como 'Ticker'/'Símbolo'/'Papel' en vez del literal 'Especie', igual se lee
# (si no, ese bloque se perdía en SILENCIO y su activo — todavía tenido — quedaba
# como falso 'ausente', candidato a borrado destructivo).
_IEB_DATA_HEADERS = {"especie", "especies", "ticker", "simbolo", "papel", "activo"}


def _ieb_num(v):
    """Número IEB: float directo, o string en formato US ('22,680.00' → 22680.0)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s == "-":
        return None
    s = s.replace(",", "")   # coma = miles (formato US); punto = decimal
    try:
        return float(s)
    except ValueError:
        return None


def looks_like_ieb_portfolio(wb) -> bool:
    """El Portafolio de IEB: workbook openpyxl con hojas 'Patrimonio' + 'Saldos'."""
    try:
        return {"Patrimonio", "Saldos"} <= set(wb.sheetnames)
    except Exception:
        return False


def _ieb_sheet_has_holdings(ws) -> bool:
    """True si una hoja del workbook (ej. 'Cauciones' / 'Títulos de crédito') trae
    filas de tenencia (≥3 celdas no vacías + algún número), no sólo encabezados.
    Sirve para AVISAR que hay activos en hojas que el parser todavía no lee → la
    foto no está completa y NO se debe ofrecer borrado sobre esa lectura parcial."""
    try:
        for r in ws.iter_rows(values_only=True):
            cells = [c for c in (r or ()) if _cell_s(c)]
            if len(cells) >= 3 and any(_ieb_num(c) is not None for c in (r[1:] if r else ())):
                return True
    except Exception:
        pass
    return False


def _ieb_saldos(wb):
    """Cash de la hoja Saldos → (ars, usd). Cada moneda es un bloque con su 'Total'."""
    if "Saldos" not in wb.sheetnames:
        return None, None
    ars = usd = None
    cur = None
    for r in wb["Saldos"].iter_rows(values_only=True):
        c0 = _cell_s(r[0]) if r else ""
        nonempty = [c for c in (r or ()) if _cell_s(c)]
        if len(nonempty) == 1:
            # Marcador de bloque de moneda (celda sola). 'USD Ext.' (cable) = USD;
            # cualquier marcador DESCONOCIDO resetea cur a None → su 'Total' NO se
            # fuga a la moneda del bloque anterior.
            cur = "USD" if c0.startswith("USD") else ("ARS" if c0 == "ARS" else None)
            continue
        if c0 == "Total" and cur:
            v = _ieb_num(r[2] if len(r) > 2 else None)
            if cur == "ARS":
                ars = v
            elif cur == "USD" and v is not None:
                usd = (usd or 0.0) + v   # acumula USD + USD Ext. si vienen ambos
    return ars, usd


def parse_ieb_portfolio(wb) -> TenenciaSnapshot:
    """Portafolio de IEB (workbook openpyxl) → TenenciaSnapshot con COSTO (PPP)."""
    snap = TenenciaSnapshot()
    if "Patrimonio" not in wb.sheetnames:
        snap.warnings.append("El Excel no tiene la hoja 'Patrimonio' — ¿es el Portafolio de IEB?")
        return snap
    rows = list(wb["Patrimonio"].iter_rows(values_only=True))
    snap.date = _ppi_extract_date(rows)   # DD/MM/YYYY o datetime en el preámbulo
    sect = None
    in_data = False
    pending_unknown = None   # label de una sección lone NO reconocida (para avisar)
    saw_data_table = False   # vimos al menos una tabla (encabezado de datos)
    sect_hold_count = 0      # tenencias leídas desde que abrió la sección actual

    def _warn_empty_section():
        # Una sección REAL (no 'Otros') que cerró sin ninguna tenencia legible =
        # lectura PARCIAL (header no reconocido, filas movidas): degrada foto_completa
        # → el caller deja de ofrecer borrado sobre esa lectura dudosa.
        if sect and sect != "OTROS" and sect_hold_count == 0:
            snap.warnings.append(
                f"Una sección de tenencias ({sect}) cerró sin filas legibles — el "
                f"formato del export pudo cambiar; no la usamos para sacar posiciones.")

    for r in rows:
        c0 = _deaccent(_cell_s(r[0])).lower() if (r and r[0] is not None) else ""
        c0h = c0.rstrip(": ").strip()
        nonempty = [c for c in (r or ()) if _cell_s(c)]
        # Encabezado de la tabla de datos (tolerante a sinónimos y ':' final). Si
        # arranca una tabla sin sección reconocida arriba, avisamos (foto incompleta).
        if c0h in _IEB_DATA_HEADERS:
            in_data = True
            saw_data_table = True
            # Arranca una tabla sin sección reconocida arriba (sect=None). Avisamos
            # SIEMPRE, no sólo si el título vino como celda sola (pending_unknown): un
            # título no mapeado con una 2da celda —ej. un total en la col 10— dejaría
            # sect=None sin pending_unknown y sus filas se dropearían EN SILENCIO
            # (lectura parcial → habilitaría borrar por 'ausencia' algo todavía tenido).
            if sect is None:
                snap.warnings.append(
                    f"Sección de IEB no reconocida: '{pending_unknown or '(sin título)'}' "
                    f"— sus tenencias no se leyeron.")
            pending_unknown = None
            continue
        if c0 in _IEB_SECTION_TYPE:
            _warn_empty_section()
            sect = _IEB_SECTION_TYPE[c0]; in_data = False; pending_unknown = None
            sect_hold_count = 0; continue
        if c0 == "otros":
            _warn_empty_section()
            sect = "OTROS"; in_data = False; pending_unknown = None
            sect_hold_count = 0; continue
        if c0 == "subtotal":
            # Cierra la sección: si era real y no leyó nada, avisá; después resetea.
            _warn_empty_section()
            sect = None; in_data = False; sect_hold_count = 0; continue
        if c0 == "disponible":
            continue
        # Fila-label sola (una única celda no vacía) que NO es una sección conocida:
        # resetea sect (evita contaminar el asset_type de la sección previa — un
        # header renombrado dejaría sus filas parseadas con el tipo anterior) y la
        # marca como sospechosa. El preámbulo (Patrimonio total / Tenencia … ) también
        # cae acá pero lo limpia la primera sección real antes de su header.
        if len(nonempty) == 1 and c0:
            sect = None; in_data = False; pending_unknown = _cell_s(r[0]); continue
        if c0 == "" or not sect:
            continue
        if not in_data or not r or r[0] is None:
            continue
        ticker = _cell_s(r[0]).split(" - ")[0].strip().upper()
        qty = _ieb_num(r[2] if len(r) > 2 else None)
        ppp = _ieb_num(r[5] if len(r) > 5 else None)          # precio promedio = COSTO
        value = _ieb_num(r[9] if len(r) > 9 else None)
        ccy = (_cell_s(r[1]).upper() if (len(r) > 1 and _cell_s(r[1])) else "ARS")
        # qty <= 0 se dropea (no abs): una cantidad negativa NO es una tenencia — como
        # los otros parsers de foto — y en override no debe generar una venta espuria.
        if not ticker or qty is None or qty <= 1e-9:
            continue
        if sect == "OTROS":
            # DOLARUSA = dólares (cash), no un activo → no se siembra. Pero CUALQUIER
            # otra especie bajo 'Otros' NO la leemos → lectura parcial: avisamos (así
            # foto_completa=False y no se ofrece borrar por 'ausencia' algo real).
            _nm = _cell_s(r[0]).upper()
            if ticker.startswith("DOLARUSA") or "DOLAR" in _nm:
                continue
            snap.warnings.append(
                f"Sección 'Otros' con un activo que no reconocimos como efectivo "
                f"('{ticker}') — la foto puede estar incompleta, no la usamos para sacar posiciones.")
            continue
        cost_per1 = ppp if (ppp and ppp > 0) else ((value / qty) if value else 0.0)
        if sect == "FUND":
            ticker = _canon_fund_ticker(ticker)   # FCI:<slug> → matchea Movimientos
        snap.holdings.append(Holding(
            ticker=ticker, asset_type=sect, quantity=qty,
            value=value or 0.0, currency=ccy or "ARS",
            price_per1=cost_per1,             # COSTO real (PPP) → P&L correcto
            name=_cell_s(r[0])))
        sect_hold_count += 1
    _warn_empty_section()   # última sección si el archivo no cerró con 'Subtotal'
    # ── Chequeos de completitud (gatean el borrado opt-in en el caller) ──────────
    # Leímos tablas pero 0 tenencias → el layout cambió (hoja renombrada, columnas
    # movidas): la foto es una lectura ROTA, no una cartera vacía real.
    if saw_data_table and not snap.holdings:
        snap.warnings.append(
            "Leímos la hoja 'Patrimonio' pero no pudimos interpretar ninguna tenencia "
            "— el formato del export pudo haber cambiado.")
    # Activos en hojas que el parser todavía NO lee: por EXCLUSIÓN (cualquier hoja que
    # no sea Patrimonio/Saldos con filas de tenencia), no por una lista fija de nombres
    # — así una hoja renombrada o nueva (Cauciones, Títulos de crédito, Opciones, …)
    # igual fuerza foto_completa=False y no se ofrece borrar por 'ausencia'.
    _known_sheets = {"Patrimonio", "Saldos"}
    for _sheet in wb.sheetnames:
        if _sheet not in _known_sheets and _ieb_sheet_has_holdings(wb[_sheet]):
            snap.warnings.append(
                f"El Portafolio trae la hoja '{_sheet}' con tenencias que todavía no "
                f"importamos — no las tocamos.")
    cash_ars, cash_usd = _ieb_saldos(wb)
    if cash_ars is None and cash_usd is None:
        snap.warnings.append("No encontramos los saldos de efectivo en la hoja 'Saldos'.")
    snap.cash_ars, snap.cash_usd = cash_ars, cash_usd
    return snap
