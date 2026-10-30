// El «No me interesa» de las tarjetas del Diagnóstico es de la persona Y de la
// cuenta (utils/duenoDeLaPestana): lo que el asesor descarta en el cliente 2 no
// se esconde en el 3 (re-test a ciegas, 30/10).
//
// Montado con react-dom (testing/navegadorMinimo), con las piezas de verdad: la
// sesión de `rendi_user` (la que api.js borra con un 401) y el cliente del
// asesor por setClientContext de api.js — que avisa el cambio de cuenta, y el
// hook lo escucha con la pantalla abierta.
import { describe, it, expect, beforeAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, enActo } from '../testing/navegadorMinimo'

let api, useDescartesDelDiagnostico
beforeAll(async () => {
  instalarNavegadorMinimo()
  api = await import('../utils/api')
  ;({ useDescartesDelDiagnostico } = await import('./useDescartesDelDiagnostico'))
})

const entrar = (email) => localStorage.setItem('rendi_user', JSON.stringify({ name: email, email }))
let montado = null
const pantalla = {}
// Como DiagnosisSection: lee el estado, y al descartar actualiza y guarda.
function Diagnostico() {
  const [state, setState, guardar] = useDescartesDelDiagnostico()
  pantalla.descartadas = [...state.dismissed]
  pantalla.descartar = (id) => setState(prev => {
    const dismissed = new Set([...prev.dismissed, id])
    guardar(dismissed, prev.slots)
    return { dismissed, slots: prev.slots }
  })
  return null
}
async function abrir() {
  if (montado) await montado.desmontar()
  montado = await montar(h(Diagnostico))
}
const cambiarDeCliente = (ctx) => enActo(async () => { api.setClientContext(ctx) })

beforeEach(() => entrar('asesora@prueba.test'))
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()
  api.setClientContext(null)
})

describe('las tarjetas descartadas son de la persona y de la cuenta', () => {
  it('el asesor descarta una en el cliente 2 y abre el 3: en el 3 sigue a la vista', async () => {
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir()
    await enActo(async () => pantalla.descartar('concentracion'))
    expect(pantalla.descartadas).toEqual(['concentracion'])
    api.setClientContext({ id: 3, label: 'Tres' })
    await abrir()
    expect(pantalla.descartadas).toEqual([])
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir()
    expect(pantalla.descartadas).toEqual(['concentracion'])   // la del 2 sigue en el 2
  })

  it('con la pantalla abierta, el cambio de cliente trae las del cliente nuevo', async () => {
    api.setClientContext({ id: 2, label: 'Dos' })
    await abrir()
    await enActo(async () => pantalla.descartar('concentracion'))
    await cambiarDeCliente({ id: 3, label: 'Tres' })
    expect(pantalla.descartadas).toEqual([])
  })

  it('a Ana se le vence la sesión y entra Bruno: no hereda lo que descartó Ana', async () => {
    entrar('ana@prueba.test')
    await abrir()
    await enActo(async () => pantalla.descartar('liquidez'))
    localStorage.removeItem('rendi_user')                     // lo que hace api.js con un 401
    entrar('bruno@prueba.test')
    await abrir()
    expect(pantalla.descartadas).toEqual([])
  })
})
