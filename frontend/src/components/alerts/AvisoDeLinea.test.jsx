// El aviso de una línea tuya desde la sección Alertas (Nico, 29/10), montado
// de verdad (testing/navegadorMinimo.js):
//   · «Señal técnica» → «Una línea que dibujaste» → el activo → tus líneas de
//     ese activo, con su gráfico chiquito (GET /api/tecnico/…/lineas, la forma
//     de alerts_engine.resumen_de_dibujo) → elegir el canal → por qué borde y
//     cuándo cuenta → lo que viaja al servidor (main._crear_alerta_de_linea);
//   · «Mis alertas»: el gráfico chiquito, dónde está el precio, «Ver en el
//     gráfico» con la línea elegida y, si la borraste, el tacho.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto, enActo, clic, buscarBoton, buscar } from '../../testing/navegadorMinimo'

vi.mock('../../hooks/usePushNotifications', () => ({
  usePushNotifications: () => ({ supported: false, permission: 'default', subscribed: false, subscribe: vi.fn(), unsubscribe: vi.fn() }),
}))
const serie = Array.from({ length: 60 }, (_, i) => 180 + i * 0.13)
const LINEAS = [
  { id: 'c1', tipo: 'canal', color: null, fecha: '2026-10-28', ultimo: 187.6, hoy: [182.23, 193.75], serie,
    lineas: [serie.map((_, i) => 175 + i * 0.12), serie.map((_, i) => 186 + i * 0.13)] },
  { id: 'h1', tipo: 'horizontal', color: 'ambar', fecha: '2026-10-28', ultimo: 187.6, hoy: [196], serie, lineas: [serie.map(() => 196)] },
]
const pedidos = []
vi.mock('../../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => {
      pedidos.push(ruta)
      if (ruta.startsWith('/tecnico/AAPL/lineas')) return Promise.resolve({ lineas: LINEAS })
      if (ruta.startsWith('/tecnico/')) return Promise.resolve({ lineas: [] })
      if (ruta === '/alerts') return Promise.resolve({ items: [] })
      return Promise.resolve([])
    }),
  },
}))

let AlertaForm, MisAlertas, caminoALaLinea
beforeAll(async () => {
  instalarNavegadorMinimo()
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
  window.matchMedia = globalThis.matchMedia
  ;({ default: AlertaForm } = await import('./AlertaForm'))
  ;({ default: MisAlertas, caminoALaLinea } = await import('./MisAlertas'))
})
afterAll(() => vi.unstubAllGlobals())
let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; pedidos.length = 0 })

const esperar = () => enActo(() => new Promise(r => setTimeout(r, 450)))
const boton = (parte) => buscarBoton(montado.contenedor, parte)
const tocar = async (parte) => { await enActo(async () => clic(montado.contenedor, boton(parte))) }

describe('Alertas → Una línea que dibujaste', () => {
  it('elegís el activo, aparecen tus líneas y el canal pregunta por qué borde y cuándo cuenta', async () => {
    const crear = vi.fn(() => Promise.resolve({ ok: true, id: 9 }))
    const plan = { can: () => true, limit: () => null }
    // El activo, como si se hubiera elegido en el buscador (el navegador de
    // prueba no tipea en un campo controlado).
    montado = await montar(h(MemoryRouter, null, h(AlertaForm, { plan, prefill: { kind: 'tecnica', symbol: 'AAPL' }, onClose() {}, crear })))
    expect(texto(montado.contenedor)).toContain('Su impulso (RSI) baje de 30')     // de entrada, la lista de señales
    await tocar('Una línea que dibujaste')
    await esperar()
    expect(pedidos).toContain('/tecnico/AAPL/lineas?moneda=usd&accion_local=false')
    const t = texto(montado.contenedor)
    expect(t).toContain('Tus dibujos en AAPL (en dólares)')
    expect(t).toContain('CanalHoy va de US$ 182,23 a US$ 193,75')
    expect(t).toContain('Línea horizontalUS$ 196,00')
    expect(t).toContain('Fibonacci, Elliott y los trazos a mano no tienen aviso')
    // Sin elegir línea no se crea.
    await enActo(async () => { for (const fn of montado.contenedor.escuchas.submit || []) fn({ type: 'submit', target: buscar(montado.contenedor, 'form'), bubbles: true, preventDefault() {}, stopPropagation() {} }) })
    expect(texto(montado.contenedor)).toContain('Elegí una de tus líneas.')
    expect(crear).not.toHaveBeenCalled()
    await tocar('Hoy va de US$ 182,23')
    expect(texto(montado.contenedor)).toContain('Por qué borde')
    await tocar('Por abajo')
    expect(texto(montado.contenedor)).toContain('Te avisamos cuando AAPL toque o pase el borde de abajo de tu canal.')
    await enActo(async () => { for (const fn of montado.contenedor.escuchas.submit || []) fn({ type: 'submit', target: buscar(montado.contenedor, 'form'), bubbles: true, preventDefault() {}, stopPropagation() {} }) })
    expect(crear).toHaveBeenCalledWith({ kind: 'tecnica', scope: 'ticker', symbol: 'AAPL', senal: 'linea', direction: 'below',
      currency: 'USD', accion_local: false, channel: 'both', repeat: 'once', dibujo: 'c1', modo: 'toque' })
  })

  it('sin líneas en ese activo, te lleva a dibujar una', async () => {
    const plan = { can: () => true, limit: () => null }
    montado = await montar(h(MemoryRouter, null, h(AlertaForm, { plan, prefill: { kind: 'tecnica', symbol: 'KO' }, onClose() {}, crear: vi.fn() })))
    await tocar('Una línea que dibujaste')
    await esperar()
    expect(texto(montado.contenedor)).toContain('Todavía no dibujaste líneas en KO en dólares. Dibujá una en su gráfico')
  })
})

describe('«Mis alertas» con el aviso de tu canal', () => {
  const aviso = (extra = {}) => ({ id: 5, kind: 'tecnica', senal: 'linea', symbol: 'AAPL', currency: 'USD', direction: 'either', active: true, repeat: 'once',
    dibujo: JSON.stringify({ asset: 'AAPL', moneda: 'usd', id: 'c1', tipo: 'canal', modo: 'toque' }), ...extra })
  const lista = (items, lineas, onQuitar = vi.fn()) => h(MemoryRouter, null, h(MisAlertas, {
    items, events: [], precios: {}, resumen: { prendido: false }, hoy: '2026-10-29', lineas, onEditar() {}, onPausar() {}, onQuitar, onIrACrear() {} }))

  it('el gráfico chiquito, dónde está el precio y «Ver en el gráfico» con el canal elegido', async () => {
    montado = await montar(lista([aviso()], { 5: LINEAS[0] }))
    const t = texto(montado.contenedor)
    expect(t).toContain('AAPL sale de tu canal, por cualquier borde')
    expect(t).toContain('Está en US$ 187,60 · adentro, a 2,9 % del borde de abajo')
    expect(t).toContain('Ver en el gráfico')
    expect(caminoALaLinea(aviso())).toBe('/activo/AAPL?linea=c1&moneda=usd')
    const svgs = []
    const pila = [montado.contenedor]
    while (pila.length) { const n = pila.shift(); if (n.nodeName === 'SVG' && n.getAttribute?.('aria-label')) svgs.push(n); pila.push(...(n.childNodes || [])) }
    expect(svgs.map(n => n.getAttribute('aria-label'))).toEqual(['Tu canal de AAPL', 'Tu canal de AAPL'])   // compu y celular
  })

  it('si borraste el canal: se apagó, sin gráfico ni link, y el tacho lo quita', async () => {
    const onQuitar = vi.fn()
    montado = await montar(lista([aviso({ active: false })], { 5: { borrada: true } }, onQuitar))
    const t = texto(montado.contenedor)
    expect(t).toContain('Se apagó: borraste la línea del gráfico')
    expect(t).not.toContain('Ver en el gráfico')
    const tacho = []
    const pila = [montado.contenedor]
    while (pila.length) { const n = pila.shift(); if (n.getAttribute?.('aria-label') === 'Quitar el aviso de AAPL') tacho.push(n); pila.push(...(n.childNodes || [])) }
    expect(tacho).toHaveLength(1)
    await enActo(async () => clic(montado.contenedor, tacho[0]))
    expect(onQuitar).toHaveBeenCalledTimes(1)
  })
})
