import { describe, it, expect } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { createElement as h } from 'react'
import {
  cuantos, paso, empresasDeLaCartera, chipsDeEmpresas, MAXIMO_CHIPS,
  pasosEventosParaTi, pasosEventosPopulares, pasosNoticias,
} from './cargaPorPasos'
import CargaPorPasos from '../components/novedades/CargaPorPasos'

describe('paso — un pedido real, con su tilde cuando vuelve', () => {
  it('null = cargando; con dato = listo con lo que trajo; error = no respondió', () => {
    expect(paso('a', 'Algo', null, 'x')).toEqual({ id: 'a', etiqueta: 'Algo', estado: 'cargando', detalle: null })
    expect(paso('a', 'Algo', [1, 2], d => cuantos(d.length, 'cosa', 'cosas')).detalle).toBe('2 cosas')
    expect(paso('a', 'Algo', [], d => cuantos(d.length, 'cosa', 'cosas')).detalle).toBe('0 cosas')
    expect(paso('a', 'Algo', null, 'x', { error: true }).estado).toBe('error')
  })
  it('singular y plural', () => {
    expect(cuantos(1, 'evento', 'eventos')).toBe('1 evento')
    expect(cuantos(3, 'evento', 'eventos')).toBe('3 eventos')
  })
})

describe('empresasDeLaCartera — lo que tiene earnings y dividendos', () => {
  const pos = [
    { asset: 'NVDA' }, { asset: 'nvda' },            // repetida (otro broker / minúscula)
    { asset: 'KO', asset_type: 'cedear' },
    { asset: 'USD', is_cash: 1 }, { asset: 'USDT' },  // efectivo
    { asset: 'BTC' },                                 // cripto
    { asset: 'AL30' }, { asset: 'GD35' },             // bonos que la pantalla conoce
    { asset: 'T30J6' },                               // bono que sólo conoce el servidor: lo agarra la forma del ticker
    { asset: 'PNDCO', asset_type: 'on' },             // ON marcada como tal
    { asset: 'FIMA PREMIUM', asset_type: 'fci' },     // fondo
  ]
  it('sin efectivo, cripto, bonos, ONs ni fondos, y sin repetir', () => {
    expect(empresasDeLaCartera(pos)).toEqual(['NVDA', 'KO'])
  })
  it('sin posiciones, nada', () => {
    expect(empresasDeLaCartera(null)).toEqual([])
  })
})

describe('chipsDeEmpresas — barren mientras se buscan, aterrizan con su cuenta', () => {
  it('sin respuesta todavía: todos buscando', () => {
    expect(chipsDeEmpresas(['NVDA', 'KO'], null).map(c => c.estado)).toEqual(['buscando', 'buscando'])
  })
  it('con la respuesta: cada empresa con cuántos eventos trajo (0 si ninguno)', () => {
    const evs = [{ ticker: 'NVDA' }, { ticker: 'nvda' }, { ticker: 'AAPL' }]
    expect(chipsDeEmpresas(['NVDA', 'KO'], evs)).toEqual([
      { simbolo: 'NVDA', estado: 'listo', cuenta: 2 },
      { simbolo: 'KO', estado: 'listo', cuenta: 0 },
    ])
  })
  it('un tope de chips: una cartera de 60 empresas no llena la pantalla', () => {
    const muchas = Array.from({ length: 60 }, (_, i) => `T${i}X`)
    expect(chipsDeEmpresas(muchas, null)).toHaveLength(MAXIMO_CHIPS)
  })
})

describe('los pasos de cada pestaña', () => {
  it('Eventos · Para ti: cartera, acciones y precios, cada uno con lo que trajo', () => {
    const pasos = pasosEventosParaTi({
      positions: [{ asset: 'NVDA' }, { asset: 'KO' }, { asset: 'USD', is_cash: 1 }],
      eventos: [{ ticker: 'NVDA' }], precios: null,
    })
    expect(pasos.map(p => [p.id, p.estado, p.detalle])).toEqual([
      ['cartera', 'listo', '2 activos'],
      ['acciones', 'listo', '1 evento'],
      ['precios', 'cargando', null],
    ])
  })
  it('Eventos · Para ti: si los eventos no respondieron, lo dice', () => {
    expect(pasosEventosParaTi({ fallo: { cartera: true } })[1].estado).toBe('error')
  })
  it('Eventos · Populares: el mercado primero, después tu cartera', () => {
    expect(pasosEventosPopulares({}).map(p => p.id)).toEqual(['mercado', 'cartera'])
  })
  it('Noticias: el pedido de la pestaña que mirás va primero', () => {
    expect(pasosNoticias({ primero: 'portfolio' }).map(p => p.id)).toEqual(['cartera', 'mercado'])
    expect(pasosNoticias({ primero: 'market' }).map(p => p.id)).toEqual(['mercado', 'cartera'])
    expect(pasosNoticias({ mercado: [1, 2, 3] })[1].detalle).toBe('3 noticias')
  })
})

describe('CargaPorPasos — lo que se ve', () => {
  const html = renderToStaticMarkup(h(CargaPorPasos, {
    titulo: 'Cargando tus eventos',
    pasos: [
      { id: 'cartera', etiqueta: 'Tu cartera', estado: 'listo', detalle: '12 activos' },
      { id: 'acciones', etiqueta: 'Earnings y dividendos de tus acciones', estado: 'cargando', detalle: null },
    ],
    chips: [
      { simbolo: 'NVDA', estado: 'buscando', cuenta: null },
      { simbolo: 'KO', estado: 'listo', cuenta: 2 },
      { simbolo: 'MELI', estado: 'listo', cuenta: 0 },
    ],
  }))
  it('anuncia que está cargando (lectores de pantalla) y dice cada paso', () => {
    expect(html).toContain('role="status"')
    expect(html).toContain('aria-label="Cargando tus eventos"')
    expect(html).toContain('Tu cartera')
    expect(html).toContain('12 activos')
    expect(html).toContain('Earnings y dividendos de tus acciones')
  })
  it('el que carga gira (y no gira con "reducir movimiento"); el listo no', () => {
    expect((html.match(/animate-spin/g) || [])).toHaveLength(1)
    expect(html).toContain('motion-reduce:animate-none')
  })
  it('el chip que se busca barre; el que llegó aterriza con su cuenta, o "–" si no trajo nada', () => {
    expect(html).toMatch(/chip-escaneando[^>]*>NVDA/)
    expect(html).toMatch(/chip-listo[^>]*>KO<span[^>]*>2</)
    expect(html).toMatch(/chip-listo[^>]*>MELI<span[^>]*>–</)
  })
  it('sin chips, no dibuja la fila', () => {
    const sinChips = renderToStaticMarkup(h(CargaPorPasos, { pasos: [] }))
    expect(sinChips).not.toContain('chip-')
  })
})
