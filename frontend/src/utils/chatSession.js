// chatSession — persistencia client-side de la conversación de Mervall-E AI.
// ═══════════════════════════════════════════════════════════════════════════
// Pedido de Nico: hablar con la IA, ir al Dashboard, volver — y que el chat
// SIGA ahí. La conversación solo se borra con "Nueva conversación" (o al
// cerrar el tab: usamos sessionStorage, que sobrevive navegación SPA y F5
// pero no cruza días/tabs — un chat de la semana pasada con un snapshot
// viejo confunde más de lo que ayuda).
//
// COSTO — el punto clave: persistir NO puede encarecer el chat. El costo por
// turno lo domina el historial que viaja al modelo; por eso al LLM se le
// manda SOLO la ventana final (MAX_SENT mensajes, ver sendWindow) aunque en
// pantalla se muestre la conversación completa (cap MAX_STORED). Hoy una
// conversación de una sentada ya mandaba hasta 30 mensajes (cap Pydantic del
// backend) — con la ventana de 12 el peor caso queda IGUAL o más barato.
//
// Testeable sin React (mismo criterio que aiStructured.js).

import { isDemoMode } from './demo'
import { getClientContext } from './api'

const KEY = 'rendi_chat_v1'
// Demo con clave propia: lo que chatea un visitante demo no debe aparecer
// cuando el usuario real vuelve a loguearse en el mismo browser (ni al revés).
const DEMO_KEY = 'rendi_chat_demo_v1'

export const MAX_STORED = 40  // mensajes en pantalla/persistidos
export const MAX_SENT = 12    // ventana que viaja al modelo (cost cap)

// La clave de la conversación de la cuenta abierta AHORA.
export function claveDeConversacion() {
  if (isDemoMode()) return DEMO_KEY
  // Plan Asesor: en contexto de cliente la conversación es OTRA (la IA opera
  // sobre la cuenta del cliente) — key separada por cliente para no mezclar.
  // El cliente se pregunta a api.js, que es el que decide a qué cuenta va cada
  // pedido. Antes se leía de localStorage por separado: si esa escritura
  // fallaba, los pedidos iban a un cliente y la conversación era la de otro.
  const id = getClientContext()?.id
  return id ? `${KEY}_c${id}` : KEY
}
const storageKey = claveDeConversacion

// 🔴 DE QUIÉN ES LO GUARDADO EN ESTA PESTAÑA.
// Cerrar sesión lo borra todo (AuthContext.logout), pero hay otras formas de
// que entre otra persona en la misma pestaña sin pasar por ahí: la sesión
// vence sola (el 401 recarga la página y no borra nada), o en otra pestaña
// alguien cerró sesión y entró con su cuenta, y ésta se recarga después. En
// esos casos las conversaciones del anterior —las de sus clientes también, si
// es asesor— seguían acá y se cargaban para el que entraba. Así que queda
// anotado de quién son, y si entra otra persona se borran.
const DUENO_KEY = 'rendi_chat_dueno'
const PREFIJO = 'rendi_chat_'

/**
 * `quien` (el email) pasa a ser el dueño de las conversaciones guardadas en
 * esta pestaña; si eran de OTRA persona, antes se borran todas.
 * Devuelve true si lo guardado se puede mostrar: era suyo, o no tenía dueño
 * anotado (vacío después de un logout, o lo que dejó la versión anterior).
 *
 * `sinDuenoEsAjeno`: para cuando ENTRA alguien. Lo que esta versión guarda
 * va siempre firmado, así que algo sin dueño en ese momento sólo puede ser de
 * la versión anterior —de quien estaba antes— y se borra. Al recargar la
 * página con la misma persona no se usa: ahí lo sin dueño es suyo.
 */
export function adoptarConversaciones(quien, { sinDuenoEsAjeno = false } = {}) {
  // El demo no es nadie: tiene su clave aparte y no puede borrar lo de la
  // persona real que abrió el demo en la misma pestaña (ni al revés).
  if (isDemoMode()) return true
  let dueno
  try {
    dueno = sessionStorage.getItem(DUENO_KEY)
    if (dueno === null && sinDuenoEsAjeno) dueno = '(versión anterior)'
    if (dueno !== null && dueno !== quien) {
      const claves = []
      for (let i = 0; i < sessionStorage.length; i++) {
        const k = sessionStorage.key(i)
        if (k && k.startsWith(PREFIJO)) claves.push(k)
      }
      claves.forEach(k => sessionStorage.removeItem(k))
    }
  } catch {
    return false
  }
  try { sessionStorage.setItem(DUENO_KEY, quien) } catch { /* lleno: igual vale lo de arriba */ }
  return dueno === null || dueno === quien
}

function isValidMsg(m) {
  return m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string'
}

// Qué se guarda de cada mensaje, además del texto. Es una lista CERRADA a
// propósito: lo que no esté acá se descarta al guardar.
//
//   voz  — el resumen hablado FIRMADO. Sin esto, al volver de otra pantalla
//          los mensajes viejos pierden su botón de escuchar: el audio existe
//          en el cache del servidor pero el navegador ya no sabe pedirlo,
//          porque la firma viajaba en memoria.
//   meta — las tarjetas (stats, blocks, followups). Sin esto la conversación
//          vuelve en texto pelado y los botones de "seguí por acá" desaparecen.
//
// Cuánto pesa: 40 mensajes con tarjetas dan ~40 KB, contra los ~5 MB que
// aguanta el navegador. No es el límite que nos va a molestar.
const CAMPOS_QUE_SOBREVIVEN = ['voz', 'meta']

/** Conversación guardada (o [] si no hay / storage roto). */
export function loadChatSession() {
  try {
    const raw = sessionStorage.getItem(storageKey())
    if (!raw) return []
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return []
    return arr.filter(isValidMsg).slice(-MAX_STORED)
  } catch {
    return []
  }
}

/**
 * Persiste la conversación (solo role+content, cap MAX_STORED). `clave` es la
 * de la cuenta abierta, salvo que se quiera escribir la de otra (ver
 * claveDeConversacion).
 */
export function saveChatSession(messages, clave = storageKey()) {
  try {
    if (!Array.isArray(messages) || messages.length === 0) {
      sessionStorage.removeItem(clave)
      return
    }
    const slim = messages
      .filter(isValidMsg)
      .slice(-MAX_STORED)
      .map(m => {
        const out = { role: m.role, content: m.content }
        for (const k of CAMPOS_QUE_SOBREVIVEN) if (m[k]) out[k] = m[k]
        return out
      })
    sessionStorage.setItem(clave, JSON.stringify(slim))
  } catch {
    // storage lleno / modo privado → el chat sigue funcionando, solo no persiste.
  }
}

export function clearChatSession() {
  try {
    sessionStorage.removeItem(storageKey())
  } catch {
    // best-effort
  }
}

/**
 * Ventana que se manda al modelo: últimos MAX_SENT mensajes, arrancando en
 * uno del USUARIO — la API exige que el primer mensaje sea user, y el backend
 * inyecta el snapshot de la cartera en el primer user de lo que recibe.
 * El backend aplica el mismo recorte server-side (autoritativo para costo).
 */
export function sendWindow(messages) {
  let w = (messages || []).slice(-MAX_SENT)
  while (w.length && w[0].role !== 'user') w = w.slice(1)
  // Red: si el recorte dejó la ventana vacía (no debería — el último mensaje
  // siempre es la pregunta recién agregada), mandamos solo ese último.
  return w.length ? w : (messages || []).slice(-1)
}
