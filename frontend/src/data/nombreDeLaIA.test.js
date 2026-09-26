import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

// La IA de Rendi se llama Rendi AI. "Coach IA" es el nombre viejo y no vuelve.
// ════════════════════════════════════════════════════════════════════════════
// El nombre cambió en el catálogo, la FAQ y la guía, y el viejo siguió vivo en
// unos 60 textos más: el <title> de la home, Términos (donde era una
// DEFINICIÓN), Privacidad, las landings de SEO, el blog y la app. Un nombre
// viejo no rompe nada ni tira ningún error: sale en Google y calla. Los textos
// que arma el servidor los vigila `backend/tests/test_nombre_de_la_ia.py`.
//
// Recorre el ÁRBOL, no una lista: una página o un componente nuevo entra solo.
// Los comentarios SÍ pueden nombrarlo (cuentan la historia); lo que se muestra,
// no. Los tests no se leen: citan el texto viejo a propósito.

const FRONTEND = fileURLToPath(new URL('../..', import.meta.url))
const SRC = join(FRONTEND, 'src')

function archivosDe(dir, extensiones) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const ruta = join(dir, e.name)
    if (e.isDirectory()) return archivosDe(ruta, extensiones)
    return extensiones.test(e.name) && !/\.test\.[jt]sx?$/.test(e.name) ? [ruta] : []
  })
}

// Lo que se publica tal cual, sin pasar por React: el HTML que leen Google y
// WhatsApp antes de que arranque la app, y TODO `public/`, que va entero a
// rendi.finance aunque nada lo enlace. Ahí estaba el manual de marca con
// "COACH IA" al pie de la historia de ejemplo, y ningún test lo leía.
const ESTATICOS = [
  join(FRONTEND, 'index.html'),
  ...archivosDe(join(FRONTEND, 'public'), /\.(html|webmanifest|json|txt|xml|md|css|js)$/),
]
const TODOS = [...ESTATICOS, ...archivosDe(SRC, /\.(jsx?|mjs)$/)]

// Sin comentarios, pero con los atributos: un aria-label lo lee el lector de
// pantalla y un <meta content> lo lee Google. Los comentarios se reemplazan por
// sus saltos de línea para que el número de línea del aviso sea el real.
const vaciar = (m) => m.replace(/[^\n]/g, '')
function sinComentarios(ruta, src) {
  if (/\.(html|xml)$/.test(ruta)) return src.replace(/<!--[\s\S]*?-->/g, vaciar)
  if (!/\.(jsx?|mjs|css)$/.test(ruta)) return src  // manifiesto, .md, .txt: se lee todo
  return src
    .replace(/\/\*[\s\S]*?\*\//g, vaciar)         // /* … */ y {/* … */}
    .replace(/(^|[^:\\])\/\/.*$/gm, '$1')         // // … (no el de https://)
}

const NOMBRE_VIEJO = [
  /coach\s+(de\s+)?ia\b/gi,     // "Coach IA", "coach IA", "Coach de IA"
  /\b(el|al|del)\s+coach\b/gi,  // "El Coach lee tu test", "Memoria del Coach"
]

function hallazgos(ruta, patrones) {
  const texto = sinComentarios(ruta, readFileSync(ruta, 'utf8'))
  return patrones.flatMap((p) => [...texto.matchAll(p)].map((m) => {
    const linea = texto.slice(0, m.index).split('\n').length
    return `${relative(FRONTEND, ruta)}:${linea} «${m[0].replace(/\s+/g, ' ')}»`
  }))
}

describe('el nombre viejo de la IA no vuelve', () => {
  it('el recorrido lee la app entera, no sólo lo que alguien listó', () => {
    // Contra el falso verde: si el recorrido se rompe y no lee nada, el test
    // de abajo pasa sin mirar un solo archivo.
    const leidos = TODOS.map((r) => relative(FRONTEND, r))
    expect(leidos.length).toBeGreaterThan(150)
    for (const r of ['index.html', 'public/site.webmanifest', 'public/brand-kit/manual.html',
      'src/pages/Landing.jsx', 'src/pages/Terminos.jsx', 'src/pages/Privacidad.jsx',
      'src/pages/More.jsx']) {
      expect(leidos, r).toContain(r)
    }
  })

  it('el patrón caza el texto y deja pasar los comentarios', () => {
    // Que el guard mire lo que tiene que mirar: el mismo nombre, adentro y
    // afuera de un comentario, en las tres formas de comentar que hay.
    const jsx = "// el Coach IA\n{/* el Coach IA */}\n<p>Preguntale al Coach IA</p>\nx // Coach IA"
    const vistos = NOMBRE_VIEJO.flatMap((p) => [...sinComentarios('a.jsx', jsx).matchAll(p)])
    expect(vistos.map((m) => m[0])).toEqual(['Coach IA', 'al Coach'])
    const html = '<!-- Coach IA --><title>Rendi, con Coach IA</title>'
    expect(sinComentarios('index.html', html)).toBe('<title>Rendi, con Coach IA</title>')
    // Y no confunde la URL de la guía, que se queda como está: cambiarla
    // rompería los links que ya indexó Google (no hay redirección).
    expect(sinComentarios('a.jsx', "to: '/guia/coach-ia'")).not.toMatch(NOMBRE_VIEJO[0])
  })

  it('ningún texto de la app, la home, el blog, la guía ni los legales dice "Coach IA"', () => {
    const encontrados = TODOS.flatMap((r) => hallazgos(r, NOMBRE_VIEJO))
    expect(encontrados, 'la IA se llama Rendi AI').toEqual([])
  })
})

// ── Las páginas públicas no nombran el modelo ───────────────────────────────
// La FAQ, la guía y el HTML de la home decían "Claude Haiku 4.5" cuando el chat
// ya usaba Sonnet 5 (desde el 2026-09-12, `chat_model` en main.py). Una versión
// escrita a mano en una página pública es un dato que se vence solo. Nombrar al
// proveedor (Claude, de Anthropic) sí: eso lo exigen Términos y Privacidad.
//
// Por carpeta y no por archivo: un artículo o una landing nueva entra sola.
const PUBLICA = new RegExp('^(index\\.html|public/|src/(' + [
  'pages/(Landing|Guia|Planes|Terminos|Privacidad|Reembolso)\\.jsx',
  'pages/(keywords|blog|guia)/',
  'components/(landing|blog|guide)/',
].join('|') + '))')

describe('las páginas públicas no atan el texto a una versión del modelo', () => {
  const publicas = TODOS.filter((r) => PUBLICA.test(relative(FRONTEND, r)))

  it('el filtro encuentra las páginas públicas', () => {
    const rel = publicas.map((r) => relative(FRONTEND, r))
    expect(rel.length).toBeGreaterThan(20)
    expect(rel).toContain('src/pages/guia/CoachIA.jsx')
    expect(rel).toContain('src/components/landing/FAQ.jsx')
  })

  it('ninguna dice Haiku, Sonnet ni Opus', () => {
    const encontrados = publicas.flatMap((r) => hallazgos(r, [/\b(haiku|sonnet|opus)\b/gi]))
    expect(encontrados).toEqual([])
  })
})
