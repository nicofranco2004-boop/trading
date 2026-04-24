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
    localStorage.removeItem('rendi_token')
    localStorage.removeItem('rendi_user')
    window.location.href = '/login'
    throw new Error('Unauthorized')
  }

  return res.json()
}

export const api = {
  get: (path) => req('GET', path),
  post: (path, body) => req('POST', path, body),
  put: (path, body) => req('PUT', path, body),
  delete: (path) => req('DELETE', path),
}
