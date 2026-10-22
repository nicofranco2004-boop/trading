import { describe, it, expect } from 'vitest'
import { urlTieneDatosSensibles } from './rutasSensibles'

describe('urlTieneDatosSensibles (RENDI-09)', () => {
  it('bloquea /verify-email (el email viaja en la URL)', () => {
    expect(urlTieneDatosSensibles('/verify-email', '?email=juan%40x.com')).toBe(true)
  })
  it('bloquea /reset-password (el token cambia la contraseña)', () => {
    expect(urlTieneDatosSensibles('/reset-password', '?token=abc123')).toBe(true)
  })
  it('sigue bloqueando /i/ /claim /acceso', () => {
    expect(urlTieneDatosSensibles('/i/abc', '')).toBe(true)
    expect(urlTieneDatosSensibles('/claim', '?token=x')).toBe(true)
    expect(urlTieneDatosSensibles('/acceso', '')).toBe(true)
  })
  it('falla cerrado: cualquier ruta con token/email/code en la query', () => {
    expect(urlTieneDatosSensibles('/lo-que-sea', '?email=x')).toBe(true)
    expect(urlTieneDatosSensibles('/otra', '?token=x')).toBe(true)
    expect(urlTieneDatosSensibles('/x', '?code=123456')).toBe(true)
  })
  it('deja pasar las rutas públicas sin datos sensibles', () => {
    expect(urlTieneDatosSensibles('/', '')).toBe(false)
    expect(urlTieneDatosSensibles('/planes', '')).toBe(false)
    expect(urlTieneDatosSensibles('/login', '?mode=register')).toBe(false)
    expect(urlTieneDatosSensibles('/x', '?d=post-123&utm_source=ig')).toBe(false)
  })
})
