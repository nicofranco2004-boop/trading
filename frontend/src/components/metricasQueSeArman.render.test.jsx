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

// El caso reportado: "Inflación: le perdés" al lado de un "Este año · vs el S&P"
// que mide otro período. La tarjeta dice desde cuándo mide, y la celda de
// inflación por qué algo en dólares puede perderle.
describe('¿Le ganás a las alternativas? — el período y el porqué, escritos', () => {
  const contexto = 'Entre noviembre de 2024 y septiembre de 2026 los precios subieron 67% y el dólar blue 39%: algo en dólares —el S&P incluido— tenía que rendir 20% en dólares sólo para empatar.'
  const html = renderToStaticMarkup(<ArAlternativesVerdict desde="noviembre de 2024" items={[
    { key: 'dolar', label: 'Dólar', pct: 6.1 },
    { key: 'inflacion', label: 'Inflación', pct: -6.4, nota: 'tu patrimonio de hoy vs la misma plata ajustada por inflación', contexto },
  ]} />)
  it('el período que miden las tres, arriba: lo que pusiste desde el primer mes contra lo que vale hoy', () => {
    expect(html).toContain('Toda tu historia: lo que pusiste desde noviembre de 2024, contra lo que vale hoy')
  })
  it('la celda de inflación explica cuánto subieron los precios y cuánto el dólar', () => {
    expect(html).toContain(contexto.replace('&', '&amp;'))
  })
  it('aclara que no cambia con Certero/Estimado', () => {
    expect(html).toContain('Es igual en Certero y en Estimado')
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
