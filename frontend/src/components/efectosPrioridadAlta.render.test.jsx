import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'

// Los cuatro efectos de prioridad alta, dibujados de verdad: esqueletos con
// brillo, la punta viva del gráfico del Dashboard, el peso de cada fila en
// Cartera y "Desde tu última visita".
import Skeleton from './Skeleton'
import PuntaViva, { puntaEsDeAhora } from './PuntaViva'
import PesoEnCartera, { pesoEnCartera } from './PesoEnCartera'
import DeltaSinceVisit from './diagnostico/DeltaSinceVisit'
import { PrivacyProvider } from '../contexts/PrivacyContext'
import { handleDemoRequest } from '../utils/demo'
import { computeBrokerValue, valuePositionLot, buildPriceSymbols } from '../utils/valuation'

describe('esqueletos de carga con brillo', () => {
  it('el Skeleton compartido lleva el brillo, no el parpadeo', () => {
    const html = renderToStaticMarkup(<Skeleton className="h-3 w-10" />)
    expect(html).toContain('esqueleto')
    expect(html).not.toContain('animate-pulse')
  })
})

describe('la punta del gráfico late sólo si es el valor de ahora', () => {
  const serie = [{ date: '2026-09-28' }, { date: '2026-09-30' }]
  it('con precios cargados y la punta fechada hoy, late', () => {
    expect(puntaEsDeAhora(serie, true, '2026-09-30')).toBe(true)
  })
  it('sin precios (la punta es una foto guardada), no', () => {
    expect(puntaEsDeAhora(serie, false, '2026-09-30')).toBe(false)
  })
  it('con la última foto de otro día, no', () => {
    expect(puntaEsDeAhora(serie, true, '2026-10-01')).toBe(false)
    expect(puntaEsDeAhora([], true, '2026-09-30')).toBe(false)
  })
  it('dibuja el punto con su anillo; sin coordenadas, nada', () => {
    const svg = renderToStaticMarkup(<svg><PuntaViva cx={10} cy={20} color="red" /></svg>)
    expect(svg).toContain('anillo-vivo')
    expect((svg.match(/<circle/g) || []).length).toBe(2)
    expect(renderToStaticMarkup(<svg><PuntaViva cx={null} cy={20} color="red" /></svg>)).toBe('<svg></svg>')
  })
})

describe('el peso de cada fila dentro de su broker', () => {
  it('fracción del total de la tarjeta, con tope en 1', () => {
    expect(pesoEnCartera(250, 1000)).toBe(0.25)
    expect(pesoEnCartera(1200, 1000)).toBe(1)
  })
  it('sin valor, con saldo negativo o total en cero, no hay barra', () => {
    expect(pesoEnCartera(null, 1000)).toBe(null)
    expect(pesoEnCartera(-50, 1000)).toBe(null)
    expect(pesoEnCartera(0, 1000)).toBe(null)
    expect(pesoEnCartera(100, 0)).toBe(null)
    expect(renderToStaticMarkup(<PesoEnCartera valor={null} total={1000} />)).toBe('')
  })
  it('el porcentaje a la vista, a la argentina, y de QUÉ broker en el globo', () => {
    const html = renderToStaticMarkup(<PesoEnCartera valor={6247.5} total={21622.3} nombre="Schwab" />)
    expect(html).toContain('title="Pesa 28,9 % de Schwab"')
    // A la vista, no sólo en el globo: en el celular no hay mouse.
    expect(html.replace(/<span class="sr-only">[^<]*<\/span>/g, '')).toMatch(/>28,9 %</)
    expect(html).toContain('peso-crece')
    expect(renderToStaticMarkup(<PesoEnCartera valor={1} total={4} />)).toContain('de este broker')
  })
  it('con "Ocultar saldos" no se muestra', () => {
    globalThis.localStorage = { getItem: () => '1', setItem: () => {} }
    const html = renderToStaticMarkup(<PrivacyProvider><PesoEnCartera valor={124} total={1000} /></PrivacyProvider>)
    delete globalThis.localStorage
    expect(html).toBe('')
  })
})

describe('con la cartera del demo: en cada broker las filas suman 100 %', () => {
  it('fila ÷ total de la tarjeta, efectivo incluido', () => {
    const positions = handleDemoRequest('GET', '/positions')
    const brokers = handleDemoRequest('GET', '/brokers')
    const prices = handleDemoRequest('GET', `/prices?symbols=${buildPriceSymbols(positions, brokers).join(',')}`)
    const tc = 1424
    for (const b of brokers) {
      const lotes = positions.filter(p => p.broker === b.name)
      if (lotes.length === 0) continue
      const total = computeBrokerValue(lotes, prices, b, tc, tc, 1422, 'purchase').value
      const ctx = { broker: b, prices, tcValuacion: tc, tcCedear: tc, tcCripto: 1422, costBasis: 'purchase' }
      const suma = lotes.reduce((s, p) => s + (pesoEnCartera(valuePositionLot(p, ctx).valueUsd, total) || 0), 0)
      expect(suma, b.name).toBeCloseTo(1, 6)
    }
  })
})

describe('Desde tu última visita', () => {
  const delta = { isFirstVisit: false, valueDeltaPct: -1.2, newFindingIds: ['a'], resolvedCount: 0 }
  it('el cambio con el formato de toda la app y los chips entran de a uno', () => {
    const html = renderToStaticMarkup(<DeltaSinceVisit delta={delta} />)
    expect(html).toContain('Tu cartera')
    expect(html).toContain('1 hallazgo nuevo')
    // inline-block: si no, el desplazamiento de la entrada no se aplica.
    expect((html.match(/inline-block entra/g) || []).length).toBe(2)
    expect(html).toContain('--i:1')
  })
  it('primera visita: nada', () => {
    expect(renderToStaticMarkup(<DeltaSinceVisit delta={{ isFirstVisit: true }} />)).toBe('')
  })
})
