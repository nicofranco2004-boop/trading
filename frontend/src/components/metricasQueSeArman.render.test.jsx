import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ArAlternativesVerdict from './ArAlternativesVerdict'
import { ContribList } from '../pages/Insights'

// Lo que se ve, armado (sin navegador `visto` arranca en true: es el estado
// final, el que queda después de la animación).

describe('¿Le ganás a las alternativas? — la celda armada', () => {
  const html = renderToStaticMarkup(<ArAlternativesVerdict items={[
    { key: 'pf', label: 'Plazo fijo UVA', pct: 4.2 },
    { key: 'usd', label: 'Dólar blue', pct: -1.84 },
  ]} />)
  it('el porcentaje con el signo menos de verdad (antes "-1,8%" con guion)', () => {
    expect(html).toContain('+4,2%')
    expect(html).toContain('−1,8%')
    expect(html).not.toMatch(/>-\d/)
  })
  it('"Le ganás"/"Le perdés" se ponen con su tilde (tilde-entra)', () => {
    expect((html.match(/tilde-entra/g) || []).length).toBe(2)
    expect(html).toContain('Le perdés')
  })
  it('la barra: hacia la derecha si ganás, hacia la izquierda si perdés, en la misma escala', () => {
    expect(html).toMatch(/left-1\/2 bg-rendi-pos[^"]*crece-ancho[^"]*" style="width:50%;--i:0;transform-origin:left"/)
    // 1,84 de 4,2 → 21,9 % del ancho (media barra = la más grande)
    expect(html).toMatch(/right-1\/2 bg-rendi-neg[^"]*crece-ancho[^"]*" style="width:21\.9\d*%;--i:1;transform-origin:right"/)
  })
})

describe('Atribución por activo — una barra por fila, en una escala común', () => {
  const fmt = (n) => `${n >= 0 ? '+' : '−'}USD ${Math.abs(n).toFixed(2)}`
  const html = renderToStaticMarkup(<ContribList tone="positive" title="A favor" fmt={fmt} escala={2000}
    items={[{ asset: 'BTC', pnl: 2000 }, { asset: 'NVDA', pnl: 500 }]} />)
  it('el más grande llena la barra; los demás, en proporción', () => {
    expect(html).toMatch(/crece-ancho" style="width:100%;--i:0"/)
    expect(html).toMatch(/crece-ancho" style="width:25%;--i:1"/)
  })
  it('las filas entran en escalera y el monto final se escribe', () => {
    expect((html.match(/class="py-1 entra"/g) || []).length).toBe(2)
    expect(html).toContain('+USD 2000.00')
  })
  it('"En contra" sigue a "A favor" en la escalera (desde)', () => {
    const contra = renderToStaticMarkup(<ContribList tone="negative" title="En contra" fmt={fmt} escala={2000} desde={2}
      items={[{ asset: 'AMD', pnl: -240 }]} />)
    expect(contra).toMatch(/--i:2/)
    expect(contra).toContain('−USD 240.00')
  })
})
