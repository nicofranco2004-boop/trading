// La regla de "esta fila no tiene una cuenta a la que escribirle".
//
// POR QUÉ ESTE TEST
// ─────────────────
// La regla estaba escrita SIETE veces y ya había divergido: las tres del
// celular (vender, agregar compra, eliminar) miraban `_multiBroker` y el broker
// nulo pero NO `_multiCcy` — la fila de una sola pata con lotes en dos monedas,
// que es la que arma el importador de Balanz, se les colaba. Y el comentario
// arriba de esas tres líneas decía estar cubriendo justamente ese caso.
//
// La octava, las cobranzas del bono, nunca tuvo guard: el registro moría con
// el error crudo del backend en pantalla (`broker: Input should be a valid
// string`, input null). Verificado en la app el 2026-09-22.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { filaSinUnaPata } from './filaFusionada.js'

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')

describe('filaSinUnaPata', () => {
  it('la fila que junta las dos patas de la cuenta no tiene una', () => {
    expect(filaSinUnaPata({ _multiBroker: true, broker: null })).toBe(true)
  })

  it('la de UNA pata con lotes en dos monedas tampoco — el caso que el celular se comía', () => {
    expect(filaSinUnaPata({ _multiCcy: true, broker: 'Balanz' })).toBe(true)
  })

  it('un broker nulo, venga de donde venga, tampoco', () => {
    expect(filaSinUnaPata({ broker: null })).toBe(true)
  })

  it('la fila normal SÍ tiene su cuenta: no se bloquea nada', () => {
    expect(filaSinUnaPata({ broker: 'Cocos', asset: 'AL30' })).toBe(false)
    // Una fila agrupada de varios lotes del MISMO broker es normal.
    expect(filaSinUnaPata({ broker: 'Cocos', _isAgg: true, _lotCount: 3 })).toBe(false)
  })

  it('el efectivo queda afuera: no es una posición que se venda ni se cobre', () => {
    expect(filaSinUnaPata({ is_cash: true, broker: null })).toBe(false)
  })

  it('sin fila no hay nada que bloquear', () => {
    expect(filaSinUnaPata(null)).toBe(false)
    expect(filaSinUnaPata(undefined)).toBe(false)
  })
})

// ─── Vigilancia del código fuente ────────────────────────────────────────────
function archivosJsx(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivosJsx(p)
    return /\.jsx?$/.test(n) && !/\.test\.jsx?$/.test(n) ? [p] : []
  })
}

describe('la regla vive en un solo lugar', () => {
  it('nadie la vuelve a escribir a mano', () => {
    const malos = []
    for (const f of archivosJsx(SRC)) {
      if (/utils\/filaFusionada\.js$/.test(f)) continue
      const src = readFileSync(f, 'utf8')
      // Las tres formas que existían antes de unificar.
      if (/_multiBroker\s*\|\|\s*p\??\.?_multiCcy/.test(src)
          || /_multiBroker\s*\|\|\s*\(p && !p\.is_cash && p\.broker == null\)/.test(src)) {
        malos.push(f.slice(SRC.length + 1))
      }
    }
    expect(malos, 'volvió una copia de la regla: ya divergió una vez').toEqual([])
  })

  it('los ocho lugares que la usan la piden a la función', () => {
    let usos = 0
    for (const f of archivosJsx(SRC)) {
      if (/utils\/filaFusionada\.js$/.test(f)) continue
      usos += (readFileSync(f, 'utf8').match(/filaSinUnaPata\s*\(/g) || []).length
    }
    // 5 en celular (vender, agregar, eliminar, editar grupo, menú de acciones),
    // 2 en escritorio (editar y vender) y 1 en el menú compartido… más las 2
    // que se la pasan al panel del bono como prop.
    expect(usos).toBeGreaterThanOrEqual(8)
  })

  it('el panel del bono decide con la FILA, no con el resumen de cobranzas', () => {
    // El bug de la primera versión: un bono en las dos patas SIN cobros no tiene
    // resumen, así que `summary?._variasPatas` era undefined y los botones
    // quedaban a la vista — justo el caso más común.
    const bd = readFileSync(join(SRC, 'components/BondDetail.jsx'), 'utf8')
    expect(bd).toMatch(/filaFusionada/)
    expect(bd, 'la condición volvió a colgar del resumen').not.toMatch(/_variasPatas/)
    const merge = readFileSync(join(SRC, 'utils/bondSummaryMerge.js'), 'utf8')
    expect(merge, 'el resumen volvió a opinar sobre la escritura').not.toMatch(/_variasPatas/)
  })
})
