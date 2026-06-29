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
    // Modified Dietz: divisor = startUsd + 0.5*flows = 7000 + 0.5*100 = 7050.
    // Antes dividíamos por startUsd a secas, lo que inflaba el % en meses con
    // depósitos grandes vs el capital de arranque.
    expect(may.deltaPct).toBeCloseTo((1100 / 7050) * 100, 1)
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
    // ytdPct ahora es TWRR (chain-link de meses). Con 1 mes en el año, el TWRR
    // anual coincide con el deltaPct mensual Modified Dietz:
    //   avgCap = 5000 + 0.5*100 = 5050  →  2100 / 5050 ≈ 41.58%
    // Antes dividíamos 2100 / 5000 (= 42%), pero inflar el % por flujos de
    // mid-period es el bug que motivó esta migración.
    expect(yr.ytdPct).toBeCloseTo((2100 / 5050) * 100, 1)
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

  it('CONSISTENCIA: suma de deltaUsd por mes === ytdUsd del año en curso', () => {
    // Bug reportado: el Hero usaba liveValue pero el último mes mostraba
    // capital_final cerrado. La suma visual no daba el YTD. Fix: el último
    // mes manual del año en curso se actualiza con liveValue como endUsd.
    const todayYear = new Date().getFullYear()
    const out = buildMonthlyReports(
      [
        { year: todayYear, month: 2, broker: 'global', capital_inicio: 5557, capital_final: 5927.24, deposits: 370.24 },
        { year: todayYear, month: 3, broker: 'global', capital_inicio: 5927.24, capital_final: 6489.96, deposits: 604.72 },
        { year: todayYear, month: 4, broker: 'global', capital_inicio: 6489.96, capital_final: 6998.31, deposits: 500.80 },
        { year: todayYear, month: 5, broker: 'global', capital_inicio: 6998.31, capital_final: 8299.38, deposits: 112 },
      ],
      [],
      // Live snapshot está $240.57 por encima del último capital_final
      [{ date: `${todayYear}-05-11`, total_value: 8539.95 }]
    )
    const yr = out.years[0]
    const sumOfDeltas = yr.months.reduce((s, m) => s + m.deltaUsd, 0)
    expect(sumOfDeltas).toBeCloseTo(yr.ytdUsd, 1)
    // El último mes (Mayo) debe estar marcado isLive y reflejar el gap
    const mayo = yr.months.find(m => m.month === 5)
    expect(mayo.isLive).toBe(true)
    expect(mayo.endUsd).toBe(8539.95)
    // delta de mayo = 8539.95 - 6998.31 - 112 = 1429.64
    expect(mayo.deltaUsd).toBeCloseTo(1429.64, 1)
  })

  it('isLive solo se aplica al año en curso, no a años pasados', () => {
    const lastYear = new Date().getFullYear() - 1
    const out = buildMonthlyReports(
      [{ year: lastYear, month: 12, broker: 'global', capital_inicio: 5000, capital_final: 5500 }],
      [],
      [{ date: `${new Date().getFullYear()}-01-15`, total_value: 7000 }]
    )
    const dec = out.years[0].months[0]
    expect(dec.isLive).toBeFalsy()
    expect(dec.endUsd).toBe(5500)  // capital_final original, no live
  })

  it('isLive NO se aplica si el gap entre live y capital_final es despreciable', () => {
    const todayYear = new Date().getFullYear()
    const out = buildMonthlyReports(
      [{ year: todayYear, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 8000 }],
      [],
      [{ date: `${todayYear}-05-31`, total_value: 8000.0001 }]  // gap < 0.01
    )
    const may = out.years[0].months[0]
    expect(may.isLive).toBeFalsy()
  })

  // ─── Filtro por broker ───────────────────────────────────────────────────
  describe('broker filter', () => {
    const monthlyMix = [
      // global rollup
      { year: 2026, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 8000, deposits: 200, pnl_realized: 800 },
      // por broker individual
      { year: 2026, month: 5, broker: 'Binance', capital_inicio: 3000, capital_final: 3500, deposits: 100, pnl_realized: 400 },
      { year: 2026, month: 5, broker: 'Cocos',   capital_inicio: 4000, capital_final: 4500, deposits: 100, pnl_realized: 400 },
    ]

    it('default broker="global" usa solo entries con broker=global', () => {
      const out = buildMonthlyReports(monthlyMix, [])
      expect(out.years[0].months[0].startUsd).toBe(7000)
      expect(out.years[0].months[0].endUsd).toBe(8000)
    })

    it('filtro broker="Binance" usa solo entries de Binance', () => {
      const out = buildMonthlyReports(monthlyMix, [], [], 'Binance')
      expect(out.years[0].months[0].startUsd).toBe(3000)
      expect(out.years[0].months[0].endUsd).toBe(3500)
    })

    it('filtro broker="Cocos" usa solo entries de Cocos', () => {
      const out = buildMonthlyReports(monthlyMix, [], [], 'Cocos')
      expect(out.years[0].months[0].startUsd).toBe(4000)
      expect(out.years[0].months[0].endUsd).toBe(4500)
    })

    it('al filtrar por broker, las operations también se filtran', () => {
      const out = buildMonthlyReports(
        [],
        [
          { date: '2026-05-10', broker: 'Binance', op_type: 'Venta', pnl_usd: 100 },
          { date: '2026-05-15', broker: 'Cocos',   op_type: 'Venta', pnl_usd: 200 },
        ],
        [],
        'Binance'
      )
      expect(out.years[0].months[0].deltaUsd).toBe(100)
    })

    it('al filtrar por global, todas las operations cuentan', () => {
      const out = buildMonthlyReports(
        [],
        [
          { date: '2026-05-10', broker: 'Binance', op_type: 'Venta', pnl_usd: 100 },
          { date: '2026-05-15', broker: 'Cocos',   op_type: 'Venta', pnl_usd: 200 },
        ],
        [],
        'global'
      )
      expect(out.years[0].months[0].deltaUsd).toBe(300)
    })

    it('selectedBroker se expone en el return para que la UI sepa el filtro activo', () => {
      const out = buildMonthlyReports([], [], [], 'Cocos')
      expect(out.selectedBroker).toBe('Cocos')
    })

    it('sparklines se OMITEN cuando hay filtro de broker (snapshots son globales)', () => {
      const out = buildMonthlyReports(
        monthlyMix,
        [],
        [
          { date: '2026-05-01', total_value: 7000 },
          { date: '2026-05-15', total_value: 7500 },
          { date: '2026-05-30', total_value: 8000 },
        ],
        'Binance'
      )
      // Aunque hay 3 snapshots, no se asocian al mes porque el filtro es
      // por broker — los snapshots son del portfolio total, no del broker.
      expect(out.years[0].months[0].sparkline).toBeNull()
    })

    it('sparklines SÍ se asocian con filtro=global (default)', () => {
      const out = buildMonthlyReports(
        monthlyMix,
        [],
        [
          { date: '2026-05-01', total_value: 7000 },
          { date: '2026-05-30', total_value: 8000 },
        ]
        // sin selectedBroker → 'global'
      )
      expect(out.years[0].months[0].sparkline).toHaveLength(2)
    })
  })

  // ─── Drivers y benchmarks por mes ────────────────────────────────────────
  describe('drivers por mes', () => {
    it('bestOp y worstOp identifican las operaciones del mes', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 8200 }],
        [
          { date: '2026-05-10', asset: 'NVDA', op_type: 'Venta', pnl_usd: 320 },
          { date: '2026-05-15', asset: 'BTC',  op_type: 'Venta', pnl_usd: 540 },
          { date: '2026-05-22', asset: 'TSLA', op_type: 'Venta', pnl_usd: -41 },
        ]
      )
      const d = out.years[0].months[0].drivers
      expect(d.bestOp.asset).toBe('BTC')
      expect(d.bestOp.pnl).toBe(540)
      expect(d.worstOp.asset).toBe('TSLA')
      expect(d.worstOp.pnl).toBe(-41)
    })

    it('si no hay ops negativas, worstOp es null (no inventa)', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 7500 }],
        [{ date: '2026-05-10', asset: 'NVDA', op_type: 'Venta', pnl_usd: 100 }]
      )
      const d = out.years[0].months[0].drivers
      expect(d.bestOp.asset).toBe('NVDA')
      expect(d.worstOp).toBeNull()
    })

    it('ignora pnl_usd despreciable (≤ $1) para evitar ruido', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 5, broker: 'global', capital_inicio: 7000, capital_final: 7500 }],
        [{ date: '2026-05-10', asset: 'X', op_type: 'Venta', pnl_usd: 0.5 }]
      )
      expect(out.years[0].months[0].drivers.bestOp).toBeNull()
    })
  })

  describe('benchmarks por mes', () => {
    const bench = {
      sp500: { '2026-04': 5000, '2026-05': 5200 },        // +4.0%
      inflation_ar: { '2026-05': 4.5 },                    // 4.5%
    }
    const brokersArs = [{ name: 'Cocos', currency: 'ARS' }]
    const brokersUsd = [{ name: 'Binance', currency: 'USDT' }]

    it('vsSp500 = deltaPct del portfolio − deltaPct del S&P', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 5, broker: 'global', capital_inicio: 5000, capital_final: 5500 }],
        [],
        [],
        'global',
        { bench, brokers: brokersUsd }
      )
      // deltaPct portfolio = +10%, S&P = +4%, diferencia = +6 puntos
      expect(out.years[0].months[0].drivers.vsSp500).toBeCloseTo(6, 1)
    })

    it('vsInflation solo se calcula cuando hay broker ARS (filter=global)', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 5, broker: 'global', capital_inicio: 5000, capital_final: 5500 }],
        [],
        [],
        'global',
        { bench, brokers: brokersArs }
      )
      // delta = 10%, inflación = 4.5%, diferencia = +5.5
      expect(out.years[0].months[0].drivers.vsInflation).toBeCloseTo(5.5, 1)
    })

    it('vsInflation es NULL cuando NO hay brokers ARS (solo USD)', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 5, broker: 'global', capital_inicio: 5000, capital_final: 5500 }],
        [],
        [],
        'global',
        { bench, brokers: brokersUsd }
      )
      expect(out.years[0].months[0].drivers.vsInflation).toBeNull()
    })

    it('vsInflation funciona si filter es un broker ARS individual', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 5, broker: 'Cocos', capital_inicio: 5000, capital_final: 5500 }],
        [],
        [],
        'Cocos',
        { bench, brokers: brokersArs }
      )
      expect(out.years[0].months[0].drivers.vsInflation).toBeCloseTo(5.5, 1)
    })

    it('vsInflation es NULL si filter es un broker USD individual', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 5, broker: 'Binance', capital_inicio: 5000, capital_final: 5500 }],
        [],
        [],
        'Binance',
        { bench, brokers: brokersUsd }
      )
      expect(out.years[0].months[0].drivers.vsInflation).toBeNull()
    })

    it('vsInflationPending=true cuando hay cartera ARS pero falta data INDEC del mes', () => {
      // INDEC publica con lag de ~14 días → meses recientes pueden no tener
      // dato aún. La fila debe seguir visible (pending) en lugar de ocultarse.
      const out = buildMonthlyReports(
        [{ year: 2026, month: 4, broker: 'global', capital_inicio: 5000, capital_final: 5500 }],
        [],
        [],
        'global',
        {
          bench: { sp500: { '2026-03': 5000, '2026-04': 5100 }, inflation_ar: { '2026-03': 3.4 } },
          brokers: brokersArs,
        }
      )
      const d = out.years[0].months[0].drivers
      expect(d.vsInflation).toBeNull()
      expect(d.vsInflationPending).toBe(true)
    })

    it('vsInflationPending=false cuando NO hay cartera ARS (la fila se oculta)', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 4, broker: 'global', capital_inicio: 5000, capital_final: 5500 }],
        [],
        [],
        'global',
        {
          bench: { inflation_ar: {} },
          brokers: brokersUsd,
        }
      )
      const d = out.years[0].months[0].drivers
      expect(d.vsInflation).toBeNull()
      expect(d.vsInflationPending).toBe(false)
    })

    it('vsSp500 = null si falta data del mes o del mes anterior', () => {
      const out = buildMonthlyReports(
        [{ year: 2026, month: 5, broker: 'global', capital_inicio: 5000, capital_final: 5500 }],
        [],
        [],
        'global',
        { bench: { sp500: { '2026-05': 5200 } /* falta abril */ }, brokers: brokersUsd }
      )
      expect(out.years[0].months[0].drivers.vsSp500).toBeNull()
    })
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

  // ─── TWRR & Modified Dietz — anti-regresión del bug "+400% anual" ───────
  describe('TWRR yearly aggregate', () => {
    it('ytdPct anual NO se infla cuando hay depósitos grandes con capital chico', () => {
      // Caso real del bug: arranque $5k, depósitos masivos durante el año,
      // resultado modesto al final → la vieja fórmula daba %  >300% porque
      // dividía por el startUsd inicial. Modified Dietz + TWRR lo arregla.
      const todayYear = new Date().getFullYear()
      const out = buildMonthlyReports(
        [
          { year: todayYear, month: 1, broker: 'global', capital_inicio: 5000,  capital_final: 6100,  deposits: 1000 },
          { year: todayYear, month: 2, broker: 'global', capital_inicio: 6100,  capital_final: 16300, deposits: 10000 },
          { year: todayYear, month: 3, broker: 'global', capital_inicio: 16300, capital_final: 31500, deposits: 15000 },
        ],
        [],
      )
      const yr = out.years[0]
      // Sin aportes, el portfolio creció:
      //   Jan: (6100-5000-1000) = 100 sobre avgCap=5500 → 1.82%
      //   Feb: (16300-6100-10000) = 200 sobre avgCap=11100 → 1.80%
      //   Mar: (31500-16300-15000) = 200 sobre avgCap=23800 → 0.84%
      // TWRR chain-link ≈ 4.5% (no 400%).
      expect(yr.ytdPct).toBeLessThan(10)
      expect(yr.ytdPct).toBeGreaterThan(0)
    })

    it('mes con flows=0 mantiene el % equivalente al simple (sin Modified Dietz overhead)', () => {
      const out = buildMonthlyReports(
        [{ year: 2025, month: 6, broker: 'global', capital_inicio: 10000, capital_final: 11000, deposits: 0, withdrawals: 0 }],
        [],
      )
      // avgCap = 10000 + 0 = 10000; deltaPct = 1000/10000 = 10%
      expect(out.years[0].months[0].deltaPct).toBeCloseTo(10, 2)
    })

    it('Modified Dietz: depósito mid-mes sobre capital chico no infla %', () => {
      const out = buildMonthlyReports(
        [{ year: 2025, month: 6, broker: 'global', capital_inicio: 1000, capital_final: 12200, deposits: 11000, withdrawals: 0 }],
        [],
      )
      // deltaUsd = 12200 - 1000 - 11000 = 200
      // avgCap   = 1000 + 0.5*11000 = 6500
      // deltaPct = 200 / 6500 ≈ 3.08% (no 20% que daría la vieja fórmula)
      expect(out.years[0].months[0].deltaPct).toBeCloseTo(200 / 6500 * 100, 1)
    })
  })

  // ─── ytdPctOverContrib — métrica alternativa "sobre capital aportado" ────
  describe('ytdPctOverContrib (% sobre capital aportado total)', () => {
    it('se computa como ytdUsd / (Σ deposits − Σ withdrawals) al cierre del año', () => {
      // Año único: arranque $5k, depósitos $10k, gain $1k. Cap aportado = $10k. Gain = $1k.
      // ytdPctOverContrib = 1000 / 10000 = +10%
      const out = buildMonthlyReports(
        [
          { year: 2025, month: 1, broker: 'global', capital_inicio: 5000, capital_final: 16000, deposits: 10000 },
        ],
        [],
      )
      const yr = out.years[0]
      // ytdUsd = 16000 - 5000 - 10000 = 1000
      expect(yr.ytdUsd).toBe(1000)
      expect(yr.capContribAtYearEnd).toBe(10000)
      expect(yr.ytdPctOverContrib).toBeCloseTo(10, 1)
    })

    it('acumula deposits/withdrawals de años anteriores en el denominador', () => {
      // 2024: aporta $20k, sin gain. 2025: aporta $5k, gana $2k.
      // Para 2025: cap aportado acumulado al cierre = $25k. ytdPctOverContrib = 2k/25k = 8%.
      const out = buildMonthlyReports(
        [
          { year: 2024, month: 12, broker: 'global', capital_inicio: 0,     capital_final: 20000, deposits: 20000 },
          { year: 2025, month: 12, broker: 'global', capital_inicio: 20000, capital_final: 27000, deposits: 5000 },
        ],
        [],
      )
      const yr2025 = out.years.find(y => y.year === 2025)
      expect(yr2025.ytdUsd).toBe(2000)
      expect(yr2025.capContribAtYearEnd).toBe(25000)
      expect(yr2025.ytdPctOverContrib).toBeCloseTo(8, 1)
    })

    it('resta withdrawals correctamente del cap aportado acumulado', () => {
      // 2024: aporta $30k. 2025: retira $10k, gana $1k.
      // Cap aportado al cierre 2025 = $30k - $10k = $20k. ytdPctOverContrib = 1k/20k = 5%.
      const out = buildMonthlyReports(
        [
          { year: 2024, month: 12, broker: 'global', capital_inicio: 0,     capital_final: 30000, deposits: 30000 },
          { year: 2025, month: 12, broker: 'global', capital_inicio: 30000, capital_final: 21000, withdrawals: 10000 },
        ],
        [],
      )
      const yr2025 = out.years.find(y => y.year === 2025)
      expect(yr2025.capContribAtYearEnd).toBe(20000)
      expect(yr2025.ytdPctOverContrib).toBeCloseTo(5, 1)
    })

    it('es null si el capital aportado acumulado es 0 o negativo (no tiene sentido)', () => {
      // Solo operaciones derived (sin entries) → no flows → cap = 0.
      const out = buildMonthlyReports(
        [],
        [{ date: '2025-05-10', op_type: 'Venta', pnl_usd: 100 }],
      )
      const yr = out.years[0]
      expect(yr.capContribAtYearEnd).toBe(0)
      expect(yr.ytdPctOverContrib).toBeNull()
    })
  })

  // ─── Mes en curso — quick-win C1 (rendimiento sin discontinuidad de base) ───
  describe('mes en curso — quick-win C1', () => {
    const now = new Date()
    const y = now.getFullYear()
    const mo = now.getMonth() + 1
    const period = `${y}-${String(mo).padStart(2, '0')}`
    const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    const prevMonthEnd = iso(new Date(new Date(y, mo - 1, 1).getTime() - 86400000))
    // Entry del mes EN CURSO: capital_inicio (cost-basis del chain) MUY por encima
    // del valor MtM real → sin re-anclaje daría un rendimiento fantasma muy negativo
    // (el bug del −64.9% que ve el usuario).
    const liveEntry = { year: y, month: mo, broker: 'global', capital_inicio: 27000, capital_final: 9500, deposits: 0, withdrawals: 14, pnl_realized: 0, pnl_unrealized: 0 }

    it('re-ancla el delta al MtM de los snapshots (no fantasma)', () => {
      const snaps = [
        { date: prevMonthEnd, total_value: 9400 },     // baseline MtM = cierre mes anterior
        { date: `${period}-05`, total_value: 9500 },    // valor MtM actual
      ]
      const out = buildMonthlyReports([liveEntry], [], snaps, 'global')
      const m = out.years[0].months.find(mm => mm.month === mo)
      // deltaUsd = mtmEnd − mtmStart − flows = 9500 − 9400 − (−14) = 114
      expect(m.deltaUsd).toBeCloseTo(114, 0)
      expect(m.deltaPct).toBeGreaterThan(0)
      expect(m.deltaPct).toBeLessThan(5)              // NO el −64% fantasma
    })

    it('sin baseline MtM → no inventa un % (deltaUsd/deltaPct null)', () => {
      const out = buildMonthlyReports([liveEntry], [], [], 'global')
      const m = out.years[0].months.find(mm => mm.month === mo)
      expect(m.deltaUsd).toBeNull()
      expect(m.deltaPct).toBeNull()
    })
  })
})
