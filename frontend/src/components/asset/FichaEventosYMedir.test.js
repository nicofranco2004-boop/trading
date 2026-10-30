// La pieza 12 de la ficha, montada de verdad (testing/navegadorMinimo.js):
//   · medir entre dos puntos con el mouse y con el dedo, sin romper el
//     arrastre del gráfico (arrastrar o deslizar NO marca un punto);
//   · los balances («B») y dividendos («D») sobre el eje de fechas, con su
//     globo, y el botón de la leyenda que los prende y los apaga;
//   · el rango «Desde que lo tenés», que arranca en tu primera compra;
//   · «Cuánto se mueve este papel» con lo que manda el servidor y tu tenencia.
// Lo que manda el servidor tiene la forma de backend/movimiento.py (sus
// cuentas se prueban allá, contra una cuenta independiente).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { CAPAS_TODAS } from './BarraGrafico'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, enActo, medidas, clic, buscarBoton } from '../../testing/navegadorMinimo'
import { botonDeLaVista, elegirEnLaVista, opcionesDeLaVista, periodoElegido } from '../../testing/menuGrafico'
import { margenDerecho } from '../../utils/tecnico'

const puntos = Array.from({ length: 700 }, (_, i) => {
  const d = new Date(Date.UTC(2024, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = 100 + 20 * Math.sin(i / 40) + i * 0.05
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, s50: null, s200: null, rsi: 50 }
})
const MOVIMIENTO = {
  disponible: true, desde: '2024-09-01', hasta: puntos[699].d,   // 2 años: el servidor corta 730 días
  peor_caida: { pico: { fecha: puntos[50].d, precio: 122.5 }, piso: { fecha: puntos[170].d, precio: 82.1 },
    pct: -33, volvio: null, dias_para_volver: null, dias_corridos_para_volver: null },
  dia_normal: { desvio_pct: 1.6, dias: 699, dias_malos: 100, sp500_desvio_pct: 0.9, veces_el_sp500: 1.78 },
  desde_el_maximo: { pct: -5, maximo: 150, anio_completo: true },
}
const DATOS = {
  disponible: true, moneda: 'usd', ticker: 'ZZEV', convertida: null, puntos, fibonacci: undefined,
  lectura: { ruedas: 700, fecha: puntos[699].d, precio: puntos[699].c, rsi: 50 },
  movimiento: MOVIMIENTO,
}
const EVENTOS = {
  empresa: 'ZZEV',
  eventos: [
    { tipo: 'balance', fecha: puntos[600].d, momento: 'despues_del_cierre',
      reaccion: { desde: puntos[600].d, hasta: puntos[601].d, pct: -4.21, cuando: 'al_otro_dia' },
      eps_esperado: 1.5, eps_declarado: 1.65, sorpresa_pct: 10, moneda: 'usd' },
    { tipo: 'dividendo', fecha: puntos[610].d, monto: 0.26, moneda: 'usd',
      reaccion: { desde: puntos[609].d, hasta: puntos[610].d, pct: -0.4, cuando: 'ese_dia' } },
  ],
}

vi.mock('../../utils/api', () => ({
  getClientContext: () => null,   // mirando tu propia cuenta (no la de un cliente)
  api: { get: vi.fn((ruta) => Promise.resolve(ruta.includes('/eventos') ? EVENTOS : DATOS)) },
}))

let LecturaTecnica, diasRecientes, PX_POR_VELA
beforeAll(async () => {
  instalarNavegadorMinimo()
  medidas(() => ({ left: 0, top: 0, width: 1000, height: 250, right: 1000, bottom: 250 }))
  ;({ default: LecturaTecnica, diasRecientes, PX_POR_VELA } = await import('./LecturaTecnica'))
})
afterAll(() => { medidas(null); vi.unstubAllGlobals() })

let montado, props
// De fábrica el gráfico viene limpio (precio, promedio de 200 y volumen). Estas
// pruebas miran las demás capas: arrancan con todas prendidas, como quien las
// prende desde «Indicadores» (lo que se prende queda guardado así).
beforeEach(() => { try { localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS)) } catch { /* sin almacenamiento */ } })
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()   // lo que apaga una prueba no pasa a la siguiente
})
const el = () => h(LecturaTecnica, { asset: 'ZZEV', ...props })
async function dibujar(p = {}) {
  props = p
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
}
async function redibujar() { for (let i = 0; i < 2; i++) await montado.redibujar(el()) }

function porRol(nodo, rol, etiqueta) {
  const pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (n.getAttribute?.('role') === rol && (!etiqueta || n.getAttribute('aria-label')?.startsWith(etiqueta))) return n
    pila.push(...(n.childNodes || []))
  }
  return null
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
// Un evento del mouse o del dedo como lo recibe React: por la raíz.
async function evento(tipo, nodo, datos = {}) {
  let ev
  await enActo(async () => {
    ev = { type: tipo, target: nodo, bubbles: true, cancelable: true, button: 0, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true }, stopPropagation() {}, ...datos }
    for (const fn of montado.contenedor.escuchas[tipo] || []) fn(ev)
  })
  return ev
}
const grafico = () => porRol(montado.contenedor, 'img', 'Precio con su promedio')
async function clickEn(x, y = 100) {
  await evento('mousedown', grafico(), { clientX: x, clientY: y })
  await evento('mouseup', grafico(), { clientX: x, clientY: y })
  await redibujar()
}
async function toqueEn(x, hastaX = x) {
  const t = (cx) => ({ touches: [{ clientX: cx, clientY: 100 }], changedTouches: [{ clientX: cx, clientY: 100 }] })
  await evento('touchstart', grafico(), t(x))
  if (hastaX !== x) await evento('touchmove', grafico(), t(hastaX))
  const fin = await evento('touchend', grafico(), { touches: [], changedTouches: [{ clientX: hastaX, clientY: 100 }] })
  await redibujar()
  return fin
}
const fecha = (iso) => { const [y, m, d] = iso.split('-'); return `${d}/${m}/${y.slice(2)}` }
// Lo que se ve de entrada («Todo»): los 700 puntos (uno por día) más el aire vacío de
// la derecha (como TradingView): el ancho se reparte en LUGARES. El punto bajo
// x: round(x / 1000 × (lugares − 1)) dentro de lo que se ve.
const LUGARES = 700 + margenDerecho(700)
const bajo = (x) => Math.round((x / 1000) * (LUGARES - 1))
const pct = (a, b) => ((puntos[b].c / puntos[a].c - 1) * 100).toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

// Los precios que dice la medición, como números («US$ 1.234,56» → 1234.56).
const precios = (t) => [...t.matchAll(/US\$ ([\d.]+,\d+)/g)].map(m => Number(m[1].replace(/\./g, '').replace(',', '.')))
const status = () => texto(porRol(montado.contenedor, 'status') || { childNodes: [] })
const EMPEZAR = 'Tocá cualquier punto del gráfico para empezar a medir'

describe('medir entre dos puntos (como la regla de TradingView)', () => {
  it('con el mouse: el % entre los PRECIOS tocados, no los cierres, y los días de mercado', async () => {
    await dibujar()
    expect(texto(montado.contenedor)).not.toContain(EMPEZAR)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos'))
    await redibujar()
    expect(status()).toContain(EMPEZAR)

    await clickEn(100, 150)
    const a = bajo(100)
    expect(status()).toContain(`, el ${fecha(puntos[a].d)}. Ahora tocá el otro punto.`)
    const [pa] = precios(status())
    expect(Math.abs(pa - puntos[a].c)).toBeGreaterThan(0.5)      // la altura del click, no el cierre de ese día
    await clickEn(900, 40)                                        // más arriba en la pantalla: un precio más alto
    const b = bajo(900)
    const t = status()
    const [desde, hasta] = precios(t)
    expect(desde).toBe(pa)
    expect(hasta).toBeGreaterThan(desde)
    const pct = ((hasta / desde - 1) * 100).toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
    expect(t).toContain(`+${pct}% en ${b - a} días de mercado`)
    expect(t).toContain(`(el ${fecha(puntos[a].d)})`)
    expect(t).toContain(`(el ${fecha(puntos[b].d)})`)
    expect(t).not.toContain('de cierre a cierre')

    // Un tercer click empieza otra medición.
    await clickEn(500)
    expect(status()).toContain(`, el ${fecha(puntos[bajo(500)].d)}. Ahora tocá el otro punto.`)
  })

  it('el mismo día, dos alturas: mide en vertical', async () => {
    await dibujar()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos')); await redibujar()
    await clickEn(500, 200)
    await clickEn(500, 60)
    expect(status()).toMatch(/\+[\d,]+% en el mismo día/)
  })

  it('el aire de la derecha mide hacia adelante: días de mercado que todavía no pasaron', async () => {
    await dibujar()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos')); await redibujar()
    expect(bajo(995)).toBeGreaterThan(699)        // 995 px cae en el aire, después del último día (699)
    await clickEn(300)
    await clickEn(995, 30)
    const t = status()
    expect(t).toContain(`en ${bajo(995) - bajo(300)} días de mercado`)
    expect(t).toContain(`(dentro de ${bajo(995) - 699} días de mercado)`)
    expect(t).toContain('Lo que queda a la derecha de hoy es una cuenta: todavía no hay precios ahí.')
    // Y con el dedo, igual.
    await toqueEn(995)
    expect(status()).toContain(`dentro de ${bajo(995) - 699} días de mercado. Ahora tocá el otro punto.`)
  })

  it('con un punto puesto, el otro extremo sigue al mouse hasta el segundo click', async () => {
    await dibujar()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos')); await redibujar()
    await clickEn(200, 150)
    await evento('mousemove', grafico(), { clientX: 800, clientY: 50 }); await redibujar()
    const rotulo = todos(montado.contenedor, n => n.getAttribute?.('data-rotulo') === '6')
    expect(rotulo).toHaveLength(1)
    expect(texto(rotulo[0])).toContain(`en ${bajo(800) - bajo(200)} días de mercado`)
    expect(status()).toContain('Ahora tocá el otro punto.')      // todavía no se eligió
  })

  it('arrastrar el gráfico sigue moviéndolo y no marca un punto', async () => {
    await dibujar()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos'))
    await redibujar()
    // Con «Todo» arranca en el primer día: se arrastra hacia el futuro.
    await evento('mousedown', grafico(), { clientX: 600, clientY: 100 })
    await evento('mousemove', grafico(), { clientX: 300, clientY: 100 })
    await evento('mouseup', grafico(), { clientX: 300, clientY: 100 })
    await redibujar()
    expect(status()).toContain(EMPEZAR)
    // Se movió: ya no hay un rango elegido y aparece «Automático».
    expect(buscarBoton(montado.contenedor, 'Automático')).not.toBeNull()
  })

  it('con el dedo: un toque quieto marca; deslizar no', async () => {
    await dibujar()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos'))
    await redibujar()
    await toqueEn(200, 400)             // deslizó: es mirar el gráfico, no medir
    expect(status()).toContain(EMPEZAR)
    const fin = await toqueEn(200)
    expect(fin.defaultPrevented).toBe(true)   // sin el click de mouse que el navegador arma después
    await toqueEn(800)
    const a = bajo(200), b = bajo(800)
    expect(status()).toContain(`en ${b - a} días de mercado`)
  })

  it('apagar el modo borra la medición', async () => {
    await dibujar()
    const boton = () => buscarBoton(montado.contenedor, 'Medir entre dos puntos')
    await clic(montado.contenedor, boton()); await redibujar()
    await clickEn(100); await clickEn(900, 40)
    await clic(montado.contenedor, boton()); await redibujar()
    expect(texto(montado.contenedor)).not.toContain('días de mercado:')
    expect(todos(montado.contenedor, n => n.getAttribute?.('data-rotulo') === '6')).toHaveLength(0)
    expect(boton().getAttribute('aria-pressed')).toBe('false')
  })
})

describe('balances y dividendos en el gráfico', () => {
  const marcas = () => todos(montado.contenedor, n => n.nodeName === 'BUTTON'
    && /^(Balance|Dividendo)/.test(n.getAttribute?.('aria-label') || ''))

  it('una «B» y una «D» con su globo: lo declarado contra lo esperado y qué parte del precio fue el dividendo', async () => {
    // Acercado a los últimos 110 días (la primera compra), quedan separadas.
    await dibujar({ lotes: [{ entry_date: puntos[590].d, quantity: 1 }] })
    await elegirEnLaVista(montado.contenedor, 'Desde que lo tenés'); await redibujar()
    const ms = marcas()
    expect(ms.map(n => texto(n))).toEqual(['B', 'D'])
    // En el mismo lugar que la vela de ese día (el ancho se reparte en lugares,
    // con el aire de la derecha): no corridas.
    const lug = 110 + margenDerecho(110)
    const lugarDe = (i) => `${((i - 590) / (lug - 1)) * 100}%`
    expect(ms[0].style.left).toBe(lugarDe(600))
    expect(ms[1].style.left).toBe(lugarDe(610))
    expect(ms[0].getAttribute('aria-label')).toBe(
      `Balance del ${fecha(puntos[600].d)}. Declaró una ganancia de US$ 1,65 por acción; se esperaba US$ 1,50: 10% más de lo esperado. `
      + 'Lo presentó con el mercado ya cerrado. Al otro día el precio: −4,2%')
    // Con un toque, el globo del dividendo: qué parte del precio de ese día fue.
    await clic(montado.contenedor, ms[1]); await redibujar()
    const t = texto(montado.contenedor)
    const parte = ((0.26 / puntos[610].c) * 100).toLocaleString('es-AR', { maximumFractionDigits: 2 })
    expect(t).toContain(`Dividendo · día de corte ${fecha(puntos[610].d)}`)
    expect(t).toContain(`Pagó US$ 0,26 por acción: el ${parte}% de lo que valía la acción ese día.`)
    expect(t).toContain('Ese día el precio: −0,4%')

    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Balances y dividendos')); await redibujar()
    expect(marcas()).toEqual([])
  })

  it('con toda la historia a la vista, un balance y un dividendo cercanos van en UNA marca, en una sola fila', async () => {
    await dibujar()
    const ms = todos(montado.contenedor, n => n.nodeName === 'BUTTON' && /balances y dividendos/.test(n.getAttribute?.('aria-label') || ''))
    expect(ms.map(n => texto(n))).toEqual(['2'])
    const fila = todos(montado.contenedor, n => n.getAttribute?.('aria-label') === 'Balances y dividendos' && n.getAttribute?.('role') === 'group')[0]
    expect(fila.getAttribute('class')).toContain('h-4')                     // un renglón, no dos
  })

  it('los que no entran en lo que se ve no se dibujan', async () => {
    // «Desde que lo tenés», con la primera compra hace 91 días: el balance (hace 99) queda afuera y el dividendo (hace 89) adentro.
    await dibujar({ lotes: [{ entry_date: puntos[609].d, quantity: 1 }] })
    await elegirEnLaVista(montado.contenedor, 'Desde que lo tenés'); await redibujar()
    expect(marcas().map(n => texto(n))).toEqual(['D'])
  })
})

describe('en el celular (un gráfico angosto, Nico 29/10)', () => {
  // El celular: el gráfico mide 300 px (lo mide el propio gráfico, no la pantalla: R6).
  const angosto = () => { globalThis.ResizeObserver = class { constructor(cb) { this.cb = cb } observe() { this.cb([{ contentRect: { width: 300, height: 250 } }]) } disconnect() {} } }
  afterEach(() => { delete globalThis.ResizeObserver })
  const marcas = () => todos(montado.contenedor, n => n.nodeName === 'BUTTON'
    && /^(Balance|Dividendo|\d+ (dividendos|balances))/.test(n.getAttribute?.('aria-label') || ''))
  // El primer día que se ve: midiendo desde el borde izquierdo.
  async function primerDia() {
    const medir = () => buscarBoton(montado.contenedor, 'Medir entre dos puntos')
    await clic(montado.contenedor, medir()); await redibujar()
    await clickEn(0)
    const t = status()
    await clic(montado.contenedor, medir()); await redibujar()
    return t
  }

  it('abre con lo reciente: las velas que entran a 4 px cada una, terminando hoy; «Todo» muestra la historia entera', async () => {
    angosto()
    await dibujar()
    expect(periodoElegido(montado.contenedor)).toBe('Reciente')
    // Los días que se ven, con su aire a la derecha, entran a PX_POR_VELA (4 px) cada uno.
    const n = diasRecientes(300, puntos.length)
    expect(300 / (n + margenDerecho(n))).toBeGreaterThanOrEqual(PX_POR_VELA)
    expect(300 / (n + 1 + margenDerecho(n + 1))).toBeLessThan(PX_POR_VELA)   // y no entra ni uno más
    expect(n).toBe(71)   // ~3 meses de mercado
    expect(await primerDia()).toContain(`, el ${fecha(puntos[700 - n].d)}. Ahora tocá el otro punto.`)
    // Termina hoy: el último día se ve, y a la derecha está el aire de siempre.
    expect(texto(montado.contenedor)).not.toContain('Automático')
    // El menú ofrece lo reciente, con cuánto es, y «Todo».
    const ops = await opcionesDeLaVista(montado.contenedor)
    expect(ops).toContain('Lo reciente3 meses')
    expect(ops).toContain('Todo')

    await elegirEnLaVista(montado.contenedor, 'Todo'); await redibujar()
    expect(periodoElegido(montado.contenedor)).toBe('Todo')
    expect(await primerDia()).toContain(`, el ${fecha(puntos[0].d)}. Ahora tocá el otro punto.`)
  })

  it('la temporalidad no cambia sola: con velas siguen siendo diarias («1D»), y en semanales entran más días', async () => {
    angosto()
    localStorage.setItem('rendi_grafico_tipo', 'velas')
    await dibujar()
    expect(texto(buscarBoton(montado.contenedor, 'Cada vela es'))).toContain('1D')
    expect(await primerDia()).toContain(`, el ${fecha(puntos[700 - 71].d)}.`)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Cada vela es'))
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Semanales')); await redibujar()
    expect(texto(buscarBoton(montado.contenedor, 'Cada vela es'))).toContain('1S')
    // Cada vela semanal también a ≥ 4 px: 5 veces más días a la vista.
    expect(diasRecientes(300, puntos.length, 5)).toBeGreaterThan(5 * 60)
    expect(periodoElegido(montado.contenedor)).toBe('Reciente')
  })

  it('en la compu (un gráfico ancho) abre con «Todo», como siempre, y no ofrece «Lo reciente»', async () => {
    await dibujar()   // 1000 px
    expect(periodoElegido(montado.contenedor)).toBe('Todo')
    expect(await primerDia()).toContain(`, el ${fecha(puntos[0].d)}.`)
    expect((await opcionesDeLaVista(montado.contenedor)).some(o => o.startsWith('Lo reciente'))).toBe(false)
  })

  it('con la historia entera sólo se ven los balances; los dividendos aparecen al acercar, cuando entran separados', async () => {
    const antes = { ...EVENTOS }
    EVENTOS.eventos = [
      EVENTOS.eventos[0],
      ...[640, 650, 660].map(i => ({ tipo: 'dividendo', fecha: puntos[i].d, monto: 8.3, moneda: 'ars',
        reaccion: { desde: puntos[i - 1].d, hasta: puntos[i].d, pct: 1, cuando: 'ese_dia' } })),
    ]
    angosto()
    try {
      await dibujar()
      await elegirEnLaVista(montado.contenedor, 'Todo'); await redibujar()
      // Con «Todo», 10 días de mercado son 4 px: los dividendos se pisarían. Antes era UNA marca «4»
      // con todo mezclado; ahora, el balance solo y un aviso de que al acercar están los dividendos.
      expect(marcas().map(n => texto(n))).toEqual(['B'])
      expect(marcas()[0].getAttribute('aria-label')).toMatch(/^Balance del /)
      expect(texto(montado.contenedor)).toContain('Acercá el gráfico para ver los dividendos.')
      // Lo reciente (71 días): 10 días de mercado son 40 px, entran separados.
      await elegirEnLaVista(montado.contenedor, 'Lo reciente'); await redibujar()
      expect(marcas().map(n => texto(n))).toEqual(['D', 'D', 'D'])
      expect(texto(montado.contenedor)).not.toContain('Acercá el gráfico para ver los dividendos.')
    } finally {
      EVENTOS.eventos = antes.eventos
    }
  })

  it('dos dividendos tan pegados que ni acercando del todo se separan no se esconden: se juntan en una marca', async () => {
    const antes = { ...EVENTOS }
    EVENTOS.eventos = [690, 692].map(i => ({ tipo: 'dividendo', fecha: puntos[i].d, monto: 0.2, moneda: 'usd',
      reaccion: { desde: puntos[i - 1].d, hasta: puntos[i].d, pct: 0, cuando: 'ese_dia' } }))
    angosto()
    try {
      await dibujar()
      // Lo más acercado (20 días y su aire) son ~13 px por día: 2 días nunca llegan a los 34 de una marca.
      expect(marcas().map(n => texto(n))).toEqual(['D2'])
      expect(texto(montado.contenedor)).not.toContain('Acercá el gráfico para ver los dividendos.')
    } finally {
      EVENTOS.eventos = antes.eventos
    }
  })

  it('los controles van en un renglón: la moneda y el período en un menú; botones de 44 px y la barra sólo con íconos', async () => {
    angosto()
    await dibujar({ lotes: [{ entry_date: puntos[620].d, quantity: 1 }] })
    // Ya no hay dos filas de botones sueltos (Dólares/Pesos y Todo/Desde que lo tenés).
    expect(porRol(montado.contenedor, 'group', 'Moneda')).toBeNull()
    expect(porRol(montado.contenedor, 'group', 'Rango')).toBeNull()
    expect(buscarBoton(montado.contenedor, 'Dólares')).toBeNull()
    expect(await opcionesDeLaVista(montado.contenedor)).toEqual(['DólaresUS$', 'Pesos$', 'Lo reciente3 meses', 'Todo', 'Desde que lo tenés'])
    await elegirEnLaVista(montado.contenedor, 'Pesos'); await redibujar()
    expect(texto(botonDeLaVista(montado.contenedor))).toBe('Moneda y período: $ · Reciente')
    // Ningún período escribe en el botón más que «Reciente»: medido a 375 px con
    // velas, más largo («Desde tu compra») el botón bajaba a otro renglón.
    for (const r of ['Desde que lo tenés', 'Todo', 'Lo reciente']) {
      await elegirEnLaVista(montado.contenedor, r); await redibujar()
      expect(periodoElegido(montado.contenedor).length).toBeLessThanOrEqual('Reciente'.length)
    }
    // Cada botón de arriba del gráfico, de 44 px en el celular.
    const arriba = ['pantalla', 'linea', 'velas', 'vista'].map(c => todos(montado.contenedor, n => n.getAttribute?.('data-capa') === c)[0])
    for (const b of arriba) expect(b.getAttribute('class')).toMatch(/(^| )min-h-11( |$)/)
    // «Pantalla completa» en el celular es el ícono; el nombre, para el lector de pantalla.
    const pc = todos(arriba[0], n => n.nodeName === 'SPAN' && texto(n) === 'Pantalla completa')[0]
    expect(pc.getAttribute('class')).toBe('sr-only sm:not-sr-only')
    // La barra de herramientas: cada botón de 44 × 44, con el nombre escondido (no al lado del ícono).
    const barra = porRol(montado.contenedor, 'toolbar', 'Herramientas del gráfico')
    const botones = todos(barra, n => n.nodeName === 'BUTTON')
    expect(botones.length).toBeGreaterThan(3)
    for (const b of botones) {
      expect(b.getAttribute('class')).toMatch(/ h-11 w-11 /)
      const nombres = b.childNodes.filter(n => n.nodeName === 'SPAN' && !n.getAttribute('aria-hidden'))
      expect(nombres.length).toBeGreaterThan(0)
      for (const n of nombres) expect(n.getAttribute('class')).toBe('sr-only')
    }
  })

  it('con un dedo, lo que promete la ayuda: deslizar mueve el gráfico en el tiempo; mantener apretado y deslizar muestra cada día', async () => {
    angosto()
    await dibujar()
    const t = (cx, cy = 100) => ({ touches: [{ clientX: cx, clientY: cy }], changedTouches: [{ clientX: cx, clientY: cy }] })
    const globo = () => todos(montado.contenedor, n => n.getAttribute?.('data-globo') != null)[0]
    const n = diasRecientes(300, puntos.length), lugares = n + margenDerecho(n)
    // Deslizar hacia la derecha: para atrás en el tiempo (como arrastrar con el mouse).
    await evento('touchstart', grafico(), t(200))
    for (const x of [400, 600]) await evento('touchmove', grafico(), t(x))
    expect(globo()).toBeUndefined()                  // mientras se mueve, sin el globo encima
    await evento('touchend', grafico(), { touches: [], changedTouches: [{ clientX: 600, clientY: 100 }] })
    await redibujar()
    const corrido = Math.round(0.2 * lugares) * 2   // 400 px de 1000: dos pasos del 20 %
    expect(await primerDia()).toContain(`, el ${fecha(puntos[700 - n - corrido].d)}.`)
    expect(periodoElegido(montado.contenedor)).toBe(null)   // ya no es «Lo reciente»: se movió a mano
    // Para arriba o abajo (aunque el pulgar se tuerza un poco) es la página la que se mueve: el gráfico queda.
    await evento('touchstart', grafico(), t(500, 100))
    for (const [x, y] of [[520, 200], [560, 300]]) await evento('touchmove', grafico(), t(x, y))
    await evento('touchend', grafico(), { touches: [], changedTouches: [{ clientX: 560, clientY: 300 }] })
    await redibujar()
    expect(await primerDia()).toContain(`, el ${fecha(puntos[700 - n - corrido].d)}.`)
    // Mantener apretado y después deslizar: pasea el globo de cada día, no mueve el gráfico.
    const ahora = Date.now()
    const reloj = vi.spyOn(Date, 'now').mockReturnValue(ahora)
    try {
      await evento('touchstart', grafico(), t(200))
      reloj.mockReturnValue(ahora + 500)
      await evento('touchmove', grafico(), t(600))
      await redibujar()
      expect(globo()).toBeDefined()
      await evento('touchend', grafico(), { touches: [], changedTouches: [{ clientX: 600, clientY: 100 }] })
      await redibujar()
    } finally { reloj.mockRestore() }
    expect(await primerDia()).toContain(`, el ${fecha(puntos[700 - n - corrido].d)}.`)
  })

  it('la ayuda de abajo del gráfico: en el celular, para el dedo; en la compu, corta', async () => {
    angosto()
    localStorage.setItem('rendi_grafico_tipo', 'velas')
    await dibujar()
    await elegirEnLaVista(montado.contenedor, 'Todo'); await redibujar()   // > 300 velas diarias
    const ayuda = todos(montado.contenedor, n => n.getAttribute?.('data-ayuda') != null)[0]
    const celular = ayuda.childNodes.find(n => n.getAttribute?.('class') === 'sm:hidden')
    const compu = ayuda.childNodes.find(n => n.getAttribute?.('class') === 'hidden sm:inline')
    expect(texto(celular)).toBe('Pellizcá para acercar o alejar, deslizá para moverte, mantené apretado para ver cada día y tocá un dibujo para elegirlo.')
    // Lo que se ve en el celular (todo menos lo de la compu) no habla de la ruedita ni del mouse.
    const enCelular = texto(ayuda).replace(texto(compu), '')
    expect(enCelular).toContain('Cada vela es un día')
    expect(enCelular).not.toMatch(/ruedita|mouse|click/i)
    expect(texto(compu).length).toBeLessThan(120)   // antes eran ~330 letras
    // Pegada a las fechas, antes del panel del RSI: abajo de todo, con los paneles
    // prendidos, caía donde flotan WhatsApp y Mervall-E y quedaba tapada.
    const t = texto(montado.contenedor)
    expect(t).toContain('Fuerza (RSI)')
    expect(t.indexOf('Pellizcá')).toBeLessThan(t.indexOf('Fuerza (RSI)'))
  })
})

describe('desde que lo tenés', () => {
  it('sólo si lo tenés; arranca en tu primera compra', async () => {
    await dibujar()
    expect(await opcionesDeLaVista(montado.contenedor)).not.toContain('Desde que lo tenés')
    await montado.desmontar()
    await dibujar({ lotes: [{ entry_date: puntos[620].d, quantity: 2 }, { entry_date: puntos[640].d, quantity: 1 }] })
    await elegirEnLaVista(montado.contenedor, 'Desde que lo tenés'); await redibujar()
    expect(periodoElegido(montado.contenedor)).toBe('Lo tuyo')
    // El primer día que se ve es el de tu primera compra: midiendo desde el borde izquierdo.
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos')); await redibujar()
    await clickEn(0)
    expect(status()).toContain(`, el ${fecha(puntos[620].d)}. Ahora tocá el otro punto.`)
  })
})

describe('cuánto se mueve este papel', () => {
  it('con lo que manda el servidor y tu tenencia', async () => {
    await dibujar({ tenencia: { valorUsd: 5300, tc: 1400 }, pesoEnCartera: 0.11, lotes: [{ entry_date: puntos[620].d, quantity: 2 }] })
    const t = texto(montado.contenedor)
    expect(t).toContain('Cuánto se mueve este papel')
    expect(t).toContain('Últimos 2 años, en dólares')
    expect(t).toContain('Su peor caída')
    expect(t).toContain('Todavía no volvió a US$ 122,50.')
    expect(t).toContain('±1,6%')
    // 5.300 × 1,6 % = 84,8 → −US$ 85; el 11 % lo manda el servidor (senales_semana.peso).
    expect(t).toContain('−US$ 85')
    expect(t).toContain('Es el 11% de tu cartera')
    expect(t).toContain('no dice cuánto se va a mover de acá en adelante')
  })

  it('sin tenencia, sin la tarjeta de tu cartera', async () => {
    await dibujar()
    const t = texto(montado.contenedor)
    expect(t).toContain('Un día normal')
    expect(t).not.toContain('En tu cartera')
  })
})
