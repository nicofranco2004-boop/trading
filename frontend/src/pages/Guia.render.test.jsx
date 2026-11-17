// /guia según quién la mira. El link a la guía para asesores se sumó para quien
// llega sin sesión (lo vigila __guards__/contenido-publico.test.jsx armando el
// HTML pre-escrito, que es lo que lee Google). Esto cuida la otra mitad: que al
// sumarlo no cambie lo que ven los que ya tienen cuenta. Con sesión la página no
// se pre-escribe —se arma en el navegador con el usuario de la sesión—, así que
// acá se dibuja el componente con ese usuario.
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'

let usuario = null
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario }) }))

const { default: Guia } = await import('./Guia.jsx')

const linksCon = (user) => {
  usuario = user
  const html = renderToStaticMarkup(<HelmetProvider><MemoryRouter><Guia /></MemoryRouter></HelmetProvider>)
  return [...html.matchAll(/<a [^>]*href="([^"]+)"/g)].map((m) => m[1]).filter((h) => h.startsWith('/guia/'))
}

describe('/guia: la guía para asesores, a quién se le ofrece', () => {
  it('sin sesión: una vez, después de las 6 secciones', () => {
    const links = linksCon(null)
    expect(links.filter((h) => h === '/guia/asesores')).toHaveLength(1)
    expect(links.indexOf('/guia/asesores')).toBe(links.length - 1)
    expect(links[0]).toBe('/guia/empezar')
  })

  it('con cuenta de asesor: sigue siendo la primera tarjeta, y una sola', () => {
    const links = linksCon({ tier: 'advisor', email: 'asesor@ejemplo.com' })
    expect(links[0]).toBe('/guia/asesores')
    expect(links.filter((h) => h === '/guia/asesores')).toHaveLength(1)
  })

  it('con cuenta común: no se le ofrece (no aplica a su cuenta)', () => {
    expect(linksCon({ tier: 'pro', email: 'alguien@ejemplo.com' })).not.toContain('/guia/asesores')
  })
})
