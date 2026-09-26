import { describe, it, expect } from 'vitest'
import { planQueDestraba } from './planes'

// Los topes de acá son INVENTADOS a propósito: el test prueba la regla, no el
// plan de hoy. Los de verdad los compara el backend
// (`tests/test_carteles_vs_limites.py::LosPlanesQueVeLaPantalla`).
const HOY = [
  { tier: 'plus', limits: { behavioral_tags_visible: 5 } },
  { tier: 'pro', limits: { behavioral_tags_visible: null } },
]
// El 15/10: el Plus pasa a verlos todos.
const DESDE_EL_15_10 = [
  { tier: 'plus', limits: { behavioral_tags_visible: null } },
  { tier: 'pro', limits: { behavioral_tags_visible: null } },
]

describe('planQueDestraba — el plan más barato que muestra ese ítem', () => {
  it('con los topes de hoy: las que ve el Plus dicen Plus, el resto Pro', () => {
    // Un Free con tope 3: la carta 3 (cuarta) ya la ve el Plus.
    expect(planQueDestraba(HOY, 'behavioral_tags_visible', 3)).toBe('plus')
    expect(planQueDestraba(HOY, 'behavioral_tags_visible', 4)).toBe('plus')
    expect(planQueDestraba(HOY, 'behavioral_tags_visible', 5)).toBe('pro')
    expect(planQueDestraba(HOY, 'behavioral_tags_visible', 11)).toBe('pro')
  })

  it('desde el 15/10 todas dicen Plus: ninguna se vende como Pro', () => {
    for (let i = 3; i < 12; i++) {
      expect(planQueDestraba(DESDE_EL_15_10, 'behavioral_tags_visible', i)).toBe('plus')
    }
  })

  it('respeta el orden: el primero que lo da, aunque otro más caro también', () => {
    const planes = [
      { tier: 'plus', limits: { brokers_max: 2 } },
      { tier: 'pro', limits: { brokers_max: null } },
    ]
    expect(planQueDestraba(planes, 'brokers_max', 1)).toBe('plus')
    expect(planQueDestraba(planes, 'brokers_max', 2)).toBe('pro')
  })

  it('sin la lista (backend o cache viejo) no inventa: devuelve null', () => {
    expect(planQueDestraba(undefined, 'behavioral_tags_visible', 3)).toBeNull()
    expect(planQueDestraba(null, 'behavioral_tags_visible', 3)).toBeNull()
  })

  it('si ningún plan lo muestra, tampoco inventa', () => {
    const planes = [{ tier: 'plus', limits: { alerts_max: 2 } },
                    { tier: 'pro', limits: { alerts_max: 4 } }]
    expect(planQueDestraba(planes, 'alerts_max', 9)).toBeNull()
  })
})
