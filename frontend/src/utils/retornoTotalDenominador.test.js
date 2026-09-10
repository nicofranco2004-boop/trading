/**
 * F4 · guard C7, punto 2 — el denominador del número más visible de la app.
 *
 * El "+X %" que va abajo del total en el Dashboard se calculaba sobre el
 * aportado neto DE HOY. Ese número se achica con cada retiro y el porcentaje
 * se infla solo; si se pone negativo, el call site publicaba 0 % — que no es
 * "no sé", es "no ganaste nada", sobre alguien que ganó.
 *
 * La promesa de este archivo, en orden de importancia:
 *   1. al que NUNCA retiró no se le mueve un decimal
 *   2. al que retiró se le corrige el porcentaje inflado
 *   3. el 0 % falso se convierte en "no calculable"
 *   4. la frase de arriba y el chip del hero son el MISMO número
 *
 * ⚠️ Al medirlo contra el código anterior (75a7a9f5) fallan los 13, pero la
 * mayoría falla con "capitalMaximoAportado is not a function", que sólo prueba
 * que la función es nueva. Los DOS que miden de verdad, porque no dependen de
 * que exista, son:
 *
 *   · "sin denominador, la frase habla de plata y no afirma un 0 %"
 *      → contra el código viejo devuelve literal "Tu cartera rinde +0.0%
 *        sobre el capital aportado". Ése es el bug, medido.
 *   · "el retorno total se calcula en evolution.js y en ningún otro lado"
 *      → contra el código viejo lista las dos copias: Dashboard.jsx e
 *        insights.js.
 */
import { describe, it, expect } from 'vitest'
import { capitalMaximoAportado, retornoTotal } from './evolution'
import { buildDashboardInsight } from './insights'

// Serie mínima: sólo hace falta `net_deposited` por fecha.
const serie = (...netDeps) => netDeps.map((nd, i) => ({
  date: `2026-0${i + 1}-01`, total_value: 0, total_invested: 0, net_deposited: nd,
}))

describe('capitalMaximoAportado', () => {
  it('sin historia devuelve el aportado de hoy — o sea, no cambia nada', () => {
    expect(capitalMaximoAportado([], 10_000)).toBe(10_000)
    expect(capitalMaximoAportado(null, 10_000)).toBe(10_000)
  })

  it('nunca devuelve menos que el aportado de hoy', () => {
    expect(capitalMaximoAportado(serie(1_000, 2_000), 10_000)).toBe(10_000)
  })

  it('toma el pico de la historia cuando el de hoy es menor', () => {
    expect(capitalMaximoAportado(serie(10_000, 50_000, 5_000), 5_000)).toBe(50_000)
  })

  it('el ajuste pone las dos escalas en el mismo plano', () => {
    // Los snapshots no fotografían los plazos fijos; `netDeposited` sí.
    expect(capitalMaximoAportado(serie(40_000), 45_000, 8_000)).toBe(48_000)
  })

  it('un aportado NEGATIVO en la historia no rompe el máximo', () => {
    // net_deposited < 0 es legítimo (retiros por encima de aportes): 11,7 % de
    // las filas de producción al 16/08.
    expect(capitalMaximoAportado(serie(30_000, -5_000), -5_000)).toBe(30_000)
  })
})

describe('retornoTotal — los tres casos que decidieron el diseño', () => {
  it('1) nunca retiró: el número NO se mueve', () => {
    // Puso 10k, nunca sacó, hoy tiene 30k.
    const snaps = serie(10_000)
    const cap = capitalMaximoAportado(snaps, 10_000)
    const r = retornoTotal({ totalValue: 30_000, netDeposited: 10_000, capitalMaximo: cap })
    expect(r.usd).toBe(20_000)
    expect(r.pct).toBeCloseTo(2.0, 10)          // +200 %, igual que antes
  })

  it('2) retiro grande: el +600 % inflado baja al real', () => {
    // Puso 50k, sacó 45k, hoy tiene 35k. Aportado de hoy = 5k.
    const snaps = serie(50_000, 5_000)
    const cap = capitalMaximoAportado(snaps, 5_000)
    expect(cap).toBe(50_000)
    const r = retornoTotal({ totalValue: 35_000, netDeposited: 5_000, capitalMaximo: cap })
    expect(r.usd).toBe(30_000)
    expect(r.pct).toBeCloseTo(0.6, 10)          // +60 %, no +600 %
    // Y la vieja fórmula, para dejar el contraste medido:
    expect(30_000 / 5_000).toBe(6)              // +600 %
  })

  it('3) retiró más de lo que puso: no calculable, NO cero', () => {
    // Puso 50k, sacó 60k, hoy tiene 5k. Aportado de hoy = −10k.
    const snaps = serie(50_000, -10_000)
    const cap = capitalMaximoAportado(snaps, -10_000)
    expect(cap).toBe(50_000)
    const r = retornoTotal({ totalValue: 5_000, netDeposited: -10_000, capitalMaximo: cap })
    expect(r.usd).toBe(15_000)                  // el MONTO siempre es correcto
    expect(r.pct).toBeCloseTo(0.3, 10)

    // Y si además no hay historia con qué sostenerlo: null, nunca 0.
    const sinHistoria = retornoTotal({ totalValue: 5_000, netDeposited: -10_000 })
    expect(sinHistoria.usd).toBe(15_000)
    expect(sinHistoria.pct).toBeNull()
  })

  it('el monto se publica siempre, aunque la tasa no', () => {
    const r = retornoTotal({ totalValue: 5_000, netDeposited: 0 })
    expect(r.usd).toBe(5_000)
    expect(r.pct).toBeNull()
  })
})

describe('la frase del Dashboard usa el MISMO número que el hero', () => {
  const positions = [
    { asset: 'AAPL', pnl_usd: 1_000, pnl_pct: 10, value_usd: 11_000 },
    { asset: 'MELI', pnl_usd: -200, pnl_pct: -5, value_usd: 3_800 },
  ]

  it('con retiro grande, la frase dice +60 % y no +600 %', () => {
    const cap = capitalMaximoAportado(serie(50_000, 5_000), 5_000)
    const insight = buildDashboardInsight({
      totalValue: 35_000, netDeposited: 5_000, capitalMaximo: cap, positions,
    })
    expect(insight.text).toContain('+60.0%')
    expect(insight.text).not.toContain('600')
  })

  it('sin denominador, la frase habla de plata y no afirma un 0 %', () => {
    const insight = buildDashboardInsight({
      totalValue: 5_000, netDeposited: -10_000, capitalMaximo: null, positions,
    })
    expect(insight.text).not.toContain('0.0%')
    expect(insight.text).toContain('a favor')
    expect(insight.tone).toBe('positive')
  })

  it('para el que nunca retiró la frase tampoco cambia', () => {
    const cap = capitalMaximoAportado(serie(10_000), 10_000)
    const insight = buildDashboardInsight({
      totalValue: 30_000, netDeposited: 10_000, capitalMaximo: cap, positions,
    })
    expect(insight.text).toContain('+200.0%')
  })
})

describe('nadie lo recalcula por su cuenta', () => {
  // Guard contra la copia N+1: lee CÓDIGO, no números. Un test de
  // comportamiento pasa igual el día que alguien escriba la tercera copia en
  // otro archivo — y esa copia es el bug. Es la causa raíz más frecuente de
  // este repo: el fix correcto aplicado en 1 de N call sites.
  //
  // Este cálculo vivía a mano en DOS lugares (el chip del hero y la frase de
  // arriba), los dos con `netDeposited > 0 ? … : 0`, así que al corregir uno
  // solo la misma pantalla mostraba dos porcentajes distintos.
  const A_MANO = /net_?[Dd]eposited\s*>\s*0\s*\?[^:]*\/\s*net_?[Dd]eposited/

  it('el retorno total se calcula en evolution.js y en ningún otro lado', async () => {
    const mods = import.meta.glob('../**/*.{js,jsx}', { query: '?raw', import: 'default', eager: true })
    const culpables = []
    for (const [ruta, src] of Object.entries(mods)) {
      if (ruta.includes('.test.') || ruta.includes('/evolution.js')) continue
      if (A_MANO.test(src)) culpables.push(ruta)
    }
    expect(culpables, 'el denominador del retorno total vive en evolution.js: ' +
      'usá retornoTotal() en vez de dividir por netDeposited a mano').toEqual([])
  })
})
