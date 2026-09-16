// Busca la fuga de alcance entre un `try` y su `catch`/`finally`.
//
// POR QUÉ EXISTE
// ──────────────
// Producción, 2026-09-16: `VozContext.jsx` tenía `let agregado = false` DENTRO
// del `try`, y el `catch` la usaba. `let` es de bloque: el catch nunca la vio.
// O sea que el manejador de errores reventaba con "agregado is not defined"
// JUSTO cuando había un error que mostrar, y se llevaba puesto el árbol entero
// hasta el ErrorBoundary — pantalla rota en vez del mensaje.
//
// El alcance del daño no era el caso reportado: por ese mismo catch pasaban
// TODOS los errores del chat (cuota agotada, gate de plan, timeout, red caída).
// El más común de todos es el de cuota, así que le pegaba sobre todo a los Free
// al llegar a su límite semanal.
//
// Nada lo detectaba. Ni el build, ni los tests, ni el ojo: el código "se lee"
// perfecto. Sólo aparece cuando hay un error de verdad — el peor momento para
// descubrirlo. Este escáner es lo que faltaba.
//
// POR QUÉ CON PARSER Y NO CON grep
// ────────────────────────────────
// Buscar texto no distingue una variable de la misma palabra adentro de un
// comentario o de un string, ni sabe dónde empieza y termina un bloque. Se usa
// @babel/parser, que es el MISMO que ya usa el build (declarado en package.json
// para que `npm ci` no dependa de que alguien más lo arrastre).
//
// Vive fuera de `src/` a propósito, igual que design-patterns.mjs: si estuviera
// adentro se escanearía a sí mismo.
import { parse } from '@babel/parser'
import fs from 'node:fs'
import path from 'node:path'

function archivosJs(raiz) {
  const out = []
  ;(function caminar(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name)
      if (e.isDirectory()) {
        if (e.name !== 'node_modules') caminar(p)
      } else if (/\.(js|jsx)$/.test(e.name)) {
        out.push(p)
      }
    }
  })(raiz)
  return out
}

// Recorre el árbol sintáctico. `padre` sirve para descartar identificadores que
// NO son referencias a una variable: la `x` de `obj.x` y la clave de `{ x: 1 }`.
function recorrer(n, fn, padre = null) {
  if (!n || typeof n.type !== 'string') return
  fn(n, padre)
  for (const k of Object.keys(n)) {
    if (k === 'loc' || k === 'leadingComments' || k === 'trailingComments') continue
    const v = n[k]
    if (Array.isArray(v)) {
      for (const c of v) if (c && typeof c.type === 'string') recorrer(c, fn, n)
    } else if (v && typeof v.type === 'string') {
      recorrer(v, fn, n)
    }
  }
}

/**
 * Devuelve las fugas encontradas bajo `raiz`:
 *   { archivo, nombre, declaradaEn, usadaEn, bloque: 'catch'|'finally' }
 *
 * Sólo mira `let`/`const`/`class`: `var` se iza a toda la función, así que desde
 * el catch SÍ se ve y no es un bug.
 */
export function buscarFugasDeAlcance(raiz) {
  const fugas = []
  for (const archivo of archivosJs(raiz)) {
    let ast
    try {
      ast = parse(fs.readFileSync(archivo, 'utf8'), { sourceType: 'module', plugins: ['jsx'] })
    } catch {
      continue   // un archivo que ni siquiera parsea ya falla por otro lado
    }
    recorrer(ast, (n) => {
      if (n.type !== 'TryStatement') return

      const declaradas = new Map()
      recorrer(n.block, (m) => {
        if (m.type === 'VariableDeclaration' && m.kind !== 'var') {
          for (const d of m.declarations) {
            if (d.id.type === 'Identifier') declaradas.set(d.id.name, m.loc.start.line)
          }
        }
        if (m.type === 'ClassDeclaration' && m.id) declaradas.set(m.id.name, m.loc.start.line)
      })
      if (declaradas.size === 0) return

      for (const [bloque, cuerpo] of [['catch', n.handler?.body], ['finally', n.finalizer]]) {
        if (!cuerpo) continue
        // Lo que el propio catch/finally declara (y el parámetro del catch) tapa
        // a lo de afuera: no es una fuga.
        const propias = new Set()
        if (bloque === 'catch' && n.handler?.param?.type === 'Identifier') {
          propias.add(n.handler.param.name)
        }
        recorrer(cuerpo, (m) => {
          if (m.type !== 'VariableDeclaration') return
          for (const d of m.declarations) if (d.id.type === 'Identifier') propias.add(d.id.name)
        })
        recorrer(cuerpo, (m, padre) => {
          if (m.type !== 'Identifier') return
          if (padre?.type === 'MemberExpression' && padre.property === m && !padre.computed) return
          if ((padre?.type === 'ObjectProperty' || padre?.type === 'ObjectMethod')
              && padre.key === m && !padre.computed) return
          if (propias.has(m.name) || !declaradas.has(m.name)) return
          fugas.push({
            archivo: path.relative(raiz, archivo),
            nombre: m.name,
            declaradaEn: declaradas.get(m.name),
            usadaEn: m.loc.start.line,
            bloque,
          })
        })
      }
    })
  }
  return fugas
}

// Modo suelto: `node scripts/scan-try-catch-scope.mjs [ruta]`
if (import.meta.url === `file://${process.argv[1]}`) {
  const raiz = path.resolve(process.argv[2] || 'src')
  const fugas = buscarFugasDeAlcance(raiz)
  for (const f of fugas) {
    console.log(`🔴 ${f.archivo}`)
    console.log(`   "${f.nombre}" se declara en la línea ${f.declaradaEn} (adentro del try)`)
    console.log(`   y se usa en la línea ${f.usadaEn}, adentro del ${f.bloque} → ReferenceError\n`)
  }
  console.log(`fugas de alcance try→catch/finally: ${fugas.length}`)
  process.exit(fugas.length ? 1 : 0)
}
