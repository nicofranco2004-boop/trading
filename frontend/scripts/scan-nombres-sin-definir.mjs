// Busca nombres que se USAN y no están definidos en ningún lado.
//
// POR QUÉ EXISTE
// ──────────────
// 2026-10-01, antes de publicar: al unificar los formateadores de porcentaje se
// borró el `const pct = (v) => …` local de `Admin.jsx`, y dos renglones de la
// tabla de la auditoría MTM, 600 líneas más abajo, lo seguían llamando. La
// búsqueda que tenía que encontrarlos miró sólo un tramo del archivo. El build
// compiló, los 2.444 tests pasaron, y la primera fila de esa tabla habría
// tirado "pct is not defined" y tapado la pantalla entera con el ErrorBoundary.
// Lo encontró una auditoría, no el sistema.
//
// Es la misma familia que el backtick que falta en un className
// (`font-medium` leído como `font - medium` → "font is not defined", la página
// de pago caída) y que la variable del try que el catch no ve
// (scan-try-catch-scope.mjs): JavaScript sólo se entera cuando ejecuta ESE
// renglón. Este escaneo se entera antes.
//
// QUÉ CUENTA COMO DEFINIDO
// ────────────────────────
// Lo que el propio archivo declara o importa (lo resuelve @babel/traverse con
// el alcance real: bloques, parámetros, desestructurados, funciones izadas),
// los globales del lenguaje (`Math`, `Date`…, de @babel/helper-globals), los
// del navegador (abajo, a mano: helper-globals no trae los de minúscula) y las
// constantes que inyecta vite.config.js (`define`).
// No cuenta como uso: `typeof x` (es legal sobre algo no declarado) ni el
// nombre de una etiqueta de HTML en JSX (`<div>`).
//
// Las dos librerías van declaradas en package.json con la versión EXACTA que
// ya estaba instalada: pedir un rango actualizaba una docena de paquetes de
// babel de arrastre.
//
// Vive fuera de `src/` a propósito, igual que los otros escaneos.
import { parse } from '@babel/parser'
import _traverse from '@babel/traverse'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const traverse = _traverse.default || _traverse
const require = createRequire(import.meta.url)

// Globales del navegador en minúscula que el código usa. Si un uso nuevo y
// LEGÍTIMO de un global del navegador hace saltar el guard, se suma acá.
export const GLOBALES_NAVEGADOR = [
  'window', 'document', 'navigator', 'location', 'history', 'screen',
  'localStorage', 'sessionStorage', 'indexedDB', 'caches', 'crypto', 'performance',
  'console', 'fetch', 'alert', 'confirm', 'prompt', 'open', 'close', 'print',
  'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'queueMicrotask',
  'requestAnimationFrame', 'cancelAnimationFrame', 'requestIdleCallback', 'cancelIdleCallback',
  'structuredClone', 'matchMedia', 'getComputedStyle', 'getSelection', 'scrollTo', 'scrollBy',
  'scrollX', 'scrollY', 'innerWidth', 'innerHeight', 'outerWidth', 'outerHeight',
  'devicePixelRatio', 'visualViewport', 'customElements', 'atob', 'btoa',
  'addEventListener', 'removeEventListener', 'dispatchEvent', 'postMessage',
  'self', 'top', 'parent', 'frames', 'opener', 'origin', 'name', 'status',
  // Node, para los tests y los scripts que viven en src/
  'process', 'Buffer', 'global', '__dirname', '__filename', 'require', 'module', 'exports',
]

// Las constantes de `define` en vite.config.js. Si se agrega una, va acá.
export const CONSTANTES_DE_BUILD = ['__BUILD_ID__']

const GLOBALES = new Set([
  ...require('@babel/helper-globals/data/builtin-lower.json'),
  ...require('@babel/helper-globals/data/builtin-upper.json'),
  ...require('@babel/helper-globals/data/browser-upper.json'),
  ...GLOBALES_NAVEGADOR,
  ...CONSTANTES_DE_BUILD,
  'undefined', 'NaN', 'Infinity', 'arguments', 'globalThis',
])

function archivosJs(raiz) {
  const out = []
  ;(function caminar(d) {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name)
      if (e.isDirectory()) {
        if (e.name !== 'node_modules') caminar(p)
      } else if (/\.(js|jsx|mjs)$/.test(e.name)) {
        out.push(p)
      }
    }
  })(raiz)
  return out
}

// Devuelve [{ nombre, linea }] de un pedazo de código. Exportada para que el
// test pueda plantarle un caso y comprobar que el escaneo SÍ lo ve.
export function nombresSinDefinir(codigo) {
  const ast = parse(codigo, { sourceType: 'module', plugins: ['jsx'] })
  const hallados = []
  traverse(ast, {
    ReferencedIdentifier(p) {
      const nombre = p.node.name
      // <div>, <span>: etiqueta de HTML, no una variable. <motion.div> sí
      // exige `motion` (es el objeto de un JSXMemberExpression, no pasa acá).
      if (p.isJSXIdentifier() && /^[a-z]/.test(nombre)
          && (p.parentPath.isJSXOpeningElement() || p.parentPath.isJSXClosingElement())) return
      // `typeof x` sobre algo no declarado es legal y devuelve "undefined".
      if (p.parentPath.isUnaryExpression({ operator: 'typeof' })) return
      if (p.scope.hasBinding(nombre, true)) return
      if (GLOBALES.has(nombre)) return
      hallados.push({ nombre, linea: p.node.loc.start.line })
    },
  })
  return hallados
}

export function buscarNombresSinDefinir(raiz) {
  const out = []
  for (const archivo of archivosJs(raiz)) {
    for (const h of nombresSinDefinir(fs.readFileSync(archivo, 'utf8'))) {
      out.push({ archivo: path.relative(raiz, archivo), ...h })
    }
  }
  return out
}

// Modo suelto: `node scripts/scan-nombres-sin-definir.mjs [ruta]`
if (import.meta.url === `file://${process.argv[1]}`) {
  const raiz = path.resolve(process.argv[2] || 'src')
  const hallados = buscarNombresSinDefinir(raiz)
  for (const h of hallados) console.log(`🔴 ${h.archivo}:${h.linea}  "${h.nombre}" no está definido`)
  console.log(`nombres sin definir: ${hallados.length}`)
  process.exit(hallados.length ? 1 : 0)
}
