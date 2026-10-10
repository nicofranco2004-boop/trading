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
