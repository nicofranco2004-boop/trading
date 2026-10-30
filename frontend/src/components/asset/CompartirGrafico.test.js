// «Compartir» del gráfico técnico, montado de verdad (testing/navegadorMinimo.js):
// el botón en el encabezado del gráfico, la ventana de compartir y la imagen
// que se arma con lo que se está mirando. La imagen se intercepta en la puerta
// del canvas (shareCardToDataURL): lo que se mira es el spec que le llega, el
// mismo que se pinta. Las cuentas de la imagen están en utils/imagenGrafico.test.js.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { createElement as h } from 'react'
import { CAPAS_TODAS } from './BarraGrafico'
import { instalarNavegadorMinimo, montar, texto, clic, enActo } from '../../testing/navegadorMinimo'

const dia = (i) => new Date(Date.UTC(2025, 0, 1) + i * 86400000).toISOString().slice(0, 10)
const PUNTOS = Array.from({ length: 300 }, (_, i) => {
  const c = 200 + i * 0.2
  return { d: dia(i), o: c - 0.5, h: c + 1, l: c - 1, c, v: 1000, s50: c * 1.01, s200: c * 1.03, rsi: 45 }
})
const USD = {
  disponible: true, moneda: 'usd', ticker: 'AAPL', convertida: null, puntos: PUNTOS,
  lectura: { ruedas: 300, fecha: dia(299), precio: 259.8, media50: 250, dist_media50: 2, media200: 240, dist_media200: 8,
    pendiente_media200: 1, rsi: 45, dist_maximo_12m: -3, anio_completo: true },
}

let respuestas
vi.mock('../../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => {
      const clave = Object.keys(respuestas).find(k => ruta.startsWith(k))
      const r = clave ? respuestas[clave] : []
      return r instanceof Error ? Promise.reject(r) : Promise.resolve(r)
    }),
    put: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}))
vi.mock('../../utils/track', () => ({ track: vi.fn() }))
// La puerta del canvas: se anota cada imagen pedida (en node no hay canvas).
const pedidas = []
vi.mock('../../utils/shareCard', async (original) => ({
  ...(await original()),
  shareCardToDataURL: vi.fn(async (spec) => { pedidas.push(spec); return 'data:image/png;base64,AAAA' }),
}))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

const MIS_DIBUJOS = [
  { id: 'h1', tipo: 'horizontal', precio: 250, color: 'ambar' },
  { id: 't1', tipo: 'tendencia', a: { d: dia(200), mas: 0, precio: 240 }, b: { d: dia(290), mas: 0, precio: 258 }, color: 'rosa' },
]
let montado
beforeEach(() => {
  pedidas.length = 0
  // Todo prendido, también tu precio y tus compras: lo que NO tiene que viajar.
  localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS))
  localStorage.setItem('rendi_dibujos:AAPL:usd', JSON.stringify({ pendiente: false, dibujos: MIS_DIBUJOS }))
})
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()
  for (const n of [...document.body.childNodes]) document.body.removeChild(n)
})

// Con tu precio (ganás 40 %) y una compra tuya en lo que se ve.
const PROPS = { asset: 'AAPL', symbolMiniChart: 'AAPL', pnlPctUsd: 0.4, pnlPctLinea: 0.4,
  lotes: [{ entry_date: dia(250), quantity: 3, entry_price: 249.9 }] }
async function dibujar(props = PROPS) {
  const el = () => h(LecturaTecnica, props)
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
}
function buscarEn(raiz, pred) {
  const pila = [raiz]
  while (pila.length) {
    const n = pila.shift()
    if (pred(n)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
function todos(raiz, pred) {
  const out = [], pila = [raiz]
  while (pila.length) {
    const n = pila.shift()
    if (pred(n)) out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}
const botonCompartir = () => buscarEn(montado.contenedor, n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === 'compartir')
async function compartir(boton = botonCompartir()) {
  await clic(montado.contenedor, boton)
  for (let i = 0; i < 3; i++) await enActo(async () => {})
  return pedidas.at(-1)
}

describe('Compartir el gráfico técnico', () => {
  it('el botón: en la compu en el encabezado del gráfico, en el celular el ícono al lado de la ayuda; abre la ventana con la imagen', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await dibujar()
    const botones = todos(montado.contenedor, n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === 'compartir')
    expect(botones).toHaveLength(2)
    // El del encabezado: junto a «Pantalla completa», con su nombre; escondido en el celular.
    const arriba = botones.find(b => b.parentNode === buscarEn(montado.contenedor, n => n.getAttribute?.('data-capa') === 'pantalla').parentNode)
    expect(arriba).toBeTruthy()
    expect(texto(arriba)).toContain('Compartir')
    expect(arriba.getAttribute('class')).toContain('hidden sm:inline-flex')
    // El del celular: en el renglón de la ayuda (pegada a las fechas), de 44 px para el dedo.
    const abajo = botones.find(b => b !== arriba)
    expect(abajo.parentNode.childNodes.some(n => n.getAttribute?.('data-ayuda') === '')).toBe(true)
    expect(abajo.getAttribute('class')).toContain('sm:hidden')
    expect(abajo.getAttribute('class')).toContain('min-h-11 min-w-11')
    const spec = await compartir(abajo)
    expect(spec?.kind).toBe('grafico')
    expect(texto(document.body)).toContain('Tu tarjeta lista para redes')
    // Por encima de la pantalla completa del gráfico (z-70).
    expect(document.body.childNodes.some(n => (n.getAttribute?.('class') || '').includes('z-[80]'))).toBe(true)
  })

  it('la imagen lleva el activo, tus dibujos en su color y la MISMA escala que la pantalla', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await dibujar()
    const spec = await compartir()
    expect(spec.activo).toBe('AAPL')
    expect(spec.precio.texto).toBe('US$ 259,80')
    const colores = new Set(spec.grafico.trazos.map(t => t.color))
    expect(colores.has('rgb(var(--data-amber))')).toBe(true)   // la horizontal ámbar
    expect(colores.has('rgb(var(--cat-pink))')).toBe(true)     // la línea rosa
    // El último precio cae a la misma altura que su etiqueta en la pantalla.
    const enPantalla = buscarEn(montado.contenedor, n => n.getAttribute?.('data-ultimo') === '')
    const yPantalla = parseFloat(enPantalla.style.top)
    expect(spec.grafico.etiquetas.find(e => e.principal).y).toBeCloseTo(yPantalla, 6)
  })

  it('no lleva nada de tu cartera: ni tu precio, ni tus compras, ni lo que ganás', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await dibujar()
    const enPantalla = texto(montado.contenedor)
    expect(enPantalla).toContain('Tu precio')        // en la pantalla sí está…
    expect(enPantalla).toContain('Ganás 40,0%')
    const json = JSON.stringify(await compartir())
    expect(json).not.toContain('Tu precio')          // …en la imagen no
    expect(json).not.toContain('Ganás')
    expect(json).not.toContain('Compraste')
    expect(json).not.toContain('249,9')
    expect(json).not.toContain('Tus compras')
  })

  it('lo que se ve: con el período cambiado, la imagen dice el período nuevo', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await dibujar()
    const todo = await compartir()
    expect(todo.subtitulo).toContain(`del ${'01/01/25'}`)
    await clic(document.body, buscarEn(document.body, n => n.getAttribute?.('aria-label') === 'Cerrar'))
    await enActo(async () => {})
    // «Desde que lo tenés»: desde tu primera compra.
    const { elegirEnLaVista } = await import('../../testing/menuGrafico')
    await elegirEnLaVista(montado.contenedor, 'Desde que lo tenés')
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, PROPS))
    const tuyo = await compartir()
    expect(tuyo.subtitulo).not.toContain('del 01/01/25')
  })

  it('sin gráfico (cargando, o un activo sin velas) no hay botón', async () => {
    respuestas = { '/tecnico/': { disponible: false }, '/prices/history': { points: [] } }
    await dibujar({ asset: 'AAPL', symbolMiniChart: 'AAPL' })
    expect(botonCompartir()).toBe(null)
  })
})
