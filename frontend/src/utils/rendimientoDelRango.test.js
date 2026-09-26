/**
 * El chip de la curva ("±USD X · ±Y% en <rango>") tiene que decir lo mismo que
 * el resto del Dashboard, y su rótulo tiene que ser el período que midió.
 *
 * EL CASO (2026-09-25, demo pública, 1440×900): la cartera vale US$ 41.435,82,
 * "Ganancia total +US$ 5.916,82"… y el chip: "−USD 26.791,78 · −64,9 % en el mes".
 *
 * DOS ESLABONES, hacían falta los dos para verlo:
 * 1. FIXTURE (sólo demo): la "foto de hoy" valía el saldo de BINANCE (14.517).
 * 2. CÁLCULO (usuarios reales): el chip era una SEGUNDA copia de "Δ(valor −
 *    aportado)" sin los guards de `computeReturnDelta`: terminaba en la foto
 *    guardada de hoy (existe desde la 2ª visita del día) y no en el valor vivo;
 *    abría en un punto de cualquier antigüedad; aceptaba de base una foto de media
 *    rueda; publicaba "0,0 %" con base ≤ 0.
 *
 * EL AUDIT (mismo día) encontró tres defectos de la primera versión del arreglo,
 * fijados acá: rótulo que no era el período medido (46 días "en 1 año"), chip que
 * aparecía y desaparecía según el día del mes, y un % que los aportes inflaban
 * ("+111,2 %" al lado de "Ganancia total +11,1 %").
 *
 * Las filas tienen la forma EXACTA de GET /api/snapshots (`main.py::get_snapshots`):
 * `clase`/`apto` de `twr.clasificar_serie`/`twr.es_apto`; `sintetico = not apto`.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  buildPortfolioValueSeries,
  computeDailyPnl,
  computeReturnDelta,
  inicioDeVentana,
  rendimientoDelRango,
} from './evolution.js'
import { valorAlMep } from './valuation.js'

const AQUI = dirname(fileURLToPath(import.meta.url))

// Un cierre del cron: medición a mercado, sirve de borde y de denominador.
const cierre = (date, total_value, net_deposited) => ({
  date, total_value, total_invested: total_value, net_deposited,
  clase: 'medicion', base: 'mercado', apto: true, sintetico: false,
})
// La foto que escribe el Dashboard en la primera visita del día.
const fotoDelBrowser = (date, total_value, net_deposited) => ({
  date, total_value, total_invested: total_value, net_deposited,
  clase: 'intradia', base: 'mercado', apto: false, sintetico: true,
})
// Reconstrucción del import con cobertura de precios baja: se dibuja, no mide.
const reconstruidaAlCosto = (date, total_value, net_deposited) => ({
  date, total_value, total_invested: net_deposited, net_deposited,
  clase: 'reconstruido', base: 'costo', apto: false, sintetico: true,
})
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const diarios = (desde, hasta, valor, aportado) => {
  const out = []
  for (let d = new Date(desde); d < hasta; d.setDate(d.getDate() + 1)) out.push(cierre(iso(d), valor(d), aportado(d)))
  return out
}

// El "hoy" de la app es el día local (utils/fecha); de 21 a 24 ART el día UTC ya
// es mañana. Cada caso corre a las 15:00 Y a las 22:30.
const HORAS = [
  ['15:00', new Date(2026, 8, 25, 15, 0)],
  ['22:30', new Date(2026, 8, 25, 22, 30)],
]

describe.each(HORAS)('rendimientoDelRango — reloj a las %s', (_hora, ahora) => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(ahora) })
  afterEach(() => { vi.useRealTimers() })

  const conFotoDeLaManana = () => [
    ...diarios(new Date(2026, 7, 20), new Date(2026, 8, 25), () => 10_000, () => 8_000),
    fotoDelBrowser('2026-09-25', 10_000, 8_000),
  ]

  it('SEGUNDA VISITA DEL DÍA: termina en el valor vivo, no en la foto de la mañana', () => {
    const r = rendimientoDelRango(conFotoDeLaManana(), { dias: 30, liveValue: 10_400, liveNetDeposited: 8_000 })
    expect(r.usd).toBeCloseTo(400, 6)          // antes: +0 (foto de la mañana)
    expect(r.pct).toBeCloseTo(0.04, 6)
    expect(r.desde).toBeNull()                 // cierre fresco → rótulo "en el mes"
  })

  it('la punta de la curva es el valor vivo, una sola vez por día', () => {
    const serie = buildPortfolioValueSeries(conFotoDeLaManana(), 30, 10_400, 8_000)
    expect(serie.filter(p => p.date === '2026-09-25')).toHaveLength(1)
    expect(serie[serie.length - 1].valueUsd).toBe(10_400)
  })

  it('la cotización estampada en la foto de hoy no se pierde al reemplazarla', () => {
    const snaps = [cierre('2026-09-24', 10_000, 8_000), { ...fotoDelBrowser('2026-09-25', 10_000, 8_000), fx_to_usd_blue: 1_415 }]
    const serie = buildPortfolioValueSeries(snaps, null, 10_400, 8_000)
    expect(serie[serie.length - 1].fxToUsdBlue).toBe(1_415)
  })

  it('SE AUSENTÓ: mide desde su último cierre y el rótulo DICE la fecha (no "en el mes")', () => {
    const r = rendimientoDelRango([cierre('2026-08-15', 9_000, 8_000)], { dias: 30, liveValue: 10_400, liveNetDeposited: 8_000 })
    expect(r.desde).toBe('2026-08-15')         // antes: "+15,6 % en el mes" midiendo 41 días
    expect(r.usd).toBeCloseTo(1_400, 6)
  })

  it('UNA FOTO DE MEDIA RUEDA NUNCA ES LA BASE', () => {
    expect(inicioDeVentana(30)).toBe('2026-08-27')
    const snaps = [
      cierre('2026-08-19', 9_000, 8_000),
      fotoDelBrowser('2026-08-25', 5_000, 8_000),   // media rueda: no cuenta
      cierre('2026-09-24', 10_300, 8_000),
    ]
    const r = rendimientoDelRango(snaps, { dias: 30, liveValue: 10_400, liveNetDeposited: 8_000 })
    expect(r.prevDate).toBe('2026-08-19')           // el cierre, no la foto de 5.000
    expect(r.desde).toBe('2026-08-19')              // a 8 días del arranque: se rotula
    const conCierre = rendimientoDelRango([...snaps, cierre('2026-08-24', 10_000, 8_000)],
      { dias: 30, liveValue: 10_400, liveNetDeposited: 8_000 })
    expect(conCierre.prevDate).toBe('2026-08-24')
    expect(conCierre.desde).toBeNull()
  })

  it('BASE ≤ 0: no hay porcentaje, no "0,0 %"', () => {
    const snaps = [cierre('2026-08-25', -50, 0), cierre('2026-09-24', 900, 1_000)]
    expect(rendimientoDelRango(snaps, { dias: 30, liveValue: 1_000, liveNetDeposited: 1_000 })).toBeNull()
  })

  it('1D: el último cierre antes de hoy, saltea la foto de hoy y dice cuántos días mide', () => {
    const snaps = [cierre('2026-09-19', 10_000, 8_000), cierre('2026-09-22', 10_100, 8_000), fotoDelBrowser('2026-09-25', 9_000, 8_000)]
    const r = rendimientoDelRango(snaps, { dias: 1, liveValue: 10_150, liveNetDeposited: 8_000 })
    expect(r.prevDate).toBe('2026-09-22')
    expect(r.usd).toBeCloseTo(50, 6)
    expect(r.pct).toBeCloseTo(50 / 10_100, 9)       // el modo diario divide por el valor de ayer
    expect(r.dayDiff).toBe(3)                       // la pantalla dice "en los últimos 3 días"
  })

  it('MAX es la "Ganancia total" del título, no un segundo cálculo', () => {
    const r = rendimientoDelRango([cierre('2025-03-01', 1_000, 1_000)], {
      dias: null, liveValue: 11_112, liveNetDeposited: 10_000, gananciaTotal: { usd: 1_112, pct: 0.1112 },
    })
    expect(r.usd).toBe(1_112)
    expect(r.pct).toBe(0.1112)
    expect(rendimientoDelRango([], { dias: null, gananciaTotal: null })).toBeNull()
  })

  it('con cierres diarios, el chip abre donde abre la curva', () => {
    const snaps = diarios(new Date(2026, 8, 10), new Date(2026, 8, 25), d => 10_000 + d.getDate(), () => 8_000)
    const serie = buildPortfolioValueSeries(snaps, 7, 10_100, 8_000)
    const r = rendimientoDelRango(snaps, { dias: 7, liveValue: 10_100, liveNetDeposited: 8_000 })
    expect(inicioDeVentana(7)).toBe('2026-09-19')
    expect(serie[0].date).toBe('2026-09-18')
    expect(r.prevDate).toBe(serie[0].date)
  })
})

describe('los casos del audit', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date(2026, 8, 25, 15, 0)) })
  afterEach(() => { vi.useRealTimers() })

  it('IMPORTÓ con cobertura baja: 6M, 1A dicen "desde" el primer cierre medido', () => {
    // Historia de fin de mes al costo (se dibuja, no mide) + cron diario desde el 01/07.
    const snaps = []
    for (let m = 1; m <= 18; m++) {
      const fin = new Date(2025, m, 0)
      snaps.push(reconstruidaAlCosto(iso(fin), 10_000 + m * 200, 10_000))
    }
    snaps.push(...diarios(new Date(2026, 6, 1), new Date(2026, 8, 25), () => 14_000, () => 10_000))
    for (const dias of [180, 365]) {
      const r = rendimientoDelRango(snaps, { dias, liveValue: 14_200, liveNetDeposited: 10_000 })
      expect(r.prevDate).toBe('2026-07-01')
      expect(r.desde).toBe('2026-07-01')       // antes: "en 1 año" midiendo 86 días
    }
  })

  it('CIERRES SÓLO A FIN DE MES: el chip de 6M tiene número TODOS los días del mes', () => {
    const snaps = []
    for (let m = 1; m <= 20; m++) snaps.push(cierre(iso(new Date(2025, m, 0)), 10_000 + m * 100, 10_000))
    for (let dia = 1; dia <= 30; dia++) {
      vi.setSystemTime(new Date(2026, 8, dia, 15, 0))
      const r = rendimientoDelRango(snaps, { dias: 180, liveValue: 12_500, liveNetDeposited: 10_000 })
      expect(r, `día ${dia}`).not.toBeNull()   // antes: sólo del 27 al 30
      if (r.desde) expect(r.prevDate).toBe(r.desde)
    }
  })

  it('EL QUE APORTA TODOS LOS MESES: el % no se infla con la plata que entró (Dietz)', () => {
    // Empezó con US$ 1.000 el 01/03/2025, aporta US$ 500 cada 1° y rinde ~1 % por mes.
    const snaps = []
    let v = 1_000, nd = 1_000
    for (let d = new Date(2025, 2, 1); d < new Date(2026, 8, 25); d.setDate(d.getDate() + 1)) {
      if (d.getDate() === 1 && !(d.getFullYear() === 2025 && d.getMonth() === 2)) { v += 500; nd += 500 }
      v *= Math.pow(1.01, 1 / 30)
      snaps.push(cierre(iso(d), +v.toFixed(2), nd))
    }
    const r = rendimientoDelRango(snaps, { dias: 365, liveValue: v, liveNetDeposited: nd })
    const base = snaps.find(s => s.date === r.prevDate)
    expect(r.aportes).toBe(nd - base.net_deposited)
    expect(r.valorInicio).toBe(base.total_value)
    expect(r.pct).toBeCloseTo(r.usd / (base.total_value + 0.5 * r.aportes), 9)
    expect(r.pct).toBeLessThan(0.15)            // antes: +22,4 % (sobre el valor inicial)
  })

  it('"Este mes" usa el mismo denominador que el chip; "Hoy" sigue sobre el valor de ayer', () => {
    const snaps = [cierre('2026-08-31', 1_000, 1_000), cierre('2026-09-02', 21_000, 21_000)]
    const mes = computeReturnDelta(snaps, { liveValue: 21_300, liveNetDeposited: 21_000, sinceDate: '2026-09-01' })
    expect(mes.pct).toBeCloseTo(300 / (1_000 + 0.5 * 20_000), 9)   // antes: +30 %
    const hoy = computeDailyPnl(snaps, { liveValue: 21_300, liveNetDeposited: 21_000 })
    expect(hoy.pct).toBeCloseTo(300 / 21_000, 9)
  })
})

describe('las comparaciones contra las fotos van al MEP aunque el usuario elija CCL', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date(2026, 8, 25, 15, 0)) })
  afterEach(() => { vi.useRealTimers() })

  it('sin que se mueva ningún precio, "Hoy" da 0 al MEP y una ganancia fantasma al CCL', () => {
    const brokers = [{ id: 2, name: 'Cocos', currency: 'ARS' }]
    const positions = [{ id: 1, broker: 'Cocos', asset: 'GGAL', is_cash: 0, quantity: 100, invested: 400_000, commissions: 0 }]
    const prices = { 'GGAL.BA': 4_800 }
    const alMep = valorAlMep(positions, prices, brokers, 1_424)
    const alCcl = valorAlMep(positions, prices, brokers, 1_500)
    const fotoDeAyer = [cierre('2026-09-24', alMep, 300)]
    expect(computeDailyPnl(fotoDeAyer, { liveValue: alMep, liveNetDeposited: 300 }).usd).toBeCloseTo(0, 6)
    expect(Math.abs(computeDailyPnl(fotoDeAyer, { liveValue: alCcl, liveNetDeposited: 300 }).usd)).toBeGreaterThan(10)
  })
})

describe('home mobile: las fotos que pide alcanzan para abrir "Últimos 30 días"', () => {
  beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date(2026, 8, 25, 15, 0)) })
  afterEach(() => { vi.useRealTimers() })

  // GET /api/snapshots?days=N es `ORDER BY date DESC LIMIT N` (main.py): un
  // límite de FILAS, no de días. Esto reproduce esa respuesta.
  const respuestaDelBackend = (filas, n) => [...filas].sort((a, b) => (a.date < b.date ? 1 : -1)).slice(0, n)

  it('con cierres diarios y la foto de hoy, la ventana abre en el cierre de hace 30 días', () => {
    const src = readFileSync(resolve(AQUI, '../pages/HomeMobile.jsx'), 'utf-8')
    // El pedido, no un comentario que lo mencione.
    const pedidas = Number(src.match(/api\.get\('\/snapshots\?days=(\d+)'\)/)?.[1])
    expect(pedidas, 'no encontré el api.get de /snapshots en HomeMobile.jsx').toBeGreaterThan(0)
    const filas = [...diarios(new Date(2026, 5, 1), new Date(2026, 8, 25), () => 10_000, () => 8_000),
      fotoDelBrowser('2026-09-25', 10_050, 8_000)]
    const r = rendimientoDelRango(respuestaDelBackend(filas, pedidas), { dias: 30, liveValue: 10_100, liveNetDeposited: 8_000 })
    // Con 30 filas daba '2026-08-27' (29 días rotulados "Últimos 30 días").
    expect(r.prevDate).toBe('2026-08-26')
    expect(r.desde).toBeNull()
  })
})

describe('las pantallas no vuelven a tener su propia copia', () => {
  // Guard de CÓDIGO, a propósito chico: el comportamiento lo fijan los tests de
  // arriba. Avisa si alguien vuelve a restar las puntas de la serie en la pantalla
  // o a comparar contra las fotos con el valor al dólar elegido.
  for (const archivo of ['../pages/Dashboard.jsx', '../pages/HomeMobile.jsx']) {
    it(`${archivo} usa rendimientoDelRango y valorAlMep`, () => {
      const src = readFileSync(resolve(AQUI, archivo), 'utf-8')
      expect(src).toContain('rendimientoDelRango(')
      expect(src).toContain('valorAlMep(')
      expect(src).not.toMatch(/last\.valueUsd\s*-\s*last\.netDeposited\)\s*-\s*\(first\.valueUsd/)
    })
  }
  it('la tarjeta "<Mes> en curso" muestra el número de "Este mes", no uno propio', () => {
    // Medía hasta el cierre de AYER: "Septiembre en curso −1,2 %" al lado de
    // "Este mes +0,1 %" en la misma pantalla (la diferencia era el día de hoy).
    const src = readFileSync(resolve(AQUI, '../pages/Dashboard.jsx'), 'utf-8')
    expect(src).toMatch(/<MonthlyTeaser mesEnCurso=\{monthlyVar\} \/>/)
  })
})
