// prueba — la prueba gratis y lo que pasa cuando se termina, EN PALABRAS.
// ════════════════════════════════════════════════════════════════════════════
// Desde el 22/09/2026 quien se registra NO tiene plan gratis: arranca una
// prueba de TRIAL_TOTAL_DAYS días sin tarjeta y, al terminar, elige Plus o Pro.
// Si no elige, la cuenta queda EN PAUSA (`MuroElegirPlan.jsx`) con los datos
// intactos. El plan Free sigue existiendo, pero sólo para las cuentas que ya lo
// tenían (`user.requires_plan` en falso).
//
// Por qué existe este archivo: el cambio se hizo en la home y quedaron más de
// quince textos contando el modelo anterior — la FAQ ("el plan Free es gratis
// para siempre"), seis landings de SEO ("el plan Free te alcanza"), la guía,
// /planes, Configuración y los textos legales. Ninguno daba error: le ofrecían
// a la persona un plan que la app no le iba a dar. Las frases de acá son la
// única copia; los días salen de `planCatalog.js`, y ésos los compara contra el
// backend `backend/tests/test_promesas_vs_producto.py`.
import { TRIAL_TOTAL_DAYS, TRIAL_PRO_DAYS, TRIAL_PLUS_DAYS } from './planCatalog'

/** El botón de las páginas públicas. El mismo texto que el de la home. */
export const CTA_PRUEBA = `Probar ${TRIAL_TOTAL_DAYS} días gratis`

/** La prueba en una oración, para quien todavía no se registró. */
export const PRUEBA_EN_UNA_LINEA =
  `Sin tarjeta: ${TRIAL_PRO_DAYS} días con Pro y ${TRIAL_PLUS_DAYS} con Plus. `
  + 'Después elegís el plan que te sirve.'

/** El paso 1 de "Cómo funciona" en las landings de SEO. Estaba copiado en las
 *  seis, y las seis decían que el plan Free alcanzaba para empezar. */
export const PASO_CREAR_CUENTA = {
  title: `Creá tu cuenta y probá ${TRIAL_TOTAL_DAYS} días gratis`,
  desc: PRUEBA_EN_UNA_LINEA,
}

/** Un cupo de un plan (`'Chat Rendi AI / sem'`, `'Brokers'`…) tal como lo
 *  publica el catálogo, que `test_promesas_vs_producto.py` compara contra el
 *  límite que aplica el backend. Para que un texto diga "9 consultas" sin
 *  escribir el 9: escrito a mano, se queda viejo el día que cambia el cupo. */
export function cupoDe(plan, etiqueta) {
  return plan?.quotas?.find(q => q.label === etiqueta)?.value
}

/** Qué le pasa a la cuenta cuando se le termina lo que tenía: la prueba, un
 *  plan cancelado o un regalo. Depende de UNA sola cosa, `user.requires_plan`:
 *    · nació sin plan gratis → no hay Free al que volver: queda en pausa;
 *    · ya existía            → vuelve a Free, como siempre.
 *  Va en minúscula para poder ir en medio de una oración. La misma regla, del
 *  lado de los mails, es `_al_terminar` en `backend/billing/emails.py`. */
export function alTerminar(requierePlan) {
  return requierePlan
    ? 'tu cuenta queda en pausa hasta que elijas un plan'
    : 'tu cuenta vuelve a Free'
}

/** ¿Esta persona conserva el plan Free? Sólo a ella se le muestra la tarjeta de
 *  Free en /planes, porque es la única que lo tiene (o vuelve a él al cancelar):
 *    · sin sesión    → es un visitante: si se registra, arranca la prueba;
 *    · demo          → también es un visitante, mirando;
 *    · requires_plan → se registró con la prueba y no tiene Free.
 *  La tarjeta "Free · Gratis · Para siempre" se le mostraba a todos, y como sin
 *  sesión el plan cae a 'free' por defecto (`usePlanFeatures`), al visitante se
 *  la marcaba encima como "Tu plan actual". A la cuenta en pausa, igual: el muro
 *  la manda justo a /planes para pagar. */
export function conservaElFree(user) {
  return !!user && !user.demo && !user.requires_plan
}
