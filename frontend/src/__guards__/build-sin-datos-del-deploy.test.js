// El sitio publicado no lleva los datos del deploy (mensaje del commit, autor, repo).
// ═══════════════════════════════════════════════════════════════════════════
// 🔴 POR QUÉ (10/11/2026). Vercel le pasa a la compilación ~19 variables
// `VITE_VERCEL_*`: el mensaje ENTERO del último commit, quién lo hizo, el repo,
// el proyecto. Vite sólo las mete en el JS cuando el código nombra
// `import.meta.env` COMO VALOR (`import.meta.env && …`, `env[k]`, `{...env}`):
// ahí pega el objeto entero. `utils/valuationGuards.js` lo hacía para preguntar
// «¿es desarrollo?», y cada publicación dejaba el mensaje del commit legible
// para cualquiera que abriera el sitio — también los de los arreglos de
// seguridad, que describen el agujero que tapan.
//
// Esto no busca el texto en el código fuente (un `env` armado de otra forma no
// lo vería): compila el sitio DE VERDAD, con la misma configuración que Vercel,
// con un mensaje de commit inventado, y lo busca en lo que se publicaría.
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const MARCA_MENSAJE = 'MENSAJE-DE-COMMIT-QUE-NO-SE-PUBLICA-7f3a9c'
const MARCA_AUTOR = 'AUTOR-QUE-NO-SE-PUBLICA-2b81'
// Lo que Vercel pone en la compilación (Framework Environment Variables).
const DEL_DEPLOY = {
  VITE_VERCEL_GIT_COMMIT_MESSAGE: MARCA_MENSAJE,
  VITE_VERCEL_GIT_COMMIT_AUTHOR_NAME: MARCA_AUTOR,
  VITE_VERCEL_GIT_REPO_SLUG: 'repo-que-no-se-publica',
}

let salida
let antes
beforeAll(async () => {
  antes = { NODE_ENV: process.env.NODE_ENV }
  for (const k of Object.keys(DEL_DEPLOY)) antes[k] = process.env[k]
  Object.assign(process.env, DEL_DEPLOY, { NODE_ENV: 'production' })
  salida = fs.mkdtempSync(path.join(os.tmpdir(), 'rendi-build-'))
  const { build } = await import('vite')
  await build({
    root: FRONTEND,
    configFile: path.join(FRONTEND, 'vite.config.js'),
    mode: 'production',
    logLevel: 'silent',
    build: { outDir: salida, emptyOutDir: true, reportCompressedSize: false },
  })
}, 240_000)

afterAll(() => {
  for (const [k, v] of Object.entries(antes || {})) {
    if (v === undefined) delete process.env[k]
    else process.env[k] = v
  }
  if (salida) fs.rmSync(salida, { recursive: true, force: true })
})

function archivosDe(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e =>
    e.isDirectory() ? archivosDe(path.join(dir, e.name)) : [path.join(dir, e.name)])
}

describe('lo que se publica no lleva los datos del deploy', () => {
  it('la compilación salió (si no, «no aparece» no prueba nada)', () => {
    const js = archivosDe(salida).filter(f => f.endsWith('.js'))
    expect(js.length).toBeGreaterThan(20)
  })

  it('ni el mensaje del commit, ni el autor, ni el nombre de las variables', () => {
    const encontrados = []
    for (const f of archivosDe(salida)) {
      if (!/\.(js|html|css|json|txt|map)$/.test(f)) continue
      const s = fs.readFileSync(f, 'utf8')
      for (const marca of [MARCA_MENSAJE, MARCA_AUTOR, 'VITE_VERCEL_']) {
        if (s.includes(marca)) encontrados.push(`${path.relative(salida, f)}: ${marca}`)
      }
    }
    // Si da rojo: algún archivo nombra `import.meta.env` entero. Pedí la clave
    // (`import.meta.env.DEV`, `import.meta.env.VITE_ALGO`), nunca el objeto.
    expect(encontrados).toEqual([])
  })
})
