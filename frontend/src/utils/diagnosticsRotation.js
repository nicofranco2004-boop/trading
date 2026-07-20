// Lógica PURA de la grilla 3×3 de diagnósticos (Análisis › Diagnóstico).
//
// Cada tier (Atención / Diagnóstico / Positivo) muestra hasta 3 tiles. El user
// puede tocar "No me interesa" en UNA tile: esa —y sólo esa— se reemplaza por
// otro candidato del mismo tier; las otras dos quedan EXACTAMENTE en su lugar
// (identidad de slot estable). Al agotar el tier, cicla (vuelve a la primera).
//
// Se extrajo de Insights.jsx para poder testear el algoritmo — es sutil: el bug
// original era que `pool.filter(!dismissed).slice(0,3)` corría toda la ventana
// al descartar el slot 0 y cambiaban las 3 tiles.

/**
 * resolveTierShown — ids VISIBLES de un tier, hasta min(3, N).
 *
 * Prioridad: (1) slots guardados que sigan en el pool → identidad estable;
 * (2) candidatos NO descartados que no estén ya; (3) si aún faltan (todo el
 * resto descartado), cualquiera del pool → vista ciclada. Determinística: se
 * usa igual en el render y en el handler de dismiss.
 *
 * @param {Array<{id:string}>} pool     candidatos del tier, en orden.
 * @param {string[]}           poolIds  == pool.map(d=>d.id) (precomputado).
 * @param {string[]|undefined} savedIds ids visibles persistidas (slots).
 * @param {Set<string>}        dismissed skip-list del "no me interesa".
 * @returns {string[]} ids visibles (largo == min(3, pool.length)).
 */
export function resolveTierShown(pool, poolIds, savedIds, dismissed) {
  const need = Math.min(3, poolIds.length)
  const poolSet = new Set(poolIds)
  // Array.isArray, no `|| []`: tolera storage corrupto/manual (ej. slots[tier]
  // = "C1" string) sin tirar '.filter is not a function' en pleno render.
  const result = (Array.isArray(savedIds) ? savedIds : []).filter(id => poolSet.has(id))
  const has = new Set(result)
  for (const d of pool) {
    if (result.length >= need) break
    if (!has.has(d.id) && !dismissed.has(d.id)) { result.push(d.id); has.add(d.id) }
  }
  // Fallback ciclado: si todo el resto está descartado, rellenamos con lo que
  // haya para NO dejar la fila con menos de min(3,N) tiles.
  for (const id of poolIds) {
    if (result.length >= need) break
    if (!has.has(id)) { result.push(id); has.add(id) }
  }
  return result.slice(0, need)
}

/**
 * computeDismiss — descarta `id` y lo reemplaza EN SU LUGAR.
 *
 * El reemplazo es el 1er candidato del pool que no esté ya visible ni
 * descartado. Si el tier se agotó (no queda ninguno), ciclamos: limpiamos las
 * ids descartadas de ESE tier y traemos el 1º que no esté visible — los otros
 * dos slots quedan intactos.
 *
 * @returns {{nextShown:string[], nextDismissed:Set<string>}} referencias nuevas
 *   salvo en el no-op (`id` no visible), donde devuelve las mismas → el caller
 *   puede cortar el re-render por identidad.
 */
export function computeDismiss(pool, poolIds, current, id, dismissed) {
  if (!current.includes(id)) return { nextShown: current, nextDismissed: dismissed }
  const currentSet = new Set(current)
  const nextDismissed = new Set(dismissed)
  nextDismissed.add(id)
  let repl = pool.find(d => !currentSet.has(d.id) && !nextDismissed.has(d.id))?.id
  if (!repl) {
    poolIds.forEach(pid => nextDismissed.delete(pid))
    repl = pool.find(d => !currentSet.has(d.id))?.id
  }
  const nextShown = repl ? current.map(vid => (vid === id ? repl : vid)) : current
  return { nextShown, nextDismissed }
}
