// La lectura técnica montada de verdad (testing/navegadorMinimo.js), con los
// pedidos al servidor simulados en la frontera (utils/api). Lo que se prueba es
// el ARMADO que las cuentas (utils/tecnico.test.js) no ven:
//   · con velas: las tarjetas, la leyenda y "contra tu precio" con el resultado
//     de la ficha;
//   · en pesos, el aviso de que el dólar cambia la lectura;
//   · sin velas (o si el pedido falla): el gráfico de 30 días de siempre.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { CAPAS_TODAS } from './BarraGrafico'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, buscar, buscarBoton, clic, enActo } from '../../testing/navegadorMinimo'
import { elegirEnLaVista, opcionesDeLaVista, periodoElegido } from '../../testing/menuGrafico'

function puntos(n, f) {
  return Array.from({ length: n }, (_, i) => ({
    d: new Date(Date.UTC(2025, 0, 1) + i * 86400000).toISOString().slice(0, 10),
    c: f(i), s50: f(i) * 1.02, s200: f(i) * 1.05, rsi: 40,
  }))
}
const USD = {
  disponible: true, moneda: 'usd', ticker: 'AAPL', convertida: null,
  puntos: puntos(504, i => 250 - i * 0.03),
  lectura: { ruedas: 760, fecha: '2026-10-21', precio: 235, media50: 241, dist_media50: -2.5,
    media200: 250, dist_media200: -6, tendencia: 'bajista', pendiente_media200: -1, rsi: 38, dist_maximo_12m: -14, anio_completo: true },
}
const ARS = {
  ...USD, moneda: 'ars', ticker: 'AAPL.BA',
  lectura: { ...USD.lectura, dist_media200: 24, tendencia: 'alcista', pendiente_media200: 3 },
}

// Con la fuerza de la tendencia: el ADX pasó 23 ayer con el Squeeze en verde.
const CON_FUERZA = {
  ...USD,
  puntos: USD.puntos.map((p, i) => ({ ...p, adx: 10 + i * 0.03, squeeze: Math.sin(i / 9), squeeze_color: Math.sin(i / 9) > 0 ? 'verde_fuerte' : 'rojo_fuerte' })),
  lectura: { ...USD.lectura, adx: 24.6, adx_pendiente: 1.8, adx_cruce: { tipo: 'paso_arriba', hace: 1, squeeze: 1 },
    squeeze: 0.8, squeeze_color: 'verde_fuerte', squeeze_activo: false },
}

let respuestas
vi.mock('../../utils/api', () => ({
  getClientContext: () => null,   // mirando tu propia cuenta (no la de un cliente)
  api: {
    get: vi.fn((ruta) => {
      const clave = Object.keys(respuestas).find(k => ruta.startsWith(k))
      const r = clave ? respuestas[clave] : []
      return r instanceof Error ? Promise.reject(r) : Promise.resolve(r)
    }),
  },
}))

let LecturaTecnica, ladoGlobo
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica, ladoGlobo } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
// De fábrica el gráfico viene limpio (precio, promedio de 200 y volumen). Estas
// pruebas miran las demás capas: arrancan con todas prendidas, como quien las
// prende desde «Indicadores» (lo que se prende queda guardado así).
beforeEach(() => { try { localStorage.setItem('rendi_grafico_capas', JSON.stringify(CAPAS_TODAS)) } catch { /* sin almacenamiento */ } })
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()   // lo que apaga una prueba no pasa a la siguiente
})

// Un botón de la barra de herramientas, por su capa (data-capa).
function botonDe(id) {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === id) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
function porEtiqueta(parte) {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if ((n.getAttribute?.('aria-label') || '').startsWith(parte)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
function contar(pred) {
  let k = 0
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (pred(n)) k++
    pila.push(...(n.childNodes || []))
  }
  return k
}
function buscarRol(rol, parte) {
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (n.getAttribute?.('role') === rol && texto(n).includes(parte)) return n
    pila.push(...(n.childNodes || []))
  }
  return null
}
// Una vela es un <g> con su mecha (line) y su cuerpo (rect).
const velasDibujadas = () => contar(n => n.nodeName === 'G' && (n.childNodes || []).some(c => c.nodeName === 'RECT'))
const puntosDeCompra = () => contar(n => n.nodeName === 'SPAN' && (n.getAttribute?.('title') || '').startsWith('Compraste el'))
async function otraVez(props) {
  for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', ...props }))
}

async function dibujar(props) {
  const el = () => h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', ...props })
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
}

describe('LecturaTecnica', () => {
  it('con velas: tarjetas en castellano, leyenda y contra tu precio', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    const t = await dibujar({ pnlPctUsd: -0.081, lotes: [{ entry_date: '2025-03-01', quantity: 5 }] })
    expect(t).toContain('Largo plazo')
    expect(t).toContain('Bajista')
    expect(t).toContain('Promedio 200 días')
    expect(t).toContain('Tu precio promedio')
    expect(t).toContain('Contra lo que pagaste')
    expect(t).toContain('Perdés 8,1%')
    expect(t).toContain('no es una recomendación')
    expect(t).not.toContain('En pesos la tendencia es otra')
  })

  it('en pesos avisa que el dólar cambia la lectura', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    await dibujar({ pnlPctUsd: 0.1 })
    await elegirEnLaVista(montado.contenedor, 'Pesos')
    // Pesos se piden recién ahora: que vuelva el pedido.
    for (let i = 0; i < 4; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    const t = texto(montado.contenedor)
    expect(t).toContain('En pesos, la tendencia es distinta que en dólares')
    expect(t).toContain('Alcista')
  })

  it('sin velas todavía: el gráfico de 30 días de siempre', async () => {
    respuestas = { '/tecnico/': { disponible: false }, '/prices/history': { points: [] } }
    const t = await dibujar({})
    expect(t).toContain('últimos 30 días')
    expect(t).not.toContain('Análisis técnico')
  })

  it('si el pedido falla lo dice y deja reintentar (no muestra otro gráfico)', async () => {
    respuestas = { '/tecnico/': new Error('caído'), '/prices/history': { points: [] } }
    const t = await dibujar({})
    expect(t).toContain('No se pudo cargar el gráfico')
    expect(t).not.toContain('últimos 30 días')
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Reintentar'))
    for (let i = 0; i < 3; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA' }))
    expect(texto(montado.contenedor)).toContain('Largo plazo')
  })

  it('la línea de tu precio usa el dólar de compra; sin ese dato no se dibuja y lo dice', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    let t = await dibujar({ pnlPctUsd: 0.4, pnlPctLinea: 0.1 })
    expect(botonDe('prom').getAttribute('aria-pressed')).toBe('true')
    expect(t).toContain('Tu precio')               // el cartel de la línea, en la columna de precios
    expect(t).toContain('Ganás 40,0%')            // la tarjeta: el mismo resultado de arriba
    await montado.desmontar(); montado = null
    t = await dibujar({ pnlPctUsd: 0.4, pnlPctLinea: null, lineaSinTc: true })
    expect(botonDe('prom').getAttribute('aria-disabled')).toBe('true')
    expect(texto(botonDe('prom'))).toContain('A alguna de tus compras le falta la cotización del dólar de ese día')
    expect(t).toContain('le falta la cotización del dólar de ese día')
  })

  it('tus compras y ventas: sin ninguna, el botón deshabilitado con el porqué', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    await dibujar({ pnlPctUsd: 0.1 })
    expect(botonDe('marcas').getAttribute('aria-disabled')).toBe('true')
    expect(texto(botonDe('marcas'))).toContain('No hay compras ni ventas tuyas de este activo')
    await montado.desmontar(); montado = null
    const ultimo = USD.puntos[USD.puntos.length - 10].d
    await dibujar({ pnlPctUsd: 0.1, lotes: [{ entry_date: ultimo, quantity: 1 }] })
    expect(botonDe('marcas').getAttribute('aria-pressed')).toBe('true')
    expect(puntosDeCompra()).toBe(1)
    await clic(montado.contenedor, botonDe('marcas'))
    await otraVez({ pnlPctUsd: 0.1, lotes: [{ entry_date: ultimo, quantity: 1 }] })
    expect(puntosDeCompra()).toBe(0)
  })

  it('pide pesos recién al tocarlos, y una acción argentina pide su precio local', async () => {
    const { api } = await import('../../utils/api')
    api.get.mockClear()
    respuestas = { '/tecnico/GGAL?moneda=usd&local=1': USD, '/tecnico/GGAL?moneda=ars&local=1': ARS }
    const el = () => h(LecturaTecnica, { asset: 'GGAL', accionLocal: true })
    montado = await montar(el())
    for (let i = 0; i < 4; i++) await montado.redibujar(el())
    const todos = () => api.get.mock.calls.map(c => c[0]).filter(r => r.startsWith('/tecnico'))
    const pedidos = () => todos().filter(r => !r.includes('/eventos') && !r.includes('/dibujos'))
    expect(pedidos()).toEqual(['/tecnico/GGAL?moneda=usd&local=1'])
    await elegirEnLaVista(montado.contenedor, 'Pesos')
    for (let i = 0; i < 4; i++) await montado.redibujar(el())
    expect(pedidos()).toEqual(['/tecnico/GGAL?moneda=usd&local=1', '/tecnico/GGAL?moneda=ars&local=1'])
    // Los balances y dividendos, también por moneda y con la acción local.
    expect(todos().filter(r => r.includes('/eventos'))).toEqual(
      ['/tecnico/GGAL/eventos?moneda=usd&local=1', '/tecnico/GGAL/eventos?moneda=ars&local=1'])
  })

  it('en pesos, tu precio sale de lo que pagaste en pesos (con comisiones)', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    // Último cierre en pesos: 250 − 503 × 0,03 = 234,91. 10 unidades valen
    // 2.349,10; pagaste 2.000 + 100 de comisión → +11,9 %.
    await dibujar({ pnlPctUsd: 0.5, costoPesos: { invertido: 2100, cantidad: 10 } })
    await elegirEnLaVista(montado.contenedor, 'Pesos')
    for (let i = 0; i < 4; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.5, costoPesos: { invertido: 2100, cantidad: 10 } }))
    expect(texto(montado.contenedor)).toContain('Ganás 11,9%')
  })

  it('con el botón Velas dibuja velas diarias, y semanales sólo si se eligen', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    await dibujar({ pnlPctUsd: 0.1 })
    expect(velasDibujadas()).toBe(0)
    expect(botonDe('linea').getAttribute('aria-pressed')).toBe('true')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Velas'))
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    expect(botonDe('velas').getAttribute('aria-pressed')).toBe('true')
    expect(botonDe('linea').getAttribute('aria-pressed')).toBe('false')
    expect(velasDibujadas()).toBeGreaterThan(200)     // toda la historia, una vela por día
    expect(texto(montado.contenedor)).not.toContain('Cada vela es una semana')
    // Con toda la historia siguen siendo diarias; las semanales se eligen en el
    // menú de las velas («1D», como TradingView).
    expect(texto(montado.contenedor)).toContain('Cada vela es un día')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, '1D'))
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Semanales'))
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    expect(texto(montado.contenedor)).toContain('Cada vela es una semana')
  })

  it('siempre ampliado, dentro de la ficha: sin Agrandar/Achicar ni pantalla completa (Nico, 24/10)', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    await dibujar({ pnlPctUsd: 0.1 })
    const seccion = buscar(montado.contenedor, 'section')
    expect(seccion.getAttribute('role')).toBeNull()
    expect(seccion.getAttribute('class')).not.toContain('fixed')
    expect(buscarBoton(montado.contenedor, 'Agrandar')).toBeNull()
    expect(buscarBoton(montado.contenedor, 'Achicar')).toBeNull()
    // El alto del modo ampliado de antes en compu; en el celular, uno que no se come la pantalla.
    const area = porEtiqueta('Precio con su promedio')
    expect(area.getAttribute('class')).toContain('sm:h-[58vh]')
    expect(area.getAttribute('class')).toMatch(/(^| )h-\[42vh\]/)
    // Esc ya no hace nada raro (no hay nada que achicar) y la página no queda trabada.
    await enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape' })) })
    expect(document.body.style.overflow).not.toBe('hidden')
  })

  it('«Pantalla completa» pone el gráfico sobre toda la página; «Achicar» y Esc vuelven a la ficha (Nico, 28/10)', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    await dibujar({ pnlPctUsd: 0.1 })
    const otra = () => montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    const seccion = () => buscar(montado.contenedor, 'section')
    const area = () => porEtiqueta('Precio con su promedio')
    const altoNormal = area().getAttribute('class')
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Pantalla completa'))
    await otra()
    expect(seccion().getAttribute('role')).toBe('dialog')
    expect(seccion().getAttribute('class')).toContain('fixed inset-0')
    expect(document.body.style.overflow).toBe('hidden')        // la página de atrás no se mueve
    expect(area().getAttribute('class')).toContain('sm:h-[74vh]')   // el gráfico, más alto
    expect(area().getAttribute('class')).not.toEqual(altoNormal)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Achicar'))
    await otra()
    expect(seccion().getAttribute('role')).toBeNull()
    expect(document.body.style.overflow).not.toBe('hidden')
    // Esc también achica…
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Pantalla completa'))
    await otra()
    const esc = () => enActo(() => { window.dispatchEvent(Object.assign(new Event('keydown'), { key: 'Escape' })) })
    await esc(); await otra()
    expect(seccion().getAttribute('role')).toBeNull()
    // …pero si hay algo a medio dibujar, el primer Esc cancela eso y el gráfico sigue grande.
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Pantalla completa'))
    await otra()
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Medir entre dos puntos'))
    await otra()
    await esc(); await otra()
    expect(seccion().getAttribute('role')).toBe('dialog')
    await esc(); await otra()
    expect(seccion().getAttribute('role')).toBeNull()
  })

  it('el volumen: barras abajo del precio y un botón para apagarlas; sin datos, no aparece', async () => {
    const conVolumen = { ...USD, puntos: USD.puntos.map((p, i) => ({ ...p, v: 1000 + i })) }
    respuestas = { '/tecnico/AAPL?moneda=usd': conVolumen, '/tecnico/AAPL?moneda=ars': ARS }
    const t = await dibujar({ pnlPctUsd: 0.1 })
    expect(t).toContain('Volumen')
    const barras = () => {
      let n = 0
      const pila = [montado.contenedor]
      while (pila.length) {
        const x = pila.shift()
        if (x.nodeName === 'RECT' && x.getAttribute?.('fill-opacity') === '0.2') n++
        pila.push(...(x.childNodes || []))
      }
      return n
    }
    expect(barras()).toBeGreaterThan(200)          // un año de ruedas, una barra por día
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Volumen'))
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    expect(barras()).toBe(0)
  })

  it('Bandas de Bollinger: prendidas de entrada; el botón las apaga junto con su tarjeta', async () => {
    const conBandas = {
      ...USD,
      puntos: USD.puntos.map((p, i) => (i < 19 ? p : { ...p, bb_arriba: p.c * 1.04, bb_abajo: p.c * 0.96 })),
      lectura: { ...USD.lectura, bb_arriba: 240, bb_abajo: 226, bb_posicion: 0.64, bb_ancho_relativo: 0.5, mov_dia: 2.04, mov_mes: 9.4 },
    }
    respuestas = { '/tecnico/AAPL?moneda=usd': conBandas, '/tecnico/AAPL?moneda=ars': ARS }
    const relleno = () => {
      let n = 0
      const pila = [montado.contenedor]
      while (pila.length) {
        const x = pila.shift()
        if (x.nodeName === 'PATH' && x.getAttribute?.('fill-opacity') === '0.045') n++
        pila.push(...(x.childNodes || []))
      }
      return n
    }
    const t = await dibujar({ pnlPctUsd: 0.1 })
    expect(t).toContain('Bandas de Bollinger')        // el botón de la leyenda
    expect(t).toContain('más angostas que lo habitual')
    expect(t).toContain('Entre las bandas')           // la tarjeta, de entrada
    expect(t).toContain('Cuánto se mueve')           // ésta va siempre
    expect(t).toContain('alrededor de 2,0%')
    expect(relleno()).toBe(1)
    await clic(montado.contenedor, buscarBoton(montado.contenedor, 'Bandas de Bollinger'))
    for (let i = 0; i < 2; i++) await montado.redibujar(h(LecturaTecnica, { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.1 }))
    const t2 = texto(montado.contenedor)
    expect(t2).not.toContain('Entre las bandas')
    expect(relleno()).toBe(0)
  })

  it('una banda de abajo negativa (un salto brusco) no lleva el eje abajo de 0', async () => {
    const salto = {
      ...USD,
      puntos: USD.puntos.map((p, i) => (i < 480 ? p : { ...p, bb_arriba: p.c * 1.6, bb_abajo: -5.44 })),
      lectura: { ...USD.lectura, bb_arriba: 400, bb_abajo: -5.44, bb_posicion: 0.6, bb_ancho_relativo: 3 },
    }
    respuestas = { '/tecnico/AAPL?moneda=usd': salto, '/tecnico/AAPL?moneda=ars': ARS }
    // La prueba de las velas deja guardado «velas»: ésta mira la línea.
    try { localStorage.setItem('rendi_grafico_tipo', 'linea') } catch { /* sin almacenamiento */ }
    await dibujar({ pnlPctUsd: 0.1 })
    // La línea del precio sigue ocupando el alto del gráfico (con el eje hasta
    // −5,44 y +400 quedaba aplastada en una franja finita).
    const pila = [montado.contenedor]
    let linea = null
    while (pila.length) {
      const x = pila.shift()
      if (x.nodeName === 'PATH' && x.getAttribute?.('stroke-width') === '1.7') linea = x
      pila.push(...(x.childNodes || []))
    }
    const ys = [...linea.getAttribute('d').matchAll(/,(-?[\d.]+)/g)].map(m => Number(m[1]))
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThan(100)   // de 260 de alto
  })

  it('sin volumen en los datos el botón queda deshabilitado y, al tocarlo, dice por qué', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    await dibujar({ pnlPctUsd: 0.1 })
    const b = botonDe('vol')
    expect(b.getAttribute('aria-disabled')).toBe('true')
    expect(b.getAttribute('aria-pressed')).toBeNull()
    expect(texto(montado.contenedor)).not.toContain('Volumen: No hay datos de volumen para este activo.Cerrar')
    await clic(montado.contenedor, b)
    await otraVez({ pnlPctUsd: 0.1 })
    const aviso = buscarRol('status', 'Volumen: ')
    expect(texto(aviso)).toContain('Volumen: No hay datos de volumen para este activo.')
    // Tocar otro botón lo saca.
    await clic(montado.contenedor, botonDe('s50'))
    await otraVez({ pnlPctUsd: 0.1 })
    expect(buscarRol('status', 'Volumen: ')).toBeNull()
  })

  it('sin tenencia no dibuja tu precio', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD, '/tecnico/AAPL?moneda=ars': ARS }
    const t = await dibujar({ pnlPctUsd: null })
    expect(t).not.toContain('Contra lo que pagaste')
    expect(t).not.toContain('Tu precio·')
    // Sin tenerlo ni haberlo operado, la barra no muestra nada tuyo (Nico, 24/10).
    expect(botonDe('prom')).toBeNull()
    expect(botonDe('marcas')).toBeNull()
    expect(t).not.toContain('Tu precio promedio')
    expect(t).not.toContain('Tus compras y ventas')
  })

  it('vendiste todo: tus compras y ventas siguen, tu precio promedio no', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': USD }
    const ultimo = USD.puntos[USD.puntos.length - 10].d
    await dibujar({ pnlPctUsd: null, operaciones: [{ date: ultimo, type: 'SELL', quantity: 1 }] })
    expect(botonDe('marcas')).not.toBeNull()
    expect(botonDe('prom')).toBeNull()
  })

  it('fuerza de la tendencia: panel del ADX con el Squeeze y la tarjeta con su frase destacada', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': CON_FUERZA }
    const t = await dibujar({ pnlPctUsd: null })
    expect(t).toContain('Fuerza de la tendencia (ADX)')
    expect(t).toContain('al alza')
    expect(t).toContain('La tendencia se fortalece')
    expect(t).toContain('la fuerza de la tendencia (ADX) superó 23 con el Squeeze (indica si el precio empuja al alza o a la baja) en verde: el precio viene subiendo con fuerza.')
    // El panel: una barra por día con Squeeze y la línea del ADX.
    const nodos = (n) => [n, ...(n.childNodes || []).flatMap(nodos)]
    const panel = nodos(montado.contenedor).find(n => n.getAttribute?.('aria-label')?.startsWith('Fuerza de la tendencia'))
    expect(panel.getAttribute('aria-label')).toContain('(ADX): 25, con la línea de 23')
    const barras = nodos(montado.contenedor).find(n => n.getAttribute?.('aria-label')?.startsWith('Barras del Squeeze'))
    expect(nodos(barras).filter(n => n.nodeName === 'RECT').length).toBeGreaterThan(200)
  })

  it('sin ADX (pocos días) no dibuja el panel y la tarjeta dice que faltan datos', async () => {
    respuestas = { '/tecnico/AAPL?moneda=usd': { ...USD, lectura: { ...USD.lectura, ruedas: 20, adx: null, squeeze: null } } }
    const t = await dibujar({ pnlPctUsd: null })
    expect(t).not.toContain('Fuerza de la tendencia (ADX)')
    expect(t).toContain('Para calcularla hacen falta unos 28 días de mercado y este activo tiene 20')
  })

  it('el globo del mouse nunca se sale del gráfico (celular: gráfico de 250 px, globo de 200)', () => {
    const ancho = 250, globo = 200
    for (let pct = 0; pct <= 100; pct += 1) {
      const izq = ladoGlobo(pct, ancho, globo)
      expect(izq).toBeGreaterThanOrEqual(0)
      expect(izq + globo).toBeLessThanOrEqual(ancho + 68)
    }
    // En la compu (gráfico ancho) va pegado al punto: a la derecha y, cerca del borde, a la izquierda.
    expect(ladoGlobo(50, 900, 200)).toBe(462)
    expect(ladoGlobo(95, 900, 200)).toBe(855 - 212)
  })
})
