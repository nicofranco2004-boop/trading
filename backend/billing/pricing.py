"""pricing — LA fuente de verdad de los precios de Rendi, en pesos.

═══════════════════════════════════════════════════════════════════════════
⚠️  ESTE ARCHIVO ES EL ÚNICO LUGAR DONDE SE ESCRIBE UN PRECIO EN EL BACKEND.

Quien lee de acá:
  • `billing/credits.py` — deriva el precio en USD para el motor de crédito
    (los días que le quedan a quien cambia de plan). NO tiene su propia tabla.
  • `billing/mercadopago.py` — camino legacy, apagado (ver main.py:27634).
  • `GET /api/billing/pricing` → el frontend.

Quien NO lee de acá, y por eso hay que tocarlo A MANO:
  🔴 **El monto que realmente se le cobra a la tarjeta NO está en este repo.**
     Vive en los planes del dashboard de Rebill, y Rendi sólo los referencia
     por id vía las 4 variables `REBILL_PLAN_ID_{PLAN}_{PERIOD}` de Railway
     (ver `billing/rebill.py:_plan_id`). Cambiar los números de acá sin crear
     los planes nuevos en Rebill hace que la página prometa un precio y la
     tarjeta cobre otro.
  🔴 `frontend/src/pages/Planes.jsx` tiene su propia copia en ARS para no
     depender de un fetch para pintar la landing. Si cambiás acá, cambiá allá.

═══════════════════════════════════════════════════════════════════════════
Estrategia ARS:
  Cobramos en pesos (Rebill cobra fee mínimo USD 500/mes si facturás en USD).
  Precio fijo en pesos, re-pricing con anuncio previo.

Precios vigentes desde el 2026-10-15 (antes: Plus 5.990 / Pro 13.990):
  Plus  8.900/mes ·  89.000/año (16,7% off)
  Pro  15.900/mes · 159.000/año (16,7% off)

  El IVA (21%) va INCLUIDO en el total — el total es lo que se cobra.
"""

from __future__ import annotations
from typing import Literal

# ─── Plus ───────────────────────────────────────────────────────────────────

PLUS_ARS_MONTHLY_TOTAL = 8_900    # lo que se cobra
PLUS_ARS_MONTHLY_BASE  = 7_355    # 8.900 / 1,21
PLUS_ARS_MONTHLY_IVA   = 1_545    # 8.900 − 7.355

PLUS_ARS_ANNUAL_TOTAL  = 89_000   # vs 12×8.900=106.800 → 16,7% off
PLUS_ARS_ANNUAL_BASE   = 73_554   # 89.000 / 1,21
PLUS_ARS_ANNUAL_IVA    = 15_446

# ─── Pro ────────────────────────────────────────────────────────────────────

ARS_MONTHLY_TOTAL = 15_900        # lo que se cobra
ARS_MONTHLY_BASE  = 13_140        # 15.900 / 1,21
ARS_MONTHLY_IVA   = 2_760

ARS_ANNUAL_TOTAL  = 159_000       # vs 12×15.900=190.800 → 16,7% off
ARS_ANNUAL_BASE   = 131_405       # 159.000 / 1,21
ARS_ANNUAL_IVA    = 27_595

# ─── Constantes de cálculo ──────────────────────────────────────────────────

IVA_PCT             = 0.21
ANNUAL_DISCOUNT_PCT = 0.167   # vs 12 meses al precio mensual

# ─── Equivalencia USD ───────────────────────────────────────────────────────
# Un solo tipo de cambio declarado para TODO el repo. No es el precio: el
# precio es en pesos. Sirve para (a) mostrar un "≈ USD x" informativo y
# (b) darle al motor de crédito una unidad común.
#
# ⚠️ Lo que le importa al motor de crédito es la PROPORCIÓN entre planes, no
# el valor absoluto: `credits.convert_plan` valúa los días que te quedan al
# rate del plan viejo y los divide por el del nuevo. Con la tabla anterior
# (USD 4 y USD 9) la proporción era 0,444 mientras la de los pesos reales
# (5.990/13.990) era 0,428 — pasar de Plus a Pro te daba de menos. Derivando
# los dos del mismo peso, la proporción es exacta por construcción.
ARS_PER_USD_DISPLAY = 1_500

def _usd(ars: int) -> float:
    """ARS → USD al TC declarado. Sin redondear: redondear rompe la proporción."""
    return ars / ARS_PER_USD_DISPLAY

PLUS_USD_MONTHLY_DISPLAY = f"{_usd(PLUS_ARS_MONTHLY_TOTAL):.2f}"        # ≈ 5.93
PLUS_USD_ANNUAL_DISPLAY  = f"{_usd(PLUS_ARS_ANNUAL_TOTAL) / 12:.2f}"    # ≈ 4.94/mes
USD_MONTHLY_DISPLAY      = f"{_usd(ARS_MONTHLY_TOTAL):.2f}"             # ≈ 10.60
USD_ANNUAL_DISPLAY       = f"{_usd(ARS_ANNUAL_TOTAL) / 12:.2f}"         # ≈ 8.83

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
