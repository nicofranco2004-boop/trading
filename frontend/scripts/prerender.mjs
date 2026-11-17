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
// Y guarda el index.html vacío original como dist/app.html, con «noindex» y un
// título neutro: es el que sirve Vercel para las rutas de la app y para toda
// dirección que no existe (vercel.json), que no tienen nada que guardar en
// Google. Además escribe dist/rss.xml con las notas del blog.
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
import { escribirSitio } from './paginasEscritas.mjs'

const raiz = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dist = path.join(raiz, 'dist')

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

const { render, RUTAS, POSTS } = await import(path.join(raiz, 'dist-ssr', 'entry-server.js'))

// Lo que se escribe (app.html, las páginas públicas y rss.xml) lo arma
// `escribirSitio`, en scripts/paginasEscritas.mjs: la prueba
// src/__guards__/lo-que-lee-google.test.js corre esa MISMA función con las
// páginas de verdad. Acá sólo se le pasa lo que armó `vite build`.
const base = fs.readFileSync(path.join(dist, 'index.html'), 'utf8')
const { paginas } = await escribirSitio({ dist, base, render, rutas: RUTAS, posts: POSTS })
console.log(`prerender: ${paginas} páginas públicas escritas + app.html (noindex) + rss.xml`)
