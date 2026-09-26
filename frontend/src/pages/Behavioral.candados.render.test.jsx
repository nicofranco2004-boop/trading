import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// Qué plan le ofrece cada candado de Comportamiento, renderizando la grilla DE
// VERDAD con el hook de planes REAL, alimentado por donde se alimenta en
// producción: la respuesta de /api/plan/features (`limits` y `planes`).
//
// Existe por `PLUS_VISIBLE_COUNT = 6`, que estaba escrito en la pantalla: las
// cartas de la 4 a la 6 decían "Plus" y las demás "Pro". El 15/10 el Plus pasa
// a ver las 12, y ese 6 le iba a decir "Desbloquear con Pro" a un Free en
// cartas que el Plus ya muestra. (Cuántas se VEN lo cubre
// `Behavioral.render.test.jsx`.)
//
// Los topes son inventados a propósito: el test prueba que la grilla LEE los
// topes, no los de hoy.
vi.mock('../utils/api', () => ({ api: { get: vi.fn() } }))
vi.mock('../components/ai/AskAIAbout', () => ({
  default: ({ children }) => <div data-carta-visible="">{children}</div>,
}))

import { api } from '../utils/api'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'
import { BehavioralCards } from './Behavioral'

const CARTAS = Array.from({ length: 12 }, (_, i) => ({
  code: `detector_${i}`, severity: 'neutral', title: `Detector ${i}`,
  one_liner: 'Qué detecta', value_label: '—',
}))

async function candados({ tope, planes }) {
  api.get.mockResolvedValue({
    tier: 'free', limits: { behavioral_tags_visible: tope }, access: {}, planes,
  })
  await refreshPlanFeatures()
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <BehavioralCards cards={CARTAS} onCardClick={() => {}} />
    </MemoryRouter>,
  )
  return {
    plus: (html.match(/Desbloquear con Plus/g) || []).length,
    pro: (html.match(/Desbloquear con Pro/g) || []).length,
    pie: (html.match(/Rendi (Plus|Pro) te muestra los 12/) || [])[1],
    html,
  }
}

const plan = (tier, behavioral_tags_visible) => ({ tier, limits: { behavioral_tags_visible } })

describe('Comportamiento — cada candado ofrece el plan que la destraba', () => {
  it('con un Plus que ve 5: del 3 al 4 dicen Plus, el resto Pro', async () => {
    const c = await candados({ tope: 3, planes: [plan('plus', 5), plan('pro', null)] })
    expect(c.plus).toBe(2)
    expect(c.pro).toBe(7)
    // El pie ofrece el plan que muestra TODAS: el Pro.
    expect(c.pie).toBe('Pro')
  })

  it('el 15/10 (el Plus ve todas): ningún candado se vende como Pro', async () => {
    const c = await candados({ tope: 3, planes: [plan('plus', null), plan('pro', null)] })
    expect(c.plus).toBe(9)
    expect(c.pro).toBe(0)
    expect(c.pie).toBe('Plus')
  })

  it('sin `planes` (un cache de antes del cambio) dice Pro: nunca promete de más', async () => {
    const c = await candados({ tope: 3, planes: undefined })
    expect(c.plus).toBe(0)
    expect(c.pro).toBe(9)
  })

  it('el pie no promete la IA del Pro cuando ofrece Plus', async () => {
    const c = await candados({ tope: 3, planes: [plan('plus', null), plan('pro', null)] })
    expect(c.html).not.toMatch(/recomendaciones del Coach/)
  })
})
