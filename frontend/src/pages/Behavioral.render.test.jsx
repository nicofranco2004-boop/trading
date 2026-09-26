import { describe, it, expect, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'

// Cuántas cartas de Comportamiento ve cada plan, renderizando la grilla DE
// VERDAD con el hook de planes REAL. Al hook se lo alimenta por donde se
// alimenta en producción: la respuesta de /api/plan/features.
//
// Existe por el 15/10 (`git revert 78f43739`): el Plus pasa a "sin tope"
// (`behavioral_tags_visible: null`), y la grilla decidía "todas" por el NOMBRE
// del plan (sólo Pro/Asesor/Admin). Con el Plus en null caía en la rama con
// tope y `null || 1` le mostraba UNA carta de doce.
vi.mock('../utils/api', () => ({ api: { get: vi.fn() } }))
// AskAIAbout envuelve cada carta VISIBLE (las bloqueadas no): se lo cambia por
// una marca que se puede contar. De paso se evita su contexto de voz.
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

async function cuantasSeVen(tier, tope) {
  api.get.mockResolvedValue({
    tier, limits: { behavioral_tags_visible: tope }, access: {},
  })
  await refreshPlanFeatures()
  const html = renderToStaticMarkup(
    <MemoryRouter>
      <BehavioralCards cards={CARTAS} onCardClick={() => {}} />
    </MemoryRouter>,
  )
  return (html.match(/data-carta-visible/g) || []).length
}

describe('Comportamiento — la grilla muestra lo que dice la tabla de planes', () => {
  it('con tope 3 se ven 3', async () => {
    expect(await cuantasSeVen('free', 3)).toBe(3)
  })

  it('con tope 6 se ven 6', async () => {
    expect(await cuantasSeVen('plus', 6)).toBe(6)
  })

  it('sin tope se ven las 12', async () => {
    expect(await cuantasSeVen('pro', null)).toBe(12)
  })

  it('el Plus sin tope (15/10) también ve las 12, no 1', async () => {
    expect(await cuantasSeVen('plus', null)).toBe(12)
  })
})
