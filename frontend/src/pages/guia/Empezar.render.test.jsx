// /guia/empezar después de la bienvenida obligatoria (25/11): una cuenta nueva
// no entra a Rendi hasta subir el historial de su broker con Mervall-E. La guía
// (pública, la indexa Google y se lee antes de registrarse) decía «Andá a
// Posiciones → Gestionar brokers» y ofrecía la carga a mano como primer paso:
// dos cosas que la app ya no deja hacer a quien recién llega.
import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { HelmetProvider } from 'react-helmet-async'

let usuario = null
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario }) }))
vi.mock('../../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: null }) }))

const { default: Empezar } = await import('./Empezar.jsx')

const dibujar = (user) => {
  usuario = user
  return renderToStaticMarkup(<HelmetProvider><MemoryRouter><Empezar /></MemoryRouter></HelmetProvider>)
    .replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ')
}

describe('/guia/empezar cuenta el camino nuevo', () => {
  for (const [quien, user] of [['sin sesión', null], ['con cuenta', { tier: 'pro', email: 'a@prueba.test' }]]) {
    it(`${quien}: el primer paso es elegir el broker y subir su historial con Mervall-E`, () => {
      const t = dibujar(user)
      expect(t).toContain('Mervall-E')
      expect(t).toContain('planilla de Rendi')
      expect(t).toContain('Wallbit')
      // Lo viejo, que ya no se puede hacer antes de cargar el historial:
      expect(t).not.toContain('Gestionar brokers')
      expect(t).not.toContain('Opción B')
      // La carga a mano sigue existiendo, pero DESPUÉS (para lo que falte).
      expect(t.indexOf('Registrar → Compra')).toBeGreaterThan(t.indexOf('subir su historial'))
    })
  }
})
