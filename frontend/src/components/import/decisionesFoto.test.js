// La foto no se aplica hasta que cada ítem dudoso tenga un sí o un no explícito.
// Reporte de un tester del plan asesor (2026-09-20): aplicó la foto sin ver los
// tildes y los activos vendidos quedaron en la cartera.
import { describe, it, expect } from 'vitest'
import { tickersADecidir, decisionesPendientes, tickersAprobados } from './ImportWizard'

const foto = {
  no_reconciliable: [
    { ticker: 'GGAL', motivo: 'ausente_en_la_foto', requiere_aprobacion: true },
    { ticker: 'AL30', motivo: 'mas_que_la_foto', requiere_aprobacion: true },
    { ticker: 'YPFD', motivo: 'fecha_desconocida', requiere_aprobacion: false },
  ],
}

describe('decisiones sobre la foto', () => {
  it('sólo cuenta lo que exige aprobación', () => {
    expect(tickersADecidir(foto)).toEqual(['GGAL', 'AL30'])
  })

  it('sin contestar nada, faltan todas — y la foto no se puede aplicar', () => {
    expect(decisionesPendientes(foto, new Map())).toBe(2)
  })

  it('un "no" también es una respuesta: destraba sin aprobar', () => {
    const d = new Map([['GGAL', 'no'], ['AL30', 'si']])
    expect(decisionesPendientes(foto, d)).toBe(0)
    expect(tickersAprobados(d)).toEqual(['AL30'])
  })

  it('cuando el cap anuló la decisión sobre un ausente, no se pide contestarla', () => {
    const conCap = { ...foto, override: { capped: true } }
    expect(tickersADecidir(conCap)).toEqual(['AL30'])
    expect(decisionesPendientes(conCap, new Map())).toBe(1)
  })

  it('una foto sin dudosos no traba nada', () => {
    expect(decisionesPendientes({ no_reconciliable: [] }, new Map())).toBe(0)
    expect(decisionesPendientes(null, undefined)).toBe(0)
  })
})
