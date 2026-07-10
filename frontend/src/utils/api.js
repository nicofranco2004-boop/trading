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
      return mock
    }
  }

  const headers = { 'Content-Type': 'application/json' }

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
  const res = await fetch('/api' + path, {
    method: 'POST',
    credentials: 'include',
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
  const res = await fetch('/api' + path, {
    method: 'GET',
    credentials: 'include',
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
    return { tier: res?.tier }
  }

  const res = await fetch('/api/ai/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
  return { tier }
}

export const api = {
  get: (path, opts) => req('GET', path, undefined, opts),
  post: (path, body) => req('POST', path, body),
  put: (path, body) => req('PUT', path, body),
  delete: (path, body) => req('DELETE', path, body),
  upload,
  getBlob,
  chatStream,
}
