// Lo que escribe el prerender en dist/, separado del script que lo corre.
//
// Por qué un módulo aparte: `scripts/prerender.mjs` arranca importando el
// paquete ya compilado (dist-ssr/) y escribiendo archivos, así que una prueba no
// lo puede cargar. Acá viven las mismas funciones que usa al publicar, y la
// prueba (src/__guards__/lo-que-lee-google.test.js) corre `escribirSitio` con
// las páginas de verdad sobre una carpeta temporal: el mismo camino que
// producción, no una copia del cálculo.
//
// Qué escribe, en este orden:
//   1. dist/app.html: el index.html vacío con «no me guardes» (ver paraLaApp).
//   2. dist/<ruta>/index.html: cada página pública ya armada ('/' pisa
//      dist/index.html, la portada).
//   3. dist/rss.xml: las notas del blog, para lectores de RSS y buscadores.

import fs from 'node:fs'
import path from 'node:path'
import { RSS_URL, RSS_TITULO } from '../src/data/rss.js'

export const BASE = 'https://rendi.finance'

const escaparRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// El cartel "Rendi necesita JavaScript" con el resumen de la portada: en una
// página ya escrita sobra (y en /terminos diría lo de la portada). Queda sólo
// en app.html.
export const CARTEL_SIN_JS = /\s*<noscript>\s*<div style="max-width:720px[\s\S]*?<\/noscript>/

// ─── app.html: «no me guardes» ───────────────────────────────────────────────
// Vercel sirve app.html para TODA dirección que no sea una página pública ni un
// archivo: las pantallas de la app (/dashboard, /imports…), los informes
// compartidos (/i/<link>) y cualquier dirección que no existe (/esto-no-existe).
// Todas respondían 200 con el título y la descripción de la PORTADA y con
// `robots: index, follow`, así que Google guardaba copias de la portada en
// direcciones que no son la portada (en el buscador seguía /imports con el
// título viejo «Coach IA»).
//
// Acá app.html pasa a decir «noindex, follow»: no guardes esta dirección, pero
// seguí sus links. El título queda neutro («Rendi»), porque no es la portada.
// Las 26 páginas públicas NO pasan por acá: se arman desde el index.html
// original, que sigue diciendo «index, follow».
//
// Efecto visible: con sesión iniciada, la pestaña del navegador dice «Rendi»
// en las pantallas de la app (antes, el título largo de la portada).
export const ROBOTS_DE_LA_APP = 'noindex, follow'
export const TITULO_DE_LA_APP = 'Rendi'

const ETIQUETA_ROBOTS = /<meta name="robots" content="[^"]*"\s*\/?>/g
const ETIQUETA_TITULO = /<title>[\s\S]*?<\/title>/g

export function paraLaApp(base) {
  const robots = base.match(ETIQUETA_ROBOTS) || []
  const titulos = base.match(ETIQUETA_TITULO) || []
  // Si index.html cambia de forma y no encontramos UNA de cada una, mejor que
  // el build falle a que app.html salga sin su «no me guardes» sin avisar.
  if (robots.length !== 1) throw new Error(`index.html tiene ${robots.length} etiquetas robots (esperaba 1)`)
  if (titulos.length !== 1) throw new Error(`index.html tiene ${titulos.length} <title> (esperaba 1)`)
  return base
    .replace(ETIQUETA_ROBOTS, () => `<meta name="robots" content="${ROBOTS_DE_LA_APP}" />`)
    .replace(ETIQUETA_TITULO, () => `<title>${TITULO_DE_LA_APP}</title>`)
}

// ─── Cabeza de cada página pública ───────────────────────────────────────────
// Saca del <head> base las etiquetas que la página trae propias (título,
// descripción, og:*, twitter:*), para que no queden dos con distinto valor.
export function armarHead(base, helmet, ruta) {
  let head = base
  const titulo = helmet.title.toString()
  const tieneTitulo = !/<title[^>]*><\/title>/.test(titulo)
  if (tieneTitulo) head = head.replace(/<title>[\s\S]*?<\/title>/, '')
  const metas = helmet.meta.toString()
  for (const [, attr, clave] of metas.matchAll(/(name|property)="([^"]+)"/g)) {
    head = head.replace(new RegExp(`\\s*<meta ${attr}="${escaparRegex(clave)}"[^>]*>`, 'g'), '')
  }
  // El hreflang tiene que apuntar a ESTA página, no a la portada.
  const url = ruta === '/' ? `${BASE}/` : `${BASE}${ruta}`
  head = head.replace(/(<link rel="alternate" hreflang="[^"]+" href=")[^"]*(")/g, (_, a, b) => `${a}${url}${b}`)
  // `helmet.script` trae los datos estructurados que arma cada página (las
  // preguntas frecuentes de la portada, el Article de cada nota del blog). Sin
  // esto quedaban afuera de lo escrito y el robot no los veía. `helmet.link`
  // trae el canonical y, en el blog, el link al RSS.
  const propias = [tieneTitulo ? titulo : '', metas, helmet.link.toString(), helmet.script.toString()]
    .filter(Boolean).join('\n    ')
  return head.replace('</head>', () => `    ${propias}\n  </head>`)
}

// ─── RSS del blog ────────────────────────────────────────────────────────────
// Hasta el 16/11/2026, https://rendi.finance/rss.xml devolvía la portada (el
// comodín de vercel.json manda a app.html todo lo que no es un archivo). Ahora
// el prerender escribe dist/rss.xml, y Vercel sirve un archivo que existe antes
// que cualquier rewrite (por eso ya andaban robots.txt y sitemap.xml).
//
// Sale de src/data/blogPosts.js, la lista única de notas que leen el índice
// y cada artículo: una nota nueva entra sola al RSS.
const DIAS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MESES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// RSS pide la fecha en el formato del correo (RFC 822), con día y mes en
// inglés. Las notas tienen sólo el día: va a la medianoche de Argentina. Se
// calcula con Date.UTC para que no dependa del huso de la máquina que publica.
export function fechaRss(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '')
  if (!m) throw new Error(`fecha de nota inválida: «${iso}» (esperaba AAAA-MM-DD)`)
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))
  if (d.getUTCMonth() !== +m[2] - 1 || d.getUTCDate() !== +m[3]) throw new Error(`fecha de nota inexistente: «${iso}»`)
  return `${DIAS[d.getUTCDay()]}, ${m[3]} ${MESES[d.getUTCMonth()]} ${m[1]} 00:00:00 -0300`
}

const escaparXml = (s) => String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&apos;')

const RSS_DESCRIPCION = 'Notas de Rendi sobre impuestos y FIFO en CEDEARs, tu ganancia real en dólares y los brokers argentinos.'

// La fecha que va en el RSS: la de la última revisión del contenido si la hay
// (`updatedAt`), si no la de publicación. El `guid` es la dirección de la nota,
// que no cambia: un lector no la muestra dos veces cuando se actualiza.
export function armarRss(posts) {
  if (!posts.length) throw new Error('blogPosts.js no tiene notas: el RSS saldría vacío')
  const items = posts
    .map((p) => {
      for (const campo of ['slug', 'title', 'description', 'publishedAt']) {
        if (!p[campo]) throw new Error(`la nota «${p.slug}» no tiene ${campo}`)
      }
      return { ...p, fecha: p.updatedAt || p.publishedAt, link: `${BASE}/blog/${p.slug}` }
    })
    // La más nueva primero; a igual fecha, el orden de blogPosts.js.
    .sort((a, b) => (a.fecha < b.fecha ? 1 : a.fecha > b.fecha ? -1 : 0))
  const item = (p) => [
    '    <item>',
    `      <title>${escaparXml(p.title)}</title>`,
    `      <link>${escaparXml(p.link)}</link>`,
    `      <description>${escaparXml(p.description)}</description>`,
    p.category ? `      <category>${escaparXml(p.category)}</category>` : null,
    `      <pubDate>${fechaRss(p.fecha)}</pubDate>`,
    `      <guid isPermaLink="true">${escaparXml(p.link)}</guid>`,
    '    </item>',
  ].filter(Boolean).join('\n')
  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
    '  <channel>',
    `    <title>${escaparXml(RSS_TITULO)}</title>`,
    `    <link>${BASE}/blog</link>`,
    `    <description>${escaparXml(RSS_DESCRIPCION)}</description>`,
    '    <language>es-AR</language>',
    `    <atom:link href="${RSS_URL}" rel="self" type="application/rss+xml" />`,
    // La fecha de la nota más nueva, no la hora del build: si nada cambió, el
    // archivo sale idéntico en cada publicación.
    `    <lastBuildDate>${fechaRss(items[0].fecha)}</lastBuildDate>`,
    ...items.map(item),
    '  </channel>',
    '</rss>',
    '',
  ].join('\n')
}

// ─── Todo junto ──────────────────────────────────────────────────────────────
// `base`: el index.html que armó `vite build` (vacío, con <div id="root"></div>).
// `render`, `rutas`: los de src/prerender/entry-server.jsx.
// `posts`: los de src/data/blogPosts.js.
// Si algo falla, tira error: el build falla y Vercel NO publica.
export async function escribirSitio({ dist, base, render, rutas, posts }) {
  if (!base.includes('<div id="root"></div>')) {
    throw new Error('dist/index.html no tiene <div id="root"></div>: ¿ya estaba prerenderizado?')
  }
  if (!CARTEL_SIN_JS.test(base)) throw new Error('No encontré el cartel <noscript> de index.html')

  fs.writeFileSync(path.join(dist, 'app.html'), paraLaApp(base))

  let paginas = 0
  for (const ruta of rutas) {
    const { html, helmet } = await render(ruta)
    if (html.length < 2000) throw new Error(`${ruta} salió casi vacía (${html.length} letras)`)
    const pagina = armarHead(base, helmet, ruta)
      .replace(CARTEL_SIN_JS, '')
      // Con función y no con texto: en el texto de reemplazo `$&`, `$'` y `$$`
      // son especiales, y las páginas están llenas de "$" por los precios.
      .replace('<div id="root"></div>', () => `<div id="root"><div data-prerender="">${html}</div></div>`)
    const destino = ruta === '/'
      ? path.join(dist, 'index.html')
      : path.join(dist, ...ruta.split('/').filter(Boolean), 'index.html')
    fs.mkdirSync(path.dirname(destino), { recursive: true })
    fs.writeFileSync(destino, pagina)
    paginas += 1
  }

  fs.writeFileSync(path.join(dist, 'rss.xml'), armarRss(posts))
  return { paginas }
}
