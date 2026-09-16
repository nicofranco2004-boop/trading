import { describe, it, expect } from 'vitest'
import { kindDeCuota } from './UpgradePromoCard.jsx'

// El caso REAL de producción (2026-09-16): un usuario Free se quedó sin
// ANÁLISIS (1 de 1) y todavía tenía su consulta de chat sin usar. La tarjeta
// tenía el tipo escrito a mano como 'chat' y le mostró
// "Usaste 0 de 1 consultas al Coach IA" — el sustantivo equivocado, y un
// número que se contradice con su propio título "Llegaste al límite".
const USO_REAL = {
  analyses_count: 1, analyses_limit: 1, analyses_remaining: 0,
  chat_count: 0, chat_limit: 1, chat_remaining: 1,
}

describe('kindDeCuota', () => {
  it('lo que dice el backend manda, incluso contra los contadores', () => {
    expect(kindDeCuota(USO_REAL, 'analyses')).toBe('analyses')
    expect(kindDeCuota(USO_REAL, 'chat')).toBe('chat')
  })

  it('el caso de producción: sin el dato del backend, lo deduce de los números', () => {
    expect(kindDeCuota(USO_REAL, null)).toBe('analyses')
  })

  it('el caso espejo: sin consultas pero con análisis disponibles', () => {
    expect(kindDeCuota({
      analyses_count: 0, analyses_limit: 6, analyses_remaining: 6,
      chat_count: 1, chat_limit: 1, chat_remaining: 0,
    }, null)).toBe('chat')
  })

  it('los dos agotados: usa el contexto de la pantalla', () => {
    const dos = { analyses_remaining: 0, chat_remaining: 0 }
    expect(kindDeCuota(dos, null)).toBe('chat')
    expect(kindDeCuota(dos, null, 'analyses')).toBe('analyses')
  })

  it('ignora un valor de backend que no es ninguno de los dos', () => {
    expect(kindDeCuota(USO_REAL, 'cualquier-cosa')).toBe('analyses')
  })

  it('sin datos no explota', () => {
    expect(kindDeCuota(null, null)).toBe('chat')
    expect(kindDeCuota(undefined, undefined, 'analyses')).toBe('analyses')
  })
})
