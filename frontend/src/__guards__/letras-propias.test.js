// Las letras (Geist y JetBrains Mono) se sirven desde el propio sitio.
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
// Ahora los archivos viven en public/fonts/ y index.html los pide apenas llega
// el HTML (<link rel="preload">).
//
// Qué vigila:
//   1. Que ningún CSS de src/ vuelva a importar un CSS de otro servidor (Google
//      Fonts u otro): cualquier @import externo frena el primer dibujo.
//   2. Que ni src/ ni index.html le pidan letras a Google por otro camino.
//   3. Que el preload apunte a un archivo que EXISTE en public/fonts y que sea
//      una letra de verdad. Si el archivo falta, Vercel no da error: el
//      comodín de vercel.json contesta app.html con un 200, el navegador baja
//      una página entera creyendo que es una letra y el texto sale con la
//      letra del sistema, sin un solo aviso.
//   4. Que el preload pida EXACTAMENTE el mismo archivo que usa el @font-face
//      de Geist. Si difieren, se bajan dos archivos y el precargado no sirve.
//   5. Que cada @font-face apunte a un archivo que existe, y que las familias
//      sigan llamándose "Geist" y "JetBrains Mono": utils/shareCard.js las
//      precarga por nombre para dibujar la imagen para redes.
//
// Lee index.html tal cual: scripts/prerender.mjs copia su <head> a las 26
// páginas públicas y a app.html, y sólo le saca título, descripción, og/twitter,
// hreflang y el HowTo — nunca un <link rel="preload">.
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const leer = (f) => fs.readFileSync(path.join(raiz, f), 'utf8')

function archivosDe(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? archivosDe(path.join(dir, e.name)) : [path.join(dir, e.name)])
}
const fuentesDelSitio = () => archivosDe(path.join(raiz, 'src'))
  .filter((f) => /\.(css|jsx?|html)$/.test(f) && !/\.test\.|__tests__/.test(f))

const sinComentarios = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '')
const css = sinComentarios(leer('src/index.css'))
const html = leer('index.html').replace(/<!--[\s\S]*?-->/g, '')

// Los <link rel="preload" as="font"> de index.html, con sus atributos.
const preloadsDeLetras = () => [...html.matchAll(/<link\b[^>]*>/g)]
  .map((m) => m[0])
  .filter((tag) => /\brel="preload"/.test(tag) && /\bas="font"/.test(tag))

// Cada @font-face de index.css: familia y archivo.
const caras = () => [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => ({
  familia: (m[1].match(/font-family:\s*['"]?([^'";]+?)['"]?\s*;/) || [])[1],
  src: (m[1].match(/url\(\s*['"]?([^'")]+)['"]?\s*\)/) || [])[1],
}))

const esWoff2 = (rutaPublica) => {
  const f = path.join(raiz, 'public', rutaPublica)
  if (!fs.existsSync(f)) return false
  const b = fs.readFileSync(f)
  return b.length > 1000 && b.subarray(0, 4).toString('latin1') === 'wOF2'
}

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
        const sinNotas = f.endsWith('.html') ? t.replace(/<!--[\s\S]*?-->/g, '') : sinComentarios(t)
        return /fonts\.(googleapis|gstatic)\.com/.test(sinNotas)
      })
      .map((f) => path.relative(raiz, f))
    expect(conGoogle).toEqual([])
  })

  it('index.html precarga Geist desde /fonts/, con el archivo en public/fonts y siendo una letra de verdad', () => {
    const preloads = preloadsDeLetras()
    expect(preloads.length, 'index.html no precarga ninguna letra').toBeGreaterThan(0)
    for (const tag of preloads) {
      const href = (tag.match(/\bhref="([^"]+)"/) || [])[1]
      expect(href, tag).toMatch(/^\/fonts\/[\w.-]+\.woff2$/)
      expect(esWoff2(href), `${href} no existe en public/ o no es un .woff2`).toBe(true)
      expect(tag, 'sin type="font/woff2" el navegador no sabe si la puede usar').toMatch(/\btype="font\/woff2"/)
      // Sin crossorigin el navegador la baja dos veces: las letras se piden en modo CORS.
      expect(tag, 'el preload de una letra necesita crossorigin').toMatch(/\scrossorigin(?:\s|=|\/?>)/)
    }
  })

  it('el preload pide el MISMO archivo que el @font-face de Geist (si no, se bajan dos)', () => {
    const geist = caras().filter((c) => c.familia === 'Geist')
    expect(geist.length, 'index.css no declara Geist con @font-face').toBeGreaterThan(0)
    const hrefs = preloadsDeLetras().map((tag) => (tag.match(/\bhref="([^"]+)"/) || [])[1])
    for (const c of geist) expect(hrefs).toContain(c.src)
    for (const h of hrefs) expect(caras().map((c) => c.src)).toContain(h)
  })

  it('cada @font-face apunta a un .woff2 que existe, con los nombres que usa el resto del código', () => {
    const lista = caras()
    expect(lista.map((c) => c.familia).sort()).toEqual(expect.arrayContaining(['Geist', 'JetBrains Mono']))
    for (const c of lista) {
      expect(c.src, `@font-face de ${c.familia} sin url()`).toMatch(/^\/fonts\//)
      expect(esWoff2(c.src), `${c.src} (${c.familia}) no existe en public/ o no es un .woff2`).toBe(true)
    }
  })
})
