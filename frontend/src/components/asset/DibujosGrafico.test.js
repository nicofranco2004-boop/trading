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
import { describe, it, expect, vi, beforeAll, afterAll, beforeEach, afterEach } from 'vitest'
import { CAPAS_TODAS } from './BarraGrafico'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, enActo, medidas, clic, buscarBoton } from '../../testing/navegadorMinimo'
import { elegirEnLaVista, opcionesDeLaVista, pasarATodo, periodoElegido } from '../../testing/menuGrafico'
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
const cuenta = { usd: [], ars: [], caida: false, rechazo: null, puts: 0, alertas: [], pedidos: [], subidas: [], puerta: null }
const monedaDe = (ruta) => (ruta.includes('moneda=ars') ? 'ars' : 'usd')
// Quién está del otro lado, como lo ve el servidor de verdad: la persona de la
// cookie (acá, la sesión que la app guarda en `rendi_user`) y el cliente que el
// asesor tiene abierto (el encabezado de api.js, acá `sesion.cliente`).
const sesion = { cliente: null }
const ANA = { name: 'Ana', email: 'ana@prueba.test' }
const BRUNO = { name: 'Bruno', email: 'bruno@prueba.test' }
const entrar = (u) => localStorage.setItem('rendi_user', JSON.stringify(u))
const logueado = () => { try { return JSON.parse(localStorage.getItem('rendi_user'))?.email ?? null } catch { return null } }
vi.mock('../../utils/api', () => ({
  getClientContext: () => (sesion.cliente != null ? { id: sesion.cliente, label: '' } : null),
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
  api: {
    // `cuenta.puerta`: los dibujos de la cuenta tardan hasta que la prueba la abre.
    get: vi.fn((ruta) => (ruta.includes('/dibujos') ? (cuenta.puerta || Promise.resolve()).then(() => ({ dibujos: cuenta[monedaDe(ruta)] }))
      : Promise.resolve(ruta.startsWith('/alerts') ? { items: cuenta.alertas }
        : ruta.includes('/eventos') ? EVENTOS : DATOS))),
    // Las alertas (el aviso de tu línea): se anota lo que se pide.
    post: vi.fn((ruta, body) => { cuenta.pedidos.push(['POST', ruta, body]); return Promise.resolve({ ok: true, id: 7 }) }),
    patch: vi.fn((ruta, body) => { cuenta.pedidos.push(['PATCH', ruta, body]); return Promise.resolve({ ok: true }) }),
    put: vi.fn((ruta, body) => {
      cuenta.puts++
      if (cuenta.caida) return Promise.reject(new Error('sin conexión'))
      if (cuenta.rechazo) return Promise.reject(Object.assign(new Error('HTTP 400'), cuenta.rechazo))
      // Lo que quedó guardado, y en la cuenta de quién (el de la cookie y el cliente).
      cuenta.subidas.push({ quien: logueado(), cliente: sesion.cliente, dibujos: body.dibujos })
      cuenta[monedaDe(ruta)] = body.dibujos
      return Promise.resolve({ ok: true })
    }),
  },
}))

let LecturaTecnica, copiaLocal, guardarDibujos, duenoDeLaPestana
beforeAll(async () => {
  instalarNavegadorMinimo()
  medidas(() => ({ left: 0, top: 0, width: 1000, height: 250, right: 1000, bottom: 250 }))
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
  ;({ copiaLocal, guardarDibujos } = await import('../../utils/dibujos'))
  ;({ duenoDeLaPestana } = await import('../../utils/duenoDeLaPestana'))
})
afterAll(() => { medidas(null); vi.unstubAllGlobals() })

let montado, props
// Ana logueada en su cuenta. De fábrica el gráfico viene limpio (precio,
// promedio de 200 y volumen); estas pruebas miran las demás capas: arrancan con
// todas prendidas, como quien las prende desde «Indicadores».
beforeEach(() => {
  entrar(ANA); sesion.cliente = null
  try { localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS)) } catch { /* sin almacenamiento */ }
})
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()   // lo que apaga una prueba no pasa a la siguiente
  Object.assign(cuenta, { usd: [], ars: [], caida: false, rechazo: null, puts: 0, alertas: [], pedidos: [], subidas: [], puerta: null })
})
// Con el router: el «Te avisamos» de tu línea es un link a Mis alertas.
const el = () => h(MemoryRouter, null, h(LecturaTecnica, { asset: 'ZZEV', ...props }))
// De entrada el gráfico abre en el último año; estas pruebas cuentan lugares
// sobre la historia entera (los 700 días), así que pasan a «Todo».
let conTodo = true
async function dibujar(p = {}) {
  props = p
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  if (conTodo) { await pasarATodo(montado.contenedor); for (let i = 0; i < 2; i++) await montado.redibujar(el()) }
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
// Lo que se ve de entrada («Todo»): los 700 puntos (uno por día) más el aire vacío de
// la derecha (como TradingView): el ancho se reparte en LUGARES. El punto bajo
// x: round(x / 1000 × (lugares − 1)) dentro de lo que se ve.
const LUGARES = 700 + margenDerecho(700)
const bajo = (x) => Math.round((x / 1000) * (LUGARES - 1))
const status = () => todos(montado.contenedor, n => n.getAttribute?.('role') === 'status').map(n => texto(n)).join(' ')

const linea = () => todos(montado.contenedor, n => n.nodeName === 'LINE' && n.getAttribute?.('data-dibujo') != null)
const boton = (id) => todos(montado.contenedor, n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === id)[0]
// Un botón con menú no es un interruptor (no lleva aria-pressed): se marca con el color de lo prendido.
const marcado = (id) => (boton(id).getAttribute('class') || '').includes('bg-rendi-accent/15')
// Lo que quedó guardado en la cuenta (el servidor simulado).
const guardados = (moneda = 'usd') => cuenta[moneda]
// La copia de este navegador, leída con la misma función que la pantalla (de
// quien está logueado ahora), sin depender de cómo se arma la clave.
const copia = (moneda = 'usd') => copiaLocal('ZZEV', moneda, duenoDeLaPestana())
// El precio a una altura del gráfico (250 px de alto), con la escala que muestra:
// se lee del rótulo que la línea horizontal pone en la columna de precios.
const num = (t) => Number(t.replace(/\./g, '').replace(',', '.'))
// Fibonacci y Elliott a mano se eligen en el menú de su botón de la barra.
const MENU = { fibonacci: 'menu-fibonacci', extension: 'menu-fibonacci', impulso: 'menu-elliott', correccion: 'menu-elliott',
  tendencia: 'menu-lineas', horizontal: 'menu-lineas', canal: 'menu-lineas', pincel: 'menu-lineas' }
async function usar(id) {
  if (MENU[id]) { await clic(montado.contenedor, boton(MENU[id])); await redibujar() }
  await clic(montado.contenedor, boton(id)); await redibujar()
}

describe('línea horizontal', () => {
  it('un click a una altura: la línea de borde a borde, su precio a la derecha, guardada; la herramienta se apaga', async () => {
    await dibujar()
    await usar('horizontal')
    expect(marcado('menu-lineas')).toBe(true)                                    // el grupo «Líneas» queda marcado
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
    expect(marcado('menu-lineas')).toBe(false)                               // una línea por vez
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
    const pctX = (x) => bajo(x) / (LUGARES - 1) * 100
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
    await elegirEnLaVista(montado.contenedor, 'Pesos'); await redibujar(); await redibujar()
    expect(linea()).toHaveLength(0)
    expect(boton('borrarDibujos').getAttribute('aria-disabled')).toBe('true')
  })

  it('con el zoom, la línea sigue en sus días', async () => {
    // «Desde que lo tenés» con la primera compra hace 91 días: acerca a esos 91.
    await dibujar({ lotes: [{ entry_date: puntos[609].d, quantity: 1 }] })
    await usar('tendencia'); await clickEn(860, 180); await clickEn(940, 60)   // los dos, días con precio
    const [t] = guardados()
    await elegirEnLaVista(montado.contenedor, 'Desde que lo tenés'); await redibujar()
    // Los últimos 91 días más su aire.
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
    expect(marcado('menu-lineas')).toBe(true)
    await usar('medir')
    expect(marcado('menu-lineas')).toBe(false)
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
    // Con «Todo» el gráfico arranca en el primer día: se arrastra hacia el futuro.
    await arrastrar(500, 230, 300, 230)                               // lejos de tu línea
    expect(guardados()[0]).toEqual(antes)
    expect(Number(linea()[0].getAttribute('x1'))).toBeLessThan(x)     // el gráfico fue para adelante
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

describe('deshacer y rehacer (Nico, 29/10)', () => {
  const tecla = (key, extra = {}) => enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key, ...extra })) })
  const apagado = (id) => boton(id).getAttribute('aria-disabled') === 'true'

  it('con los botones y con Cmd/Ctrl+Z: vuelve atrás de a un paso y adelante otra vez; lo guardado acompaña', async () => {
    await dibujar()
    expect(apagado('deshacer')).toBe(true)
    expect(apagado('rehacer')).toBe(true)
    await usar('horizontal'); await clickEn(500, 100)
    await usar('tendencia'); await clickEn(200, 200); await clickEn(800, 50)
    expect(guardados().map(d => d.tipo)).toEqual(['horizontal', 'tendencia'])
    await usar('deshacer')
    expect(guardados().map(d => d.tipo)).toEqual(['horizontal'])
    expect(linea()).toHaveLength(1)
    await tecla('z', { metaKey: true }); await redibujar()
    expect(guardados()).toEqual([])
    expect(apagado('deshacer')).toBe(true)
    await usar('rehacer')
    expect(guardados().map(d => d.tipo)).toEqual(['horizontal'])
    await tecla('z', { ctrlKey: true, shiftKey: true }); await redibujar()
    expect(guardados().map(d => d.tipo)).toEqual(['horizontal', 'tendencia'])
    expect(apagado('rehacer')).toBe(true)
  })

  it('un cambio nuevo después de deshacer borra lo que había para rehacer; mover y borrar también se deshacen', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    const [h] = guardados()
    // Moverla y deshacer: vuelve a su precio.
    await evento('mousedown', grafico(), { clientX: 300, clientY: 100 })
    await evento('mousemove', grafico(), { clientX: 300, clientY: 130 })
    await evento('mouseup', grafico(), { clientX: 300, clientY: 130 }); await redibujar()
    expect(guardados()[0].precio).toBeLessThan(h.precio)
    await usar('deshacer')
    expect(guardados()[0].precio).toBe(h.precio)
    // Borrarla y deshacer: vuelve.
    await clickEn(300, 101)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Borrar esta línea')); await redibujar()
    expect(guardados()).toEqual([])
    await tecla('z', { ctrlKey: true }); await redibujar()
    expect(guardados()).toEqual([h])
    // Deshacer el alta, y dibujar otra cosa: no hay nada para rehacer.
    await usar('deshacer')
    expect(apagado('rehacer')).toBe(false)
    await usar('horizontal'); await clickEn(500, 200)
    expect(apagado('rehacer')).toBe(true)
  })

  it('deshacer tu Fibonacci a mano también vuelve a prender el automático que había apagado', async () => {
    await dibujar()
    const fib = () => JSON.parse(localStorage.getItem('rendi_grafico_capas') || '{}').fib
    await usar('fibonacci'); await clickEn(200, 220); await clickEn(400, 60)
    expect(fib()).toBe(false)
    await usar('deshacer')
    expect(guardados()).toEqual([])
    expect(fib()).toBe(true)
  })

  it('deshacer el borrado de una línea con aviso vuelve a prender el aviso', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    const [h] = guardados()
    cuenta.alertas = [{ id: 7, kind: 'tecnica', senal: 'linea', active: 1, symbol: 'ZZEV', currency: 'USD',
      dibujo: JSON.stringify({ asset: 'ZZEV', moneda: 'usd', id: h.id, tipo: 'horizontal' }) }]
    await montado.desmontar(); await dibujar()
    await clickEn(300, 101)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Borrar esta línea')); await redibujar()
    await usar('deshacer')
    expect(guardados()).toEqual([h])
    expect(cuenta.pedidos).toEqual([['PATCH', '/alerts/7', { active: false }], ['PATCH', '/alerts/7', { active: true }]])
  })
})

describe('el color de cada dibujo (Nico, 29/10)', () => {
  const color = (id) => todos(montado.contenedor, n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-color') === id)[0]

  it('con el dibujo tocado se elige el color; queda guardado, vuelve en otra visita y es el de los nuevos', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    expect(color('ambar')).toBeFalsy()                                  // sin elegir nada, no hay colores
    await clickEn(300, 101)
    expect(color('cian').getAttribute('aria-pressed')).toBe('true')     // el de siempre
    await clic(montado.contenedor, color('ambar')); await redibujar()
    expect(guardados()[0].color).toBe('ambar')
    expect(linea()[0].getAttribute('stroke')).toBe('rgb(var(--data-amber))')
    expect(color('ambar').getAttribute('aria-pressed')).toBe('true')
    // Otra visita: vuelve de ese color.
    await montado.desmontar(); await dibujar()
    expect(linea()[0].getAttribute('stroke')).toBe('rgb(var(--data-amber))')
    // Y lo nuevo sale de ese color.
    await usar('tendencia'); await clickEn(200, 200); await clickEn(800, 50)
    expect(guardados()[1]).toMatchObject({ tipo: 'tendencia', color: 'ambar' })
  })

  it('deshacer devuelve el color de antes', async () => {
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    await clickEn(300, 101)
    await clic(montado.contenedor, color('rosa')); await redibujar()
    expect(guardados()[0].color).toBe('rosa')
    await usar('deshacer')
    expect(guardados()[0].color).toBeUndefined()
  })
})

describe('el canal paralelo y el pincel (Nico, 29/10)', () => {
  const poligonos = () => todos(montado.contenedor, n => n.nodeName === 'POLYGON')

  it('el canal: dos toques para la línea, el tercero para el ancho; se ven las dos paralelas, la del medio y la franja', async () => {
    await dibujar()
    await usar('canal')
    expect(status()).toContain('Canal: tocá donde empieza la línea de abajo')
    await clickEn(200, 200); await clickEn(800, 100)
    expect(status()).toContain('a qué altura va la paralela')
    await clickEn(500, 100)                                           // 50 px arriba de la línea (que en 500 está en 150)
    const [c] = guardados()
    expect(c).toMatchObject({ tipo: 'canal', a: { d: puntos[bajo(200)].d }, b: { d: puntos[bajo(800)].d } })
    expect(c.ancho).toBeGreaterThan(0)
    const ls = linea()
    expect(ls).toHaveLength(3)
    const ys = ls.map(l => Number(l.getAttribute('y1')))
    expect(ys[0] - ys[1]).toBeCloseTo(20, 0)                          // la paralela, 50 de 250 px más arriba
    expect(ls[2].getAttribute('stroke-dasharray')).toBe('5 4')        // la del medio, punteada
    expect(Number(ls[2].getAttribute('y1'))).toBeCloseTo((ys[0] + ys[1]) / 2, 4)
    expect(poligonos()).toHaveLength(1)
    expect(status()).not.toContain('Canal:')                          // la herramienta se apaga
  })

  it('el canal se ensancha agarrando su paralela; la línea de abajo no se mueve', async () => {
    await dibujar()
    await usar('canal'); await clickEn(200, 200); await clickEn(800, 100); await clickEn(500, 100)
    const [antes] = guardados()
    // La paralela pasa por (500, 100): se agarra de su mitad y se sube 25 px.
    await evento('mousedown', grafico(), { clientX: 500, clientY: 100 })
    await evento('mousemove', grafico(), { clientX: 500, clientY: 90 })
    await evento('mousemove', grafico(), { clientX: 500, clientY: 75 })
    await evento('mouseup', grafico(), { clientX: 500, clientY: 75 }); await redibujar()
    const [c] = guardados()
    expect(c.a).toEqual(antes.a)
    expect(c.b).toEqual(antes.b)
    expect(c.ancho).toBeGreaterThan(antes.ancho)
    expect(status()).toContain('Canal seleccionado.')
  })

  it('el pincel: apretar y arrastrar dibuja un trazo (no mueve el gráfico); sigue prendido para otro; Esc lo apaga', async () => {
    await dibujar()
    const fechas = () => texto(todos(montado.contenedor, n => n.getAttribute?.('title')?.startsWith('Arrastrá hacia los costados'))[0])
    const antes = fechas()
    await usar('pincel')
    expect(status()).toContain('Dibujá con el mouse apretado')
    const trazar = async (pts) => {
      await evento('mousedown', grafico(), { clientX: pts[0][0], clientY: pts[0][1] })
      for (const [x, y] of pts.slice(1)) await evento('mousemove', grafico(), { clientX: x, clientY: y })
      await evento('mouseup', grafico(), { clientX: pts.at(-1)[0], clientY: pts.at(-1)[1] }); await redibujar()
    }
    await trazar([[300, 100], [301, 101], [310, 120], [330, 140], [360, 130]])
    const [t] = guardados()
    expect(t.tipo).toBe('pincel')
    expect(t.puntos).toHaveLength(4)                                   // el de 1 px no cuenta
    expect(t.puntos.some(p => p.f > 0)).toBe(true)                    // sin escalones de a un día
    expect(linea()).toHaveLength(3)
    expect(fechas()).toBe(antes)                                       // el gráfico no se movió
    expect(status()).toContain('Dibujá con el mouse apretado')        // sigue prendido
    expect(buscarBoton(montado.contenedor, 'Cancelar')).toBeFalsy()  // lo dibujado ya quedó: «Listo»
    await trazar([[500, 200], [520, 180], [540, 200]])
    expect(guardados()).toHaveLength(2)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Listo')); await redibujar()
    expect(status()).not.toContain('Dibujá')
    expect(guardados()).toHaveLength(2)
    await usar('pincel')
    await enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape' })) }); await redibujar()
    expect(status()).not.toContain('Dibujá')
    // Elegido con un click encima, se borra entero.
    await clickEn(320, 130)
    expect(status()).toContain('Trazo seleccionado.')
  })

  it('con el dedo también dibuja, y la página no se mueve mientras', async () => {
    await dibujar()
    await usar('pincel')
    const t = (cx, cy) => ({ touches: [{ clientX: cx, clientY: cy }], changedTouches: [{ clientX: cx, clientY: cy }] })
    await evento('touchstart', grafico(), t(300, 100))
    let prevenido = false
    await enActo(async () => {
      for (const fn of grafico().escuchas.touchmove || []) fn({ ...t(320, 120), cancelable: true, preventDefault() { prevenido = true } })
    })
    expect(prevenido).toBe(true)
    for (const [x, y] of [[320, 120], [340, 150]]) await evento('touchmove', grafico(), t(x, y))
    await evento('touchend', grafico(), { touches: [], changedTouches: [{ clientX: 340, clientY: 150 }] }); await redibujar()
    expect(guardados()).toHaveLength(1)
    expect(guardados()[0].puntos).toHaveLength(3)
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
    expect(t).toContain('ZZEV toque tu línea horizontal')         // la tarjeta de la línea elegida
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

  // — tu canal (Nico, 29/10): «Avisame si sale del canal» —
  // Dos toques para la línea de abajo (de 200,200 a 800,100: en x=500 pasa por
  // y=150) y el tercero para la paralela (50 px más arriba).
  const canal = async () => { await usar('canal'); await clickEn(200, 200); await clickEn(800, 100); await clickEn(500, 100) }
  const enLaColumna = () => todos(montado.contenedor, n => n.getAttribute?.('data-aviso') != null)

  it('el canal elegido ofrece «Avisame si sale del canal»: el formulario pregunta por qué borde y cuándo cuenta', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
    window.matchMedia = globalThis.matchMedia
    await dibujar()
    await canal()
    await clickEn(500, 151)
    expect(status()).toContain('Canal seleccionado.')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Avisame si sale del canal')); await redibujar()
    let t = texto(montado.contenedor)
    expect(t).toContain('ZZEV salga de tu canal')
    expect(t).toContain('Por qué borde')
    expect(t).toContain('Te avisamos cuando ZZEV toque o pase cualquiera de los dos bordes de tu canal.')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Por arriba')); await redibujar()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Si cierra afuera')); await redibujar()
    t = texto(montado.contenedor)
    expect(t).toContain('Te avisamos cuando ZZEV cierre afuera de tu canal, por arriba.')
    await evento('submit', todos(montado.contenedor, n => n.nodeName === 'FORM')[0]); await redibujar()
    const [[, ruta, body]] = cuenta.pedidos
    expect(ruta).toBe('/alerts')
    expect(body).toMatchObject({ kind: 'tecnica', senal: 'linea', symbol: 'ZZEV', dibujo: guardados()[0].id,
      direction: 'above', modo: 'cierre', repeat: 'once' })
  })

  it('un canal con aviso sigue hacia la derecha, con la campanita en sus dos bordes; moverlo lo dice', async () => {
    await dibujar()
    await canal()
    expect(enLaColumna()).toHaveLength(0)
    cuenta.alertas = [avisoDe(guardados()[0].id, 'canal')]
    await montado.desmontar(); await dibujar()
    const ls = linea()
    expect(ls).toHaveLength(5)                                        // las tres del canal y sus dos bordes, siguiendo
    expect(ls.slice(3).every(l => Number(l.getAttribute('x2')) === 100 && l.getAttribute('stroke-dasharray') === '5 4')).toBe(true)
    expect(enLaColumna()).toHaveLength(2)                             // un precio con campanita por borde
    // Lo arrastrás: el aviso lo sigue, y se dice.
    await evento('mousedown', grafico(), { clientX: 500, clientY: 150 })
    await evento('mousemove', grafico(), { clientX: 500, clientY: 160 })
    await evento('mouseup', grafico(), { clientX: 500, clientY: 170 }); await redibujar()
    expect(status()).toContain('Moviste tu canal. El aviso lo sigue')
    expect(cuenta.pedidos).toEqual([])                                // el aviso no se toca: lee el canal guardado
  })

  it('borrar un canal con aviso lo apaga y lo dice; «Deshacer» trae el canal y prende el aviso', async () => {
    await dibujar()
    await canal()
    const [c] = guardados()
    cuenta.alertas = [avisoDe(c.id, 'canal')]
    await montado.desmontar(); await dibujar()
    await clickEn(500, 151)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Borrar este canal')); await redibujar()
    expect(status()).toContain('Borraste tu canal y se apagó su aviso.')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Deshacer')); await redibujar()
    expect(guardados()).toEqual([c])
    expect(cuenta.pedidos).toEqual([['PATCH', '/alerts/7', { active: false }], ['PATCH', '/alerts/7', { active: true }]])
    expect(status()).not.toContain('Borraste tu canal')
  })

  it('abierta desde el aviso («Ver en el gráfico»), la ficha llega con esa línea elegida', async () => {
    cuenta.usd = [{ id: 'c9', tipo: 'canal', a: { d: puntos[300].d, mas: 0, precio: 110 }, b: { d: puntos[600].d, mas: 0, precio: 130 }, ancho: 15 }]
    window.location.search = '?linea=c9&moneda=usd'
    try {
      await dibujar()
      expect(status()).toContain('Canal seleccionado.')
    } finally { window.location.search = '' }
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
    expect(copia()).toMatchObject({ pendiente: false, dibujos: [H] })   // queda la copia, ya en la cuenta
  })

  it('lo borrado en otro dispositivo no revive desde la copia de este navegador', async () => {
    guardarDibujos('ZZEV', 'usd', [H], false, duenoDeLaPestana())   // la copia de Ana, ya subida
    cuenta.usd = []
    await dibujar()
    expect(linea()).toHaveLength(0)
    expect(cuenta.puts).toBe(0)
    expect(copia()).toEqual({ pendiente: false, dibujos: [] })
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

describe('la copia de este navegador es de quien la hizo (auditoría de la pestaña Gráfico, 30/10)', () => {
  // A Ana no se le pudo guardar un dibujo en la cuenta (quedó pendiente en este
  // navegador). Antes, la copia era del ACTIVO y no de la persona: el siguiente
  // que abría ese activo en la misma compu la subía a SU cuenta y la veía.
  async function anaDejaUnoPendiente() {
    cuenta.caida = true
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    expect(copia().pendiente).toBe(true)
    await montado.desmontar(); montado = null
    cuenta.caida = false
  }
  const subidasDe = (quien, cliente = null) => cuenta.subidas.filter(x => x.quien === quien && x.cliente === cliente)

  it('a Ana se le vence la sesión y entra Bruno: no recibe ni ve el dibujo de Ana', async () => {
    await anaDejaUnoPendiente()
    localStorage.removeItem('rendi_user')            // lo que hace api.js con un 401
    entrar(BRUNO)                                   // y Bruno inicia sesión
    await dibujar()
    expect(subidasDe(BRUNO.email)).toEqual([])
    expect(linea()).toHaveLength(0)
  })

  it('y cuando Ana vuelve, su dibujo pendiente sigue ahí y se sube a SU cuenta', async () => {
    await anaDejaUnoPendiente()
    entrar(BRUNO); await dibujar(); await montado.desmontar(); montado = null
    entrar(ANA); await dibujar()
    expect(subidasDe(ANA.email)).toHaveLength(1)
    expect(subidasDe(BRUNO.email)).toEqual([])
    expect(linea()).toHaveLength(1)
  })

  it('el asesor dibuja en el cliente 2 y abre el cliente 3: al 3 no le llega', async () => {
    sesion.cliente = 2
    await anaDejaUnoPendiente()
    sesion.cliente = 3
    await dibujar()
    expect(subidasDe(ANA.email, 3)).toEqual([])
    expect(linea()).toHaveLength(0)
    await montado.desmontar(); montado = null
    sesion.cliente = 2
    await dibujar()
    expect(subidasDe(ANA.email, 2)).toHaveLength(1)
  })

  it('si la cuenta cambia con el gráfico abierto (otra pestaña), no se queda con los dibujos de la anterior', async () => {
    sesion.cliente = 2
    cuenta.usd = [H2]
    await dibujar()
    expect(linea()).toHaveLength(1)
    cuenta.usd = []                                  // la cuenta del cliente 3, vacía
    sesion.cliente = 3
    await enActo(async () => { window.dispatchEvent(new Event('rendi:cuenta-cambiada')) })
    await redibujar()
    expect(linea()).toHaveLength(0)
    await usar('horizontal'); await clickEn(300, 100)   // lo que se dibuja ahora es del 3
    const alTres = subidasDe(ANA.email, 3)
    expect(alTres).toHaveLength(1)
    expect(alTres[0].dibujos.map(d => d.id)).not.toContain(H2.id)
  })

  // La ventana entre que OTRA pestaña cambia la cuenta y este gráfico se
  // redibuja (re-test a ciegas 3, 30/10): el cliente ya es otro (api.js manda
  // los pedidos al 3) pero el gráfico todavía muestra los dibujos del 2. Antes,
  // la subida tomaba el dueño de la pestaña AHORA y le mandaba al 3 lo del 2.
  it('el pendiente del cliente 2 no sube al 3 si la cuenta cambia mientras el gráfico espera a la cuenta', async () => {
    sesion.cliente = 2
    await anaDejaUnoPendiente()
    let abrir
    cuenta.puerta = new Promise(r => { abrir = r })
    await dibujar()                                   // pidió los de la cuenta y espera
    sesion.cliente = 3                                // otra pestaña: todavía sin avisar
    await enActo(async () => { abrir(); await new Promise(r => setTimeout(r, 0)) })
    await redibujar()
    expect(subidasDe(ANA.email, 3)).toEqual([])
    await montado.desmontar(); montado = null
    cuenta.puerta = null
    sesion.cliente = 2
    await dibujar()
    expect(subidasDe(ANA.email, 2), 'sigue pendiente y sube a SU cuenta').toHaveLength(1)
  })

  it('lo que se dibuja sobre el gráfico del 2 en esa ventana no se guarda ni se sube al 3, y lo dice', async () => {
    sesion.cliente = 2
    cuenta.usd = [H2]
    await dibujar()
    expect(linea()).toHaveLength(1)
    sesion.cliente = 3                                // otra pestaña: todavía sin avisar
    await usar('horizontal'); await clickEn(300, 100)
    expect(subidasDe(ANA.email, 3)).toEqual([])
    expect(copiaLocal('ZZEV', 'usd', 'ana@prueba.test|cliente-3').dibujos).toEqual([])
    expect(texto(montado.contenedor)).toContain('en otra pestaña se cambió de cuenta')
  })

  it('una copia sin dueño (de antes de este arreglo) no se sube a nadie ni se muestra', async () => {
    localStorage.setItem('rendi_dibujos:ZZEV:usd', JSON.stringify({ pendiente: true, dibujos: [H2] }))
    await dibujar()
    expect(cuenta.subidas).toEqual([])
    expect(linea()).toHaveLength(0)
  })

  it('sin nadie logueado no queda copia', async () => {
    localStorage.removeItem('rendi_user')
    cuenta.caida = true
    await dibujar()
    await usar('horizontal'); await clickEn(500, 100)
    entrar(ANA)
    expect(copia()).toEqual({ pendiente: false, dibujos: [] })
  })
})
const H2 = { id: 'h2', tipo: 'horizontal', precio: 120 }

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
    expect(enLaBarra).toEqual(['menu-lineas', 'nota', 'menu-fibonacci', 'menu-elliott', 'medir', 'deshacer', 'rehacer', 'borrarDibujos'])
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
