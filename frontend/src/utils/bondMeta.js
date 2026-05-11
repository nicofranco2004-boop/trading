// bondMeta.js — meta-data por bono. Schema evolutivo.
// ════════════════════════════════════════════════════════════════════════════
// CAMPOS BÁSICOS (todos los bonos):
//   • currency: 'USD' | 'ARS' (CER son ARS-linked vía índice; dollar-linked
//     son ARS pagaderos en pesos a A3500 — distinción llega en Phase 3C)
//   • issuer: 'Soberano AR' | 'Corporativo AR' | 'Tesoro US' | 'ETF US'
//   • maturity: 'YYYY-MM-DD' (null para ETFs sin maturity)
//   • couponRate: % anual TNA. Para soberanos AR canje 2020 es un PROXY
//     promedio; el step-up real va en `couponSchedule` (forma rica, Phase 3B).
//   • couponFreq: 'monthly' | 'quarterly' | 'semiannual' | 'annual' | 'none'
//   • type: 'sovereign' | 'corporate' | 'cer' | 'etf'
//
// CAMPOS OPCIONALES — AMORTIZACIÓN:
//   • amortStart (legacy): fecha del primer pago de amortización para bonos
//     que amortizan en cuotas iguales semestrales.
//   • amortCount (legacy): cantidad total de cuotas. Cada cuota devuelve
//     100/amortCount del face original.
//   • amortSchedule (forma rica, Phase 3B): [{ date: 'YYYY-MM-DD', pct: 7.69 }]
//     — fechas EXACTAS del prospecto con su % de amort. Si está presente,
//     ignora amortStart/amortCount. Validación: suma de pct ≈ 100.
//
// CAMPOS OPCIONALES — STEP-UP (Phase 3B):
//   • couponSchedule: [{ from, to, rate }] — rates por período. La fecha de
//     pago N usa el rate del período que CONTIENE esa fecha. Si está presente,
//     ignora couponRate escalar.
//
// CAMPOS OPCIONALES — METADATA EXTENDIDA (Phase 3B+):
//   • issueDate: 'YYYY-MM-DD' — fecha de emisión. Usado para calcular
//     accrued interest cuando asOf está antes del primer pago en el schedule.
//   • dayCount: '30/360' | 'ACT/365' | 'ACT/360' | 'ACT/ACT-ISDA'
//     Convención de cómputo de días del prospecto. Default 'ACT/365.25'.
//     Bonos AR canje 2020 usan '30/360'.
//   • governingLaw: 'Argentina' | 'NewYork' — para distinguir AL vs GD.
//     Informacional, no afecta el cálculo (sí afecta el riesgo de default).
//   • isin: 'ISIN code' — identifier único del bono.
//
// CAMPOS OPCIONALES — INFLATION-LINKED (Phase 3C):
//   • cerEmissionDate: 'YYYY-MM-DD' — base date del coeficiente CER para
//     calcular el factor de ajuste = CER(t) / CER(emisión).
//   • dollarLinked: true | false — bono ARS ajustado por tipo de cambio
//     A3500 (no por CER).
//
// Fuentes de meta-data:
//   • Soberanos AR: prospecto Ministerio de Economía (Decreto 391/2020 para
//     canje 2020 + anexos con step-up exacto).
//   • ONs: prospectos en CNV.gov.ar
//   • ETFs US: ETF.com / iShares.com / Vanguard 30-day SEC yield JSON.
//
// CICLO DE VIDA:
//   • Phase 1-2: forma legacy (couponRate proxy + amortStart/Count).
//   • Phase 3A (PR #8): bondSchedule.js soporta AMBAS formas — no migra data
//     todavía. La forma rica está documentada y testeada con stubs.
//   • Phase 3B (PR #9): migración de los 11 soberanos AR a forma rica con
//     prospecto-exacto. CER bonds y ONs corporativas siguen en forma legacy.
//   • Phase 3C (PR #10): CER bonds reciben cerEmissionDate + backend CER
//     coefficient endpoint.

import { CANJE_2020_BY_TICKER } from './bondSchedulesAR'

// ════════════════════════════════════════════════════════════════════════════
// SOBERANOS AR — Canje 2020 (Decreto 391/2020 + 676/2020)
// ════════════════════════════════════════════════════════════════════════════
// Cada par AL/GD comparte cronograma de pagos (definido en bondSchedulesAR.js).
// Acá sólo se especifican los campos que VARÍAN: governingLaw, isin, y un
// `couponRate` promedio informativo (para display "TNA ~X%" en BondDetailRow
// cuando no rendere el step-up completo).
//
// Phase 3B: los soberanos consumen couponSchedule + amortSchedule reales del
// prospecto. El `couponRate` ya no se usa para CÁLCULO (el motor matemático
// resuelve con el step-up exacto vía couponSchedule); queda sólo como label.
//
// ISINs: AL (Argentine ley local) y GD (Globales NY ley extranjera) tienen
// ISIN diferentes aunque sus flujos sean idénticos. Esto importa para reportes
// de custodia, no para pricing.

function arSovereign({ ticker, governingLaw, isin, displayRate }) {
  const schedule = CANJE_2020_BY_TICKER[ticker]
  if (!schedule) throw new Error(`No schedule for AR sovereign ${ticker}`)
  return {
    ...schedule,
    currency: 'USD',
    issuer: 'Soberano AR',
    type: 'sovereign',
    governingLaw,
    isin,
    couponRate: displayRate,  // Sólo para display ("TNA promedio aprox")
  }
}

export const BOND_META = {
  // ─── Soberanos AR USD — ley local (Bonares) ───────────────────────────────
  // ISINs ARARGE320xx6 (placeholder hasta verificar exacto)
  AL29: arSovereign({ ticker: 'AL29', governingLaw: 'Argentina', isin: 'ARARGE3209S6', displayRate: 1.0 }),
  AL30: arSovereign({ ticker: 'AL30', governingLaw: 'Argentina', isin: 'ARARGE3209U2', displayRate: 0.75 }),
  AL35: arSovereign({ ticker: 'AL35', governingLaw: 'Argentina', isin: 'ARARGE3209X6', displayRate: 1.875 }),
  AE38: arSovereign({ ticker: 'AE38', governingLaw: 'Argentina', isin: 'ARARGE3209Z1', displayRate: 2.0 }),
  AL41: arSovereign({ ticker: 'AL41', governingLaw: 'Argentina', isin: 'ARARGE3210A3', displayRate: 2.5 }),

  // ─── Soberanos AR USD — ley extranjera (Globales NY) ──────────────────────
  GD29: arSovereign({ ticker: 'GD29', governingLaw: 'NewYork', isin: 'US040114HS92', displayRate: 1.0 }),
  GD30: arSovereign({ ticker: 'GD30', governingLaw: 'NewYork', isin: 'US040114HT75', displayRate: 0.75 }),
  GD35: arSovereign({ ticker: 'GD35', governingLaw: 'NewYork', isin: 'US040114HV40', displayRate: 1.875 }),
  GD38: arSovereign({ ticker: 'GD38', governingLaw: 'NewYork', isin: 'US040114HW23', displayRate: 2.0 }),
  GD41: arSovereign({ ticker: 'GD41', governingLaw: 'NewYork', isin: 'US040114HX06', displayRate: 2.5 }),
  GD46: arSovereign({ ticker: 'GD46', governingLaw: 'NewYork', isin: 'US040114HY88', displayRate: 2.5 }),

  // ─── CER / ARS-Linked ─────────────────────────────────────────────────────
  // Phase 3C: agregamos `cerEmissionDate` para el factor de ajuste del capital.
  // El motor (bondSchedule v3) multiplica cada flujo por:
  //   factor(payment_date) = CER(payment_date) / CER(cerEmissionDate)
  // Si la serie CER no está disponible, fallback graceful: asume factor = 1
  // (comportamiento legacy) con warning visual.
  TX26: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2026-11-09',
          couponRate: 2.0, couponFreq: 'semiannual', dayCount: 'ACT/365',
          cerEmissionDate: '2020-08-04' },
  TX28: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2028-11-09',
          couponRate: 2.25, couponFreq: 'semiannual', dayCount: 'ACT/365',
          cerEmissionDate: '2020-08-04' },
  T2X5: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2025-11-09',
          couponRate: 1.4, couponFreq: 'semiannual', dayCount: 'ACT/365',
          cerEmissionDate: '2020-08-04' },
  // Los TZX son cero-cupón (no pagan intereses periódicos, todo al vencimiento)
  // ajustado por CER desde fecha de emisión hasta vencimiento.
  TZX26: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2026-06-30',
           couponRate: 0, couponFreq: 'none', dayCount: 'ACT/365',
           cerEmissionDate: '2023-06-30' },
  TZX27: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2027-06-30',
           couponRate: 0, couponFreq: 'none', dayCount: 'ACT/365',
           cerEmissionDate: '2023-06-30' },
  TZX28: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2028-06-30',
           couponRate: 0, couponFreq: 'none', dayCount: 'ACT/365',
           cerEmissionDate: '2023-06-30' },

  // ─── ONs corporativas AR (USD) ────────────────────────────────────────────
  YCA0O: { currency: 'USD', issuer: 'YPF', type: 'corporate', maturity: '2026-02-12', couponRate: 8.5, couponFreq: 'semiannual' },
  YCAMO: { currency: 'USD', issuer: 'YPF', type: 'corporate', maturity: '2026-07-15', couponRate: 8.75, couponFreq: 'semiannual' },
  YCAQO: { currency: 'USD', issuer: 'YPF', type: 'corporate', maturity: '2031-01-12', couponRate: 7.0, couponFreq: 'semiannual' },
  YMCFO: { currency: 'USD', issuer: 'YPF', type: 'corporate', maturity: '2028-09-20', couponRate: 9.0, couponFreq: 'semiannual' },
  TLC1O: { currency: 'USD', issuer: 'Telecom Argentina', type: 'corporate', maturity: '2026-08-06', couponRate: 8.5, couponFreq: 'semiannual' },
  TLC5O: { currency: 'USD', issuer: 'Telecom Argentina', type: 'corporate', maturity: '2031-01-15', couponRate: 8.0, couponFreq: 'semiannual' },
  PMCAO: { currency: 'USD', issuer: 'Pampa Energía', type: 'corporate', maturity: '2027-07-21', couponRate: 7.5, couponFreq: 'semiannual' },
  PMCJO: { currency: 'USD', issuer: 'Pampa Energía', type: 'corporate', maturity: '2029-01-24', couponRate: 9.125, couponFreq: 'semiannual' },
  MGC1O: { currency: 'USD', issuer: 'Mastellone Hnos.', type: 'corporate', maturity: '2026-07-03', couponRate: 10.95, couponFreq: 'semiannual' },
  IRC1O: { currency: 'USD', issuer: 'IRSA', type: 'corporate', maturity: '2028-03-23', couponRate: 8.75, couponFreq: 'semiannual' },
  IRC9O: { currency: 'USD', issuer: 'IRSA Propiedades', type: 'corporate', maturity: '2030-09-21', couponRate: 8.5, couponFreq: 'semiannual' },
  GNCAO: { currency: 'USD', issuer: 'Genneia', type: 'corporate', maturity: '2027-01-29', couponRate: 8.75, couponFreq: 'semiannual' },
  DNC1O: { currency: 'USD', issuer: 'Edenor', type: 'corporate', maturity: '2030-04-19', couponRate: 9.75, couponFreq: 'semiannual' },
  CGCDO: { currency: 'USD', issuer: 'CGC', type: 'corporate', maturity: '2025-08-11', couponRate: 9.5, couponFreq: 'semiannual' },
  TGN1O: { currency: 'USD', issuer: 'TGN', type: 'corporate', maturity: '2025-05-26', couponRate: 6.75, couponFreq: 'semiannual' },
  CSC1O: { currency: 'USD', issuer: 'Capex', type: 'corporate', maturity: '2026-11-29', couponRate: 6.875, couponFreq: 'semiannual' },

  // ─── ETFs US bond (diversificados — couponRate proxy del yield distribuido) ─
  TLT:  { currency: 'USD', issuer: 'iShares (BlackRock)', type: 'etf', maturity: null, couponRate: 4.5, couponFreq: 'monthly' },
  IEF:  { currency: 'USD', issuer: 'iShares (BlackRock)', type: 'etf', maturity: null, couponRate: 4.0, couponFreq: 'monthly' },
  SHY:  { currency: 'USD', issuer: 'iShares (BlackRock)', type: 'etf', maturity: null, couponRate: 4.5, couponFreq: 'monthly' },
  AGG:  { currency: 'USD', issuer: 'iShares (BlackRock)', type: 'etf', maturity: null, couponRate: 4.0, couponFreq: 'monthly' },
  BND:  { currency: 'USD', issuer: 'Vanguard',           type: 'etf', maturity: null, couponRate: 4.0, couponFreq: 'monthly' },
  LQD:  { currency: 'USD', issuer: 'iShares (BlackRock)', type: 'etf', maturity: null, couponRate: 4.5, couponFreq: 'monthly' },
  HYG:  { currency: 'USD', issuer: 'iShares (BlackRock)', type: 'etf', maturity: null, couponRate: 7.0, couponFreq: 'monthly' },
  TIP:  { currency: 'USD', issuer: 'iShares (BlackRock)', type: 'etf', maturity: null, couponRate: 3.5, couponFreq: 'monthly' },
}

// Helper para acceder a la meta de un bono dado su ticker.
export function getBondMeta(ticker) {
  if (!ticker) return null
  return BOND_META[ticker.toUpperCase()] || null
}

// Frequency human-readable
export function formatCouponFreq(freq) {
  const map = {
    monthly: 'mensual',
    quarterly: 'trimestral',
    semiannual: 'semestral',
    annual: 'anual',
    none: 'sin cupón (cero-cupón)',
  }
  return map[freq] || freq
}

// Cupones por año según frecuencia (para calcular cupón POR PERÍODO desde TNA).
function periodsPerYear(freq) {
  switch (freq) {
    case 'monthly':    return 12
    case 'quarterly':  return 4
    case 'semiannual': return 2
    case 'annual':     return 1
    default:           return null
  }
}

// Adjetivo de frecuencia en español, en singular ("semestral", "anual", etc.).
function freqAdjective(freq) {
  const map = {
    monthly: 'mensual',
    quarterly: 'trimestral',
    semiannual: 'semestral',
    annual: 'anual',
  }
  return map[freq] || freq
}

// Construye el label legible del cupón para mostrar en la UI.
// Convención: TNA es ANUAL por definición. El adjetivo "semestral / trimestral
// / mensual" indica la FRECUENCIA DE PAGO, no la tasa.
//
// Ejemplos:
//   • { couponRate: 2.0, couponFreq: 'semiannual' }
//       → "cupón 2% TNA (1% por cupón, semestral)"
//   • { couponSchedule: [...] }  (step-up canje 2020)
//       → "cupón step-up 0.125% → 1.75% TNA (semestral)"
//   • { couponFreq: 'none' }
//       → "cero-cupón (paga todo al vencimiento)"
//
// La razón del "(X% por cupón, Y)" es disambiguar para retail: "2% TNA" se
// presta a confusión con "2% por cupón" (sería 4% TNA si es semestral). El
// formato explícito previene errores de interpretación.
export function formatCouponLabel(meta) {
  if (!meta) return ''
  if (meta.couponFreq === 'none' || (!meta.couponRate && !meta.couponSchedule)) {
    return 'cero-cupón (paga todo al vencimiento)'
  }
  const adj = freqAdjective(meta.couponFreq)
  const ppy = periodsPerYear(meta.couponFreq)

  // Step-up: rango min → max (ambos en TNA), frecuencia entre paréntesis.
  if (Array.isArray(meta.couponSchedule) && meta.couponSchedule.length > 1) {
    const rates = meta.couponSchedule.map(p => p.rate)
    const min = Math.min(...rates)
    const max = Math.max(...rates)
    return `cupón step-up ${min}% → ${max}% TNA (${adj})`
  }

  // Cupón fijo: TNA + cupón por período si la freq es conocida.
  const rate = meta.couponRate
  if (ppy && rate) {
    const perPeriod = +(rate / ppy).toFixed(4)
    return `cupón ${rate}% TNA (${perPeriod}% por cupón, ${adj})`
  }
  return `cupón ${rate}% TNA (${adj})`
}

// Type human-readable
export function formatBondType(type) {
  const map = {
    sovereign: 'Soberano',
    corporate: 'Obligación Negociable',
    cer: 'Soberano CER',
    etf: 'ETF de bonos',
  }
  return map[type] || type
}
