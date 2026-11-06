import { borrar as borrarDelAlmacen, guardar as guardarEnAlmacen, leer as leerDelAlmacen } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'
// origen — de dónde vino quien se registra (qué post, qué campaña, qué red).
// ═══════════════════════════════════════════════════════════════════════════
// El link de cada post lleva un código: `rendi.finance/?d=x-20261019`. También
// se aceptan los `utm_*` de siempre: `utm_source`, `utm_medium` y `utm_campaign`
// quedan como `fuente/medio/campaña` (el medio dice si fue pago: `paid`, `cpc`;
// se sacan los que falten). Al abrir la página
// se anota ese código en el navegador, y al crear la cuenta viaja con el
// registro y queda escrito en la fila del usuario (`users.origen`). El panel de
// /admin cuenta los registros por código y por canal (IA, X, Meta, Google…).
//
// Si el link no trae código, se anota lo que se pueda reconocer solo:
//   · la MARCA que la red le agrega al link (`?fbclid=…` en Facebook e
//     Instagram, `gclid` en los anuncios de Google): `clic/fbclid`;
//   · el SITIO de donde venía (document.referrer): `sitio/t.co`,
//     `sitio/perplexity.ai`, o una app de Android: `app/com.google.android.gm`.
//     Si vinieron los dos, van juntos: `sitio/l.instagram.com/fbclid`.
// Se guarda SÓLO el nombre del sitio, de la app o de la marca: nunca la
// dirección de donde venía (la de un buscador trae lo que se buscó) ni el valor
// de la marca (identifica el clic). Qué canal es cada uno no se decide acá: lo
// decide el servidor (backend/canal_de_origen.py), que además guarda el nombre
// del sitio o de la app sólo si es uno que conoce (si no, «otro»).
//
// Reglas:
//   · MANDA EL PRIMER CÓDIGO. Quien entró por el post del lunes y volvió el
//     jueves por otro, se cuenta para el del lunes: ése es el que lo trajo.
//   · UN CÓDIGO LE GANA A LO RECONOCIDO SOLO, aunque llegue después. Quien entró
//     un día desde Google y a la semana tocó el anuncio de Meta (el anuncio de
//     «volvé» le aparece justo a quien ya entró) se cuenta para el anuncio. Al
//     revés nunca: un sitio no pisa un código. Entre sitios y marcas, manda el
//     primero.
//   · VENCE A LOS 30 DÍAS. Pasado ese tiempo el primer contacto ya no explica
//     nada, y cualquier origen nuevo lo reemplaza.
//   · `d` le gana a los `utm_*` si vienen los dos: es el nuestro. Y un código le
//     gana a la marca y al sitio de esa misma visita.
//   · Un código del link no se puede hacer pasar por uno reconocido solo:
//     `?d=sitio/chatgpt.com` se anota `sitio-chatgpt.com` («Otro link con código»).
//   · Las apps de Instagram, Facebook o X a veces abren el link sin decir de
//     dónde venía: sin código ni marca, esa visita no anota nada (en el panel,
//     «Sin dato»).
//
// ⚠️ Se lee en `main.jsx`, ANTES de montar la app, y no en un componente: el
// demo (`?demo=1`, AuthContext) borra TODO lo que viene después del `?` al
// arrancar, así que `?demo=1&d=x-1` perdía el código si se leía después.
//
// De la dirección se saca sólo `d` (para que un link compartido no arrastre el
// código de otro). Los `utm_*` se dejan: Google Analytics los lee de la
// dirección para su propia atribución, y sacarlos antes de que cargue se la
// borraría. `demo=1` y cualquier otro parámetro quedan como estaban.

export const ORIGEN_KEY = 'rendi_origen'
export const ORIGEN_DURA_MS = 30 * 24 * 60 * 60 * 1000
const LARGO_MAX = 60

/**
 * El código limpio: minúsculas, sólo letras, números, `-` `_` `.` `/`. null si
 * no queda nada o si trae una arroba (es un mail, no un código: le pasa a una
 * herramienta de mails que mete la dirección de cada uno en el utm).
 */
export function normalizarCodigo(valor) {
  if (valor == null || String(valor).includes('@')) return null
  const limpio = String(valor).trim().toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9._/-]/g, '')
    .slice(0, LARGO_MAX)
  return limpio || null
}

// Los comienzos de lo que se reconoce solo (ver codigoDeLaVisita). Un código
// puesto en el link no puede empezar así.
const AUTOMATICO = /^(sitio|app|clic)\//
const esAutomatico = codigo => AUTOMATICO.test(codigo || '')

/** El código que trae una dirección (`?d=` o `utm_*`), o null. */
export function codigoDeLaDireccion(search) {
  let params
  try { params = new URLSearchParams(search || '') } catch { return null }
  let codigo = normalizarCodigo(params.get('d'))
  if (!codigo) {
    const fuente = normalizarCodigo(params.get('utm_source'))
    const campana = normalizarCodigo(params.get('utm_campaign'))
    // El medio sólo acompaña: un link con utm_medium solo no trae código.
    if (fuente || campana) {
      const medio = normalizarCodigo(params.get('utm_medium'))
      codigo = normalizarCodigo([fuente, medio, campana].filter(Boolean).join('/'))
    }
  }
  return codigo && esAutomatico(codigo) ? codigo.replace('/', '-') : codigo
}

// Las marcas que cada red le agrega a sus links, en el orden en que se buscan
// (si vienen dos, se anota la primera). Tiene que ser la misma lista que MARCAS
// en backend/canal_de_origen.py, que dice de quién es cada una: lo verifica
// test_origen_registros.py.
export const MARCAS_DE_CLIC = ['fbclid', 'twclid', 'gclid', 'gbraid', 'wbraid', 'ttclid', 'msclkid']

/** El nombre de la marca de clic que trae una dirección (`fbclid`…), o null. Nunca su valor. */
export function marcaDeClic(search) {
  let params
  try { params = new URLSearchParams(search || '') } catch { return null }
  return MARCAS_DE_CLIC.find(m => (params.get(m) || '').trim() !== '') || null
}

const esDeRendi = (host, propio) =>
  host === 'rendi.finance' || host.endsWith('.rendi.finance') || host === propio

/**
 * De dónde venía la persona: `{ tipo: 'sitio', nombre: 't.co' }` para una
 * página web (sin `www.`), `{ tipo: 'app', nombre: 'com.google.android.gm' }`
 * para una app de Android. SÓLO el nombre. null si no hay, si es Rendi mismo
 * (una recarga, o `propio`: el sitio donde está abierta la página) o si no se
 * entiende.
 */
export function lugarDeDondeVenia(referrer, propio = '') {
  if (!referrer) return null
  let u
  try { u = new URL(referrer) } catch { return null }
  const sinWww = h => h.toLowerCase().replace(/\.$/, '').replace(/^www\./, '')
  if (u.protocol === 'http:' || u.protocol === 'https:') {
    const host = sinWww(u.hostname)
    if (!host || esDeRendi(host, sinWww(propio || ''))) return null
    return { tipo: 'sitio', nombre: host }
  }
  // new URL('android-app://com.google.android.gm/').origin es "null": el nombre
  // de la app es el host.
  if (u.protocol === 'android-app:' && u.host) return { tipo: 'app', nombre: u.host.toLowerCase() }
  return null
}

/** `sitio/<sitio>[/<marca>]` o `app/<app>[/<marca>]`, en el largo que acepta el servidor. */
function codigoDelLugar(lugar, marca) {
  const sufijo = marca ? `/${marca}` : ''
  const cabe = LARGO_MAX - lugar.tipo.length - 1 - sufijo.length
  // La misma limpieza que normalizarCodigo, sin `/` y sin cortar todavía: el
  // corte de normalizarCodigo es por atrás y se llevaría el sitio.
  let nombre = String(lugar.nombre).toLowerCase().replace(/[^a-z0-9._-]/g, '')
  if (!nombre) return marca ? `clic/${marca}` : null
  // Un sitio que no entra se recorta por adelante: se pierden subdominios y
  // queda el sitio (`l.facebook.com`), que es lo que dice de dónde venía.
  if (lugar.tipo === 'sitio') {
    while (nombre.length > cabe && nombre.includes('.')) nombre = nombre.slice(nombre.indexOf('.') + 1)
  }
  return `${lugar.tipo}/${nombre.slice(0, cabe)}${sufijo}`
}

/**
 * Lo que se anota de una visita: el código del link (`d` o utm); si no trae,
 * el sitio de donde venía y la marca de clic; si no, null.
 */
export function codigoDeLaVisita(search, referrer, propio = '') {
  const codigo = codigoDeLaDireccion(search)
  if (codigo) return codigo
  const marca = marcaDeClic(search)
  const lugar = lugarDeDondeVenia(referrer, propio)
  if (lugar) return codigoDelLugar(lugar, marca)
  return marca ? `clic/${marca}` : null
}

function leerGuardado() {
  try {
    const raw = leerDelAlmacen(CATALOGO.origen)
    if (!raw) return null
    const o = JSON.parse(raw)
    return o && typeof o.codigo === 'string' && typeof o.visto === 'string' ? o : null
  } catch {
    return null
  }
}

function vencido(o, ahora) {
  const t = Date.parse(o.visto)
  return !Number.isFinite(t) || ahora - t > ORIGEN_DURA_MS
}

/**
 * Al abrir la página: si la visita trae un código (o se reconoce de dónde
 * venía) y no hay uno vigente guardado, se guarda. Después se saca `d` de la
 * dirección. Nunca tira: el navegador puede tener el almacenamiento bloqueado.
 */
export function anotarOrigen(ahora = Date.now()) {
  if (typeof window === 'undefined') return null
  let codigo = null
  try {
    const referrer = typeof document !== 'undefined' ? document.referrer : ''
    codigo = codigoDeLaVisita(window.location.search, referrer, window.location.hostname)
  } catch { return null }
  if (codigo) {
    try {
      const previo = leerGuardado()
      // Un código le gana a lo reconocido solo (ver «Reglas» arriba).
      const leGana = !esAutomatico(codigo) && esAutomatico(previo?.codigo)
      if (!previo || vencido(previo, ahora) || leGana) {
        // Sin la página donde entró: en un informe público (/i/<llave>) la
        // dirección ES la llave de la cartera del cliente, y quedaba guardada
        // en su navegador sin fecha. Nadie la usaba.
        guardarEnAlmacen(CATALOGO.origen, JSON.stringify({ codigo, visto: new Date(ahora).toISOString() }))
      }
    } catch { /* sin almacenamiento: no se puede anotar, la página sigue */ }
  }
  sacarCodigoDeLaDireccion()
  return codigo
}

function sacarCodigoDeLaDireccion() {
  try {
    const url = new URL(window.location.href)
    if (!url.searchParams.has('d')) return
    url.searchParams.delete('d')
    const qs = url.searchParams.toString()
    window.history.replaceState(window.history.state, '', url.pathname + (qs ? `?${qs}` : '') + url.hash)
  } catch { /* la dirección se queda como vino */ }
}

/** El origen vigente para mandar con el registro, o null. */
export function origenParaElRegistro(ahora = Date.now()) {
  const o = leerGuardado()
  if (!o || vencido(o, ahora)) return null
  return { origen: o.codigo, origen_visto: o.visto }
}

/** Ya se registró con este origen: se borra para que una segunda cuenta en el mismo navegador no lo herede. */
export function olvidarOrigen() {
  try { borrarDelAlmacen(CATALOGO.origen) } catch { /* nada */ }
}
