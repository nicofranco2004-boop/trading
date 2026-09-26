// planes — qué se ve con cada tope y qué plan destraba lo que no se ve.
// ════════════════════════════════════════════════════════════════════════════
// Los topes vienen de `/api/plan/features` (`usePlanFeatures`), que los lee de
// `backend/ai/plan.py`. Nada de acá tiene un número de plan escrito.
//
// Por qué existe: la pantalla de Comportamiento tenía `PLUS_VISIBLE_COUNT = 6`
// escrito a mano para decidir si una carta bloqueada decía "Plus" o "Pro". El
// 15/10 el Plus pasa a ver los 12 detectores y ese 6 le iba a decir "Pro" a un
// Free en cartas que el Plus ya muestra. Peor: el tope "sin límite" llega como
// `null`, y `limit(...) || 1` lo leía como UNO — el Plus, pagando, iba a ver
// una sola carta y once bloqueadas.

/**
 * Cuántos ítems se muestran con un tope del plan.
 *   · `null`      → sin tope: todos. (Es como lo manda el backend.)
 *   · un número   → ese, sin pasarse del total.
 *   · `undefined` → todavía no se sabe (cargando, sin cache): uno, como antes.
 *     Mostrar de menos un instante es mejor que mostrarle todo a un Free.
 */
export function cuantosSeVen(tope, total) {
  if (tope === null) return total
  if (typeof tope === 'number' && tope > 0) return Math.min(tope, total)
  return Math.min(1, total)
}

/**
 * El plan MÁS BARATO que muestra el ítem número `indice` (0 = el primero).
 * `planes` es `features.planes`: [{ tier, limits }] del más barato al más caro,
 * como lo arma el backend (`PLANES_EN_VENTA`). Un tope `null` es sin tope.
 *
 * Devuelve null si no lo sabe (un backend o un cache del navegador de antes de
 * este cambio no traen `planes`): quien llama elige qué decir en ese caso.
 */
export function planQueDestraba(planes, tope, indice) {
  if (!Array.isArray(planes)) return null
  for (const p of planes) {
    const v = p?.limits?.[tope]
    if (v === null || (typeof v === 'number' && v > indice)) return p.tier
  }
  return null
}
