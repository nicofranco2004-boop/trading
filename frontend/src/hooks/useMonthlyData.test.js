// Tests del builder de reportes mensuales (lógica pura, sin fetch).
// La fuente de truth combina 3 inputs: monthly_entries + operations + snapshots.

import { describe, it, expect } from 'vitest'
import { buildMonthlyReports } from './useMonthlyData.js'

describe('buildMonthlyReports', () => {
  it('devuelve vacío sin data', () => {
    const out = buildMonthlyReports([], [])
    expect(out.years).toEqual([])
    expect(out.hasAnyData).toBe(false)
  })

  it('detecta source=manual cuando hay entry global con capital_inicio + final', () => {
    const out = buildMonthlyReports(
      [{ year: 2026, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 8200, deposits: 100, withdrawals: 0, pnl_realized: 200, pnl_unrealized: 900 }],
      []
    )
    expect(out.years).toHaveLength(1)
    const may = out.years[0].months[0]
    expect(may.source).toBe('manual')
    expect(may.deltaUsd).toBe(8200 - 7000 - 100)  // 1100
    expect(may.deltaPct).toBeCloseTo((1100 / 7000) * 100, 1)
  })

  it('detecta source=partial cuando entry tiene 0 en capital_inicio', () => {
    const out = buildMonthlyReports(
      [{ year: 2026, month: 5, broker: 'global', capital_inicio: 0, capital_final: 0, pnl_realized: 200, pnl_unrealized: 50 }],
      []
    )
    expect(out.years[0].months[0].source).toBe('partial')
  })

  it('deriva pnl_realized desde operations cuando no hay entry', () => {
    const out = buildMonthlyReports(
      [],
      [
        { date: '2026-05-10', op_type: 'Venta', pnl_usd: 250 },
        { date: '2026-05-22', op_type: 'Sell',  pnl_usd: 80 },
        { date: '2026-04-15', op_type: 'Venta', pnl_usd: -40 },
      ]
    )
    expect(out.years).toHaveLength(1)
    const months = out.years[0].months
    const may = months.find(m => m.month === 5)
    const apr = months.find(m => m.month === 4)
    expect(may.source).toBe('derived')
    expect(may.deltaUsd).toBe(330)
    expect(apr.deltaUsd).toBe(-40)
  })

  it('ignora dividendos / intereses / compras / conversiones al derivar', () => {
    const out = buildMonthlyReports(
      [],
      [
        { date: '2026-05-10', op_type: 'Venta',     pnl_usd: 100 },
        { date: '2026-05-11', op_type: 'Compra',    pnl_usd: 0 },     // no cuenta
        { date: '2026-05-12', op_type: 'Dividendo', pnl_usd: 5 },     // no cuenta
        { date: '2026-05-13', op_type: 'Interés',   pnl_usd: 10 },    // no cuenta
        { date: '2026-05-14', op_type: 'CONVERSION', pnl_usd: 0 },    // no cuenta
      ]
    )
    expect(out.years[0].months[0].deltaUsd).toBe(100)
  })

  it('combina manual + derived: meses con entry usan manual, otros derivan', () => {
    const out = buildMonthlyReports(
      [
        { year: 2026, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 8200, deposits: 0, withdrawals: 0, pnl_realized: 1000, pnl_unrealized: 200 },
      ],
      [
        { date: '2026-04-10', op_type: 'Venta', pnl_usd: 50 },
        { date: '2026-05-15', op_type: 'Venta', pnl_usd: 100 },  // mes con entry, no se duplica
      ]
    )
    const months = out.years[0].months
    expect(months).toHaveLength(2)
    const may = months.find(m => m.month === 5)
    const apr = months.find(m => m.month === 4)
    expect(may.source).toBe('manual')
    expect(apr.source).toBe('derived')
    expect(apr.deltaUsd).toBe(50)
  })

  it('agrupa por año en orden descendente', () => {
    const out = buildMonthlyReports(
      [
        { year: 2024, month: 12, broker: 'global', capital_inicio: 5000, capital_final: 5500, pnl_realized: 100 },
        { year: 2026, month: 1,  broker: 'global', capital_inicio: 7000, capital_final: 7100, pnl_realized: 50 },
        { year: 2025, month: 6,  broker: 'global', capital_inicio: 6000, capital_final: 6300, pnl_realized: 75 },
      ],
      []
    )
    expect(out.years.map(y => y.year)).toEqual([2026, 2025, 2024])
  })

  it('ordena meses dentro del año del más reciente al más viejo', () => {
    const entries = [1, 5, 3, 8, 2].map(m => ({
      year: 2025, month: m, broker: 'global', capital_inicio: 5000, capital_final: 5100,
    }))
    const out = buildMonthlyReports(entries, [])
    expect(out.years[0].months.map(m => m.month)).toEqual([8, 5, 3, 2, 1])
  })

  it('calcula bestMonth/worstMonth correctamente entre meses con baseline', () => {
    const out = buildMonthlyReports(
      [
        { year: 2026, month: 1, broker: 'global', capital_inicio: 1000, capital_final: 1050, pnl_realized: 50 },   // +5%
        { year: 2026, month: 2, broker: 'global', capital_inicio: 1050, capital_final: 1230, pnl_realized: 180 }, // +17.1%
        { year: 2026, month: 3, broker: 'global', capital_inicio: 1230, capital_final: 1180, pnl_realized: -50 }, // -4.1%
      ],
      []
    )
    const yr = out.years[0]
    expect(yr.bestMonth.name).toBe('Febrero')
    expect(yr.worstMonth.name).toBe('Marzo')
  })

  it('omite entries por broker que NO sean global', () => {
    const out = buildMonthlyReports(
      [
        { year: 2026, month: 5, broker: 'Binance', capital_inicio: 3000, capital_final: 3100, pnl_realized: 100 },
        { year: 2026, month: 5, broker: 'Cocos',   capital_inicio: 4000, capital_final: 5100, pnl_realized: 1100 },
      ],
      []
    )
    // No hay entry global → si tampoco hay ops, no hay datos
    expect(out.hasAnyData).toBe(false)
  })

  it('status según deltaPct: excellent / positive / neutral / difficult', () => {
    const out = buildMonthlyReports(
      [
        { year: 2026, month: 1, broker: 'global', capital_inicio: 1000, capital_final: 1150 },  // +15% → excellent
        { year: 2026, month: 2, broker: 'global', capital_inicio: 1150, capital_final: 1180 },  // +2.6% → positive
        { year: 2026, month: 3, broker: 'global', capital_inicio: 1180, capital_final: 1180 },  // 0% → neutral
        { year: 2026, month: 4, broker: 'global', capital_inicio: 1180, capital_final: 1100 },  // -6.8% → difficult
      ],
      []
    )
    const ms = out.years[0].months
    expect(ms.find(m => m.month === 1).status).toBe('excellent')
    expect(ms.find(m => m.month === 2).status).toBe('positive')
    expect(ms.find(m => m.month === 3).status).toBe('neutral')
    expect(ms.find(m => m.month === 4).status).toBe('difficult')
  })

  it('derived month no tiene deltaPct (no hay baseline)', () => {
    const out = buildMonthlyReports(
      [],
      [{ date: '2026-05-01', op_type: 'Venta', pnl_usd: 100 }]
    )
    const may = out.years[0].months[0]
    expect(may.source).toBe('derived')
    expect(may.deltaPct).toBe(0)
  })
})
