import { isDemoMode, handleDemoRequest } from './demo'

function getToken() {
  return localStorage.getItem('rendi_token')
}

async function req(method, path, body) {
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
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch('/api' + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (res.status === 401) {
    const hadToken = !!token
    localStorage.removeItem('rendi_token')
    localStorage.removeItem('rendi_user')
    // Si había un token y expiró/fue invalidado, forzar recarga al login
    if (hadToken) {
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
  const headers = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch('/api' + path, { method: 'POST', headers, body: formData })

  if (res.status === 401) {
    localStorage.removeItem('rendi_token')
    localStorage.removeItem('rendi_user')
    window.location.href = '/'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    throw await buildHttpError(res)
  }
  return res.json()
}

// Variante para GETs que devuelven binarios (ej. CSV, PDF). Mantiene la
// auth header del usuario y propaga errores con el mismo shape (status/payload)
// que el req() normal. En demo mode levanta un error explicativo.
async function getBlob(path) {
  if (isDemoMode()) {
    const err = new Error('Las descargas no están disponibles en modo demo.')
    err.demoBlocked = true
    throw err
  }
  const headers = {}
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch('/api' + path, { method: 'GET', headers })
  if (res.status === 401) {
    localStorage.removeItem('rendi_token')
    localStorage.removeItem('rendi_user')
    window.location.href = '/'
    throw new Error('Unauthorized')
  }
  if (!res.ok) {
    throw await buildHttpError(res)
  }
  return res.blob()
}

export const api = {
  get: (path) => req('GET', path),
  post: (path, body) => req('POST', path, body),
  put: (path, body) => req('PUT', path, body),
  delete: (path, body) => req('DELETE', path, body),
  upload,
  getBlob,
}
