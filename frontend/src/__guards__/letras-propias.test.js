// Las letras (Geist y JetBrains Mono) se sirven desde el propio sitio, y lo
// que se PUBLICA las pide bien.
// ═══════════════════════════════════════════════════════════════════════════
// 🔴 POR QUÉ (16/11/2026). src/index.css cargaba las letras con un @import a
// fonts.googleapis.com. Eso arma una cadena de cuatro pedidos, cada uno
// esperando al anterior (la página → nuestro CSS → el CSS de Google → el
// archivo de la letra, en un tercer servidor), y un @import además frena el
// primer dibujo de la página entera hasta que contesta Google. Medido en un
// celular con 4G lenta y el procesador 4 veces más lento (mediana de 3, en
// dos rondas):
//   portada: primer texto 1,6–1,9 s → 1,1–1,2 s; elemento más grande
//   2,7–2,8 s → 1,1–1,2 s (y Chrome lo anota una vez, no dos); salto del
//   titular cuando llegaba Geist (CLS) 0,13 → 0.
//
// 🔴 Y POR QUÉ EN src/assets/fonts Y NO EN public/ (16/11/2026, revisión). La
// primera versión las puso en public/fonts. Vercel sirve public/ con «guardalo,
// pero preguntame cada vez si cambió» (max-age=0): cada página entera que se
// abría —la segunda de una visita, la app con la sesión ya iniciada— le volvía
// a preguntar al servidor por la letra antes de usarla, y salía más lenta que
// con Google. Y si el archivo faltaba, el comodín de vercel.json contestaba
// app.html con un «todo bien»: el navegador bajaba una página entera creyendo
// que era una letra, y el texto salía con la letra del sistema sin un aviso.
// Desde src/, Vite publica cada letra en /assets/<nombre>-<huella>.woff2: se
// guarda un día sin preguntar, cambia de nombre sola si cambia el archivo, y
// si falta da «no existe» (404).
//
// CÓMO PRUEBA: la mitad de abajo no lee index.html ni index.css. Corre el
// MISMO `npm run build` que corre Vercel (vite build, el armado del lado del
// servidor y scripts/prerender.mjs, que escribe las 26 páginas públicas y
// app.html) en una carpeta aparte, y mira lo que se publicaría. Antes miraba el
// index.html de origen y un prerender.mjs que dejara de copiar el preload, o
// una letra sin su alfabeto común, pasaban en verde.
//
// Qué vigila:
//   1. Que ningún CSS de src/ vuelva a importar un CSS de otro servidor (Google
//      Fonts u otro): cualquier @import externo frena el primer dibujo.
//   2. Que ni src/ ni index.html le pidan letras a Google por otro camino.
//   En lo publicado (cada página pública y app.html):
//   3. Que precargue Geist, con type y crossorigin, desde /assets/ con huella en
//      el nombre, y que ese archivo exista y sea una letra de verdad.
//   4. Que el preload pida EXACTAMENTE el mismo archivo que el @font-face de
//      Geist del CSS publicado (si difieren, se bajan dos), y que cada
//      @font-face apunte a una letra que existe.
//   5. Que "Geist" y "JetBrains Mono" (utils/shareCard.js las precarga por
//      nombre) cubran entero el alfabeto común (U+0000–00FF: á é í ó ú ñ ü ¿ ¡
//      « ») y la puntuación que usan los textos (– — “ ” … • − €). Sin eso, los
//      tickers o el texto salen con la letra del sistema y ninguna otra prueba
//      lo ve.
//   6. Que vercel.json haga con esas letras lo que hace falta: guardarlas al
//      menos un día y contestar «no existe» si faltan (ninguna reescritura las
//      tapa con app.html).
import { describe, it, expect, beforeAll, afterAll } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { PAGINAS_PUBLICAS } from '../paginasPublicas.js'

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const leer = (f) => fs.readFileSync(path.join(raiz, f), 'utf8')

function archivosDe(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? archivosDe(path.join(dir, e.name)) : [path.join(dir, e.name)])
}
const fuentesDelSitio = () => archivosDe(path.join(raiz, 'src'))
  .filter((f) => /\.(css|jsx?|html)$/.test(f) && !/\.test\.|__tests__/.test(f))

const sinComentarios = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')
const sinNotasHtml = (html) => html.replace(/<!--[\s\S]*?-->/g, '')

// ── El mismo `npm run build`, en una carpeta aparte ─────────────────────────
// prerender.mjs busca dist/ y dist-ssr/ al lado de su propia carpeta, así que
// se copia scripts/ entero a la carpeta aparte (con los módulos que importe) y
// se enlazan src/ y node_modules/ para que encuentre lo que importa.
let aparte
let dist
let antes
beforeAll(async () => {
  antes = process.env.NODE_ENV
  process.env.NODE_ENV = 'production'
  aparte = fs.mkdtempSync(path.join(os.tmpdir(), 'rendi-letras-'))
  dist = path.join(aparte, 'dist')
  fs.cpSync(path.join(raiz, 'scripts'), path.join(aparte, 'scripts'), { recursive: true })
  fs.copyFileSync(path.join(raiz, 'package.json'), path.join(aparte, 'package.json'))
  fs.symlinkSync(path.join(raiz, 'node_modules'), path.join(aparte, 'node_modules'), 'dir')
  fs.symlinkSync(path.join(raiz, 'src'), path.join(aparte, 'src'), 'dir')
  const { build } = await import('vite')
  const comun = { root: raiz, configFile: path.join(raiz, 'vite.config.js'), mode: 'production', logLevel: 'silent' }
  await build({ ...comun, build: { outDir: dist, emptyOutDir: true, reportCompressedSize: false } })
  await build({ ...comun, build: {
    ssr: path.join(raiz, 'src/prerender/entry-server.jsx'),
    outDir: path.join(aparte, 'dist-ssr'), emptyOutDir: true, reportCompressedSize: false,
  } })
  execFileSync(process.execPath, [path.join(aparte, 'scripts', 'prerender.mjs')], { cwd: aparte, stdio: 'pipe' })
}, 240_000)

afterAll(() => {
  if (antes === undefined) delete process.env.NODE_ENV
  else process.env.NODE_ENV = antes
  if (aparte) fs.rmSync(aparte, { recursive: true, force: true })
})

// Las páginas que escribe el prerender (una por ruta pública) + app.html, que
// es la que reciben las rutas de la app con la sesión iniciada.
const paginasPublicadas = () => [
  ...Object.keys(PAGINAS_PUBLICAS).map((ruta) => (ruta === '/'
    ? path.join(dist, 'index.html')
    : path.join(dist, ...ruta.split('/').filter(Boolean), 'index.html'))),
  path.join(dist, 'app.html'),
]

const etiquetas = (html) => [...sinNotasHtml(html).matchAll(/<link\b[^>]*>/g)].map((m) => m[0])
const atributo = (tag, nombre) => (tag.match(new RegExp(`\\b${nombre}="([^"]+)"`)) || [])[1]
const preloadsDeLetras = (html) => etiquetas(html)
  .filter((tag) => /\brel="preload"/.test(tag) && /\bas="font"/.test(tag))

const enDist = (url) => path.join(dist, ...url.split('?')[0].split('/').filter(Boolean))
const esWoff2 = (url) => {
  const f = enDist(url)
  if (!fs.existsSync(f)) return false
  const b = fs.readFileSync(f)
  return b.length > 1000 && b.subarray(0, 4).toString('latin1') === 'wOF2'
}

// Cada @font-face del CSS publicado por una página: familia, archivo y rangos.
function carasPublicadas(html) {
  const css = etiquetas(html)
    .filter((tag) => /\brel="stylesheet"/.test(tag) && /^\/[^/]/.test(atributo(tag, 'href') || ''))
    .map((tag) => fs.readFileSync(enDist(atributo(tag, 'href')), 'utf8'))
    .join('\n')
  return [...sinComentarios(css).matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => ({
    familia: ((m[1].match(/font-family:\s*([^;]+)/) || [])[1] || '').trim().replace(/^['"]|['"]$/g, ''),
    src: (m[1].match(/url\(\s*['"]?([^'")]+)['"]?\s*\)/) || [])[1],
    rango: (m[1].match(/unicode-range:\s*([^;]+)/) || [])[1] || null,
    mostrar: ((m[1].match(/font-display:\s*([^;]+)/) || [])[1] || '').trim() || null,
  }))
}

// «U+0000-00FF, U+0131, U+4??» → [[0, 255], [305, 305], [1024, 1279]].
// Sin unicode-range, la cara sirve para cualquier letra.
function rangos(texto) {
  if (!texto) return [[0, 0x10ffff]]
  return [...texto.matchAll(/u\+([0-9a-f?]+)(?:-([0-9a-f]+))?/gi)].map(([, a, b]) => (a.includes('?')
    ? [parseInt(a.replace(/\?/g, '0'), 16), parseInt(a.replace(/\?/g, 'f'), 16)]
    : [parseInt(a, 16), parseInt(b ?? a, 16)]))
}

// Las letras que tiene que dibujar cada familia: el alfabeto común entero
// (U+0000–00FF) y la puntuación que usan los textos del sitio.
const LETRAS_QUE_SE_USAN = [
  ...Array.from({ length: 0x100 }, (_, i) => i),
  0x2013, 0x2014, 0x201c, 0x201d, 0x2022, 0x2026, 0x2212, 0x20ac, // – — “ ” • … − €
]
const hex = (n) => 'U+' + n.toString(16).toUpperCase().padStart(4, '0')

// vercel.json escribe las direcciones como «/assets/(.*)»: lo de adentro de los
// paréntesis ya es una expresión regular; lo de afuera es texto literal.
function comoRegExp(source) {
  let re = ''
  let hondo = 0
  for (let i = 0; i < source.length; i++) {
    const c = source[i]
    if (c === '(') hondo += 1
    if (hondo > 0) re += c
    else if (c === ':' && /\w/.test(source[i + 1] || '')) {
      while (/\w/.test(source[i + 1] || '')) i += 1
      re += '[^/]+'
    } else re += c.replace(/[.*+?^${}|[\]\\]/g, '\\$&')
    if (c === ')') hondo -= 1
  }
  return new RegExp(`^${re}$`)
}
const vercel = JSON.parse(leer('vercel.json'))

describe('las letras se sirven desde el propio sitio', () => {
  it('ningún CSS de src/ importa un CSS de otro servidor (frena el primer dibujo)', () => {
    const externos = fuentesDelSitio().filter((f) => f.endsWith('.css')).flatMap((f) =>
      [...sinComentarios(fs.readFileSync(f, 'utf8')).matchAll(/@import\s+(?:url\()?\s*['"]?(https?:)?\/\/[^;]+;/g)]
        .map((m) => `${path.relative(raiz, f)}: ${m[0]}`))
    expect(externos).toEqual([])
  })

  it('ni src/ ni index.html le piden letras a Google Fonts', () => {
    const conGoogle = [...fuentesDelSitio(), path.join(raiz, 'index.html')]
      .filter((f) => {
        const t = fs.readFileSync(f, 'utf8')
        const sinNotas = f.endsWith('.html') ? sinNotasHtml(t) : sinComentarios(t)
        return /fonts\.(googleapis|gstatic)\.com/.test(sinNotas)
      })
      .map((f) => path.relative(raiz, f))
    expect(conGoogle).toEqual([])
  })
})

describe('lo que se publica pide bien las letras', () => {
  it('se publicaron todas las páginas (si no, «está bien» no prueba nada)', () => {
    const paginas = paginasPublicadas()
    expect(paginas.length).toBeGreaterThan(20)
    for (const f of paginas) expect(fs.existsSync(f), path.relative(dist, f)).toBe(true)
    // Escritas por el prerender, no el index.html vacío.
    expect(fs.readFileSync(path.join(dist, 'planes', 'index.html'), 'utf8')).toContain('data-prerender')
  })

  it('cada página y app.html precargan Geist desde /assets/, con huella, y el archivo es una letra de verdad', () => {
    const hrefs = new Set()
    for (const f of paginasPublicadas()) {
      const donde = path.relative(dist, f)
      const preloads = preloadsDeLetras(fs.readFileSync(f, 'utf8'))
      expect(preloads.length, `${donde} no precarga ninguna letra`).toBeGreaterThan(0)
      for (const tag of preloads) {
        const href = atributo(tag, 'href')
        // Con huella en el nombre (geist-latin-BGnTDqni.woff2): si el archivo
        // cambia, cambia el nombre, y guardarlo un día no deja a nadie con el viejo.
        expect(href, `${donde}: ${tag}`).toMatch(/^\/assets\/[\w.-]+-[\w-]{6,}\.woff2$/)
        expect(esWoff2(href), `${donde}: ${href} no se publicó o no es un .woff2`).toBe(true)
        expect(tag, `${donde}: sin type="font/woff2" el navegador no sabe si la puede usar`).toMatch(/\btype="font\/woff2"/)
        // Sin crossorigin el navegador la baja dos veces: las letras se piden en modo CORS.
        expect(tag, `${donde}: el preload de una letra necesita crossorigin`).toMatch(/\scrossorigin(?:\s|=|\/?>)/)
        hrefs.add(href)
      }
    }
    expect([...hrefs].length, `no todas las páginas precargan lo mismo: ${[...hrefs]}`).toBe(1)
  })

  it('el preload pide el MISMO archivo que el @font-face de Geist, y cada @font-face apunta a una letra que existe', () => {
    for (const f of paginasPublicadas()) {
      const donde = path.relative(dist, f)
      const html = fs.readFileSync(f, 'utf8')
      const caras = carasPublicadas(html)
      const geist = caras.filter((c) => c.familia === 'Geist')
      expect(geist.length, `${donde}: el CSS publicado no declara Geist con @font-face`).toBeGreaterThan(0)
      const hrefs = preloadsDeLetras(html).map((tag) => atributo(tag, 'href'))
      for (const h of hrefs) expect(geist.map((c) => c.src), `${donde}: ${h} no es la letra de Geist`).toContain(h)
      for (const c of caras) {
        expect(c.src, `${donde}: @font-face de ${c.familia} sin url()`).toBeTruthy()
        expect(esWoff2(c.src), `${donde}: ${c.src} (${c.familia}) no se publicó o no es un .woff2`).toBe(true)
      }
    }
  })

  // Antes lo garantizaba el «&display=swap» del enlace a Google Fonts; ahora
  // vive sólo en index.css. Sin font-display el navegador deja el texto
  // INVISIBLE hasta ~3 s mientras baja la letra: justo el primer texto que
  // este cambio mejoró.
  it('cada @font-face muestra el texto con la letra del sistema mientras baja la propia (swap u optional)', () => {
    const caras = carasPublicadas(fs.readFileSync(path.join(dist, 'app.html'), 'utf8'))
    expect(caras.length).toBeGreaterThan(0)
    const sin = caras.filter((c) => !/^(swap|optional)$/.test(c.mostrar || ''))
    expect(sin.map((c) => `${c.familia} (${c.src}): ${c.mostrar ?? 'sin font-display'}`)).toEqual([])
  })

  it('Geist y JetBrains Mono cubren el alfabeto común entero y la puntuación de los textos', () => {
    const caras = carasPublicadas(fs.readFileSync(path.join(dist, 'app.html'), 'utf8'))
      .filter((c) => c.src && esWoff2(c.src))
    for (const familia of ['Geist', 'JetBrains Mono']) {
      const suyos = caras.filter((c) => c.familia === familia).flatMap((c) => rangos(c.rango))
      expect(suyos.length, `ninguna cara de ${familia} con un archivo publicado`).toBeGreaterThan(0)
      const faltan = LETRAS_QUE_SE_USAN.filter((cp) => !suyos.some(([a, b]) => cp >= a && cp <= b))
      expect(faltan.map(hex), `${familia} no cubre estas letras: salen con la del sistema`).toEqual([])
    }
  })

  it('vercel.json guarda esas letras al menos un día y contesta «no existe» si faltan', () => {
    const html = fs.readFileSync(path.join(dist, 'app.html'), 'utf8')
    const urls = new Set([
      ...preloadsDeLetras(html).map((tag) => atributo(tag, 'href')),
      ...carasPublicadas(html).map((c) => c.src),
    ])
    expect(urls.size).toBeGreaterThan(0)
    for (const url of urls) {
      // Vercel sirve primero el archivo si existe; la reescritura sólo actúa si
      // falta. Si alguna la toma (el comodín → /app.html), una letra que falta
      // devuelve una página entera con un 200 en vez de un 404.
      const laTapan = vercel.rewrites.filter((r) => comoRegExp(r.source).test(url))
      expect(laTapan.map((r) => `${r.source} → ${r.destination}`), `${url}: si falta, no da 404`).toEqual([])
      // La regla que vale es la última que nombra Cache-Control y aplica siempre
      // (sin condiciones de host ni de encabezados).
      const cache = vercel.headers
        .filter((h) => !h.has && !h.missing && comoRegExp(h.source).test(url))
        .flatMap((h) => h.headers.filter((x) => x.key.toLowerCase() === 'cache-control'))
        .map((x) => x.value)
        .pop() || ''
      const maxAge = Number((cache.match(/max-age=(\d+)/) || [])[1] || 0)
      expect(cache, `${url}: Vercel no le pone Cache-Control y la sirve con max-age=0`).not.toBe('')
      expect(cache, `${url}: ${cache}`).not.toMatch(/no-store|no-cache/)
      expect(maxAge, `${url}: ${cache} (con menos de un día, cada página nueva vuelve a preguntar)`).toBeGreaterThanOrEqual(86400)
    }
  })
})
