// D1 (auditoría D, 29/10): la lista «Indicadores» no puede quedarse con los
// clicks del gráfico. Montada de verdad en la lectura técnica
// (testing/navegadorMinimo.js), con /api/tecnico simulado en la frontera
// (utils/api), como BarraGrafico.test.js. Lo que se prueba:
//   · con una herramienta de dibujo o de medir prendida, la lista abierta se
//     pliega sola (el gráfico queda libre para tocar) y al terminar vuelve;
//   · plegarla así no se guarda como elección de la persona;
//   · lo que toma los clicks es SÓLO lo que se ve (el botón y la lista), no la
//     caja que los envuelve: el 29/10 esa caja ocupaba todo el ancho de arriba
//     del gráfico, invisible, y ahí no se podía dibujar, medir ni ver el globo.
// (Lo que sigue es el arranque de BarraGrafico.test.js:)
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, clic, medidas, enActo } from '../../testing/navegadorMinimo'

const puntos = Array.from({ length: 300 }, (_, i) => {
  const d = new Date(Date.UTC(2025, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = i < 180 ? 100 + i * 0.4 : 172 - (i - 180) * 0.25
  return {
    d, o: c, h: c * 1.01, l: c * 0.99, c, s50: c * 0.98, s200: c * 0.95, rsi: 50 + 10 * Math.sin(i / 9),
    v: 1000 + i, adx: 15 + (i % 20), squeeze: Math.sin(i / 7), squeeze_color: Math.sin(i / 7) > 0 ? 'verde_fuerte' : 'rojo_fuerte',
  }
})
const FIB = {
  disponible: true, n_pivote: 3, dir: 'suba',
  desde: { fecha: puntos[100].d, precio: 140 }, hasta: { fecha: puntos[180].d, precio: 172 },
  ruptura: { fecha: puntos[200].d, cierre: 167, nivel: 168, nivel_fecha: puntos[170].d },
  niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 172 - n * 32 })),
  retroceso_hoy: 0.45, retroceso_maximo: { valor: 0.46, fecha: puntos[299].d }, entre: [0.382, 0.5],
}
const onda = (o, i, precio, tipo) => ({ onda: o, fecha: puntos[i].d, precio, tipo })
const ELL = {
  disponible: true, n_pivote: 3, alternativo: null,
  principal: {
    tipo: 'impulso', dir: 'suba', ahora: 'onda_5', confianza: 'media',
    ondas: [onda('0', 120, 148, 'pozo'), onda('1', 140, 156, 'pico'), onda('2', 150, 152, 'pozo'),
      onda('3', 170, 168, 'pico'), onda('4', 175, 164, 'pozo')],
    invalida: { precio: 156, lado: 'debajo', por: 'final_1' },
    pautas: [{ id: 'onda2', valor: 0.5, cumple: true }],
  },
}
const DATOS = {
  disponible: true, moneda: 'usd', ticker: 'ZZBH', convertida: null, puntos, fibonacci: FIB, elliott: ELL,
  lectura: { ruedas: 300, fecha: puntos[299].d, precio: puntos[299].c, rsi: 50 },
}
const EVENTOS = {
  eventos: [{ tipo: 'balance', fecha: puntos[250].d, momento: 'despues_del_cierre',
    reaccion: { desde: puntos[250].d, hasta: puntos[251].d, pct: -4.2, cuando: 'al_otro_dia' } }],
}

vi.mock('../../utils/api', () => ({
  // La copia de los dibujos es de la persona y la cuenta (utils/duenoDeLaPestana).
  getClientContext: () => null,
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
  api: { get: vi.fn((ruta) => Promise.resolve(ruta.includes('/eventos') ? EVENTOS : DATOS)) },
}))

let LecturaTecnica, almacenReal
beforeAll(async () => {
  instalarNavegadorMinimo()
  almacenReal = globalThis.localStorage
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  vi.stubGlobal('localStorage', almacenReal)
  localStorage.clear()
})

// Tenés el activo: una compra adentro del gráfico y un resultado (tu precio).
const props = { asset: 'ZZBH', pnlPctUsd: 0.1, lotes: [{ entry_date: puntos[260].d, quantity: 2 }] }
const el = () => h(LecturaTecnica, props)
async function dibujar() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
}
// Fibonacci y Elliott automáticos viven en el menú de su botón de la barra.
const MENU = { fib: 'menu-fibonacci', ell: 'menu-elliott' }
async function tocar(id) {
  if (MENU[id]) {
    await clic(montado.contenedor, boton(MENU[id]))
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
  }
  await clic(montado.contenedor, boton(id))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
}

function nodos(pred) {
  const out = []
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (pred(n)) out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}
const attr = (n, k) => n.getAttribute?.(k)
const boton = (id) => nodos(n => n.nodeName === 'BUTTON' && attr(n, 'data-capa') === id)[0] || null
// Prendido o apagado: el ojito de la lista (aria-pressed) o, en un menú, la
// opción tildada (aria-checked: se abre, se lee y se cierra).
async function prendido(id) {
  if (!MENU[id]) return attr(boton(id), 'aria-pressed')
  await clic(montado.contenedor, boton(MENU[id]))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
  const v = attr(boton(id), 'aria-checked')
  await clic(montado.contenedor, boton(MENU[id]))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
  return v
}

const grupo = () => nodos(n => attr(n, 'role') === 'group' && attr(n, 'aria-label') === 'Indicadores')[0]
// El primero de adentro de `raiz` con esa etiqueta (o null).
function adentro(raiz, etiqueta) {
  const pila = [...(raiz.childNodes || [])]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === etiqueta) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
const abierta = () => attr(adentro(grupo(), 'BUTTON'), 'aria-expanded')
const clases = (n) => (attr(n, 'class') || '').split(/\s+/)

describe('D1 · la lista «Indicadores» no tapa el gráfico', () => {
  for (const id of ['horizontal', 'tendencia', 'medir']) {
    it(`«${id}» prendida: la lista se pliega sola y al terminar vuelve como estaba`, async () => {
      await dibujar()
      expect(abierta()).toBe('true')            // gráfico ancho: abierta de entrada
      await tocar(id)
      expect(abierta()).toBe('false')
      expect(adentro(grupo(), 'UL')).toBeNull()
      await tocar(id)                           // apagar la herramienta
      expect(abierta()).toBe('true')
      expect(localStorage.getItem('rendi_grafico_leyenda')).toBeNull()
    })
  }

  it('plegada por la herramienta, se puede abrir igual a mano (sin guardarlo)', async () => {
    await dibujar()
    await tocar('horizontal')
    await clic(montado.contenedor, adentro(grupo(), 'BUTTON'))
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(abierta()).toBe('true')
    expect(localStorage.getItem('rendi_grafico_leyenda')).toBeNull()
  })

  it('sólo toma clicks lo que se ve: el botón y la lista, no la caja que los envuelve', async () => {
    await dibujar()
    const g = grupo()
    // Ni la caja de la lista ni la capa que la pone sobre el gráfico devuelven
    // los clicks a todo lo que tienen adentro.
    expect(clases(g)).toContain('pointer-events-none')
    expect(clases(g.parentNode)).toContain('pointer-events-none')
    expect(clases(g.parentNode).some(c => c.includes('pointer-events-auto'))).toBe(false)
    expect(clases(adentro(g, 'BUTTON'))).toContain('pointer-events-auto')
    expect(clases(adentro(g, 'UL'))).toContain('pointer-events-auto')
  })
})
