// Escribe las páginas públicas YA ARMADAS en dist/, después de `vite build`.
//
// Por qué: Rendi es una app que se arma en el navegador. Un robot que no corre
// JavaScript —los de Grok, ChatGPT, Perplexity, Claude, y Google en su primera
// pasada— recibía en las 23 páginas públicas el MISMO index.html con ~1.000
// letras: ni Sharpe, ni alfa, ni S&P 500. Medido el 2026-10-18 bajando la
// página como GPTBot. Por eso una IA decía que Rendi "no destaca" métricas que
// sí tiene.
//
// Qué hace, por cada ruta de src/paginasPublicas.js:
//   1. Arma la página con el mismo componente que ve la gente
//      (src/prerender/entry-server.jsx, compilado a dist-ssr/).
//   2. Mete ese HTML adentro de <div id="root">, con el título, la descripción
//      y el canonical de ESA página (antes todas decían los de la portada).
//   3. Lo guarda en dist/<ruta>/index.html ('/' pisa dist/index.html).
// Y guarda el index.html vacío original como dist/app.html: es el que sirve
// Vercel para las rutas de la app (vercel.json), que no tienen nada que leer.
//
// Para la persona no cambia nada: React monta encima y reemplaza lo escrito.
// Con sesión iniciada, lo escrito ni se muestra (ver `con-sesion` en index.html).
//
// Si algo falla, el build falla y Vercel NO publica: queda la versión anterior.
// La hora de Argentina, no la de la máquina que arma (Vercel corre en UTC):
// la maqueta de la portada escribe la fecha de hoy, y de 21 a 24 h decía mañana.
process.env.TZ = 'America/Argentina/Buenos_Aires'

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(raiz, 'dist')
const BASE = 'https://rendi.finance'

// Lo que ve un visitante nuevo: sin nada guardado en el navegador. Algunas
// partes leen localStorage al arrancar; acá no existe y se caían.
function almacenVacio() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)) },
    removeItem: (k) => { m.delete(k) },
    clear: () => m.clear(),
    key: (i) => [...m.keys()][i] ?? null,
    get length() { return m.size },
  }
}
globalThis.localStorage = almacenVacio()
globalThis.sessionStorage = almacenVacio()

const { render, RUTAS } = await import(path.join(raiz, 'dist-ssr', 'entry-server.js'))

const BLOQUE_HOWTO = /\s*<script type="application\/ld\+json">\s*\{\s*"@context": "https:\/\/schema\.org",\s*"@type": "HowTo"[\s\S]*?<\/script>/

const escapar = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// Saca del <head> base las etiquetas que la página trae propias (título,
// descripción, og:*, twitter:*), para que no queden dos con distinto valor.
function armarHead(base, helmet, ruta) {
  let head = base
  const titulo = helmet.title.toString()
  const tieneTitulo = !/<title[^>]*><\/title>/.test(titulo)
  if (tieneTitulo) head = head.replace(/<title>[\s\S]*?<\/title>/, '')
  const metas = helmet.meta.toString()
  for (const [, attr, clave] of metas.matchAll(/(name|property)="([^"]+)"/g)) {
    head = head.replace(new RegExp(`\\s*<meta ${attr}="${escapar(clave)}"[^>]*>`, 'g'), '')
  }
  // El hreflang tiene que apuntar a ESTA página, no a la portada.
  const url = ruta === '/' ? `${BASE}/` : `${BASE}${ruta}`
  head = head.replace(/(<link rel="alternate" hreflang="[^"]+" href=")[^"]*(")/g, (_, a, b) => `${a}${url}${b}`)
  // El "Cómo funciona" (HowTo) describe la portada: Google pide que los datos
  // estructurados hablen de la página donde están, y repetido en /terminos o en
  // un artículo del blog no es cierto.
  if (ruta !== '/') head = head.replace(BLOQUE_HOWTO, '')
  // `helmet.script` trae los datos estructurados que arma cada página (las
  // preguntas frecuentes de la portada, el Article de cada nota del blog). Sin
  // esto quedaban afuera de lo escrito y el robot no los veía.
  const propias = [tieneTitulo ? titulo : '', metas, helmet.link.toString(), helmet.script.toString()]
    .filter(Boolean).join('\n    ')
  return head.replace('</head>', () => `    ${propias}\n  </head>`)
}

// El cartel "Rendi necesita JavaScript" con el resumen de la portada: en una
// página ya escrita sobra (y en /terminos diría lo de la portada). Queda sólo
// en app.html.
const CARTEL_SIN_JS = /\s*<noscript>\s*<div style="max-width:720px[\s\S]*?<\/noscript>/

const base = fs.readFileSync(path.join(dist, 'index.html'), 'utf8')
if (!base.includes('<div id="root"></div>')) {
  throw new Error('dist/index.html no tiene <div id="root"></div>: ¿ya estaba prerenderizado?')
}
if (!CARTEL_SIN_JS.test(base)) throw new Error('No encontré el cartel <noscript> de index.html')
if (!BLOQUE_HOWTO.test(base)) throw new Error('No encontré el HowTo de index.html')
fs.writeFileSync(path.join(dist, 'app.html'), base)

let total = 0
for (const ruta of RUTAS) {
  const { html, helmet } = await render(ruta)
  if (html.length < 2000) throw new Error(`${ruta} salió casi vacía (${html.length} letras)`)
  let pagina = armarHead(base, helmet, ruta)
    .replace(CARTEL_SIN_JS, '')
    // Con función y no con texto: en el texto de reemplazo `$&`, `$'` y `$$`
    // son especiales, y las páginas están llenas de "$" por los precios.
    .replace('<div id="root"></div>', () => `<div id="root"><div data-prerender="">${html}</div></div>`)
  const destino = ruta === '/'
    ? path.join(dist, 'index.html')
    : path.join(dist, ...ruta.split('/').filter(Boolean), 'index.html')
  fs.mkdirSync(path.dirname(destino), { recursive: true })
  fs.writeFileSync(destino, pagina)
  total += 1
}
console.log(`prerender: ${total} páginas públicas escritas + app.html`)
