// La pieza 12 de la ficha, montada de verdad (testing/navegadorMinimo.js):
//   · medir entre dos puntos con el mouse y con el dedo, sin romper el
//     arrastre del gráfico (arrastrar o deslizar NO marca un punto);
//   · los balances («B») y dividendos («D») sobre el eje de fechas, con su
//     globo, y el botón de la leyenda que los prende y los apaga;
//   · el rango «Desde que lo tenés», que arranca en tu primera compra;
//   · «Cuánto se mueve este papel» con lo que manda el servidor y tu tenencia.
// Lo que manda el servidor tiene la forma de backend/movimiento.py (sus
// cuentas se prueban allá, contra una cuenta independiente).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, enActo, medidas, clic, buscarBoton } from '../../testing/navegadorMinimo'

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
      reaccion: { desde: puntos[600].d, hasta: puntos[601].d, pct: -4.21, cuando: 'al_otro_dia' } },
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
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
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
async function clickEn(x) {
  await evento('mousedown', grafico(), { clientX: x, clientY: 100 })
  await evento('mouseup', grafico(), { clientX: x, clientY: 100 })
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
// Lo que se ve en 1A: los últimos 365 puntos (uno por día). El punto bajo x:
// round(x / 1000 × 364) dentro de lo que se ve.
const bajo = (x) => 700 - 365 + Math.round((x / 1000) * 364)
const pct = (a, b) => ((puntos[b].c / puntos[a].c - 1) * 100).toLocaleString('es-AR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })

describe('medir entre dos puntos', () => {
  it('con el mouse: dos clicks dan el % entre los cierres y los días de mercado', async () => {
    await dibujar()
    expect(texto(montado.contenedor)).not.toContain('Tocá un día del gráfico')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos'))
    await redibujar()
    expect(texto(montado.contenedor)).toContain('Tocá un día del gráfico para empezar a medir.')

    await clickEn(100)
    expect(texto(montado.contenedor)).toContain(`Desde el ${fecha(puntos[bajo(100)].d)}. Ahora tocá el otro día.`)
    await clickEn(900)
    const a = bajo(100), b = bajo(900), signo = puntos[b].c >= puntos[a].c ? '+' : '−'
    const t = texto(montado.contenedor)
    expect(t).toContain(`${signo}${pct(a, b).replace('-', '')}% en ${b - a} días de mercado`)
    expect(t).toContain(`del ${fecha(puntos[a].d)}`)
    expect(t).toContain(`al ${fecha(puntos[b].d)}`)

    // Un tercer click empieza otra medición.
    await clickEn(500)
    expect(texto(montado.contenedor)).toContain(`Desde el ${fecha(puntos[bajo(500)].d)}.`)
  })

  it('arrastrar el gráfico sigue moviéndolo y no marca un punto', async () => {
    await dibujar()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos'))
    await redibujar()
    await evento('mousedown', grafico(), { clientX: 300, clientY: 100 })
    await evento('mousemove', grafico(), { clientX: 600, clientY: 100 })
    await evento('mouseup', grafico(), { clientX: 600, clientY: 100 })
    await redibujar()
    const t = texto(montado.contenedor)
    expect(t).toContain('Tocá un día del gráfico para empezar a medir.')
    // Se movió: ya no hay un rango elegido y aparece «Automático».
    expect(buscarBoton(montado.contenedor, 'Automático')).not.toBeNull()
  })

  it('con el dedo: un toque quieto marca; deslizar no', async () => {
    await dibujar()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos'))
    await redibujar()
    await toqueEn(200, 400)             // deslizó: es mirar el gráfico, no medir
    expect(texto(montado.contenedor)).toContain('Tocá un día del gráfico para empezar a medir.')
    const fin = await toqueEn(200)
    expect(fin.defaultPrevented).toBe(true)   // sin el click de mouse que el navegador arma después
    await toqueEn(800)
    const a = bajo(200), b = bajo(800)
    expect(texto(montado.contenedor)).toContain(`en ${b - a} días de mercado`)
  })

  it('apagar el modo borra la medición', async () => {
    await dibujar()
    const boton = () => buscarBoton(montado.contenedor, 'Medir entre dos puntos')
    await clic(montado.contenedor, boton()); await redibujar()
    await clickEn(100); await clickEn(900)
    await clic(montado.contenedor, boton()); await redibujar()
    expect(texto(montado.contenedor)).not.toContain('días de mercado:')
    expect(boton().getAttribute('aria-pressed')).toBe('false')
  })
})

describe('balances y dividendos en el gráfico', () => {
  const marcas = () => todos(montado.contenedor, n => n.nodeName === 'BUTTON'
    && /^(Balance|Dividendo)/.test(n.getAttribute?.('aria-label') || ''))

  it('una «B» y una «D» con su globo, y el botón de la leyenda los apaga', async () => {
    await dibujar()
    const ms = marcas()
    expect(ms.map(n => texto(n))).toEqual(['B', 'D'])
    expect(ms[0].getAttribute('aria-label')).toBe(
      `Balance del ${fecha(puntos[600].d)}. Lo presentó con el mercado ya cerrado. Al otro día el precio: −4,2%`)
    // Con un toque, el globo.
    await clic(montado.contenedor, ms[1]); await redibujar()
    const t = texto(montado.contenedor)
    expect(t).toContain(`Dividendo · día de corte ${fecha(puntos[610].d)}`)
    expect(t).toContain('Pagó US$ 0,26 por acción.')
    expect(t).toContain('Ese día el precio: −0,4%')

    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Balances y dividendos')); await redibujar()
    expect(marcas()).toEqual([])
  })

  it('los que no entran en lo que se ve no se dibujan', async () => {
    await dibujar()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, '3M')); await redibujar()
    // 3M = los últimos 91 días: el balance (hace 99) queda afuera y el dividendo (hace 89) adentro.
    expect(marcas().map(n => texto(n))).toEqual(['D'])
  })
})

describe('marcas que se pisarían', () => {
  it('en un gráfico angosto, los dividendos de todos los meses se juntan en una marca con cuántos son', async () => {
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
        && /^(Balance|\d+ dividendos)/.test(n.getAttribute?.('aria-label') || ''))
      expect(ms.map(n => texto(n))).toEqual(['B', 'D3'])
      await clic(montado.contenedor, ms[1]); await redibujar()
      const t = texto(montado.contenedor)
      expect(t).toContain('3 dividendos')
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
    expect(texto(montado.contenedor)).toContain(`Desde el ${fecha(puntos[620].d)}.`)
  })
})

describe('cuánto se mueve este papel', () => {
  it('con lo que manda el servidor y tu tenencia', async () => {
    await dibujar({ tenencia: { valorUsd: 5300, tc: 1400 }, valorCartera: 48000, lotes: [{ entry_date: puntos[620].d, quantity: 2 }] })
    const t = texto(montado.contenedor)
    expect(t).toContain('Cuánto se mueve este papel')
    expect(t).toContain('Últimos 2 años, en dólares')
    expect(t).toContain('Su peor caída')
    expect(t).toContain('Todavía no volvió a US$ 122,50.')
    expect(t).toContain('±1,6%')
    // 5.300 × 1,6 % = 84,8 → −US$ 85; 5.300 de 48.000 = 11 %.
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
