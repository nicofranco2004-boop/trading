"""pricing — constantes de precios para suscripción Pro.
═══════════════════════════════════════════════════════════════════════════
Cambiar acá afecta:
  • MP preapproval (monto + frecuencia)
  • Frontend /planes (display)
  • Webhook validation (sanity-check del monto)

Estrategia ARS:
  Cobramos en pesos para evitar números feos por FX. Re-pricing cada 3
  meses (próximo review: agosto 2026). El precio busca ser ≈ $6.99 USD
  al blue (≈ 1420 ARS/USD), con IVA 21% encima.

Cálculo base mensual:
  USD 6.99 × 1420 ≈ ARS 9.925 → redondeamos a ARS 10.000 base + IVA 21%
  = ARS 12.100/mes total.

Plan anual (15% descuento):
  Mensual a precio anual = ARS 10.300 × 12 = ARS 102.000 base + IVA
  = ARS 123.420/año total.
  Ahorro vs mensual: ARS 145.200 (12 × 12.100) − ARS 123.420 = ARS 21.780/año.
"""

from __future__ import annotations
from typing import Literal

# ─── Mensual ────────────────────────────────────────────────────────────────

ARS_MONTHLY_BASE  = 10_000   # antes de IVA
ARS_MONTHLY_IVA   = 2_100    # 21% s/ base
ARS_MONTHLY_TOTAL = 12_100   # base + IVA — esto es lo que se cobra

# ─── Anual (15% descuento) ──────────────────────────────────────────────────

ARS_ANNUAL_BASE   = 102_000  # 12 × 8.500 = ARS 10.285/mes equiv (sin IVA)
ARS_ANNUAL_IVA    = 21_420   # 21% s/ base
ARS_ANNUAL_TOTAL  = 123_420  # base + IVA — esto es lo que se cobra

# ─── Constantes de cálculo ──────────────────────────────────────────────────

IVA_PCT           = 0.21
ANNUAL_DISCOUNT_PCT = 0.15   # vs 12 meses al precio mensual

# ─── Equivalencia USD (informativa, varia con FX) ──────────────────────────

USD_MONTHLY_DISPLAY = "6.99"  # lo que mostramos en /planes
USD_ANNUAL_DISPLAY  = "5.99"  # promedio mensual del plan anual

# ─── Helper: shape para frontend ────────────────────────────────────────────

Period = Literal["monthly", "annual"]

def get_pricing(period: Period = "monthly") -> dict:
    """Devuelve dict con todos los valores de un plan — usado por endpoints
    y frontend para mostrar precio consistente."""
    if period == "annual":
        return {
            "period": "annual",
            "base_ars": ARS_ANNUAL_BASE,
            "iva_ars": ARS_ANNUAL_IVA,
            "total_ars": ARS_ANNUAL_TOTAL,
            "iva_pct": IVA_PCT,
            "monthly_equivalent_ars": ARS_ANNUAL_TOTAL // 12,  # display only
            "discount_pct": ANNUAL_DISCOUNT_PCT,
            "savings_vs_monthly_ars": (ARS_MONTHLY_TOTAL * 12) - ARS_ANNUAL_TOTAL,
            "usd_equivalent_monthly": USD_ANNUAL_DISPLAY,
        }
    return {
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
    """Shape completo para que el frontend muestre los 2 planes side-by-side."""
    return {
        "monthly": get_pricing("monthly"),
        "annual": get_pricing("annual"),
    }
