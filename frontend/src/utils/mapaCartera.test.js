// Las cuentas del mapa de calor (utils/mapaCartera.js) y su acomodo
// (components/MapaCartera.jsx → acomodar). Lo montado, con el Dashboard y el
// servidor simulado, está en components/MapaCartera.render.test.jsx.
import { describe, it, expect, beforeEach } from 'vitest'
import { sumarLotes, cuadrosDelMapa, colorDelCuadro, losExtremosDeHoy, sumaDeHoy } from './mapaCartera'
import { acomodar } from '../components/MapaCartera'
import { setBrokersRegistry } from './valuation'

beforeEach(() => setBrokersRegistry([
  { id: 1, name: 'IOL', currency: 'ARS' }, { id: 2, name: 'Schwab', currency: 'USD' },
]))

const GGAL_IOL = { broker: 'IOL', asset: 'GGAL', asset_type: 'ACCION', quantity: 100, currency: 'ARS' }
const GGAL_ADR = { broker: 'Schwab', asset: 'GGAL', asset_type: 'STOCK', quantity: 10 }

describe('mapaCartera', () => {
  it('junta los lotes por papel: GGAL de BYMA aparte del ADR, como el servidor', () => {
    const m = sumarLotes([
      { p: GGAL_IOL, dia: { amount: 20, base: 580 }, valueUsd: 600, pnlUsd: 100 },
      { p: { ...GGAL_IOL, id: 9 }, dia: { amount: 2, base: 58 }, valueUsd: 60, pnlUsd: 10 },
      { p: GGAL_ADR, dia: null, valueUsd: 300, pnlUsd: -20 },
    ])
    expect(m.get('GGAL|1')).toMatchObject({ diaUsd: 22, diaBase: 638, conDia: true, valor: 660, resultado: 110 })
    expect(m.get('GGAL|0')).toMatchObject({ conDia: false, valor: 300, resultado: -20 })
  })

  it('los cuadros: el peso del servidor, % del día y contra tu promedio, efectivo y plazos fijos', () => {
    const cuadros = cuadrosDelMapa({
      tenencias: [{ asset: 'GGAL', local: true, peso: 0.5, tipo: 'ACCION' }, { asset: 'GGAL', local: false, peso: 0.3, tipo: 'STOCK' }],
      sinMedir: { efectivo: 0.15, plazos_fijos: 0.05 },
      lotes: [
        { p: GGAL_IOL, dia: { amount: 20, base: 580 }, valueUsd: 600, pnlUsd: 100 },
        { p: GGAL_ADR, dia: null, valueUsd: 300, pnlUsd: -20 },
      ],
    })
    expect(cuadros.map(c => [c.clave, c.peso])).toEqual([['GGAL|1', 0.5], ['GGAL|0', 0.3], ['efectivo', 0.15], ['plazos_fijos', 0.05]])
    expect(cuadros[0].detalle).toBe('en BYMA')
    expect(cuadros[1].detalle).toBe('en Nueva York')
    expect(cuadros[0].hoy.pct).toBeCloseTo(20 / 580, 12)
    expect(cuadros[0].promedio.pct).toBeCloseTo(100 / 500, 12)
    expect(cuadros[1].hoy).toBeNull()
    expect(cuadros[1].promedio.pct).toBeCloseTo(-20 / 320, 12)
    expect(cuadros[2]).toMatchObject({ nombre: 'Efectivo', ruta: null, hoy: null, promedio: null })
    expect(cuadros[2].fondo.id).toBe('sin')
    expect(colorDelCuadro(cuadros[1], 'hoy')).toEqual(colorDelCuadro(cuadros[2], 'tendencia'))   // los dos grises
  })

  it('lo que más sumó, lo que más restó y la suma de los cuadros', () => {
    const c = (clave, usd, base) => ({ clave, hoy: { usd, base, pct: usd / base } })
    const cuadros = [c('A', 30, 1000), c('B', -50, 1000), c('C', 10, 500), { clave: 'D', hoy: null }]
    const { sumo, resto } = losExtremosDeHoy(cuadros)
    expect([sumo.clave, resto.clave]).toEqual(['A', 'B'])
    expect(sumaDeHoy(cuadros)).toEqual({ usd: -10, pct: -10 / 2500 })
    expect(losExtremosDeHoy([c('A', 5, 100)]).resto).toBeNull()
  })

  it('acomodar: nada más chico que el mínimo; lo que no entra baja a la lista, de menor peso', () => {
    const cuadros = [0.5, 0.3, 0.15, 0.03, 0.015, 0.005].map((peso, i) => ({ clave: `c${i}`, peso }))
    const { laid, abajo } = acomodar(cuadros, 360, 414, 52)
    for (const b of laid) expect(Math.min(b.w, b.h)).toBeGreaterThanOrEqual(52)
    expect(abajo.length).toBeGreaterThan(0)
    expect(abajo).toEqual(cuadros.slice(laid.length))   // los más chicos, en orden
    // El área de los que quedan sigue siendo proporcional a su peso.
    const area = (k) => { const b = laid.find(x => x.clave === k); return b.w * b.h }
    expect(area('c0') / area('c1')).toBeCloseTo(0.5 / 0.3, 6)
  })
})
