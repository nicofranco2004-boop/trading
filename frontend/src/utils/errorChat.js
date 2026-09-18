// errorChat — traducir un error del chat a algo que se pueda leer.
// ═══════════════════════════════════════════════════════════════════════════
// El backend devuelve el detalle de tres formas distintas, y una de ellas es
// un array de Pydantic que crudo en pantalla es JSON técnico. Esto lo traduce.
//
// Vive acá y no adentro de un componente porque la conversación con Rendi se
// ve en DOS lugares —el chat grande de /ai y la isla flotante— y hasta ahora
// cada uno traducía por su cuenta: el grande tenía las cinco variantes y la
// isla tenía un "no pudimos completar la consulta" para todo. El mismo 429 de
// cuota mostraba la card de upgrade en una pantalla y un cartel rojo genérico
// en la otra.
//
// Es una función pura: se prueba sin React.

/**
 * @returns {{ mensaje: string, usage?: object, upgrade?: object }}
 *   mensaje — lo que ve el usuario.
 *   usage   — la cuota que vino en el error, si vino (para refrescar el pie).
 *   upgrade — el payload de "pasate a Pro", sólo si el backend lo marcó
 *             available. Con esto la UI dibuja la card promocional en vez del
 *             cartel rojo.
 */
export function traducirErrorDeChat(e) {
  const out = { mensaje: 'No pudimos completar la consulta. Intentalo nuevamente.' }
  if (!e) return out

  // El wrapper de api.js guarda el detalle crudo del backend acá.
  const detail = e?.payload?.detail ?? e?.detail ?? e?.response?.data?.detail
  const status = e?.status

  if (e.truncated) {
    // El stream se cortó sin frame de cierre (Vercel a los 30s, red móvil).
    // Antes esto se mostraba como respuesta COMPLETA y el usuario leía media
    // respuesta creyendo que era toda.
    out.mensaje = 'La respuesta se cortó a mitad de camino. Volvé a intentarlo — si pasa seguido, probá una pregunta más corta.'
    return out
  }
  if (!detail && (status === 504 || status === 502 || status === 503 || e?.payload === null)) {
    // Sin detalle y con estos códigos suele ser el proxy cortando por tiempo:
    // devuelve HTML, no JSON, así que no hay nada que leer.
    out.mensaje = 'El bot tardó más de lo normal en responder. Intentá una pregunta más simple, o esperá unos segundos y reintentá.'
    return out
  }
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) {
    // Error armado por nosotros: gate de plan, cuota agotada.
    out.mensaje = detail.message
    if (detail.usage) out.usage = detail.usage
    if (detail.upgrade && detail.upgrade.available) out.upgrade = detail.upgrade
    // Qué cupo se agotó ('analyses' | 'chat'). Sin esto la tarjeta lo adivinaba
    // mal: ver kindDeCuota() en UpgradePromoCard.jsx.
    if (detail.kind) out.kind = detail.kind
    // 🔴 Y POR QUÉ se frenó, que NO siempre es la cuota.
    //
    // 'free_chat_not_allowed' (403) no es quedarse sin cupo: es que la pregunta
    // libre no está en el plan. La tarjeta de upgrade pisa el mensaje de error,
    // así que sin este código mostraba "Llegaste al límite · Usaste 0 de 1
    // consultas" — un contador que no frenó nada, y encima escondía el texto
    // que SÍ servía ("elegí una guiada, o registrá una operación").
    if (detail.error) out.codigo = detail.error
    return out
  }
  if (Array.isArray(detail) && detail.length > 0) {
    // Array de validación de Pydantic. Nunca se muestra crudo — se infiere qué
    // pasó y se dice en castellano.
    const tipo = String(detail[0]?.type || '').toLowerCase()
    out.mensaje = (tipo === 'string_too_long' || tipo.includes('too_long'))
      ? 'La conversación se hizo muy larga. Tocá "Nuevo" para empezar de cero y volvé a preguntar.'
      : 'El mensaje no pasó la validación del servidor. Tocá "Nuevo" para refrescar el chat.'
    return out
  }
  if (typeof detail === 'string') {
    out.mensaje = detail
    return out
  }
  return out
}

/** ¿Este error es el usuario cancelando (tocó "Nuevo")? No se muestra nada. */
export function esCancelacion(e) {
  return e?.name === 'AbortError'
}
