// chatSession — persistencia client-side de la conversación de Rendi AI.
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

const KEY = 'rendi_chat_v1'
// Demo con clave propia: lo que chatea un visitante demo no debe aparecer
// cuando el usuario real vuelve a loguearse en el mismo browser (ni al revés).
const DEMO_KEY = 'rendi_chat_demo_v1'

export const MAX_STORED = 40  // mensajes en pantalla/persistidos
export const MAX_SENT = 12    // ventana que viaja al modelo (cost cap)

function storageKey() {
  if (isDemoMode()) return DEMO_KEY
  // Plan Asesor: en contexto de cliente la conversación es OTRA (la IA opera
  // sobre la cuenta del cliente) — key separada por cliente para no mezclar.
  try {
    const ctx = JSON.parse(localStorage.getItem('rendi_client_ctx') || 'null')
    if (ctx?.id) return `${KEY}_c${ctx.id}`
  } catch { /* sin ctx */ }
  return KEY
}

function isValidMsg(m) {
  return m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string'
}

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

/** Persiste la conversación (solo role+content, cap MAX_STORED). */
export function saveChatSession(messages) {
  try {
    if (!Array.isArray(messages) || messages.length === 0) {
      sessionStorage.removeItem(storageKey())
      return
    }
    const slim = messages
      .filter(isValidMsg)
      .slice(-MAX_STORED)
      .map(m => ({ role: m.role, content: m.content }))
    sessionStorage.setItem(storageKey(), JSON.stringify(slim))
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
