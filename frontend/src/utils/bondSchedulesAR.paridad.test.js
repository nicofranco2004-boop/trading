/**
 * El cronograma de amortización tiene DOS copias y tienen que decir lo mismo.
 *
 *   · frontend/src/utils/bondSchedulesAR.js — con el que la pantalla calcula los
 *     cupones, la TIR y lo que propone la bandeja de cobros.
 *   · backend/pricing/bond_amortization.py — con el que el servidor baja los
 *     nominales de los bonos importados (`sweep_bond_amortizations`).
 *
 * Hasta 2026-10-09 AL30/GD30 decían cosas distintas (13 cuotas de 7,69 % en la
 * pantalla, 4 % + 12×8 % en el servidor) y la bandeja proponía montos que no eran
 * los que pagó el bono. Este test lee la tabla del servidor tal cual está escrita
 * y la compara, fecha por fecha, con la de la pantalla.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { CANJE_2020_BY_TICKER } from './bondSchedulesAR.js'
import { BOND_META } from './bondMeta.js'
import { generateSchedule } from './bondSchedule.js'

const AQUI = dirname(fileURLToPath(import.meta.url))
const PY = readFileSync(resolve(AQUI, '../../../backend/pricing/bond_amortization.py'), 'utf8')

// _AL30_GD30: List[...] = [ ("2024-07-09", 0.04), ... ]  → { nombre: [[fecha, %], ...] }
function tablasDelServidor() {
  const tablas = {}
  for (const m of PY.matchAll(/^(_[A-Z0-9_]+):\s*List\[[^\]]*\]\]\s*=\s*\[([\s\S]*?)^\]/gm)) {
    tablas[m[1]] = [...m[2].matchAll(/\("(\d{4}-\d{2}-\d{2})",\s*([\d.]+)\)/g)]
      .map(x => [x[1], +(Number(x[2]) * 100).toFixed(4)])
  }
  const porTicker = {}
  const mapa = PY.match(/_AMORT_SCHEDULES[^=]*=\s*\{([\s\S]*?)\}/)[1]
  for (const m of mapa.matchAll(/"([A-Z0-9]+)":\s*(_[A-Z0-9_]+)/g)) porTicker[m[1]] = tablas[m[2]]
  return porTicker
}

describe('cronograma de amortización — pantalla y servidor dicen lo mismo', () => {
  const servidor = tablasDelServidor()

  it('el servidor tiene cronograma para los bonos que amortiza hoy', () => {
    expect(Object.keys(servidor)).toEqual(expect.arrayContaining(['AL29', 'GD29', 'AL30', 'GD30']))
  })

  for (const [ticker, tabla] of Object.entries(tablasDelServidor())) {
    it(`${ticker}: mismas fechas y mismos porcentajes`, () => {
      const pantalla = (CANJE_2020_BY_TICKER[ticker]?.amortSchedule || [])
        .map(a => [a.date, +Number(a.pct).toFixed(4)])
      expect(pantalla).toEqual(tabla)
    })
  }
})

// ── La otra dirección ───────────────────────────────────────────────────────
// Lo de arriba recorre los bonos del SERVIDOR. Faltaba mirar al revés: un bono
// que la pantalla ya hace amortizar y el servidor no conoce. No es un error en
// sí (a esos lotes los nominales se los baja el cobro confirmado, no el
// barrido), pero tiene que ser una decisión anotada y no un olvido: con GD46
// pasó sin que nadie lo viera, y la pantalla leía su cantidad importada con
// otra regla que la de AL30 (auditoría 2026-10-10).
describe('bonos que ya amortizan en la pantalla y el servidor no barre', () => {
  // ticker → por qué el barrido de amortizaciones del servidor no lo lleva.
  const SIN_BARRIDO = {
    GD46: 'Cronograma verificado contra el prospecto el 2026-10-10 (44 cuotas desde 09/01/2025). '
      + 'Sumarlo al barrido le cambia la cantidad a quien ya lo tiene importado: decisión de producto pendiente.',
    TX26: 'En pesos ajustado por CER: el barrido sólo lleva soberanos en dólares del canje. '
      + 'Sus nominales los baja el cobro confirmado.',
    TX28: 'Ídem TX26.',
    // Los que todavía NO empezaron, anotados desde ya: este test mira la fecha
    // de hoy, y sin esto se ponía rojo solo el día de la primera cuota (el
    // mismo tipo de rojo "de calendario" que ya costó caro en este repo).
    AE38: 'Empieza a amortizar el 09/07/2027. Mismo caso que GD46.',
    GD38: 'Ídem AE38.',
    AL41: 'Empieza a amortizar el 09/01/2028. Mismo caso que GD46.',
    GD41: 'Ídem AL41.',
    AL35: 'Empieza a amortizar el 09/01/2031. Mismo caso que GD46.',
    GD35: 'Ídem AL35.',
  }
  const HOY = new Date().toISOString().slice(0, 10)
  const servidor = tablasDelServidor()

  it('todo bono con una cuota de capital ya pagada está en el servidor o en la lista, con su motivo', () => {
    const sinDecidir = []
    for (const ticker of Object.keys(BOND_META)) {
      if (BOND_META[ticker].type === 'corporate') continue   // cronograma estimado: sin click
      const sched = generateSchedule(ticker) || []
      // Sólo los que devuelven capital EN CUOTAS (no el pago único al vencer).
      const cuotas = sched.filter(x => (x.amortPct || 0) > 0)
      if (cuotas.length < 2 || !(cuotas[0].date <= HOY)) continue
      if (!servidor[ticker] && !SIN_BARRIDO[ticker]) sinDecidir.push(ticker)
    }
    expect(sinDecidir, 'ya devuelven capital y nadie decidió quién les baja los nominales: '
      + 'sumalos al barrido del servidor o a SIN_BARRIDO con su motivo').toEqual([])
  })

  it('la lista no nombra bonos que el servidor ya barre', () => {
    for (const t of Object.keys(SIN_BARRIDO)) expect(servidor[t], t).toBeUndefined()
  })
})
