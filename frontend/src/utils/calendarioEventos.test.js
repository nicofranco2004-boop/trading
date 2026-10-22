// Tests del calendario de Eventos: qué entra, en qué casillero y qué meses se recorren.
import { describe, it, expect } from 'vitest'
import {
  eventosDelCalendario, porDia, semanasDelMes, mesesDelCalendario, categoriaDe, rotuloDe,
} from './calendarioEventos'

const ev = (ticker, eventType, eventDate) => ({ ticker, eventType, eventDate, details: {} })
const EVENTOS = [
  ev('KO', 'payment_date', '2026-12-15'),
  ev('KO', 'ex_dividend', '2026-12-01'),
  ev('AAPL', 'earnings', '2026-10-30'),
  ev('AL30', 'bond_coupon_amort', '2027-01-09'),
  ev('FED', 'macro', '2026-11-05'),          // no entra: no es cobro ni balance
  ev('MSFT', 'earnings', '2026-10-01'),      // ya pasó
]

describe('eventosDelCalendario', () => {
  it('sólo cobros, cortes y balances de hoy en adelante, por fecha', () => {
    const r = eventosDelCalendario(EVENTOS, { hoy: '2026-10-22' })
    expect(r.map(e => `${e.ticker}:${e.eventDate}`)).toEqual([
      'AAPL:2026-10-30', 'KO:2026-12-01', 'KO:2026-12-15', 'AL30:2027-01-09',
    ])
  })
  it('filtra dividendos y cupones, o balances', () => {
    expect(eventosDelCalendario(EVENTOS, { hoy: '2026-10-22', filtro: 'cobros' }).map(e => e.ticker))
      .toEqual(['KO', 'KO', 'AL30'])
    expect(eventosDelCalendario(EVENTOS, { hoy: '2026-10-22', filtro: 'balances' }).map(e => e.ticker))
      .toEqual(['AAPL'])
  })
})

describe('semanasDelMes', () => {
  it('octubre 2026 arranca jueves: tres casilleros vacíos antes del 1', () => {
    const s = semanasDelMes(2026, 10)
    expect(s[0]).toEqual([null, null, null, '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04'])
    expect(s.flat().filter(Boolean)).toHaveLength(31)
    expect(s.every(w => w.length === 7)).toBe(true)
  })
  it('febrero bisiesto tiene 29 días', () => {
    expect(semanasDelMes(2028, 2).flat().filter(Boolean)).toHaveLength(29)
  })
})

describe('mesesDelCalendario', () => {
  it('del mes de hoy al del último evento, cruzando el año', () => {
    const r = mesesDelCalendario('2026-10-22', eventosDelCalendario(EVENTOS, { hoy: '2026-10-22' }))
    expect(r).toEqual([
      { anio: 2026, mes: 10 }, { anio: 2026, mes: 11 }, { anio: 2026, mes: 12 }, { anio: 2027, mes: 1 },
    ])
  })
  it('sin eventos, sólo el mes de hoy', () => {
    expect(mesesDelCalendario('2026-10-22', [])).toEqual([{ anio: 2026, mes: 10 }])
  })
})

describe('agrupar y rotular', () => {
  it('porDia junta los eventos del mismo día', () => {
    const m = porDia([ev('KO', 'payment_date', '2026-12-15'), ev('PEP', 'payment_date', '2026-12-15')])
    expect(m.get('2026-12-15').map(e => e.ticker)).toEqual(['KO', 'PEP'])
  })
  it('categorías y rótulos', () => {
    expect(categoriaDe('earnings')).toBe('balance')
    expect(categoriaDe('ex_dividend')).toBe('corte')
    expect(categoriaDe('bond_coupon')).toBe('cobro')
    expect(categoriaDe('macro')).toBeNull()
    expect(rotuloDe('earnings')).toBe('Presenta balance')
  })
})
