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
import { capitalMaximoAportado, retornoTotal, denominadorAportado, PISO_DENOMINADOR_USD } from './evolution'
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

describe('lo que encontró auditar esto contra sí mismo', () => {
  // Los tres salieron de revisar el propio fix, no de un reporte. Los tres
  // pasaban en verde con el código que se había escrito primero.

  it('un costo histórico corrupto NO puede contaminar el denominador', () => {
    // `netDepositedOf` —el helper que usa el resto del archivo— cae a
    // `total_invested` (COSTO) cuando net_deposited viene en 0. Reusarlo acá
    // metía la base contable por la ventana: los snapshots legacy de este repo
    // tienen costos corruptos conocidos (CEDEAR ×1486, comisión fantasma), y
    // uno solo se convertía en el máximo.
    //
    // Medido con la primera versión: el +200 % real daba +0,13 %.
    const conLegacyRoto = [
      { date: '2024-01-01', total_value: 10_000, total_invested: 14_860_000, net_deposited: 0 },
      { date: '2026-01-01', total_value: 30_000, total_invested: 10_000, net_deposited: 10_000 },
    ]
    const cap = capitalMaximoAportado(conLegacyRoto, 10_000)
    expect(cap).toBe(10_000)
    const r = retornoTotal({ totalValue: 30_000, netDeposited: 10_000, capitalMaximo: cap })
    expect(r.pct).toBeCloseTo(2.0, 10)          // +200 %, no +0,13 %
  })

  it('un net_deposited en 0 es un HUECO, no un aportado de cero', () => {
    // La columna es NOT NULL DEFAULT 0: así se escribe "no lo tengo" en las
    // filas pre-Phase 6. Saltearlas es lo correcto; tomarlas como 0 no cambia
    // el máximo pero tomarlas por `total_invested` sí.
    expect(capitalMaximoAportado(serie(0, 0, 0), 7_000)).toBe(7_000)
  })

  it('la frase no afirma una causa que puede ser falsa', () => {
    // `pct` viene en null por más de un motivo. Decir "retiraste más de lo que
    // pusiste" a un usuario NUEVO que todavía no cargó ningún aporte es
    // afirmarle un retiro que nunca hizo.
    const nuevo = buildDashboardInsight({
      totalValue: 5_000, netDeposited: 0, capitalMaximo: null,
      positions: [{ asset: 'AAPL', pnl_usd: 100, pnl_pct: 2, value_usd: 5_000 }],
    })
    expect(nuevo.text).not.toMatch(/retiraste/i)
    expect(nuevo.text).toContain('no se puede calcular')
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


describe('unificar las siete copias del denominador', () => {
  // La misma regla vivía escrita SIETE veces con TRES criterios distintos.
  // Estos tests fijan cuál ganó y por qué las otras dos estaban mal.

  it('el pico de la CARTERA estaba mal: metía la ganancia no realizada', () => {
    // Aportó 10k, nunca retiró, la cartera vale 30k, realizó 5k.
    // La curva del Dashboard usaba max(nd, valorCartera*0.8) = 24k → 20,8 %.
    const conLaReglaVieja = 5_000 / Math.max(10_000, 30_000 * 0.8) * 100
    expect(conLaReglaVieja).toBeCloseTo(20.83, 1)
    // La regla única usa el capital APORTADO: 5k sobre 10k = 50 %.
    expect(5_000 / denominadorAportado(10_000, 10_000) * 100).toBe(50)
  })

  it('el umbral del 60 % era discontinuo; max() no puede saltar', () => {
    // Con el umbral, retirar un dólar de más cruzaba el 60 % y el denominador
    // pegaba un salto que no corresponde a nada que haya pasado.
    const viejo = (nd, peak) => (nd >= peak * 0.6 && nd > 1000) ? nd : peak
    expect(viejo(60_000, 100_000)).toBe(60_000)
    expect(viejo(59_999, 100_000)).toBe(100_000)   // ← salta 40 mil por un dólar
    // La regla única da lo mismo a los dos lados del ex-umbral.
    expect(denominadorAportado(60_000, 100_000)).toBe(100_000)
    expect(denominadorAportado(59_999, 100_000)).toBe(100_000)
  })

  it('abajo del piso no se publica nada, ni siquiera un cero', () => {
    expect(denominadorAportado(50, 50)).toBeNull()
    expect(denominadorAportado(PISO_DENOMINADOR_USD, 0)).toBe(PISO_DENOMINADOR_USD)
    // …y el hero hereda el piso
    expect(retornoTotal({ totalValue: 200, netDeposited: 50, capitalMaximo: 50 }).pct).toBeNull()
    expect(retornoTotal({ totalValue: 200, netDeposited: 50, capitalMaximo: 50 }).usd).toBe(150)
  })

  it('el retorno total y la curva usan EL MISMO denominador', () => {
    // Si se separan, la misma pantalla cuenta dos historias.
    const nd = 5_000, max = 50_000
    const delHero = retornoTotal({ totalValue: 35_000, netDeposited: nd, capitalMaximo: max })
    expect(delHero.pct).toBeCloseTo(30_000 / denominadorAportado(nd, max), 10)
  })
})

describe('auditar la unificación encontró tres más', () => {
  it('la CURVA alimentaba su pico con el helper que cae a costo', async () => {
    // Arreglé ese fallback en `capitalMaximoAportado` y no vi que la curva
    // tenía el mismo, alimentándose de `netDepositedOf`. Medido con el costo
    // corrupto conocido (CEDEAR ×1486): el realized% publicaba 0,03 %.
    const { buildEvolutionFromSnapshots } = await import('./evolution')
    const snaps = [
      { date: '2024-01-31', total_value: 10_000, total_invested: 14_860_000,
        net_deposited: 0, source: 'cron', base: 'mercado', apto: 1 },
      { date: '2026-01-31', total_value: 30_000, total_invested: 10_000,
        net_deposited: 10_000, source: 'cron', base: 'mercado', apto: 1 },
    ]
    const monthly = [
      { year: 2024, month: 1, broker: 'global', pnl_realized: 0, capital_inicio: 10_000 },
      { year: 2026, month: 1, broker: 'global', pnl_realized: 5_000, capital_inicio: 10_000 },
    ]
    const r = buildEvolutionFromSnapshots(snaps, monthly, null, 1400)
    const ultimo = r.seriesUsd[r.seriesUsd.length - 1]
    expect(ultimo.realized).toBeCloseTo(50, 0)     // 5k realizados sobre 10k aportados
  })

  it('el piso está en DÓLARES: las dos monedas dan el mismo veredicto', () => {
    const FX = 1400
    for (const ndUsd of [50, 99, 100, 150, 5_000]) {
      const enUsd = denominadorAportado(ndUsd, ndUsd)
      const enArs = denominadorAportado(ndUsd * FX, ndUsd * FX, FX)
      expect(enUsd === null, `US$${ndUsd}: una moneda publica y la otra no`)
        .toBe(enArs === null)
    }
  })

  it('sin el FX, los pesos pasaban todos el piso', () => {
    expect(denominadorAportado(70_000, 70_000)).not.toBeNull()        // sin fx: pasa
    expect(denominadorAportado(70_000, 70_000, 1400)).toBeNull()      // con fx: no
  })

  it('un FX inválido no apaga el guard', () => {
    for (const fx of [0, -1, null, undefined, NaN, 'x']) {
      expect(denominadorAportado(50, 50, fx), `fx=${fx}`).toBeNull()
    }
  })
})
