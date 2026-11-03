// Pantalla completa del gráfico técnico y el cambio de intervalo (Nico, 31/10:
// «si estoy en pantalla completa y quiero cambiar de 1 día a 4 horas o 1 hora,
// que no me saque del gráfico. Tenía la pantalla ampliada y al cambiar se
// achicó, cambió, y ahí se agrandó de vuelta»). Montado de verdad
// (testing/navegadorMinimo.js), con el pedido de las velas de 4 horas DEMORADO
// a propósito: con las velas ya guardadas el salto no se veía (por eso le
// pasaba a veces sí y a veces no).
import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, clic, enActo } from '../../testing/navegadorMinimo'

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
const utc = (m, d, hh, mm = 0) => Date.UTC(2026, m - 1, d, hh, mm) / 1000
const CUATRO = (() => {
  const puntos = []
  for (const d of [26, 27, 28, 29]) {
    for (let k = 0; k < 2; k++) {
      const c = 300 + puntos.length
      puntos.push({ d: `2026-10-${d}`, t: utc(10, d, 13 + 4 * k, 30), o: c - 0.2, h: c + 0.6, l: c - 0.6, c, v: 100 })
    }
  }
  return {
    asset: 'AAPL', moneda: 'usd', cada: '4h', disponible: true, ticker: 'AAPL', convertida: null, mercado: 'us',
    sesion: { abre: 570, cierra: 960, desfase: -240, todos_los_dias: false, velas_por_dia: 2 },
    en_horario: false, actualizada: new Date().toISOString(), puntos,
  }
})()

let respuestas
vi.mock('../../utils/api', () => ({
  api: {
    get: vi.fn((ruta) => {
      const clave = Object.keys(respuestas).filter(k => ruta.startsWith(k)).sort((a, b) => b.length - a.length)[0]
      const r = clave ? (typeof respuestas[clave] === 'function' ? respuestas[clave](ruta) : respuestas[clave]) : []
      return r instanceof Promise ? r : Promise.resolve(r)
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

let montado, soltarCuatro
beforeEach(() => {
  // Las de 4 horas no llegan hasta que la prueba lo diga: el caso lento.
  const demorado = new Promise(r => { soltarCuatro = () => r(CUATRO) })
  respuestas = {
    '/tecnico/AAPL?moneda=usd': DIA,
    '/tecnico/AAPL/horas?cada=4h&moneda=usd': () => demorado,
  }
  localStorage.setItem('rendi_grafico_tipo', 'velas')
  localStorage.setItem('rendi_user', JSON.stringify({ email: 'ana@prueba.test' }))
})
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()
})

const props = { asset: 'AAPL', symbolMiniChart: 'AAPL' }
const otraVez = async () => { for (let i = 0; i < 4; i++) await montado.redibujar(h(LecturaTecnica, props)) }
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
const clase = (n) => n?.getAttribute?.('class') || ''
const seccion = () => uno(n => n.nodeName === 'SECTION' && n.getAttribute?.('aria-label') === 'Análisis técnico')
const boton = (capa) => uno(n => n.nodeName === 'BUTTON' && n.getAttribute?.('data-capa') === capa)

// El alto que pide un nodo («h-[68vh] min-h-72 sm:h-[74vh]»): lo único que
// este navegador de prueba no mide, así que se compara lo pedido.
const alto = (n) => clase(n).split(/\s+/).filter(c => /^(sm:)?(min-)?h-/.test(c)).sort().join(' ')
const areaDelGrafico = () => uno(n => n.nodeName === 'DIV' && clase(n).startsWith('relative mr-[72px]') && clase(n).includes('touch-pan-y'))
const cargandoGrafico = () => uno(n => n.getAttribute?.('role') === 'status' && n.getAttribute('aria-label') === 'Cargando gráfico')

async function abrir() {
  montado = await montar(h(LecturaTecnica, props))
  await otraVez()
}
async function elegirCuatroHoras() {
  await clic(montado.contenedor, boton('intervalo'))
  await clic(montado.contenedor, uno(n => n.getAttribute?.('data-intervalo') === '4h'))
  await otraVez()
}
async function lleganLasCuatroHoras() {
  await enActo(async () => { soltarCuatro(); for (let i = 0; i < 4; i++) await Promise.resolve() })
  await otraVez()
}

describe('pantalla completa y el cambio de intervalo', () => {
  it('ampliado, pasar de 1D a 4H con las velas tardando no lo achica: sigue ampliado y del mismo alto durante y después', async () => {
    await abrir()
    await clic(montado.contenedor, boton('pantalla'))
    await otraVez()
    expect(seccion().getAttribute('role')).toBe('dialog')
    const altoAmpliado = alto(areaDelGrafico())
    expect(altoAmpliado).toContain('h-[68vh]')

    await elegirCuatroHoras()
    // Mientras llegan: sigue en pantalla completa y el gris ocupa lo mismo que
    // el gráfico ampliado (antes, 22rem: «se achicó»).
    expect(seccion().getAttribute('role')).toBe('dialog')
    expect(boton('pantalla').getAttribute('aria-pressed')).toBe('true')
    expect(cargandoGrafico()).not.toBeNull()
    expect(alto(cargandoGrafico())).toBe(altoAmpliado)

    await lleganLasCuatroHoras()
    expect(cargandoGrafico()).toBeNull()
    expect(seccion().getAttribute('role')).toBe('dialog')
    expect(boton('pantalla').getAttribute('aria-pressed')).toBe('true')
    expect(alto(areaDelGrafico())).toBe(altoAmpliado)
  })

  it('sin ampliar, el gris de la carga también ocupa lo mismo que el gráfico (la página no salta)', async () => {
    await abrir()
    expect(seccion().getAttribute('role')).toBeNull()
    const altoNormal = alto(areaDelGrafico())
    await elegirCuatroHoras()
    expect(alto(cargandoGrafico())).toBe(altoNormal)
    await lleganLasCuatroHoras()
    expect(alto(areaDelGrafico())).toBe(altoNormal)
  })
})
