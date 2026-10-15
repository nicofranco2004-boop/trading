// El (?) del pre/post: con los saldos ocultos explica el cálculo pero no muestra
// plata (auditoría 2026-10-15: mostraba los montos con el ojito tachado).
import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { ComoSeCalcula } from './FueraDeHorario'

const impacto = {
  total: { usd: 59.23, ars: 84343, pct: 0.0014 },
  porVia: {
    exacto: { usd: 37.63, ars: 53585, valorUsd: 21622, valorArs: 30789000 },
    anticipo: { usd: 21.6, ars: 30758, valorUsd: 5000, valorArs: 2796000 },
  },
}

describe('ComoSeCalcula', () => {
  it('muestra la cuenta con la plata', () => {
    const html = renderToStaticMarkup(<ComoSeCalcula sesion="pre" impacto={impacto} moneda="USD" />)
    expect(html).toContain('USD 59,23')
    expect(html).toContain('ARS 2.796.000')
  })
  it('con los saldos ocultos no muestra ningún monto', () => {
    const html = renderToStaticMarkup(<ComoSeCalcula sesion="pre" impacto={impacto} moneda="USD" oculto />)
    expect(html).not.toContain('59,23')
    expect(html).not.toContain('2.796.000')
    expect(html).toContain('Cómo se calcula el pre-mercado')
  })
})
