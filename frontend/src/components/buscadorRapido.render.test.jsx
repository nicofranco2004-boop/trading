import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// El buscador ⌘K de la compu, DIBUJADO abierto y con algo escrito, como lo ve
// el usuario. Las reglas de qué ofrece viven en utils/buscadorRapido.js y se
// prueban ahí; acá, que el componente las use (deshacer el "al asesor en su
// nivel no le ofrezcas empresas" pasaba en verde: nadie lo dibujaba abierto).
let usuario = { tier: 'pro' }
let cliente = null
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: usuario }) }))
vi.mock('../contexts/AdvisorContext', () => ({ useAdvisorContext: () => ({ clientCtx: cliente }) }))
vi.mock('../contexts/CurrencyContext', () => ({ useCurrency: () => ({ currency: 'USD', setCurrency: () => {} }) }))
vi.mock('../contexts/ThemeContext', () => ({ useTheme: () => ({ dark: true, toggle: () => {} }) }))
vi.mock('../contexts/PrivacyContext', () => ({ usePrivacy: () => ({ hidden: false, toggle: () => {} }) }))
vi.mock('../contexts/CoachDrawerContext', () => ({ useCoachDrawer: () => ({ open: () => {} }) }))
vi.mock('../hooks/usePlanFeatures', () => ({ usePlanFeatures: () => ({ isPro: true, isAdmin: false }) }))

import BuscadorRapido from './BuscadorRapido'

const buscar = (consulta, u, c = null) => {
  usuario = u; cliente = c
  return renderToStaticMarkup(
    <MemoryRouter><BuscadorRapido abiertoAlInicio consultaInicial={consulta} /></MemoryRouter>)
}

describe('⌘K abierto', () => {
  it('a un usuario común le ofrece la empresa que no tiene', () => {
    expect(buscar('apple', { tier: 'pro' })).toContain('Ver la empresa')
  })
  it('al asesor en su nivel, no (no tiene Calidad de cartera en su menú); adentro de un cliente, sí', () => {
    expect(buscar('apple', { tier: 'advisor' })).not.toContain('Ver la empresa')
    expect(buscar('apple', { tier: 'advisor' }, { id: 7, label: 'Ana' })).toContain('Ver la empresa')
  })
  it('un bono no aparece como "empresa" (no tiene ficha: llevaba a una pantalla vacía)', () => {
    const html = buscar('al30', { tier: 'pro' })
    expect(html).not.toMatch(/AL30[^<]*<\/span><span[^>]*>Ver la empresa/)
  })
})
