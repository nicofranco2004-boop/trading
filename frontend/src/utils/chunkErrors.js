// ─── "El navegador no pudo cargar un pedazo de la app" ───────────────────────
// Dos cosas viven acá: RECONOCER ese error, y REPARARLO.
//
// El bug de fondo (producción, 2026-09-16): Vercel contestaba cualquier
// /assets/*.js inexistente con index.html — o sea HTML — con status 200 y el
// header `immutable, max-age=1 año` que le ponemos a /assets/. El navegador
// guardó esa página HTML bajo el nombre de un archivo .js y, como dice
// "immutable", NO VUELVE A PREGUNTAR: sigue sirviendo el HTML aunque el archivo
// de verdad ya exista en el servidor. La app queda rota en ESE navegador para
// siempre, sin que el servidor tenga nada mal.
//
// La causa se tapó en vercel.json (/assets/ ya no cae al index.html). Lo de acá
// es la otra mitad: rescatar a los navegadores que YA quedaron envenenados.

// Cada patrón está escrito contra el mensaje TEXTUAL de un motor real, no contra
// una paráfrasis. La lista original se armó mirando Chrome y NINGUNO matcheaba
// lo que Safari escribe de verdad — por eso en Safari la reparación automática
// no arrancaba nunca y el usuario veía "Se rompió esta pantalla".
// Si aparece un mensaje nuevo, se agrega ACÁ (un solo lugar) y su string exacto
// va al test.
const CHUNK_ERROR_PATTERNS = [
  // Webpack / Vite
  'Loading chunk',
  'Loading CSS chunk',
  'Failed to fetch dynamically imported module',
  'error loading dynamically imported module',
  'Importing a module script failed',
  // Chrome — MIME incorrecto en un module script
  'Failed to load module script',
  'Expected a JavaScript module script',
  "MIME type ('text/html')",
  'is not executable',
  // Safari — MIME incorrecto. ESTE es el que faltaba.
  'is not a valid JavaScript MIME type',
  // Firefox — MIME incorrecto
  'was blocked because of a disallowed MIME type',
  // Safari parseando HTML como JS (script clásico, no módulo)
  'Unexpected token',
]

export function isChunkLoadError(msg) {
  const s = String(msg || '')
  return CHUNK_ERROR_PATTERNS.some(p => s.includes(p))
}

// Solo reparamos archivos de build (/assets/), nunca otra cosa: son los únicos
// que llevan el header `immutable` y por lo tanto los únicos que el navegador
// puede estar sirviendo de su propio cache sin revalidar.
function esAssetDelBuild(url, origin) {
  if (typeof url !== 'string' || !origin) return false
  if (!url.startsWith(origin + '/assets/')) return false
  return /\.(?:js|mjs|css)(?:[?#]|$)/.test(url)
}

// Chrome y Vite escriben la URL del chunk dentro del mensaje; Safari no. Cuando
// está, es la que MÁS nos importa reparar, así que va primera.
export function urlsEnElMensaje(mensaje) {
  const re = /https?:\/\/[^\s"'()]+/g
  return String(mensaje || '').match(re) || []
}

// Junta los candidatos a reparar: la URL que menciona el error + todo /assets/
// que esta página llegó a pedir + lo que cuelga del HTML. Se deduplica y se
// acota, porque esto se ejecuta cuando la app YA está rota y hay que recargar.
export function urlsAReparar({ mensaje, recursos = [], nodos = [], origin = '', max = 40 }) {
  const out = []
  const sumar = (u) => {
    if (!esAssetDelBuild(u, origin)) return
    if (out.includes(u)) return
    out.push(u)
  }
  urlsEnElMensaje(mensaje).forEach(sumar)
  recursos.forEach(sumar)
  nodos.forEach(sumar)
  return out.slice(0, max)
}

// `cache: 'reload'` es la pieza clave y está verificada en un lab que reproduce
// el bug: fuerza ir a la red IGNORANDO el cache y, además, PISA la entrada
// guardada. Un fetch normal posterior —y el import() tras recargar— ya reciben
// el JavaScript de verdad. Sin esto, recargar no sirve de nada: el navegador
// vuelve a sacar el HTML envenenado de su propio cache sin preguntar.
export async function repararAssets(urls, { fetchImpl, timeoutMs = 3000 } = {}) {
  const f = fetchImpl || (typeof fetch !== 'undefined' ? fetch : null)
  if (!f || !urls.length) return 0
  let reparados = 0
  const trabajo = Promise.allSettled(
    urls.map(u =>
      f(u, { cache: 'reload', credentials: 'omit' }).then(() => { reparados += 1 }),
    ),
  )
  // Nunca dejamos al usuario esperando: si la red no responde, recargamos igual.
  await Promise.race([trabajo, new Promise(r => setTimeout(r, timeoutMs))])
  return reparados
}
