// «Compartir» del gráfico técnico, montado de verdad (testing/navegadorMinimo.js):
// el botón en el encabezado del gráfico, la ventana de compartir y la imagen
// que se arma con lo que se está mirando. La imagen se intercepta en la puerta
// del canvas (shareCardToDataURL): lo que se mira es el spec que le llega, el
// mismo que se pinta. Las cuentas de la imagen están en utils/imagenGrafico.test.js.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { createElement as h } from 'react'
import { CAPAS_TODAS } from './BarraGrafico'
import { instalarNavegadorMinimo, montar, texto, clic, enActo } from '../../testing/navegadorMinimo'
import { elegirEnLaVista } from '../../testing/menuGrafico'

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
  getClientContext: () => null,   // mirando tu propia cuenta (no la de un cliente)
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
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
  // Ana logueada en su cuenta: los dibujos del navegador son a su nombre (utils/dibujos.js).
  localStorage.setItem('rendi_user', JSON.stringify({ email: 'ana@prueba.test' }))
  // Todo prendido, también tu precio y tus compras: lo que NO tiene que viajar.
  localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS))
  localStorage.setItem('rendi_dibujos:ana@prueba.test|propia:AAPL:usd', JSON.stringify({ pendiente: false, dibujos: MIS_DIBUJOS }))
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
  it('un CEDEAR estimado en pesos: la imagen también dice que es un estimado (Nico, 06/11)', async () => {
    // La ficha le pasa la escala a la imagen: sin ella, la imagen que se sube a
    // redes diría «pasado a pesos con el MEP» sobre un precio estimado, y ninguna
    // prueba lo veía (auditoría 06/11, pruebas: hallazgo 4).
    respuestas = { '/tecnico/AAPL?moneda=usd': USD,
      '/tecnico/AAPL?moneda=ars': { ...USD, moneda: 'ars', ticker: 'AAPL', convertida: 'ccl', escala: 20 } }
    await dibujar({ asset: 'AAPL', symbolMiniChart: 'AAPL' })
    await elegirEnLaVista(montado.contenedor, 'Pesos')
    for (let i = 0; i < 4; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL' }))
    const spec = await compartir()
    expect(spec.pie.join(' ')).toContain('Precio estimado del CEDEAR')
    expect(spec.pie.join(' ')).toContain('con el dólar contado con liqui (CCL) de cada día')
    expect(spec.pie.join(' ')).not.toContain('está pasado a pesos con el MEP de ese día')
  })

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
    // Sin tu precio en el gráfico (con él, ver la prueba de abajo).
    await dibujar({ asset: 'AAPL', symbolMiniChart: 'AAPL' })
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

  it('no lleva tus notas ni tu tesis: la imagen con notas es la misma que sin ellas (Nico, 30/10)', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await dibujar({ asset: 'AAPL', symbolMiniChart: 'AAPL' })
    const sinNotas = await compartir()
    await montado.desmontar(); montado = null
    for (const n of [...document.body.childNodes]) document.body.removeChild(n)
    const NOTAS = [
      { id: 'n1', tipo: 'nota', a: { d: dia(220), mas: 0, precio: 246 }, texto: 'compré acá por el balance', color: 'violeta' },
      { id: 'n2', tipo: 'nota', a: { d: dia(299), mas: 3, precio: 255 }, texto: 'vendo si pasa 300' },
    ]
    localStorage.setItem('rendi_dibujos:ana@prueba.test|propia:AAPL:usd', JSON.stringify({ pendiente: false, dibujos: [...MIS_DIBUJOS, ...NOTAS] }))
    const TESIS = [{ id: 5, asset: 'AAPL', texto: 'el recambio de iPhone', escrita_el: dia(150) }]
    await dibujar({ asset: 'AAPL', symbolMiniChart: 'AAPL', tesis: TESIS })
    // En la pantalla están…
    expect(todos(montado.contenedor, n => n.getAttribute?.('data-banderita') != null).map(n => n.getAttribute('data-banderita')).sort())
      .toEqual(['n1', 'n2', 'tesis:5'])
    const conNotas = await compartir()
    // …en la imagen no: ni el texto, ni una marca, ni una escala distinta.
    const json = JSON.stringify(conNotas)
    for (const t of ['compré acá', 'vendo si pasa', 'recambio', 'nota', 'tesis']) expect(json).not.toContain(t)
    expect(json).toBe(JSON.stringify(sinNotas))
  })

  it('tu precio no estira la escala de la imagen (si no, la franja vacía delataría a cuánto compraste)', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    // Ganás 40 %: tu precio (US$ 185,57) queda cerca de lo que se ve y la
    // pantalla estira su escala hasta él.
    await dibujar()
    const conTuPrecio = await compartir()
    await montado.desmontar(); montado = null
    for (const n of [...document.body.childNodes]) document.body.removeChild(n)
    await dibujar({ asset: 'AAPL', symbolMiniChart: 'AAPL' })
    const sinCartera = await compartir()
    expect(conTuPrecio.grafico.etiquetas.find(e => e.principal).y).toBeCloseTo(sinCartera.grafico.etiquetas.find(e => e.principal).y, 6)
    expect(conTuPrecio.grafico.eje.map(t => t.texto)).toEqual(sinCartera.grafico.eje.map(t => t.texto))
  })

  it('«Desde que lo tenés» diría el día de tu compra y casi lo que ganaste: la imagen sale con «Todo», y la pantalla pasa a «Todo»', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await dibujar()
    const { elegirEnLaVista, periodoElegido } = await import('../../testing/menuGrafico')
    await elegirEnLaVista(montado.contenedor, 'Desde que lo tenés')
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, PROPS))
    const spec = await compartir()
    expect(spec.subtitulo).toContain('del 01/01/25 al 27/10/25')       // toda la historia, no desde tu compra (08/09/25)
    expect(JSON.stringify(spec)).not.toContain('08/09/25')
    expect(periodoElegido(montado.contenedor)).toBe('Todo')            // lo que se ve es lo que se manda
  })

  it('lo que se ve: acercado con la ruedita, la imagen dice el período nuevo', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await dibujar()
    const todo = await compartir()
    expect(todo.subtitulo).toContain('del 01/01/25 al 27/10/25')
    await clic(document.body, buscarEn(document.body, n => n.getAttribute?.('aria-label') === 'Cerrar'))
    await enActo(async () => {})
    // La ruedita hacia arriba acerca (con el último día quieto).
    const conRueda = buscarEn(montado.contenedor, n => n.getAttribute?.('role') === 'img' && n.escuchas?.wheel?.length)
    for (let k = 0; k < 4; k++) {
      await enActo(async () => { for (const fn of conRueda.escuchas.wheel) fn({ deltaY: -100, deltaMode: 0, clientX: 0, preventDefault() {} }) })
    }
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, PROPS))
    const cerca = await compartir()
    expect(cerca.subtitulo).not.toContain('del 01/01/25')
    expect(cerca.subtitulo).toContain('al 27/10/25')
    // De entrada son velas (Nico, 02/11): la imagen lleva las de lo que se ve.
    expect(cerca.grafico.velas.length).toBeGreaterThan(0)
    expect(cerca.grafico.velas.length).toBeLessThan(todo.grafico.velas.length)
  })

  it('en el celular: «Compartir» de la ventana abre el compartir del sistema con la imagen de la vista previa y su nombre', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    const compartidos = []
    const original = globalThis.navigator
    vi.stubGlobal('navigator', { ...globalThis.navigator, canShare: () => true, share: vi.fn(async (d) => { compartidos.push(d) }) })
    const { shareCardToBlob } = await import('../../utils/shareCard')
    try {
      await dibujar()
      await compartir()
      const enLaVentana = buscarEn(document.body, n => n.nodeName === 'BUTTON' && texto(n).trim() === 'Compartir')
      expect(enLaVentana).toBeTruthy()
      const dibujadas = pedidas.length
      await clic(document.body, enLaVentana)
      for (let i = 0; i < 3; i++) await enActo(async () => {})
      expect(compartidos).toHaveLength(1)
      expect(compartidos[0].files[0].name).toMatch(/^aapl-grafico-\d{4}-\d{2}-\d{2}\.png$/)
      expect(compartidos[0].files[0].type).toBe('image/png')
      expect(compartidos[0].text).not.toMatch(/Tu precio|Ganás/)
      // No se volvió a dibujar: es la imagen que se vio en la vista previa.
      expect(pedidas.length).toBe(dibujadas)
      expect(vi.isMockFunction(shareCardToBlob) ? shareCardToBlob.mock.calls.length : 0).toBe(0)
    } finally {
      vi.stubGlobal('navigator', original)
    }
  })

  // Esc en pantalla completa (cierra sólo la ventana) se probó en un navegador
  // de verdad: acá `window` no tiene la fase de bajada (captura) antes que la de
  // subida, que es justo lo que decide el caso.

  it('sin gráfico (cargando, o un activo sin velas) no hay botón', async () => {
    respuestas = { '/tecnico/': { disponible: false }, '/prices/history': { points: [] } }
    await dibujar({ asset: 'AAPL', symbolMiniChart: 'AAPL' })
    expect(botonCompartir()).toBe(null)
  })
})
