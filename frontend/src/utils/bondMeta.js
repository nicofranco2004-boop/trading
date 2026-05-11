// bondMeta.js — meta-data básico de cada bono soportado en Fase 1.
// ════════════════════════════════════════════════════════════════════════════
// Por ticker, definimos:
//   • currency: USD | ARS | USD_CER (CER son ARS-linked vía índice)
//   • issuer: 'Soberano AR' | 'Corporativo AR' | 'Tesoro US' | 'ETF US'
//   • maturity: fecha YYYY-MM-DD de vencimiento
//   • couponRate: TNA aproximada (% anual). Para soberanos AR, la stepup
//     real es complicada — guardamos un proxy promedio.
//   • couponFreq: 'semiannual' | 'quarterly' | 'monthly' | 'annual'
//   • type: 'sovereign' | 'corporate' | 'cer' | 'etf'
//
// FASE 1: schedule (cronograma de pagos) vacío. Se registran cupones cobrados
// manualmente desde el ActionMenu. FASE 2: agregar el array `schedule` con
// las fechas y montos exactos por unidad nominal (USD 100 / ARS 1000 según).
//
// Fuentes de meta-data:
//   • Soberanos AR: prospecto Ministerio de Economía
//   • ONs: prospectos en CNV.gov.ar
//   • ETFs US: ETF.com / iShares.com
//
// Si un dato cambia (reestructuración, etc.) se actualiza acá. La data está
// del lado del frontend porque es mostly informativa — el cálculo real
// (TIR, próximo cupón) llega en Fase 2.

export const BOND_META = {
  // ─── Soberanos AR USD — ley local ─────────────────────────────────────────
  AL29: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2029-07-09', couponRate: 1.0, couponFreq: 'semiannual' },
  AL30: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2030-07-09', couponRate: 0.75, couponFreq: 'semiannual' },
  AL35: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2035-07-09', couponRate: 1.875, couponFreq: 'semiannual' },
  AE38: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2038-01-09', couponRate: 2.0, couponFreq: 'semiannual' },
  AL41: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2041-07-09', couponRate: 2.5, couponFreq: 'semiannual' },

  // ─── Soberanos AR USD — ley extranjera ────────────────────────────────────
  GD29: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2029-07-09', couponRate: 1.0, couponFreq: 'semiannual' },
  GD30: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2030-07-09', couponRate: 0.75, couponFreq: 'semiannual' },
  GD35: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2035-07-09', couponRate: 1.875, couponFreq: 'semiannual' },
  GD38: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2038-01-09', couponRate: 2.0, couponFreq: 'semiannual' },
  GD41: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2041-07-09', couponRate: 2.5, couponFreq: 'semiannual' },
  GD46: { currency: 'USD', issuer: 'Soberano AR', type: 'sovereign', maturity: '2046-07-09', couponRate: 2.5, couponFreq: 'semiannual' },

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
