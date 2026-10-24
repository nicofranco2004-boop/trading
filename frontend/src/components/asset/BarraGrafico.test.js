// La barra de herramientas del gráfico (BarraGrafico.jsx) montada de verdad en
// la lectura técnica (testing/navegadorMinimo.js), con /api/tecnico simulado
// en la frontera (utils/api). Lo que se prueba es lo que ve la persona:
//   · todo prendido de entrada, Fibonacci y Elliott incluidos (Nico, 24/10);
//   · cada botón saca SU capa del gráfico y la vuelve a poner;
//   · lo que se apaga se recuerda al volver (otro montaje = otra visita);
//   · «Volver a lo de fábrica» prende todo y olvida lo guardado;
//   · con el almacenamiento bloqueado o un valor roto, todo prendido y sin romperse.
// Los botones sin datos (sin volumen, sin conteo, sin compras) están en
// LecturaTecnica.test.js, CapaElliott.test.js y CapaFibonacci.test.js.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, clic, medidas } from '../../testing/navegadorMinimo'

const puntos = Array.from({ length: 300 }, (_, i) => {
  const d = new Date(Date.UTC(2025, 9, 1) + i * 86400000).toISOString().slice(0, 10)
  const c = i < 180 ? 100 + i * 0.4 : 172 - (i - 180) * 0.25
  return {
    d, o: c, h: c * 1.01, l: c * 0.99, c, s50: c * 0.98, s200: c * 0.95, rsi: 50 + 10 * Math.sin(i / 9),
    v: 1000 + i, adx: 15 + (i % 20), squeeze: Math.sin(i / 7), squeeze_color: Math.sin(i / 7) > 0 ? 'verde_fuerte' : 'rojo_fuerte',
  }
})
const FIB = {
  disponible: true, n_pivote: 3, dir: 'suba',
  desde: { fecha: puntos[100].d, precio: 140 }, hasta: { fecha: puntos[180].d, precio: 172 },
  ruptura: { fecha: puntos[200].d, cierre: 167, nivel: 168, nivel_fecha: puntos[170].d },
  niveles: [0.236, 0.382, 0.5, 0.618, 0.786].map(n => ({ nivel: n, precio: 172 - n * 32 })),
  retroceso_hoy: 0.45, retroceso_maximo: { valor: 0.46, fecha: puntos[299].d }, entre: [0.382, 0.5],
}
const onda = (o, i, precio, tipo) => ({ onda: o, fecha: puntos[i].d, precio, tipo })
const ELL = {
  disponible: true, n_pivote: 3, alternativo: null,
  principal: {
    tipo: 'impulso', dir: 'suba', ahora: 'onda_5', confianza: 'media',
    ondas: [onda('0', 120, 148, 'pozo'), onda('1', 140, 156, 'pico'), onda('2', 150, 152, 'pozo'),
      onda('3', 170, 168, 'pico'), onda('4', 175, 164, 'pozo')],
    invalida: { precio: 156, lado: 'debajo', por: 'final_1' },
    pautas: [{ id: 'onda2', valor: 0.5, cumple: true }],
  },
}
const DATOS = {
  disponible: true, moneda: 'usd', ticker: 'ZZBH', convertida: null, puntos, fibonacci: FIB, elliott: ELL,
  lectura: { ruedas: 300, fecha: puntos[299].d, precio: puntos[299].c, rsi: 50 },
}
const EVENTOS = {
  eventos: [{ tipo: 'balance', fecha: puntos[250].d, momento: 'despues_del_cierre',
    reaccion: { desde: puntos[250].d, hasta: puntos[251].d, pct: -4.2, cuando: 'al_otro_dia' } }],
}

vi.mock('../../utils/api', () => ({
  api: { get: vi.fn((ruta) => Promise.resolve(ruta.includes('/eventos') ? EVENTOS : DATOS)) },
}))

let LecturaTecnica, almacenReal
beforeAll(async () => {
  instalarNavegadorMinimo()
  almacenReal = globalThis.localStorage
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  vi.stubGlobal('localStorage', almacenReal)
  localStorage.clear()
})

// Tenés el activo: una compra adentro del gráfico y un resultado (tu precio).
const props = { asset: 'ZZBH', pnlPctUsd: 0.1, lotes: [{ entry_date: puntos[260].d, quantity: 2 }] }
const el = () => h(LecturaTecnica, props)
async function dibujar() {
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
}
async function tocar(id) {
  await clic(montado.contenedor, boton(id))
  for (let i = 0; i < 2; i++) await montado.redibujar(el())
}

function nodos(pred) {
  const out = []
  const pila = [montado.contenedor]
  while (pila.length) {
    const n = pila.shift()
    if (pred(n)) out.push(n)
    pila.push(...(n.childNodes || []))
  }
  return out
}
const attr = (n, k) => n.getAttribute?.(k)
const boton = (id) => nodos(n => n.nodeName === 'BUTTON' && attr(n, 'data-capa') === id)[0] || null
const prendido = (id) => attr(boton(id), 'aria-pressed')

// Cómo se reconoce cada capa en el gráfico dibujado.
const SE_VE = {
  vol: () => nodos(n => n.nodeName === 'RECT' && attr(n, 'fill-opacity') === '0.28').length > 0,
  s200: () => nodos(n => n.nodeName === 'PATH' && attr(n, 'stroke') === 'rgb(var(--rendi-accent))' && attr(n, 'stroke-width') === '2.5').length > 0,
  s50: () => nodos(n => n.nodeName === 'PATH' && attr(n, 'stroke') === 'rgb(var(--cat-orange))' && attr(n, 'stroke-width') === '1.6').length > 0,
  fib: () => texto(montado.contenedor).includes('Pico · US$ 172,00'),
  ell: () => texto(montado.contenedor).includes('Dejaría de valer · US$ 156,00'),
  rsi: () => nodos(n => n.nodeName === 'SVG' && attr(n, 'viewBox') === '0 0 1000 64').length > 0,
  fuerza: () => nodos(n => n.nodeName === 'SVG' && attr(n, 'viewBox') === '0 0 1000 56').length > 0,
  eventos: () => nodos(n => attr(n, 'role') === 'group' && attr(n, 'aria-label') === 'Balances y dividendos').length > 0,
  marcas: () => nodos(n => (attr(n, 'title') || '').startsWith('Compraste el')).length > 0,
  prom: () => nodos(n => n.nodeName === 'LINE' && attr(n, 'stroke-dasharray') === '6 5').length > 0,
}
const CAPAS = Object.keys(SE_VE)

describe('la barra de herramientas del gráfico', () => {
  it('todo prendido de entrada, Fibonacci y Elliott incluidos', async () => {
    await dibujar()
    for (const id of CAPAS) {
      expect(prendido(id), id).toBe('true')
      expect(SE_VE[id](), id).toBe(true)
    }
    expect(prendido('linea')).toBe('true')
    expect(prendido('velas')).toBe('false')
    expect(prendido('medir')).toBe('false')     // medir es una herramienta: se prende para usarla
    // La leyenda de chips de abajo ya no está: un solo lugar para prender cada cosa.
    expect(nodos(n => attr(n, 'aria-label') === 'Qué líneas mostrar')).toHaveLength(0)
    expect(nodos(n => attr(n, 'role') === 'toolbar' && attr(n, 'aria-label') === 'Herramientas del gráfico')).toHaveLength(1)
  })

  for (const id of CAPAS) {
    it(`«${id}»: el botón saca su capa y la vuelve a poner, sin tocar las otras`, async () => {
      await dibujar()
      await tocar(id)
      expect(prendido(id)).toBe('false')
      expect(SE_VE[id]()).toBe(false)
      for (const otra of CAPAS.filter(k => k !== id)) expect(SE_VE[otra](), `${otra} al apagar ${id}`).toBe(true)
      await tocar(id)
      expect(prendido(id)).toBe('true')
      expect(SE_VE[id]()).toBe(true)
    })
  }

  it('cada botón tiene su nombre (en el celular a la vista; en compu, en el globo)', async () => {
    await dibujar()
    const nombres = {
      linea: 'Línea', velas: 'Velas', vol: 'Volumen', s200: 'Promedio 200 días', s50: 'Promedio 50 días',
      fib: 'Fibonacci', ell: 'Ondas de Elliott', rsi: 'RSI', fuerza: 'Fuerza de la tendencia',
      eventos: 'Balances y dividendos', marcas: 'Tus compras y ventas', prom: 'Tu precio promedio',
      medir: 'Medir entre dos puntos', fabrica: 'Volver a lo de fábrica',
    }
    for (const [id, nombre] of Object.entries(nombres)) expect(texto(boton(id)), id).toContain(nombre)
    expect(texto(boton('vol'))).toContain('Prendido. Tocá para apagarlo.')
    await tocar('vol')
    expect(texto(boton('vol'))).toContain('Apagado. Tocá para prenderlo.')
  })

  it('lo que se apaga se recuerda al volver', async () => {
    await dibujar()
    await tocar('vol')
    await tocar('ell')
    await tocar('velas')
    expect(JSON.parse(localStorage.getItem('rendi_grafico_capas'))).toMatchObject({ vol: false, ell: false, fib: true })
    await montado.desmontar()
    await dibujar()                             // otra visita a la ficha
    expect(prendido('vol')).toBe('false')
    expect(prendido('ell')).toBe('false')
    expect(prendido('fib')).toBe('true')
    expect(prendido('velas')).toBe('true')
    expect(SE_VE.vol()).toBe(false)
    expect(SE_VE.ell()).toBe(false)
    expect(SE_VE.fib()).toBe(true)
  })

  it('«Volver a lo de fábrica» prende todo, vuelve a la línea y olvida lo guardado', async () => {
    await dibujar()
    for (const id of ['vol', 'fib', 'ell', 'rsi', 'prom']) await tocar(id)
    await tocar('velas')
    await tocar('medir')
    expect(texto(boton('fabrica'))).toContain('Prende todo de nuevo')
    await tocar('fabrica')
    for (const id of CAPAS) {
      expect(prendido(id), id).toBe('true')
      expect(SE_VE[id](), id).toBe(true)
    }
    expect(prendido('linea')).toBe('true')
    expect(prendido('medir')).toBe('false')
    expect(localStorage.getItem('rendi_grafico_capas')).toBeNull()
    expect(localStorage.getItem('rendi_grafico_tipo')).toBeNull()
    expect(texto(boton('fabrica'))).toContain('Ya está todo como viene')
    await montado.desmontar()
    await dibujar()
    for (const id of CAPAS) expect(prendido(id), id).toBe('true')
  })

  it('medir es una herramienta: se prende, se usa y se apaga; no hay botón de agrandar (siempre ampliado)', async () => {
    await dibujar()
    await tocar('medir')
    expect(prendido('medir')).toBe('true')
    expect(texto(montado.contenedor)).toContain('Tocá cualquier punto del gráfico para empezar a medir')
    await tocar('medir')
    expect(texto(montado.contenedor)).not.toContain('Tocá cualquier punto del gráfico')
    expect(boton('grande')).toBeNull()
    // Medir no se guarda: la próxima vez el gráfico arranca normal.
    expect(localStorage.getItem('rendi_grafico_capas')).toBeNull()
  })

  it('con el almacenamiento bloqueado (modo privado): todo prendido y los botones andan igual', async () => {
    const roto = () => { throw new Error('SecurityError') }
    vi.stubGlobal('localStorage', { getItem: roto, setItem: roto, removeItem: roto, clear: () => {} })
    await dibujar()
    for (const id of CAPAS) expect(prendido(id), id).toBe('true')
    await tocar('vol')
    expect(SE_VE.vol()).toBe(false)
    await tocar('fabrica')
    expect(SE_VE.vol()).toBe(true)
  })

  it('un valor guardado roto o de otra versión no apaga nada de más', async () => {
    localStorage.setItem('rendi_grafico_capas', '{esto no es json')
    await dibujar()
    for (const id of CAPAS) expect(prendido(id), id).toBe('true')
    await montado.desmontar()
    // Sólo cuenta un sí/no de una capa conocida: lo demás, de fábrica.
    localStorage.setItem('rendi_grafico_capas', JSON.stringify({ vol: false, ell: 'false', capaQueYaNoExiste: false }))
    await dibujar()
    expect(prendido('vol')).toBe('false')
    for (const id of CAPAS.filter(k => k !== 'vol')) expect(prendido(id), id).toBe('true')
  })

  it('rótulos de capas distintas que se pisan: se esconde el menos importante, no la capa', async () => {
    // Todos los rótulos en el mismo lugar (el peor caso): quedan sólo los de
    // más prioridad, los números de las ondas; los niveles del Fibonacci y la
    // raya de Elliott se esconden, pero sus rayas siguen dibujadas.
    medidas(n => (n.getAttribute('data-rotulo') != null ? { left: 100, top: 50, width: 80, height: 14 } : null))
    try {
      await dibujar()
      const rotulos = () => nodos(n => attr(n, 'data-rotulo') != null)
      const visibles = () => rotulos().filter(n => attr(n, 'data-tapado') == null).map(n => texto(n))
      const tapados = () => rotulos().filter(n => attr(n, 'data-tapado') != null)
      expect(visibles()).toEqual(['1'])                     // la onda 1: la primera de más prioridad
      expect(tapados().some(n => texto(n).startsWith('Pico ·'))).toBe(true)
      expect(tapados().every(n => n.style.visibility === 'hidden')).toBe(true)
      expect(SE_VE.fib()).toBe(true)                         // la capa sigue: el texto está, escondido
      // Sin Elliott, el Fibonacci recupera su rótulo de más arriba.
      await tocar('ell')
      expect(visibles()).toHaveLength(1)
      expect(visibles()[0]).toMatch(/·/)
      expect(tapados().every(n => attr(n, 'data-rotulo') === '4')).toBe(true)
    } finally {
      medidas(null)
    }
  })
})
