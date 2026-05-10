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

  it('ordena meses dentro del año cronológicamente (Enero → Diciembre, lectura natural)', () => {
    const entries = [1, 5, 3, 8, 2].map(m => ({
      year: 2025, month: m, broker: 'global', capital_inicio: 5000, capital_final: 5100,
    }))
    const out = buildMonthlyReports(entries, [])
    expect(out.years[0].months.map(m => m.month)).toEqual([1, 2, 3, 5, 8])
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

  // ─── Sparkline desde snapshots ───────────────────────────────────────────
  it('asocia sparkline al mes cuando hay >=2 snapshots dentro del rango', () => {
    const out = buildMonthlyReports(
      [{ year: 2026, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 8200 }],
      [],
      [
        { date: '2026-05-01', total_value: 7000 },
        { date: '2026-05-15', total_value: 7600 },
        { date: '2026-05-30', total_value: 8200 },
      ]
    )
    const may = out.years[0].months[0]
    expect(may.sparkline).toHaveLength(3)
    expect(may.sparkline[0].value).toBe(7000)
    expect(may.sparkline[2].value).toBe(8200)
  })

  it('sparkline=null cuando hay solo 1 snapshot en el mes', () => {
    const out = buildMonthlyReports(
      [{ year: 2026, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 8200 }],
      [],
      [{ date: '2026-05-15', total_value: 7800 }]
    )
    expect(out.years[0].months[0].sparkline).toBeNull()
  })

  it('sparkline ordenada cronológicamente aunque snapshots vengan desordenados', () => {
    const out = buildMonthlyReports(
      [{ year: 2026, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 8200 }],
      [],
      [
        { date: '2026-05-30', total_value: 8200 },
        { date: '2026-05-01', total_value: 7000 },
        { date: '2026-05-15', total_value: 7600 },
      ]
    )
    const sp = out.years[0].months[0].sparkline
    expect(sp.map(p => p.date)).toEqual(['2026-05-01', '2026-05-15', '2026-05-30'])
  })

  // ─── YTD live: año en curso usa snapshot reciente como endUsd ────────────
  it('año en curso: usa el último snapshot como endUsd (alineado al Dashboard)', () => {
    const todayYear = new Date().getFullYear()
    const out = buildMonthlyReports(
      [{ year: todayYear, month: 1, broker: 'global', capital_inicio: 5000, capital_final: 5500, deposits: 100 }],
      [],
      // Snapshot mucho más reciente que el último capital_final manual
      [{ date: `${todayYear}-12-15`, total_value: 7200 }]
    )
    const yr = out.years[0]
    expect(yr.endSource).toBe('live')
    expect(yr.endUsd).toBe(7200)
    // YTD = endUsd - startUsd - flows = 7200 - 5000 - 100 = 2100
    expect(yr.ytdUsd).toBe(2100)
    expect(yr.ytdPct).toBeCloseTo((2100 / 5000) * 100, 1)
  })

  it('año pasado: usa último capital_final manual como endUsd, no snapshot live', () => {
    const lastYear = new Date().getFullYear() - 1
    const out = buildMonthlyReports(
      [
        { year: lastYear, month: 1,  broker: 'global', capital_inicio: 5000, capital_final: 5300 },
        { year: lastYear, month: 12, broker: 'global', capital_inicio: 5800, capital_final: 6100 },
      ],
      [],
      // Snapshot live es del año en curso, no debe contaminar el año pasado
      [{ date: `${new Date().getFullYear()}-06-01`, total_value: 9000 }]
    )
    const yr = out.years[0]
    expect(yr.endSource).toBe('manual')
    expect(yr.endUsd).toBe(6100)
  })

  it('flows del año descontados del YTD para que coincida con Dashboard', () => {
    const todayYear = new Date().getFullYear()
    const out = buildMonthlyReports(
      [
        { year: todayYear, month: 1, broker: 'global', capital_inicio: 5000, capital_final: 5200, deposits: 500, withdrawals: 0 },
        { year: todayYear, month: 2, broker: 'global', capital_inicio: 5700, capital_final: 5900, deposits: 0,   withdrawals: 200 },
      ],
      [],
      [{ date: `${todayYear}-03-15`, total_value: 6500 }]
    )
    const yr = out.years[0]
    // flowsYear = 500 + 0 - 0 - 200 = 300 (deposits − withdrawals neto)
    expect(yr.flowsYear).toBe(300)
    // YTD = 6500 - 5000 - 300 = 1200 (rendimiento puro, sin contar aportes)
    expect(yr.ytdUsd).toBe(1200)
  })
})
