import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import DistribucionPorActivo from './DistribucionPorActivo'

// La tarjeta "Distribución de activos" (Dashboard y Análisis). El % de efectivo
// de arriba se lee de la porción: no puede diferir del de la torta.
const items = [
  { key: 'AAPL', label: 'AAPL', value: 600, pct: 60, color: 'x' },
  { key: 'efectivo', label: 'Efectivo', value: 400, pct: 40, color: 'y' },
]

describe('DistribucionPorActivo', () => {
  it('título y efectivo leído de la porción, en ámbar desde 30 %', () => {
    const html = renderToStaticMarkup(<DistribucionPorActivo items={items} fmt={v => `US$ ${v}`} />)
    expect(html).toContain('Distribución de activos')
    expect(html).toContain('40,0%')
    expect(html).toContain('text-rendi-warn')
  })
  it('sin efectivo dice 0,0 % y no avisa; sin porciones no dibuja nada', () => {
    const html = renderToStaticMarkup(<DistribucionPorActivo items={[items[0]]} fmt={v => `${v}`} />)
    expect(html).toContain('0,0%')
    expect(html).not.toContain('text-rendi-warn')
    expect(renderToStaticMarkup(<DistribucionPorActivo items={[]} fmt={v => `${v}`} />)).toBe('')
  })
})
