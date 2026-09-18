/**
 * El símbolo que se PIDE tiene que ser el que se LEE.
 *
 * EL BUG. El CEDEAR de Berkshire se llama `BRK.B`, y las dos puntas del sistema
 * le pegaban el sufijo a mano: `BRK.B` + `.BA` = `BRK.B.BA`, un símbolo que no
 * cotiza en ningún lado. Como era el único papel no-cash de esa cuenta, el cron
 * medía 0 % de cobertura, se negaba a guardar la foto del día —correctamente, no
 * quería escribir un valor subvaluado— y esa persona quedó sin un solo cierre
 * medido. Sin cierre medido no se puede medir una semana, ni un mes, ni la
 * variación diaria. Un punto en un ticker le apagó el historial entero.
 *
 * POR QUÉ NO SE ARREGLA "SACANDO LOS PUNTOS". Parece la regla obvia y está mal:
 * BYMA publica `AKO.B` CON punto. La normalización a lo bruto arreglaría
 * Berkshire y rompería Andina. Por eso es una lista de excepciones verificadas
 * contra el universo real de la fuente, y por eso este test existe: para que la
 * lista no se duplique mal.
 *
 * ESTE TEST LEE EL ARCHIVO DE PYTHON. Es el mismo recurso que usa
 * `bordeFresco.test.js` con el guard del backend, y por el mismo motivo: "la
 * misma tabla a propósito" sólo es una afirmación si algo la verifica. Están en
 * dos lenguajes y a dos capas de distancia; nada más las mantiene juntas.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, it, expect } from 'vitest'
import { BYMA_EXCEPCIONES, priceSymbol } from './valuation.js'

const AQUI = dirname(fileURLToPath(import.meta.url))

describe('el símbolo de BYMA', () => {
  it('Berkshire se pide como BRKB.BA, no como BRK.B.BA', () => {
    expect(priceSymbol('BRK.B', true)).toBe('BRKB.BA')
    expect(priceSymbol('BRK B', true)).toBe('BRKB.BA')
    expect(priceSymbol('BRK-B', true)).toBe('BRKB.BA')
    // Y por la rama del CEDEAR, que es por donde entra desde un broker en dólares.
    expect(priceSymbol('BRK.B', false, 'CEDEAR')).toBe('BRKB.BA')
  })

  it('el ticker de Nueva York sigue normalizando con guión, como antes', () => {
    // La rama US no cambió: yfinance cotiza las clases con guión.
    expect(priceSymbol('BRK.B', false)).toBe('BRK-B')
  })

  it('un ticker que BYMA SÍ publica con punto no se toca', () => {
    // AKO.B existe tal cual en BYMA. Si alguien "generaliza" la excepción a una
    // regla de sacar puntos, este test se pone en rojo.
    expect(priceSymbol('AKO.B', true)).toBe('AKO.B.BA')
  })

  it('un ticker común no se ve afectado', () => {
    expect(priceSymbol('NVDA', true)).toBe('NVDA.BA')
    expect(priceSymbol('GGAL', true)).toBe('GGAL.BA')
  })

  it('la tabla dice lo MISMO que la del backend', () => {
    const py = readFileSync(resolve(AQUI, '../../../backend/snapshots_job.py'), 'utf8')
    const bloque = py.match(/BYMA_EXCEPCIONES = \{([^}]*)\}/)
    expect(bloque, 'no se encontró BYMA_EXCEPCIONES en snapshots_job.py').toBeTruthy()

    const delBackend = {}
    for (const m of bloque[1].matchAll(/'([^']+)':\s*'([^']+)'/g)) {
      delBackend[m[1]] = m[2]
    }
    expect(delBackend).toEqual(BYMA_EXCEPCIONES)
  })
})
