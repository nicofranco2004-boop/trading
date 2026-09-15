// Los tokens de tema no se pueden romper en silencio.
//
// POR QUÉ ESTE TEST
// ─────────────────
// F0 (2026-09-15) sacó 33 colores de tailwind.config.js, donde eran hex fijos,
// y los pasó a variables CSS con dos juegos de valores (`:root` claro, `.dark`
// oscuro). Eso destraba el modo claro, pero abre tres formas de romper la app
// sin que nada se queje:
//
//   1. Escribir la variable en hex (`--bg-1: #0E1218`) en vez de canales
//      (`--bg-1: 14 18 24`). Tailwind compone `rgb(var(--bg-1) / 0.4)` para
//      resolver `bg-bg-1/40`; con un hex adentro eso es CSS inválido y el
//      navegador descarta la declaración entera. Son 1.937 usos con opacidad
//      que se vuelven opacos, sin error y sin warning.
//
//   2. Agregar un token al config apuntando a una variable que no existe, o
//      definirla en un solo bloque. El color sale transparente o queda con el
//      valor del otro tema.
//
//   3. Tocar un valor del bloque `.dark` creyendo que "ordena" algo. El modo
//      oscuro es lo que ven TODOS los usuarios hoy: F0 se hizo con la promesa
//      de cambio visual CERO en oscuro, y esa promesa hay que poder probarla.
//
// El punto 3 es el que justifica la tabla de abajo. Los 33 hex están copiados
// del config PRE-F0 (commit da57c55e) y son la vara: si alguien cambia un valor
// oscuro, este test dice exactamente cuál y cuánto.
//
// Los valores CLAROS no están congelados a propósito — todavía se están
// calibrando y nadie los ve. Lo que sí se verifica de ellos es que existan
// todos y que estén en formato de canales.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const CSS = readFileSync(resolve(ROOT, 'src/index.css'), 'utf8')
const CONFIG = readFileSync(resolve(ROOT, 'tailwind.config.js'), 'utf8')

// El modo oscuro de HOY, tal cual estaba antes de F0. No tocar sin un motivo
// que se pueda escribir: cada línea de acá la está viendo un usuario ahora.
const DARK_ANTES_DE_F0 = {
  'bg-0': '#07090C', 'bg-1': '#0E1218', 'bg-2': '#141923', 'bg-3': '#1B2230',
  'ink-0': '#E6EAF2', 'ink-1': '#C3CAD8', 'ink-2': '#9CA3B5', 'ink-3': '#5A6478',
  'line': '#1B2230', 'line-2': '#262E40', 'line-3': '#3A4256',
  'rendi-pos': '#21D07A', 'rendi-neg': '#FF5360',
  'rendi-warn': '#E8B14A', 'rendi-accent': '#5B9DF9',
  'data-cyan': '#46C6E0', 'data-blue': '#5B9DF9',
  'data-violet': '#8B7DFF', 'data-amber': '#E8B14A',
  'rendi-violet-hover': '#6E5FF0', 'rendi-violet-deep': '#1E1840',
  'rendi-charcoal': '#0D1015', 'rendi-slate': '#141923', 'rendi-sky': '#5B9DF9',
  'rendi-green': '#21D07A', 'rendi-green-dark': '#14A560',
  'rendi-aqua': '#46C6E0', 'rendi-pink': '#FF5360',
  'rendi-bg': '#07090C', 'rendi-card': '#0E1218', 'rendi-muted': '#9CA3B5',
  // Los dos que F0 agregó: en OSCURO valen lo mismo que su gemelo de texto.
  // La partición sólo se nota en claro. Si alguien los separa en oscuro, es
  // un cambio visual para todos los usuarios y tiene que ser deliberado.
  'rendi-pos-fill': '#21D07A', 'rendi-neg-fill': '#FF5360',
}

// La rampa de polaridad (heatmap + calendario). No pasa por Tailwind: se usa
// directo desde utils/polarityScale.js en atributos SVG y estilos inline, así
// que no tiene clase que la resuelva. Se congela igual — el modo oscuro de la
// rampa es lo que ve todo el mundo hoy.
const RAMPA_DARK = {
  'pol-up-1': '#0F5C36', 'pol-up-2': '#14A560', 'pol-up-3': '#21D07A',
  'pol-up-1-ink': '#E6EAF2',
  // ⚠️ ÚNICO valor de la rampa oscura que F2 cambió, a propósito: era #E6EAF2
  // y daba 2,65:1 sobre #14A560 — por debajo del mínimo legible de 4,5. Los
  // meses de +2 % a +5 % venían con el texto mal contrastado desde siempre.
  // Con #06160E da 5,83. Si alguien lo vuelve a #E6EAF2, el test avisa.
  'pol-up-2-ink': '#06160E',
  'pol-up-3-ink': '#06160E',
  'pol-down-1': '#8E2B33', 'pol-down-2': '#C8333E', 'pol-down-3': '#FF5360',
  'pol-down-1-ink': '#E6EAF2', 'pol-down-2-ink': '#E6EAF2', 'pol-down-3-ink': '#1F0A0C',
  'pol-flat': '#1B2230', 'pol-flat-ink': '#5A6478',
}

// Variables de gráfico que sí son colores. Como la rampa: no pasan por
// Tailwind, las lee utils/chartTheme.js.
const GRAFICO_DARK = {
  'chart-grid': '#1B2230',
  // El hover de las barras del año. Los valores oscuros son `green-200` y
  // `red-100`, que es lo que ese componente usaba antes de tener tema.
  'bar-hover-up': '#5FE19D', 'bar-hover-down': '#FFB4BA',
  'mono-violet-1': '#8B7DFF', 'mono-violet-2': '#7466E8', 'mono-violet-3': '#5F53C4',
  'mono-violet-4': '#4C429E', 'mono-violet-5': '#3D357E',
}

// La tercera familia: variables que NO son colores. Son las dos cosas del
// gráfico que cambian de forma y no de tono entre temas — cuánta transparencia
// lleva el relleno bajo la línea, y si el globo de datos tiene sombra o no.
// No se les puede aplicar la regla de "tres canales": una opacidad es un
// número y una sombra es una lista de largos y colores.
const NO_SON_COLORES = new Set(['chart-area-op', 'chart-tooltip-shadow'])

const hexACanales = (hex) => {
  const h = hex.replace('#', '')
  return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)).join(' ')
}

// Extrae las declaraciones `--token: v v v;` de un bloque delimitado por su
// selector. Se parsea el CSS crudo a propósito: es el archivo que se despacha.
function leerBloque(selector) {
  const i = CSS.indexOf(`${selector} {`)
  if (i === -1) throw new Error(`No existe el bloque \`${selector} {\` en index.css`)
  const cuerpo = CSS.slice(i, CSS.indexOf('\n  }', i))
  const vars = {}
  for (const m of cuerpo.matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) {
    vars[m[1]] = m[2].trim()
  }
  return vars
}

const LIGHT = leerBloque(':root')
const DARK = leerBloque('.dark')

// Los tokens que el config resuelve por variable. Se leen DEL CONFIG y no de
// una lista escrita a mano: un token nuevo entra al test solo.
//
// Se sacan los comentarios ANTES de buscar. El config explica el formato
// `rgb(var(--x) / <alpha-value>)` en un comentario, y sin este filtro el test
// sale a buscar una variable llamada `--x` que obviamente no existe. Es el
// mismo tropiezo que documenta design-contract.test.js: estos parsers leen
// texto crudo, y un comentario que cita la sintaxis cuenta como sintaxis.
const CONFIG_SIN_COMENTARIOS = CONFIG.split('\n')
  .filter(l => !l.trim().startsWith('//'))
  .join('\n')

const TOKENS_DEL_CONFIG = [...CONFIG_SIN_COMENTARIOS.matchAll(/rgb\(var\(--([\w-]+)\)\s*\/\s*<alpha-value>\)/g)]
  .map(m => m[1])

describe('tokens de tema — el modo oscuro no cambió', () => {
  it('cada token oscuro vale exactamente lo de antes de F0', () => {
    const cambiados = []
    for (const [token, hex] of Object.entries({ ...DARK_ANTES_DE_F0, ...RAMPA_DARK, ...GRAFICO_DARK })) {
      const esperado = hexACanales(hex)
      if (DARK[token] !== esperado) {
        cambiados.push(`--${token}: esperaba "${esperado}" (${hex}), encontré "${DARK[token]}"`)
      }
    }
    expect(cambiados, `El modo oscuro cambió de valor. Eso lo ven todos los usuarios HOY:\n  ${cambiados.join('\n  ')}`)
      .toEqual([])
  })

  it('no sobra ningún token en el bloque oscuro sin pasar por la tabla', () => {
    const sobrantes = Object.keys(DARK)
      .filter(t => !NO_SON_COLORES.has(t))
      .filter(t => !(t in DARK_ANTES_DE_F0) && !(t in RAMPA_DARK) && !(t in GRAFICO_DARK))
    expect(sobrantes, `Tokens en .dark que nadie congeló. Agregalos con su hex a DARK_ANTES_DE_F0 (tema), RAMPA_DARK (polaridad) o GRAFICO_DARK (gráficos) — o a NO_SON_COLORES si no son un color: ${sobrantes.join(', ')}`)
      .toEqual([])
  })
})

describe('tokens de tema — el formato que hace funcionar la opacidad', () => {
  // La trampa #1 de F0. `bg-bg-2/40` sólo funciona si la variable trae los
  // tres canales sueltos; con un hex adentro, el /40 se descarta en silencio.
  const CANALES = /^\d{1,3} \d{1,3} \d{1,3}$/

  for (const [nombre, bloque] of [['claro (:root)', LIGHT], ['oscuro (.dark)', DARK]]) {
    it(`todas las variables del bloque ${nombre} están en canales, no en hex`, () => {
      const malas = Object.entries(bloque)
        .filter(([k]) => !NO_SON_COLORES.has(k))
        .filter(([, v]) => !CANALES.test(v))
        .map(([k, v]) => `--${k}: "${v}"`)
      expect(malas, `Estas variables no están en formato "R G B". Con un hex adentro, los 1.937 usos con opacidad (bg-bg-2/40, border-line/50) se renderizan opacos sin ningún error:\n  ${malas.join('\n  ')}`)
        .toEqual([])
    })
  }

  it('los canales están dentro de 0-255', () => {
    const fuera = []
    for (const [nombre, bloque] of [['claro', LIGHT], ['oscuro', DARK]]) {
      for (const [k, v] of Object.entries(bloque)) {
        if (v.split(' ').some(n => +n < 0 || +n > 255)) fuera.push(`${nombre} --${k}: ${v}`)
      }
    }
    expect(fuera).toEqual([])
  })
})

describe('tokens de tema — los dos temas cubren lo mismo', () => {
  it('cada token del config tiene su variable definida en los dos bloques', () => {
    const faltan = []
    for (const t of TOKENS_DEL_CONFIG) {
      if (!(t in LIGHT)) faltan.push(`--${t} falta en :root (claro)`)
      if (!(t in DARK)) faltan.push(`--${t} falta en .dark (oscuro)`)
    }
    expect(faltan, `El config pide variables que index.css no define. El color sale transparente:\n  ${faltan.join('\n  ')}`)
      .toEqual([])
  })

  it('cada token del config se usa, y cada variable de rampa también', () => {
    // Dos familias, dos lectores. Un token de tema lo resuelve una clase de
    // Tailwind; una variable de rampa la nombra polarityScale.js. Una variable
    // que no tiene ninguno de los dos no la lee nadie: es peso muerto que el
    // próximo que mire la paleta va a creer que está en uso.
    const RAMPA = readFileSync(resolve(ROOT, 'src/utils/polarityScale.js'), 'utf8')
      + readFileSync(resolve(ROOT, 'src/utils/chartTheme.js'), 'utf8')
      + CSS  // algunas las usa el propio CSS (la sombra del globo de datos)
      + readFileSync(resolve(ROOT, 'src/components/reports/PerformanceCalendar.jsx'), 'utf8')
    const huerfanas = Object.keys(LIGHT).filter(t => {
      if (TOKENS_DEL_CONFIG.includes(t)) return false
      // polarityScale arma los nombres por pedazos (`--pol-${lado}-${step}`),
      // así que se busca el patrón, no el nombre completo.
      const patron = t.replace(/^pol-(up|down)-(\d)/, 'pol-${lado}-${step}')
      // `--chart-area-op` y la sombra se nombran adentro de un string más
      // largo (`var(--chart-area-op)`), así que alcanza con buscar el nombre.
      return !RAMPA.includes(`--${t}`) && !RAMPA.includes(`--${patron}`)
    })
    expect(huerfanas, `Variables que no lee nadie. O falta el token en tailwind.config.js, o falta usarlas en polarityScale.js / chartTheme.js, o sobran acá: ${huerfanas.join(', ')}`)
      .toEqual([])
  })

  it('el bloque claro y el oscuro declaran el mismo juego de tokens', () => {
    const soloClaro = Object.keys(LIGHT).filter(t => !(t in DARK))
    const soloOscuro = Object.keys(DARK).filter(t => !(t in LIGHT))
    expect({ soloClaro, soloOscuro }).toEqual({ soloClaro: [], soloOscuro: [] })
  })
})

describe('tokens de tema — el interruptor sigue de una pieza', () => {
  // El lock vive en dos archivos y tienen que decir lo mismo. Si se destraba
  // uno solo: o la app parpadea en cada carga, o las cuentas con preferencia
  // vieja guardada arrancan del color equivocado.
  const CONTEXT = readFileSync(resolve(ROOT, 'src/contexts/ThemeContext.jsx'), 'utf8')
  const HTML = readFileSync(resolve(ROOT, 'index.html'), 'utf8')

  const lockDe = (src) => {
    const m = src.match(/LIGHT_MODE_LOCKED\s*=\s*(true|false)/)
    return m ? m[1] : null
  }

  it('ThemeContext.jsx y index.html declaran el mismo lock', () => {
    const ctx = lockDe(CONTEXT)
    const html = lockDe(HTML)
    expect(ctx, 'ThemeContext.jsx no declara LIGHT_MODE_LOCKED').not.toBe(null)
    expect(html, 'index.html no declara LIGHT_MODE_LOCKED en el script de tema').not.toBe(null)
    expect(html, `El lock está destrabado en un solo lado (ThemeContext=${ctx}, index.html=${html}). Se cambian JUNTOS.`)
      .toBe(ctx)
  })

  it('el body toma su color de las variables, no de un hex', () => {
    const body = CSS.slice(CSS.indexOf('\nbody {'), CSS.indexOf('}', CSS.indexOf('\nbody {')))
    expect(body, 'El body tiene un color fijo: en modo claro quedaría con el fondo oscuro pegado.')
      .toMatch(/background:\s*rgb\(var\(--bg-0\)\)/)
    expect(body).toMatch(/color:\s*rgb\(var\(--ink-0\)\)/)
  })
})
