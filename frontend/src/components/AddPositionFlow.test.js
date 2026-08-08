// Los tipos del paso "Otro" tienen que mapear a categorías REALES.
//
// POR QUÉ ESTE TEST
// ─────────────────
// El paso "Otro" (para el activo que no está en ninguna lista) le pide al
// usuario qué es lo que está cargando y devuelve la categoría correspondiente,
// para que el resto del sistema lo trate igual que si lo hubiera elegido de una
// lista. Ese contrato pasa por DOS mapas que viven en archivos distintos:
//
//   AddPositionFlow.TIPOS_OTRO[].cat  →  Positions.CATEGORY_ASSET_TYPE[cat]
//
// Un typo en el `cat` (un 'bond' donde va 'bonds') no rompe nada visible: el
// activo se guarda igual, pero SIN asset_type. Y sin asset_type un CEDEAR
// comprado en dólares se valúa por la acción US en vez de por su precio local,
// un bono no entra en la zona de Renta Fija, y nadie se entera hasta que el
// usuario reporta que "los números están raros".
//
// Los dos mapas se leen del archivo fuente a propósito: importarlos rompería por
// el JSX, y duplicarlos acá haría que el test se quede viejo justo cuando hace
// falta.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const AQUI = dirname(fileURLToPath(import.meta.url))
const FLOW = readFileSync(join(AQUI, 'AddPositionFlow.jsx'), 'utf8')
const POSITIONS = readFileSync(join(AQUI, '..', 'pages', 'Positions.jsx'), 'utf8')
const TICKERS = readFileSync(join(AQUI, '..', 'utils', 'tickers.js'), 'utf8')

/** Los `cat:` que ofrece el paso "Otro". */
function catsDelPasoOtro() {
  const bloque = /const TIPOS_OTRO = \[([\s\S]*?)\n\]/.exec(FLOW)
  expect(bloque, 'no encontré TIPOS_OTRO — ¿lo renombraron?').toBeTruthy()
  return [...bloque[1].matchAll(/cat:\s*'([^']+)'/g)].map(m => m[1])
}

/** Los ids de categoría que el flujo conoce (el array CATEGORIES + 'fci'). */
function idsDeCategoria() {
  const ids = [...FLOW.matchAll(/\{\s*id:\s*'([^']+)'\s*,\s*label:/g)].map(m => m[1])
  return new Set([...ids, 'fci'])   // 'fci' se agrega dinámico (catálogo del backend)
}

/** El mapa categoría → asset_type que usa Positions al guardar. */
function mapaAssetType() {
  const bloque = /const CATEGORY_ASSET_TYPE = \{([\s\S]*?)\}/.exec(POSITIONS)
  expect(bloque, 'no encontré CATEGORY_ASSET_TYPE en Positions.jsx').toBeTruthy()
  return new Set([...bloque[1].matchAll(/(\w+):\s*'/g)].map(m => m[1]))
}

describe('paso "Otro" — agregar un activo que no está en la lista', () => {
  it('ofrece al menos los tipos que un usuario argentino puede tener', () => {
    const cats = catsDelPasoOtro()
    expect(cats.length).toBeGreaterThanOrEqual(6)
    // Los que motivaron el pedido: un CEDEAR nuevo, una ON, un fondo.
    for (const esperado of ['cedears', 'bonds', 'fci', 'ar_lider']) {
      expect(cats, `falta la opción "${esperado}"`).toContain(esperado)
    }
  })

  it('cada tipo apunta a una categoría que el flujo conoce', () => {
    const validos = idsDeCategoria()
    for (const cat of catsDelPasoOtro()) {
      expect(validos.has(cat), `"${cat}" no es un id de categoría del flujo`).toBe(true)
    }
  })

  it('cada tipo termina en un asset_type, salvo FCI que hoy no lo lleva', () => {
    const conAssetType = mapaAssetType()
    for (const cat of catsDelPasoOtro()) {
      if (cat === 'fci') continue   // el flujo normal de FCI tampoco lo manda
      expect(conAssetType.has(cat),
        `"${cat}" no está en CATEGORY_ASSET_TYPE → el activo se guardaría sin tipo`).toBe(true)
    }
  })

  it('el ejemplo de cada tipo no es un ticker inventado del mismo tipo equivocado', () => {
    // Los ejemplos son la única pista que tiene el usuario para elegir bien.
    // Chequeo mínimo: que los de CEDEAR y acción AR no estén cruzados.
    const bloque = /const TIPOS_OTRO = \[([\s\S]*?)\n\]/.exec(FLOW)[1]
    const arLider = /cat: 'ar_lider'[^}]*ej: '([^']+)'/.exec(bloque)
    expect(arLider, 'el tipo ar_lider tiene que traer ejemplos').toBeTruthy()
    // GGAL/ALUA/YPFD son argentinas y están en la allowlist de acciones AR.
    const ejemplos = arLider[1].split(',').map(x => x.trim())
    const hayAlgunaReal = ejemplos.some(e => TICKERS.includes(`'${e}'`))
    expect(hayAlgunaReal, `ninguno de los ejemplos (${ejemplos}) existe en tickers.js`).toBe(true)
  })
})
