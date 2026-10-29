// Los atajos de Mervall-E (bloque «actions») llevan el ícono de su pantalla.
// /analisis-tecnico empieza como /analisis (Métricas): tiene que llevar el suyo.
import { describe, it, expect } from 'vitest'
import { CandlestickChart, LineChart, Gauge } from 'lucide-react'
import { iconForRoute } from './AIBlocks'

describe('el ícono de cada atajo de Mervall-E', () => {
  it('Análisis técnico (y sus pestañas) no se confunde con Métricas', () => {
    expect(iconForRoute('/analisis-tecnico')).toBe(CandlestickChart)
    expect(iconForRoute('/analisis-tecnico?tab=senales')).toBe(CandlestickChart)
    expect(iconForRoute('/analisis?tab=diagnostico')).toBe(LineChart)
    expect(iconForRoute('/fundamentals')).toBe(Gauge)
  })
})
