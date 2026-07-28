// Tests del chain de prioridad de FX histórico (audit fix H1).
//
// `resolveHistoricalFx` es una función pura — el wrapper hook `useHistoricalMoney`
// (que combina useCurrency + useFxHistory) se valida implícitamente vía el
// build + smoke en Operations/OperationsMobile. Acá testeamos la lógica pura
// porque es donde puede romperse el chain.

import { describe, it, expect } from 'vitest'
import { resolveHistoricalFx } from './useHistoricalMoney'

const TC_BLUE_ACTUAL = 1466

// Helper: lookup determinístico para los tests
const getRate = (d) => {
  const m = {
    '2024-08-15': 1100,
    '2024-12-31': 1180,
    '2025-06-01': 1310,
    '2025-12-01': 1420,
  }
  return m[d] || null
}

describe('resolveHistoricalFx — chain de prioridad', () => {
  it('USD currency: SIEMPRE devuelve 1 (no convierte)', () => {
    // Aun con stampedFx + dateIso presentes, currency='USD' fuerza 1
    expect(resolveHistoricalFx('USD', TC_BLUE_ACTUAL, { stampedFx: 9999, dateIso: '2024-08-15' }, getRate)).toBe(1)
    expect(resolveHistoricalFx('USD', TC_BLUE_ACTUAL, {}, getRate)).toBe(1)
  })

  it('ARS + stampedFx válido: gana sobre todo lo demás (prioridad 1)', () => {
    // Aun con dateIso que mapea a otro valor, stamped tiene preferencia
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { stampedFx: 1234, dateIso: '2024-08-15' }, getRate)
    expect(r).toBe(1234)
  })

  it('ARS + stampedFx=null: fallback al lookup por fecha (prioridad 2)', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { stampedFx: null, dateIso: '2024-08-15' }, getRate)
    expect(r).toBe(1100) // del map del helper
  })

  it('ARS + stampedFx=0: fallback al lookup (0 no cuenta como válido)', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { stampedFx: 0, dateIso: '2024-08-15' }, getRate)
    expect(r).toBe(1100)
  })

  it('ARS + stampedFx negativo: fallback al lookup', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { stampedFx: -100, dateIso: '2024-08-15' }, getRate)
    expect(r).toBe(1100)
  })

  it('ARS + dateIso sin match: fallback a tcBlue actual (prioridad 3)', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { dateIso: '2030-01-01' }, getRate)
    expect(r).toBe(TC_BLUE_ACTUAL)
  })

  it('ARS + sin dateIso ni stamped: tcBlue actual', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, {}, getRate)
    expect(r).toBe(TC_BLUE_ACTUAL)
  })

  it('ARS + tcBlue inválido (0): último fallback es 1 (no rompe matemática)', () => {
    // Edge: si por alguna razón tcBlue es 0 / negativo, no devolvemos 0
    // (rompería multiplicación). Devolvemos 1 → valor queda en USD nominal.
    expect(resolveHistoricalFx('ARS', 0, {}, getRate)).toBe(1)
    expect(resolveHistoricalFx('ARS', -100, {}, getRate)).toBe(1)
  })

  it('ARS + getRateForDate no es función: cae a tcBlue', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { dateIso: '2024-08-15' }, null)
    expect(r).toBe(TC_BLUE_ACTUAL)
  })

  it('ARS + getRateForDate devuelve 0: cae a tcBlue', () => {
    const r = resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, { dateIso: '2024-08-15' }, () => 0)
    expect(r).toBe(TC_BLUE_ACTUAL)
  })

  it('opts undefined no rompe', () => {
    expect(() => resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, undefined, getRate)).not.toThrow()
    expect(resolveHistoricalFx('ARS', TC_BLUE_ACTUAL, undefined, getRate)).toBe(TC_BLUE_ACTUAL)
  })
})

// ─── Casos reales: la razón de existir de este fix ───────────────────────────

describe('resolveHistoricalFx — casos reales (audit fix H1)', () => {
  it('trade cerrado en agosto 2024 (blue=1100) NO se infla al blue de hoy', () => {
    // Antes del fix: $200 pnl_usd × 1466 (blue actual) = $293,200 ARS — INFLADO
    // Después del fix: usa el blue stampeado al cierre = $200 × 1100 = $220,000 ARS
    const fx = resolveHistoricalFx('ARS', 1466, { stampedFx: 1100, dateIso: '2024-08-15' }, getRate)
    expect(fx).toBe(1100)
    const pnlArs = 200 * fx
    expect(pnlArs).toBe(220_000)  // realista
  })

  it('trade sin fx stampeado pero con date: usa lookup', () => {
    // Operaciones legacy (importadas antes del Phase D backend) sin fx_to_usd
    const fx = resolveHistoricalFx('ARS', 1466, { dateIso: '2025-06-01' }, getRate)
    expect(fx).toBe(1310)
  })

  it('toggle en USD: el chain entero queda neutralizado (no convierte)', () => {
    // El user mira en USD → siempre devolvemos 1, el value canónico se preserva
    const fx = resolveHistoricalFx('USD', 1466, { stampedFx: 1100, dateIso: '2024-08-15' }, getRate)
    expect(fx).toBe(1)
  })
})

// ─── convert-then-sum: el total tiene que coincidir con sus filas ────────────
//
// El bug que arreglan estos tests (reporte real YPFD/BMB): el header de un grupo
// convertía el total USD al dólar de HOY mientras cada fila usaba el FX de SU
// fecha → un grupo de UN SOLO trade mostraba dos números distintos
// (header +$147.007 vs su única fila +$135.444: mismo pnl_usd, dos dólares).

// Réplica pura de `sumConvertedAt` del hook (el hook necesita CurrencyProvider).
function sumConvertedAt(rows, getUsd, currency, tcBlue, getRateForDate) {
  let total = 0
  for (const r of (rows || [])) {
    const usd = getUsd(r)
    if (usd == null || !Number.isFinite(usd)) continue
    const fx = resolveHistoricalFx(
      currency, tcBlue,
      { stampedFx: r?.fx_to_usd, dateIso: r?.date, rowCurrency: r?.currency },
      getRateForDate,
    )
    total += currency === 'ARS' ? usd * fx : usd
  }
  return total
}

describe('convert-then-sum — invariante total === Σ filas', () => {
  const YPFD = { date: '2026-04-22', pnl_usd: 90.1189, fx_to_usd: null }
  const BLUE_FECHA = 1502.95
  const MEP_HOY = 1631.26
  const rate = (d) => (d === '2026-04-22' ? BLUE_FECHA : null)

  it('grupo de UN trade: el total es exactamente el de la fila', () => {
    const fila = 90.1189 * BLUE_FECHA
    const total = sumConvertedAt([YPFD], o => o.pnl_usd, 'ARS', MEP_HOY, rate)
    expect(total).toBeCloseTo(fila, 6)
    // y NO el número viejo del header (pnl_usd × dólar de hoy)
    expect(total).not.toBeCloseTo(90.1189 * MEP_HOY, 0)
  })

  it('el modo viejo inflaba en la razón entre los dos dólares', () => {
    const viejo = 90.1189 * MEP_HOY
    const nuevo = sumConvertedAt([YPFD], o => o.pnl_usd, 'ARS', MEP_HOY, rate)
    expect(viejo / nuevo).toBeCloseTo(MEP_HOY / BLUE_FECHA, 6)
  })

  it('multi-fecha: cada trade con SU FX (stamped o lookup), no un promedio', () => {
    const rows = [
      { date: '2026-04-22', pnl_usd: 100, fx_to_usd: null },   // lookup
      { date: '2024-08-15', pnl_usd: 50, fx_to_usd: 1100 },    // stamped
    ]
    const total = sumConvertedAt(rows, o => o.pnl_usd, 'ARS', MEP_HOY, rate)
    expect(total).toBeCloseTo(100 * BLUE_FECHA + 50 * 1100, 6)
  })

  it('mezcla ARS y USD en el mismo grupo: cada una con su propio FX', () => {
    // Caso del subtotal por día en mobile, que antes aplicaba el fx de la PRIMERA
    // op con fx>0 a TODO el subtotal.
    const rows = [
      { date: '2026-04-22', pnl_usd: 10, fx_to_usd: 1, currency: 'USD' },   // trade USD
      { date: '2026-04-22', pnl_usd: 20, fx_to_usd: 1500, currency: 'ARS' }, // trade ARS
    ]
    // La op USD se lleva a pesos por el BLUE de su fecha (no por su fx=1).
    expect(sumConvertedAt(rows, o => o.pnl_usd, 'ARS', MEP_HOY, rate))
      .toBeCloseTo(10 * BLUE_FECHA + 20 * 1500, 6)
  })

  // ⚠️ REGRESIÓN CAZADA EN REVIEW: el backend estampa fx_to_usd = tc_venta, que
  // vale 1.0 en las ventas en DÓLARES (no hubo conversión). Si el front tomara
  // ese 1.0 como "ARS por USD", un P&L de USD 10.000 se mostraría como "$10.000"
  // (~1500× menos) en TODA cuenta USD (Binance, Schwab, Wallbit, Balanz Intl).
  it('venta en USD: el stamp 1.0 se IGNORA y se usa el blue de la fecha', () => {
    const fx = resolveHistoricalFx('ARS', MEP_HOY,
      { stampedFx: 1, dateIso: '2026-04-22', rowCurrency: 'USD' }, rate)
    expect(fx).toBe(BLUE_FECHA)
    expect(10000 * fx).toBeCloseTo(10000 * BLUE_FECHA, 6)   // NO 10.000 pesos
  })

  it('venta en ARS: el stamp SÍ manda (reconstruye el nominal real en pesos)', () => {
    const fx = resolveHistoricalFx('ARS', MEP_HOY,
      { stampedFx: 1434.18, dateIso: '2026-04-22', rowCurrency: 'ARS' }, rate)
    expect(fx).toBe(1434.18)
  })

  it('sin rowCurrency (ops viejas) el stamp se sigue respetando', () => {
    const fx = resolveHistoricalFx('ARS', MEP_HOY,
      { stampedFx: 1434.18, dateIso: '2026-04-22' }, rate)
    expect(fx).toBe(1434.18)
  })

  it('en USD el total es la suma cruda', () => {
    const rows = [YPFD, { date: '2024-08-15', pnl_usd: -10, fx_to_usd: 1100 }]
    expect(sumConvertedAt(rows, o => o.pnl_usd, 'USD', MEP_HOY, rate)).toBeCloseTo(80.1189, 6)
  })

  it('filas sin P&L no rompen el total', () => {
    const rows = [YPFD, { date: '2026-05-01', pnl_usd: null }, { date: '2026-05-02' }]
    expect(sumConvertedAt(rows, o => o.pnl_usd, 'ARS', MEP_HOY, rate))
      .toBeCloseTo(90.1189 * BLUE_FECHA, 6)
  })
})
