// preciosEnVivo — qué dice el cartel de los precios ("● Precios de hace 40 s ·
// se actualizan solos") y cuándo late su punto.
//
// El punto late SÓLO si el último refresco trajo al menos un precio distinto
// del anterior: es la prueba de que los números se están moviendo ahora. Con
// el mercado cerrado los refrescos traen lo mismo y el punto queda quieto —
// mismo principio que EnVivo de las secciones de mercado y que PuntaViva del
// gráfico: un punto que late al lado de un número quieto miente.
//
// Hasta el 2026-10-01 el encabezado de Cartera y del Dashboard decía
// "Precios · 14:32" con el punto latiendo SIEMPRE (PageHeader lo prendía con
// sólo ver la palabra "precios"), y el Dashboard ni siquiera vuelve a pedir
// precios: el punto latía al lado de un dato de cuando se abrió la pantalla.

// ¿Cuántos símbolos cambiaron de precio entre dos respuestas de /prices?
// `__meta` es la procedencia, no un precio. Un símbolo que aparece o
// desaparece no cuenta como movimiento: es la lista que cambió, no el mercado.
export function preciosQueCambiaron(antes, despues) {
  if (!antes || !despues) return 0
  let n = 0
  for (const [sym, v] of Object.entries(despues)) {
    if (sym === '__meta') continue
    const a = antes[sym]
    if (typeof v !== 'number' || typeof a !== 'number') continue
    if (Number.isFinite(v) && Number.isFinite(a) && v !== a) n++
  }
  return n
}

// ¿La respuesta de /prices trajo al menos un precio? Si vino vacía (proveedor
// caído), el cartel no puede decir "Precios de hace 3 s": no hay precios.
export function hayPrecios(data) {
  if (!data) return false
  return Object.entries(data).some(([sym, v]) => sym !== '__meta' && typeof v === 'number' && Number.isFinite(v))
}

// "hace 40 s" / "hace 3 min" / "hace 2 h". Con segundos por debajo del minuto:
// el cartel promete "en vivo" y un "ahora" quieto durante 59 s no lo parece.
export function haceDesde(desde, ahora = Date.now()) {
  if (!desde) return ''
  const t = desde instanceof Date ? desde.getTime() : new Date(desde).getTime()
  if (!Number.isFinite(t)) return ''
  const s = Math.max(0, Math.floor((ahora - t) / 1000))
  if (s < 60) return `hace ${s} s`
  const min = Math.floor(s / 60)
  if (min < 60) return `hace ${min} min`
  return `hace ${Math.floor(min / 60)} h`
}

// Cada cuánto se reescribe el "hace…": cada segundo mientras dice segundos,
// cada 15 s cuando ya dice minutos u horas.
export function proximoTic(desde, ahora = Date.now()) {
  const t = desde instanceof Date ? desde.getTime() : new Date(desde ?? NaN).getTime()
  if (!Number.isFinite(t)) return 1000
  return ahora - t < 60_000 ? 1000 : 15_000
}

// El texto entero del cartel. `seActualizanSolos` es una promesa: sólo va en
// la pantalla que de verdad vuelve a pedir los precios (Cartera, cada 90 s con
// la pestaña a la vista). El Dashboard los pide una vez y no la hace.
export function textoPreciosEnVivo({ actualizado, actualizando = false, seActualizanSolos = false }, ahora = Date.now()) {
  if (actualizando && !actualizado) return 'Buscando precios…'
  const hace = haceDesde(actualizado, ahora)
  if (!hace) return ''
  return `Precios de ${hace}${seActualizanSolos ? ' · se actualizan solos' : ''}`
}
