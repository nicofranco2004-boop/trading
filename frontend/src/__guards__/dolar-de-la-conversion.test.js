// Rendi pasa cada operación en pesos al dólar MEP DE SU FECHA (backend/fx.py:
// MEP → blue sólo antes de 2018, cuando no hay serie del MEP). Las páginas
// públicas decían "al dólar blue del día", "P&L real en USD blue" y "cobramos al
// TC blue del día": falso, y desde que las páginas se publican ya escritas
// (scripts/prerender.mjs) es lo que leen y repiten las IA. Esto no deja que vuelva.
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = fileURLToPath(new URL('..', import.meta.url))
const LUGARES = ['pages', 'components/landing', 'components/blog', 'components/guide']

function archivos(dir) {
  return readdirSync(dir).flatMap((n) => {
    const r = join(dir, n)
    if (statSync(r).isDirectory()) return archivos(r)
    return /\.jsx?$/.test(n) && !/\.test\./.test(n) ? [r] : []
  })
}
const sinComentarios = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n').filter((l) => !l.trimStart().startsWith('//')).join('\n')

const MENTIRAS = [
  /(convierte|pasa|convertimos)[^.'"`]{0,40}d[óo]lar blue/i,
  /USD blue[,.]/,
  /en d[óo]lares blue/i,
  /TC blue del d[íi]a/i,
  /TC blue autom[áa]tico/i,
]

describe('ninguna página dice que Rendi pasa los pesos al dólar blue', () => {
  it('ni en la portada, ni en las landings, el blog o la guía', () => {
    const hallazgos = []
    for (const lugar of LUGARES) {
      for (const f of archivos(join(SRC, lugar))) {
        const src = sinComentarios(readFileSync(f, 'utf8'))
        for (const re of MENTIRAS) {
          const m = src.match(re)
          if (m) hallazgos.push(`${f.slice(SRC.length)}: «${m[0]}»`)
        }
      }
    }
    expect(hallazgos).toEqual([])
  })
})
