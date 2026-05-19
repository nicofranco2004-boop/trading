"""pricing — constantes de precios para suscripciones Plus y Pro.
═══════════════════════════════════════════════════════════════════════════
Cambiar acá afecta:
  • MP preapproval (monto + frecuencia)
  • Frontend /planes (display)
  • Webhook validation (sanity-check del monto)

Estrategia ARS:
  Cobramos en pesos para evitar números feos por FX. Re-pricing cada 3
  meses. Precios buscan ser ≈ $4 USD (Plus) y ≈ $7 USD (Pro) al blue
  (≈ 1420 ARS/USD), con IVA 21% encima.

Plus (mensual):
  Target marketing-friendly debajo de los ARS 6k psicológicos.
  Base ARS 4.950 + IVA 21% (1.040) = ARS 5.990/mes total.
  Equivalente a ≈ USD 4 al blue 1420 (incluyendo IVA). El display USD
  es aproximado — el precio real cobrado siempre es en ARS.

Pro (mensual):
  USD 6.99 × 1420 ≈ ARS 9.925 → redondeamos a ARS 10.000 base + IVA 21%
  = ARS 12.100/mes total.

Plan anual Pro (15% descuento):
  Base = 102.000 + IVA = ARS 123.420/año total. Ahorro vs mensual: ARS 21.780.

Plus por ahora solo tiene plan mensual. Si se justifica, sumamos anual.
"""

from __future__ import annotations
from typing import Literal

# ─── Plus (mensual) ─────────────────────────────────────────────────────────

PLUS_ARS_MONTHLY_BASE  = 4_950
PLUS_ARS_MONTHLY_IVA   = 1_040   # 21% de 4.950 (redondeo)
PLUS_ARS_MONTHLY_TOTAL = 5_990   # base + IVA — psicológicamente debajo de 6k
PLUS_USD_MONTHLY_DISPLAY = "4"   # aproximado al blue, incluyendo IVA

# ─── Plus (anual, 15% descuento) ────────────────────────────────────────────
# 5.990 × 12 × 0.85 ≈ 61.098 → redondeamos psicológicamente a 59.990 total
# (sub 60k). Equivale a ~5.000/mes = 16.5% off real vs mensual.
PLUS_ARS_ANNUAL_BASE   = 49_580   # 59.990 / 1.21
PLUS_ARS_ANNUAL_IVA    = 10_410
PLUS_ARS_ANNUAL_TOTAL  = 59_990
PLUS_USD_ANNUAL_DISPLAY = "3.50"  # 5.000 / 1420 (promedio mensual del anual)

# ─── Pro (mensual) ──────────────────────────────────────────────────────────

ARS_MONTHLY_BASE  = 10_000   # antes de IVA
ARS_MONTHLY_IVA   = 2_100    # 21% s/ base
ARS_MONTHLY_TOTAL = 12_100   # base + IVA — esto es lo que se cobra

# ─── Pro Anual (15% descuento) ──────────────────────────────────────────────

ARS_ANNUAL_BASE   = 102_000  # 12 × 8.500 = ARS 10.285/mes equiv (sin IVA)
ARS_ANNUAL_IVA    = 21_420   # 21% s/ base
ARS_ANNUAL_TOTAL  = 123_420  # base + IVA — esto es lo que se cobra

# ─── Constantes de cálculo ──────────────────────────────────────────────────

IVA_PCT           = 0.21
ANNUAL_DISCOUNT_PCT = 0.15   # vs 12 meses al precio mensual

# ─── Equivalencia USD (informativa, varia con FX) ──────────────────────────

USD_MONTHLY_DISPLAY = "6.99"  # Pro mensual
USD_ANNUAL_DISPLAY  = "5.99"  # Pro anual (promedio mensual)

# ─── Helper: shape para frontend ────────────────────────────────────────────

Plan = Literal["plus", "pro"]
Period = Literal["monthly", "annual"]


def get_pricing(plan: Plan = "pro", period: Period = "monthly") -> dict:
    """Devuelve dict con todos los valores de un plan + período.

    Plus no tiene plan anual (todavía). Pedir plus+annual cae a plus+monthly.
    """
    if plan == "plus":
        if period == "annual":
            return {
                "plan": "plus",
                "period": "annual",
                "base_ars": PLUS_ARS_ANNUAL_BASE,
                "iva_ars": PLUS_ARS_ANNUAL_IVA,
                "total_ars": PLUS_ARS_ANNUAL_TOTAL,
                "iva_pct": IVA_PCT,
                "monthly_equivalent_ars": PLUS_ARS_ANNUAL_TOTAL // 12,
                "discount_pct": ANNUAL_DISCOUNT_PCT,
                "savings_vs_monthly_ars": (PLUS_ARS_MONTHLY_TOTAL * 12) - PLUS_ARS_ANNUAL_TOTAL,
                "usd_equivalent_monthly": PLUS_USD_ANNUAL_DISPLAY,
            }
        return {
            "plan": "plus",
            "period": "monthly",
            "base_ars": PLUS_ARS_MONTHLY_BASE,
            "iva_ars": PLUS_ARS_MONTHLY_IVA,
            "total_ars": PLUS_ARS_MONTHLY_TOTAL,
            "iva_pct": IVA_PCT,
            "monthly_equivalent_ars": PLUS_ARS_MONTHLY_TOTAL,
            "discount_pct": 0,
            "savings_vs_monthly_ars": 0,
            "usd_equivalent_monthly": PLUS_USD_MONTHLY_DISPLAY,
        }
    # Pro
    if period == "annual":
        return {
            "plan": "pro",
            "period": "annual",
            "base_ars": ARS_ANNUAL_BASE,
            "iva_ars": ARS_ANNUAL_IVA,
            "total_ars": ARS_ANNUAL_TOTAL,
            "iva_pct": IVA_PCT,
            "monthly_equivalent_ars": ARS_ANNUAL_TOTAL // 12,
            "discount_pct": ANNUAL_DISCOUNT_PCT,
            "savings_vs_monthly_ars": (ARS_MONTHLY_TOTAL * 12) - ARS_ANNUAL_TOTAL,
            "usd_equivalent_monthly": USD_ANNUAL_DISPLAY,
        }
    return {
        "plan": "pro",
        "period": "monthly",
        "base_ars": ARS_MONTHLY_BASE,
        "iva_ars": ARS_MONTHLY_IVA,
        "total_ars": ARS_MONTHLY_TOTAL,
        "iva_pct": IVA_PCT,
        "monthly_equivalent_ars": ARS_MONTHLY_TOTAL,
        "discount_pct": 0,
        "savings_vs_monthly_ars": 0,
        "usd_equivalent_monthly": USD_MONTHLY_DISPLAY,
    }


def get_all_plans() -> dict:
    """Shape completo para que el frontend muestre todos los planes."""
    return {
        "plus": {
            "monthly": get_pricing("plus", "monthly"),
            "annual":  get_pricing("plus", "annual"),
        },
        "pro": {
            "monthly": get_pricing("pro", "monthly"),
            "annual":  get_pricing("pro", "annual"),
        },
    }
