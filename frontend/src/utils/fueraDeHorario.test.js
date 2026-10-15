// La cuenta del pre y post mercado: a qué acción de EE.UU. mira cada tenencia y
// cuánta plata mueve. Atraviesa `valuePositionLot` (la valuación real de las
// pantallas), no un valor armado a mano: si la valuación cambia, esto lo ve.
import { describe, it, expect } from 'vitest'
import { referenciaEnEEUU, simbolosFueraDeHorario, impactoFueraDeHorario, pctDeLaTenencia, sumarTenencias } from './fueraDeHorario'
import { computeBrokerValue } from './valuation'

const BROKERS = [
  { id: 1, name: 'Schwab', currency: 'USD' },
  { id: 2, name: 'Cocos', currency: 'ARS' },
  { id: 3, name: 'Binance', currency: 'USDT' },
]
const lote = (id, broker, asset, quantity, invested, extra = {}) =>
  ({ id, broker, asset, quantity, invested, is_cash: 0, commissions: 0, ...extra })

const POS = [
  lote(1, 'Schwab', 'NVDA', 35, 4987.5, { currency: 'USD' }),
  lote(2, 'Schwab', 'AAPL', 22, 3920.4, { currency: 'USD' }),
  lote(3, 'Schwab', 'GGAL', 10, 300, { currency: 'USD' }),
  lote(4, 'Cocos', 'AAPL', 87, 2300000, { currency: 'ARS', asset_type: 'CEDEAR' }),
  lote(5, 'Cocos', 'YPFD', 40, 1500000, { currency: 'ARS' }),
  lote(6, 'Cocos', 'AGRO', 100, 9000, { currency: 'ARS' }),
  lote(7, 'Cocos', 'AL30', 2650, 2100000, { currency: 'ARS', asset_type: 'BOND' }),
  lote(8, 'Binance', 'BTC', 0.1, 7000, { currency: 'USDT', asset_type: 'CRYPTO' }),
  lote(9, 'Schwab', 'USD', 1250, 1250, { is_cash: 1, currency: 'USD' }),
  lote(10, 'Cocos', 'DISN', 30, 400000, { currency: 'ARS', asset_type: 'CEDEAR' }),
]
const PRICES = {
  NVDA: 178.5, AAPL: 192.4, GGAL: 35.55,
  'AAPL.BA': 27700, 'YPFD.BA': 41000, 'AGRO.BA': 95, 'AL30.BA': 825.49, 'DISN.BA': 14000,
  BTC: 80000,
}
const TC = 1424
const ctx = { prices: PRICES, tcValuacion: TC, tcCedear: TC }

const datos = (sesion, pcts, extra = {}) => ({
  sesion, cierra: '10:30', byma_abierto: false,
  cotizaciones: Object.fromEntries(Object.entries(pcts).map(([s, pct]) => [s, { pct, precio: null }])),
  ...extra,
})

describe('a qué acción de EE.UU. mira cada tenencia', () => {
  const ref = (id) => referenciaEnEEUU(POS.find(p => p.id === id), BROKERS)
  it('una acción de EE.UU. en un broker del exterior se mira a sí misma', () => {
    expect(ref(1)).toEqual({ s: 'NVDA', via: 'propio' })
  })
  it('el ADR argentino en Schwab es él mismo, no un anticipo', () => {
    expect(ref(3)).toEqual({ s: 'GGAL', via: 'propio' })
  })
  it('el CEDEAR mira su acción en EE.UU., con el ticker de allá', () => {
    expect(ref(4)).toEqual({ s: 'AAPL', via: 'eeuu' })
    expect(ref(10)).toEqual({ s: 'DIS', via: 'eeuu' })     // DISN es Disney: DIS
  })
  it('la acción argentina con ADR mira el ADR', () => {
    expect(ref(5)).toEqual({ s: 'YPF', via: 'adr' })        // YPFD → YPF
  })
  it('sin ADR, bonos, cripto y efectivo no miran nada', () => {
    expect(ref(6)).toBeNull()   // AGRO tal cual sería Adecoagro, otra empresa
    expect(ref(7)).toBeNull()
    expect(ref(8)).toBeNull()
    expect(ref(9)).toBeNull()
  })
  it('pide cada símbolo una sola vez', () => {
    expect(simbolosFueraDeHorario(POS, BROKERS)).toEqual(['AAPL', 'DIS', 'GGAL', 'NVDA', 'YPF'])
  })
})

describe('la plata que mueve', () => {
  it('35 NVDA a USD 178,50 con el pre en −1,60 % es −USD 99,96 (el ejemplo de la propuesta)', () => {
    const r = impactoFueraDeHorario(POS, BROKERS, ctx, datos('pre', { NVDA: -1.6 }))
    expect(r.porPosicion[1].usd).toBeCloseTo(-99.96, 2)
    expect(r.porPosicion[1].ars).toBeCloseTo(-99.96 * TC, 2)
  })

  it('un CEDEAR mueve su valor en pesos por el % de la acción de EE.UU.', () => {
    const r = impactoFueraDeHorario(POS, BROKERS, ctx, datos('pre', { AAPL: 0.74 }))
    // 87 × ARS 27.700 = ARS 2.409.900 → +0,74 % = +ARS 17.833,26
    expect(r.porPosicion[4].ars).toBeCloseTo(17833.26, 2)
    expect(r.porPosicion[4].usd).toBeCloseTo(17833.26 / TC, 6)
    expect(r.porPosicion[4].via).toBe('eeuu')
  })

  it('la suma de las tenencias es la del broker y la de la cartera', () => {
    const d = datos('pre', { NVDA: -1.6, AAPL: 0.74, GGAL: -0.28, YPF: -0.7, DIS: 1.1 })
    const r = impactoFueraDeHorario(POS, BROKERS, ctx, d)
    const filas = Object.values(r.porPosicion)
    const suma = filas.reduce((s, x) => s + x.usd, 0)
    expect(r.total.usd).toBeCloseTo(suma, 9)
    const porBroker = Object.values(r.porBroker).reduce((s, b) => s + b.usd, 0)
    expect(porBroker).toBeCloseTo(suma, 9)
    // El % del total es sobre el MISMO valor que suman los totales de pantalla.
    const valorPantalla = BROKERS.reduce((s, b) => s + computeBrokerValue(POS, PRICES, b, TC, TC).value, 0)
    expect(r.total.pct).toBeCloseTo(r.total.usd / valorPantalla, 12)
  })

  it('no toca nada de lo que valúa la pantalla', () => {
    const antes = BROKERS.map(b => computeBrokerValue(POS, PRICES, b, TC, TC).value)
    impactoFueraDeHorario(POS, BROKERS, ctx, datos('pre', { NVDA: -1.6, AAPL: 0.74 }))
    expect(BROKERS.map(b => computeBrokerValue(POS, PRICES, b, TC, TC).value)).toEqual(antes)
  })

  it('una acción que todavía no operó no mueve plata y dice «sin operar» (pct null), no 0 %', () => {
    const r = impactoFueraDeHorario(POS, BROKERS, ctx, datos('pre', { NVDA: null, AAPL: 0.5 }))
    expect(r.porPosicion[1]).toMatchObject({ usd: 0, pct: null })
    expect(r.aplica).toBe(true)
  })

  it('con BYMA abierta el CEDEAR y la acción argentina ya tienen precio propio: se apaga el anticipo', () => {
    const d = datos('pre', { NVDA: -1.6, AAPL: 0.74, YPF: -0.7 }, { byma_abierto: true })
    const r = impactoFueraDeHorario(POS, BROKERS, ctx, d)
    expect(r.porPosicion[1]).toBeDefined()     // NVDA en Schwab sigue
    expect(r.porPosicion[2]).toBeDefined()     // AAPL en Schwab sigue
    expect(r.porPosicion[4]).toBeUndefined()   // el CEDEAR no
    expect(r.porPosicion[5]).toBeUndefined()   // YPFD no
  })

  it('sin pre ni post no hay nada', () => {
    const r = impactoFueraDeHorario(POS, BROKERS, ctx, datos(null, { NVDA: -1.6 }))
    expect(r.aplica).toBe(false)
    expect(r.total.usd).toBe(0)
    expect(pctDeLaTenencia(POS[0], BROKERS, null)).toBeNull()
  })

  it('separa lo exacto (la acción misma) del anticipo (CEDEAR y vía ADR), que en pesos también se mueve con el CCL', () => {
    const d = datos('pre', { NVDA: -1.6, AAPL: 0.74, GGAL: -0.28, YPF: -0.7, DIS: 1.1 })
    const r = impactoFueraDeHorario(POS, BROKERS, ctx, d)
    const { exacto, anticipo } = r.porVia
    const de = (ids) => ids.reduce((s, id) => s + r.porPosicion[id].usd, 0)
    expect(exacto.usd).toBeCloseTo(de([1, 2, 3]), 9)        // NVDA, AAPL y GGAL en Schwab
    expect(anticipo.usd).toBeCloseTo(de([4, 5, 10]), 9)     // CEDEAR AAPL, YPFD, CEDEAR DISN
    expect(exacto.usd + anticipo.usd).toBeCloseTo(r.total.usd, 9)
    // El valor en pesos del anticipo es el de las tenencias en pesos, tal cual.
    expect(anticipo.valorArs).toBeCloseTo(87 * 27700 + 40 * 41000 + 30 * 14000, 6)
  })

  it('una fila con varios lotes suma sus lotes', () => {
    const dos = [lote(21, 'Schwab', 'NVDA', 10, 1500, { currency: 'USD' }), lote(22, 'Schwab', 'NVDA', 25, 3500, { currency: 'USD' })]
    const r = impactoFueraDeHorario(dos, BROKERS, ctx, datos('post', { NVDA: 1 }))
    const fila = sumarTenencias([21, 22], r)
    expect(fila.usd).toBeCloseTo(35 * 178.5 * 0.01, 9)
    expect(fila.pct).toBe(1)
    expect(sumarTenencias([999], r)).toBeNull()
  })

  it('la ficha de un activo da lo mismo que su fila en Cartera', () => {
    // La ficha (AssetDetail / PositionDetailMobile) hace la cuenta SÓLO con los
    // lotes de ese activo; Cartera, con toda la cartera. Tiene que dar igual.
    const d = datos('pre', { NVDA: -1.6, AAPL: 0.74, GGAL: -0.28, YPF: -0.7, DIS: 1.1 })
    const cartera = impactoFueraDeHorario(POS, BROKERS, ctx, d)
    const aapl = POS.filter(p => p.asset === 'AAPL')          // Schwab + el CEDEAR de Cocos
    const ficha = impactoFueraDeHorario(aapl, BROKERS, ctx, d)
    const fila = sumarTenencias(aapl.map(p => p.id), cartera)
    expect(ficha.aplica).toBe(true)
    expect(ficha.total.usd).toBeCloseTo(fila.usd, 9)
    expect(ficha.total.pct * 100).toBeCloseTo(0.74, 9)        // el % es el de la acción
  })
})


describe('lo que encontró la auditoría (2026-10-15)', () => {
  it('un ticker con punto pide el MISMO símbolo que el precio (BRK.B → BRK-B)', () => {
    expect(referenciaEnEEUU(lote(31, 'Schwab', 'BRK.B', 1, 400, { currency: 'USD' }), BROKERS))
      .toEqual({ s: 'BRK-B', via: 'propio' })
  })
  it('el CEDEAR guardado como BRK.B sigue a Berkshire en EE.UU.', () => {
    expect(referenciaEnEEUU(lote(32, 'Cocos', 'BRK.B', 1, 20000, { currency: 'ARS', asset_type: 'CEDEAR' }), BROKERS))
      .toEqual({ s: 'BRK-B', via: 'eeuu' })
  })
  it('un CEDEAR comprado en pesos dentro de una cuenta en dólares es anticipo, como en el servidor', () => {
    expect(referenciaEnEEUU(lote(33, 'Schwab', 'AAPL', 10, 270000, { currency: 'ARS' }), BROKERS))
      .toEqual({ s: 'AAPL', via: 'eeuu' })
  })
})
