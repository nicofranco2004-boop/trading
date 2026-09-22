// El muro tiene que apagar lo que queda DETRÁS, y la primera versión no apagaba
// nada: buscaba los hijos de `#root` y los filtraba por "no contiene al muro",
// pero `#root` tiene un solo hijo —el <div> que envuelve la app— que SÍ lo
// contiene. La lista quedaba vacía y `inert` era un no-op silencioso.
//
// Se prueba la función sola porque los tests de este repo corren sin navegador.
import { describe, it, expect } from 'vitest'
import { hermanosDe } from './MuroElegirPlan'

// Un nodo de mentira con lo único que la función usa: parentElement y children.
function nodo(hijos = []) {
  const n = { children: hijos }
  hijos.forEach(h => { h.parentElement = n })
  return n
}

describe('hermanosDe — lo que el muro tiene que apagar', () => {
  it('devuelve los hermanos, no el muro', () => {
    const app = { id: 'app' }
    const muro = { id: 'muro' }
    const voz = { id: 'voz' }
    nodo([app, muro, voz])
    expect(hermanosDe(muro).map(n => n.id)).toEqual(['app', 'voz'])
  })

  it('NO devuelve al padre que contiene al muro (el bug exacto)', () => {
    const muro = { id: 'muro' }
    const envoltorio = nodo([muro])
    envoltorio.id = 'envoltorio'
    nodo([envoltorio])                      // #root con un solo hijo
    const apagados = hermanosDe(muro)
    expect(apagados).toEqual([])            // no hay hermanos DENTRO del envoltorio
    expect(apagados).not.toContain(envoltorio)
  })

  it('con hermanos dentro del envoltorio los devuelve todos', () => {
    const app = { id: 'app' }
    const muro = { id: 'muro' }
    nodo([app, muro])
    expect(hermanosDe(muro)).toHaveLength(1)
  })

  it('sin nodo o sin padre no revienta', () => {
    expect(hermanosDe(null)).toEqual([])
    expect(hermanosDe(undefined)).toEqual([])
    expect(hermanosDe({ })).toEqual([])
  })
})
