// detectoresVisibles — cuántos detectores de Comportamiento ve la cuenta.
// ════════════════════════════════════════════════════════════════════════════
// Lo decide UN dato: `limits.behavioral_tags_visible` de /api/plan/features,
// que sale de `PLAN_LIMITS` en `backend/ai/plan.py` — la misma tabla que usan
// los mails y el catálogo para decir cuántos detectores trae cada plan.
//
// ⚠️ POR QUÉ NO SE DECIDE POR EL NOMBRE DEL PLAN. La pantalla usaba
// `hasFullAccess` (tier === 'pro' || 'advisor' || 'admin') para mostrar todas
// las cartas, y el número sólo para los demás. El 2026-10-15 (`git revert
// 78f43739`) el Plus pasa a ver los 12: la tabla dice "sin tope" (`null`)
// pero Plus no es 'pro', así que caía en la rama con tope y `null || 1` le
// mostraba UNA carta — justo al plan cuya promesa nueva es "Rendi entero".
//
//   · `null`      → sin tope: todas (Infinity);
//   · un número   → ese número (0 cuenta como 1, como antes);
//   · `undefined` → todavía no llegaron los features: 1, fail-closed (un Free
//                   no ve por un instante lo que no le toca).
export function detectoresVisibles(tope) {
  if (tope === null) return Infinity
  return tope || 1
}
