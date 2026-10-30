// pantallasDeLaApp — la lista de pantallas de la app SALE DE App.jsx, no de
// una lista escrita a mano: una ruta nueva entra sola a las pruebas de
// «Ocultar saldos» (__guards__/ocultar-saldos-pantallas-*.render.test.jsx).
//
// Cada <Route path=… element={<X/>}> de AppRoutes (la app con sesión) es una
// pantalla. Las que reciben un parámetro se abren con uno del demo. Las que
// tienen pestañas (`const TABS = [{ id: … }]` + `?tab=`) se abren en cada una,
// y los <Navigate to="/x?tab=y"> también cuentan como pestaña.
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const APP = fs.readFileSync(path.join(SRC, 'App.jsx'), 'utf8')

// Con qué valor se abre cada ruta con parámetro (datos del demo).
export const PARAMETROS = {
  '/activo/:ticker': ['/activo/NVDA', '/activo/GGAL', '/activo/AL30', '/activo/BTC'],
  '/posiciones/:id': ['/posiciones/101', '/posiciones/199'],
}

// Rutas que no se miran, con el porqué. Cualquier otra ruta con parámetro que
// aparezca en App.jsx sin estar en PARAMETROS ni acá pone la prueba en rojo.
export const NO_SE_MIRAN = {
  '/i/:token': 'informe público del asesor: lo abre otra persona por link; el ojito es de quien mira su cuenta',
  '*': 'redirige a /',
  // ⚠️ HUECO: el demo no es asesor ni administrador, así que estas pantallas lo
  // mandan a otra parte o le dicen que no puede. Quedan SIN mirar por esta
  // prueba (anotado en la nota de la ronda, 30/10).
  '/clientes': 'del asesor: el demo no es asesor (redirige)',
  '/importar-historiales': 'del asesor: el demo no es asesor (redirige)',
  '/cobros': 'del asesor: el demo no es asesor',
  '/admin': 'del administrador: el demo no lo es; muestra datos de otras cuentas, no las tuyas',
  '/admin/pruebas': 'del administrador: el demo no lo es',
}

/**
 * Las rutas que también existen SIN sesión (la portada, el blog, la guía, los
 * términos…): no tienen datos de ninguna cuenta. Salen del bloque `if (!user)`
 * de Layout, no de una lista: una página pública nueva queda afuera sola, y una
 * privada nueva entra sola.
 */
export function rutasPublicas() {
  const i = APP.indexOf('if (!user) {')
  const j = APP.indexOf('</Routes>', i)
  return new Set([...APP.slice(i, j).matchAll(/<Route\s+path="([^"]+)"/g)].map(m => m[1]))
}

// Pantallas que guardan la pestaña en el navegador en vez de la URL: se abren
// en cada una (la prueba verifica que esos ids sigan existiendo en el archivo).
export const PESTANAS_GUARDADAS = {
  '/operaciones': { archivo: 'pages/Operations.jsx', clave: 'rendi_operations_tab', ids: ['all', 'trades', 'cobros'] },
}

function bloqueDeAppRoutes() {
  const i = APP.indexOf('function AppRoutes()')
  const j = APP.indexOf('</Routes>', i)
  return APP.slice(i, j)
}

/** { ruta, componente } de cada <Route> de la app con sesión. */
export function rutasDeLaApp() {
  const out = []
  for (const m of bloqueDeAppRoutes().matchAll(/<Route\s+path="([^"]+)"\s+element=\{<(\w+)([^}]*)\}/g)) {
    const [, ruta, comp, resto] = m
    const destino = comp === 'Navigate' ? /to="([^"]+)"/.exec(resto)?.[1] : null
    out.push({ ruta, componente: comp, destino })
  }
  return out
}

function archivoDe(componente) {
  const lazy = new RegExp(`const ${componente} = lazy\\(\\(\\) => import\\('\\./pages/(\\w+)'\\)`).exec(APP)
  const directo = new RegExp(`import ${componente} from '\\./pages/(\\w+)'`).exec(APP)
  const nombre = lazy?.[1] || directo?.[1]
  return nombre ? path.join(SRC, 'pages', `${nombre}.jsx`) : null
}

function pestanasDe(componente) {
  const f = archivoDe(componente)
  if (!f || !fs.existsSync(f)) return []
  const src = fs.readFileSync(f, 'utf8')
  if (!/get\('tab'\)/.test(src)) return []
  const bloque = /const TABS = \[([\s\S]*?)\n\]/.exec(src)
  return bloque ? [...bloque[1].matchAll(/id:\s*'([\w-]+)'/g)].map(x => x[1]) : []
}

/**
 * Las URLs que se abren. Cada una: { url, de } (de = la ruta de App.jsx).
 * Las que faltan decidir (parámetro sin valor del demo) van en `sinDecidir`.
 */
export function pantallasDeLaApp() {
  const urls = new Map()
  const sinDecidir = []
  const agregar = (url, de, local) => {
    const k = url + (local ? JSON.stringify(local) : '')
    if (!urls.has(k)) urls.set(k, { url, de, local })
  }
  const publicas = rutasPublicas()
  for (const { ruta, componente, destino } of rutasDeLaApp()) {
    if (ruta in NO_SE_MIRAN || (publicas.has(ruta) && ruta !== '/')) continue
    if (destino) { agregar(destino, ruta); continue }
    if (ruta.includes(':')) {
      if (PARAMETROS[ruta]) PARAMETROS[ruta].forEach(u => agregar(u, ruta))
      else sinDecidir.push(ruta)
      continue
    }
    const g = PESTANAS_GUARDADAS[ruta]
    if (g) g.ids.forEach(id => agregar(ruta, ruta, { [g.clave]: id }))
    else agregar(ruta, ruta)
    for (const t of pestanasDe(componente)) agregar(`${ruta}?tab=${t}`, ruta)
  }
  return { pantallas: [...urls.values()], sinDecidir }
}
