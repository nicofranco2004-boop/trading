// Arrastrar los ejes del gráfico técnico, montado de verdad
// (testing/navegadorMinimo.js, que reparte el puntero como Chrome):
//   · la columna de precios: hacia abajo achica el gráfico (los precios de la
//     grilla se separan) y deja el precio a mano: aparece «Auto» (Automático),
//     y arrastrar el gráfico lo mueve para arriba y para abajo; «Auto», el
//     doble click u otro rango vuelven a lo automático;
//   · la fila de fechas, con el dedo: hacia la izquierda acerca (se ven menos
//     meses y ningún botón de rango queda elegido), doble click vuelve al 1A.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, puntero, enActo, medidas, clic, buscarBoton } from '../../testing/navegadorMinimo'
import { elegirEnLaVista, pasarATodo, periodoElegido } from '../../testing/menuGrafico'
import { margenDerecho } from '../../utils/tecnico'

const puntos = Array.from({ length: 700 }, (_, i) => {
  const d = new Date(Date.UTC(2024, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = 100 + 20 * Math.sin(i / 40) + i * 0.05
  return { d, o: c, h: c * 1.01, l: c * 0.99, c, s50: null, s200: null, rsi: 50 }
})
const DATOS = {
  disponible: true, moneda: 'usd', ticker: 'ZZEJ', convertida: null, puntos, fibonacci: undefined,
  lectura: { ruedas: 700, fecha: puntos[699].d, precio: puntos[699].c, rsi: 50 },
}

vi.mock('../../utils/api', () => ({
  // La copia de los dibujos es de la persona y la cuenta (utils/duenoDeLaPestana).
  getClientContext: () => null,
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
  api: { get: vi.fn(() => Promise.resolve(DATOS)) } }))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  // Todo mide 1000 × 250: alcanza para convertir un arrastre en fracción del alto.
  medidas(() => ({ left: 0, top: 0, width: 1000, height: 250, right: 1000, bottom: 250 }))
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { medidas(null); vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()   // lo que apaga una prueba no pasa a la siguiente
})

// Con una compra hace 200 días: hay «Desde que lo tenés» (el otro rango además de «Todo»).
const el = () => h(LecturaTecnica, { asset: 'ZZEJ', lotes: [{ entry_date: puntos[500].d, quantity: 1 }] })
// De entrada el gráfico abre en el último año; estas pruebas arrancan de la
// historia entera, así que pasan a «Todo».
async function dibujar() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  await pasarATodo(montado.contenedor)
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
}

// El primer nodo cuyo `title` empieza así.
function porTitulo(nodo, empieza) {
  const pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (n.getAttribute?.('title')?.startsWith(empieza)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
const numeros = (t) => (t.match(/[\d.]+(,\d+)?/g) || []).map(x => Number(x.replace(/\./g, '').replace(',', '.')))

// «Auto» (Automático): el botón que vuelve el precio y las fechas a automático.
function botonAuto() {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === 'automatico') return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
async function arrastrar(nodo, { dx = 0, dy = 0, pointerType = 'mouse' }) {
  await puntero('pointerdown', nodo, { pointerType, clientX: 100, clientY: 100 })
  for (let k = 1; k <= 7; k++) {
    await puntero('pointermove', nodo, { pointerType, clientX: 100 + (dx * k) / 7, clientY: 100 + (dy * k) / 7 })
  }
  await puntero('pointerup', nodo, { pointerType, clientX: 100 + dx, clientY: 100 + dy })
}
// Un evento del mouse (no de puntero) como lo recibe React: por la raíz.
async function raton(tipo, nodo, datos = {}) {
  await enActo(async () => {
    const ev = { type: tipo, target: nodo, bubbles: true, cancelable: true, button: 0,
      preventDefault() {}, stopPropagation() {}, ...datos }
    for (const fn of montado.contenedor.escuchas[tipo] || []) fn(ev)
  })
}
async function dobleClick(nodo) {
  await raton('dblclick', nodo, { detail: 2 })
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
}
function porRol(nodo, rol) {
  const pila = [nodo]
  while (pila.length) {
    const n = pila.shift()
    if (n.getAttribute?.('role') === rol) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}

describe('arrastrar los ejes del gráfico', () => {
  it('la columna de precios: achica, deja el precio a mano y se vuelve a automático', async () => {
    await dibujar()
    const columna = porTitulo(montado.contenedor, 'Arrastrá hacia arriba o hacia abajo')
    expect(columna).not.toBeNull()
    // Cada rótulo de la columna (la grilla y el último precio), por separado.
    const grilla = () => columna.childNodes.filter(n => n.getAttribute?.('data-mira') == null).map(n => numeros(texto(n))[0]).filter(x => x != null)
    const antes = grilla()
    expect(botonAuto()).toBeNull()

    await arrastrar(columna, { dy: 140 })
    const achicado = grilla()
    // Entró el doble de rango de precio: los precios redondos de la columna
    // (como TradingView) van de a saltos más grandes (de 40 en 40 → de 50 en 50).
    const paso = (g) => { const r = g.filter(Number.isInteger).sort((x, y) => x - y); return Math.min(...r.slice(1).map((x, k) => x - r[k])) }
    expect(paso(achicado)).toBeGreaterThan(paso(antes))
    expect(botonAuto()).not.toBeNull()

    // Con el precio a mano, arrastrar el gráfico hacia abajo muestra precios más altos.
    const grafico = porRol(montado.contenedor, 'img')
    await raton('mousedown', grafico, { clientX: 500, clientY: 100 })
    await raton('mousemove', grafico, { clientX: 500, clientY: 150 })   // 1/5 del alto
    await raton('mouseup', grafico, { clientX: 500, clientY: 150 })
    const corrido = grilla()
    expect(Math.max(...corrido)).toBeGreaterThan(Math.max(...achicado))

    // «Automático» lo devuelve.
    await clic(montado.contenedor, botonAuto())
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(grilla()).toEqual(antes)
    expect(botonAuto()).toBeNull()

    // El doble click también.
    await arrastrar(columna, { dy: -100 })
    expect(grilla()).not.toEqual(antes)
    await dobleClick(columna)
    expect(grilla()).toEqual(antes)

  })

  it('arrastrar el gráfico para arriba o para abajo lo mueve a donde quieras, aunque no haya precios ahí (Nico, 29/10)', async () => {
    await dibujar()
    const columna = porTitulo(montado.contenedor, 'Arrastrá hacia arriba o hacia abajo')
    const grilla = () => columna.childNodes.filter(n => n.getAttribute?.('data-mira') == null).map(n => numeros(texto(n))[0]).filter(x => x != null)
    const antes = grilla()
    const grafico = porRol(montado.contenedor, 'img')
    // Un temblor de la mano (6 px para abajo) no mueve el precio ni lo saca de automático.
    await raton('mousedown', grafico, { clientX: 500, clientY: 100 })
    await raton('mousemove', grafico, { clientX: 500, clientY: 106 })
    await raton('mouseup', grafico, { clientX: 500, clientY: 106 })
    expect(grilla()).toEqual(antes)
    expect(botonAuto()).toBeNull()
    // Hacia abajo, mucho: muestra precios bastante más altos que el máximo que hubo.
    await raton('mousedown', grafico, { clientX: 500, clientY: 20 })
    for (const y of [60, 120, 180, 240]) await raton('mousemove', grafico, { clientX: 500, clientY: y })
    await raton('mouseup', grafico, { clientX: 500, clientY: 240 })
    expect(botonAuto()).not.toBeNull()
    expect(Math.min(...grilla())).toBeGreaterThan(Math.max(...antes))  // ya no se ve ningún precio de los de antes
    await clic(montado.contenedor, botonAuto())
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(grilla()).toEqual(antes)
  })

  it('el mouse lleva su precio a la columna y su día a la fila de fechas, como TradingView (Nico, 29/10)', async () => {
    await dibujar()
    const grafico = porRol(montado.contenedor, 'img')
    const miras = () => {
      const out = [], pila = [montado.contenedor]
      while (pila.length) { const n = pila.shift(); if (n.getAttribute?.('data-mira') != null) out.push(texto(n)); pila.push(...(n.childNodes || [])) }
      return out
    }
    expect(miras()).toEqual([])
    // Arriba de todo del gráfico (y = 0) y en el último día con precio.
    const ultimoLugar = 1000 * (699 / (699 + margenDerecho(700)))
    await raton('mousemove', grafico, { clientX: ultimoLugar, clientY: 0 })
    const precio = miras().find(t => /^[\d.,]+$/.test(t))
    const dia = miras().find(t => /[a-z]/.test(t))
    expect(miras()).toHaveLength(2)
    expect(numeros(precio)[0]).toBeGreaterThan(Math.max(...puntos.map(p => p.c)))   // lo más alto que se ve
    const d = new Date(puntos[699].d + 'T12:00:00Z')
    expect(dia).toContain(`${d.getUTCDate()} `)
    await raton('mouseout', grafico, { relatedTarget: null })
    expect(miras()).toEqual([])
  })

  // Otro rango, moneda, tipo de gráfico o diarias/semanales: el precio vuelve a
  // automático (cada uno con su prueba, como pidió la sesión central).
  for (const [nombre, pasos] of [
    ['otro rango', ['Desde que lo tenés']],
    ['otra moneda', ['Pesos']],
    ['otro tipo de gráfico', ['Línea']],                              // de fábrica son velas
    ['de diarias a semanales', ['Velas', '@', '1D', 'Semanales']],   // «1D» abre el menú de las velas
  ]) {
    it(`${nombre} vuelve el precio a automático`, async () => {
      await dibujar()
      const columna = () => porTitulo(montado.contenedor, 'Arrastrá hacia arriba o hacia abajo')
      const grilla = () => columna().childNodes.filter(n => n.getAttribute?.('data-mira') == null).map(n => numeros(texto(n))[0]).filter(x => x != null)
      // Lo que se cambia ANTES de estirar (marcado con '@') no cuenta: es el punto de partida.
      // La moneda y el rango están en el menú «Moneda y período»; lo demás, a la vista.
      const tocar = (b) => (['Pesos', 'Desde que lo tenés'].includes(b) ? elegirEnLaVista(montado.contenedor, b)
        : clic(montado.contenedor, buscarBoton(montado.contenedor, b)))
      const antes = pasos.includes('@') ? pasos.slice(0, pasos.indexOf('@')) : []
      const despues = pasos.includes('@') ? pasos.slice(pasos.indexOf('@') + 1) : pasos
      for (const b of antes) {
        await tocar(b)
        for (let i = 0; i < 3; i++) await montado.redibujar(el())
      }
      const auto = grilla()
      await arrastrar(columna(), { dy: 120 })
      expect(grilla()).not.toEqual(auto)
      expect(botonAuto()).not.toBeNull()
      for (const b of despues) {
        await tocar(b)
        for (let i = 0; i < 3; i++) await montado.redibujar(el())
      }
      expect(botonAuto()).toBeNull()
    }, 15000)   // muchos redibujos de toda la historia: con la suite entera corriendo pasa los 5 s
  }

  it('las fechas a mano también muestran «Automático» (en el celular no hay doble click)', async () => {
    await dibujar()
    const fechas = porTitulo(montado.contenedor, 'Arrastrá hacia los costados')
    expect(botonAuto()).toBeNull()
    await arrastrar(fechas, { dx: -200, pointerType: 'touch' })   // acerca (con «Todo» ya no se puede alejar más)
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(periodoElegido(montado.contenedor)).toBe(null)
    await clic(montado.contenedor, botonAuto())
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(periodoElegido(montado.contenedor)).toBe('Todo')
    expect(botonAuto()).toBeNull()
  })

  it('la fila de fechas, con el dedo: hacia la izquierda acerca; doble click, vuelve a «Todo»', async () => {
    await dibujar()
    const fechas = porTitulo(montado.contenedor, 'Arrastrá hacia los costados')
    expect(fechas).not.toBeNull()
    expect(periodoElegido(montado.contenedor)).toBe('Todo')
    const meses = () => texto(fechas)
    const antes = meses()
    await arrastrar(fechas, { dx: -280, pointerType: 'touch' })
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(meses()).not.toBe(antes)
    // Acercó: los rótulos van parejos a cualquier zoom (como TradingView), pero el
    // período que se ve se achicó: el año del principio ya no entra.
    expect(antes).toContain('2025')
    expect(meses()).not.toContain('2025')
    expect(periodoElegido(montado.contenedor)).toBe(null)  // ya no es el rango del botón
    await dobleClick(fechas)
    expect(periodoElegido(montado.contenedor)).toBe('Todo')
    expect(meses()).toBe(antes)
  })

  it('la ruedita hace lo mismo que la fila de fechas: acerca con el último día quieto, esté donde esté el mouse', async () => {
    // En línea: el punto donde termina marca el último día (con velas no hay punto).
    localStorage.setItem('rendi_grafico_tipo', 'linea')
    await dibujar()
    const fechas = porTitulo(montado.contenedor, 'Arrastrá hacia los costados')
    const rotulos = () => fechas.childNodes.filter(n => n.nodeName === 'SPAN').map(n => texto(n))
    const antes = rotulos()
    // El punto del último precio: su lugar en el ancho.
    const ultimoPunto = () => {
      const pila = [montado.contenedor]
      while (pila.length) { const n = pila.shift(); if (String(n.getAttribute?.('class') || '').startsWith('absolute w-2 h-2 -translate-x-1/2')) return n.style.left; pila.push(...(n.childNodes || [])) }
      return null
    }
    const ultimoAntes = ultimoPunto()
    expect(ultimoAntes).not.toBeNull()
    // El gráfico (role="img") tiene el escucha de la rueda; el mouse, a la izquierda de todo.
    const pila = [montado.contenedor]
    let area = null
    while (pila.length && !area) {
      const n = pila.shift()
      if (n.getAttribute?.('role') === 'img') area = n
      pila.push(...(n.childNodes || []))
    }
    expect(area).not.toBeNull()
    for (let k = 0; k < 6; k++) {
      await enActo(async () => {
        for (const fn of area.escuchas.wheel || []) fn({ deltaY: -100, deltaMode: 0, clientX: 0, preventDefault() {} })
      })
    }
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    const despues = rotulos()
    expect(antes).toContain('2025')
    expect(despues).not.toContain('2025')                            // acercó: el principio ya no entra
    // El último día sigue a la vista, contra la derecha (no se fue para el costado).
    expect(parseFloat(ultimoPunto())).toBeGreaterThan(85)
    expect(parseFloat(ultimoPunto())).toBeLessThan(100)
  })
})

// El zoom en los extremos (Nico, 31/10): «cuando está lo más achicado posible y
// quiero agrandar, cuesta mucho: lo hago muchas veces y recién ahí empieza. Lo
// mismo cuando está agrandado del todo». Los gestos juntaban movimiento aunque el
// gráfico ya estuviera en el tope, y al darse vuelta primero había que devolver
// lo juntado. En el tope, un solo gesto para el otro lado ya tiene que mover.
describe('el zoom en los extremos responde igual que en el medio', () => {
  const area = () => porRol(montado.contenedor, 'img')
  const fechas = () => porTitulo(montado.contenedor, 'Arrastrá hacia los costados')
  // Lo que se ve en el tiempo: cada rótulo de la fila de fechas y dónde cae.
  const vistaFechas = () => fechas().childNodes.filter(n => n.nodeName === 'SPAN').map(n => `${texto(n)}@${n.style.left}`).join(' ')
  async function ruedita(deltaY, veces = 1) {
    for (let k = 0; k < veces; k++) {
      await enActo(async () => {
        for (const fn of area().escuchas.wheel || []) fn({ deltaY, deltaMode: 0, clientX: 0, preventDefault() {} })
      })
    }
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
  }
  const dedos = (d) => [{ clientX: 500 - d / 2, clientY: 100 }, { clientX: 500 + d / 2, clientY: 100 }]

  it('la ruedita: alejado del todo y de más, un paso para acercar ya acerca', async () => {
    await dibujar()
    await ruedita(100, 12)                                   // con «Todo» ya no se puede alejar más
    const antes = vistaFechas()
    await ruedita(-100)
    expect(vistaFechas()).not.toBe(antes)
  })

  it('la ruedita: acercado del todo y de más, un paso para alejar ya aleja', async () => {
    await dibujar()
    await ruedita(-100, 70)                                  // ~45 pasos llegan al tope; 25 de más
    const antes = vistaFechas()
    await ruedita(-100, 1)
    expect(vistaFechas()).toBe(antes)                        // de verdad está en el tope
    await ruedita(100)
    expect(vistaFechas()).not.toBe(antes)
  })

  it('pellizcar: abiertos los dedos del todo y de más, cerrarlos un poco ya aleja', async () => {
    await dibujar()
    await raton('touchstart', area(), { touches: dedos(100) })
    for (let d = 150; d <= 4000; d += 50) await raton('touchmove', area(), { touches: dedos(d) })
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    const antes = vistaFechas()
    await raton('touchmove', area(), { touches: dedos(3800) })
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(vistaFechas()).not.toBe(antes)
    await raton('touchend', area(), { touches: [] })
  })

  it('la fila de fechas: acercado del todo, arrastrar despacito para alejar ya aleja', async () => {
    await dibujar()
    await ruedita(-100, 70)
    const antes = vistaFechas()
    await puntero('pointerdown', fechas(), { pointerType: 'mouse', clientX: 100, clientY: 10 })
    for (let k = 1; k <= 6; k++) await puntero('pointermove', fechas(), { pointerType: 'mouse', clientX: 100 + 4 * k, clientY: 10 })
    await puntero('pointerup', fechas(), { pointerType: 'mouse', clientX: 124, clientY: 10 })
    for (let i = 0; i < 2; i++) await montado.redibujar(el())
    expect(vistaFechas()).not.toBe(antes)
  })

  it('la columna de precios: estirada hasta el tope y de más, volver un poco ya la cambia', async () => {
    await dibujar()
    const columna = porTitulo(montado.contenedor, 'Arrastrá hacia arriba o hacia abajo')
    const grilla = () => columna.childNodes.map(n => `${texto(n)}@${n.style?.top}`).join(' ')
    await puntero('pointerdown', columna, { pointerType: 'mouse', clientX: 10, clientY: 100 })
    for (let y = 150; y <= 1500; y += 50) await puntero('pointermove', columna, { pointerType: 'mouse', clientX: 10, clientY: y })
    const antes = grilla()
    await puntero('pointermove', columna, { pointerType: 'mouse', clientX: 10, clientY: 1460 })
    expect(grilla()).not.toBe(antes)
    await puntero('pointerup', columna, { pointerType: 'mouse', clientX: 10, clientY: 1460 })
  })
})
