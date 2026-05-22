"""ar_bonds_metadata — metadata de bonos AR para enriquecer packets de IA.
═══════════════════════════════════════════════════════════════════════════
El Coach IA históricamente trataba bonos AR como acciones — sin conocer
maturity, mecánica CER, ley aplicable o paridad. Eso causaba respuestas
genéricas que ignoraban la dinámica específica de cada instrumento.

Este módulo define metadata estructurada por ticker. Se inyecta en los
packets de IA cuando hay bonos en cartera para que el LLM responda con
contexto real ("AL30 vence en julio 2030, ley local, step-up de cupones",
no "AL30 es un activo argentino").

Fuente de datos: prospectos oficiales + bolsar.com + iamc.com.ar.
Mantenimiento: cuando se agregue un bono nuevo a AR_BONDS_DATA912 en
main.py, agregar también acá. Las maturities están fixadas en la emisión
— no cambian salvo restructuring.

Ámbito: SOLO soberanos AR (AL/GD/AE/AL41) + bonos CER (TX/T2X/TZX).
Bonos corporativos / ONs se manejan vía AR_BONDS_DATA912 sin metadata
detallada (los corporates son menos consultados por el bot).
"""

from __future__ import annotations
from typing import Dict, Any, Optional

# ─── Metadata por bono ─────────────────────────────────────────────────────
# Estructura por entry:
#   kind: tipo de bono (soberano_usd | cer | letras)
#   maturity: fecha de vencimiento (YYYY-MM-DD)
#   law: jurisdicción legal aplicable (ley_local | ley_ny)
#   currency_denom: moneda en la que se denomina el cupón/capital
#   indexed_by: índice de ajuste (CER, dólar link, etc.) o None
#   step_up: True si los cupones suben a lo largo de la vida del bono
#   description: contexto breve para el LLM

_BOND_METADATA: Dict[str, Dict[str, Any]] = {
    # ─── Soberanos USD ley local (AL) — reestructurados 2020 ──────────────
    # Cupón step-up: arranca bajo y sube en escalones. Mecánica única que
    # el LLM debe conocer para razonar yields.
    "AL29": {
        "kind": "soberano_usd",
        "maturity": "2029-07-09",
        "law": "ley_local",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Bonar 2029 USD ley local. Cupón step-up (0.5%→1.0%→1.5%→1.75%). El más corto del tramo AL — duration baja, sensible a el riesgo crédito AR pero menos volátil que largos.",
    },
    "AL30": {
        "kind": "soberano_usd",
        "maturity": "2030-07-09",
        "law": "ley_local",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Bonar 2030 USD ley local. EL BONO MÁS LÍQUIDO de Argentina (mayor volumen MEP/CCL). Referencia para dolarizar dentro del país. Step-up de cupones hasta 1.75%.",
    },
    "AL35": {
        "kind": "soberano_usd",
        "maturity": "2035-07-09",
        "law": "ley_local",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Bonar 2035 USD ley local. Duration intermedia, más sensible a expectativas de tasas y riesgo país que AL30.",
    },
    "AE38": {
        "kind": "soberano_usd",
        "maturity": "2038-01-09",
        "law": "ley_local",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Bonar 2038 USD ley local. Largo, alta sensibilidad a duration. Cupón fijo 5% post-step-up.",
    },
    "AL41": {
        "kind": "soberano_usd",
        "maturity": "2041-07-09",
        "law": "ley_local",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Bonar 2041 USD ley local. El más largo del tramo AL. Alta duration, alta volatilidad — apuesta a normalización del riesgo país AR.",
    },
    # ─── Soberanos USD ley NY (GD) — equivalentes a AL pero jurisdicción NY
    # Pari passu vs AL pero con protección legal extranjera. Suelen cotizar
    # ~2-3% por encima de AL (paridad más alta) por esa diferencia legal.
    "GD29": {
        "kind": "soberano_usd",
        "maturity": "2029-07-09",
        "law": "ley_ny",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Global 2029 USD ley NY. Mismo flujo que AL29 pero con protección legal extranjera. Suele cotizar premium vs AL29.",
    },
    "GD30": {
        "kind": "soberano_usd",
        "maturity": "2030-07-09",
        "law": "ley_ny",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Global 2030 USD ley NY. EL REFERENCE BOND de Argentina internacionalmente — el que mira el mercado para riesgo país. Suele cotizar 3-5pp encima del AL30 por ley NY.",
    },
    "GD35": {
        "kind": "soberano_usd",
        "maturity": "2035-07-09",
        "law": "ley_ny",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Global 2035 USD ley NY. Versión ley NY del AL35. Mayor liquidez internacional.",
    },
    "GD38": {
        "kind": "soberano_usd",
        "maturity": "2038-01-09",
        "law": "ley_ny",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Global 2038 USD ley NY. Largo, ley extranjera. Apuesta a recuperación AR + protección legal.",
    },
    "GD41": {
        "kind": "soberano_usd",
        "maturity": "2041-07-09",
        "law": "ley_ny",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Global 2041 USD ley NY. El más largo del tramo GD. Máxima duration, máxima sensibilidad a riesgo país.",
    },
    "GD46": {
        "kind": "soberano_usd",
        "maturity": "2046-07-09",
        "law": "ley_ny",
        "currency_denom": "USD",
        "indexed_by": None,
        "step_up": True,
        "description": "Global 2046 USD ley NY. Bonos a 25 años. Apuesta especulativa a recuperación de largo plazo.",
    },
    # ─── CER (TX/T2X/TZX) — capital ajusta por inflación AR ───────────────
    # Mecánica crítica que el LLM debe conocer: el capital se actualiza
    # diariamente por CER (Coeficiente de Estabilización de Referencia, ~IPC
    # diario). Eso significa que el rendimiento real es lo declarado en el
    # cupón; la inflación se "agrega" al capital. Tasa real ≈ rendimiento.
    "TX26": {
        "kind": "cer",
        "maturity": "2026-11-09",
        "law": "ley_local",
        "currency_denom": "ARS",
        "indexed_by": "CER",
        "step_up": False,
        "description": "Boncer 2026. Capital ajusta diariamente por CER (≈inflación AR). El cupón es tasa REAL — rendimiento sobre inflación. Cobertura natural contra inflación en pesos.",
    },
    "TX28": {
        "kind": "cer",
        "maturity": "2028-11-09",
        "law": "ley_local",
        "currency_denom": "ARS",
        "indexed_by": "CER",
        "step_up": False,
        "description": "Boncer 2028. CER-linked. Plazo medio. Útil para acompañar inflación AR de 2-3 años.",
    },
    "T2X5": {
        "kind": "cer",
        "maturity": "2025-11-09",
        "law": "ley_local",
        "currency_denom": "ARS",
        "indexed_by": "CER",
        "step_up": False,
        "description": "Bono CER corto 2025. Vencimiento próximo — sensible al carry de corto plazo + dinámica de tasas reales.",
    },
    "TZX26": {
        "kind": "cer",
        "maturity": "2026-06-30",
        "law": "ley_local",
        "currency_denom": "ARS",
        "indexed_by": "CER",
        "step_up": False,
        "description": "Boncer Cero 2026. Cero cupón (no paga renta intermedia), ajuste 100% por CER. Capital efectivo crece con inflación.",
    },
    "TZX27": {
        "kind": "cer",
        "maturity": "2027-06-30",
        "law": "ley_local",
        "currency_denom": "ARS",
        "indexed_by": "CER",
        "step_up": False,
        "description": "Boncer Cero 2027. Cero cupón CER-linked. Duration más alta que TZX26 — mayor sensibilidad a tasas reales.",
    },
    "TZX28": {
        "kind": "cer",
        "maturity": "2028-06-30",
        "law": "ley_local",
        "currency_denom": "ARS",
        "indexed_by": "CER",
        "step_up": False,
        "description": "Boncer Cero 2028. Cero cupón CER. El más largo del tramo TZX. Máxima sensibilidad a tasa real.",
    },
}


def is_known_ar_bond(ticker: str) -> bool:
    """Devuelve True si el ticker tiene metadata detallada en este módulo.

    NO incluye corporates ni todos los bonos AR — solo los soberanos USD
    (AL/GD/AE/AL41) y CER (TX/T2X/TZX). Estos son los más consultados.

    Acepta ticker con o sin sufijo .BA — lo strippea antes del lookup.
    """
    if not ticker:
        return False
    base = str(ticker).upper().strip().replace(".BA", "")
    return base in _BOND_METADATA


def get_bond_metadata(ticker: str) -> Optional[Dict[str, Any]]:
    """Devuelve metadata del bono o None.

    El dict devuelto es seguro de mutar (copy).
    """
    if not ticker:
        return None
    base = str(ticker).upper().strip().replace(".BA", "")
    md = _BOND_METADATA.get(base)
    if md is None:
        return None
    return dict(md)  # shallow copy


def enrich_bond_holdings(positions: list) -> list:
    """Detecta posiciones de bonos AR conocidos y devuelve lista enriquecida
    con metadata. Solo retorna posiciones que SÍ son bonos conocidos.

    Útil para inyectar al packet de IA un bloque `ar_bond_holdings` con
    info que el LLM puede usar para narrar correctamente.

    Args:
        positions: lista de posiciones (dicts con asset, quantity, etc.)

    Returns:
        Lista de dicts {ticker, position_qty, metadata: {...}}
    """
    enriched = []
    for p in positions or []:
        if not isinstance(p, dict):
            continue
        ticker = p.get("asset")
        if not ticker:
            continue
        md = get_bond_metadata(ticker)
        if not md:
            continue
        enriched.append({
            "ticker": str(ticker).upper().strip().replace(".BA", ""),
            "position_qty": float(p.get("quantity") or 0),
            "metadata": md,
        })
    return enriched
