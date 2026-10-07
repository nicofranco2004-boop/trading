import { describe, it, expect, vi, beforeAll, beforeEach, afterAll } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, puntero, medidas } from '../../testing/navegadorMinimo'

// 🔴 EL CLIC CON MOUSE NO ABRÍA LA ISLA (medido 2026-10-07 en Chrome).
//
// Con el dedo abría; con el mouse, no. Registro del clic en la burbuja:
// pointerdown → BOTÓN, gotpointercapture → contenedor, pointerup → contenedor,
// click → contenedor. El arrastre "agarraba" el puntero apenas se apretaba, y
// con el puntero agarrado Chrome manda el clic del MOUSE al que lo agarró —el
// contenedor—, no al botón. El del dedo no: lo arma sobre lo que estaba debajo.
//
// Acá se monta la isla REAL (RendiMate, con la sesión y el chat reales) y el
// navegador mínimo reparte los eventos con esas mismas reglas de Chrome (ver
// `puntero` en testing/navegadorMinimo.js). Con el arreglo sacado, la primera
// prueba se pone en rojo.

// El personaje animado dibuja a mano sobre el DOM de verdad (y el navegador
// mínimo no lo tiene). Es decoración: no recibe ni reparte ningún evento del
// puntero, así que se reemplaza por un lugar vacío del mismo tipo.
vi.mock('../ai/MervallE', () => ({ default: () => null }))

let auth, voz, RendiMate, MemoryRouter, sesion
beforeAll(async () => {
  ;({ sesion } = instalarNavegadorMinimo())
  const api = await import('../../utils/api')
  vi.spyOn(api.api, 'get').mockImplementation(async () => [])
  vi.spyOn(api.api, 'post').mockImplementation(async () => ({}))
  auth = await import('../../contexts/AuthContext')
  voz = await import('../../contexts/VozContext')
  RendiMate = (await import('./RendiMate')).default
  ;({ MemoryRouter } = await import('react-router-dom'))
})
afterAll(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
beforeEach(() => { for (const k of [...sesion.keys()]) sesion.delete(k) })

function buscarPor(raiz, cumple) {
  const pila = [raiz]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeType === 1 && cumple(n)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
const conEtiqueta = (raiz, re) => buscarPor(raiz, n => re.test(n.getAttribute?.('aria-label') || ''))

async function montarIsla() {
  const v = {}
  const Mirar = () => { v.voz = voz.useVoz(); return null }
  const m = await montar(
    h(MemoryRouter, { initialEntries: ['/dashboard'] },
      h(auth.AuthProvider, null,
        h(voz.VozProvider, null, h(Mirar), h(RendiMate)))))
  const burbuja = () => conEtiqueta(m.contenedor, /abrir la conversación/)
  const abierta = () => !!conEtiqueta(m.contenedor, /^Mervall-E AI/)
  return { m, v, burbuja, abierta }
}

// Un gesto completo: apretar, moverse por `pasos` (desplazamientos desde donde
// apretó) y soltar. El puntero sigue encima de lo que se apretó, como cuando
// la isla se mueve con él.
async function gesto(debajo, pointerType, pasos = []) {
  const base = { pointerType, pointerId: pointerType === 'mouse' ? 1 : 7, clientX: 100, clientY: 100 }
  await puntero('pointerdown', debajo, base)
  let ultimo = base
  for (const [dx, dy] of pasos) {
    ultimo = { ...base, clientX: 100 + dx, clientY: 100 + dy }
    await puntero('pointermove', debajo, ultimo)
  }
  await puntero('pointerup', debajo, ultimo)
}

describe('la isla con el mouse (sesión, chat y burbuja reales)', () => {
  it('un clic de mouse en la burbuja ABRE la isla', async () => {
    const { m, burbuja, abierta } = await montarIsla()
    expect(abierta()).toBe(false)
    await gesto(burbuja(), 'mouse')
    expect(abierta()).toBe(true)
    await m.desmontar()
  })

  it('con un temblor chico del mouse (3px) también abre', async () => {
    const { m, burbuja, abierta } = await montarIsla()
    await gesto(burbuja(), 'mouse', [[2, 1], [3, 0]])
    expect(abierta()).toBe(true)
    await m.desmontar()
  })

  it('ARRASTRAR más que el umbral mueve la burbuja y NO la abre', async () => {
    const { m, burbuja, abierta } = await montarIsla()
    await gesto(burbuja(), 'mouse', [[10, 10], [-60, 60]])
    expect(abierta()).toBe(false)
    expect(JSON.parse(sesion.get('rendi:isla:pos'))).toEqual(expect.objectContaining({ dx: expect.any(Number), dy: expect.any(Number) }))
    // Y el clic siguiente, sin arrastrar, abre: el "vengo de arrastrar" no se
    // come el toque que sigue.
    await gesto(burbuja(), 'mouse')
    expect(abierta()).toBe(true)
    await m.desmontar()
  })

  it('mover el mouse SIN apretar después de un arrastre no arrastra', async () => {
    // Si el gesto anterior quedara a medias, la isla seguiría al mouse sin
    // que nadie la esté agarrando.
    const { m, burbuja } = await montarIsla()
    await gesto(burbuja(), 'mouse', [[0, 40]])
    const antes = sesion.get('rendi:isla:pos')
    await puntero('pointermove', burbuja(), { pointerType: 'mouse', pointerId: 1, clientX: 400, clientY: 400 })
    expect(sesion.get('rendi:isla:pos')).toBe(antes)
    await m.desmontar()
  })

  it('abierta: la X y el parlante andan con el mouse (viven en la cabecera que arrastra)', async () => {
    const { m, v, burbuja, abierta } = await montarIsla()
    await gesto(burbuja(), 'mouse')
    expect(abierta()).toBe(true)
    const parlante = () => buscarPor(m.contenedor, n => n.getAttribute?.('aria-pressed') != null)
    const antes = v.voz.enabled
    await gesto(parlante(), 'mouse')
    expect(v.voz.enabled).toBe(!antes)
    await gesto(conEtiqueta(m.contenedor, /^Cerrar$/), 'mouse')
    expect(abierta()).toBe(false)
    await m.desmontar()
  })

  it('abierta: arrastrar la cabecera y soltar sobre la X NO la cierra', async () => {
    const { m, burbuja, abierta } = await montarIsla()
    await gesto(burbuja(), 'mouse')
    await gesto(conEtiqueta(m.contenedor, /^Cerrar$/), 'mouse', [[40, 30], [2, 1]])
    expect(abierta()).toBe(true)
    await m.desmontar()
  })
})

describe('la isla con el dedo (lo que ya andaba, sigue andando)', () => {
  it('un toque con temblor de dedo (6px) abre', async () => {
    const { m, burbuja, abierta } = await montarIsla()
    await gesto(burbuja(), 'touch', [[4, 4], [6, 2]])
    expect(abierta()).toBe(true)
    await m.desmontar()
  })

  it('arrastrar con el dedo no abre', async () => {
    const { m, burbuja, abierta } = await montarIsla()
    await gesto(burbuja(), 'touch', [[20, -10], [80, -100]])
    expect(abierta()).toBe(false)
    await m.desmontar()
  })
})

// 🔴 AL CERRARLA, LA BURBUJA VUELVE ADONDE LA DEJÓ EL USUARIO (2026-10-07).
//
// Nico: "luego de cerrar la burbuja vuelve a una posición; debería dejarla
// donde la arrojó el usuario". MEDIDO en el navegador a 375px: soltada en
// (166, 396), abierta, cerrada → aparecía en (20, 560). La tarjeta abierta es
// mucho más grande y hay que correrla para que entre; esa corrección se
// guardaba encima de la posición elegida.
//
// Acá la pantalla es la de un celular y cada pieza mide lo que mide en el
// navegador: la burbuja nace abajo a la izquierda, la tarjeta arriba de borde
// a borde.
describe('la burbuja vuelve adonde la dejaste (celular, isla real)', () => {
  beforeAll(() => {
    window.innerWidth = 375
    window.innerHeight = 812
    medidas((n) => {
      if (n.getAttribute('data-tour') === 'isla') return { left: 16, top: 696, width: 159, height: 34 }
      if (n.tagName === 'SECTION') return { left: 12, top: 88, width: 351, height: 420 }
      return null
    })
  })
  afterAll(() => { medidas(null); window.innerWidth = 1280; window.innerHeight = 800 })

  const desplazamiento = (nodo) => nodo.style.transform || 'ninguno'

  it('soltar, abrir y cerrar: la burbuja queda donde la soltaste', async () => {
    const { m, burbuja, abierta } = await montarIsla()
    const isla = () => buscarPor(m.contenedor, n => n.getAttribute?.('data-tour') === 'isla')
    await gesto(burbuja(), 'mouse', [[10, -10], [150, -300]])
    const soltada = desplazamiento(isla())
    expect(soltada).toBe('translate3d(150px, -300px, 0)')

    await gesto(burbuja(), 'mouse')
    expect(abierta()).toBe(true)
    // Abierta, la corrió para que entre (si no, quedaba 212px arriba, afuera).
    const tarjeta = buscarPor(m.contenedor, n => n.tagName === 'SECTION')
    expect(tarjeta.getBoundingClientRect().top).toBeGreaterThanOrEqual(8)

    await gesto(conEtiqueta(m.contenedor, /^Cerrar$/), 'mouse')
    expect(abierta()).toBe(false)
    expect(desplazamiento(isla())).toBe(soltada)
    // Y lo guardado para la pestaña sigue siendo lo que eligió el usuario.
    expect(JSON.parse(sesion.get('rendi:isla:pos'))).toEqual({ dx: 150, dy: -300 })
    await m.desmontar()
  })

  it('la app abierta de nuevo (pestaña nueva) arranca en su lugar de siempre', async () => {
    // sessionStorage vacío = pestaña nueva (beforeEach lo limpia).
    const { m } = await montarIsla()
    const isla = buscarPor(m.contenedor, n => n.getAttribute?.('data-tour') === 'isla')
    expect(desplazamiento(isla)).toBe('ninguno')
    await m.desmontar()
  })
})
