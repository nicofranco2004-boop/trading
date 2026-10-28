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
const cuenta = { usd: [], ars: [], caida: false, puts: 0 }
const monedaDe = (ruta) => (ruta.includes('moneda=ars') ? 'ars' : 'usd')
vi.mock('../../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => Promise.resolve(ruta.includes('/dibujos') ? { dibujos: cuenta[monedaDe(ruta)] }
      : ruta.includes('/eventos') ? EVENTOS : DATOS)),
    put: vi.fn((ruta, body) => {
      cuenta.puts++
      if (cuenta.caida) return Promise.reject(new Error('sin conexión'))
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
  Object.assign(cuenta, { usd: [], ars: [], caida: false, puts: 0 })
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
async function usar(id) { await clic(montado.contenedor, boton(id)); await redibujar() }

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
    expect(status()).toContain('Línea horizontal elegida.')
    expect(linea().map(n => n.getAttribute('stroke-width'))).toEqual(['3', '1.8'])
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Borrar esta línea')); await redibujar()
    expect(linea()).toHaveLength(1)
    expect(Number(linea()[0].getAttribute('y1'))).toBeCloseTo(80, 2)   // quedó la otra
    expect(guardados()).toHaveLength(1)
  })

  it('un click lejos de todas suelta la elegida; la tecla Suprimir la borra', async () => {
    await dibujar()
    await usar('tendencia'); await clickEn(200, 200); await clickEn(800, 50)
    // A mitad de camino, sobre la línea: x 500 → y 125.
    await clickEn(500, 128)
    expect(status()).toContain('Línea de tendencia elegida.')
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
    expect(status()).toContain('Línea horizontal elegida.')
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

  it('lo dibujado en este navegador antes del guardado en la cuenta se sube solo', async () => {
    localStorage.setItem('rendi_dibujos:ZZEV:usd', JSON.stringify([H]))      // la copia vieja: la lista sola
    await dibujar()
    expect(linea()).toHaveLength(1)
    expect(guardados()).toEqual([H])
    expect(copia().pendiente).toBe(false)
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

  it('la barra separa el automático de la herramienta a mano', async () => {
    await dibujar()
    expect(texto(boton('fib'))).toContain('Fibonacci automático')
    expect(texto(boton('ell'))).toContain('Ondas de Elliott automáticas')
    expect(texto(boton('fibonacci'))).toContain('Fibonacci a mano')
    expect(texto(boton('elliott'))).toContain('Elliott a mano')
  })

  it('tu Fibonacci: dos toques (arranque y final del tramo), los niveles con su precio, guardado; apaga el automático', async () => {
    await dibujar()
    await usar('fibonacci')
    expect(status()).toContain('Tocá donde arranca el tramo que querés medir')
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
    expect(boton('fibonacci').getAttribute('aria-pressed')).toBe('false')
  })

  it('cancelar a mitad de camino no apaga el automático ni guarda nada', async () => {
    await dibujar()
    await usar('fibonacci'); await clickEn(300, 200)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Cancelar')); await redibujar()
    expect(guardados()).toEqual([])
    expect(capas().fib).not.toBe(false)
  })

  it('tu conteo de Elliott: un toque por onda, «Terminar acá» cuando quieras; apaga el automático', async () => {
    await dibujar()
    await usar('elliott')
    expect(status()).toContain('Tocá el arranque del conteo (el 0)')
    await clickEn(100, 220)
    expect(status()).not.toContain('Terminar acá')              // con el 0 solo no hay conteo
    await clickEn(250, 120)
    expect(status()).toContain('Ahora tocá la onda 2')
    await clickEn(350, 170)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Terminar acá')); await redibujar()
    const [e] = guardados()
    expect(e.tipo).toBe('elliott')
    expect(e.puntos.map(q => q.d)).toEqual([bajo(100), bajo(250), bajo(350)].map(i => puntos[i].d))
    expect(rotulos().filter(t => /^[0-5ABC]$/.test(t))).toEqual(['0', '1', '2'])
    expect(capas().ell).toBe(false)
  })

  it('al llegar a la C el conteo se termina solo', async () => {
    await dibujar()
    await usar('elliott')
    for (let k = 0; k < 9; k++) await clickEn(100 + k * 80, k % 2 ? 80 : 200)
    const [e] = guardados()
    expect(e.puntos).toHaveLength(9)
    expect(rotulos().filter(t => /^[0-5ABC]$/.test(t))).toEqual(['0', '1', '2', '3', '4', '5', 'A', 'B', 'C'])
    expect(boton('elliott').getAttribute('aria-pressed')).toBe('false')
  })

  it('tocar uno de tus niveles elige tu Fibonacci y se borra entero', async () => {
    await dibujar()
    await usar('fibonacci'); await clickEn(300, 200); await clickEn(800, 50)
    // El nivel del 50 %: a mitad de altura entre los dos toques.
    await clickEn(900, 125)
    expect(status()).toContain('Tu Fibonacci, elegido.')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Borrar este Fibonacci')); await redibujar()
    expect(guardados()).toEqual([])
    expect(rotulos().some(t => t.startsWith('61,8 %'))).toBe(false)
  })
})
