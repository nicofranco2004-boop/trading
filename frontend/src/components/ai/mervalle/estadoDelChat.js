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
  if (!upgradeInfo) return false
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
  const [reaccion, setReaccion] = useState(null)

  useEffect(() => {
    const resto = restoDeReaccion(tono, llego)
    if (!resto) return undefined
    setReaccion({ tono, llego })
    const id = setTimeout(() => setReaccion(null), resto)
    return () => clearTimeout(id)
  }, [llego, tono])

  // La reacción vale SÓLO mientras siga siendo la de la última respuesta. Si
  // en esos segundos llega otra (sin tono) o se vacía el chat, el efecto de
  // arriba cancela el temporizador y nadie apagaba la cara: quedaba contento
  // para siempre, con el pecho en verde (auditoría 2026-10-04).
  const vigente = reaccion && reaccion.llego === llego ? reaccion : null
  return estadoDelChat({ ...voz, reaccion: vigente })
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
