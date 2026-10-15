// Lo que la pantalla le pide al servidor: los símbolos de EE.UU. y, aparte,
// cuáles siguen a un CEDEAR o a una acción argentina (`byma`). Sin `byma` el
// servidor no manda el % desde el cierre de BYMA y, de noviembre a marzo, el
// CEDEAR se perdería la última hora de la rueda de Nueva York.
import { describe, it, expect, vi } from 'vitest'

vi.mock('../utils/api', () => ({ api: { get: vi.fn() } }))

import { urlFueraDeHorario } from './useFueraDeHorario'
import { simbolosFueraDeHorario, simbolosDesdeByma } from '../utils/fueraDeHorario'

const BROKERS = [{ id: 1, name: 'Schwab', currency: 'USD' }, { id: 2, name: 'Cocos', currency: 'ARS' }]
const POS = [
  { id: 1, broker: 'Schwab', asset: 'AAPL', quantity: 1, invested: 1, is_cash: 0, currency: 'USD' },
  { id: 2, broker: 'Cocos', asset: 'AAPL', quantity: 1, invested: 1, is_cash: 0, currency: 'ARS', asset_type: 'CEDEAR' },
  { id: 3, broker: 'Schwab', asset: 'NVDA', quantity: 1, invested: 1, is_cash: 0, currency: 'USD' },
  { id: 4, broker: 'Cocos', asset: 'YPFD', quantity: 1, invested: 1, is_cash: 0, currency: 'ARS' },
]

describe('el pedido del pre/post', () => {
  it('manda los símbolos y cuáles van desde el cierre de BYMA', () => {
    const url = urlFueraDeHorario(simbolosFueraDeHorario(POS, BROKERS), { byma: simbolosDesdeByma(POS, BROKERS) })
    const q = new URLSearchParams(url.split('?')[1])
    expect(q.get('symbols')).toBe('AAPL,NVDA,YPF')
    expect(q.get('byma')).toBe('AAPL,YPF')
  })
  it('sin tenencias que sigan a un papel de acá, no manda `byma`', () => {
    expect(urlFueraDeHorario(['NVDA'])).toBe('/fuera-de-horario?symbols=NVDA')
  })
  it('sin símbolos y sin listas no pide nada', () => {
    expect(urlFueraDeHorario([])).toBeNull()
    expect(urlFueraDeHorario([], { listas: true })).toBe('/fuera-de-horario?listas=1')
  })
})
