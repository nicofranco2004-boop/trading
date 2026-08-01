import { describe, it, expect } from 'vitest'
import { labelVentanaMeses } from './format'
describe('labelVentanaMeses — la card "Acumulado" tiene que decir su período', () => {
  it('12 meses (el default) se lee "1A"', () => {
    expect(labelVentanaMeses(12)).toBe('1A')
  })
  it('los tabs del gráfico', () => {
    expect(labelVentanaMeses(24)).toBe('2A')
    expect(labelVentanaMeses(60)).toBe('5A')
  })
  it('meses sueltos', () => {
    expect(labelVentanaMeses(6)).toBe('6m')
    expect(labelVentanaMeses(1)).toBe('1m')
  })
  it('MAX (null/0) es "histórico", no vacío ni "0m"', () => {
    // El caso que importa: sin rótulo, "Acumulado" se lee como "desde siempre"
    // y compite mentalmente con el "Rendimiento anual" del Dashboard.
    expect(labelVentanaMeses(null)).toBe('histórico')
    expect(labelVentanaMeses(undefined)).toBe('histórico')
    expect(labelVentanaMeses(0)).toBe('histórico')
    expect(labelVentanaMeses(-3)).toBe('histórico')
  })
})
