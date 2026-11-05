// La torta de composición (components/CompositionDonut) montada: con plata (la
// de tu cartera) cada renglón dice el monto y el %; con `montos={false}` (la
// cartera que se arma en «Simular una cartera») sólo el %, y el ojito no tiene
// plata que tapar.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, clic, buscarBoton } from '../testing/navegadorMinimo'

const ojito = vi.hoisted(() => ({ hidden: false }))
vi.mock('../contexts/PrivacyContext', () => ({
  usePrivacy: () => ({ hidden: ojito.hidden, toggle: () => {} }),
  OCULTO: '•••',
}))
// El globo se dibuja con la porción de `encima`, como hace recharts al pasar el
// mouse: sin esto el globo nunca se dibujaba y lo que dijera no lo veía nadie
// (auditoría de las pruebas 05/11, C2). La torta anota lo que recibe.
const encima = vi.hoisted(() => ({ porcion: null, pie: null }))
vi.mock('recharts', async () => {
  const { cloneElement } = await import('react')
  const hijos = ({ children }) => children ?? null
  return {
    ResponsiveContainer: hijos, PieChart: hijos, Cell: () => null, Sector: () => null,
    Pie: (p) => { encima.pie = p; return null },
    Tooltip: ({ content }) => (content && encima.porcion
      ? cloneElement(content, { active: true, payload: [{ payload: encima.porcion }] }) : null),
  }
})

const ITEMS = [
  { key: 'AAPL', label: 'AAPL', value: 600, pct: 60, color: 'rgb(var(--mono-violet-1))' },
  { key: 'GGAL', label: 'GGAL', value: 400, pct: 40, color: 'rgb(var(--mono-violet-2))' },
]

let montado
beforeEach(() => { instalarNavegadorMinimo(); ojito.hidden = false; encima.porcion = null; encima.pie = null })
afterEach(async () => { await montado?.desmontar?.(); montado = null })

describe('la torta de composición', () => {
  it('con plata: el monto y el %; con el ojito, el monto tapado', async () => {
    const { default: CompositionDonut } = await import('./CompositionDonut')
    montado = await montar(h(CompositionDonut, { title: 'Por activo', items: ITEMS }))
    expect(texto(montado.contenedor)).toContain('US$ 600')
    expect(texto(montado.contenedor)).toContain('60,0%')
    await montado.desmontar()
    ojito.hidden = true
    montado = await montar(h(CompositionDonut, { title: 'Por activo', items: ITEMS }))
    expect(texto(montado.contenedor)).not.toContain('US$ 600')
    expect(texto(montado.contenedor)).toContain('•••')
  })

  it('sólo porcentajes: ni monto ni puntos de tapado', async () => {
    const { default: CompositionDonut } = await import('./CompositionDonut')
    ojito.hidden = true
    montado = await montar(h(CompositionDonut, { title: 'La torta', items: ITEMS, montos: false }))
    const t = texto(montado.contenedor)
    expect(t).toContain('60,0%')
    expect(t).toContain('40,0%')
    expect(t).not.toContain('US$')
    expect(t).not.toContain('•••')
  })

  it('el globo, con plata dice el monto; con montos={false}, sólo el %', async () => {
    const { default: CompositionDonut } = await import('./CompositionDonut')
    encima.porcion = ITEMS[0]
    montado = await montar(h(CompositionDonut, { title: 'Por activo', items: ITEMS }))
    expect(texto(montado.contenedor)).toContain('US$ 600 · ')       // el globo se dibuja
    await montado.desmontar()
    montado = await montar(h(CompositionDonut, { title: 'La torta', items: ITEMS, montos: false }))
    expect(texto(montado.contenedor)).toContain('60,0%')
    expect(texto(montado.contenedor)).not.toContain('US$')
  })

  it('con montos={false} tampoco hay plata en la fila desplegada ni en su resultado', async () => {
    // Antes tapaba sólo la leyenda y el globo: la fila desplegada y el «Resultado»
    // de la porción decían la plata (auditoría de regresiones 05/11, B2).
    const { default: CompositionDonut } = await import('./CompositionDonut')
    const conActivos = [{ ...ITEMS[0], key: 'acciones', label: 'Acciones', pnl: { total: 2442, pct: 12.5 },
      assets: [{ asset: 'AAPL', value: 3442, pct: 60, pnl: { total: 2442, pct: 12.5 } }] }, ITEMS[1]]
    for (const montos of [true, false]) {
      montado = await montar(h(CompositionDonut, { title: 'La torta', items: conActivos, montos }))
      await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Acciones'))
      const t = texto(montado.contenedor)
      expect(t, `montos=${montos}`).toContain('Resultado')
      expect(t, `montos=${montos}`).toContain('+12,5%')
      if (montos) expect(t).toContain('US$ 3.442')
      else expect(t).not.toContain('US$')
      await montado.desmontar()
      montado = null
    }
  })

  it('la torta no es una parada del teclado (lo que dice cada porción está en la leyenda)', async () => {
    const { default: CompositionDonut } = await import('./CompositionDonut')
    montado = await montar(h(CompositionDonut, { title: 'Por activo', items: ITEMS }))
    expect(encima.pie.rootTabIndex).toBe(-1)
  })
})
