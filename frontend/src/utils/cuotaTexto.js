// cuotaTexto — cómo se le cuenta al usuario lo que le queda de Rendi AI.
// ═══════════════════════════════════════════════════════════════════════════
// Existe porque el mismo dato se muestra en tres lugares (el contador chico del
// encabezado, el pie del chat y el globo de ayuda del parlante) y tres textos
// escritos a mano se contradicen solos en cuanto uno cambia.
//
// LO QUE ESTO TIENE QUE DEJAR CLARO, porque hasta ahora no se veía:
//   · En Free, escuchar NO sale de las consultas: tiene un cupo propio de 1.
//     Antes el contador decía "1 consulta restante" y del escuche no decía
//     nada — el usuario se enteraba de que existía justo cuando se le acababa.
//   · En Plus y Pro sí sale de las consultas: una respuesta hablada gasta DOS,
//     la pregunta y la escucha. Antes veías bajar el contador de a dos sin
//     ninguna explicación.
//
// Cómo se distingue un caso del otro: `listens_limit`. Si viene un número, ese
// plan tiene cupo propio de escuchas (hoy sólo Free). Si viene null, paga con
// consultas. Es el mismo criterio que usa el backend (ai/quota.py).

const plural = (n, singular, plural_) => `${n} ${n === 1 ? singular : plural_}`

/** ¿Este plan tiene cupo PROPIO de escuchas, o las paga con consultas? */
export function tieneCupoDeEscuchas(usage) {
  return !!usage && usage.listens_limit != null
}

/**
 * Lo que le queda, en una línea. Es el texto del pie del chat.
 * Devuelve null cuando no hay cuota que mostrar (admin, o usage sin cargar).
 */
export function restantesTexto(usage) {
  if (!usage || !(usage.chat_limit > 0)) return null
  const consultas = Math.max(0, usage.chat_limit - usage.chat_count)
  if (!tieneCupoDeEscuchas(usage)) {
    return `${plural(consultas, 'consulta restante', 'consultas restantes')} · escucharla gasta 1 más`
  }
  const escuchas = usage.listens_remaining != null
    ? usage.listens_remaining
    : Math.max(0, usage.listens_limit - (usage.listen_count || 0))
  if (consultas === 0 && escuchas === 0) return 'Sin consultas ni escuchas esta semana'
  return `${plural(consultas, 'consulta', 'consultas')} y ${plural(escuchas, 'escucha', 'escuchas')} esta semana`
}

/** La versión corta, para el contador del encabezado. */
export function contadorCorto(usage) {
  if (!usage || !(usage.chat_limit > 0)) return null
  const base = `${usage.chat_count}/${usage.chat_limit} esta semana`
  if (!tieneCupoDeEscuchas(usage)) return base
  return `${usage.chat_count}/${usage.chat_limit} · ${usage.listen_count || 0}/${usage.listens_limit} 🔊`
}

/** Qué cuesta escuchar, para el globo de ayuda del parlante. */
export function costoDeEscuchar(usage) {
  if (!usage) return 'Rendi te lee la respuesta en voz alta.'
  if (tieneCupoDeEscuchas(usage)) {
    const escuchas = usage.listens_remaining != null
      ? usage.listens_remaining
      : Math.max(0, usage.listens_limit - (usage.listen_count || 0))
    return `Rendi te lee la respuesta en voz alta. Tenés ${plural(escuchas, 'escucha', 'escuchas')} `
      + 'por semana, aparte de tus consultas. Volver a oír una que ya escuchaste es gratis.'
  }
  return 'Rendi te lee la respuesta en voz alta. Escuchar gasta 1 consulta más, '
    + 'así que una respuesta hablada te sale 2. Volver a oír una que ya escuchaste es gratis.'
}

// ─── El aviso de "se te está acabando" ───────────────────────────────────────
// Aparece SOLO cuando queda poco: mostrarlo siempre lo convierte en decorado y
// deja de leerse. Umbral: 2 consultas, salvo en Free —que tiene UNA— donde
// avisar "te queda 1" sería avisar desde el minuto cero; ahí sólo cuando se
// acabó.
//
// El atajo a Planes va sólo si hay adónde ir: sobre Pro no hay plan retail más
// arriba, así que a un Pro sin consultas se le dice cuándo se le renuevan y
// nada más. Ofrecerle "mejorá tu plan" al que ya está en el techo es ruido.
const CON_ADONDE_IR = new Set(['free', 'plus'])

export function avisoDeCuota(usage) {
  if (!usage || !(usage.chat_limit > 0)) return null
  const consultas = Math.max(0, usage.chat_limit - usage.chat_count)
  const umbral = usage.chat_limit === 1 ? 0 : 2
  if (consultas > umbral) return null

  const cuando = usage.resets_on ? ` Se renuevan el ${usage.resets_on}.` : ''
  const cta = CON_ADONDE_IR.has(usage.tier)

  if (consultas === 0) {
    // En Free el escuche es un cupo aparte: puede quedarle uno aunque no le
    // queden consultas, y decir "te quedaste sin nada" sería falso.
    const escuchas = tieneCupoDeEscuchas(usage)
      ? (usage.listens_remaining != null
          ? usage.listens_remaining
          : Math.max(0, usage.listens_limit - (usage.listen_count || 0)))
      : 0
    const extra = escuchas > 0 ? ` Todavía te queda ${plural(escuchas, 'escucha', 'escuchas')}.` : ''
    return { agotado: true, cta, texto: `Te quedaste sin consultas por esta semana.${cuando}${extra}` }
  }
  const frase = consultas === 1 ? 'Te queda 1 consulta' : `Te quedan ${consultas} consultas`
  return { agotado: false, cta, texto: `${frase} esta semana.${cuando}` }
}
