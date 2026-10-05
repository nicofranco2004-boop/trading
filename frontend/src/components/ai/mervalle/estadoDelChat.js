// Qué cara pone Mervall-E según lo que está pasando en la conversación.
// ═══════════════════════════════════════════════════════════════════════════
// La conversación vive en VozContext (la misma para /ai y para la isla). Acá
// se traduce ese estado a uno de los estados del personaje. Es una función
// pura a propósito: el orden de las reglas ES la decisión de producto, y se
// prueba sin montar nada (estadoDelChat.test.js).
//
// "Escuchando" no está acá: tipear y el micrófono son eventos de cada tecla y
// llegan al motor directo (avisarTipeo / avisarMicrofono), sin pasar por React.

import { useEffect, useState } from 'react'
import { useVoz } from '../../../contexts/VozContext'
import { kindDeCuota } from '../UpgradePromoCard'

/** El tono que trae el bloque estructurado de la respuesta → la reacción. */
export const REACCION_POR_TONO = { pos: 'contento', warn: 'atento', neg: 'serio' }
/** Cuánto dura la reacción antes de volver a reposo (ms). */
export const DURACION_REACCION = { contento: 3200, atento: 4200, serio: 4200 }

/**
 * ¿Se le acabaron las consultas de CHAT? Es lo único que lo duerme.
 *
 * La tarjeta de "pasate de plan" (`upgradeInfo`) sale por tres cosas
 * distintas, y sólo una es esa (auditoría 2026-10-04):
 *   · `free_chat_not_allowed`: un Free escribió una pregunta libre. No se
 *     llenó ningún contador: le queda elegir una guiada, y dormirse arriba de
 *     las guiadas le decía lo contrario.
 *   · cuota de ANÁLISIS (los ✦): el chat sigue andando.
 *   · cuota de CHAT: ésta sí.
 * `sinCupo` NO entra: es el cupo de ESCUCHAR respuestas en voz alta. Un Free
 * que ya usó su audio de la semana sigue preguntando por escrito; y como ese
 * aviso sólo se apaga al pedir otro audio, dormía al personaje en todas las
 * respuestas siguientes hasta recargar.
 */
export function sinConsultasDeChat({ upgradeInfo, codigoDelError, kindDeCuotaDelError, usageDelError } = {}) {
  // El 429 de cuota trae `chat_quota_exceeded`, pero la tarjeta de "pasate de
  // plan" sólo se le ofrece a Free y Plus: un Pro o un asesor sin consultas
  // llega sin `upgradeInfo` y antes se quedaba con cara de confundido.
  if (!upgradeInfo && codigoDelError !== 'chat_quota_exceeded') return false
  if (codigoDelError === 'free_chat_not_allowed') return false
  return kindDeCuota(usageDelError, kindDeCuotaDelError) === 'chat'
}

/**
 * @returns {{ estado: string, tono: 'pos'|'warn'|'neg'|null }}
 *
 * El orden importa, de más fuerte a más débil:
 *   1. Esperando la primera letra (o datos a mitad de respuesta) → pensando.
 *   2. El texto está llegando → hablando. Si está contestando, eso es lo que
 *      pasa: le gana a cualquier cartel que haya quedado de antes.
 *   3. La respuesta recién terminó con tono → reacción (con el color del tono
 *      en el monitor: es el único momento en que dice un número con signo).
 *   4. La voz la está leyendo en voz alta → hablando (aunque no le queden
 *      consultas: re-escuchar el último audio es gratis, y la isla dice
 *      "está hablando").
 *   5. Sin consultas de chat → durmiendo.
 *   6. La pregunta falló → confundido.
 *   7. Nada de lo anterior → reposo.
 */
export function estadoDelChat(voz = {}) {
  const { sending, loading, status, askError, reaccion } = voz
  if (sending && loading) return { estado: 'pensando', tono: null }
  if (sending) return { estado: 'hablando', tono: null }
  if (reaccion && REACCION_POR_TONO[reaccion.tono]) return { estado: REACCION_POR_TONO[reaccion.tono], tono: reaccion.tono }
  if (status === 'playing') return { estado: 'hablando', tono: null }
  if (sinConsultasDeChat(voz)) return { estado: 'durmiendo', tono: null }
  if (askError) return { estado: 'confundido', tono: null }
  return { estado: 'reposo', tono: null }
}

/** La reacción de la última respuesta, si todavía le queda tiempo; si no, null.
 *  Es una cuenta, no un estado guardado: no hay nada que "apagar". La versión
 *  con estado guardado se quedaba pegada dos veces (auditorías 1 y 2 del
 *  2026-10-04): si llegaba otra respuesta en esos segundos, o si la nueva se
 *  cortaba y volvía a quedar como última la anterior, nadie la apagaba. */
export function reaccionVigente(tono, llego, ahora = Date.now()) {
  return restoDeReaccion(tono, llego, ahora) > 0 ? { tono, llego } : null
}

/** Cuánto le queda a la reacción de una respuesta que llegó en `llego` (ms,
 *  0 si ya pasó). Se cuenta desde que LLEGÓ, no desde que se montó la
 *  pantalla: volver a /ai a los 3 s no la repite entera. */
export function restoDeReaccion(tono, llego, ahora = Date.now()) {
  const estado = REACCION_POR_TONO[tono]
  if (!estado || !llego) return 0
  return Math.max(0, DURACION_REACCION[estado] - (ahora - llego))
}

/** El último mensaje de Mervall-E en la conversación, o null. */
export function ultimaRespuesta(thread) {
  if (!thread?.length) return null
  for (let i = thread.length - 1; i >= 0; i--) if (thread[i]?.role === 'assistant') return thread[i]
  return null
}

/**
 * El estado del personaje, en vivo. Lo usan la cabecera de /ai, la portada,
 * el que acompaña al cuadro de texto y la isla.
 * La reacción dura unos segundos y se apaga sola; sólo arranca con una
 * respuesta que ACABA de llegar (una conversación que se reabre no reacciona).
 */
export function useEstadoMervallE() {
  const voz = useVoz()
  const ultima = ultimaRespuesta(voz.thread)
  const llego = ultima?.llego || null
  const tono = ultima?.meta?.tone || null
  // La reacción se CALCULA en cada render (reaccionVigente). El temporizador
  // sólo pide un render más cuando se le acaba el tiempo.
  const [, otraVuelta] = useState(0)
  const reaccion = reaccionVigente(tono, llego)

  useEffect(() => {
    const resto = restoDeReaccion(tono, llego)
    if (!resto) return undefined
    const id = setTimeout(() => otraVuelta((n) => n + 1), resto + 20)
    return () => clearTimeout(id)
  }, [llego, tono])

  return estadoDelChat({ ...voz, reaccion })
}

/* ── Quién está en escena ────────────────────────────────────────────────
   Uno solo se mueve por pantalla en /ai. La regla vive ACÁ y la leen las
   dos pantallas que la necesitan (AICoach y RendiAI): estaba copiada en las
   dos, igual hoy pero libre de separarse mañana. */

/** Desde este ancho hay lugar para el compañero al costado del cuadro de
 *  texto. Más angosto (tablet con la barra lateral abierta) le comía el
 *  cuadro: a 768 px quedaban 320 px para escribir. */
export const ANCHO_COMPANERO = 1024

/**
 * @returns {'portada'|'companero'|'cabecera'} quién sigue el chat:
 *   · chat vacío → la portada;
 *   · con conversación y lugar al costado → el compañero del cuadro de texto;
 *   · con conversación y sin lugar (celular, tablet) → la cabecera.
 */
export function enEscena({ hayConversacion, hayLugarAlCostado }) {
  if (!hayConversacion) return 'portada'
  return hayLugarAlCostado ? 'companero' : 'cabecera'
}

/** Mientras espera, "pensando" lo dice el visor barriendo de la burbuja de la
 *  espera: quien la acompañe (la cabecera, la de la isla) queda en reposo, así
 *  no hay dos caras animándose a la vez. */
export function sinPensando(estado) {
  return estado === 'pensando' ? 'reposo' : estado
}

/**
 * Qué Mervall-E entra en la portada del chat vacío, según el alto que le
 * queda a esa zona (es lo único que se achica: las preguntas sugeridas y el
 * cuadro de texto no ceden). El título y la explicación ocupan ~120 px.
 * Si no entra ni la cabeza, no va: un personaje rebanado se ve peor que
 * ninguno, y la cabecera de /ai ya tiene su cara.
 * En celular se prefiere el CUERPO (grande si entra, uno más chico si no) antes
 * que la cabeza sola: medido el 2026-10-05, a un Pro Max o un Android grande le
 * sobran 170-210 px (cuerpo entero), a un iPhone 14 75-84 px (cuerpo chico), y
 * a un iPhone SE o con las barras de Safari abiertas, nada. Antes iba "como
 * mucho la cabeza" en todos: era de cuando la portada se cortaba arriba.
 * @returns {{ forma: string, size: number } | null}
 */
export const ALTO_TEXTO_PORTADA = 120
export function formaDePortada(alto, esCelular) {
  if (!alto) return null
  const opciones = esCelular
    ? [['full', 112, 147], ['full', 56, 73], ['head', 50, 50]]
    : [['full', 112, 147], ['bust', 76, 83], ['head', 50, 50]]
  for (const [forma, size, altoDibujo] of opciones) {
    if (alto >= altoDibujo + ALTO_TEXTO_PORTADA) return { forma, size }
  }
  return null
}

const CLAVE_SALUDO = 'mervalle_saludo_dia'

/** Si todavía no saludó hoy (fecha local del dispositivo). Lo marca como saludado. */
export function tocaSaludar(hoy = new Date(), storage = (typeof localStorage !== 'undefined' ? localStorage : null)) {
  const dia = `${hoy.getFullYear()}-${hoy.getMonth() + 1}-${hoy.getDate()}`
  try {
    if (!storage || storage.getItem(CLAVE_SALUDO) === dia) return false
    storage.setItem(CLAVE_SALUDO, dia)
    return true
  } catch {
    return false
  }
}

/**
 * true durante los 2,6 s del saludo, una sola vez por día — y sólo si la
 * portada está A LA VISTA (`visible`). Antes se gastaba al montar el chat
 * aunque hubiera una conversación abierta y la portada no apareciera: después,
 * con el chat vacío, ya no saludaba.
 */
export function useSaludoDelDia(visible = true) {
  const [saludando, setSaludando] = useState(false)
  useEffect(() => {
    if (!visible) { setSaludando(false); return undefined }
    if (!tocaSaludar()) return undefined
    setSaludando(true)
    const id = setTimeout(() => setSaludando(false), 2600)
    return () => { clearTimeout(id); setSaludando(false) }
  }, [visible])
  return saludando
}
