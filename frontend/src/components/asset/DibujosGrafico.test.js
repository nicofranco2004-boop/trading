// Los dibujos a mano del gráfico, montados de verdad (testing/navegadorMinimo.js)
// con /api/tecnico simulado en la frontera, con clicks y toques sobre el
// gráfico como los manda el navegador:
//   · línea horizontal: un click a la altura del precio;
//   · línea de tendencia: dos clicks, también hacia adelante (el espacio vacío);
//   · se guardan en la CUENTA por activo y moneda (en todos los dispositivos) y
//     vuelven al volver a la ficha; lo borrado en otro dispositivo no revive;
//     si el guardado falla, lo dice y lo sube la próxima vez;
//   · quedan en su día con el zoom;
//   · tocar una línea la elige y se borra (botón o tecla); borrar todas pregunta antes.
// Las cuentas (dónde se guardan, el día de cada punto) están en utils/dibujos.test.js.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, enActo, medidas, clic, buscarBoton } from '../../testing/navegadorMinimo'
import { MemoryRouter } from 'react-router-dom'
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
      reaccion: { desde: puntos[600].d, hasta: puntos[601].d, pct: -4.21, cuando: 'al_otro_dia' } },
    { tipo: 'dividendo', fecha: puntos[610].d, monto: 0.26, moneda: 'usd',
      reaccion: { desde: puntos[609].d, hasta: puntos[610].d, pct: -0.4, cuando: 'ese_dia' } },
  ],
}

// La cuenta, del otro lado de la frontera: GET y PUT de /tecnico/ZZEV/dibujos
// guardan acá, por moneda. `cuenta.caida` = el guardado falla (sin conexión).
const cuenta = { usd: [], ars: [], caida: false, rechazo: null, puts: 0, alertas: [], pedidos: [] }
const monedaDe = (ruta) => (ruta.includes('moneda=ars') ? 'ars' : 'usd')
vi.mock('../../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => Promise.resolve(ruta.includes('/dibujos') ? { dibujos: cuenta[monedaDe(ruta)] }
      : ruta.startsWith('/alerts') ? { items: cuenta.alertas }
        : ruta.includes('/eventos') ? EVENTOS : DATOS)),
    // Las alertas (el aviso de tu línea): se anota lo que se pide.
    post: vi.fn((ruta, body) => { cuenta.pedidos.push(['POST', ruta, body]); return Promise.resolve({ ok: true, id: 7 }) }),
    patch: vi.fn((ruta, body) => { cuenta.pedidos.push(['PATCH', ruta, body]); return Promise.resolve({ ok: true }) }),
    put: vi.fn((ruta, body) => {
      cuenta.puts++
      if (cuenta.caida) return Promise.reject(new Error('sin conexión'))
      if (cuenta.rechazo) return Promise.reject(Object.assign(new Error('HTTP 400'), cuenta.rechazo))
      cuenta[monedaDe(ruta)] = body.dibujos
      return Promise.resolve({ ok: true })
    }),
  },
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
  localStorage.clear()   // lo que apaga una prueba no pasa a la siguiente
  Object.assign(cuenta, { usd: [], ars: [], caida: false, rechazo: null, puts: 0, alertas: [], pedidos: [] })
})
// Con el router: el «Te avisamos» de tu línea es un link a Mis alertas.
const el = () => h(MemoryRouter, null, h(LecturaTecnica, { asset: 'ZZEV', ...props }))
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
async function toqueEn(x, hastaX = x, y = 100) {
  const t = (cx) => ({ touches: [{ clientX: cx, clientY: y }], changedTouches: [{ clientX: cx, clientY: y }] })
  await evento('touchstart', grafico(), t(x))
  if (hastaX !== x) await evento('touchmove', grafico(), t(hastaX))
  const fin = await evento('touchend', grafico(), { touches: [], changedTouches: [{ clientX: hastaX, clientY: y }] })
  await redibujar()
  return fin
}
// Lo que se ve en 1A: los últimos 365 puntos (uno por día) más el aire vacío de
// la derecha (como TradingView): el ancho se reparte en LUGARES. El punto bajo
// x: round(x / 1000 × (lugares − 1)) dentro de lo que se ve.
const LUGARES = 365 + margenDerecho(365)
const bajo = (x) => 700 - 365 + Math.round((x / 1000) * (LUGARES - 1))
const status = () => todos(montado.contenedor, n => n.getAttribute?.('role') === 'status').map(n => texto(n)).join(' ')

const linea = () => todos(montado.contenedor, n => n.nodeName === 'LINE' && n.getAttribute?.('data-dibujo') != null)
const boton = (id) => todos(montado.contenedor, n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === id)[0]
// Lo que quedó guardado en la cuenta (el servidor simulado).
const guardados = (moneda = 'usd') => cuenta[moneda]
const copia = (moneda = 'usd') => JSON.parse(localStorage.getItem(`rendi_dibujos:ZZEV:${moneda}`) || 'null')
// El precio a una altura del gráfico (250 px de alto), con la escala que muestra:
// se lee del rótulo que la línea horizontal pone en la columna de precios.
const num = (t) => Number(t.replace(/\./g, '').replace(',', '.'))
// Fibonacci y Elliott a mano se eligen en el menú de su botón de la barra.
const MENU = { fibonacci: 'menu-fibonacci', extension: 'menu-fibonacci', impulso: 'menu-elliott', correccion: 'menu-elliott' }
async function usar(id) {
  if (MENU[id]) { await clic(montado.contenedor, boton(MENU[id])); await redibujar() }
  await clic(montado.contenedor, boton(id)); await redibujar()
}

describe('línea horizontal', () => {
  it('un click a una altura: la línea de borde a borde, su precio a la derecha, guardada; la herramienta se apaga', async () => {
    await dibujar()
    await usar('horizontal')
    expect(boton('horizontal').getAttribute('aria-pressed')).toBe('true')
    expect(status()).toContain('Tocá la altura del gráfico (el precio) donde va la línea horizontal.')
    await clickEn(400, 100)
    const [l] = linea()
    expect(l.getAttribute('x1')).toBe('0')
    expect(l.getAttribute('x2')).toBe('100')
    expect(Number(l.getAttribute('y1'))).toBeCloseTo(40, 2)           // 100 de 250 px = 40 %
    const g = guardados()
    expect(g).toHaveLength(1)
    expect(g[0].tipo).toBe('horizontal')
    // Su precio, en la columna de la derecha, es el que se guardó.
    const rotulo = todos(montado.contenedor, n => n.nodeName === 'SPAN' && n.style?.top === `${l.getAttribute('y1')}%`
      && /^[\d.]+,\d+$/.test(texto(n)))
    expect(rotulo).toHaveLength(1)
    expect(num(texto(rotulo[0]))).toBeCloseTo(g[0].precio, 2)
    expect(boton('horizontal').getAttribute('aria-pressed')).toBe('false')   // una línea por vez
    // Otro click ya no dibuja: vuelve a ser mirar el gráfico.
    await clickEn(600, 200)
    expect(linea()).toHaveLength(1)
  })
})

describe('línea de tendencia', () => {
  it('dos clicks: de un punto al otro, por día y precio; el segundo puede ir hacia adelante', async () => {
    await dibujar()
    await usar('tendencia')
    expect(status()).toContain('Tocá donde empieza la línea de tendencia.')
    await clickEn(200, 180)
    expect(status()).toContain('Ahora tocá donde termina la línea')
    expect(linea()).toHaveLength(0)
    // Mientras tanto, la línea sigue al mouse.
    await evento('mousemove', grafico(), { clientX: 700, clientY: 60 }); await redibujar()
    expect(todos(montado.contenedor, n => n.nodeName === 'LINE' && n.getAttribute?.('stroke-dasharray') === '5 4'
      && n.getAttribute?.('stroke') === 'rgb(var(--data-cyan))')).toHaveLength(1)
    await clickEn(995, 40)                                     // el espacio vacío de la derecha
    const [l] = linea()
    const pctX = (x) => (bajo(x) - (700 - 365)) / (LUGARES - 1) * 100
    expect(Number(l.getAttribute('x1'))).toBeCloseTo(pctX(200), 6)
    expect(Number(l.getAttribute('x2'))).toBeCloseTo(pctX(995), 6)
    expect(Number(l.getAttribute('y1'))).toBeCloseTo(72, 2)    // 180 de 250 px
    expect(Number(l.getAttribute('y2'))).toBeCloseTo(16, 2)
    const [t] = guardados()
    expect(t.a).toMatchObject({ d: puntos[bajo(200)].d, mas: 0 })
    expect(t.b).toMatchObject({ d: puntos[699].d, mas: bajo(995) - 699 })
    expect(t.b.precio).toBeGreaterThan(t.a.precio)
  })

  it('se guarda por activo y moneda: vuelve al volver, no aparece en pesos', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(200, 180); await clickEn(800, 60)
    await usar('horizontal'); await clickEn(500, 120)
    expect(linea()).toHaveLength(2)
    await montado.desmontar()
    await dibujar()                                            // otra visita
    expect(linea()).toHaveLength(2)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Pesos')); await redibujar(); await redibujar()
    expect(linea()).toHaveLength(0)
    expect(boton('borrarDibujos').getAttribute('aria-disabled')).toBe('true')
  })

  it('con el zoom, la línea sigue en sus días', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(700, 180); await clickEn(900, 60)
    const [t] = guardados()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, '3M')); await redibujar()
    // 3M: los últimos 91 días más su aire.
    const lug = 91 + margenDerecho(91)
    const enX = (d) => ((puntos.findIndex(p => p.d === d) - (700 - 91)) / (lug - 1)) * 100
    const [l] = linea()
    expect(Number(l.getAttribute('x1'))).toBeCloseTo(enX(t.a.d), 6)
    expect(Number(l.getAttribute('x2'))).toBeCloseTo(enX(t.b.d), 6)
  })
})

describe('elegir y borrar', () => {
  it('un click sobre la línea la elige; «Borrar esta línea» la saca del gráfico y de lo guardado', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    await usar('horizontal'); await clickEn(500, 200)
    expect(linea()).toHaveLength(2)
    await clickEn(300, 103)                                    // a 3 px de la primera
    expect(status()).toContain('Línea horizontal seleccionada.')
    expect(linea().map(n => n.getAttribute('stroke-width'))).toEqual(['3', '1.8'])
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Borrar esta línea')); await redibujar()
    expect(linea()).toHaveLength(1)
    expect(Number(linea()[0].getAttribute('y1'))).toBeCloseTo(80, 2)   // quedó la otra
    expect(guardados()).toHaveLength(1)
  })

  it('con el mouse encima de un dibujo aparece la manito (y la línea se marca); en un lugar vacío, la cruz', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    const clase = () => grafico().getAttribute('class')
    const ancho = () => linea()[0].getAttribute('stroke-width')
    await evento('mousemove', grafico(), { clientX: 300, clientY: 104 }); await redibujar()   // a 4 px de la línea
    expect(clase()).toContain('cursor-pointer')
    expect(clase()).not.toContain('cursor-crosshair')
    expect(ancho()).toBe('2.6')
    await evento('mousemove', grafico(), { clientX: 300, clientY: 180 }); await redibujar()   // lejos
    expect(clase()).toContain('cursor-crosshair')
    expect(ancho()).toBe('1.8')
    // Con una herramienta prendida, encima de un dibujo es para dibujar: la cruz.
    await usar('tendencia')
    await evento('mousemove', grafico(), { clientX: 300, clientY: 104 }); await redibujar()
    expect(clase()).toContain('cursor-crosshair')
    // Y al salir del gráfico, nada queda marcado.
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Cancelar')); await redibujar()
    await evento('mousemove', grafico(), { clientX: 300, clientY: 104 }); await redibujar()
    // React arma «onMouseLeave» con el «mouseout» del navegador (hacia afuera: sin destino).
    await evento('mouseout', grafico(), { relatedTarget: null }); await redibujar()
    expect(clase()).toContain('cursor-crosshair')
  })

  it('un click lejos de todas suelta la elegida; la tecla Suprimir la borra', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(200, 200); await clickEn(800, 50)
    // A mitad de camino, sobre la línea: x 500 → y 125.
    await clickEn(500, 128)
    expect(status()).toContain('Línea de tendencia seleccionada.')
    await clickEn(500, 20)
    expect(status()).not.toContain('elegida')
    await clickEn(500, 122)
    await enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Delete' })) })
    await redibujar()
    expect(linea()).toHaveLength(0)
    expect(guardados()).toEqual([])
  })

  it('con el dedo hace falta acertarle menos', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    await toqueEn(300, 300, 112)                              // a 12 px: con el mouse no alcanzaría
    expect(status()).toContain('Línea horizontal seleccionada.')
  })

  it('«Borrar mis dibujos» pregunta antes; «No» no borra nada', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    await usar('tendencia'); await clickEn(200, 200); await clickEn(800, 50)
    await usar('borrarDibujos')
    expect(status()).toContain('¿Borrar tus 2 dibujos de este activo en dólares? No se puede deshacer.')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'No')); await redibujar()
    expect(linea()).toHaveLength(2)
    await usar('borrarDibujos')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Sí, borrar')); await redibujar()
    expect(linea()).toHaveLength(0)
    expect(guardados()).toEqual([])
    expect(boton('borrarDibujos').getAttribute('aria-disabled')).toBe('true')
  })

  it('una herramienta por vez: elegir dibujar apaga medir, y al revés', async () => {
    await dibujar()
    await usar('medir')
    await usar('tendencia')
    expect(boton('medir').getAttribute('aria-pressed')).toBe('false')
    expect(boton('tendencia').getAttribute('aria-pressed')).toBe('true')
    await usar('medir')
    expect(boton('tendencia').getAttribute('aria-pressed')).toBe('false')
  })
})

describe('mover y corregir un dibujo ya hecho (Nico, 28/10)', () => {
  async function arrastrar(x0, y0, x1, y1, { soltar = true } = {}) {
    await evento('mousedown', grafico(), { clientX: x0, clientY: y0 })
    await evento('mousemove', grafico(), { clientX: (x0 + x1) / 2, clientY: (y0 + y1) / 2 })
    await evento('mousemove', grafico(), { clientX: x1, clientY: y1 })
    if (soltar) await evento('mouseup', grafico(), { clientX: x1, clientY: y1 })
    await redibujar()
  }
  const dk = (dx) => Math.round((dx / 1000) * (LUGARES - 1))

  it('una horizontal se arrastra a otro precio; mientras se arrastra no se guarda ni se mueve el gráfico', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    const [antes] = guardados()
    const fechas = () => todos(montado.contenedor, n => n.getAttribute?.('title')?.startsWith('Arrastrá hacia los costados'))[0]
    const mesesAntes = texto(fechas())
    await arrastrar(300, 100, 700, 150, { soltar: false })
    expect(Number(linea()[0].getAttribute('y1'))).toBeCloseTo(60, 1)   // 150 de 250 px, ya corrida
    expect(guardados()[0].precio).toBe(antes.precio)                  // todavía no se soltó
    expect(grafico().getAttribute('class')).toContain('cursor-grabbing')
    await evento('mouseup', grafico(), { clientX: 700, clientY: 150 }); await redibujar()
    expect(guardados()[0].precio).toBeLessThan(antes.precio)
    expect(Number(linea()[0].getAttribute('y1'))).toBeCloseTo(60, 1)
    expect(texto(fechas())).toBe(mesesAntes)                          // el gráfico no se corrió
    expect(status()).toContain('Línea horizontal seleccionada.')           // queda elegida, como TradingView
  })

  it('agarrada de una punta, se corre esa punta sola', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(200, 200); await clickEn(800, 50)
    const [antes] = guardados()
    await arrastrar(802, 52, 902, 30)
    const [t] = guardados()
    expect(t.a).toEqual(antes.a)
    expect(t.b).toMatchObject({ d: puntos[bajo(800) + dk(100)].d, mas: 0 })
    expect(t.b.precio).toBeGreaterThan(antes.b.precio)
  })

  it('agarrada del medio, se mueve entera: los dos puntos los mismos días y el mismo precio de más', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(200, 200); await clickEn(800, 50)
    const [antes] = guardados()
    await arrastrar(500, 125, 600, 125)
    const [t] = guardados()
    expect(t.a).toMatchObject({ d: puntos[bajo(200) + dk(100)].d, mas: 0, precio: antes.a.precio })
    expect(t.b).toMatchObject({ d: puntos[bajo(800) + dk(100)].d, mas: 0, precio: antes.b.precio })
    // Hacia adelante, más allá del último día: cuenta días de mercado después de hoy.
    await arrastrar(600, 125, 900, 125)
    expect(guardados()[0].b).toMatchObject({ d: puntos[699].d, mas: bajo(800) + dk(100) + dk(300) - 699 })
  })

  it('arrastrar lejos de tus dibujos mueve el gráfico, no la línea', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(200, 200); await clickEn(800, 50)
    const [antes] = guardados()
    const x = Number(linea()[0].getAttribute('x1'))
    await arrastrar(300, 230, 500, 230)                               // lejos de tu línea
    expect(guardados()[0]).toEqual(antes)
    expect(Number(linea()[0].getAttribute('x1'))).toBeGreaterThan(x)  // el gráfico fue para atrás
    expect(status()).not.toContain('elegida')
  })

  it('con el dedo sólo se arrastra la elegida (si no, deslizar la página agarraría líneas)', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    const [antes] = guardados()
    const t = (cx, cy) => ({ touches: [{ clientX: cx, clientY: cy }], changedTouches: [{ clientX: cx, clientY: cy }] })
    const quieta = async (cx, cy) => {
      let prevenido = false
      await enActo(async () => {
        for (const fn of grafico().escuchas.touchmove || []) fn({ ...t(cx, cy), cancelable: true, preventDefault() { prevenido = true } })
      })
      return prevenido
    }
    const deslizar = async () => {
      await evento('touchstart', grafico(), t(300, 100))
      const prevenido = await quieta(300, 150)
      await evento('touchmove', grafico(), t(300, 150))
      await evento('touchend', grafico(), { touches: [], changedTouches: [{ clientX: 300, clientY: 150 }] })
      await redibujar()
      return prevenido
    }
    expect(await deslizar()).toBe(false)                            // sin elegir: la página se mueve
    expect(guardados()[0].precio).toBe(antes.precio)
    await toqueEn(300, 300, 100)                                      // la elige
    expect(status()).toContain('Línea horizontal seleccionada.')
    expect(await deslizar()).toBe(true)                              // elegida: la página queda quieta
    expect(guardados()[0].precio).toBeLessThan(antes.precio)
    expect(Number(linea()[0].getAttribute('y1'))).toBeCloseTo(60, 1)
  })
})

describe('avisarte cuando el precio toca tu línea (Nico, 28/10)', () => {
  const avisoDe = (id, tipo = 'horizontal') => ({ id: 7, kind: 'tecnica', senal: 'linea', active: 1, symbol: 'ZZEV',
    currency: 'USD', dibujo: JSON.stringify({ asset: 'ZZEV', moneda: 'usd', id, tipo }) })

  it('la línea elegida ofrece «Avisame si la toca»; el formulario manda cuál línea es', async () => {
    // El formulario pregunta por el tamaño de pantalla (el navegador de prueba no lo trae).
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
    window.matchMedia = globalThis.matchMedia
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    await clickEn(300, 101)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Avisame si la toca')); await redibujar()
    const t = texto(montado.contenedor)
    expect(t).toContain('Toque tu línea horizontal')
    expect(t).toContain('Te avisamos cuando ZZEV toque tu línea horizontal.')
    expect(t).not.toContain('Su impulso (RSI) baje de 30')          // no es la lista de señales
    // «Crear aviso»: el navegador manda el «submit» del formulario.
    await evento('submit', todos(montado.contenedor, n => n.nodeName === 'FORM')[0]); await redibujar()
    const [[, ruta, body]] = cuenta.pedidos
    expect(ruta).toBe('/alerts')
    expect(body).toMatchObject({ kind: 'tecnica', senal: 'linea', symbol: 'ZZEV', currency: 'USD',
      dibujo: guardados()[0].id, repeat: 'once' })
  })

  it('con el aviso puesto dice «Te avisamos»; borrar la línea apaga su aviso', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    cuenta.alertas = [avisoDe(guardados()[0].id)]
    await montado.desmontar(); await dibujar()                     // vuelve con el aviso ya puesto
    await clickEn(300, 101)
    expect(texto(montado.contenedor)).toContain('Te avisamos si la toca')
    expect(buscarBoton(montado.contenedor, 'Avisame si la toca')).toBeFalsy()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Borrar esta línea')); await redibujar()
    expect(cuenta.pedidos).toEqual([['PATCH', '/alerts/7', { active: false }]])
  })

  it('un Fibonacci no ofrece aviso; una de tendencia con aviso se ve seguir hacia la derecha', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(200, 200); await clickEn(600, 100)
    expect(linea()).toHaveLength(1)
    cuenta.alertas = [avisoDe(guardados()[0].id, 'tendencia')]
    await montado.desmontar(); await dibujar()
    const ls = linea()
    expect(ls).toHaveLength(2)                                        // la línea y su continuación
    expect(Number(ls[1].getAttribute('x2'))).toBe(100)
    expect(ls[1].getAttribute('stroke-dasharray')).toBe('5 4')
    // Sigue en la misma dirección: sube 100 px cada 400 → en el borde, 100 px más arriba.
    expect(Number(ls[1].getAttribute('y2'))).toBeLessThan(Number(ls[1].getAttribute('y1')))
    await usar('fibonacci'); await clickEn(200, 220); await clickEn(400, 60)
    await clickEn(300, 140)
    expect(status()).toContain('Fibonacci seleccionado.')
    expect(buscarBoton(montado.contenedor, 'Avisame si la toca')).toBeFalsy()
  })
})

describe('pellizcar para acercar, en el celular (Nico, 28/10)', () => {
  it('abrir los dedos acerca con el último día quieto; cerrarlos aleja; la página no hace zoom', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(200, 200); await clickEn(800, 50)
    const x1 = () => Number(linea()[0].getAttribute('x1'))
    const antes = x1()
    const dedos = (sep) => ({ touches: [{ clientX: 500 - sep / 2, clientY: 100 }, { clientX: 500 + sep / 2, clientY: 100 }] })
    await evento('touchstart', grafico(), dedos(100))
    let prevenido = false
    await enActo(async () => {
      for (const fn of grafico().escuchas.touchmove || []) fn({ ...dedos(200), cancelable: true, preventDefault() { prevenido = true } })
    })
    expect(prevenido).toBe(true)
    for (const sep of [140, 200]) await evento('touchmove', grafico(), dedos(sep))
    await evento('touchend', grafico(), { touches: [dedos(200).touches[0]], changedTouches: [] })
    await redibujar()
    expect(x1()).toBeLessThan(antes)                                   // más cerca: el punto se va a la izquierda
    expect(guardados()).toHaveLength(1)                                // pellizcar no dibuja ni mueve nada
    const acercado = x1()
    await evento('touchstart', grafico(), dedos(200))
    for (const sep of [150, 100]) await evento('touchmove', grafico(), dedos(sep))
    await evento('touchend', grafico(), { touches: [], changedTouches: [] })
    await redibujar()
    expect(x1()).toBeGreaterThan(acercado)                             // alejó
  })
})

describe('en todos tus dispositivos', () => {
  const H = { id: 'h1', tipo: 'horizontal', precio: 150 }

  it('lo dibujado en otro dispositivo aparece (está en la cuenta, no en este navegador)', async () => {
    cuenta.usd = [H]
    await dibujar()
    expect(linea()).toHaveLength(1)
    expect(copia()).toEqual({ pendiente: false, dibujos: [H] })   // queda la copia, ya en la cuenta
  })

  it('lo borrado en otro dispositivo no revive desde la copia de este navegador', async () => {
    localStorage.setItem('rendi_dibujos:ZZEV:usd', JSON.stringify({ pendiente: false, dibujos: [H] }))
    cuenta.usd = []
    await dibujar()
    expect(linea()).toHaveLength(0)
    expect(cuenta.puts).toBe(0)
    expect(copia()).toBeNull()
  })

  it('una copia de formato viejo (la lista sola) no revive dibujos: la cuenta manda (auditoría C, 29/10)', async () => {
    // Como después de un reset: la cuenta vacía y, en este navegador, una copia
    // de antes del guardado en la cuenta. Esa versión nunca se publicó: ningún
    // usuario tiene una copia así que haga falta subir.
    localStorage.setItem('rendi_dibujos:ZZEV:usd', JSON.stringify([H]))
    cuenta.usd = []
    await dibujar()
    expect(linea()).toHaveLength(0)
    expect(cuenta.puts).toBe(0)
  })

  it('si la cuenta RECHAZA el guardado, dice el motivo que mandó el servidor (re-test E3)', async () => {
    cuenta.rechazo = { status: 400, payload: { detail: 'Ya dibujaste en 200 gráficos.' } }
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    expect(linea()).toHaveLength(1)
    expect(texto(montado.contenedor)).toContain('Tus dibujos quedaron sólo en este navegador. Ya dibujaste en 200 gráficos.')
    expect(texto(montado.contenedor)).not.toContain('No se pudieron guardar')
    expect(copia().pendiente).toBe(true)
  })

  it('si el guardado falla, lo dice, queda pendiente y se sube al volver', async () => {
    cuenta.caida = true
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    expect(linea()).toHaveLength(1)
    expect(texto(montado.contenedor)).toContain('No se pudieron guardar tus dibujos en tu cuenta: por ahora quedaron en este navegador.')
    expect(guardados()).toEqual([])
    expect(copia().pendiente).toBe(true)
    await montado.desmontar()
    cuenta.caida = false
    await dibujar()                                                          // otra visita, con conexión
    expect(guardados()).toHaveLength(1)
    expect(copia().pendiente).toBe(false)
    expect(linea()).toHaveLength(1)
  })
})

describe('Fibonacci y Elliott a mano (Nico, 28/10: «poder calcularlo como ellos estiman»)', () => {
  const capas = () => JSON.parse(localStorage.getItem('rendi_grafico_capas') || '{}')
  const rotulos = () => todos(montado.contenedor, n => n.nodeName === 'SPAN' && n.getAttribute?.('data-rotulo') != null).map(n => texto(n))

  it('un solo botón para cada uno, con su menú: «Automático» o «A mano» (Nico, 28/10)', async () => {
    await dibujar()
    expect(boton('fib')).toBeFalsy()                            // cerrado, no se ve nada más que el botón
    expect(texto(boton('menu-fibonacci'))).toContain('Fibonacci')
    expect(boton('menu-fibonacci').getAttribute('aria-haspopup')).toBe('menu')
    await clic(montado.contenedor, boton('menu-fibonacci')); await redibujar()
    expect(boton('menu-fibonacci').getAttribute('aria-expanded')).toBe('true')
    const menu = todos(montado.contenedor, n => n.getAttribute?.('role') === 'menu')[0]
    expect(texto(menu)).toContain('Automático')
    expect(texto(menu)).toContain('Retroceso a mano')
    expect(texto(menu)).toContain('Extensión a mano')
    expect(boton('fib').getAttribute('role')).toBe('menuitemcheckbox')
    expect(boton('fibonacci').getAttribute('role')).toBe('menuitem')
    // Esc lo cierra; elegir una opción también.
    await enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape' })) }); await redibujar()
    expect(boton('fib')).toBeFalsy()
    await usar('impulso')
    expect(todos(montado.contenedor, n => n.getAttribute?.('role') === 'menu')).toHaveLength(0)
    expect(status()).toContain('Impulso: tocá el arranque (el 0)')
  })

  it('la barra del costado tiene sólo las herramientas; los indicadores van en su lista y línea/velas arriba', async () => {
    await dibujar()
    const barra = todos(montado.contenedor, n => n.getAttribute?.('role') === 'toolbar')[0]
    const enLaBarra = todos(barra, n => n.nodeName === 'BUTTON').map(n => n.getAttribute('data-capa'))
    expect(enLaBarra).toEqual(['tendencia', 'horizontal', 'menu-fibonacci', 'menu-elliott', 'medir', 'borrarDibujos'])
    const lista = todos(montado.contenedor, n => n.getAttribute?.('role') === 'group' && n.getAttribute('aria-label') === 'Indicadores')[0]
    const enLaLista = todos(lista, n => n.nodeName === 'BUTTON').map(n => n.getAttribute('data-capa')).filter(Boolean)
    expect(enLaLista).toEqual(['vol', 's200', 's50', 'bb', 'rsi', 'fuerza', 'eventos', 'globo', 'fabrica'])
    const tipo = todos(montado.contenedor, n => n.getAttribute?.('aria-label') === 'Tipo de gráfico')[0]
    expect(todos(tipo, n => n.nodeName === 'BUTTON').map(n => n.getAttribute('data-capa'))).toEqual(['linea', 'velas'])
  })

  it('en un gráfico angosto (el celular) la lista arranca plegada, para no tapar el gráfico', async () => {
    globalThis.ResizeObserver = class { constructor(cb) { this.cb = cb } observe() { this.cb([{ contentRect: { width: 300 } }]) } disconnect() {} }
    try {
      await dibujar()
      expect(buscarBoton(montado.contenedor, 'Indicadores').getAttribute('aria-expanded')).toBe('false')
      expect(boton('vol')).toBeFalsy()
    } finally {
      delete globalThis.ResizeObserver
    }
  })

  it('el cartel con los datos al pasar el mouse se oculta con su ojito, como un indicador más (Nico, 28/10)', async () => {
    await dibujar()
    const globo = () => todos(montado.contenedor, n => n.getAttribute?.('data-globo') != null)
    await evento('mousemove', grafico(), { clientX: 400, clientY: 120 }); await redibujar()
    expect(globo()).toHaveLength(1)
    expect(texto(globo()[0])).toMatch(/US\$ [\d.,]+/)
    await clic(montado.contenedor, boton('globo')); await redibujar()
    await evento('mousemove', grafico(), { clientX: 420, clientY: 120 }); await redibujar()
    expect(globo()).toHaveLength(0)
    // La raya del día sigue (para saber dónde estás), sólo se va el cartel.
    expect(todos(montado.contenedor, n => n.nodeName === 'DIV' && (n.getAttribute?.('class') || '').includes('inset-y-0 w-px'))).not.toHaveLength(0)
    // Y se acuerda, como los demás.
    expect(JSON.parse(localStorage.getItem('rendi_grafico_capas')).globo).toBe(false)
  })

  it('la lista de indicadores se pliega a un renglón y se acuerda', async () => {
    await dibujar()
    const plegar = () => buscarBoton(montado.contenedor, 'Indicadores')
    expect(plegar().getAttribute('aria-expanded')).toBe('true')
    expect(texto(plegar())).toMatch(/· \d+ de \d+/)
    await clic(montado.contenedor, plegar()); await redibujar()
    expect(boton('vol')).toBeFalsy()
    expect(localStorage.getItem('rendi_grafico_leyenda')).toBe('cerrada')
    await montado.desmontar()
    await dibujar()
    expect(plegar().getAttribute('aria-expanded')).toBe('false')
  })

  it('tu Fibonacci: dos toques (arranque y final del tramo), los niveles con su precio, guardado; apaga el automático', async () => {
    await dibujar()
    await usar('fibonacci')
    expect(status()).toContain('Retroceso: tocá donde empieza el tramo que querés medir')
    await clickEn(300, 200)                                    // el pozo
    expect(status()).toContain('Ahora tocá donde termina el tramo')
    await clickEn(800, 50)                                     // el pico
    const [f] = guardados()
    expect(f.tipo).toBe('fibonacci')
    expect(f.a).toMatchObject({ d: puntos[bajo(300)].d, mas: 0 })
    expect(f.b).toMatchObject({ d: puntos[bajo(800)].d, mas: 0 })
    // Los niveles: la misma cuenta que el automático, con el precio de cada uno.
    const precio618 = f.b.precio - 0.618 * (f.b.precio - f.a.precio)
    const r = rotulos().find(t => t.startsWith('61,8 % · '))
    expect(r).toBeTruthy()
    expect(num(r.replace('61,8 % · US$ ', ''))).toBeCloseTo(precio618, 1)
    expect(rotulos().some(t => t.startsWith('Pico · '))).toBe(true)
    expect(rotulos().some(t => t.startsWith('Arranque · '))).toBe(true)
    expect(capas().fib).toBe(false)                            // el automático, apagado (se prende de nuevo desde la barra)
    expect(texto(boton('menu-fibonacci'))).not.toContain('Marcando a mano')   // la herramienta se apagó al terminar
  })

  it('cancelar a mitad de camino no apaga el automático ni guarda nada', async () => {
    await dibujar()
    await usar('fibonacci'); await clickEn(300, 200)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Cancelar')); await redibujar()
    expect(guardados()).toEqual([])
    expect(capas().fib).not.toBe(false)
  })

  it('tu impulso de Elliott: un toque por onda, «Terminar acá» cuando quieras; apaga el automático', async () => {
    await dibujar()
    await usar('impulso')
    expect(status()).toContain('Impulso: tocá el arranque (el 0)')
    await clickEn(100, 220)
    expect(status()).not.toContain('Terminar acá')              // con el 0 solo no hay conteo
    await clickEn(250, 120)
    expect(status()).toContain('Ahora tocá la onda 2')
    await clickEn(350, 170)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Terminar acá')); await redibujar()
    const [e] = guardados()
    expect(e.tipo).toBe('elliott')
    expect(e.forma).toBe('impulso')
    expect(e.puntos.map(q => q.d)).toEqual([bajo(100), bajo(250), bajo(350)].map(i => puntos[i].d))
    expect(rotulos().filter(t => /^[0-5ABC]$/.test(t))).toEqual(['0', '1', '2'])
    expect(capas().ell).toBe(false)
  })

  it('el impulso se termina solo en la 5, y la corrección A-B-C es otra herramienta, aparte (Nico, 28/10)', async () => {
    await dibujar()
    await usar('impulso')
    for (let k = 0; k < 6; k++) await clickEn(100 + k * 60, k % 2 ? 80 : 200)
    expect(texto(boton('menu-elliott'))).not.toContain('Contando a mano')     // terminó solo
    await usar('correccion')
    expect(status()).toContain('Corrección: tocá dónde arranca y después las ondas A, B y C.')
    for (let k = 0; k < 4; k++) await clickEn(500 + k * 100, k % 2 ? 210 : 90)
    const [imp, cor] = guardados()
    expect(imp).toMatchObject({ tipo: 'elliott', forma: 'impulso' })
    expect(imp.puntos).toHaveLength(6)
    expect(cor).toMatchObject({ tipo: 'elliott', forma: 'correccion' })
    expect(cor.puntos).toHaveLength(4)
    // El impulso dice 0 a 5; la corrección, A, B y C (el arranque es un punto, sin número).
    expect(rotulos().filter(t => /^[0-5ABC]$/.test(t))).toEqual(['0', '1', '2', '3', '4', '5', 'A', 'B', 'C'])
  })

  it('la extensión de Fibonacci: tres toques y los niveles hacia adelante desde el tercero', async () => {
    await dibujar()
    await usar('extension')
    expect(status()).toContain('Extensión: tocá donde empieza el movimiento')
    // Un movimiento chico, para que los niveles (hasta 261,8 %) entren en el gráfico.
    await clickEn(200, 210)                                    // arranca la suba
    expect(status()).toContain('Ahora tocá donde termina el movimiento')
    await clickEn(400, 170)                                    // termina
    expect(status()).toContain('Ahora tocá donde terminó el retroceso')
    await clickEn(550, 195)                                    // termina el retroceso
    const [x] = guardados()
    expect(x.tipo).toBe('extension')
    const medida = x.b.precio - x.a.precio
    const r1618 = rotulos().find(t => t.startsWith('161,8 % · '))
    expect(r1618).toBeTruthy()
    expect(num(r1618.replace('161,8 % · US$ ', ''))).toBeCloseTo(x.c.precio + 1.618 * medida, 1)
    expect(rotulos().some(t => t.startsWith('100 % · '))).toBe(true)
    expect(capas().fib).not.toBe(false)                        // la extensión no apaga el automático
  })

  it('Esc cancela lo que se está dibujando, como en TradingView', async () => {
    await dibujar()
    await usar('impulso')
    await clickEn(100, 220); await clickEn(250, 120)
    await enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape' })) }); await redibujar()
    expect(guardados()).toEqual([])
    expect(status()).not.toContain('Ahora tocá la onda')
    expect(texto(boton('menu-elliott'))).not.toContain('Contando a mano')
    // Y mientras se mide, también.
    await usar('medir'); await clickEn(300, 100)
    await enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape' })) }); await redibujar()
    expect(boton('medir').getAttribute('aria-pressed')).toBe('false')
  })

  it('doble click termina el conteo ahí (sin repetir la onda del doble click)', async () => {
    await dibujar()
    await usar('impulso')
    await clickEn(100, 220); await clickEn(250, 120); await clickEn(350, 170)
    // El doble click en la onda 3: dos clicks en el mismo lugar y el «dblclick».
    await clickEn(450, 60); await clickEn(450, 60)
    await evento('dblclick', grafico(), { clientX: 450, clientY: 60 }); await redibujar()
    const [e] = guardados()
    expect(e.puntos).toHaveLength(4)                          // 0, 1, 2 y 3: la 3 una sola vez
    expect(rotulos().filter(t => /^[0-5]$/.test(t))).toEqual(['0', '1', '2', '3'])
  })

  it('click derecho también termina el conteo, sin marcar una onda ni abrir el menú del navegador', async () => {
    await dibujar()
    await usar('correccion')
    await clickEn(100, 80); await clickEn(250, 200); await clickEn(350, 120)
    await evento('mousedown', grafico(), { clientX: 600, clientY: 100, button: 2 })
    await evento('mouseup', grafico(), { clientX: 600, clientY: 100, button: 2 })
    const menu = await evento('contextmenu', grafico(), { clientX: 600, clientY: 100, button: 2 }); await redibujar()
    expect(menu.defaultPrevented).toBe(true)
    const [e] = guardados()
    expect(e).toMatchObject({ forma: 'correccion' })
    expect(e.puntos).toHaveLength(3)                          // el arranque, A y B
  })

  it('tocar uno de tus niveles elige tu Fibonacci y se borra entero', async () => {
    await dibujar()
    await usar('fibonacci'); await clickEn(300, 200); await clickEn(800, 50)
    // El nivel del 50 %: a mitad de altura entre los dos toques.
    await clickEn(900, 125)
    expect(status()).toContain('Fibonacci seleccionado.')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Borrar este Fibonacci')); await redibujar()
    expect(guardados()).toEqual([])
    expect(rotulos().some(t => t.startsWith('61,8 %'))).toBe(false)
  })
})
