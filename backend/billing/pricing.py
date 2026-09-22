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

Precios VIGENTES HOY. Los nuevos (Plus 8.900 / Pro 15.900, anual 79.000 y
139.000) llegan el 2026-10-15 y están listos en el commit que este revierte:
  Plus  5.990/mes ·  59.900/año (16,7% off)
  Pro  13.990/mes · 139.900/año (16,7% off)

⚠️ El monto que se cobra de verdad está en el dashboard de Rebill. Estos
números y los de Rebill se cambian EL MISMO DÍA, o la página promete un precio
y la tarjeta cobra otro.

  El anual se empuja fuerte a propósito: el fijo de USD 0,20 que cobra
  Rebill por transacción se paga UNA vez al año en vez de doce, así que el
  fee efectivo baja de ~6% a ~4% — el descuento se paga casi solo.

  El IVA (21%) va INCLUIDO en el total — el total es lo que se cobra.
"""

from __future__ import annotations
from typing import Literal

# ─── Plus ───────────────────────────────────────────────────────────────────

PLUS_ARS_MONTHLY_TOTAL = 5_990    # lo que se cobra
PLUS_ARS_MONTHLY_BASE  = 4_950    # 5.990 / 1,21
PLUS_ARS_MONTHLY_IVA   = 1_040

PLUS_ARS_ANNUAL_TOTAL  = 59_900   # vs 12×5.990=71.880 → 16,7% off
PLUS_ARS_ANNUAL_BASE   = 49_504   # 59.900 / 1,21
PLUS_ARS_ANNUAL_IVA    = 10_396

# ─── Pro ────────────────────────────────────────────────────────────────────

ARS_MONTHLY_TOTAL = 13_990        # lo que se cobra
ARS_MONTHLY_BASE  = 11_562        # 13.990 / 1,21
ARS_MONTHLY_IVA   = 2_428

ARS_ANNUAL_TOTAL  = 139_900       # vs 12×13.990=167.880 → 16,7% off
ARS_ANNUAL_BASE   = 115_620       # 139.900 / 1,21
ARS_ANNUAL_IVA    = 24_280

# ─── Constantes de cálculo ──────────────────────────────────────────────────

IVA_PCT             = 0.21


def annual_discount_pct(plan: str = "pro") -> float:
    """Descuento REAL del plan anual, calculado de los precios.

    Era una constante 0.26 para los dos planes, y los dos ya no coinciden: el
    Plus anual descuenta 26,03% y el Pro 27,15%. Una constante compartida vuelve
    a ser un número escrito a mano que se desincroniza del precio — lo mismo que
    la tabla en dólares que este módulo vino a eliminar.
    """
    if plan == "plus":
        mensual, anual = PLUS_ARS_MONTHLY_TOTAL, PLUS_ARS_ANNUAL_TOTAL
    else:
        mensual, anual = ARS_MONTHLY_TOTAL, ARS_ANNUAL_TOTAL
    return round(1 - anual / (mensual * 12), 4)


# @deprecated — quedó para no romper un caller viejo; usar annual_discount_pct().
# Devuelve el MENOR de los dos: promete de menos, nunca de más.
ANNUAL_DISCOUNT_PCT = min(annual_discount_pct("plus"), annual_discount_pct("pro"))

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
                "discount_pct": annual_discount_pct("plus"),
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
            "discount_pct": annual_discount_pct("pro"),
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
