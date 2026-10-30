// «Desde tu última visita» (Análisis › Diagnóstico) es de la persona Y de la
// cuenta (utils/duenoDeLaPestana), adentro del hook: ninguna pantalla que lo use
// se lo puede olvidar.
//
// Re-test a ciegas del 30/10: la huella se guardaba por persona y no por cuenta.
// El asesor miraba el cliente 2 (US$ 41.536,95) y al abrir el 3 el «cambió X %
// desde tu última visita» se calculaba contra la cartera del 2 (+94,7 %).
//
// Montado con react-dom (testing/navegadorMinimo), con las piezas de verdad: la
// sesión que AuthContext guarda en `rendi_user` (y que api.js borra con un 401)
// y el cliente del asesor por setClientContext de api.js.
import { describe, it, expect, beforeAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo } from '../testing/navegadorMinimo'

let api, useLastVisit, CATALOGO
beforeAll(async () => {
  instalarNavegadorMinimo()
  api = await import('../utils/api')
  ;({ useLastVisit } = await import('./useLastVisit'))
  ;({ CATALOGO } = await import('../utils/catalogoDelAlmacen'))
})

const entrar = (email) => localStorage.setItem('rendi_user', JSON.stringify({ name: email, email }))
let montado = null
const visto = {}
// Una pantalla que usa el hook como Insights: la clave de la sección y record()
// con el valor de la cartera que está mirando.
function Pantalla({ valor }) {
  const lastVisit = useLastVisit(CATALOGO.ultimaVisitaDiagnostico)
  visto.delta = lastVisit.record({ valueUsd: valor, findingIds: [] }).delta
  return null
}
// Abrir la pantalla con la cartera que está a la vista (una visita).
async function visitar(valor) {
  if (montado) await montado.desmontar()
  montado = await montar(h(Pantalla, { valor }))
  await enActo(async () => {})          // el efecto que guarda la huella
  return visto.delta
}

beforeEach(() => entrar('asesora@prueba.test'))
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()
  api.setClientContext(null)
})

describe('«desde tu última visita» es de la persona y de la cuenta', () => {
  it('el asesor mira el cliente 2 y después el 3: el 3 no se compara contra el 2', async () => {
    api.setClientContext({ id: 2, label: 'Dos' })
    expect((await visitar(41536.95)).isFirstVisit).toBe(true)
    api.setClientContext({ id: 3, label: 'Tres' })
    const delta3 = await visitar(80877.49)
    expect(delta3.isFirstVisit).toBe(true)               // primera visita del 3, no «+94,7 %»
    expect(delta3.valueDeltaPct).toBeUndefined()
    api.setClientContext({ id: 2, label: 'Dos' })
    const delta2 = await visitar(41536.95)
    expect(delta2.isFirstVisit).toBe(false)              // el 2 sí tiene su visita anterior
    expect(delta2.valueDeltaPct).toBe(0)
  })

  it('a Ana se le vence la sesión y entra Bruno: Bruno no se compara contra Ana', async () => {
    entrar('ana@prueba.test')
    await visitar(1000)
    localStorage.removeItem('rendi_user')                // lo que hace api.js con un 401
    entrar('bruno@prueba.test')
    expect((await visitar(5000)).isFirstVisit).toBe(true)
  })

  it('pantalla abierta en el cliente 2 y OTRA pestaña entra al 3: el número del 2 no se guarda en el 3 (re-test 2)', async () => {
    api.setClientContext({ id: 3, label: 'Tres' })
    await visitar(80877.49)                               // la visita del 3, con su valor
    api.setClientContext({ id: 2, label: 'Dos' })
    await visitar(41536.95)                               // pantalla abierta en el 2
    // Otra pestaña entra al 3; ésta sigue mostrando el 2 y vuelve a dibujar.
    await enActo(async () => { api.setClientContext({ id: 3, label: 'Tres' }) })
    await enActo(async () => { await montado.redibujar(h(Pantalla, { valor: 41536.95 * 1.1 })) })
    api.setClientContext({ id: 3, label: 'Tres' })
    const delta3 = await visitar(80877.49)                // el 3 se compara contra SÍ mismo
    expect(delta3.isFirstVisit).toBe(false)
    expect(delta3.valueDeltaPct).toBe(0)
    api.setClientContext({ id: 2, label: 'Dos' })
    expect((await visitar(41536.95)).valueDeltaPct).toBe(0)   // y lo del 2 no cambió tampoco
  })

  it('pantalla abierta de Ana y OTRA pestaña entra como Bruno: la plata de Ana no queda a nombre de Bruno (re-test 2)', async () => {
    entrar('ana@prueba.test')
    await visitar(41536.95)
    entrar('bruno@prueba.test')                           // otra pestaña: la sesión pasa a Bruno
    await enActo(async () => { await montado.redibujar(h(Pantalla, { valor: 41536.95 * 1.2 })) })
    const claves = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
    expect(claves.filter(k => k.includes('bruno'))).toEqual([])
    expect((await visitar(124610.84)).isFirstVisit).toBe(true)   // Bruno: su primera visita
  })

  it('sin nadie logueado no se guarda huella', async () => {
    localStorage.removeItem('rendi_user')
    await visitar(1000)
    const claves = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
    expect(claves.filter(k => k.startsWith('rendi_lastvisit_'))).toEqual([])
  })
})
