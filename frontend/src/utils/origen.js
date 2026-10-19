// origen — de dónde vino quien se registra (qué post, qué campaña).
// ═══════════════════════════════════════════════════════════════════════════
// El link de cada post lleva un código: `rendi.finance/?d=x-20261019`. También
// se aceptan los `utm_source` / `utm_campaign` de siempre. Al abrir la página
// se anota ese código en el navegador, y al crear la cuenta viaja con el
// registro y queda escrito en la fila del usuario (`users.origen`). El panel de
// /admin cuenta los registros por código.
//
// Reglas:
//   · MANDA EL PRIMERO. Quien entró por el post del lunes y volvió el jueves
//     por otro, se cuenta para el del lunes: ése es el que lo trajo.
//   · VENCE A LOS 30 DÍAS. Pasado ese tiempo el primer contacto ya no explica
//     nada, y un código nuevo lo reemplaza.
//   · `d` le gana a los `utm_*` si vienen los dos: es el nuestro.
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

/** El código limpio: minúsculas, sólo letras, números, `-` `_` `.` `/`. null si no queda nada. */
export function normalizarCodigo(valor) {
  if (valor == null) return null
  const limpio = String(valor).trim().toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9._/-]/g, '')
    .slice(0, LARGO_MAX)
  return limpio || null
}

/** El código que trae una dirección (`?d=` o `utm_*`), o null. */
export function codigoDeLaDireccion(search) {
  let params
  try { params = new URLSearchParams(search || '') } catch { return null }
  const d = normalizarCodigo(params.get('d'))
  if (d) return d
  const fuente = normalizarCodigo(params.get('utm_source'))
  const campana = normalizarCodigo(params.get('utm_campaign'))
  if (fuente && campana) return normalizarCodigo(`${fuente}/${campana}`)
  return fuente || campana || null
}

function leerGuardado() {
  try {
    const raw = localStorage.getItem(ORIGEN_KEY)
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
 * Al abrir la página: si la dirección trae un código y no hay uno vigente
 * guardado, se guarda. Después se saca `d` de la dirección. Nunca tira: el
 * navegador puede tener el almacenamiento bloqueado.
 */
export function anotarOrigen(ahora = Date.now()) {
  if (typeof window === 'undefined') return null
  let codigo = null
  try { codigo = codigoDeLaDireccion(window.location.search) } catch { return null }
  if (codigo) {
    try {
      const previo = leerGuardado()
      if (!previo || vencido(previo, ahora)) {
        localStorage.setItem(ORIGEN_KEY, JSON.stringify({
          codigo,
          visto: new Date(ahora).toISOString(),
          pagina: window.location.pathname || '/',
        }))
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
  try { localStorage.removeItem(ORIGEN_KEY) } catch { /* nada */ }
}
