// «+ Crear un broker nuevo» desde «Mover a otro broker» abre el alta de siempre
// (BrokerManager) con un pedido que se CUENTA (`abrirAlta`, Positions.jsx). La
// revisión E12 (problema 5) encontró que el alta se abría sola: el efecto corría
// también al montarse, y el contador queda en 1 o más después de usarlo. La
// Cartera monta BrokerManager en dos ramas (sin brokers / con brokers), así que
// al pasar de una a la otra aparecía el formulario sin que nadie lo pidiera.
//
// Montado de verdad (testing/navegadorMinimo.js): corren los efectos, que es
// justo lo que `renderToStaticMarkup` no hace.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto } from '../testing/navegadorMinimo'

vi.mock('../utils/api', async (orig) => ({
  ...(await orig()),
  api: { get: vi.fn(() => Promise.resolve([])), post: vi.fn(() => Promise.resolve({})) },
}))

let BrokerManager
beforeAll(async () => {
  instalarNavegadorMinimo()
  window.matchMedia = (q) => ({ matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} })
  ;({ default: BrokerManager } = await import('./BrokerManager'))
}, 60000)
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => { if (montado) await montado.desmontar(); montado = null })

const BROKERS = [{ id: 1, name: 'Cocos', currency: 'ARS' }]
const el = (abrirAlta) => h(BrokerManager, { brokers: BROKERS, onChange: () => {}, abrirAlta })
// «Nombre del broker» sólo está en el formulario del alta (el botón dice «Agregar broker»).
const altaAbierta = () => texto(montado.contenedor).includes('Nombre del broker')

describe('BrokerManager · el alta se abre cuando la piden, no al montarse', () => {
  it('sin pedido, cerrada; un pedido nuevo (0 → 1) la abre', async () => {
    montado = await montar(el(0))
    expect(altaAbierta()).toBe(false)
    await montado.redibujar(el(1))
    expect(altaAbierta()).toBe(true)
  })

  it('montarse con un pedido VIEJO (el contador ya en 2) no la abre; uno nuevo (2 → 3), sí', async () => {
    montado = await montar(el(2))
    for (let i = 0; i < 3; i++) await montado.redibujar(el(2))
    expect(altaAbierta(), 'se abrió sola al montarse').toBe(false)
    await montado.redibujar(el(3))
    expect(altaAbierta()).toBe(true)
  })
})
