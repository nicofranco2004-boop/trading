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
//
// Nada lo detectaba. Ni el build, ni los tests, ni el ojo: el código "se lee"
// perfecto. Sólo aparece cuando hay un error de verdad — el peor momento para
// descubrirlo.
//
// LO QUE APRENDIÓ AUDITÁNDOSE (2026-09-16, mismo día)
// ───────────────────────────────────────────────────
// La primera versión fallaba en las DOS direcciones:
//
//   • Ciega a `const { mensaje, usage } = …` y a `const [a, b] = …`. Sólo
//     miraba `d.id.type === 'Identifier'`, así que cualquier desestructurado
//     pasaba. Grave: el catch que originó todo esto usa justamente
//     `const { mensaje, usage, upgrade, kind, codigo } = traducirErrorDeChat(e)`.
//   • Ciega a `function ayuda() {}` declarada adentro del try.
//   • Y al revés: reportaba un caso VÁLIDO. Si hay una `dato` declarada ANTES
//     del try y otra `dato` en un bloque anidado adentro, el catch ve la de
//     afuera y no pasa nada. Un falso positivo en un guard de tolerancia cero
//     es peor que no tenerlo: pone la suite en rojo sobre código correcto, y lo
//     que se hace entonces es borrar el guard.
//
// POR QUÉ CON PARSER Y NO CON grep
// ────────────────────────────────
// Buscar texto no distingue una variable de la misma palabra adentro de un
// comentario o de un string, ni sabe dónde empieza y termina un bloque. Se usa
// @babel/parser, el MISMO que ya usa el build (declarado en package.json, y
// pinneado a la ^7 que ya estaba: pedir la ^8 empujaba diez copias anidadas).
//
// Vive fuera de `src/` a propósito, igual que design-patterns.mjs: si estuviera
// adentro se escanearía a sí mismo.
import { parse } from '@babel/parser'
import fs from 'node:fs'
import path from 'node:path'

const TIPOS_FUNCION = new Set([
  'FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression',
  'ObjectMethod', 'ClassMethod', 'ClassPrivateMethod',
])

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

// `padre` sirve para descartar identificadores que NO son referencias a una
// variable: la `x` de `obj.x` y la clave de `{ x: 1 }`.
// `entrarAFunciones=false` corta en el borde de una función anidada: lo que se
// declara ahí adentro no vive en el alcance del try.
function recorrer(n, fn, { entrarAFunciones = true } = {}, padre = null) {
  if (!n || typeof n.type !== 'string') return
  fn(n, padre)
  if (!entrarAFunciones && padre && TIPOS_FUNCION.has(n.type)) return
  for (const k of Object.keys(n)) {
    if (k === 'loc' || k === 'leadingComments' || k === 'trailingComments') continue
    const v = n[k]
    if (Array.isArray(v)) {
      for (const c of v) if (c && typeof c.type === 'string') recorrer(c, fn, { entrarAFunciones }, n)
    } else if (v && typeof v.type === 'string') {
      recorrer(v, fn, { entrarAFunciones }, n)
    }
  }
}

// Todos los nombres que ATA un patrón de declaración: el simple `x`, el objeto
// `{ a, b: c, ...resto }`, el array `[a, , b]`, y los valores por defecto.
export function nombresDelPatron(nodo, out = []) {
  if (!nodo || typeof nodo.type !== 'string') return out
  switch (nodo.type) {
    case 'Identifier':
      out.push(nodo.name); break
    case 'ObjectPattern':
      for (const p of nodo.properties) {
        nombresDelPatron(p.type === 'RestElement' ? p.argument : p.value, out)
      }
      break
    case 'ArrayPattern':
      for (const el of nodo.elements) nombresDelPatron(el, out)
      break
    case 'AssignmentPattern':
      nombresDelPatron(nodo.left, out); break
    case 'RestElement':
      nombresDelPatron(nodo.argument, out); break
    default:
      break
  }
  return out
}

function mapaDePadres(ast) {
  const padres = new Map()
  recorrer(ast, (n, p) => { if (p) padres.set(n, p) })
  return padres
}

// ¿Este nivel ata `nombre`? Sólo mira las declaraciones DE ESTE nivel (las de
// bloque viven en su propio bloque) más, en una función, sus parámetros y los
// `var` de adentro (que se izan a toda la función).
function ataEnEsteNivel(scope, nombre) {
  const cuerpo = TIPOS_FUNCION.has(scope.type) ? scope.body : scope
  if (TIPOS_FUNCION.has(scope.type)) {
    for (const p of scope.params || []) {
      if (nombresDelPatron(p).includes(nombre)) return true
    }
    // `var` de cualquier profundidad (sin entrar a funciones anidadas)
    let hay = false
    recorrer(scope.body, (m) => {
      if (m.type === 'VariableDeclaration' && m.kind === 'var') {
        for (const d of m.declarations) if (nombresDelPatron(d.id).includes(nombre)) hay = true
      }
    }, { entrarAFunciones: false })
    if (hay) return true
  }
  const sentencias = cuerpo && Array.isArray(cuerpo.body) ? cuerpo.body : []
  for (const s of sentencias) {
    if (s.type === 'VariableDeclaration') {
      for (const d of s.declarations) if (nombresDelPatron(d.id).includes(nombre)) return true
    }
    if ((s.type === 'FunctionDeclaration' || s.type === 'ClassDeclaration') && s.id?.name === nombre) {
      return true
    }
  }
  return false
}

// ¿El catch ve una `nombre` de AFUERA del try? Si la ve, no hay fuga: la de
// adentro le hace sombra a la de afuera mientras dura el try, y listo.
function hayBindingAfuera(nombre, tryNode, padres) {
  let p = padres.get(tryNode)
  while (p) {
    if (p.type === 'BlockStatement' || p.type === 'Program' || TIPOS_FUNCION.has(p.type)) {
      if (ataEnEsteNivel(p, nombre)) return true
    }
    p = padres.get(p)
  }
  return false
}

/**
 * Devuelve las fugas encontradas bajo `raiz`:
 *   { archivo, nombre, declaradaEn, usadaEn, bloque: 'catch'|'finally' }
 *
 * `var` no cuenta: se iza a toda la función, así que desde el catch SÍ se ve.
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
    const padres = mapaDePadres(ast)

    recorrer(ast, (n) => {
      if (n.type !== 'TryStatement') return

      // Lo que el try ata y el catch NO puede ver. Sin entrar a funciones
      // anidadas: eso vive en otro alcance y no es esta falla.
      const declaradas = new Map()
      recorrer(n.block, (m) => {
        if (m.type === 'VariableDeclaration' && m.kind !== 'var') {
          for (const d of m.declarations) {
            for (const nom of nombresDelPatron(d.id)) declaradas.set(nom, m.loc.start.line)
          }
        }
        if ((m.type === 'ClassDeclaration' || m.type === 'FunctionDeclaration') && m.id) {
          declaradas.set(m.id.name, m.loc.start.line)
        }
      }, { entrarAFunciones: false })
      if (declaradas.size === 0) return

      for (const [bloque, cuerpo] of [['catch', n.handler?.body], ['finally', n.finalizer]]) {
        if (!cuerpo) continue
        // Lo que el propio catch/finally ata (y el parámetro del catch) tapa a
        // lo de afuera: no es una fuga.
        const propias = new Set()
        if (bloque === 'catch' && n.handler?.param) {
          for (const nom of nombresDelPatron(n.handler.param)) propias.add(nom)
        }
        recorrer(cuerpo, (m) => {
          if (m.type === 'VariableDeclaration') {
            for (const d of m.declarations) for (const nom of nombresDelPatron(d.id)) propias.add(nom)
          }
          if ((m.type === 'FunctionDeclaration' || m.type === 'ClassDeclaration') && m.id) {
            propias.add(m.id.name)
          }
        })
        const yaReportadas = new Set()
        recorrer(cuerpo, (m, padre) => {
          if (m.type !== 'Identifier') return
          if (padre?.type === 'MemberExpression' && padre.property === m && !padre.computed) return
          if ((padre?.type === 'ObjectProperty' || padre?.type === 'ObjectMethod')
              && padre.key === m && !padre.computed) return
          if (propias.has(m.name) || !declaradas.has(m.name)) return
          if (hayBindingAfuera(m.name, n, padres)) return
          const clave = `${m.name}:${m.loc.start.line}`
          if (yaReportadas.has(clave)) return
          yaReportadas.add(clave)
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
