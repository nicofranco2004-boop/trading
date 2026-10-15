// pricing — la copia del frontend de los precios de Rendi, y nada más.
// ════════════════════════════════════════════════════════════════════════════
// Vive en `data/` y NO en `pages/Planes.jsx` por el mismo motivo que
// `planCatalog.js`: el muro de "elegí un plan" se monta SIEMPRE (es hermano de
// <Layout/>) y necesita los precios, así que importarlos de la página los
// arrastraba al bundle inicial y anulaba su `lazy()`. Medido: 6 kB de más en
// el arranque para todo visitante, incluido el que nunca se registra.
//
// Planes.jsx re-exporta todo esto para no romper su API previa.

// ─── Pricing en ARS hardcoded (2026-05-31) ──────────────────────────────────
// Cobramos en pesos fijo (no convertido al blue). Razón:
//   1. Rebill cobra fee mínimo USD 500/mes si facturás en USD — inviable
//      hasta tener ~200 users pagos.
//   2. ARS fijo = pricing simple sin sorpresas para el user.
//   3. Cuando el blue suba significativamente (+15%), ajustamos manualmente
//      con anuncio previo. Ver "Playbook de ajuste" en project_rebill_pricing.md
//
// Antes: pricing en USD con conversión arsPriceRounded(usd, tcValuacion) → ARS.
// Ahora: ARS hardcoded como source of truth.
// Vigentes desde el 2026-10-15. Antes: Plus 5.990 / Pro 13.990.
// ⚠️ Esta es LA copia del frontend. La del backend está en
// backend/billing/pricing.py, y el monto que realmente se cobra está en los
// planes del dashboard de Rebill. Los tres tienen que decir lo mismo.
export const PLUS_PRICE_ARS_MONTHLY = '8900'
export const PRO_PRICE_ARS_MONTHLY = '15900'
// Anual con ~26% off vs monthly × 12 — tres meses gratis. Se empuja fuerte
// porque el fijo de USD 0,20 de Rebill se paga 1 vez al año en vez de 12.
export const PLUS_PRICE_ARS_ANNUAL = '79000'   // vs 12×8900=106800 → 26% off
export const PRO_PRICE_ARS_ANNUAL = '139000'   // vs 12×15900=190800 → 27% off

// Mensual equivalente cuando elige plan anual (para display "X/mes · facturado anual")
// Math.round(annual / 12)
export const PLUS_PRICE_ARS_ANNUAL_MONTHLY_EQ = '6583'   // 79000/12 = 6583.33
export const PRO_PRICE_ARS_ANNUAL_MONTHLY_EQ = '11583'   // 139000/12 = 11583.33

// Helper: formatea un número ARS al estilo argentino con punto miles.
//   5990 → "5.990"
//   59900 → "59.900"
//   139900 → "139.900"
export function fmtArs(amount) {
  const n = typeof amount === 'string' ? parseInt(amount, 10) : amount
  if (!Number.isFinite(n)) return String(amount)
  return n.toLocaleString('es-AR')
}

// ─── Descuento del plan anual: SE CALCULA, no se escribe ────────────────────
// El cartel del selector decía "−15%" a mano mientras el descuento real era
// 16,7%: la página vendía peor de lo que Rendi daba. Y el ahorro en pesos no
// se mostraba en ningún lado, que es el número que de verdad convence.
const _n = (v) => (typeof v === 'string' ? parseInt(v, 10) : v)

export function annualSavingsArs(plan) {
  const mensual = _n(plan === 'plus' ? PLUS_PRICE_ARS_MONTHLY : PRO_PRICE_ARS_MONTHLY)
  const anual = _n(plan === 'plus' ? PLUS_PRICE_ARS_ANNUAL : PRO_PRICE_ARS_ANNUAL)
  return mensual * 12 - anual
}

export function annualDiscountPct(plan) {
  const mensual = _n(plan === 'plus' ? PLUS_PRICE_ARS_MONTHLY : PRO_PRICE_ARS_MONTHLY)
  // Math.floor, no Math.round: 16,67% redondeado da 17% y el cartel prometería
  // un poco más de lo que la cuenta da. El cartel nunca promete de más.
  return Math.floor((annualSavingsArs(plan) / (mensual * 12)) * 100)
}

// El cartel del selector es uno para los dos planes. Si algún día los
// descuentos difieren, mostramos el menor: prometer de menos y dar de más.
export const ANNUAL_DISCOUNT_BADGE_PCT = Math.min(
  annualDiscountPct('plus'), annualDiscountPct('pro'),
)
