function getToken() {
  return localStorage.getItem('rendi_token')
}

async function req(method, path, body) {
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
    let detail = `HTTP ${res.status}`
    try { const j = await res.json(); detail = j.detail || detail } catch {}
    throw new Error(detail)
  }

  return res.json()
}

async function upload(path, formData) {
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
    let detail = `HTTP ${res.status}`
    try { const j = await res.json(); detail = j.detail || detail } catch {}
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  get: (path) => req('GET', path),
  post: (path, body) => req('POST', path, body),
  put: (path, body) => req('PUT', path, body),
  delete: (path) => req('DELETE', path),
  upload,
}
