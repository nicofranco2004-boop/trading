// planes — qué plan destraba lo que un tope deja afuera.
// ════════════════════════════════════════════════════════════════════════════
// Los topes vienen de `/api/plan/features` → `features.planes` (los planes en
// venta, del más barato al más caro), que el backend lee de `ai/plan.py`.
// Nada de acá tiene un número de plan escrito. (Cuántos ítems se VEN con un
// tope lo dice `utils/detectoresVisibles.js`.)
//
// Por qué existe: la pantalla de Comportamiento tenía `PLUS_VISIBLE_COUNT = 6`
// escrito a mano para decidir si una carta bloqueada decía "Plus" o "Pro". El
// 15/10 el Plus pasa a ver los 12 detectores, y ese 6 le iba a decir "Pro" a un
// Free en cartas que el Plus ya muestra: le vendía el plan caro por algo que
// trae el barato.

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
