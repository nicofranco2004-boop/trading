// Con cuánto tiempo a la vista abre el gráfico en cada temporalidad (Nico,
// 02/11: «si te muestra todo de una, parece que es muy poco historial»).
import { describe, it, expect } from 'vitest'
import { MESES_DE_ENTRADA, cuantoEsReciente, puntosDelPeriodo } from './LecturaTecnica'

// Días de mercado (lunes a viernes) desde `desde` hasta `hasta`.
function ruedas(desde, hasta) {
  const out = []
  for (let t = Date.parse(desde); t <= Date.parse(hasta); t += 86400000) {
    const f = new Date(t)
    if (f.getUTCDay() % 6) out.push({ d: f.toISOString().slice(0, 10) })
  }
  return out
}
// Velas de 1 hora: 7 por día de mercado (Nueva York), con la fecha del día.
const porHoras = (dias, cada) => dias.flatMap(p => Array.from({ length: cada }, () => ({ d: p.d })))

describe('el período de entrada por temporalidad', () => {
  const cincoAnios = ruedas('2021-11-01', '2026-10-30')

  it('1H: el último mes; 4H: 3 meses; 1D: 1 año; 1S: 3 años', () => {
    expect(MESES_DE_ENTRADA).toEqual({ '1h': 1, '4h': 3, dia: 12, semana: 36 })
    const ultimo = cincoAnios[cincoAnios.length - 1].d
    const primeroVisto = (serie, meses) => serie[serie.length - puntosDelPeriodo(serie, meses)].d
    expect(primeroVisto(cincoAnios, 12)).toBe('2025-10-30')
    expect(cuantoEsReciente(primeroVisto(cincoAnios, 12), ultimo)).toBe('1 año')
    expect(cuantoEsReciente(primeroVisto(cincoAnios, 36), ultimo)).toBe('3 años')
    const h1 = porHoras(cincoAnios.slice(-150), 7)
    expect(cuantoEsReciente(primeroVisto(h1, 1), ultimo)).toBe('1 mes')
    expect(puntosDelPeriodo(h1, 1)).toBeGreaterThan(130)   // ~22 ruedas × 7 horas
    const h4 = porHoras(cincoAnios.slice(-150), 2)
    expect(cuantoEsReciente(primeroVisto(h4, 3), ultimo)).toBe('3 meses')
  })

  it('si toda la historia entra en el período, abre con «Todo» (null)', () => {
    expect(puntosDelPeriodo(ruedas('2026-03-02', '2026-10-30'), 12)).toBeNull()
    expect(puntosDelPeriodo([], 12)).toBeNull()
  })

  it('nunca menos de 20 velas (lo más acercado que se puede)', () => {
    // Un punto por semana: en el último mes hay 4 o 5, pero se abre con 20.
    const semanal = ruedas('2024-11-01', '2026-10-30').filter((_, i) => i % 5 === 0)
    expect(puntosDelPeriodo(semanal, 1)).toBe(20)
  })

  it('en palabras: años sólo si son redondos', () => {
    expect(cuantoEsReciente('2025-04-30', '2026-10-30')).toBe('18 meses')
    expect(cuantoEsReciente('2026-10-09', '2026-10-30')).toBe('3 semanas')
  })
})
