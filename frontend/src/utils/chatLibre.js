// ¿Puede escribirle preguntas LIBRES a Rendi AI? Pro, admin y el asesor en su
// propio nivel (modo libro: chatea sobre el libro). Plus elige entre las
// preguntas sugeridas: el servidor rebota el resto con "el chat libre es sólo
// Pro". UNA regla para la pantalla de Rendi AI (AICoach) y el buscador ⌘K
// (BuscadorRapido), que si no ofrecería mandar una pregunta que va a rebotar.
export function puedeChatLibre({ isPro, isAdmin, user, clientCtx } = {}) {
  const modoLibro = user?.tier === 'advisor' && !clientCtx
  return !!(isPro || isAdmin || modoLibro)
}
