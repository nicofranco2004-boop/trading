"""Clasificación de posiciones en SECCIONES de Renta Fija (cross-broker).

Una "sección" es una agrupación de PRESENTACIÓN por (categoría, moneda):
  • Bonos USD / Bonos ARS
  • Letras USD / Letras ARS
  • FCI USD / FCI ARS

Las posiciones NO se mueven de broker (la valuación y el neteo cross-currency
dependen del broker) — esto solo las clasifica para agruparlas en la vista y para
el borrado/restore por sección. La renta variable (acciones/CEDEARs/cripto)
devuelve None (no es renta fija).
"""
from __future__ import annotations
from typing import Optional, Tuple

from .maturity import letra_maturity

_FIXED_INCOME_TYPES = {"BOND", "BONO", "ON", "LETRA", "LECAP"}

CATEGORY_BONO = "BONO"
CATEGORY_LETRA = "LETRA"
CATEGORY_FCI = "FCI"

_CATEGORY_LABEL = {CATEGORY_BONO: "Bonos", CATEGORY_LETRA: "Letras", CATEGORY_FCI: "FCI"}


def _is_known_ar_bond(symbol: str) -> bool:
    try:
        from ai.ar_bonds_metadata import is_known_ar_bond
    except Exception:
        return False
    return bool(is_known_ar_bond(symbol))


def _norm_ccy(currency: Optional[str]) -> str:
    """Moneda de la sección: USD (incluye USDT, la convención interna del sibling)
    o ARS (default)."""
    c = (currency or "").strip().upper()
    return "USD" if c in ("USD", "USDT") else "ARS"


def position_section(asset_type: Optional[str], symbol: Optional[str],
                     currency: Optional[str]) -> Optional[Tuple[str, str]]:
    """Devuelve (categoría, moneda) si la posición es renta fija, o None si no.

    categoría ∈ {BONO, LETRA, FCI}; moneda ∈ {USD, ARS}. La detección de Letra es
    por el patrón del ticker (maturity.letra_maturity), independiente del asset_type
    (IEB/otros no lo etiquetan). FCI = asset_type FUND. Bono = resto de renta fija."""
    at = (asset_type or "").strip().upper()
    sym = (symbol or "").strip().upper()
    ccy = _norm_ccy(currency)

    if at == "FUND":
        return (CATEGORY_FCI, ccy)
    # Letra ANTES que bono: un ticker de letra (S28N5, T13F6…) matchea el patrón
    # aunque no esté en el catálogo de bonos.
    if sym and letra_maturity(sym) is not None:
        return (CATEGORY_LETRA, ccy)
    if at in _FIXED_INCOME_TYPES or _is_known_ar_bond(sym):
        return (CATEGORY_BONO, ccy)
    return None


def section_key(category: str, currency: str) -> str:
    """Clave estable de sección para el dato/endpoint: 'BONO|USD'."""
    return f"{category}|{_norm_ccy(currency)}"


def section_label(category: str, currency: str) -> str:
    """Etiqueta legible: 'Bonos USD'."""
    return f"{_CATEGORY_LABEL.get(category, category)} {_norm_ccy(currency)}"


def parse_section_key(key: str) -> Optional[Tuple[str, str]]:
    """'BONO|USD' → ('BONO','USD'). None si inválida."""
    parts = (key or "").split("|")
    if len(parts) != 2:
        return None
    cat, ccy = parts[0].strip().upper(), parts[1].strip().upper()
    if cat not in (CATEGORY_BONO, CATEGORY_LETRA, CATEGORY_FCI) or ccy not in ("USD", "ARS"):
        return None
    return (cat, ccy)
