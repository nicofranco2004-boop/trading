// El «Mapa de tu cartera» montado de verdad (testing/navegadorMinimo.js), con el
// servidor simulado en la frontera (utils/api): «Color por» (Tendencia de
// entrada), el renglón «Hoy tu cartera» y lo que más sumó y restó, CON y SIN
// «Ocultar saldos». Es el MISMO componente en el Panorama y en el Dashboard.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, clic } from '../testing/navegadorMinimo'

const DEL_DIA = {
  hoy: '2026-10-30',
  cartera: { pct: 0.8, usd: 120, mercados: ['eeuu'] },
  activos: [
    { asset: 'NVDA', local: false, hoy: { pct: 2, usd: 150 }, dia_txt: 'hoy', promedio_pct: 30 },
    { asset: 'KO', local: false, hoy: { pct: -1, usd: -40 }, dia_txt: 'hoy', promedio_pct: -5 },
  ],
}
let pedidas
vi.mock('../utils/api', async (original) => ({
  ...(await original()),
  api: { get: vi.fn((ruta) => { pedidas.push(ruta); return Promise.resolve(ruta === '/cartera/mapa-del-dia' ? DEL_DIA : null) }) },
}))

let MapaCartera, MemoryRouter
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: MapaCartera } = await import('./MapaCartera'))
  ;({ MemoryRouter } = await import('react-router-dom'))
})
afterAll(() => { vi.unstubAllGlobals() })
let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null; localStorage.clear() })

const fila = (nombre, peso, tendencia) => ({ clave: `${nombre}|0`, nombre, ruta: nombre, tenes: true, peso, fondo: { id: tendencia } })
const FILAS = [fila('NVDA', 60, 'alcista'), fila('KO', 40, 'bajista')]

async function dibujar(hidden = false) {
  pedidas = []
  const el = () => h(MemoryRouter, null, h(MapaCartera, { filas: FILAS, cargando: false, error: null, hidden, rutaOtros: '/x' }))
  montado = await montar(el())
  for (let i = 0; i < 3; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}
function todos(pred) {
  const out = [], pila = [montado.contenedor]
  while (pila.length) { const n = pila.shift(); if (pred(n)) out.push(n); pila.push(...(n.childNodes || [])) }
  return out
}
const radios = () => todos(n => n.getAttribute?.('role') === 'radio')
const etiquetas = () => todos(n => n.getAttribute?.('aria-label') && /NVDA|KO/.test(n.getAttribute('aria-label'))).map(n => n.getAttribute('aria-label'))

describe('el mapa de tu cartera: lo de la pieza 8, en el mismo componente', () => {
  it('«Color por» con Tendencia de entrada, el renglón de hoy y lo que más sumó y restó', async () => {
    const t = await dibujar()
    expect(pedidas).toContain('/cartera/mapa-del-dia')
    expect(radios().map(texto)).toEqual(['Hoy', 'Tendencia', 'Contra tu promedio'])
    expect(radios()[1].getAttribute('aria-checked')).toBe('true')
    expect(t).toContain('Hoy tu cartera: +0,8%')
    expect(t).toContain('Lo que más sumó hoy: NVDA (+2,0%).')
    expect(t).toContain('Lo que más restó: KO (−1,0%).')
  })

  it('«Hoy» pinta con la rampa y lo dice cada cuadrito; la elección queda guardada', async () => {
    await dibujar()
    await clic(montado.contenedor, radios()[0])
    expect(radios()[0].getAttribute('aria-checked')).toBe('true')
    expect(etiquetas().some(e => e.includes('+2,0% hoy'))).toBe(true)
    const pintados = todos(n => /--pol-(up|down)-/.test(String(n.style?.background || '')))
    expect(pintados.length).toBeGreaterThanOrEqual(2)
    expect(localStorage.getItem('rendi_mapa_color')).toBe('hoy')
    await clic(montado.contenedor, radios()[2])
    expect(etiquetas().some(e => e.includes('+30,0% contra lo que pagaste'))).toBe(true)
  })

  it('con «Ocultar saldos»: el renglón sin %, de los extremos sólo QUÉ activo, y los cuadritos sin %', async () => {
    localStorage.setItem('rendi_mapa_color', 'hoy')
    const t = await dibujar(true)
    expect(t).toContain('Hoy tu cartera: ••••')
    expect(t).not.toContain('+0,8')
    expect(t).toContain('Lo que más sumó hoy: NVDA.')
    expect(t).toContain('Lo que más restó: KO.')
    expect(t).not.toMatch(/[+−]\d+,\d%/)
    expect(etiquetas().join(' ')).not.toMatch(/\d+,\d%/)
  })
})
