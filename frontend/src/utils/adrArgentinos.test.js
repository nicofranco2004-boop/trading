import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { ADR_DE_ACCION_AR } from './tickers'
import { classifyAsset } from './assetClass'

// La lista de ADRs argentinos sirve para DOS cosas: el buscador abre la empresa
// de una acción argentina por su ADR (tickers.js, ADR_DE_ACCION_AR), y la torta
// cuenta un ADR en un broker del exterior como "Acción AR" (assetClass.js toma
// los de esa tabla). Si alguien saca uno pensando en el buscador, la torta de
// quien lo tiene cambia sin aviso. Y el servidor tiene su propia copia
// (backend/behavioral.py, _AR_ADRS) para el diagnóstico de "sesgo local".
const AQUI = dirname(fileURLToPath(import.meta.url))
const delServidor = () => {
  const py = readFileSync(resolve(AQUI, '../../../backend/behavioral.py'), 'utf-8')
  const bloque = py.match(/_AR_ADRS = frozenset\(\{([\s\S]*?)\}\)/)
  expect(bloque, 'no encontré _AR_ADRS en behavioral.py').toBeTruthy()
  // Con cualquier comilla: con sólo las dobles, un 'VIST' agregado en el
  // servidor pasaba en verde. Si queda una entrada sin leer, rojo.
  const cuerpo = bloque[1].replace(/#[^\n]*/g, '')
  const leidos = [...cuerpo.matchAll(/['"]([A-Z0-9.]+)['"]/g)].map(m => m[1])
  const entradas = cuerpo.split(',').map(x => x.trim()).filter(Boolean)
  expect(leidos.length, 'hay una entrada de _AR_ADRS que no se pudo leer').toBe(entradas.length)
  return leidos.sort()
}
// DESP (Despegar) es argentina pero no cotiza en BYMA: va aparte en assetClass.
const deLaPantalla = () => [...new Set([...Object.values(ADR_DE_ACCION_AR), 'DESP'])].sort()

describe('ADRs argentinos: una lista, la misma en la pantalla y en el servidor', () => {
  it('son los mismos en los dos lados', () => {
    expect(deLaPantalla()).toEqual(delServidor())
  })
  it('cada uno, en un broker del exterior, cuenta como "Acción AR" en la torta', () => {
    const brokers = [{ name: 'Schwab', currency: 'USD' }]
    for (const s of delServidor()) {
      expect(classifyAsset({ asset: s, broker: 'Schwab' }, brokers), s).toBe('accion_ar')
    }
  })
})
