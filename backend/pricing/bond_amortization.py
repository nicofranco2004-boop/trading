"""Cronogramas de amortización de bonos soberanos AR (canje 2020) + helper de
factor residual.

Por qué existe
─────────────
Los bonos AR que amortizan (AL30/GD30, etc.) NO devuelven el capital al final:
lo devuelven en cuotas a lo largo de la vida del bono. El mercado los cotiza
"por valor nominal RESIDUAL" (el VN que todavía sigue vivo). Pero Rendi
reconstruye la tenencia desde las transacciones (la COMPRA del nominal original)
y NUNCA baja ese nominal cuando entra una amortización (la importa como dividendo
= solo cash). Resultado: el nominal mostrado queda en el ORIGINAL → tenencia y
valuación sobrevaluadas (precio_per_residual × nominal_original > valor real).

Este módulo provee el factor residual R(bono, fecha) ∈ [0, 1] = fracción del
capital nominal ORIGINAL que sigue viva a esa fecha. Con eso, el sweep de
amortización (importing/maturity.py) baja la posición a `nominal_original × R`.

Convención de los datos
───────────────────────
`_AMORT_SCHEDULES[ticker]` = lista de (fecha_iso, fracción_del_capital_ORIGINAL
que devuelve ESA cuota). La suma de todas las cuotas de un bono == 1.0 (100%).
R(fecha) = 1 − Σ(fracción de las cuotas con fecha ≤ fecha_ref).

Fuente: condiciones de emisión del canje 2020 (Decreto 701/2020 e infoleg).
VERIFICADOS al detalle (Rava): AL29/GD29 (10 cuotas de 10%, 1ª 9-ene-2025) y
AL30/GD30 (13 cuotas: 4% el 9-jul-2024 + 12×8%).

PENDIENTE de verificar antes de hardcodear (NO inventar) — ver la nota en
_AMORT_SCHEDULES: GD46 (AMORTIZA HOY → sin su schedule queda sobrevaluado),
AL41/GD41, AE38/GD38, AL35/GD35 (empiezan 2027/2028/2031 → hoy R=1, no-op).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

try:
    from ai.ar_bonds_metadata import _strip_bond_suffix
except Exception:  # pragma: no cover - fallback defensivo si cambia el módulo
    def _strip_bond_suffix(ticker: str) -> str:
        t = (ticker or "").strip().upper()
        if t.endswith(".BA"):
            t = t[:-3]
        if t and t[-1] in ("D", "C") and len(t) > 1:
            # AL30D / AL30C → AL30 (variantes MEP/CCL)
            base = t[:-1]
            if any(ch.isdigit() for ch in base):
                t = base
        return t


# ── AL29 / GD29 (idéntico; difieren en ley local vs NY) ─────────────────────
# Verificado (Rava): "DIEZ (10) cuotas semestrales iguales el 9 de enero y el 9
# de julio, con la primera el 9-ene-2025 y la última el 9-jul-2029" → 10×10%.
_AL29_GD29: List[Tuple[str, float]] = [
    ("2025-01-09", 0.10),
    ("2025-07-09", 0.10),
    ("2026-01-09", 0.10),
    ("2026-07-09", 0.10),
    ("2027-01-09", 0.10),
    ("2027-07-09", 0.10),
    ("2028-01-09", 0.10),
    ("2028-07-09", 0.10),
    ("2029-01-09", 0.10),
    ("2029-07-09", 0.10),
]

# ── AL30 / GD30 (idéntico; sólo difieren en ley local vs NY) ─────────────────
# Verificado (Rava/IOL): 13 cuotas semestrales. 1ª (9-jul-2024) = 4%; las 12
# restantes = 8% c/u → 4% + 12×8% = 100%.
_AL30_GD30: List[Tuple[str, float]] = [
    ("2024-07-09", 0.04),
    ("2025-01-09", 0.08),
    ("2025-07-09", 0.08),
    ("2026-01-09", 0.08),
    ("2026-07-09", 0.08),
    ("2027-01-09", 0.08),
    ("2027-07-09", 0.08),
    ("2028-01-09", 0.08),
    ("2028-07-09", 0.08),
    ("2029-01-09", 0.08),
    ("2029-07-09", 0.08),
    ("2030-01-09", 0.08),
    ("2030-07-09", 0.08),
]

# ticker base (sin sufijo .BA/D/C) → cronograma. SOLO cronogramas VERIFICADOS al
# detalle (fechas + % exactos). Agregar uno nuevo == verificar en fuente primero.
_AMORT_SCHEDULES: Dict[str, List[Tuple[str, float]]] = {
    "AL29": _AL29_GD29,
    "GD29": _AL29_GD29,
    "AL30": _AL30_GD30,
    "GD30": _AL30_GD30,
}

# PENDIENTE de verificar al detalle antes de hardcodear (NO inventar). Datos
# parciales hallados, sin fecha/conteo exacto confirmado:
#   • GD46 — amortiza desde 2025, ~44 cuotas de ~2,27% (Global 2046). AMORTIZA HOY
#     → mientras no esté, GD46 queda sobrevaluado (R=1).
#   • AL41/GD41 — 28 cuotas semestrales de 3,571% (arranca ~2027/2028). R=1 hoy.
#   • AE38/GD38 — arranca ~2027. R=1 hoy.
#   • AL35/GD35 — arranca 2031. R=1 hoy (por eso GD35 con 1117 nominales está bien).
# Fuente autoritativa: Decreto 701/2020 (infoleg) / prospecto CNV.


def is_amortizing_bond(ticker_or_name: Optional[str]) -> bool:
    """True si tenemos cronograma de amortización para este ticker."""
    return _lookup_schedule(ticker_or_name) is not None


def _lookup_schedule(ticker_or_name: Optional[str]) -> Optional[List[Tuple[str, float]]]:
    if not ticker_or_name:
        return None
    base = _strip_bond_suffix(ticker_or_name)
    sched = _AMORT_SCHEDULES.get(base)
    if sched is not None:
        return sched
    # Fallback por nombre: algunos brokers (Cocos) traen el ticker en el nombre.
    up = ticker_or_name.strip().upper()
    for tk, s in _AMORT_SCHEDULES.items():
        if tk in up:
            return s
    return None


def residual_factor(ticker_or_name: Optional[str], as_of_date_iso: str) -> float:
    """Fracción ∈ [0, 1] del capital nominal ORIGINAL que sigue viva a la fecha.

    - 1.0 si el bono no amortizó nada todavía (o no tenemos schedule → no-op).
    - 0.0 si ya amortizó el 100% (bono terminado → la posición debe desaparecer).
    `as_of_date_iso` = 'YYYY-MM-DD'. Cuotas con fecha ≤ as_of_date ya se pagaron.
    """
    sched = _lookup_schedule(ticker_or_name)
    if not sched:
        return 1.0  # sin schedule → no tocamos el nominal (no-op seguro)
    ref = (as_of_date_iso or "")[:10]
    paid = sum(frac for (d, frac) in sched if d <= ref)
    r = 1.0 - paid
    if r < 1e-9:        # ya amortizó el 100% (limpia el ruido de coma flotante)
        return 0.0
    if r > 1:
        return 1.0
    return r
