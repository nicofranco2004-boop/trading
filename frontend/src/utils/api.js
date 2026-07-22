import { isDemoMode, handleDemoRequest } from './demo'

// Wrapper de fetch para llamadas al API.
//
// Auth: vía cookie HttpOnly (`rendi_token`). El backend la setea en /auth/login,
// /auth/register, /auth/verify-email, /auth/reset-password. El JS del frontend
// NO la puede leer (HttpOnly) — sólo el browser la adjunta al request si
// `credentials: 'include'` está activo. Esto cierra el vector XSS-roba-token.
//
// Cookies legacy: hay limpieza one-time abajo para borrar `rendi_token` y
// `rendi_user` del localStorage si quedaron de versiones anteriores.

if (typeof window !== 'undefined') {
  try {
    localStorage.removeItem('rendi_token')  // legacy: ahora es cookie HttpOnly
  } catch {}
}

// ── Contexto de cliente (Plan Asesor) ────────────────────────────────────────
// Cuando el asesor entra a "el Rendi de un cliente", TODOS los requests llevan
// el header X-Rendi-Client-Id → el backend (get_effective_user) resuelve la
// cuenta del cliente para endpoints de datos, e IGNORA el header en los
// prefijos exentos (auth/billing/ai/push/advisor). Persistimos en localStorage
// para sobrevivir reloads; AdvisorContext (React) espeja este estado y fuerza
// el refetch de plan features al entrar/salir.
const CLIENT_CTX_KEY = 'rendi_client_ctx'
let _clientCtx = null
try {
  if (typeof window !== 'undefined') {
    const raw = localStorage.getItem(CLIENT_CTX_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed.id === 'number') _clientCtx = parsed
    }
  }
} catch { /* basura en LS → sin contexto */ }

export function getClientContext() {
  return _clientCtx
}

export function setClientContext(ctx) {
  // ctx: { id: <client_uid>, label: <string> }
  _clientCtx = ctx && typeof ctx.id === 'number' ? { id: ctx.id, label: ctx.label || '' } : null
  try {
    if (_clientCtx) localStorage.setItem(CLIENT_CTX_KEY, JSON.stringify(_clientCtx))
    else localStorage.removeItem(CLIENT_CTX_KEY)
  } catch { /* ignore */ }
}

export function clearClientContext() {
  setClientContext(null)
}

// Sync multi-pestaña: si OTRA pestaña limpia/cambia el contexto (logout, salir
// del cliente), el mirror en memoria de ESTA pestaña se actualiza — sin esto,
// una pestaña vieja seguía mandando el header de un cliente ajeno tras el
// logout+login de otro usuario (403 en toda la app hasta un F5).
if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key !== null && e.key !== CLIENT_CTX_KEY) return
    try {
      const parsed = e.key === null ? null : (e.newValue ? JSON.parse(e.newValue) : null)
      _clientCtx = parsed && typeof parsed.id === 'number' ? parsed : null
    } catch { _clientCtx = null }
  })
}

async function req(method, path, body, opts) {
  // ── Demo mode interceptor ────────────────────────────────────────────────
  // Si el user está en modo demo, devolvemos fixtures hardcodeadas en lugar
  // de pegarle al backend. handleDemoRequest devuelve:
  //   - null → no hay mock → seguir al fetch real (defensa)
  //   - { __demoBlocked: true, message } → la acción no está soportada en
  //     demo (ej. vender una posición). Lanzamos Error con mensaje claro
  //     para que el componente lo muestre como error inline.
  //   - cualquier otro objeto → respuesta normal.
  if (isDemoMode()) {
    const mock = handleDemoRequest(method, path, body)
    if (mock !== null) {
      // Mini-delay para evitar UI parpadeante "demasiado rápida"
      await new Promise(r => setTimeout(r, 80))
      if (mock && mock.__demoBlocked) {
        const err = new Error(mock.message || 'Acción no disponible en modo demo.')
        err.demoBlocked = true
        throw err
      }
      // Error HTTP simulado (ej. 429 de cuota) — mismo shape que buildHttpError
      // (err.status + err.payload) para que los callers lo traten como el real.
      if (mock && mock.__demoHttpError) {
        const e = mock.__demoHttpError
        const err = new Error(e.message || `HTTP ${e.status}`)
        err.status = e.status
        err.payload = e.payload
        throw err
      }
      return mock
    }
  }

  const headers = { 'Content-Type': 'application/json' }
  // Plan Asesor: contexto de cliente activo → el backend resuelve la cuenta
  // del cliente (o ignora el header en los prefijos exentos).
  if (_clientCtx?.id) headers['X-Rendi-Client-Id'] = String(_clientCtx.id)

  const res = await fetch('/api' + path, {
    method,
    headers,
    credentials: 'include',  // adjunta la cookie HttpOnly de auth
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal: opts?.signal,
  })

  if (res.status === 401) {
    // Si hay un usuario "conocido" en localStorage y nos rebotan, expiró la
    // cookie / sesión — limpiar y mandar al login.
    const hadUser = !!localStorage.getItem('rendi_user')
    localStorage.removeItem('rendi_user')
    if (hadUser) {
      window.location.href = '/'
    }
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    throw await buildHttpError(res)
  }

  return res.json()
}

// Parsea el body del error y arma un Error con mensaje legible. FastAPI puede
// devolver `detail` como string ("Token inválido") o como dict ({error,usage}
// — el caso del 429 de IA). Si es dict, intentamos extraer .error / .message /
// .detail; si no, JSON.stringify como último recurso. Adjuntamos el payload
// crudo en err.payload por si el caller necesita info adicional (ej. usage).
async function buildHttpError(res) {
  let message = `HTTP ${res.status}`
  let payload = null
  try {
    payload = await res.json()
    const detail = payload?.detail
    if (typeof detail === 'string') {
      message = detail
    } else if (detail && typeof detail === 'object') {
      message = detail.error || detail.message || detail.detail || JSON.stringify(detail)
    }
  } catch { /* body no es JSON — dejamos el HTTP {status} */ }
  const err = new Error(message)
  err.status = res.status
  err.payload = payload
  return err
}

async function upload(path, formData) {
  // En demo mode no soportamos imports (el wizard de CSV requiere parsing
  // server-side). Throw inmediato con mensaje claro.
  if (isDemoMode()) {
    const err = new Error('En modo demo no podés importar archivos. Creá una cuenta gratis para subir tu CSV.')
    err.demoBlocked = true
    throw err
  }
  // No setear Content-Type — el browser agrega multipart/form-data con su boundary.
  // Contexto de cliente (Plan Asesor): mismo header que req() — sin esto el
  // import caía SILENCIOSAMENTE en la cuenta del asesor con el ctx activo.
  const upHeaders = {}
  if (_clientCtx?.id) upHeaders['X-Rendi-Client-Id'] = String(_clientCtx.id)
  const res = await fetch('/api' + path, {
    method: 'POST',
    credentials: 'include',
    headers: upHeaders,
    body: formData,
  })

  if (res.status === 401) {
    localStorage.removeItem('rendi_user')
    window.location.href = '/'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    throw await buildHttpError(res)
  }
  return res.json()
}

// Variante para GETs que devuelven binarios (ej. CSV, PDF). Propaga errores
// con el mismo shape (status/payload) que el req() normal. En demo levanta
// un error explicativo.
async function getBlob(path) {
  if (isDemoMode()) {
    const err = new Error('Las descargas no están disponibles en modo demo.')
    err.demoBlocked = true
    throw err
  }
  // Contexto de cliente (Plan Asesor): mismo header que req() — sin esto el
  // export CSV bajaba la cartera del ASESOR presentada como la del cliente.
  const blobHeaders = {}
  if (_clientCtx?.id) blobHeaders['X-Rendi-Client-Id'] = String(_clientCtx.id)
  const res = await fetch('/api' + path, {
    method: 'GET',
    credentials: 'include',
    headers: blobHeaders,
  })
  if (res.status === 401) {
    localStorage.removeItem('rendi_user')
    window.location.href = '/'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    throw await buildHttpError(res)
  }
  return res.blob()
}

// Chat IA con streaming (SSE). Emite cada pedacito de texto vía onDelta(text)
// para que la UI lo muestre token por token. Los errores PRE-stream (429 cuota,
// 403 gate) llegan como HTTP non-200 y se parsean con buildHttpError → mismo
// shape que api.post (err.status/err.payload) para conservar la UX de errores
// (UpgradePromoCard, etc). Un error del LLM a mitad del stream llega como frame
// `error` y se lanza con el mismo shape. En demo mode no hay streaming real:
// usamos el mock y emitimos todo de una.
async function chatStream(body, { onDelta, onReset, signal } = {}) {
  if (isDemoMode()) {
    const res = await req('POST', '/ai/chat', { ...body, stream: false })
    // El mock demo resuelve por setTimeout (inabortable): respetar el abort
    // acá — sin esto, reset()/"Nuevo" en demo dejaba una burbuja fantasma.
    if (signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError')
    }
    if (onDelta && res?.reply) onDelta(res.reply)
    return { tier: res?.tier, portfolioChanged: !!res?.portfolio_changed }
  }

  // Contexto de cliente (Plan Asesor): la IA SIGUE al contexto — con ctx
  // activo el coach lee/escribe la cuenta del CLIENTE (IA per-cliente).
  const chatHeaders = { 'Content-Type': 'application/json' }
  if (_clientCtx?.id) chatHeaders['X-Rendi-Client-Id'] = String(_clientCtx.id)
  const res = await fetch('/api/ai/chat', {
    method: 'POST',
    headers: chatHeaders,
    credentials: 'include',
    body: JSON.stringify({ ...body, stream: true }),
    signal,
  })

  if (res.status === 401) {
    const hadUser = !!localStorage.getItem('rendi_user')
    localStorage.removeItem('rendi_user')
    if (hadUser) window.location.href = '/'
    throw new Error('Unauthorized')
  }
  if (!res.ok || !res.body) {
    throw await buildHttpError(res)   // 429/403/500 → mismo shape que api.post
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let tier = null
  // El turno ESCRIBIÓ en la cartera (registro/undo por chat) — el caller
  // dispara el refresh de Cartera y del snapshot sin F5 del usuario.
  let portfolioChanged = false
  let streamErr = null
  // B-6 (audit IA #2): sin sentinel de fin, un stream CORTADO a mitad (Vercel
  // corta a 30s, red móvil, proxy) terminaba el reader sin frame terminal y se
  // devolvía como si la respuesta estuviera COMPLETA — el user leía media
  // respuesta creyendo que era toda. Solo `done`/`error` marcan fin legítimo.
  let sawTerminal = false

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let sep
    // Frames SSE separados por línea en blanco (\n\n).
    while ((sep = buf.indexOf('\n\n')) !== -1) {
      const frame = buf.slice(0, sep)
      buf = buf.slice(sep + 2)
      for (const line of frame.split('\n')) {
        if (!line.startsWith('data:')) continue   // ignora comentarios (`: ok`)
        const payload = line.slice(5).trim()
        if (!payload) continue
        let evt
        try { evt = JSON.parse(payload) } catch { continue }
        if (evt.t === 'delta') {
          if (onDelta && evt.d) onDelta(evt.d)
        } else if (evt.t === 'reset') {
          // B-13: el turno anterior terminó en tool_use — lo streameado hasta
          // acá era el PREÁMBULO ("déjame consultar…"), no la respuesta. El
          // caller limpia la burbuja y vuelve al loader.
          if (onReset) onReset()
        } else if (evt.t === 'done') {
          sawTerminal = true
          tier = evt.tier ?? tier
          if (evt.portfolio_changed) portfolioChanged = true
        } else if (evt.t === 'error') {
          // Error del LLM a mitad de stream: lo guardamos y cortamos la lectura.
          sawTerminal = true
          const err = new Error(evt.message || 'Error en el chat')
          err.status = 503
          err.payload = { detail: { error: evt.code, message: evt.message } }
          streamErr = err
        }
      }
      if (streamErr) break
    }
    if (streamErr) break
  }
  try { reader.cancel() } catch {}
  if (streamErr) throw streamErr
  if (!sawTerminal) {
    const err = new Error('La respuesta se cortó antes de terminar.')
    err.truncated = true
    throw err
  }
  return { tier, portfolioChanged }
}

export const api = {
  get: (path, opts) => req('GET', path, undefined, opts),
  post: (path, body) => req('POST', path, body),
  put: (path, body) => req('PUT', path, body),
  patch: (path, body) => req('PATCH', path, body),
  delete: (path, body) => req('DELETE', path, body),
  upload,
  getBlob,
  chatStream,
}
