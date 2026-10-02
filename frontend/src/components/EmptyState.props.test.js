import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// EmptyState lee `description`. News y Events le pasaban `subtitle` desde
// mayo de 2026 y la explicación ("No hay noticias recientes de los activos de
// tu cartera") no se vio nunca: una prop que el componente no lee no da error.
const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const PROPS = new Set(['icon', 'eyebrow', 'title', 'description', 'action', 'dense', 'tone', 'key'])

function archivos(dir) {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    if (statSync(p).isDirectory()) return archivos(p)
    return /\.jsx?$/.test(n) && !/\.test\./.test(n) ? [p] : []
  })
}

// Las props de primer nivel de cada <EmptyState …>: lo que está entre llaves
// (un ícono con sus propias props, un texto con `=`) no cuenta.
function propsDe(txt, desde) {
  const props = []
  let llaves = 0
  for (let i = desde; i < txt.length; i++) {
    const c = txt[i]
    if (c === '{') llaves++
    else if (c === '}') llaves--
    else if (llaves === 0) {
      if (c === '>' || (c === '/' && txt[i + 1] === '>')) break
      const m = /^\s([a-zA-Z]+)=/.exec(txt.slice(i, i + 40))
      if (m) props.push(m[1])
    }
  }
  return props
}

describe('EmptyState — cada llamada usa props que el componente lee', () => {
  it('ninguna prop desconocida (subtitle, message, …)', () => {
    const malas = []
    for (const f of archivos(SRC)) {
      const txt = readFileSync(f, 'utf8')
      for (const m of txt.matchAll(/<EmptyState\b/g)) {
        for (const prop of propsDe(txt, m.index + m[0].length)) {
          if (!PROPS.has(prop)) malas.push(`${f.slice(SRC.length + 1)}: ${prop}`)
        }
      }
    }
    expect(malas).toEqual([])
  })
})
