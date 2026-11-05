// La torta de composición (components/CompositionDonut) montada: con plata (la
// de tu cartera) cada renglón dice el monto y el %; con `montos={false}` (la
// cartera que se arma en «Simular una cartera») sólo el %, y el ojito no tiene
// plata que tapar.
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'

const ojito = vi.hoisted(() => ({ hidden: false }))
vi.mock('../contexts/PrivacyContext', () => ({
  usePrivacy: () => ({ hidden: ojito.hidden, toggle: () => {} }),
  OCULTO: '•••',
}))
vi.mock('recharts', () => {
  const hijos = ({ children }) => children ?? null
  return { ResponsiveContainer: hijos, PieChart: hijos, Pie: () => null, Cell: () => null, Sector: () => null, Tooltip: () => null }
})

const ITEMS = [
  { key: 'AAPL', label: 'AAPL', value: 600, pct: 60, color: 'rgb(var(--mono-violet-1))' },
  { key: 'GGAL', label: 'GGAL', value: 400, pct: 40, color: 'rgb(var(--mono-violet-2))' },
]

let montado
beforeEach(() => { instalarNavegadorMinimo(); ojito.hidden = false })
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
})
