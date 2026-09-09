import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { buildAiSummary } from './aiSummary.js'

// `/api/monthly` devuelve la fila sintética `global` (que ya es la suma) JUNTO a
// las por-broker. La forma real del payload: dos brokers + su global.
const mes = (broker, year, month, over = {}) => ({
  broker, year, month,
  deposits: 0, withdrawals: 0, pnl_realized: 0, pnl_unrealized: 0,
  capital_inicio: 0, capital_final: 0,
  ...over,
})

const MONTHLY = [
  mes('Cocos',   2026, 1, { pnl_realized: 300, deposits: 1000, withdrawals: 100 }),
  mes('Balanz',  2026, 1, { pnl_realized: 200, deposits: 500,  withdrawals: 0 }),
  mes('global',  2026, 1, { pnl_realized: 500, deposits: 1500, withdrawals: 100 }),
  mes('Cocos',   2026, 2, { pnl_realized: -50, deposits: 0,    withdrawals: 200 }),
  mes('Balanz',  2026, 2, { pnl_realized: 150, deposits: 0,    withdrawals: 0 }),
  mes('global',  2026, 2, { pnl_realized: 100, deposits: 0,    withdrawals: 200 }),
]

describe('buildAiSummary — lo que viaja al modelo en cada mensaje', () => {
  it('no cuenta dos veces: sólo la fila global, que ya es la suma', () => {
    const s = buildAiSummary([], MONTHLY)
    // Sumando TODAS las filas daban 1200 / 3000 / 600 — exactamente ×2.
    expect(s.realized_pnl_usd_lifetime).toBe(600)
    expect(s.deposits_lifetime).toBe(1500)
    expect(s.withdrawals_lifetime).toBe(300)
  })

  it('months_tracked cuenta meses, no filas', () => {
    // 6 filas, 2 meses. Con 4 brokers el modelo leía "48 meses de historia".
    expect(buildAiSummary([], MONTHLY).months_tracked).toBe(2)
  })

  it('coincide con el KPI del Dashboard, que filtra el mismo `global`', () => {
    const dashboard = MONTHLY
      .filter(m => m.broker === 'global')
      .reduce((s, m) => s + (m.pnl_realized || 0), 0)
    expect(buildAiSummary([], MONTHLY).realized_pnl_usd_lifetime).toBe(dashboard)
  })

  it('las posiciones se parten por is_cash, y el cash no cuenta como invertido', () => {
    const s = buildAiSummary([
      { invested: 1000, is_cash: false },
      { invested: 500, is_cash: false },
      { invested: 250, is_cash: true },
    ], [])
    expect(s.total_invested_usd).toBe(1500)
    expect(s.open_positions_count).toBe(2)
    expect(s.cash_lines_count).toBe(1)
  })

  it('aguanta null/undefined sin romper el contexto del chat', () => {
    const s = buildAiSummary(null, null)
    expect(s.realized_pnl_usd_lifetime).toBe(0)
    expect(s.months_tracked).toBe(0)
    expect(s.open_positions_count).toBe(0)
  })
})

describe('el resumen se arma en UN solo lugar', () => {
  // No alcanza con haber unificado las dos copias hoy: el bug original fue
  // exactamente eso, dos `buildSummary` idénticas que dejaron de serlo. Si
  // alguien vuelve a armar el resumen dentro de una pantalla, esto se pone rojo.
  const SUPERFICIES = [
    'src/pages/RendiAI.jsx',
    'src/components/ai/AICoachDrawer.jsx',
  ]

  it.each(SUPERFICIES)('%s importa el resumen en vez de rearmarlo', (ruta) => {
    const src = readFileSync(ruta, 'utf8')
    expect(src).toMatch(/import \{[^}]*buildAiSummary[^}]*\} from/)
    expect(src).not.toMatch(/function\s+buildSummary\s*\(/)
    // Ni la suma CRUDA de las filas mensuales, que es de donde salía el ×2.
    // Se prohíbe `monthly.reduce(` y `(monthly || []).reduce(` — o sea reducir
    // sin filtrar. Un `monthly.filter(...).reduce(...)` legítimo pasa.
    expect(src).not.toMatch(/monthly\s*\.reduce\(/)
    expect(src).not.toMatch(/\(\s*monthly\s*\|\|\s*\[\]\s*\)\s*\.reduce\(/)
  })
})
