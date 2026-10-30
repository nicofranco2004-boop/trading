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
  api: { get: vi.fn((ruta) => Promise.resolve(ruta.includes('/eventos') ? EVENTOS : DATOS)) },
}))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  medidas(() => ({ left: 0, top: 0, width: 1000, height: 250, right: 1000, bottom: 250 }))
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
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
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Desde que lo tenés')); await redibujar()
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
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Desde que lo tenés')); await redibujar()
    expect(marcas().map(n => texto(n))).toEqual(['D'])
  })
})

describe('marcas que se pisarían', () => {
  it('en un gráfico angosto, las marcas que se pisarían se juntan en una sola, con cuántas son (aunque sean de tipos distintos)', async () => {
    const antes = { ...EVENTOS }
    EVENTOS.eventos = [
      EVENTOS.eventos[0],
      ...[640, 650, 660].map(i => ({ tipo: 'dividendo', fecha: puntos[i].d, monto: 8.3, moneda: 'ars',
        reaccion: { desde: puntos[i - 1].d, hasta: puntos[i].d, pct: 1, cuando: 'ese_dia' } })),
    ]
    // El celular: el gráfico mide 300 px (10 días de mercado son 8 px).
    globalThis.ResizeObserver = class { constructor(cb) { this.cb = cb } observe() { this.cb([{ contentRect: { width: 300 } }]) } disconnect() {} }
    try {
      await dibujar()
      const ms = todos(montado.contenedor, n => n.nodeName === 'BUTTON'
        && /^(Balance|\d+ (dividendos|balances))/.test(n.getAttribute?.('aria-label') || ''))
      // Una sola fila: el balance y los tres dividendos, a menos de una marca
      // de distancia entre sí, van en UNA marca (mitad y mitad) con cuántos son.
      expect(ms.map(n => texto(n))).toEqual(['4'])
      await clic(montado.contenedor, ms[0]); await redibujar()
      const t = texto(montado.contenedor)
      expect(t).toContain('4 balances y dividendos')
      expect(t).toContain(`${fecha(puntos[600].d)}: balance · al otro día −4,2% · 10% más de lo esperado`)
      expect(t).toContain(`${fecha(puntos[650].d)}: pagó $ 8,3 · ese día +1,0%`)
    } finally {
      delete globalThis.ResizeObserver
      EVENTOS.eventos = antes.eventos
    }
  })
})

describe('desde que lo tenés', () => {
  it('sólo si lo tenés; arranca en tu primera compra', async () => {
    await dibujar()
    expect(buscarBoton(montado.contenedor, 'Desde que lo tenés')).toBeNull()
    await montado.desmontar()
    await dibujar({ lotes: [{ entry_date: puntos[620].d, quantity: 2 }, { entry_date: puntos[640].d, quantity: 1 }] })
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Desde que lo tenés')); await redibujar()
    expect(buscarBoton(montado.contenedor, 'Desde que lo tenés').getAttribute('aria-pressed')).toBe('true')
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
