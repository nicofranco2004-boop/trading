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

// Schedules de amortización de soberanos AR (canje 2020).
// Cada bono amortiza en cuotas iguales semestrales (100/amortCount % del face
// original cada una) a partir de amortStart. Aproximación basada en los
// prospectos públicos — los rates step-up exactos viven en Fase 3.
export const BOND_META = {
  // ─── Soberanos AR USD — ley local ─────────────────────────────────────────
  AL29: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2029-07-09', couponRate: 1.0,   couponFreq: 'semiannual', amortStart: '2024-07-09', amortCount: 10 },
  AL30: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2030-07-09', couponRate: 0.75,  couponFreq: 'semiannual', amortStart: '2024-07-09', amortCount: 13 },
  AL35: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2035-07-09', couponRate: 1.875, couponFreq: 'semiannual', amortStart: '2031-01-09', amortCount: 10 },
  AE38: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2038-01-09', couponRate: 2.0,   couponFreq: 'semiannual', amortStart: '2027-07-09', amortCount: 22 },
  AL41: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2041-07-09', couponRate: 2.5,   couponFreq: 'semiannual', amortStart: '2028-01-09', amortCount: 28 },

  // ─── Soberanos AR USD — ley extranjera ────────────────────────────────────
  GD29: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2029-07-09', couponRate: 1.0,   couponFreq: 'semiannual', amortStart: '2024-07-09', amortCount: 10 },
  GD30: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2030-07-09', couponRate: 0.75,  couponFreq: 'semiannual', amortStart: '2024-07-09', amortCount: 13 },
  GD35: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2035-07-09', couponRate: 1.875, couponFreq: 'semiannual', amortStart: '2031-01-09', amortCount: 10 },
  GD38: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2038-01-09', couponRate: 2.0,   couponFreq: 'semiannual', amortStart: '2027-07-09', amortCount: 22 },
  GD41: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2041-07-09', couponRate: 2.5,   couponFreq: 'semiannual', amortStart: '2028-01-09', amortCount: 28 },
  GD46: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2046-07-09', couponRate: 2.5,   couponFreq: 'semiannual', amortStart: '2024-07-09', amortCount: 44 },

  // ─── CER / ARS-Linked ─────────────────────────────────────────────────────
  TX26: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2026-11-09', couponRate: 2.0, couponFreq: 'semiannual' },
  TX28: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2028-11-09', couponRate: 2.25, couponFreq: 'semiannual' },
  T2X5: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2025-11-09', couponRate: 1.4, couponFreq: 'semiannual' },
  // Los TZX son cero-cupón (no pagan intereses periódicos, todo al vencimiento)
  TZX26: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2026-06-30', couponRate: 0, couponFreq: 'none' },
  TZX27: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2027-06-30', couponRate: 0, couponFreq: 'none' },
  TZX28: { currency: 'ARS', issuer: 'Soberano AR', type: 'cer', maturity: '2028-06-30', couponRate: 0, couponFreq: 'none' },

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
