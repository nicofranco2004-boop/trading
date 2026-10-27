import { describe, it, expect } from 'vitest'
import { specDeDistribucion, specDeRendimiento, specDeComposicion, specDeAportes, nombreDeArchivo, pctConSigno } from './shareCard'

const fmt = (v) => `US$ ${Math.round(v)}`
const now = new Date('2026-10-26T12:00:00')

describe('specDeDistribucion', () => {
  const porciones = [
    { key: 'tecnologia', label: 'Tecnología', color: 'rgb(var(--rendi-accent))', value: 600, pct: 60 },
    { key: 'energia', label: 'Energía', color: 'rgb(var(--data-amber))', value: 300, pct: 30 },
    { key: 'otro', label: 'Sin clasificar', color: 'rgb(var(--cat-gray-2))', value: 100, pct: 10 },
  ]

  it('sin montos: sólo porcentajes, ni total ni monto por porción', () => {
    const s = specDeDistribucion({ titulo: 'Distribución por sector', porciones, fmt, mostrarMontos: false, now })
    expect(s.kind).toBe('distribucion')
    // Sin nombre, el titular es el título de la torta (no el % mayor).
    expect(s.title).toBe('Distribución por sector')
    expect(s.eyebrow).toBeNull()
    expect(s.total).toBeNull()
    expect(s.porciones.every(p => p.monto === null)).toBe(true)
    expect(s.porciones.map(p => p.pct)).toEqual([60, 30, 10])
  })

  it('con montos: usa el mismo fmt de la torta', () => {
    const s = specDeDistribucion({ titulo: 'X', porciones, fmt, mostrarMontos: true, now })
    expect(s.total).toBe('US$ 1000')
    expect(s.porciones[0].monto).toBe('US$ 600')
  })

  it('con nombre: el nombre es el titular y el título va arriba', () => {
    const s = specDeDistribucion({ titulo: 'Distribución de activos', porciones, fmt, nombre: 'Nicolás Franco', now })
    expect(s.title).toBe('Nicolás Franco')
    expect(s.eyebrow).toBe('Distribución de activos')
  })

  it('nunca imprime un email como nombre', () => {
    const s = specDeDistribucion({ titulo: 'X', porciones, fmt, nombre: 'alguien@gmail.com', now })
    expect(s.title).toBe('X')
    expect(JSON.stringify(s)).not.toMatch(/@/)
  })

  it('si no entran, las últimas filas se juntan en "Otros" y los % siguen sumando 100', () => {
    const muchas = Array.from({ length: 14 }, (_, i) => ({
      key: `a${i}`, label: `A${i}`, color: '#123456', value: 10, pct: 100 / 14,
    }))
    const s = specDeDistribucion({ titulo: 'X', porciones: muchas, fmt, now })
    expect(s.porciones).toHaveLength(10)
    expect(s.porciones[9].label).toBe('Otros')
    const suma = s.porciones.reduce((a, p) => a + p.pct, 0)
    expect(suma).toBeCloseTo(100, 6)
  })
})

describe('specDeRendimiento', () => {
  const serie = [
    { ts: 1, cartera: 0, bench: 0 },
    { ts: 2, cartera: 5, bench: 3 },
    { ts: 3, cartera: null, bench: 4 },
    { ts: 4, cartera: 12.34, bench: 9.1 },
  ]

  it('publica los números del KPI, con signo y la diferencia en puntos', () => {
    const s = specDeRendimiento({ carteraPct: 12.34, benchPct: 9.1, benchLabel: 'S&P 500', serie, periodo: 'Último año', moneda: 'USD', now })
    expect(s.kind).toBe('rendimiento')
    expect(s.title).toBe('+12,3%')
    expect(s.eyebrow).toBe('Mi cartera vs S&P 500')
    expect(s.subtitle).toBe('Último año · en dólares')
    expect(s.stats.map(x => x.value)).toEqual(['+12,3%', '+9,1%', '+3,2 puntos'])
    expect(s.veredicto).toBe('Mejor que S&P 500')
    expect(s.serie).toHaveLength(4)
  })

  it('negativo y perdiendo contra el benchmark', () => {
    const s = specDeRendimiento({ carteraPct: -4, benchPct: 2, benchLabel: 'Inflación AR', moneda: 'ARS', now })
    expect(s.title).toBe('−4,0%')
    expect(s.tono).toBe('red')
    expect(s.subtitle).toBe('en pesos')
    expect(s.stats[2].value).toBe('−6,0 puntos')
    expect(s.veredicto).toBe('Por debajo de Inflación AR')
  })

  it('el valor de la cartera sólo va si eligió mostrar montos', () => {
    const base = { carteraPct: 1, benchPct: 1, benchLabel: 'S&P 500', patrimonio: 'US$ 10.000', now }
    expect(specDeRendimiento({ ...base, mostrarMontos: false }).patrimonio).toBeNull()
    expect(specDeRendimiento({ ...base, mostrarMontos: true }).patrimonio).toBe('US$ 10.000')
  })

  it('sin benchmark: sólo la cartera, sin veredicto', () => {
    const s = specDeRendimiento({ carteraPct: 3, benchPct: null, now })
    expect(s.stats).toHaveLength(1)
    expect(s.veredicto).toBeNull()
  })

  it('ralea series largas pero conserva el último punto (hoy)', () => {
    const larga = Array.from({ length: 1000 }, (_, i) => ({ ts: i, cartera: i, bench: i }))
    const s = specDeRendimiento({ carteraPct: 1, benchPct: 1, serie: larga, now })
    expect(s.serie.length).toBeLessThanOrEqual(241)
    expect(s.serie[s.serie.length - 1].ts).toBe(999)
  })
})

describe('helpers', () => {
  it('nombreDeArchivo', () => {
    expect(nombreDeArchivo('Distribución por tipo de activo')).toBe('distribucion-por-tipo-de-activo')
    expect(nombreDeArchivo('S&P 500')).toBe('s-p-500')
  })
  it('pctConSigno usa el menos tipográfico', () => {
    expect(pctConSigno(-0.5)).toBe('−0,5%')
    expect(pctConSigno(0)).toBe('+0,0%')
  })
})

describe('specDeComposicion', () => {
  const tipos = [
    { key: 'cash', label: 'Efectivo', color: 'c0', value: 334, pct: 33.4, detail: [] },
    { key: 'cripto', label: 'Cripto', color: 'c1', value: 418, pct: 41.8, detail: [
      { label: 'ETH', value: 30, pct: 3 }, { label: 'BTC', value: 290, pct: 29 }, { label: 'BNB', value: 98, pct: 9.8 },
    ] },
    { key: 'etf', label: 'ETFs', color: 'c2', value: 248, pct: 24.8, detail: [{ label: 'SPY', value: 248, pct: 24.8 }] },
  ]

  it('invertido = todo lo que no es efectivo', () => {
    const s = specDeComposicion({ titulo: 'Distribución por tipo de activo', porciones: tipos, now })
    expect(s.kind).toBe('composicion')
    expect(s.invertido).toBeCloseTo(66.6, 6)
  })

  it('una tarjeta por tipo con activos (Efectivo sin activos no lleva), activos de mayor a menor', () => {
    const s = specDeComposicion({ titulo: 'X', porciones: tipos, now })
    expect(s.grupos.map(g => g.label)).toEqual(['Cripto', 'ETFs'])
    expect(s.grupos[0].activos.map(a => a.label)).toEqual(['BTC', 'BNB', 'ETH'])
  })

  it('sin montos no hay total; con montos, el del fmt', () => {
    expect(specDeComposicion({ titulo: 'X', porciones: tipos, fmt, now }).total).toBeNull()
    expect(specDeComposicion({ titulo: 'X', porciones: tipos, fmt, mostrarMontos: true, now }).total).toBe('US$ 1000')
  })
})

describe('specDeAportes', () => {
  const base = {
    aportado: 800, valor: 1000, ganancia: 200, pct: 0.25,
    serie: [{ ts: 1, valor: 500, aportado: 500 }, { ts: 2, valor: 1000, aportado: 800 }],
    periodo: 'Último año', fmt: (v) => `USD ${v}`, fmtConSigno: (v) => `${v >= 0 ? '+' : '−'}USD ${Math.abs(v)}`, now,
  }

  it('con montos: los de las tarjetas del Dashboard', () => {
    const s = specDeAportes({ ...base, mostrarMontos: true })
    expect(s.stats.map(x => x.value)).toEqual(['USD 800', '+USD 200', 'USD 1000'])
    expect(s.stats[0].sub).toBe('80,0% del total')
    expect(s.stats[1].sub).toBe('+25,0% sobre lo aportado')
  })

  it('sin montos: reparto en % y ganancia en %, ninguna cifra de plata', () => {
    const s = specDeAportes({ ...base, mostrarMontos: false })
    expect(s.stats.map(x => x.value)).toEqual(['80,0%', '20,0%', '+25,0%'])
    expect(JSON.stringify(s)).not.toMatch(/USD/)
  })

  it('pérdida: el rótulo lo dice y la barra va en rojo', () => {
    const s = specDeAportes({ ...base, valor: 700, ganancia: -100, pct: -0.125 })
    expect(s.stats[1].label).toBe('Lo que perdió en el mercado')
    expect(s.barra.gana).toBe(false)
  })
})
