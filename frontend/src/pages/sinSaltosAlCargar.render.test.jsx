// El inicio y el Dashboard no saltan al terminar de cargar (auditoría SEO
// 16/11/2026: el CLS —cuánto se mueve la pantalla sola— era la única medida de
// velocidad en rojo para Google, 0,43 en celulares con usuarios reales).
//
// QUÉ PASABA
// ──────────
// · Inicio del celular: la lista «Tu setup en Rendi» vivía sólo en la pantalla
//   terminada. Sus pedidos salían recién cuando el inicio ya había cargado y la
//   lista aparecía una vuelta de red DESPUÉS, arriba de todo, empujando «Tu
//   cartera» y las tarjetas casi 1000 px hacia abajo. En el laboratorio (Chrome a
//   412 px, 4G lenta): CLS 0,77 en 4 de 4 cargas.
// · Inicio de la compu: la misma lista, que sí arrancaba con la página pero
//   igual llegaba después que el resto: 0,31.
// · Dashboard: el cartel «Nuevo · IA contextual» se prendía un dibujo después
//   que la pantalla (estado en un efecto) y el renglón «Precios de hace…»
//   aparecía al llegar los precios: 0,16.
//
// CÓMO SE PRUEBA
// ──────────────
// La app entera (testing/pantallaConOjito: shell, rutas y proveedores de verdad)
// con la cuenta del demo, cuyos pedidos pasan por utils/api.js como en producción
// y tardan lo mismo cada uno (80 ms): nada se adelanta ni se atrasa a mano. Un
// <Profiler> mira la pantalla en CADA dibujo de React, no cada tanto: el salto
// duraba un par de dibujos, y una prueba que mira de a ratos lo puede perder
// —igual que Chrome en el laboratorio, que en una copia local lo contó 1 de 4
// veces aunque la lista se movía las 4—.
//
// Sin navegador no hay alturas. Lo que se mira es si cada caja está o no está,
// que es lo que movía todo: desde el primer dibujo en que se ve el contenido, lo
// que va arriba ya tiene que estar, y no aparecer después.
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest'
import { createElement as h, Profiler } from 'react'
import { prepararApp, cargando } from '../testing/pantallaConOjito'
import { montar } from '../testing/navegadorMinimo'
import { CLAVES_DE_LOS_TOURS } from '../components/tour/recorrido'
import { TOPE_ESPERA_LISTA_MS } from '../hooks/useEsperaDeLaLista'

// Un pedido del demo que no contesta nunca (servidor trabado), para la prueba del tope.
const control = vi.hoisted(() => ({ colgado: null }))
vi.mock('../utils/demo', async (io) => {
  const orig = await io()
  return {
    ...orig,
    handleDemoRequest: (m, p, b) => (control.colgado && p.startsWith(control.colgado)
      ? new Promise(() => {})
      : orig.handleDemoRequest(m, p, b)),
  }
})
// El muñequito animado de Mervall-E dibuja un SVG que el navegador mínimo no tiene; no muestra datos.
vi.mock('../components/ai/mervalle/motor', async (io) => ({
  ...(await io()), crearMervallE: () => new Proxy({}, { get: () => () => {} }),
}))

// El texto que se VE: lo que está adentro de algo `hidden` o `invisible` no.
function textoVisible(n) {
  if (!n) return ''
  if (n.nodeType === 3) return n.nodeValue
  if (n.nodeName === 'STYLE' || n.nodeName === 'SCRIPT') return ' '
  const a = n.atributos || {}
  if ('hidden' in a || /(^|\s)invisible(\s|$)/.test(a.class || '')) return ' '
  if (!n.childNodes?.length) return typeof n.textContent === 'string' ? n.textContent : ''
  return n.childNodes.map(textoVisible).join(' ')
}

const esperar = (ms) => new Promise((r) => setTimeout(r, ms))

/**
 * Dibuja `ruta` con el demo y guarda lo que se veía en cada dibujo de React,
 * hasta que la pantalla terminó y quedó quieta. Devuelve la lista de dibujos
 * ({ t: ms desde el montaje, texto }).
 */
async function dibujosDe(ruta, { local = {} } = {}) {
  const { App, HelmetProvider, ToastProvider, MemoryRouter } = await piezas()
  localStorage.clear()
  localStorage.setItem('rendi_demo_mode', String(Date.now()))
  window.dispatchEvent(new Event((await import('../utils/demo')).EVENTO_MODO_DEMO))
  for (const k of CLAVES_DE_LOS_TOURS) localStorage.setItem(k, '1')
  for (const [k, v] of Object.entries(local)) localStorage.setItem(k, v)

  const dibujos = []
  let contenedor = null
  const t0 = performance.now()
  const alDibujar = () => {
    if (contenedor) dibujos.push({ t: performance.now() - t0, texto: textoVisible(contenedor).replace(/\s+/g, ' ') })
  }
  const el = () => h(Profiler, { id: 'app', onRender: alDibujar },
    h(HelmetProvider, null, h(ToastProvider, null, h(MemoryRouter, { initialEntries: [ruta] }, h(App)))))
  const m = await montar(el())
  contenedor = m.contenedor
  let antes = null, quietas = 0
  for (let i = 0; i < 120 && (i < 10 || quietas < 6); i++) {
    await esperar(60)
    await m.redibujar(el())
    const t = textoVisible(m.contenedor)
    quietas = (t === antes && !cargando(m.contenedor)) ? quietas + 1 : 0
    antes = t
  }
  await m.desmontar()
  return dibujos
}

let modulos
async function piezas() {
  if (!modulos) {
    modulos = {
      App: (await import('../App')).default,
      HelmetProvider: (await import('react-helmet-async')).HelmetProvider,
      ToastProvider: (await import('../components/Toast')).ToastProvider,
      MemoryRouter: (await import('react-router-dom')).MemoryRouter,
    }
  }
  return modulos
}

const LISTA = 'Tu setup en Rendi'

// Corre `fn` anotando cada vez que SUENA el tope de useEsperaDeLaLista (no
// cuando se arma: en la compu se arma y se cancela en el mismo instante).
// NO se mide con reloj: con la Mac cargada (otras sesiones corriendo su suite)
// el primer dibujo llegó a los 3,6 s y una cota de tiempo daba rojo sin que
// nada esperara el tope.
async function anotandoElTope(fn) {
  const sono = []
  const setTimeoutDeVerdad = globalThis.setTimeout
  const espia = vi.spyOn(globalThis, 'setTimeout').mockImplementation((cb, ms, ...resto) => (
    ms === TOPE_ESPERA_LISTA_MS && String(cb).includes('setVencida')
      ? setTimeoutDeVerdad(() => { sono.push(ms); cb() }, ms, ...resto)
      : setTimeoutDeVerdad(cb, ms, ...resto)
  ))
  try { return { resultado: await fn(), sono } } finally { espia.mockRestore() }
}

afterEach(() => { control.colgado = null })

describe('celular (375 px)', () => {
  beforeAll(async () => { await prepararApp({ ancho: 375 }) }, 60000)

  it('inicio: la lista de primeros pasos ya está en el primer dibujo con «Tu cartera», y no aparece después', async () => {
    const dibujos = await dibujosDe('/')
    const conContenido = dibujos.filter((d) => d.texto.includes('Tu cartera'))
    expect(conContenido.length, 'el inicio nunca mostró «Tu cartera»').toBeGreaterThan(0)
    // La cuenta del demo tiene pasos sin hacer: la lista se muestra.
    const sinLista = conContenido.filter((d) => !d.texto.includes(LISTA))
    expect(sinLista.map((d) => `${Math.round(d.t)} ms`), '«Tu cartera» a la vista sin la lista arriba: la lista va a aparecer después y empujar todo').toEqual([])
  }, 60000)

  it('inicio con la lista cerrada: se muestra sin esperar el tope', async () => {
    // La lista cerrada se sabe de entrada: el inicio aparece apenas tiene sus
    // datos (quien pagó y la cerró no espera nada). Si hubiera tenido que
    // esperar, el tope habría sonado.
    const { resultado: dibujos, sono } = await anotandoElTope(() => dibujosDe('/', { local: { rendi_checklist_dismissed: '1' } }))
    const primero = dibujos.find((d) => d.texto.includes('Tu cartera'))
    expect(primero, 'el inicio nunca mostró «Tu cartera»').toBeTruthy()
    expect(primero.texto).not.toContain(LISTA)
    expect(sono, 'con la lista cerrada, el inicio esperó el tope en vez de mostrarse').toEqual([])
  }, 60000)

  it('inicio con el servidor de la lista trabado: se muestra igual al vencer el tope', async () => {
    control.colgado = '/primeros-pasos'
    const { resultado: dibujos, sono } = await anotandoElTope(() => dibujosDe('/'))
    const primero = dibujos.find((d) => d.texto.includes('Tu cartera'))
    expect(primero, 'una lista trabada dejó el inicio en el esqueleto para siempre').toBeTruthy()
    // Se mostró PORQUE sonó el tope (y una sola vez). Esto también prueba que
    // el espía ve sonar el tope: sin él, el «no sonó» de arriba no diría nada.
    expect(sono).toHaveLength(1)
    expect(primero.texto).not.toContain(LISTA)
  }, 60000)

  it('Dashboard: el cartel de la IA y el renglón de los precios están desde el primer dibujo con «Valor actual»', async () => {
    const dibujos = await dibujosDe('/dashboard')
    const conContenido = dibujos.filter((d) => d.texto.includes('Valor actual'))
    expect(conContenido.length, 'el Dashboard nunca mostró «Valor actual»').toBeGreaterThan(0)
    // Recién entrado (sin la marca de «ya conoció la IA»), el cartel va.
    expect(conContenido.filter((d) => !d.texto.includes('Nuevo · IA contextual')).map((d) => `${Math.round(d.t)} ms`),
      '«Valor actual» a la vista sin el cartel de la IA: el cartel aparece después y lo baja').toEqual([])
    // Mientras viajan los precios dice «Buscando precios…»; después, «Precios de hace…».
    expect(conContenido.filter((d) => !/Buscando precios…|Precios de hace/.test(d.texto)).map((d) => `${Math.round(d.t)} ms`),
      '«Valor actual» a la vista sin el renglón de los precios: el renglón aparece después y baja la pantalla').toEqual([])
    // Y el «Buscando…» de verdad se vio (si no, la prueba no miró el momento que importa).
    expect(conContenido.some((d) => d.texto.includes('Buscando precios…'))).toBe(true)
  }, 60000)
})

describe('compu (1280 px)', () => {
  beforeAll(async () => { await prepararApp({ ancho: 1280 }) }, 60000)

  it('inicio: las secciones del mercado no se ven antes que la lista de primeros pasos', async () => {
    const dibujos = await dibujosDe('/')
    const conContenido = dibujos.filter((d) => d.texto.includes('Movers del día'))
    expect(conContenido.length, 'el inicio nunca mostró los movers').toBeGreaterThan(0)
    expect(conContenido.filter((d) => !d.texto.includes(LISTA)).map((d) => `${Math.round(d.t)} ms`),
      'secciones a la vista sin la lista arriba: la lista va a aparecer después y empujarlas').toEqual([])
  }, 60000)
})
