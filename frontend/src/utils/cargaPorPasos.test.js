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
    { asset: 'FCI:COCOS-RENDIMIENTO-A' },            // fondo del catálogo (salía como chip en prod, 2026-10-02)
    { asset: 'OTRO FONDO', asset_type: 'FUND' },      // fondo marcado FUND
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

import { pasosDiagnostico } from './cargaPorPasos'

describe('pasosDiagnostico — los 10 pedidos y los precios, agrupados', () => {
  it('un grupo se tilda cuando volvieron TODAS sus piezas, con su cuenta', () => {
    const pasos = pasosDiagnostico({ monthly: 12, positions: 9, brokers: 2, operations: 85 })
    const por = Object.fromEntries(pasos.map(p => [p.id, p]))
    expect(por.historial).toMatchObject({ estado: 'listo', detalle: '12 meses' })
    expect(por.cartera).toMatchObject({ estado: 'listo', detalle: '9 activos' })
    expect(por.operaciones.estado).toBe('cargando')        // falta commissions
    expect(por.precios.estado).toBe('cargando')
  })
  it('un pedido caído lo dice', () => {
    const p = pasosDiagnostico({ snapshots: 'error' }).find(x => x.id === 'fotos')
    expect(p.estado).toBe('error')
  })
  it('en Perfil de inversor, el test va primero', () => {
    expect(pasosDiagnostico({}, { perfilPrimero: true })[0].id).toBe('perfil')
    expect(pasosDiagnostico({})[0].id).toBe('historial')
  })
  it('los precios dicen "al día" al llegar', () => {
    expect(pasosDiagnostico({ prices: true }).find(x => x.id === 'precios').detalle).toBe('al día')
  })
})

import { mesesDelHistorial, faltaLoImprescindible } from './cargaPorPasos'

describe('mesesDelHistorial — meses, no renglones de /monthly', () => {
  // La forma de /api/monthly: un renglón por broker y por mes, más el "global".
  const fila = (broker, year, month) => ({ broker, year, month })
  const doceMesesDosBrokers = []
  for (let m = 1; m <= 12; m++) {
    doceMesesDosBrokers.push(fila('Cocos', 2026, m), fila('Schwab', 2026, m), fila('global', 2026, m))
  }
  it('12 meses con 2 brokers son 12 meses (el cargador decía "36 meses")', () => {
    expect(doceMesesDosBrokers).toHaveLength(36)
    expect(mesesDelHistorial(doceMesesDosBrokers)).toBe(12)
    const p = pasosDiagnostico({ monthly: mesesDelHistorial(doceMesesDosBrokers) }).find(x => x.id === 'historial')
    expect(p.detalle).toBe('12 meses')
  })
  it('sin el renglón global, los meses distintos de todos', () => {
    expect(mesesDelHistorial([fila('Cocos', 2025, 12), fila('Schwab', 2025, 12), fila('Cocos', 2026, 1)])).toBe(2)
  })
  it('nada o algo raro: 0', () => {
    expect(mesesDelHistorial([])).toBe(0)
    expect(mesesDelHistorial(null)).toBe(0)
  })
})

describe('faltaLoImprescindible — sin historial, posiciones o brokers no se calcula', () => {
  it('cualquiera de las tres caída: la pantalla lo dice', () => {
    expect(faltaLoImprescindible({ brokers: 'error' })).toBe(true)
    expect(faltaLoImprescindible({ positions: 'error' })).toBe(true)
    expect(faltaLoImprescindible({ monthly: 'error' })).toBe(true)
  })
  it('las demás caídas no frenan la página (salen sin esa parte)', () => {
    expect(faltaLoImprescindible({ snapshots: 'error', benchmarks: 'error', prices: 'error' })).toBe(false)
    expect(faltaLoImprescindible({ positions: 9, brokers: 2, monthly: 12 })).toBe(false)
    expect(faltaLoImprescindible({})).toBe(false)
  })
})
