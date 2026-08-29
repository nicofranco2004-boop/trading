// design-patterns.mjs — el walker y los patrones del guard del sistema visual.
// ═══════════════════════════════════════════════════════════════════════════
// Fuente ÚNICA compartida por dos consumidores:
//   • scripts/gen-design-baseline.mjs  → escribe src/__design__/design-baseline.json
//   • src/__design__/design-contract.test.js → lo verifica en cada `npm test`
// Si los patrones se copiaran en vez de importarse, el generador y el test
// medirían cosas distintas y el baseline sería una mentira estable.
//
// POR QUÉ ESTE ARCHIVO VIVE EN scripts/ Y NO EN src/:
// el walker recorre src/**/*.{js,jsx}. Un módulo con los literales 'font-mono',
// 'rounded-md' y 'uppercase' adentro de src/ se contaría A SÍ MISMO. Los tests
// se salvan por el filtro *.test.js; este archivo no es un test, así que la
// única defensa robusta es estar fuera del árbol escaneado.
//
// Ver el contrato completo en frontend/CLAUDE.md.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Raíz resuelta contra import.meta.url, NO contra process.cwd(): `npm test`
// corre desde frontend/, pero alguien puede invocar vitest desde la raíz del
// repo o desde otro worktree y el guard tiene que medir siempre lo mismo.
export const FRONTEND_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const SRC = path.join(FRONTEND_ROOT, 'src')

// Se corta por NOMBRE DE DIRECTORIO antes de descender, no filtrando al final.
// `dist/` hoy no existe en el repo, pero aparece con el primer `npm run build`
// y contiene todas las clases del proyecto concatenadas: sin este corte el
// guard pasa en una máquina y explota en la del que buildeó.
const DIRS_CORTADOS = new Set(['node_modules', 'dist', 'build', 'coverage', '.git', '.vite'])

const esTest = (nombre) => /\.test\.(js|jsx)$/.test(nombre)
const esFuente = (nombre) => /\.(js|jsx)$/.test(nombre) && !esTest(nombre)

/** Todos los .js/.jsx de src/ que NO son tests, como rutas relativas a frontend/. */
export function listarFuentes(raiz = SRC) {
  const salida = []
  const bajar = (dir) => {
    for (const entrada of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entrada.isDirectory()) {
        if (!DIRS_CORTADOS.has(entrada.name)) bajar(path.join(dir, entrada.name))
      } else if (esFuente(entrada.name)) {
        salida.push(path.relative(FRONTEND_ROOT, path.join(dir, entrada.name)))
      }
    }
  }
  bajar(raiz)
  return salida.sort()
}

export const leer = (rel) => fs.readFileSync(path.join(FRONTEND_ROOT, rel), 'utf8')

const contar = (texto, re) => (texto.match(re) || []).length

// ── Los patrones ──────────────────────────────────────────────────────────
// Cada categoría declara:
//   regla     → a qué regla de CLAUDE.md responde
//   contar    → (texto, rutaRelativa) → número de ocurrencias en ese archivo
//   alcance   → 'fuentes' (todo src) | ruta fija | 'archivos' (cuenta archivos, no ocurrencias)
//   nota      → la trampa que este patrón esquiva, para el que lo lea dentro de un año
//
// UNIDAD: OCURRENCIAS, no líneas. AddPositionFlow.jsx:817 tiene 12 font-mono en
// una sola línea (los códigos de mes); contando líneas, migrar 11 de esos 12 no
// movería el número y el que hizo el trabajo vería el mismo total que antes.

// `\b` inicial a propósito: captura los prefijos de variante (sm:rounded-xl,
// hover:rounded-md) porque ':' no es carácter de palabra. Un regex que exija
// inicio-de-token o espacio antes NO los ve. El grupo de lado cubre
// rounded-t-2xl / rounded-br-md / rounded-bl-sm, que son 13 usos reales.
const LADO = '(?:-(?:t|r|b|l|tl|tr|br|bl))?'

export const CATEGORIAS = {
  mono_clase: {
    regla: 'R1/R3',
    alcance: 'fuentes',
    nota:
      'JAMÁS /mono/ ni /\\bmono\\b/: el primero suma la clase renombrada en Fase 0 (que ya ' +
      'era sans) y el segundo suma la prop `mono` de DataRow — mediría 428 donde hay 341.',
    contar: (t) => contar(t, /\bfont-mono\b/g),
  },

  mono_inline: {
    regla: 'R4',
    alcance: 'fuentes',
    nota:
      'El canal ciego: 22 usos de JetBrains Mono que `grep font-mono` no ve (SVG por atributo ' +
      'y canvas por ctx.font). El predicado es "asignación de familia cuyo VALOR dice mono", ' +
      'nunca `fontFamily` pelado (50 hits, 33 de ellos sans legítimos en logos SVG) ni ' +
      '`monospace` suelto (aparece dentro de stacks de fallback legítimos).',
    contar: (t) =>
      contar(t, /fontFamily\s*=\s*\{[^}]*mono[^}]*\}/gi) +
      contar(t, /fontFamily\s*=\s*"[^"]*mono[^"]*"/gi) +
      contar(t, /fontFamily\s*:\s*['"`][^'"`]*mono[^'"`]*['"`]/gi) +
      contar(t, /ctx\.font\s*=\s*`[^`]*mono[^`]*`/gi),
  },

  mono_uppercase: {
    regla: 'R2',
    alcance: 'fuentes',
    nota:
      'Subconjunto de mono_clase, congelado aparte porque es la familia que R2 prohíbe de ' +
      'forma explícita. Se mide POR LÍNEA (es una coocurrencia, no una ocurrencia). ' +
      'La MAYÚSCULA sola no está prohibida — el Plan Asesor la usa en 6 lugares.',
    contar: (t) =>
      t.split('\n').filter((l) => /\bfont-mono\b/.test(l) && /\buppercase\b/.test(l)).length,
  },

  clase_renombrada: {
    regla: 'R7',
    alcance: 'fuentes',
    nota:
      'La clase de label que se renombró en Fase 0 porque su nombre prometía mono y emitía ' +
      'sans. Congelada en 0: el guard existe para que no vuelva. El nombre viejo NO se ' +
      'escribe en ningún archivo escaneado — vive sólo en frontend/CLAUDE.md.',
    contar: (t) => contar(t, /\blabel-mono\b/g),
  },

  rounded_arbitrario: {
    regla: 'R5',
    alcance: 'fuentes',
    nota:
      'Los 9 son rounded-[2px] en swatches de leyenda de 2×3px, 3 de ellos en la página de ' +
      'referencia del asesor. Por eso Fase 0 declaró el token `xs: 2px` en vez de prohibirlos ' +
      'a secas: sin token, el mínimo de la escala (4px) los volvía círculos.',
    contar: (t) => contar(t, new RegExp(`\\brounded${LADO}-\\[[^\\]]+\\]`, 'g')),
  },

  rounded_md: {
    regla: 'R5',
    alcance: 'fuentes',
    nota:
      'Deuda PIXEL-INVISIBLE: md es 6px, idéntico al DEFAULT. Migrar md→rounded no cambia ' +
      'un pixel pero BAJA este número y hace fallar el test. Es intencional: bajar exige ' +
      'actualizar el JSON en el mismo commit, para que la mejora quede registrada y no se ' +
      'gaste como presupuesto silencioso para violaciones nuevas.',
    contar: (t) => contar(t, new RegExp(`\\brounded${LADO}-md\\b`, 'g')),
  },

  rounded_2xl_3xl: {
    regla: 'R5',
    alcance: 'fuentes',
    nota:
      'No son violación hoy: 8 de los 18 `2xl` son rounded-t-2xl, el idioma del bottom-sheet ' +
      'mobile. Se congelan para que las curvas grandes dejen de crecer.',
    contar: (t) => contar(t, new RegExp(`\\brounded${LADO}-[23]xl\\b`, 'g')),
  },

  upper_inline: {
    regla: 'R2',
    alcance: 'fuentes',
    nota:
      'Los 10 viven en pages/ReportPublic.jsx, el informe imprimible que ven los CLIENTES de ' +
      'los asesores; usa estilos inline a propósito porque se renderiza fuera del contexto ' +
      'Tailwind. Congelado para que no se propague — explícitamente NO en el camino de migración.',
    contar: (t) => contar(t, /textTransform\s*:\s*['"]uppercase['"]/g),
  },

  fork_viewport: {
    regla: 'R6',
    alcance: 'fuentes',
    nota:
      'Los forks que existen (Home→HomeMobile, Positions→PositionsMobile) son textualmente ' +
      'idénticos. Congelado en 2 exacto: Operations era el tercero y murió en la Fase 3 — un ' +
      'dueño de datos y dos ramas sobre components/operations/.',
    contar: (t) => contar(t, /if\s*\(\s*isMobile\s*\)\s*return\s*</g),
  },

  fork_ternario: {
    regla: 'R6',
    alcance: 'fuentes',
    nota:
      'La variante `isMobile ? <A/> : <B/>` no existe en ningún .jsx. Congelada en 0 para que ' +
      'el fork no se cuele reescrito de otra forma. El patrón exige `<` pegado al `?` a ' +
      'propósito: los ternarios de VALOR sobre isMobile son legítimos y hay varios ' +
      "(`size={isMobile ? 12 : 13}`, `isMobile ? 'day' : groupBy` en Operations.jsx). Lo que " +
      'R6 prohíbe es elegir el ÁRBOL con un ternario, no elegir un número o un string.',
    contar: (t) => contar(t, /isMobile\s*\?\s*</g),
  },

  comentarios_fosiles: {
    regla: 'R7',
    alcance: 'fuentes',
    nota:
      'Frases que describían el sistema ANTERIOR en la cabecera de un átomo. Se cazan por ' +
      'frase exacta, JAMÁS por substring global: "antes uppercase mono" (DataRow.jsx:82) e ' +
      '"Instrument Serif → Geist" (index.css:16) dicen la VERDAD y documentan la migración, ' +
      'y la subcadena "mono uppercase" vive dentro de la propia clase `font-mono uppercase` ' +
      'en 70+ líneas de JSX.',
    contar: (t) => {
      const frases = [
        'Instrument Serif italic',
        'label uppercase mono pequeño arriba',
        'Labels en mono uppercase pequeño',
        'Radius default = rounded (6px, no 10px)',
        'uppercase mono pequeño arriba del título',
        'Estándar visual v2: uppercase mono',
        'Eyebrows uppercase mono',
      ]
      return frases.reduce((n, f) => n + (t.includes(f) ? 1 : 0), 0)
    },
  },
}

// ── Categorías con forma distinta ─────────────────────────────────────────
// No se miden por archivo: son propiedades del árbol o de un archivo fijo.

export const CATEGORIAS_ESPECIALES = {
  mono_css: {
    regla: 'R1/R3',
    nota:
      'Sólo los @apply de src/index.css. index.css:34 NO cuenta: es el selector `.font-mono,` ' +
      'dentro del bloque que aplica tabular-nums, no un @apply. De los 3 reales, 2 son ' +
      'legítimos (.blog-prose code y pre) y 1 es violación (.blog-prose th, mono+uppercase).',
    medir: () => contar(leer('src/index.css'), /@apply[^;]*\bfont-mono\b/g),
  },

  paginas_mobile: {
    regla: 'R6',
    nota:
      'Cuenta ARCHIVOS, no ocurrencias: caza el fork que alguien escriba SIN la línea ' +
      'canónica del despachador. Son 3: los 2 gemelos de fork + PositionDetailMobile, ' +
      'que no tiene gemelo desktop (es una ruta propia, /posiciones/:id). Un cuarto archivo ' +
      'es un fork nuevo aunque el patrón literal siga en 2.',
    medir: () => listarFuentes().filter((f) => /^src\/pages\/[^/]+Mobile\.jsx$/.test(f)).length,
  },
}

/** Mide todo el árbol. Devuelve { categoria: { rutaRelativa: n } } + especiales. */
export function medir() {
  const fuentes = listarFuentes()
  const textos = new Map(fuentes.map((f) => [f, leer(f)]))

  const porCategoria = {}
  for (const [nombre, cat] of Object.entries(CATEGORIAS)) {
    const mapa = {}
    for (const f of fuentes) {
      const n = cat.contar(textos.get(f), f)
      if (n > 0) mapa[f] = n   // ruta ausente = 0; el test itera el ÁRBOL, no el mapa
    }
    porCategoria[nombre] = mapa
  }

  const especiales = {}
  for (const [nombre, cat] of Object.entries(CATEGORIAS_ESPECIALES)) {
    especiales[nombre] = cat.medir()
  }

  return { porCategoria, especiales, totalArchivos: fuentes.length }
}

export const total = (mapa) => Object.values(mapa).reduce((s, n) => s + n, 0)
