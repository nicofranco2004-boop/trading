// Toda pantalla que pide un cupo por su etiqueta tiene que pedir una que EXISTA.
//
// POR QUÉ ESTE TEST
// ─────────────────
// `cupoDe(plan, 'Chat … / sem')` busca el número por el texto exacto de la
// etiqueta y, si no lo encuentra, no avisa: devuelve vacío y la página dice
// "Pro: undefined consultas/sem". La etiqueta del chat estaba escrita a mano en
// nueve pantallas; al renombrar la IA (2026-10-03) se cambiaron bien, pero sólo
// la home tenía un test que lo vigilara (auditoría 2026-10-04). Ahora la del
// chat es una constante (`CUPO_CHAT`) y este test recorre el árbol: una
// etiqueta escrita a mano que no está en el catálogo es un rojo.
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'fs'
import { resolve, dirname, join } from 'path'
import { fileURLToPath } from 'url'
import { FREE_FEATURES, PLUS_FEATURES, PRO_FEATURES, CUPO_CHAT } from './planCatalog'

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function fuentes(dir = SRC) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name)
    if (e.isDirectory()) return e.name === 'node_modules' ? [] : fuentes(p)
    return /\.(js|jsx)$/.test(e.name) && !/\.test\./.test(e.name) ? [p] : []
  })
}

const ETIQUETAS = new Set(
  [FREE_FEATURES, PLUS_FEATURES, PRO_FEATURES].flatMap((p) => (p?.quotas || []).map((q) => q.label)),
)

describe('cupoDe — las etiquetas que se piden existen', () => {
  it('el catálogo tiene el cupo de chat en los tres planes, con la constante', () => {
    for (const plan of [FREE_FEATURES, PLUS_FEATURES, PRO_FEATURES]) {
      expect(plan.quotas.some((q) => q.label === CUPO_CHAT)).toBe(true)
    }
  })

  it('cada cupoDe / vecesMas con una etiqueta escrita a mano pide una del catálogo', () => {
    const malas = []
    let vistas = 0
    const LLAMADAS = [
      /cupoDe\([^,()]+,\s*(['"`])([^'"`]+)\1\s*\)/g,                 // cupoDe(plan, 'etiqueta')
      /vecesMas\([^,()]+,[^,()]+,\s*(['"`])([^'"`]+)\1\s*\)/g,       // vecesMas(plan, otro, 'etiqueta')
    ]
    for (const archivo of fuentes()) {
      const texto = readFileSync(archivo, 'utf8')
      for (const patron of LLAMADAS) {
        for (const m of texto.matchAll(patron)) {
          vistas++
          if (!ETIQUETAS.has(m[2])) malas.push(`${archivo.replace(SRC + '/', '')}: «${m[2]}»`)
        }
      }
    }
    expect(vistas, 'el recorrido no encontró ningún cupoDe con etiqueta: ¿cambió la forma de llamarlo?').toBeGreaterThan(0)
    expect(malas, 'etiquetas que el catálogo no tiene (la página diría "undefined")').toEqual([])
  })

  it('la etiqueta del chat no vuelve a escribirse a mano fuera del catálogo', () => {
    const copias = fuentes()
      .filter((a) => !a.endsWith('planCatalog.js'))
      .filter((a) => {
        const t = readFileSync(a, 'utf8')
        return [`'${CUPO_CHAT}'`, `"${CUPO_CHAT}"`, `\`${CUPO_CHAT}\``].some((c) => t.includes(c))
      })
      .map((a) => a.replace(SRC + '/', ''))
    expect(copias, 'usá CUPO_CHAT de data/planCatalog').toEqual([])
  })
})
