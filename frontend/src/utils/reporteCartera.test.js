import { describe, it, expect } from 'vitest'
import { armarReporte } from './reporteCartera'

const fmt = (v) => `US$ ${Math.round(v)}`
const now = new Date('2026-10-27T12:00:00')
const base = {
  fmt, now, moneda: 'USD', periodo: 'Último año', patrimonio: 1000,
  rendimiento: { carteraPct: 12.34, benchPct: 9.1, benchLabel: 'S&P 500', serie: [{ ts: 1, cartera: 0, bench: 0 }, { ts: 2, cartera: 12.3, bench: 9.1 }] },
  drawdown: { currentPct: -3.2, maxPct: -18.5 },
  distribuciones: [
    { titulo: 'Distribución por sector', items: [
      { key: 'tecnologia', label: 'Tecnología', color: 'c1', value: 600, pct: 60 },
      { key: 'energia', label: 'Energía', color: 'c2', value: 390, pct: 39 },
      { key: 'chica', label: 'Chica', color: 'c3', value: 10, pct: 1 },
    ] },
    { titulo: 'Vacía', items: [] },
  ],
  ganadores: [{ asset: 'FCI:FIMA-A', pnl: 120 }],
  perdedores: [{ asset: 'YPF', pnl: -40 }],
  fmtEnVista: (v, o = {}) => `${o.signed ? (v >= 0 ? '+' : '−') : ''}USD ${Math.abs(Math.round(v))}`,
  capital: { aportado: 800, mercado: 200, valorHoy: 1000 },
  noRealizado: { pnl: 150, pct: 0.176 },
}

describe('armarReporte', () => {
  it('sin montos no queda NINGUNA cifra de plata en el objeto', () => {
    const r = armarReporte({ ...base, mostrarMontos: false })
    expect(JSON.stringify(r)).not.toMatch(/(US\$|USD) \d/)
    expect(r.plata).toBeNull()
    // El no realizado va igual, sólo con su %.
    expect(r.noRealizado).toEqual({ monto: null, pct: '+17,6%', positivo: true })
    expect(r.patrimonio).toBeNull()
    expect(r.ganadores[0].resultado).toBeNull()
  })

  it('con montos: total, montos por porción y resultado con signo', () => {
    const r = armarReporte({ ...base, mostrarMontos: true })
    expect(r.patrimonio).toBe('US$ 1000')
    expect(r.distribuciones[0].porciones[0].monto).toBe('US$ 600')
    expect(r.ganadores[0]).toEqual({ label: 'FIMA-A', resultado: '+US$ 120' })
    expect(r.perdedores[0].resultado).toBe('−US$ 40')
    // Aportado / mercado / no realizado: con el formateador de la vista.
    expect(r.plata).toEqual({ aportado: 'USD 800', mercado: '+USD 200', mercadoPositivo: true, valorHoy: 'USD 1000' })
    expect(r.noRealizado.monto).toBe('+USD 150')
  })

  it('agrupa las porciones igual que la torta de la pantalla y saca las vacías', () => {
    const r = armarReporte({ ...base })
    expect(r.distribuciones).toHaveLength(1)
    // 1% < 1,5% (MIN_SLICE_PCT): la torta de la pantalla la lista igual al
    // final porque es una sola; el reporte tiene que hacer lo mismo.
    expect(r.distribuciones[0].porciones.map(p => p.label)).toEqual(['Tecnología', 'Energía', 'Chica'])
  })

  it('rendimiento: los números del KPI, con signo y diferencia en puntos', () => {
    const r = armarReporte({ ...base })
    expect(r.rendimiento.cartera).toBe('+12,3%')
    expect(r.rendimiento.bench).toBe('+9,1%')
    expect(r.rendimiento.diferencia).toBe('+3,2 puntos')
    expect(r.rendimiento.ganaAlBench).toBe(true)
    expect(r.drawdown).toEqual({ actual: '−3,2%', maximo: '−18,5%' })
  })

  it('sin rendimiento publicado no inventa uno', () => {
    const r = armarReporte({ ...base, rendimiento: null, drawdown: null })
    expect(r.rendimiento).toBeNull()
    expect(r.drawdown).toBeNull()
  })
})
