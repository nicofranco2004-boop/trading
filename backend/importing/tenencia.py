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
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        sm = _SECTION_RE.match(line)
        if sm:
            cur_type = _SECTION_TYPE.get(_norm(sm.group(1)))
            ccy = _norm(sm.group(2))
            cur_ccy = "USD" if ("u$s" in ccy or "usd" in ccy or "dolar" in ccy) else "ARS"
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
    return snap
