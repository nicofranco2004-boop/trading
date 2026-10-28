// El globo del (?) en el celular: se corre para entrar en la PÁGINA, aunque el
// navegador agrande `innerWidth` cuando el globo se sale (medido el 28/10 con el
// (?) de Beta en la ficha: la página en 375, innerWidth en 409; el globo quedaba
// con un corrimiento de 8 px y cortado). Se monta de verdad, con un click.
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, buscarBoton, clic, enActo, medidas } from '../testing/navegadorMinimo'

let InfoTooltip
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: InfoTooltip } = await import('./InfoTooltip'))
})
afterAll(() => { medidas() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  medidas()
})

function globo(contenedor) {
  const pila = [contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.atributos?.role === 'tooltip') return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

describe('el globo del (?) en un celular de 375 px', () => {
  it('se mete en la página aunque el navegador diga que la ventana mide 409', async () => {
    // Lo que se midió en la ficha: el globo, centrado en el (?) de Beta,
    // arranca en x=153 y mide 256 → termina en 409, fuera de los 375 de la página.
    window.innerWidth = 409
    document.documentElement.clientWidth = 375
    medidas(n => n.atributos?.role === 'tooltip'
      ? { left: 153 + (parseFloat(n.style.marginLeft) || 0), top: 0, width: 256, height: 80 }
      : null)
    montado = await montar(h(InfoTooltip, { label: 'Beta', align: 'center' }, h('p', null, 'Cuánto se mueve')))
    const boton = buscarBoton(montado.contenedor, '') // el único botón: el (?)
    await enActo(async () => clic(montado.contenedor, boton))
    const g = globo(montado.contenedor)
    expect(g).toBeTruthy()
    const r = g.getBoundingClientRect()
    // Entra con el margen de 8 px contra el borde de la PÁGINA (375), no el de 409.
    expect(r.right).toBeLessThanOrEqual(375 - 8)
    expect(r.left).toBeGreaterThanOrEqual(8)
  })

  it('el que ya entraba no se mueve', async () => {
    window.innerWidth = 375
    document.documentElement.clientWidth = 375
    medidas(n => n.atributos?.role === 'tooltip'
      ? { left: 20 + (parseFloat(n.style.marginLeft) || 0), top: 0, width: 256, height: 80 }
      : null)
    montado = await montar(h(InfoTooltip, { label: 'Market Cap', align: 'center' }, h('p', null, 'Cuánto vale')))
    await enActo(async () => clic(montado.contenedor, buscarBoton(montado.contenedor, '')))
    const g = globo(montado.contenedor)
    expect(g.getBoundingClientRect().left).toBe(20)
    expect(g.style.marginLeft || '').toBe('')
  })
})
