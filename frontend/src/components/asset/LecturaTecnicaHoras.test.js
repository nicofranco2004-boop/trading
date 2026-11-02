// Velas de 1 hora y de 4 horas en el gráfico técnico de la ficha, montado de
// verdad (testing/navegadorMinimo.js) con los pedidos al servidor simulados en
// la frontera (utils/api). Lo que se prueba es lo que ve la persona:
//   · «1H» y «4H» en el menú «1D ▾», y elegirlos pide sus velas;
//   · la última vela está en curso (más transparente, «en curso · hace X s») y
//     se mueve sola cada minuto: el refresco pide sólo desde la última vela;
//   · con la pestaña oculta no se pide nada;
//   · la lectura y las tarjetas de abajo siguen siendo las diarias;
//   · tus dibujos se ubican por fecha y hora, y el que arranca antes de las
//     velas de horas no se dibuja (se dice por qué);
//   · tus compras van a la primera vela de ese día.
// Las cuentas sueltas (ubicar, el eje, la mezcla): utils/velasPorHora.test.js.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, clic, enActo, medidas } from '../../testing/navegadorMinimo'
import { CAPAS_TODAS } from './BarraGrafico'

// Las diarias: los días hábiles del 1/6/2025 al 28/10/2026 (el 29 todavía no
// está guardado: la vela de hoy no entra hasta la noche).
const DIARIOS = (() => {
  const out = []
  for (let t = Date.UTC(2025, 5, 2); t <= Date.UTC(2026, 9, 28); t += 86400000) {
    const w = new Date(t).getUTCDay()
    if (w === 0 || w === 6) continue
    const c = 200 + out.length * 0.2
    out.push({ d: new Date(t).toISOString().slice(0, 10), o: c, h: c + 1, l: c - 1, c, s50: c - 2, s200: c - 5, rsi: 55, v: 1000 })
  }
  return out
})()
const DIA = {
  disponible: true, moneda: 'usd', ticker: 'AAPL', convertida: null, puntos: DIARIOS,
  lectura: { ruedas: DIARIOS.length, fecha: '2026-10-28', precio: 300, media50: 298, dist_media50: 0.7,
    media200: 290, dist_media200: 3.4, pendiente_media200: 1, rsi: 55, dist_maximo_12m: -1, anio_completo: true },
}

// Las de 1 hora de Nueva York (9:30 a 15:30 de allá = 10:30 a 16:30 acá) del
// 12/10 al 29/10/2026; la del 29 a las 15:30 de allá está en curso.
const utc = (m, d, hh, mm = 0) => Date.UTC(2026, m - 1, d, hh, mm) / 1000
const DIAS_HORAS = [12, 13, 14, 15, 16, 19, 20, 21, 22, 23, 26, 27, 28, 29]
function horas(precioFinal = 350) {
  const out = []
  for (const d of DIAS_HORAS) {
    for (let k = 0; k < 7; k++) {
      const c = 300 + out.length * 0.5
      out.push({ d: `2026-10-${d}`, t: utc(10, d, 13 + k, 30), o: c - 0.2, h: c + 0.6, l: c - 0.6, c, s50: c - 1, s200: c - 3, rsi: 50, v: 100 })
    }
  }
  out[out.length - 1] = { ...out[out.length - 1], c: precioFinal, h: Math.max(precioFinal, out[out.length - 1].h), enCurso: true }
  return out
}
const SESION = { abre: 570, cierra: 960, desfase: -240, todos_los_dias: false, velas_por_dia: 7 }
const HORA = (puntos = horas()) => ({
  asset: 'AAPL', moneda: 'usd', cada: '1h', disponible: true, ticker: 'AAPL', convertida: null, mercado: 'us',
  sesion: SESION, en_horario: true, actualizada: new Date().toISOString(), puntos,
})

let respuestas, pedidos
vi.mock('../../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => {
      pedidos.push(ruta)
      const clave = Object.keys(respuestas).filter(k => ruta.startsWith(k)).sort((a, b) => b.length - a.length)[0]
      const r = clave ? (typeof respuestas[clave] === 'function' ? respuestas[clave](ruta) : respuestas[clave]) : []
      return r instanceof Error ? Promise.reject(r) : Promise.resolve(r)
    }),
    put: vi.fn(() => Promise.resolve({ ok: true })),
    patch: vi.fn(() => Promise.resolve({})),
  },
  getClientContext: () => null,
  EVENTO_CUENTA_CAMBIADA: 'rendi:cuenta-cambiada',
}))

let LecturaTecnica
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
beforeEach(() => {
  pedidos = []
  respuestas = {
    '/tecnico/AAPL?moneda=usd': DIA,
    '/tecnico/AAPL/horas?cada=1h&moneda=usd': HORA(),
    '/tecnico/AAPL/horas?cada=4h&moneda=usd': { ...HORA(), cada: '4h' },
  }
  // Velas, no línea: el menú «1D ▾» sólo está con velas.
  localStorage.setItem('rendi_grafico_tipo', 'velas')
  // Ana logueada en su cuenta: los dibujos del navegador son a su nombre (utils/dibujos.js).
  localStorage.setItem('rendi_user', JSON.stringify({ email: 'ana@prueba.test' }))
  // El reloj del refresco (setInterval) lo maneja la prueba.
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
})
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()
  document.visibilityState = 'visible'
  vi.useRealTimers()
})

const props = (extra = {}) => ({ asset: 'AAPL', symbolMiniChart: 'AAPL', ...extra })
async function abrir(extra) {
  montado = await montar(h(LecturaTecnica, props(extra)))
  for (let i = 0; i < 4; i++) await montado.redibujar(h(LecturaTecnica, props(extra)))
}
async function otraVez(extra) {
  for (let i = 0; i < 3; i++) await montado.redibujar(h(LecturaTecnica, props(extra)))
}
function todos(pred) {
  const out = [], pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (pred(n)) out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}
const uno = (pred) => todos(pred)[0] || null
const velas = () => todos(n => n.nodeName === 'G' && (n.childNodes || []).some(c => c.nodeName === 'RECT'))
const tarjetas = () => texto(uno(n => (n.getAttribute?.('class') || '').includes('xl:grid-cols-3')))
async function elegirIntervalo(id, extra) {
  await clic(montado.contenedor, uno(n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === 'intervalo'))
  await clic(montado.contenedor, uno(n => n.getAttribute?.('data-intervalo') === id))
  await otraVez(extra)
}
// Pasa un minuto con la pestaña como esté, y deja llegar lo que se pidió.
async function pasaUnMinuto(extra) {
  await enActo(async () => {
    vi.advanceTimersByTime(60_000)
    for (let i = 0; i < 4; i++) await Promise.resolve()
  })
  await otraVez(extra)
}

describe('velas de 1 hora y de 4 horas', () => {
  it('el menú ofrece 1H y 4H; elegir 1H pide sus velas y la última está en curso', async () => {
    await abrir()
    await clic(montado.contenedor, uno(n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === 'intervalo'))
    const opciones = todos(n => n.getAttribute?.('data-intervalo') != null).map(n => [n.getAttribute('data-intervalo'), texto(n)])
    expect(opciones).toEqual([['1h', '1 hora1H'], ['4h', '4 horas4H'], ['dia', 'Diarias1D'], ['semana', 'Semanales1S']])
    expect(pedidos.filter(r => r.includes('/horas'))).toEqual([])   // nadie pide horas sin elegirlas
    await clic(montado.contenedor, uno(n => n.getAttribute?.('data-intervalo') === '1h'))
    await otraVez()

    expect(pedidos.filter(r => r.includes('/horas'))).toEqual(['/tecnico/AAPL/horas?cada=1h&moneda=usd'])
    expect(velas()).toHaveLength(DIAS_HORAS.length * 7)
    // La vela en curso es la última y es la única más transparente.
    const enCurso = velas().filter(g => g.getAttribute('data-en-curso') != null)
    expect(enCurso).toHaveLength(1)
    expect(enCurso[0]).toBe(velas()[velas().length - 1])
    expect(enCurso[0].getAttribute('opacity')).toBe('0.55')
    const t = texto(montado.contenedor)
    expect(t).toContain('Cada vela es una hora, en hora de Argentina.')
    expect(t).toMatch(/La última vela está en curso · hace \d+ s\./)
    // Las medias son de 200 y 50 velas: horas.
    expect(t).toContain('Promedio 200 horas')
    expect(t).not.toContain('Promedio 200 días')
  })

  it('la vela en curso se mueve sola cada minuto: pide sólo desde la última vela', async () => {
    await abrir()
    await elegirIntervalo('1h')
    const ultimaT = horas()[horas().length - 1].t
    // En el minuto siguiente la hora en curso subió a 352 y empezó otra.
    const nuevas = [{ ...horas(352)[horas().length - 1], enCurso: undefined },
      { d: '2026-10-29', t: ultimaT + 3600, o: 352, h: 353, l: 351, c: 352.5, enCurso: true }]
    respuestas[`/tecnico/AAPL/horas?cada=1h&moneda=usd&desde=${ultimaT}`] = { ...HORA(), puntos: nuevas }
    await pasaUnMinuto()
    expect(pedidos.filter(r => r.includes('/horas'))).toEqual([
      '/tecnico/AAPL/horas?cada=1h&moneda=usd', `/tecnico/AAPL/horas?cada=1h&moneda=usd&desde=${ultimaT}`])
    expect(velas()).toHaveLength(DIAS_HORAS.length * 7 + 1)
    // El último precio del costado es el de la vela nueva; la anterior ya no está en curso.
    expect(texto(montado.contenedor)).toContain('352,50')
    expect(velas().filter(g => g.getAttribute('data-en-curso') != null)).toHaveLength(1)
  })

  it('con la pestaña oculta no pide nada; al volver, sí', async () => {
    await abrir()
    await elegirIntervalo('1h')
    const antes = pedidos.length
    document.visibilityState = 'hidden'
    await pasaUnMinuto()
    await pasaUnMinuto()
    expect(pedidos.length).toBe(antes)
    document.visibilityState = 'visible'
    await pasaUnMinuto()
    expect(pedidos.slice(antes).filter(r => r.includes('/horas'))).toHaveLength(1)
  })

  it('en BYMA dice la demora de sus precios junto a la vela en curso', async () => {
    respuestas['/tecnico/AAPL/horas?cada=1h&moneda=usd'] = { ...HORA(), mercado: 'byma', demora_min: 20 }
    await abrir()
    await elegirIntervalo('1h')
    expect(texto(montado.contenedor)).toMatch(/La última vela está en curso · hace \d+ s \(los precios de esta bolsa llegan con unos 20 minutos de demora\)\./)
  })

  it('con la rueda cerrada no pide cada minuto', async () => {
    respuestas['/tecnico/AAPL/horas?cada=1h&moneda=usd'] = { ...HORA(horas().map(p => ({ ...p, enCurso: undefined }))), en_horario: false }
    await abrir()
    await elegirIntervalo('1h')
    const antes = pedidos.length
    await pasaUnMinuto()
    expect(pedidos.length).toBe(antes)
    expect(texto(montado.contenedor)).toContain('La última vela es la del 29/10/26 16:30.')
  })

  it('la lectura y las tarjetas no cambian: siguen siendo las diarias', async () => {
    await abrir()
    const diarias = tarjetas()
    expect(diarias).toContain('Largo plazo')
    await elegirIntervalo('1h')
    expect(tarjetas()).toBe(diarias)
    await elegirIntervalo('4h')
    expect(tarjetas()).toBe(diarias)
    expect(pedidos.filter(r => r.startsWith('/tecnico/AAPL?'))).toHaveLength(1)   // la diaria, una sola vez
  })

  it('tus dibujos se ubican por fecha y hora; el que arranca antes de las velas de horas no se dibuja', async () => {
    localStorage.setItem('rendi_dibujos:ana@prueba.test|propia:AAPL:usd', JSON.stringify({ pendiente: false, dibujos: [
      { id: 'horizontal', tipo: 'horizontal', precio: 320 },
      // Dibujada en diarias del 14 al 27: en 1H va de la primera hora del 14 a la del 27.
      { id: 'adentro', tipo: 'tendencia', a: { d: '2026-10-14', mas: 0, precio: 305 }, b: { d: '2026-10-27', mas: 0, precio: 340 } },
      // Arranca en septiembre: antes de las velas de 1 hora que hay.
      { id: 'vieja', tipo: 'tendencia', a: { d: '2026-09-01', mas: 0, precio: 280 }, b: { d: '2026-10-20', mas: 0, precio: 310 } },
    ] }))
    await abrir()
    const lineas = () => [...new Set(todos(n => n.nodeName === 'LINE' && n.getAttribute?.('data-dibujo') != null).map(n => n.getAttribute('data-dibujo')))]
    expect(lineas().sort()).toEqual(['adentro', 'horizontal', 'vieja'])
    await elegirIntervalo('1h')
    expect(lineas().sort()).toEqual(['adentro', 'horizontal'])
    expect(texto(montado.contenedor)).toContain('Uno de tus dibujos arranca antes de las velas de 1 hora que hay: se ve en diarias.')
    // La de adentro empieza en la primera vela del 14 (la 14 de la serie) y
    // termina en la primera del 27 (la 77). En % del ancho.
    const l = uno(n => n.nodeName === 'LINE' && n.getAttribute?.('data-dibujo') === 'adentro')
    const lugares = DIAS_HORAS.length * 7 + 5     // las velas más el aire de la derecha (margenDerecho)
    expect(Number(l.getAttribute('x1'))).toBeCloseTo((14 / (lugares - 1)) * 100, 3)
    expect(Number(l.getAttribute('x2'))).toBeCloseTo((77 / (lugares - 1)) * 100, 3)
  })

  it('tus compras van a la primera vela de ese día', async () => {
    // «Tus compras y ventas» prendida (de fábrica viene apagada).
    localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS))
    await abrir({ lotes: [{ entry_date: '2026-10-21', quantity: 1 }] })
    await elegirIntervalo('1h', { lotes: [{ entry_date: '2026-10-21', quantity: 1 }] })
    const marca = uno(n => n.nodeName === 'SPAN' && (n.getAttribute?.('title') || '') === 'Compraste el 21/10/26')
    expect(marca).not.toBeNull()
    const lugares = DIAS_HORAS.length * 7 + 5
    // La primera hora del 21 es la vela 49 (7 ruedas de 7 antes).
    expect(parseFloat(marca.style.left)).toBeCloseTo((49 / (lugares - 1)) * 100, 6)
  })

  it('una compra de hoy se marca en 1H aunque las diarias todavía no tengan el día de hoy', async () => {
    localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS))
    const lotes = [{ entry_date: '2026-10-29', quantity: 1 }]
    await abrir({ lotes })
    expect(uno(n => n.nodeName === 'SPAN' && (n.getAttribute?.('title') || '') === 'Compraste el 29/10/26')).toBeNull()
    await elegirIntervalo('1h', { lotes })
    const marca = uno(n => n.nodeName === 'SPAN' && (n.getAttribute?.('title') || '') === 'Compraste el 29/10/26')
    expect(marca).not.toBeNull()
    const lugares = DIAS_HORAS.length * 7 + 5
    expect(parseFloat(marca.style.left)).toBeCloseTo((91 / (lugares - 1)) * 100, 6)   // la primera hora del 29
  })

  it('si Yahoo no tiene velas de 1 hora de este activo, lo dice y ofrece volver a diarias', async () => {
    respuestas['/tecnico/AAPL/horas?cada=1h&moneda=usd'] = { disponible: false, motivo: 'sin_datos' }
    await abrir()
    await elegirIntervalo('1h')
    expect(texto(montado.contenedor)).toContain('No encontramos velas de 1 hora de este activo.')
    expect(tarjetas()).toContain('Largo plazo')
    await clic(montado.contenedor, uno(n => n.nodeName === 'BUTTON' && texto(n) === 'Ver velas diarias'))
    await otraVez()
    // Vuelve en el período de entrada de las diarias: el último año (~250 ruedas), no las 300+ guardadas.
    expect(velas().length).toBeGreaterThan(240)
    expect(velas().length).toBeLessThan(270)
  })
})

// ─── Lo que encontró la auditoría (30/10) ─────────────────────────────────────

// El gráfico mide `ancho` × 250 px (el navegador mínimo no tiene tamaños).
const conAncho = (ancho) => medidas(() => ({ left: 0, top: 0, width: ancho, height: 250, right: ancho, bottom: 250 }))
// Un evento del mouse como lo recibe React: por la raíz.
async function evento(tipo, nodo, datos = {}) {
  await enActo(async () => {
    const ev = { type: tipo, target: nodo, bubbles: true, cancelable: true, button: 0, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true }, stopPropagation() {}, ...datos }
    for (const fn of montado.contenedor.escuchas[tipo] || []) fn(ev)
  })
}
const grafico = () => uno(n => n.getAttribute?.('role') === 'img' && (n.getAttribute('aria-label') || '').startsWith('Precio con su promedio'))
const linea = (id) => uno(n => n.nodeName === 'LINE' && n.getAttribute?.('data-dibujo') === id)
// El medio de una línea en px, en un gráfico de `ancho` × 250.
function medioDe(id, ancho) {
  const l = linea(id)
  const x = (Number(l.getAttribute('x1')) + Number(l.getAttribute('x2'))) / 2
  const y = (Number(l.getAttribute('y1')) + Number(l.getAttribute('y2'))) / 2
  return [(x / 100) * ancho, (y / 100) * 250]
}
async function clickEn(x, y, extra) {
  await evento('mousedown', grafico(), { clientX: x, clientY: y })
  await evento('mouseup', grafico(), { clientX: x, clientY: y })
  await otraVez(extra)
}
const guardados = () => JSON.parse(localStorage.getItem('rendi_dibujos:ana@prueba.test|propia:AAPL:usd') || 'null')?.dibujos || []
const sembrar = (dibujos) => localStorage.setItem('rendi_dibujos:ana@prueba.test|propia:AAPL:usd', JSON.stringify({ pendiente: false, dibujos }))

describe('lo que encontró la auditoría', () => {
  afterEach(() => { medidas(null); vi.restoreAllMocks() })

  it('el aviso de una línea inclinada se pone en diarias; en 1H, y si empieza y termina el mismo día, se dice por qué no', async () => {
    conAncho(1000)
    sembrar([
      { id: 'dias', tipo: 'tendencia', a: { d: '2026-10-14', mas: 0, precio: 305 }, b: { d: '2026-10-27', mas: 0, precio: 340 } },
      // Dibujada en 1H: de las 10:30 a las 14:30 de Nueva York del 21. Para el
      // aviso (que mira el cierre de cada día) las dos puntas son el mismo día.
      { id: 'mismo', tipo: 'tendencia', a: { d: '2026-10-21', mas: 0, t: utc(10, 21, 14, 30), precio: 305 },
        b: { d: '2026-10-21', mas: 0, t: utc(10, 21, 18, 30), precio: 330 } },
    ])
    await abrir()
    await clickEn(...medioDe('dias', 1000))
    expect(texto(montado.contenedor)).toContain('Avisame si la toca')
    await clickEn(...medioDe('mismo', 1000))
    expect(texto(montado.contenedor)).toContain('Esta línea empieza y termina el mismo día')
    expect(texto(montado.contenedor)).not.toContain('Avisame si la toca')
    await elegirIntervalo('1h')
    await clickEn(...medioDe('dias', 1000))
    expect(texto(montado.contenedor)).toContain('Los avisos de líneas miran el cierre de cada día: para ponerle uno a esta, elegila en velas diarias (1D).')
    expect(texto(montado.contenedor)).not.toContain('Avisame si la toca')
  })

  it('mover una línea sólo de precio en 1H no le cambia el día ni la hora', async () => {
    conAncho(1000)
    const a = { d: '2026-10-14', mas: 0, precio: 305 }
    const b = { d: '2026-10-27', mas: 0, t: utc(10, 27, 15, 30), precio: 340 }
    sembrar([{ id: 'dias', tipo: 'tendencia', a, b }])
    await abrir()
    await elegirIntervalo('1h')
    const [x, y] = medioDe('dias', 1000)
    await evento('mousedown', grafico(), { clientX: x, clientY: y })
    await evento('mousemove', grafico(), { clientX: x, clientY: y + 25 })
    await evento('mouseup', grafico(), { clientX: x, clientY: y + 25 })
    await otraVez()
    const [g] = guardados()
    expect(g.a.precio).toBeLessThan(305)                       // bajó de precio…
    expect({ ...g.a, precio: 0 }).toEqual({ ...a, precio: 0 })  // …y el día quedó (sin inventarle una hora)
    expect({ ...g.b, precio: 0 }).toEqual({ ...b, precio: 0 })  // la hora que tenía, también
  })

  it('con el gráfico corrido hacia atrás, una línea que llega a la vela en curso se dibuja en su lugar', async () => {
    conAncho(300)   // angosto: 1H abre con las últimas 50 velas
    const ultima = horas()[horas().length - 1].t
    sembrar([{ id: 'hasta-hoy', tipo: 'tendencia', a: { d: '2026-10-20', mas: 0, t: utc(10, 20, 13, 30), precio: 330 },
      b: { d: '2026-10-28', mas: 1, t: ultima + 1800, precio: 345 } }])   // la mitad de la vela en curso
    await abrir()
    await elegirIntervalo('1h')
    // Se arrastra el gráfico 150 px a la derecha (hacia atrás): se ven las velas 22 a 74 de 98.
    await evento('mousedown', grafico(), { clientX: 10, clientY: 245 })
    await evento('mousemove', grafico(), { clientX: 160, clientY: 245 })
    await evento('mouseup', grafico(), { clientX: 160, clientY: 245 })
    await otraVez()
    const l = linea('hasta-hoy')
    expect(Number(l.getAttribute('x1'))).toBeCloseTo(((42 - 22) / 52) * 100, 3)
    expect(Number(l.getAttribute('x2'))).toBeCloseTo(((97.5 - 22) / 52) * 100, 3)   // antes: contra el borde (101 %)
  })

  it('al volver a 1H con lo de hace más de un minuto, pide enseguida (no espera al próximo tic)', async () => {
    let ahora = Date.now()
    vi.spyOn(Date, 'now').mockImplementation(() => ahora)
    await abrir()
    await elegirIntervalo('1h')
    await elegirIntervalo('dia')
    const antes = pedidos.length
    ahora += 61_000
    await elegirIntervalo('1h')
    expect(pedidos.slice(antes).filter(r => r.includes('/horas?cada=1h') && r.includes('&desde='))).toHaveLength(1)
  })

  it('con la rueda cerrada, el próximo pedido se calcula con cada respuesta (no se repite el primer plazo)', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    vi.setSystemTime(new Date('2026-10-31T13:58:40Z'))      // sábado 10:58:40: hasta las 11:00 y su margen son 170 s
    respuestas['/tecnico/AAPL/horas?cada=1h&moneda=usd'] = { ...HORA(horas().map(p => ({ ...p, enCurso: undefined }))), en_horario: false }
    await abrir()
    await elegirIntervalo('1h')
    const horasPedidas = () => pedidos.filter(r => r.includes('/horas')).length
    const antes = horasPedidas()
    await enActo(async () => { vi.advanceTimersByTime(170_000); for (let i = 0; i < 4; i++) await Promise.resolve() })
    await otraVez()
    expect(horasPedidas()).toBe(antes + 1)
    // Llegó a las 11:01:30: el próximo va a la próxima media hora (11:30 y su margen), no 170 s después.
    await enActo(async () => { vi.advanceTimersByTime(170_000); for (let i = 0; i < 4; i++) await Promise.resolve() })
    await otraVez()
    expect(horasPedidas()).toBe(antes + 1)
  })

  it('si el servidor llegó a su cupo de descargas de la hora, lo dice (no «no hay velas») y deja reintentar', async () => {
    let tope = true
    respuestas['/tecnico/AAPL/horas?cada=1h&moneda=usd'] = () => (tope ? { disponible: false, motivo: 'tope' } : HORA())
    await abrir()
    await elegirIntervalo('1h')
    expect(texto(montado.contenedor)).toContain('Ahora no pudimos traer las velas de 1 hora de este activo. Probá de nuevo en un rato.')
    expect(texto(montado.contenedor)).not.toContain('No encontramos velas')
    tope = false
    await clic(montado.contenedor, uno(n => n.nodeName === 'BUTTON' && texto(n) === 'Reintentar'))
    await otraVez()
    expect(velas().length).toBeGreaterThan(40)
  })

  it('en 1H, pasar de dólares a pesos vuelve a las últimas velas (el zoom contaba las velas del otro ticker)', async () => {
    conAncho(300)
    respuestas['/tecnico/AAPL?moneda=ars'] = { ...DIA, moneda: 'ars', ticker: 'AAPL.BA' }
    respuestas['/tecnico/AAPL/horas?cada=1h&moneda=ars'] = { ...HORA(), moneda: 'ars', ticker: 'AAPL.BA', mercado: 'byma' }
    await abrir()
    await elegirIntervalo('1h')
    const enCurso = () => uno(n => n.nodeName === 'G' && n.getAttribute?.('data-en-curso') === '')
    await evento('mousedown', grafico(), { clientX: 10, clientY: 245 })
    await evento('mousemove', grafico(), { clientX: 160, clientY: 245 })
    await evento('mouseup', grafico(), { clientX: 160, clientY: 245 })
    await otraVez()
    expect(enCurso()).toBe(null)                 // corrido hacia atrás: la vela en curso quedó afuera
    await clic(montado.contenedor, uno(n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === 'vista'))
    await clic(montado.contenedor, uno(n => n.getAttribute?.('data-moneda') === 'ars'))
    await otraVez()
    expect(pedidos).toContain('/tecnico/AAPL/horas?cada=1h&moneda=ars')
    expect(enCurso()).not.toBe(null)
  })

  it('dibujar un Fibonacci a mano en 1H dice que se apagó el automático de las diarias', async () => {
    conAncho(1000)
    localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS))
    await abrir()
    await elegirIntervalo('1h')
    const boton = (id) => uno(n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === id)
    await clic(montado.contenedor, boton('menu-fibonacci')); await otraVez()
    await clic(montado.contenedor, boton('fibonacci')); await otraVez()
    await clickEn(300, 150)
    await clickEn(700, 60)
    expect(guardados().some(d => d.tipo === 'fibonacci')).toBe(true)
    expect(texto(montado.contenedor)).toContain('Se apagó el Fibonacci automático de las velas diarias')
  })
})

