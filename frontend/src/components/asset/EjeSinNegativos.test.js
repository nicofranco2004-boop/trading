// Un precio nunca se rotula negativo (23/11/2026, capturas de la cuenta de
// ejemplo): en Análisis técnico → Gráfico, período «Todo», escala de siempre,
// el eje llegaba abajo de cero — bitcoin «−20.000», Galicia «−2».
//
// Por qué: para dejarle lugar al volumen abajo (y un poco de aire), el gráfico
// corre el borde de abajo del rango de precios (escalaPrecio.rangoConAire, con
// `abajo`). Con «Todo», lo más bajo que se ve está cerca de cero, así que esa
// franja vacía queda «en precios negativos», y los rótulos del eje la
// numeraban. La mira del mouse también: pasando por el volumen decía «−15.000».
// El pincel y el toque ya lo cuidaban cada uno por su lado; ahora es una regla
// (escalaPrecio.precioALaAltura y ejesGrafico.marcasDePrecio).
//
// Montado de verdad (testing/navegadorMinimo.js), con /api/tecnico simulado en
// la frontera, como EscalaLogGrafico.test.js. La imagen de «Compartir» usa el
// mismo rango y los mismos rótulos: se prueba también.
import { describe, it, expect, vi, beforeAll, afterAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto, enActo, medidas, clic } from '../../testing/navegadorMinimo'
import { pasarATodo } from '../../testing/menuGrafico'

// Como bitcoin con «Todo»: de US$ 200 a 126.000, con volumen todos los días.
const puntos = Array.from({ length: 700 }, (_, i) => {
  const d = new Date(Date.UTC(2020, 0, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = 200 * Math.pow(630, i / 699)
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, v: 1000 + i, s50: null, s200: null, rsi: 50 }
})
const DATOS = {
  disponible: true, moneda: 'usd', ticker: 'ZZBT', convertida: null, puntos, fibonacci: undefined,
  lectura: { ruedas: 700, fecha: puntos[699].d, precio: puntos[699].c, rsi: 50 },
}

vi.mock('../../utils/api', () => ({
  getClientContext: () => null,
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
  api: {
    get: vi.fn((ruta) => Promise.resolve(ruta.includes('/dibujos') ? { dibujos: [] }
      : ruta.startsWith('/alerts') ? { items: [] } : ruta.includes('/eventos') ? { eventos: [] } : DATOS)),
    post: vi.fn(() => Promise.resolve({ ok: true })),
    patch: vi.fn(() => Promise.resolve({ ok: true })),
    put: vi.fn(() => Promise.resolve({ ok: true })),
  },
}))
vi.mock('../../utils/track', () => ({ track: vi.fn() }))
const pedidas = []
vi.mock('../../utils/shareCard', async (original) => ({
  ...(await original()),
  shareCardToDataURL: vi.fn(async (spec) => { pedidas.push(spec); return 'data:image/png;base64,AAAA' }),
}))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  // 600 px, el alto del gráfico en una compu: los rótulos van de 20.000 en
  // 20.000 y, sin el arreglo, el de abajo era «−20.000» (con 250 px van de
  // 50.000 en 50.000 y el primero cae justo en cero: no se vería).
  medidas(() => ({ left: 0, top: 0, width: 1000, height: 600, right: 1000, bottom: 600 }))
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { medidas(null); vi.unstubAllGlobals() })

let montado
beforeEach(() => { localStorage.setItem('rendi_user', JSON.stringify({ name: 'Ana', email: 'ana@prueba.test' })) })
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()
  pedidas.length = 0
})

const el = () => h(MemoryRouter, null, h(LecturaTecnica, { asset: 'ZZBT' }))
async function redibujar() { for (let i = 0; i < 2; i++) await montado.redibujar(el()) }
async function dibujarConTodo() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  await pasarATodo(montado.contenedor)
  await redibujar()
}

function todos(nodo, ok) {
  const out = [], pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (ok(n)) out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}
const clase = (n) => n.getAttribute?.('class') || ''
const boton = (id) => todos(montado.contenedor, n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === id)[0]
const grafico = () => todos(montado.contenedor, n => n.getAttribute?.('role') === 'img' && (n.getAttribute('aria-label') || '').startsWith('Precio con su promedio'))[0]
// Los rótulos de la columna de precios, como texto (con su signo si lo tuvieran).
const rotulos = () => todos(montado.contenedor, n => n.nodeName === 'SPAN' && clase(n).includes('left-1.5') && clase(n).includes('text-[11px]'))
  .map(n => texto(n).trim())
// El precio bajo el mouse (en la columna; la fecha de abajo también es «mira»).
const mira = () => todos(montado.contenedor, n => n.getAttribute?.('data-mira') != null && clase(n).includes('-translate-y-1/2'))
  .map(n => texto(n).trim())
const NEGATIVO = /^[-−]/

async function moverElMouse(x, y) {
  await enActo(async () => {
    const ev = { type: 'mousemove', target: grafico(), bubbles: true, cancelable: true, button: 0,
      preventDefault() {}, stopPropagation() {}, clientX: x, clientY: y }
    for (const fn of montado.contenedor.escuchas.mousemove || []) fn(ev)
  })
  await redibujar()
}

describe('«Todo» en la escala de siempre: ningún precio bajo cero', () => {
  it('la franja del volumen existe y queda bajo cero (si no, la prueba no prueba nada)', async () => {
    await dibujarConTodo()
    expect(boton('escala-log').getAttribute('aria-pressed')).toBe('false')
    // Abajo de todo, la mira no da precio: es la franja del volumen.
    await moverElMouse(500, 599)
    expect(mira()).toEqual([])
    // A media altura sí: un precio positivo, con la misma columna.
    await moverElMouse(500, 250)
    expect(mira()).toHaveLength(1)
    expect(mira()[0]).not.toMatch(NEGATIVO)
  })

  it('los rótulos del eje: ninguno negativo, y el cero sí', async () => {
    await dibujarConTodo()
    const r = rotulos()
    expect(r.length).toBeGreaterThanOrEqual(3)
    expect(r.filter(t => NEGATIVO.test(t))).toEqual([])
    expect(r).toContain('0')
  })

  it('la imagen de «Compartir»: tampoco', async () => {
    await dibujarConTodo()
    await clic(montado.contenedor, boton('compartir'))
    for (let i = 0; i < 3; i++) await enActo(async () => {})
    const spec = pedidas.at(-1)
    expect(spec?.grafico?.eje?.length).toBeGreaterThanOrEqual(3)
    expect(spec.grafico.eje.map(t => t.texto).filter(t => NEGATIVO.test(t))).toEqual([])
  })
})
