import { describe, it, expect } from 'vitest'
import { hallazgosDeLaBienvenida, repartoDeLaCartera, HALLAZGOS_DEL_MOTOR, MAX_HALLAZGOS } from './hallazgosDeLaBienvenida'
import { selectDiagnostics } from './diagnostics'
import { OCULTO } from './ocultarSaldos'

const HOY = new Date('2026-11-25T12:00:00Z')

// Una cartera ganadora y concentrada: AAPL es el 80 %.
const GANADORA = {
  value: 10000, invested: 8000, pnl: 2000, pnlPct: 0.25,
  best: { asset: 'AAPL', pnl_usd: 1500 }, worst: { asset: 'GGAL', pnl_usd: -200 },
  pieData: [{ name: 'AAPL', value: 8000 }, { name: 'GGAL', value: 1500 }, { name: 'SPY', value: 500 }],
}

describe('hallazgosDeLaBienvenida', () => {
  it('sin valor no dice nada (no inventa un resumen sobre una cartera vacía)', () => {
    expect(hallazgosDeLaBienvenida({ stats: null })).toEqual([])
    expect(hallazgosDeLaBienvenida({ stats: { ...GANADORA, value: 0 } })).toEqual([])
  })

  it('arranca por cómo viene y por el mejor activo, y suma lo más importante del motor de Diagnóstico', () => {
    const h = hallazgosDeLaBienvenida({ stats: GANADORA, hoy: HOY })
    expect(h.map(x => x.id).slice(0, 2)).toEqual(['resultado', 'mejor_activo'])
    expect(h[0].tono).toBe('pos')
    expect(h[0].texto).toContain('USD 2.000 más')
    expect(h[0].texto).toContain('+25,0%')
    expect(h[1].texto).toContain('**AAPL**')
    // AAPL pesa 80 %: el motor lo marca como concentración extrema.
    expect(h.map(x => x.id)).toContain('concentration_extreme')
    expect(h.find(x => x.id === 'concentration_extreme').tono).toBe('atencion')
    expect(h.length).toBeLessThanOrEqual(MAX_HALLAZGOS)
  })

  it('el texto del motor es el MISMO que muestra Diagnóstico (no una copia reescrita)', () => {
    const datos = { pieData: GANADORA.pieData, totalPortfolio: GANADORA.value, positions: [], brokers: [], tcValuacion: null, oculto: false }
    const delMotor = selectDiagnostics(datos, 999, HOY).find(d => d.id === 'concentration_extreme')
    const h = hallazgosDeLaBienvenida({ stats: GANADORA, hoy: HOY })
    expect(h.find(x => x.id === 'concentration_extreme').texto).toBe(delMotor.text)
  })

  it('del motor entran sólo los de la lista (nada de consejos impositivos ni de meses de historia)', () => {
    // 6 activos, 3 de ellos chiquitos: dispararía «tiny_positions_drag», que no va.
    const muchos = {
      ...GANADORA,
      pieData: [
        { name: 'A', value: 3000 }, { name: 'B', value: 3000 }, { name: 'C', value: 3300 },
        { name: 'D', value: 100 }, { name: 'E', value: 100 }, { name: 'F', value: 100 },
      ],
    }
    const disparados = selectDiagnostics({ pieData: muchos.pieData, totalPortfolio: muchos.value }, 999, HOY).map(d => d.id)
    expect(disparados).toContain('tiny_positions_drag')
    const h = hallazgosDeLaBienvenida({ stats: muchos, hoy: HOY })
    for (const x of h) {
      if (['resultado', 'mejor_activo', 'peor_activo'].includes(x.id)) continue
      expect(HALLAZGOS_DEL_MOTOR).toContain(x.id)
    }
    expect(h.map(x => x.id)).not.toContain('tiny_positions_drag')
  })

  it('perdiendo: lo dice derecho, y si el motor no ve nada, completa con el que más le pesa', () => {
    const perdedora = {
      value: 9000, invested: 10000, pnl: -1000, pnlPct: -0.1,
      best: { asset: 'MELI', pnl_usd: -50 }, worst: { asset: 'GGAL', pnl_usd: -700 },
      // Repartida (nadie pasa el 35 %) y con 4 activos: el motor no dice nada.
      pieData: [{ name: 'MELI', value: 2500 }, { name: 'GGAL', value: 2500 }, { name: 'SPY', value: 2000 }, { name: 'KO', value: 2000 }],
    }
    const h = hallazgosDeLaBienvenida({ stats: perdedora, hoy: HOY })
    expect(h[0]).toMatchObject({ id: 'resultado', tono: 'neg' })
    expect(h[0].texto).toContain('USD 1.000 menos')
    expect(h[0].texto).toContain('−10,0%')
    expect(h.map(x => x.id)).not.toContain('mejor_activo')   // el «mejor» también perdió
    expect(h.find(x => x.id === 'peor_activo').texto).toContain('**GGAL**')
  })

  it('con «Ocultar saldos» tapa los montos pero deja los porcentajes y los nombres', () => {
    const h = hallazgosDeLaBienvenida({ stats: GANADORA, oculto: true, hoy: HOY })
    const todo = h.map(x => x.texto).join(' ')
    expect(todo).toContain(OCULTO)
    expect(todo).not.toMatch(/USD \d/)
    expect(todo).toContain('+25,0%')
    expect(todo).toContain('AAPL')
  })
})

describe('repartoDeLaCartera (la torta)', () => {
  it('sin valor, no hay torta', () => {
    expect(repartoDeLaCartera(null)).toEqual([])
    expect(repartoDeLaCartera({ value: 0, pieData: [] })).toEqual([])
  })

  it('de mayor a menor, y el % es sobre el total de la cartera: el mismo que dice el hallazgo de concentración', () => {
    const r = repartoDeLaCartera(GANADORA)
    expect(r.map(x => x.nombre)).toEqual(['AAPL', 'GGAL', 'SPY'])
    expect(r[0].pct).toBeCloseTo(80)
    expect(r.reduce((s, x) => s + x.pct, 0)).toBeCloseTo(100)
    const texto = hallazgosDeLaBienvenida({ stats: GANADORA, hoy: HOY }).find(x => x.id === 'concentration_extreme').texto
    expect(texto).toContain('**80%**')
  })

  it('el efectivo es una porción más, en su lugar por tamaño', () => {
    const r = repartoDeLaCartera({ value: 10000, cashUsd: 3000, pieData: [{ name: 'AAPL', value: 5000 }, { name: 'KO', value: 2000 }] })
    expect(r.map(x => x.nombre)).toEqual(['AAPL', 'Efectivo', 'KO'])
    expect(r[1]).toMatchObject({ efectivo: true })
    expect(r[1].pct).toBeCloseTo(30)
  })

  it('más de 5 partes: las 4 más grandes y el resto plegado en «Otros», que suma lo que falta', () => {
    const pieData = [3000, 2500, 2000, 1000, 800, 400, 300].map((value, i) => ({ name: `A${i}`, value }))
    const r = repartoDeLaCartera({ value: 10000, pieData })
    expect(r).toHaveLength(5)
    expect(r[4]).toMatchObject({ nombre: 'Otros', otros: true, cuantos: 3 })
    expect(r[4].pct).toBeCloseTo(15)
    expect(r.reduce((s, x) => s + x.pct, 0)).toBeCloseTo(100)
  })

  it('con efectivo negativo (deuda con el broker) nada pasa de 100 %', () => {
    // Los activos suman 1.100 y el total es 1.000 (hay −100 de efectivo).
    const r = repartoDeLaCartera({ value: 1000, cashUsd: -100, pieData: [{ name: 'AAPL', value: 700 }, { name: 'KO', value: 400 }] })
    expect(r.map(x => x.nombre)).toEqual(['AAPL', 'KO'])
    expect(r.reduce((s, x) => s + x.pct, 0)).toBeCloseTo(100)
    for (const x of r) expect(x.pct).toBeLessThanOrEqual(100)
  })
})
