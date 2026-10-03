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
import { useVoz, esRecienLlegada } from '../../../contexts/VozContext'

/** El tono que trae el bloque estructurado de la respuesta → la reacción. */
export const REACCION_POR_TONO = { pos: 'contento', warn: 'atento', neg: 'serio' }
/** Cuánto dura la reacción antes de volver a reposo (ms). */
export const DURACION_REACCION = { contento: 3200, atento: 4200, serio: 4200 }

/**
 * @returns {{ estado: string, tono: 'pos'|'warn'|'neg'|null }}
 *
 * El orden importa, de más fuerte a más débil:
 *   1. Sin consultas → durmiendo. Gana a todo: no hay nada más que pueda pasar.
 *   2. Esperando la primera letra (o datos a mitad de respuesta) → pensando.
 *   3. El texto está llegando → hablando.
 *   4. La respuesta recién terminó con tono → reacción (con el color del tono
 *      en el monitor: es el único momento en que dice un número con signo).
 *   5. La voz la está leyendo en voz alta → hablando.
 *   6. La pregunta falló → confundido.
 *   7. Nada de lo anterior → reposo.
 */
export function estadoDelChat({ sending, loading, status, askError, upgradeInfo, sinCupo, reaccion } = {}) {
  if (upgradeInfo || sinCupo) return { estado: 'durmiendo', tono: null }
  if (sending && loading) return { estado: 'pensando', tono: null }
  if (sending) return { estado: 'hablando', tono: null }
  if (reaccion && REACCION_POR_TONO[reaccion.tono]) return { estado: REACCION_POR_TONO[reaccion.tono], tono: reaccion.tono }
  if (status === 'playing') return { estado: 'hablando', tono: null }
  if (askError) return { estado: 'confundido', tono: null }
  return { estado: 'reposo', tono: null }
}

/** El último mensaje de Mervall-E en la conversación, o null. */
export function ultimaRespuesta(thread) {
  if (!thread?.length) return null
  for (let i = thread.length - 1; i >= 0; i--) if (thread[i]?.role === 'assistant') return thread[i]
  return null
}

/**
 * El estado del personaje, en vivo. Lo usan la cabecera de /ai y la isla.
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
    if (!llego || !REACCION_POR_TONO[tono] || !esRecienLlegada({ llego })) return undefined
    setReaccion({ tono, llego })
    const id = setTimeout(() => setReaccion(null), DURACION_REACCION[REACCION_POR_TONO[tono]])
    return () => clearTimeout(id)
  }, [llego, tono])

  return estadoDelChat({ ...voz, reaccion })
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

/** true durante los 2,6 s del saludo, una sola vez por día. */
export function useSaludoDelDia() {
  const [saludando, setSaludando] = useState(false)
  useEffect(() => {
    if (!tocaSaludar()) return undefined
    setSaludando(true)
    const id = setTimeout(() => setSaludando(false), 2600)
    return () => clearTimeout(id)
  }, [])
  return saludando
}
