// «La lectura de hoy» y las tarjetas en pestañas, montadas de verdad dentro de
// LecturaTecnica (testing/navegadorMinimo.js), con el servidor simulado en la
// frontera (utils/api): lo que se ve en la ficha, lo que se ve en la pestaña
// «Gráfico» de Análisis técnico (`soloGrafico`) y el ojito de los saldos.
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from 'vitest'
import { createElement as h } from 'react'
import { instalarNavegadorMinimo, montar, texto, clic } from '../../testing/navegadorMinimo'

const dia = (i) => new Date(Date.UTC(2025, 0, 1) + i * 86400000).toISOString().slice(0, 10)
// Sube parejo: arriba de los dos promedios desde el día 400.
const PUNTOS = Array.from({ length: 504 }, (_, i) => ({
  d: dia(i), c: 100 + i * 0.1, s50: i < 400 ? 200 : 100 + i * 0.09, s200: i < 400 ? 200 : 100 + i * 0.08, rsi: 60,
}))
const LECTURA = {
  ruedas: 760, fecha: '2026-10-29', precio: 150, media50: 145, dist_media50: 3.4, media200: 140, dist_media200: 7.1,
  pendiente_media200: 1, rsi: 62, dist_maximo_12m: -2, anio_completo: true, maximo_12m: 153, minimo_12m: 120,
  adx: 27, adx_pendiente: 1, squeeze: 1, squeeze_color: 'verde_fuerte', bb_arriba: 155, bb_abajo: 140, bb_posicion: 0.6,
}
const MOVIMIENTO = { disponible: true, desde: '2024-10-29', hasta: '2026-10-29', peor_caida: null,
  desde_el_maximo: { pct: -2, anio_completo: true, maximo: 153 }, dia_normal: { desvio_pct: 2, dias: 500, dias_malos: 70 } }
const USD = { disponible: true, moneda: 'usd', ticker: 'AAPL', convertida: null, puntos: PUNTOS, lectura: LECTURA, movimiento: MOVIMIENTO }

let respuestas
vi.mock('../../utils/api', () => ({
  getClientContext: () => null,
  api: {
    get: vi.fn((ruta) => {
      const clave = Object.keys(respuestas).find(k => ruta.startsWith(k))
      return Promise.resolve(clave ? respuestas[clave] : [])
    }),
  },
}))

let LecturaTecnica, PrivacyProvider
beforeAll(async () => {
  instalarNavegadorMinimo()
  ;({ default: LecturaTecnica } = await import('./LecturaTecnica'))
  ;({ PrivacyProvider } = await import('../../contexts/PrivacyContext'))
})
afterAll(() => { vi.unstubAllGlobals() })

let montado
afterEach(async () => {
  if (montado) await montado.desmontar()
  montado = null
  localStorage.clear()
})

const PROPS = { asset: 'AAPL', symbolMiniChart: 'AAPL.BA', pnlPctUsd: 0.123, tenencia: { valorUsd: 5000, tc: 1500 }, pesoEnCartera: 0.2 }
async function dibujar(props = {}) {
  respuestas = { '/tecnico/AAPL?moneda=usd': USD }
  const el = () => h(PrivacyProvider, null, h(LecturaTecnica, { ...PROPS, ...props }))
  montado = await montar(el())
  for (let i = 0; i < 4; i++) await montado.redibujar(el())
  return texto(montado.contenedor)
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
const conRol = (rol) => todos(n => n.getAttribute?.('role') === rol)
const visibles = () => conRol('tabpanel').filter(p => !p.hasAttribute('hidden'))

describe('la ficha: la lectura de hoy y las tarjetas en pestañas', () => {
  it('arriba del gráfico, la frase y los cuatro casilleros con los números de la lectura', async () => {
    const t = await dibujar()
    expect(t).toContain('La lectura de hoy:')
    expect(t).toContain('tendencia alcista en los dos plazos, con impulso al alza.')
    expect(t).toContain('cierre del jueves 29/10')
    expect(t).toContain('Largo plazo · 200 días')
    expect(t).toContain('+7,1% arriba de su promedio · desde el 05/02')   // día 400 de la serie (mismo año que el cierre: sin el año)
    expect(t).toContain('Mediano plazo · 50 días')
    expect(t).toContain('Impulso (RSI)')
    expect(t).toContain('Fuerza de la tendencia (ADX)')
    // La tarjeta va antes que el marco del gráfico (sus botones).
    expect(t.indexOf('La lectura de hoy')).toBeLessThan(t.indexOf('Pantalla completa'))
  })

  it('cinco pestañas con su puntito; se ve una sola y la elegida se recuerda', async () => {
    await dibujar()
    const tabs = conRol('tab')
    expect(tabs.map(texto)).toEqual(['Tendencia', 'Impulso y fuerza', 'Niveles', 'Tu posición', 'Cuánto se mueve'])
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(visibles()).toHaveLength(1)
    expect(texto(visibles()[0])).toContain('Largo plazo')
    expect(texto(visibles()[0])).toContain('Últimos 6 meses')          // el dibujito
    expect(texto(visibles()[0])).toContain('mínimo US$ 120,00')        // la regla del año
    const punto = (k) => tabs[k].childNodes[0].getAttribute('class')
    expect(punto(0)).toContain('bg-rendi-pos')
    expect(punto(2)).toContain('bg-ink-3')
    expect(punto(4)).toContain('bg-rendi-warn')
    await clic(montado.contenedor, tabs[4])
    expect(texto(visibles()[0])).toContain('Cuánto se mueve este papel')
    expect(localStorage.getItem('rendi_ficha_tema_tecnico')).toBe('movimiento')
  })

  it('Niveles: la de Bollinger sólo con su capa prendida; si no hay ninguna, cómo prenderlas', async () => {
    localStorage.setItem('rendi_grafico_capas', JSON.stringify({ bb: true }))
    let t = await dibujar()
    expect(t).toContain('Bandas de Bollinger')
    expect(t).toContain('Entre las bandas')
    await montado.desmontar()
    localStorage.setItem('rendi_grafico_capas', JSON.stringify({ bb: false, fib: false, ell: false }))
    t = await dibujar()
    expect(t).not.toContain('Entre las bandas')
    expect(t).toContain('No hay ningún nivel prendido en el gráfico.')
  })

  it('«Tu posición» sólo si lo tenés', async () => {
    const t = await dibujar({ pnlPctUsd: null, tenencia: null })
    expect(conRol('tab').map(texto)).not.toContain('Tu posición')
    expect(t).not.toContain('Contra lo que pagaste')
  })

  it('con el ojito cerrado no dice tu resultado, tu plata ni qué parte de tu cartera es', async () => {
    let t = await dibujar()
    expect(t).toContain('Ganás 12,3%')
    expect(t).toContain('Es el 20% de tu cartera')
    await montado.desmontar()
    localStorage.setItem('rendi_privacy', '1')
    t = await dibujar()
    expect(t).not.toContain('Ganás')
    expect(t).not.toMatch(/US\$ 100/)        // 2 % de US$ 5.000
    expect(t).not.toContain('de tu cartera:')
    expect(t).toContain('••••••')
    expect(conRol('tab')[3].childNodes[0].getAttribute('class')).toContain('bg-ink-3')
  })
})

describe('la pestaña «Gráfico» de Análisis técnico (soloGrafico)', () => {
  it('sólo el gráfico: sin la lectura de hoy ni pestañas; las tarjetas como antes', async () => {
    const t = await dibujar({ soloGrafico: true })
    expect(t).not.toContain('La lectura de hoy')
    expect(conRol('tablist')).toHaveLength(0)
    expect(t).toContain('Largo plazo')
    expect(t).toContain('Contra lo que pagaste')
    expect(t).toContain('Cuánto se mueve este papel')
    expect(t).not.toContain('Últimos 6 meses')     // sin los dibujitos de la ficha
  })
})
