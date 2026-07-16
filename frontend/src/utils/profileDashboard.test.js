// Tests del motor de relevancia del Tablero del perfil.
// Fijan: orden por REL, boost por severidad, locks por status, radar (ejes y
// umbral ≥3), topHoldings, y estabilidad del orden (tie-break determinístico).
import { describe, it, expect } from 'vitest'
import { buildProfileDashboard, buildTopHoldings, tradesToActivityPos } from './profileDashboard'

// ── Fixtures: cards con el shape real de profileMatch.js ────────────────────

const READY_CARDS = {
  allocation: {
    status: 'ready',
    declared: { category: 'moderado', categoryLabel: 'Moderado', suggested: { cash: 15, fixed_income: 40, equity: 40, alternative: 5 } },
    actual: { buckets: { cash: 5, fixed_income: 8, equity: 54, alternative: 33 }, totalUsd: 50000 },
    comparison: { deltas: { cash: -10, fixed_income: -32, equity: 14, alternative: 28 }, driftPct: 42 },
  },
  objective: {
    status: 'ready',
    declared: { goal: 'freedom', goalLabel: 'Libertad financiera', timeframe: 'largo', alignedLabel: 'crecimiento', misalignedLabel: 'defensivo' },
    actual: { alignedPct: 87, misalignedPct: 13, totalUsd: 50000 },
  },
  horizon: {
    status: 'ready',
    declared: { horizon: 'short', horizonLabel: 'Meses', expectedLabel: 'estable', riskLabel: 'riesgo' },
    actual: { expectedPct: 13, riskPct: 87, totalUsd: 50000 },
  },
  drawdown: {
    status: 'ready',
    declared: { behavior: 'hold', behaviorLabel: 'Mantengo', impliedTolerance: { min: 20, max: 30, mid: 25, label: '20-30%' } },
    actual: { drawdownPct: 12.5 },
    comparison: 'within',
  },
  concentration: {
    status: 'ready',
    declared: { category: 'moderado', categoryLabel: 'Moderado', typicalRange: { min: 30, max: 50 } },
    actual: { top3Pct: 62, top3Assets: ['BTC', 'NVDA', 'AAPL'], holdingsCount: 9 },
    comparison: 'above',
  },
  style: {
    status: 'ready',
    declared: { style: 'mixed', styleLabel: 'Mixto', typicalRange: { label: '3-8', min: 3, max: 8 } },
    actual: { tradesPerMonth: 1.3, tradesTotal: 8, monthsWindow: 6, inferredStyle: 'passive', inferredStyleLabel: 'Pasivo' },
    comparison: 'mismatch_more_passive',
  },
  liquidity: {
    status: 'ready',
    declared: { liquidity: 'no', liquidityLabel: 'No', safeMinPct: 0 },
    actual: { safePct: 13, volatilePct: 87, buckets: { cash: 5, fixed_income: 8, equity: 54, alternative: 33 } },
    comparison: 'aligned',
  },
  return_exp: {
    status: 'ready',
    declared: { expectation: 'grow', expectationLabel: 'Crecer fuerte', floorReal: 10 },
    actual: { realReturnPct: 6, portfolioReturnPct: 48, inflationPct: 39.6, monthsCounted: 12 },
    comparison: 'below',
  },
}

const POSITIONS = [
  { asset: 'BTC', value_usd: 11000, is_cash: false },
  { asset: 'NVDA', value_usd: 6500, is_cash: false },
  { asset: 'AAPL', value_usd: 4500, is_cash: false },
  { asset: 'ETH', value_usd: 4000, is_cash: false },
  { asset: 'MELI', value_usd: 3000, is_cash: false },
  { asset: 'AL30', value_usd: 2500, is_cash: false },
  { asset: 'ARS', value_usd: 2500, is_cash: true },   // cash: fuera del donut
]

// ── Motor: orden, boosts, disponibilidad ────────────────────────────────────

describe('buildProfileDashboard — usuario completo con mismatches', () => {
  const dash = buildProfileDashboard({ cards: READY_CARDS, positions: POSITIONS })

  it('todos los módulos disponibles y ordenados por rel desc', () => {
    expect(dash.modules).toHaveLength(9)
    expect(dash.availCount).toBe(9)
    const rels = dash.modules.map((m) => m.rel)
    expect(rels).toEqual([...rels].sort((a, b) => b - a))
  })

  it('la concentración severa (top3 62%, above) rankea primera', () => {
    // base 45 + 25 + min(15, 62/5)=12.4 → ~82, por encima del resto
    expect(dash.modules[0].id).toBe('concentration')
    expect(dash.modules[0].rel).toBeGreaterThan(75)
  })

  it('mismatches suben módulos por encima de alineados', () => {
    const byId = Object.fromEntries(dash.modules.map((m) => [m.id, m]))
    // horizon: riskPct 87 → boost ~30 · liquidity aligned → sin boost
    expect(byId.horizon.rel).toBeGreaterThan(byId.liquidity.rel)
    // return below → +30 · drawdown within → sin boost
    expect(byId.return_exp.rel).toBeGreaterThan(byId.drawdown.rel)
  })

  it('radar disponible con los 5 ejes', () => {
    expect(dash.radar).not.toBeNull()
    expect(dash.radar.axes.map((a) => a.label)).toEqual(
      ['Riesgo', 'Horizonte', 'Diversif.', 'Actividad', 'Liquidez']
    )
  })

  it('los ejes del radar reflejan la data real', () => {
    const ax = Object.fromEntries(dash.radar.axes.map((a) => [a.label, a]))
    expect(ax['Riesgo'].declared).toBe(55)          // moderado
    expect(ax['Horizonte'].declared).toBe(25)       // short
    expect(ax['Horizonte'].actual).toBe(87)         // equity 54 + alt 33
    expect(ax['Diversif.'].actual).toBe(38)         // 100 - 62
    expect(ax['Liquidez'].actual).toBe(13)          // safePct
  })

  it('rel en [0, 100] y wide solo en radar/allocation', () => {
    for (const m of dash.modules) {
      expect(m.rel).toBeGreaterThanOrEqual(0)
      expect(m.rel).toBeLessThanOrEqual(100)
      expect(m.wide).toBe(m.id === 'radar' || m.id === 'allocation')
    }
  })

  it('es determinístico (misma entrada → mismo orden)', () => {
    const again = buildProfileDashboard({ cards: READY_CARDS, positions: POSITIONS })
    expect(again.modules.map((m) => m.id)).toEqual(dash.modules.map((m) => m.id))
  })
})

// ── Locks: test incompleto / sin data ───────────────────────────────────────

describe('buildProfileDashboard — test a medias (estilo Tomás)', () => {
  // Solo horizon respondido: allocation/concentration derivan categoría de
  // horizon+drawdown → sin drawdown, no hay categoría → no_profile.
  const cards = {
    allocation: { status: 'no_profile' },
    objective: { status: 'no_profile' },
    horizon: READY_CARDS.horizon,
    drawdown: { status: 'no_data' },
    concentration: { status: 'no_profile' },
    style: { status: 'no_data', declared: { style: 'mixed', styleLabel: 'Mixto' } },
    liquidity: { status: 'no_profile' },
    return_exp: { status: 'no_data', declared: { expectation: 'grow', expectationLabel: 'Crecer', floorReal: 10 } },
  }
  const dash = buildProfileDashboard({ cards, positions: POSITIONS })
  const byId = Object.fromEntries(dash.modules.map((m) => [m.id, m]))

  it('los módulos sin test quedan locked con mensaje de desbloqueo', () => {
    expect(byId.allocation.avail).toBe(false)
    expect(byId.allocation.lock).toMatch(/test/i)
    expect(byId.liquidity.lock).toMatch(/plata pronto/i)
    expect(byId.style.avail).toBe(false)
    expect(byId.style.lock).toMatch(/actividad/i)
  })

  it('el lock por test incompleto rankea ALTO (empuja a completar)', () => {
    // allocation locked por no_profile (base 38 + 22 = 60) supera a
    // horizon ready sin gran mismatch… horizon acá tiene riskPct 87 (+30) = 70.
    // Lo importante: el locked-por-test queda por encima de módulos ready sin boost.
    expect(byId.allocation.rel).toBeGreaterThan(byId.drawdown.rel)
    expect(byId.liquidity.rel).toBeGreaterThan(byId.style.rel)
  })

  it('radar sin ejes suficientes → locked', () => {
    expect(dash.radar).toBeNull()
    expect(byId.radar.avail).toBe(false)
    expect(byId.radar.lock).toMatch(/test/i)
  })

  it('no_data NO recibe el boost de test incompleto', () => {
    // style (no_data, base 32) vs objective (no_profile, base 30 + 22 = 52)
    expect(byId.objective.rel).toBeGreaterThan(byId.style.rel)
  })
})

describe('buildProfileDashboard — fixes del review adversarial', () => {
  it('H1: horizon ready sin liquidity/allocation → buckets desde positions', () => {
    // Test a medias: solo horizon respondido. liquidity/allocation sin actual.
    const cards = {
      horizon: READY_CARDS.horizon,
      allocation: { status: 'no_profile' },
      liquidity: { status: 'no_profile' },
    }
    const dash = buildProfileDashboard({ cards, positions: POSITIONS })
    // El fallback computa buckets desde positions → el módulo horizon tiene
    // fuente de datos y avail⇔renderizable se sostiene.
    expect(dash.buckets).not.toBeNull()
    expect(dash.buckets.equity).toBeGreaterThan(0)
    const horizon = dash.modules.find((m) => m.id === 'horizon')
    expect(horizon.avail).toBe(true)
  })

  it('M2: horizonte LARGO no recibe boost (evita ★ con texto "Coherente")', () => {
    const longHorizon = {
      ...READY_CARDS.horizon,
      declared: { horizon: 'long', horizonLabel: 'Años', expectedLabel: 'crecimiento', riskLabel: 'estable' },
      actual: { expectedPct: 10, riskPct: 90, totalUsd: 50000 },  // 90% en cash+RF
    }
    const dash = buildProfileDashboard({ cards: { ...READY_CARDS, horizon: longHorizon }, positions: POSITIONS })
    const byId = Object.fromEntries(dash.modules.map((m) => [m.id, m]))
    expect(byId.horizon.rel).toBe(40)  // base sin boost
  })

  it("L2: 'below' (menos riesgo del tolerado) no cuenta como mismatch del radar", () => {
    const cards = {
      ...READY_CARDS,
      // solo estados buenos/below → 1 mismatch real (style) < 2 → sin boost radar
      allocation: { ...READY_CARDS.allocation, comparison: { deltas: {}, driftPct: 5 } },
      concentration: { ...READY_CARDS.concentration, comparison: 'below' },
      drawdown: { ...READY_CARDS.drawdown, comparison: 'below' },
      liquidity: { ...READY_CARDS.liquidity, comparison: 'aligned' },
    }
    const dash = buildProfileDashboard({ cards, positions: POSITIONS })
    const radar = dash.modules.find((m) => m.id === 'radar')
    expect(radar.rel).toBe(36)  // base sin boost de mismatches
  })
})

describe('buildProfileDashboard — sin cards (usuario vacío)', () => {
  const dash = buildProfileDashboard({ cards: {}, positions: [] })
  it('nada disponible, todo locked, sin crash', () => {
    expect(dash.availCount).toBe(0)
    expect(dash.radar).toBeNull()
    expect(dash.topHoldings).toEqual([])
    for (const m of dash.modules) {
      expect(m.avail).toBe(false)
      expect(typeof m.lock).toBe('string')
    }
  })
})

// ── Helpers ─────────────────────────────────────────────────────────────────

describe('buildTopHoldings', () => {
  it('agrupa por asset, excluye cash, top 5 con pct del total no-cash', () => {
    const top = buildTopHoldings(POSITIONS)
    expect(top).toHaveLength(5)
    expect(top[0]).toEqual({ name: 'BTC', pct: 35 })   // 11000/31500
    expect(top.map((h) => h.name)).not.toContain('ARS')
  })

  it('suma posiciones repetidas del mismo asset entre brokers', () => {
    const top = buildTopHoldings([
      { asset: 'BTC', value_usd: 500, is_cash: false },
      { asset: 'btc', value_usd: 500, is_cash: false },
    ])
    expect(top).toEqual([{ name: 'BTC', pct: 100 }])
  })

  it('vacío sin posiciones valuables', () => {
    expect(buildTopHoldings([{ asset: 'X', value_usd: 0 }])).toEqual([])
    expect(buildTopHoldings([])).toEqual([])
  })
})

describe('tradesToActivityPos', () => {
  it('mapea las bandas pasivo/mixto/activo', () => {
    expect(tradesToActivityPos(0)).toBe(8)
    expect(tradesToActivityPos(2)).toBe(33)
    expect(tradesToActivityPos(8)).toBe(66)
    expect(tradesToActivityPos(20)).toBe(95)   // cap
  })
  it('null/inválido → null', () => {
    expect(tradesToActivityPos(null)).toBeNull()
    expect(tradesToActivityPos(NaN)).toBeNull()
    expect(tradesToActivityPos(-1)).toBeNull()
  })
})
