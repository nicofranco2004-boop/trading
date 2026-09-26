// El texto que ve la gente, leído de los ARCHIVOS.
//
// POR QUÉ EXISTE
// ──────────────
// Un texto viejo no rompe nada ni tira ningún error: sale en Google y calla. Por
// eso hay guards que leen los archivos y buscan frases que no pueden volver: el
// nombre viejo de la IA (`src/__guards__/nombre-de-la-ia.test.js`) y el plan
// Free ofrecido a quien ya no lo tiene (`src/data/prueba.test.js`). Los dos
// necesitan lo mismo —qué archivos se publican, cuáles son páginas públicas y
// qué parte de cada archivo es texto y no comentario— y estaba escrito dos
// veces, con dos listas de páginas públicas distintas (17 y 28 archivos).
//
// POR QUÉ CON PARSER Y NO CON REGEX
// ─────────────────────────────────
// La primera versión sacaba los comentarios con una regex (`/* … */`). En
// WallbitConnect.jsx un comentario de una línea menciona la ruta
// `/api/wallbit/*.`: la regex tomó ese `/*` como apertura y borró hasta el
// próximo `*/`, 110 renglones más abajo — 94 renglones de texto real que el
// guard no leía. Qué es comentario lo decide @babel/parser, el mismo que usa
// scan-try-catch-scope.mjs (declarado en package.json).
//
// Vive fuera de `src/` a propósito, igual que design-patterns.mjs: si estuviera
// adentro, el recorrido se leería a sí mismo.
import { parse } from '@babel/parser'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const DE_LA_APP = /\.(jsx?|mjs|tsx?)$/
// `public/` va ENTERO a rendi.finance aunque nada lo enlace: ahí estaba el
// manual de marca con "COACH IA" al pie de la historia de ejemplo.
const PUBLICADO = /\.(html|webmanifest|json|txt|xml|md|css|js|svg)$/

function caminar(dir, extensiones) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const ruta = path.join(dir, e.name)
    if (e.isDirectory()) return e.name === 'node_modules' ? [] : caminar(ruta, extensiones)
    return extensiones.test(e.name) && !/\.test\.[jt]sx?$/.test(e.name) ? [ruta] : []
  })
}

/** Todo lo que puede terminar en una pantalla: `index.html` (lo leen Google y
 *  WhatsApp antes de que arranque React), todo `public/` y el código de `src/`
 *  sin los tests (citan los textos viejos a propósito). Rutas absolutas. */
export function archivosConTexto() {
  return [
    path.join(FRONTEND, 'index.html'),
    ...caminar(path.join(FRONTEND, 'public'), PUBLICADO),
    ...caminar(path.join(FRONTEND, 'src'), DE_LA_APP),
  ]
}

/** La ruta desde `frontend/`, con barras: "src/pages/Landing.jsx". */
export const relativa = (ruta) => path.relative(FRONTEND, ruta).split(path.sep).join('/')

// Las páginas que lee alguien sin cuenta (y Google). Por carpeta y no por
// archivo: un artículo, una landing o una sección nueva de la guía entra sola.
// `data/` va porque el catálogo y las frases de la prueba se leen en la home y
// en /planes.
const PUBLICA = new RegExp('^(index\\.html|public/|src/(' + [
  'data/',
  'pages/(Landing|Guia|Blog|Planes|Terminos|Privacidad|Reembolso)\\.jsx',
  'pages/(keywords|blog|guia)/',
  'components/(landing|blog|guide)/',
].join('|') + '))')

export const esPublica = (ruta) => PUBLICA.test(relativa(ruta))

const vaciar = (s) => s.replace(/[^\n]/g, '')

function sinComentariosJs(src, ruta) {
  const { comments } = parse(src, {
    sourceType: 'unambiguous',
    plugins: /\.tsx?$/.test(ruta) ? ['jsx', 'typescript'] : ['jsx'],
    errorRecovery: true,
  })
  let limpio = ''
  let desde = 0
  for (const c of comments) {
    limpio += src.slice(desde, c.start) + vaciar(src.slice(c.start, c.end))
    desde = c.end
  }
  return limpio + src.slice(desde)
}

/** El texto de un archivo sin sus comentarios, que SÍ pueden nombrar lo viejo:
 *  cuentan la historia. Los atributos quedan (un aria-label lo lee el lector de
 *  pantalla, un <meta content> lo lee Google). Cada comentario se cambia por sus
 *  saltos de línea, así el renglón que dice un aviso es el real. */
export function sinComentarios(ruta, src) {
  if (/\.(html|xml|svg)$/.test(ruta)) {
    return src
      .replace(/<!--[\s\S]*?-->/g, vaciar)
      // El JS de un <script> común también tiene comentarios; el JSON-LD no.
      .replace(/(<script\b(?![^>]*ld\+json)[^>]*>)([\s\S]*?)(<\/script>)/gi,
        (_, abre, js, cierra) => abre + sinComentariosJs(js, 'script.js') + cierra)
  }
  if (/\.css$/.test(ruta)) return src.replace(/\/\*[\s\S]*?\*\//g, vaciar)
  if (DE_LA_APP.test(ruta) || /\.js$/.test(ruta)) return sinComentariosJs(src, ruta)
  return src  // manifiesto, .json, .md, .txt: todo lo que tienen se lee
}

// Entre dos palabras de una frase puede haber más que un espacio y en pantalla
// se lee igual: una etiqueta (`Coach <strong>IA</strong>`), el `{' '}` que deja
// el formateador al cortar el renglón, o un espacio duro (`&nbsp;`, ` `).
// El guard del plan Free ya lo había aprendido ("vuelve a <strong>Free</strong>").
export const ENTRE = String.raw`(?:\s|&nbsp;|&#160;|&#xa0;|\\u00a0|\\xa0|\{\s*(?:'\s*'|"\s*"|\x60\s*\x60)\s*\}|<[^<>]*>)+`

/** Cada aparición de cada patrón (con flag g) en el texto sin comentarios de
 *  `ruta`, como "src/pages/Landing.jsx:140 «Coach IA»". */
export function hallazgos(ruta, patrones) {
  const texto = sinComentarios(ruta, fs.readFileSync(ruta, 'utf8'))
  return patrones.flatMap((p) => [...texto.matchAll(p)].map((m) => {
    const renglon = texto.slice(0, m.index).split('\n').length
    return `${relativa(ruta)}:${renglon} «${m[0].replace(/\s+/g, ' ')}»`
  }))
}
