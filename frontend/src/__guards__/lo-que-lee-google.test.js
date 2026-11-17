// Lo que el prerender deja en dist/ para Google: app.html con «no me guardes»,
// las páginas públicas sin él, el RSS del blog y los datos estructurados.
//
// Auditoría SEO del 16/11/2026, verificada contra producción:
//   · Toda dirección que no es una página pública (/esto-no-existe, /dashboard,
//     /i/<link inválido>) respondía 200 con app.html, que decía el título de
//     la portada e «index, follow»: Google guardaba copias de la portada.
//   · https://rendi.finance/rss.xml devolvía la portada.
//   · index.html traía un HowTo que Google dejó de mostrar en 2023, y le
//     faltaban los perfiles de la marca y el fundador.
//
// Por qué la prueba corre `escribirSitio` y no lee los archivos sueltos: es la
// MISMA función que corre scripts/prerender.mjs al publicar, con las páginas
// armadas por prerender/entry-server.jsx, sobre una carpeta temporal. Si alguien
// cambia el camino (otra función que escribe app.html, un paso que pisa al
// anterior), la prueba lo ve igual que lo vería Google.
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  escribirSitio, paraLaApp, fechaRss, armarRss, ROBOTS_DE_LA_APP, TITULO_DE_LA_APP,
} from '../../scripts/paginasEscritas.mjs'
import { POSTS } from '../data/blogPosts'
import { RSS_URL } from '../data/rss'

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const leer = (f) => fs.readFileSync(path.join(raiz, f), 'utf8')
const INDEX = leer('index.html')

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

const robotsDe = (html) => [...html.matchAll(/<meta name="robots" content="([^"]*)"/g)].map((m) => m[1])
const cabezaDe = (html) => html.slice(0, html.indexOf('</head>'))
const datosEstructurados = (html) => [...html.matchAll(/<script[^>]*type="application\/ld\+json"[^>]*>([\s\S]*?)<\/script>/g)]
  .map((m) => m[1])
const archivoDe = (ruta) => (ruta === '/' ? 'index.html' : path.join(...ruta.split('/').filter(Boolean), 'index.html'))

let dist
let RUTAS
const escrito = {}
let resultado

beforeAll(async () => {
  globalThis.localStorage = almacenVacio()
  globalThis.sessionStorage = almacenVacio()
  const servidor = await import('../prerender/entry-server.jsx')
  RUTAS = servidor.RUTAS
  dist = fs.mkdtempSync(path.join(os.tmpdir(), 'rendi-prerender-'))
  resultado = await escribirSitio({ dist, base: INDEX, render: servidor.render, rutas: RUTAS, posts: servidor.POSTS })
  escrito.app = fs.readFileSync(path.join(dist, 'app.html'), 'utf8')
  escrito.rss = fs.readFileSync(path.join(dist, 'rss.xml'), 'utf8')
  escrito.paginas = Object.fromEntries(RUTAS.map((r) => [r, fs.readFileSync(path.join(dist, archivoDe(r)), 'utf8')]))
}, 120_000)

afterAll(() => { if (dist) fs.rmSync(dist, { recursive: true, force: true }) })

describe('app.html dice «no me guardes»; las páginas públicas no', () => {
  it('app.html: una sola etiqueta robots, «noindex, follow», y título neutro', () => {
    expect(robotsDe(escrito.app)).toEqual([ROBOTS_DE_LA_APP])
    expect(ROBOTS_DE_LA_APP).toBe('noindex, follow')
    expect(escrito.app).toContain(`<title>${TITULO_DE_LA_APP}</title>`)
    expect(escrito.app).not.toContain('Todas tus inversiones en un solo lugar | Multi-broker')
  })

  it('app.html es el index.html vacío con sólo esas dos líneas cambiadas', () => {
    const antes = INDEX.split('\n')
    const despues = escrito.app.split('\n')
    expect(despues.length).toBe(antes.length)
    const distintas = antes.filter((l, i) => l !== despues[i])
    expect(distintas.length).toBe(2)
    expect(escrito.app).toContain('<div id="root"></div>')
  })

  // La cantidad la ata la lista única (src/paginasPublicas.js), no un número
  // escrito acá: agregar una página pública bien hecha no tiene que dar rojo.
  it('cada página pública se escribe y ninguna dice noindex', () => {
    expect(resultado.paginas).toBe(RUTAS.length)
    for (const ruta of RUTAS) {
      const cabeza = cabezaDe(escrito.paginas[ruta])
      expect(robotsDe(cabeza), `${ruta}`).toEqual(['index, follow, max-image-preview:large'])
      expect(cabeza, `${ruta} dice noindex`).not.toMatch(/noindex/i)
    }
  })

  it('si index.html cambia de forma, el build falla en vez de publicar app.html sin «noindex»', () => {
    expect(() => paraLaApp(INDEX.replace(/<meta name="robots"[^>]*>/, ''))).toThrow(/robots/)
    expect(() => paraLaApp(INDEX.replace(/<title>[\s\S]*?<\/title>/, ''))).toThrow(/title/)
  })

  // Un texto, con sus puntos ciegos: ata el script de publicar a la función
  // que prueba este archivo, para que no vuelva a escribir app.html por su lado.
  it('scripts/prerender.mjs escribe con escribirSitio y no por su cuenta', () => {
    const script = leer('scripts/prerender.mjs')
    expect(script).toMatch(/import \{ escribirSitio \} from '\.\/paginasEscritas\.mjs'/)
    expect(script).toMatch(/await escribirSitio\(/)
    expect(script).not.toMatch(/writeFileSync/)
  })
})

describe('RSS del blog', () => {
  const items = () => [...escrito.rss.matchAll(/<item>([\s\S]*?)<\/item>/g)].map((m) => m[1])
  const campo = (item, nombre) => (item.match(new RegExp(`<${nombre}[^>]*>([\\s\\S]*?)</${nombre}>`)) || [])[1]

  it('una entrada por nota, con título, link, descripción, fecha y guid', () => {
    expect(escrito.rss.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"')).toBe(true)
    expect(escrito.rss).toContain('<language>es-AR</language>')
    expect(escrito.rss).toContain(`<atom:link href="${RSS_URL}" rel="self" type="application/rss+xml" />`)
    expect(items().length).toBe(POSTS.length)
    for (const post of POSTS) {
      const link = `https://rendi.finance/blog/${post.slug}`
      const item = items().find((i) => campo(i, 'link') === link)
      expect(item, `falta ${post.slug}`).toBeTruthy()
      for (const c of ['title', 'description', 'pubDate', 'guid']) expect(campo(item, c), `${post.slug}: ${c}`).toBeTruthy()
      expect(campo(item, 'guid')).toBe(link)
      // updatedAt si la nota se revisó; si no, la fecha de publicación.
      expect(campo(item, 'pubDate')).toBe(fechaRss(post.updatedAt || post.publishedAt))
      // Cada link apunta a una página que existe ya escrita.
      expect(RUTAS).toContain(`/blog/${post.slug}`)
    }
  })

  it('los «&» van escapados (el título «P&L…» rompía el XML si no)', () => {
    expect(POSTS.some((p) => p.title.includes('&'))).toBe(true)
    expect(escrito.rss).not.toMatch(/&(?!amp;|lt;|gt;|quot;|apos;)/)
    expect(escrito.rss).toContain('P&amp;L real en USD blue')
  })

  it('la fecha va en el formato que pide RSS, sin depender del huso de la máquina', () => {
    expect(fechaRss('2026-11-16')).toBe('Mon, 16 Nov 2026 00:00:00 -0300')
    expect(fechaRss('2026-05-24')).toBe('Sun, 24 May 2026 00:00:00 -0300')
    expect(() => fechaRss('2026-02-30')).toThrow()
    expect(() => fechaRss('16/11/2026')).toThrow()
  })

  it('la nota más nueva va primero y lastBuildDate es su fecha', () => {
    const rss = armarRss([
      { slug: 'vieja', title: 'V', description: 'v', publishedAt: '2026-01-01', updatedAt: null },
      { slug: 'revisada', title: 'R', description: 'r', publishedAt: '2025-01-01', updatedAt: '2026-03-01' },
    ])
    expect(rss.indexOf('/blog/revisada')).toBeLessThan(rss.indexOf('/blog/vieja'))
    expect(rss).toContain(`<lastBuildDate>${fechaRss('2026-03-01')}</lastBuildDate>`)
  })

  it('el índice del blog y cada nota avisan dónde está el RSS', () => {
    for (const ruta of RUTAS.filter((r) => r === '/blog' || r.startsWith('/blog/'))) {
      expect(cabezaDe(escrito.paginas[ruta]), `${ruta} sin link al RSS`)
        .toMatch(new RegExp(`<link[^>]*rel="alternate"[^>]*type="application/rss\\+xml"[^>]*href="${RSS_URL.replace(/\./g, '\\.')}"`))
    }
  })
})

describe('datos estructurados', () => {
  const bloques = () => datosEstructurados(INDEX).map((t) => JSON.parse(t))
  const deTipo = (tipo) => bloques().find((b) => b['@type'] === tipo)
  const landing = leer('src/pages/Landing.jsx')
  const linkDeLanding = (red) => (landing.match(new RegExp(`${red}: '([^']+)'`)) || [])[1]

  it('cada bloque de cada página escrita (y de app.html) es JSON válido', () => {
    // Un comentario adentro del <script> rompe el bloque entero y Google deja
    // de leerlo sin avisar: ya pasó una vez.
    for (const [nombre, html] of [['app.html', escrito.app], ...Object.entries(escrito.paginas)]) {
      for (const texto of datosEstructurados(html)) {
        expect(() => JSON.parse(texto), `${nombre}: ${texto.slice(0, 80)}`).not.toThrow()
      }
    }
  })

  it('index.html ya no trae el HowTo de «Cómo funciona» (Google dejó de mostrarlo en 2023)', () => {
    expect(bloques().map((b) => b['@type'])).not.toContain('HowTo')
    expect(INDEX).not.toMatch(/"HowTo"/)
  })

  it('Organization: el Instagram de la marca en sameAs, y el LinkedIn del fundador en founder (no en la marca)', () => {
    const org = deTipo('Organization')
    const instagram = linkDeLanding('instagram')
    const linkedin = linkDeLanding('linkedin')
    expect(instagram, 'no encontré el Instagram en Landing.jsx').toMatch(/^https:\/\/www\.instagram\.com\//)
    expect(linkedin, 'no encontré el LinkedIn en Landing.jsx').toMatch(/^https:\/\/www\.linkedin\.com\/in\//)
    expect(org.sameAs).toContain(instagram)
    expect(org.sameAs).not.toContain(linkedin)
    expect(org.founder).toMatchObject({ '@type': 'Person', name: 'Nicolás Pussetto' })
    expect(org.founder.sameAs).toContain(linkedin)
  })

  it('Organization: el email es uno que el sitio muestra como contacto', () => {
    const { email } = deTipo('Organization')
    const visibles = Object.values(escrito.paginas).filter((html) => html.includes(`mailto:${email}`))
    expect(visibles.length, `${email} no aparece como contacto en ninguna página pública`).toBeGreaterThan(0)
  })

  it('WebSite: «Rendi Finance» como nombre alternativo, para no confundirse con otra «Rendi»', () => {
    expect(deTipo('WebSite').alternateName).toBe('Rendi Finance')
  })
})
