// La escala logarítmica del gráfico (Nico, 12/11: un usuario la pidió),
// montada de verdad (testing/navegadorMinimo.js) con /api/tecnico simulado en
// la frontera, como DibujosGrafico.test.js:
//   · de entrada, la escala de siempre; «Log» (debajo de la columna de
//     precios) la cambia, se recuerda y «Volver a lo de fábrica» la olvida;
//   · en logarítmica los precios del eje se reparten multiplicando y lo que
//     multiplica igual mide lo mismo (de 10 a 100 = de 20 a 200);
//   · el precio bajo el mouse es la vuelta exacta de la altura;
//   · una línea o un canal dibujados en logarítmica se guardan con su escala
//     y, mirados en la de siempre, se dibujan curvos (es la misma línea);
//   · la imagen de «Compartir» sale con la misma escala y lo dice al pie.
// Las cuentas sueltas están en utils/escalaPrecio.test.js; el aviso del
// servidor que sigue la línea en su escala, en backend/tests/test_alertas_tecnicas.py.
import { describe, it, expect, vi, beforeAll, afterAll, beforeEach, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { instalarNavegadorMinimo, montar, texto, enActo, medidas, clic, puntero } from '../../testing/navegadorMinimo'
import { pasarATodo } from '../../testing/menuGrafico'

// Cinco años de un papel que se multiplicó por 20: de 10 a 200, parejo en porcentaje.
const puntos = Array.from({ length: 700 }, (_, i) => {
  const d = new Date(Date.UTC(2024, 0, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = 10 * Math.pow(20, i / 699)
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, s50: null, s200: null, rsi: 50 }
})
const DATOS = {
  disponible: true, moneda: 'usd', ticker: 'ZZLG', convertida: null, puntos, fibonacci: undefined,
  lectura: { ruedas: 700, fecha: puntos[699].d, precio: puntos[699].c, rsi: 50 },
}

// La cuenta, del otro lado de la frontera: lo que se guarda de los dibujos.
// `viejo`: un servidor de antes de la escala (guarda sin ella y no lo dice).
const cuenta = { usd: [], viejo: false, puts: 0 }
vi.mock('../../utils/api', () => ({
  getClientContext: () => null,
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
  api: {
    get: vi.fn((ruta) => Promise.resolve(ruta.includes('/dibujos') ? { dibujos: cuenta.usd }
      : ruta.startsWith('/alerts') ? { items: [] } : ruta.includes('/eventos') ? { eventos: [] } : DATOS)),
    post: vi.fn(() => Promise.resolve({ ok: true })),
    patch: vi.fn(() => Promise.resolve({ ok: true })),
    put: vi.fn((ruta, body) => {
      cuenta.puts++
      cuenta.usd = cuenta.viejo ? body.dibujos.map(({ escala, ...d }) => d) : body.dibujos
      cuenta.ultimoPut = body
      return Promise.resolve(cuenta.viejo ? { ok: true, dibujos: body.dibujos.length } : { ok: true, dibujos: body.dibujos.length, escalas: true })
    }),
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
  medidas(() => ({ left: 0, top: 0, width: 1000, height: 250, right: 1000, bottom: 250 }))
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { medidas(null); vi.unstubAllGlobals() })

let montado
beforeEach(() => { localStorage.setItem('rendi_user', JSON.stringify({ name: 'Ana', email: 'ana@prueba.test' })) })
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()
  Object.assign(cuenta, { usd: [], viejo: false, puts: 0, ultimoPut: null })
  pedidas.length = 0
})

const el = () => h(MemoryRouter, null, h(LecturaTecnica, { asset: 'ZZLG' }))
async function redibujar() { for (let i = 0; i < 2; i++) await montado.redibujar(el()) }
async function dibujar() {
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
const botonLog = () => boton('escala-log')
const grafico = () => todos(montado.contenedor, n => n.getAttribute?.('role') === 'img' && (n.getAttribute('aria-label') || '').startsWith('Precio con su promedio'))[0]
const num = (t) => Number(t.replace(/\./g, '').replace(',', '.'))
// Los precios de la columna: { precio, top } (top en % del alto).
const rotulos = () => todos(montado.contenedor, n => n.nodeName === 'SPAN' && clase(n).includes('left-1.5') && clase(n).includes('text-[11px]'))
  .map(n => ({ precio: num(texto(n)), top: parseFloat(n.style.top) }))
const lineas = () => todos(montado.contenedor, n => (n.nodeName === 'LINE' || n.nodeName === 'POLYLINE') && n.getAttribute?.('data-dibujo') != null)

async function evento(tipo, nodo, datos = {}) {
  await enActo(async () => {
    const ev = { type: tipo, target: nodo, bubbles: true, cancelable: true, button: 0, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true }, stopPropagation() {}, ...datos }
    for (const fn of montado.contenedor.escuchas[tipo] || []) fn(ev)
  })
}
async function clickEn(x, y) {
  await evento('mousedown', grafico(), { clientX: x, clientY: y })
  await evento('mouseup', grafico(), { clientX: x, clientY: y })
  await redibujar()
}
async function usar(id) {
  await clic(montado.contenedor, boton('menu-lineas')); await redibujar()
  await clic(montado.contenedor, boton(id)); await redibujar()
}
async function tocarLog() { await clic(montado.contenedor, botonLog()); await redibujar() }

describe('la escala logarítmica del gráfico', () => {
  it('de entrada la de siempre; «Log» la cambia y se recuerda; «Volver a lo de fábrica» la olvida', async () => {
    await dibujar()
    expect(botonLog().getAttribute('aria-pressed')).toBe('false')
    expect(grafico().getAttribute('aria-label')).not.toContain('logarítmica')
    // En la de siempre los precios del eje van parejos: el mismo salto, la misma distancia.
    const parejos = rotulos()
    const pasos = parejos.slice(1).map((r, k) => parejos[k].top - r.top)
    for (const p of pasos) expect(p).toBeCloseTo(pasos[0], 6)

    await tocarLog()
    expect(botonLog().getAttribute('aria-pressed')).toBe('true')
    expect(localStorage.getItem('rendi_grafico_escala')).toBe('log')
    expect(grafico().getAttribute('aria-label')).toContain('En escala logarítmica.')
    expect(texto(montado.contenedor)).toContain('Escala logarítmica: una suba del mismo porcentaje mide lo mismo en todo el gráfico.')
    // Los precios del eje se reparten multiplicando (el 200 lo tapa el último
    // precio, que está ahí), y lo que multiplica igual mide lo mismo: de 10 a
    // 20 como de 50 a 100; de 10 a 50 como de 20 a 100.
    const r = rotulos()
    expect(r.map(x => x.precio)).toEqual([10, 20, 50, 100])
    const top = (p) => r.find(x => x.precio === p).top
    expect(top(10) - top(20)).toBeCloseTo(top(50) - top(100), 6)
    expect(top(10) - top(50)).toBeCloseTo(top(20) - top(100), 6)

    // Otra visita a la ficha: sigue en logarítmica.
    await montado.desmontar()
    await dibujar()
    expect(botonLog().getAttribute('aria-pressed')).toBe('true')

    // «Volver a lo de fábrica»: la de siempre, y se olvida lo guardado.
    expect(boton('fabrica').getAttribute('disabled')).toBeNull()
    await clic(montado.contenedor, boton('fabrica')); await redibujar()
    expect(botonLog().getAttribute('aria-pressed')).toBe('false')
    expect(localStorage.getItem('rendi_grafico_escala')).toBeNull()
  })

  it('el precio bajo el mouse es la vuelta de la altura: una horizontal cae donde se tocó', async () => {
    await dibujar()
    await tocarLog()
    await usar('horizontal')
    await clickEn(400, 125)                                  // la mitad del alto
    const [l] = lineas()
    expect(Number(l.getAttribute('y1'))).toBeCloseTo(50, 3)          // el precio se guarda redondeado
    // El precio guardado es el de esa altura según los rótulos del eje, leído
    // en logarítmica (entre 20 y 50: su logaritmo, en proporción a la altura).
    const r = rotulos(), top = (p) => r.find(x => x.precio === p).top
    const f = (50 - top(20)) / (top(50) - top(20))
    const esperado = Math.exp(Math.log(20) + f * (Math.log(50) - Math.log(20)))
    expect(cuenta.usd[0].precio).toBeCloseTo(esperado, 3)
    // En la de siempre, esa misma cuenta daría otro precio.
    expect(Math.abs((20 + f * 30) - esperado)).toBeGreaterThan(1)
  })

  it('una línea y un canal dibujados en logarítmica se guardan con su escala; en la de siempre se ven curvos', async () => {
    await dibujar()
    await tocarLog()
    await usar('tendencia'); await clickEn(100, 200); await clickEn(600, 100)
    await usar('canal'); await clickEn(200, 220); await clickEn(700, 140); await clickEn(450, 120)
    const [t, c] = cuenta.usd
    expect(t).toMatchObject({ tipo: 'tendencia', escala: 'log' })
    expect(c).toMatchObject({ tipo: 'canal', escala: 'log' })
    // El ancho del canal es cuánto multiplica su paralela (un logaritmo chico), no plata.
    expect(Math.abs(c.ancho)).toBeLessThan(2)
    expect(cuenta.ultimoPut.escalas).toBe(true)              // esta pantalla conoce la escala
    // En logarítmica, rectas: cada una es un <line>.
    expect(lineas().every(n => n.nodeName === 'LINE')).toBe(true)
    // La franja del canal va de su línea a su paralela (la que multiplica, no
    // la línea más «ancho» de plata): su tercera esquina es la punta de la paralela.
    const franja = () => todos(montado.contenedor, n => n.nodeName === 'POLYGON' && (n.getAttribute('fill-opacity') || n.getAttribute('fillOpacity')))
      .map(n => n.getAttribute('points').split(' ').map(q => q.split(',').map(Number)))[0]
    const paralela = lineas().filter(n => n.getAttribute('data-dibujo') === c.id)[1]
    expect(franja()).toHaveLength(4)
    expect(franja()[1][0]).toBeCloseTo(Number(paralela.getAttribute('x2')), 6)
    expect(franja()[2][1]).toBeCloseTo(Number(paralela.getAttribute('y2')), 6)
    // En la de siempre, la misma línea es una curva (un solo trazo).
    await tocarLog()
    expect(franja().length).toBeGreaterThan(10)              // la franja también, curva
    const curvas = lineas().filter(n => n.nodeName === 'POLYLINE')
    expect(curvas.length).toBe(4)                            // la tendencia y los tres bordes del canal
    expect(curvas.every(n => n.getAttribute('points').split(' ').length > 10)).toBe(true)
    // Lo dibujado en la de siempre no lleva marca (como todas las de antes).
    await usar('tendencia'); await clickEn(150, 210); await clickEn(650, 120)
    expect(cuenta.usd[2].escala).toBeUndefined()
  })

  it('la imagen de «Compartir» sale con la misma escala y lo dice al pie', async () => {
    await dibujar()
    await tocarLog()
    await clic(montado.contenedor, boton('compartir'))
    for (let i = 0; i < 3; i++) await enActo(async () => {})
    const spec = pedidas.at(-1)
    expect(spec.pie).toContain('Escala logarítmica: una suba del mismo porcentaje mide lo mismo en todo el gráfico.')
    const eje = Object.fromEntries(spec.grafico.eje.map(t => [t.texto, t.y]))
    expect(eje['10'] - eje['100']).toBeCloseTo(eje['20'] - eje['200'], 6)
  })

  // — arrastrar con «Log» prendido: la línea, el eje y el ancho de un canal —
  async function arrastrar(x0, y0, x1, y1) {
    await evento('mousedown', grafico(), { clientX: x0, clientY: y0 })
    await evento('mousemove', grafico(), { clientX: (x0 + x1) / 2, clientY: (y0 + y1) / 2 })
    await evento('mousemove', grafico(), { clientX: x1, clientY: y1 })
    await evento('mouseup', grafico(), { clientX: x1, clientY: y1 })
    await redibujar()
  }
  const columna = () => todos(montado.contenedor, n => (n.getAttribute?.('title') || '').startsWith('Arrastrá hacia arriba o hacia abajo'))[0]
  async function estirarColumna(dy) {
    await puntero('pointerdown', columna(), { clientX: 970, clientY: 100 })
    for (let k = 1; k <= 7; k++) await puntero('pointermove', columna(), { clientX: 970, clientY: 100 + (dy * k) / 7 })
    await puntero('pointerup', columna(), { clientX: 970, clientY: 100 + dy })
    await redibujar()
  }
  const sinNumerosRotos = () => todos(montado.contenedor, n => ['d', 'x1', 'y1', 'x2', 'y2', 'points', 'y', 'height']
    .some(a => /NaN|Infinity/.test(n.getAttribute?.(a) || '')))
  const automatico = () => todos(montado.contenedor, n => n.nodeName === 'BUTTON' && texto(n) === 'Automático')[0]

  it('arrastrar una horizontal en «Log» la deja donde se soltó', async () => {
    await dibujar()
    await tocarLog()
    await usar('horizontal'); await clickEn(400, 100)
    await arrastrar(500, 100, 500, 150)
    const [l] = lineas()
    expect(Number(l.getAttribute('y1'))).toBeCloseTo(60, 2)          // 150 de 250 px
  })

  it('estirar la columna en «Log» hasta el tope, dos veces: el gráfico sigue entero; cambiar de escala vuelve a automático', async () => {
    await dibujar()
    await tocarLog()
    await estirarColumna(2000)
    await estirarColumna(2000)
    expect(sinNumerosRotos()).toEqual([])
    const r = rotulos()
    expect(r.length).toBeGreaterThanOrEqual(2)
    expect(r.every(x => x.precio > 0)).toBe(true)
    expect(automatico()).toBeTruthy()
    await tocarLog()                                         // a la de siempre: el precio a mano no sirve ahí
    expect(automatico()).toBeFalsy()
    expect(sinNumerosRotos()).toEqual([])
  })

  it('ensanchar un canal logarítmico mirándolo en la de siempre: queda donde se soltó', async () => {
    await dibujar()
    await tocarLog()
    await usar('canal'); await clickEn(200, 220); await clickEn(700, 140); await clickEn(450, 120)
    await tocarLog()
    // La punta del ancho: el medio de la paralela (la segunda curva del canal).
    const paralela = () => lineas().filter(n => n.nodeName === 'POLYLINE')[1].getAttribute('points').split(' ').map(p => p.split(',').map(Number))
    const [px, py] = paralela()[12]
    const x = px * 10, y = py * 2.5
    await arrastrar(x, y, x, y - 20)
    expect(paralela()[12][1] * 2.5).toBeCloseTo(y - 20, 0)
    expect(cuenta.usd[0].escala).toBe('log')
  })

  it('un canal demasiado ancho para la logarítmica no se crea (trabaría tu cuenta) y lo dice', async () => {
    await dibujar()
    await tocarLog()
    await usar('canal'); await clickEn(100, 240); await clickEn(102, 20); await clickEn(990, 240)
    expect(cuenta.usd).toEqual([])
    expect(texto(montado.contenedor)).toContain('Ese canal es demasiado ancho para la escala logarítmica')
  })

  it('con un servidor de antes de la escala, la línea logarítmica queda pendiente y se vuelve a subir', async () => {
    cuenta.viejo = true
    await dibujar()
    await tocarLog()
    await usar('tendencia'); await clickEn(100, 200); await clickEn(600, 100)
    expect(cuenta.usd[0].escala).toBeUndefined()            // el servidor viejo la guardó sin escala
    expect(texto(montado.contenedor)).toContain('No se pudieron guardar tus dibujos en tu cuenta')
    // Se publica el servidor nuevo; la próxima vez que abrís el gráfico, se sube con su escala.
    cuenta.viejo = false
    await montado.desmontar()
    await dibujar()
    expect(cuenta.usd[0].escala).toBe('log')
  })

  it('el pincel no guarda puntos de precio cero o menos (trabaría tu cuenta)', async () => {
    await dibujar()                                          // la de siempre: abajo de todo, el eje baja de 0
    await usar('pincel')
    await evento('mousedown', grafico(), { clientX: 300, clientY: 230 })
    for (const [x, y] of [[320, 240], [340, 249], [360, 249], [380, 200]]) await evento('mousemove', grafico(), { clientX: x, clientY: y })
    await evento('mouseup', grafico(), { clientX: 380, clientY: 200 }); await redibujar()
    const pinceles = cuenta.usd.filter(d => d.tipo === 'pincel')
    expect(pinceles.every(d => d.puntos.every(p => p.precio > 0))).toBe(true)
  })

  it('la imagen de «Compartir» en «Log»: tu canal logarítmico recto y tu línea de siempre curva', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(100, 200); await clickEn(600, 100)          // en la de siempre
    await tocarLog()
    await usar('canal'); await clickEn(200, 220); await clickEn(700, 140); await clickEn(450, 120)
    await clic(montado.contenedor, boton('compartir'))
    for (let i = 0; i < 3; i++) await enActo(async () => {})
    const g = pedidas.at(-1).grafico
    const curvas = g.trazos.filter(t => t.puntos)
    expect(curvas).toHaveLength(1)                                                       // la línea de siempre
    expect(curvas[0].puntos.length).toBeGreaterThan(10)
    const franja = g.poligonos.find(p => p.alpha === 0.08)
    expect(franja.puntos).toHaveLength(4)                                                // el canal, recto en su escala
  })
})

