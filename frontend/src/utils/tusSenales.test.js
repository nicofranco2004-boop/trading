// Las frases nuevas de la tarjeta grande del Panorama (lienzo «1 · Panorama»,
// 30/10): el chip contra la semana pasada y «Qué lo movió». Con «Ocultar
// saldos» ninguna dice cuánto pesa algo ni cuánto se movió tu cartera.
import { describe, it, expect } from 'vitest'
import { cambioContraAntes, queLoMovio } from './tusSenales'

const HASTA = '2026-10-31'
describe('cambioContraAntes', () => {
  it('▲ / ▼ con los puntos y «la semana pasada» o el sábado con fecha', () => {
    expect(cambioContraAntes({ pct: 62, semana_pasada: { semana: '2026-10-24', pct: 54 } }, HASTA, false))
      .toEqual({ texto: '▲ 8 puntos más que la semana pasada', tono: 'pos' })
    expect(cambioContraAntes({ pct: 53, semana_pasada: { semana: '2026-10-17', pct: 54 } }, HASTA, false))
      .toEqual({ texto: '▼ 1 punto menos que el sábado 17/10', tono: 'neg' })
    expect(cambioContraAntes({ pct: 54, semana_pasada: { semana: '2026-10-24', pct: 54.2 } }, HASTA, false))
      .toEqual({ texto: 'Igual que la semana pasada', tono: null })
  })
  it('sin semana pasada, sin % o con «Ocultar saldos»: nada', () => {
    expect(cambioContraAntes({ pct: 62, semana_pasada: null }, HASTA, false)).toBeNull()
    expect(cambioContraAntes({ pct: null, semana_pasada: { semana: '2026-10-24', pct: 54 } }, HASTA, false)).toBeNull()
    expect(cambioContraAntes({ pct: 62, semana_pasada: { semana: '2026-10-24', pct: 54 } }, HASTA, true)).toBeNull()
  })
})

describe('queLoMovio', () => {
  const datos = { senales: [
    { asset: 'GGAL', tenes: true, tipo: 'media200', sentido: 'arriba', fecha: '2026-10-29', peso: 0.18 },
    { asset: 'KO', tenes: true, tipo: 'rsi_bajo_30', fecha: '2026-10-26', peso: 0.1 },
    { asset: 'TSLA', tenes: false, tipo: 'media200', sentido: 'abajo', fecha: '2026-10-28', peso: null },
  ] }
  it('sólo los cruces del promedio de 200 de lo que tenés, con su peso y el día', () => {
    expect(queLoMovio(datos, false)).toBe('GGAL (18% de tu cartera) pasó a alcista el jueves 29/10.')
  })
  it('con «Ocultar saldos», sin el peso', () => {
    expect(queLoMovio(datos, true)).toBe('GGAL pasó a alcista el jueves 29/10.')
  })
  it('si no se dio vuelta nada, null', () => {
    expect(queLoMovio({ senales: [datos.senales[1]] }, false)).toBeNull()
  })
})
