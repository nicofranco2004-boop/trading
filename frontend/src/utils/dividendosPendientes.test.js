// Tests de la bandeja de dividendos: qué propone y con qué números.
//
// Los porcentajes llegan del servidor (backend/dividendos.py · REGLAS). Acá van
// los MISMOS valores para fijar la cuenta, con el caso de la maqueta:
// 150 CEDEARs de KO (5 por acción) = 30 acciones × US$ 0,53 = US$ 15,90.
import { describe, it, expect, beforeEach } from 'vitest'
import { setBrokersRegistry } from './valuation'
import { detectarDividendos, yaRegistrado, familiaDeBroker, tickersParaHistorial } from './dividendosPendientes'

const BROKERS = [
  { id: 1, name: 'Balanz', currency: 'ARS' },
  { id: 2, name: 'Balanz · USD', currency: 'USDT', parent_broker_id: 1 },
  { id: 3, name: 'Cocos', currency: 'ARS' },
  { id: 4, name: 'Schwab', currency: 'USD' },
]
beforeEach(() => setBrokersRegistry(BROKERS))

const REGLAS = {
  impuesto_eeuu: 0.30, otros_accion: 0.05,
  comision_pesos: { balanz: 0.0042, iol: 0.0072 },
  dias_hasta_el_pago: 21, dias_hacia_atras: 120,
  ventana_ya_registrado: 45, tolerancia_monto_sin_activo: 0.20, solo_ultimo_pago: true,
  paises_con_regla: ['United States'],
}
const HOY = '2026-10-09'
const historial = (tickers) => ({ hoy: HOY, reglas: REGLAS, tickers })
const KO = { pais: 'United States', tipo: 'EQUITY', pagos: [{ ex_date: '2026-09-15', por_accion: 0.53 }] }
const lote = (o) => ({ asset: 'KO', quantity: 150, broker: 'Balanz', is_cash: 0,
  asset_type: 'CEDEAR', currency: 'ARS', entry_date: '2026-08-01', ...o })

const detectar = (o = {}) => detectarDividendos({
  positions: [lote()], historial: historial({ KO }), operaciones: [], salteados: [],
  brokers: BROKERS, mep: 1450, ...o,
})

describe('la cuenta', () => {
  it('150 CEDEARs de KO → US$ 15,90 de dividendo y US$ 10,33 que llegan', () => {
    const { paraConfirmar } = detectar()
    expect(paraConfirmar).toHaveLength(1)
    const it0 = paraConfirmar[0]
    expect(it0.acciones).toBe(30)
    expect(it0.bruto).toBe(15.9)
    expect(it0.impuesto).toBe(4.77)
    expect(it0.otros).toBe(0.8)          // 0,795 redondeado
    expect(it0.neto).toBe(10.33)
    // Balanz cobra ~0,42 % de lo que llegó, en pesos.
    expect(it0.comisionPesos).toBeCloseTo(10.33 * 0.0042 * 1450, 1)
    expect(it0.pagoEstimado).toBe('2026-10-06')
    expect(it0.exDate).toBe('2026-09-15')
  })

  it('un ETF sólo tiene el impuesto, sin los otros descuentos', () => {
    const SPY = { pais: null, tipo: 'ETF', pagos: [{ ex_date: '2026-09-15', por_accion: 1.889 }] }
    const { paraConfirmar } = detectar({
      positions: [lote({ asset: 'SPY', quantity: 120 })], historial: historial({ SPY }),
    })
    expect(paraConfirmar[0].otros).toBe(0)
    expect(paraConfirmar[0].bruto).toBe(3.78)       // 120 / 60 = 2 acciones
    expect(paraConfirmar[0].neto).toBe(2.65)
  })

  it('cuenta sólo lo que tenía el día de corte', () => {
    const { paraConfirmar } = detectar({
      positions: [lote({ quantity: 100 }), lote({ quantity: 50, entry_date: '2026-09-20' })],
    })
    expect(paraConfirmar[0].cedears).toBe(100)
  })

  it('comprado DESPUÉS del corte: no hay dividendo', () => {
    expect(detectar({ positions: [lote({ entry_date: '2026-09-15' })] }).paraConfirmar).toEqual([])
  })
})

describe('sin monto antes que un monto malo', () => {
  it('una empresa de afuera de EE.UU. (otra retención, sin medir) no se propone', () => {
    const VALE = { pais: 'Brazil', tipo: 'EQUITY', pagos: [{ ex_date: '2026-09-15', por_accion: 0.5 }] }
    expect(detectar({ positions: [lote({ asset: 'VALE', quantity: 20 })], historial: historial({ VALE }) })
      .paraConfirmar).toEqual([])
  })

  it('la acción en un broker del exterior queda fuera de esta etapa', () => {
    expect(detectar({ positions: [lote({ broker: 'Schwab', asset_type: 'STOCK', currency: 'USD', quantity: 30 })] })
      .paraConfirmar).toEqual([])
  })

  it('un CEDEAR sin ratio en la tabla no tiene tarjeta', () => {
    const X = { pais: 'United States', tipo: 'EQUITY', pagos: [{ ex_date: '2026-09-15', por_accion: 1 }] }
    expect(detectar({ positions: [lote({ asset: 'NO_EXISTE_XYZ' })], historial: historial({ NO_EXISTE_XYZ: X }) })
      .paraConfirmar).toEqual([])
  })

  it('sin reglas del servidor no se propone nada', () => {
    expect(detectar({ historial: { hoy: HOY, tickers: { KO } } }).paraConfirmar).toEqual([])
  })
})

describe('cuándo aparece y cuándo no', () => {
  it('antes de la fecha de pago estimada va a "próximos"', () => {
    const r = detectar({ historial: historial({ KO: { ...KO, pagos: [{ ex_date: '2026-10-01', por_accion: 0.53 }] } }) })
    expect(r.paraConfirmar).toEqual([])
    expect(r.proximos).toHaveLength(1)
    expect(r.proximos[0].pagoEstimado).toBe('2026-10-22')
  })

  it('un corte de hace más de 120 días no se propone', () => {
    const r = detectar({ historial: historial({ KO: { ...KO, pagos: [{ ex_date: '2026-05-01', por_accion: 0.53 }] } }) })
    expect(r.paraConfirmar).toEqual([])
  })

  it('ya importado (en la cuenta en dólares del mismo broker) → no aparece', () => {
    const operaciones = [{ op_type: 'Dividendo', broker: 'Balanz · USD', asset: 'KO', date: '2026-10-07', pnl_usd: 10.4 }]
    expect(detectar({ operaciones }).paraConfirmar).toEqual([])
  })

  it('importado SIN activo (Cocos) con un monto parecido → no aparece; con otro monto, sí', () => {
    const sinActivo = (pnl) => [{ op_type: 'Dividendo', broker: 'Balanz · USD', asset: '—', date: '2026-10-07', pnl_usd: pnl }]
    expect(detectar({ operaciones: sinActivo(10.2) }).paraConfirmar).toEqual([])
    expect(detectar({ operaciones: sinActivo(30) }).paraConfirmar).toHaveLength(1)
  })

  it('un dividendo de OTRO broker no cuenta', () => {
    const operaciones = [{ op_type: 'Dividendo', broker: 'Cocos', asset: 'KO', date: '2026-10-07', pnl_usd: 10.4 }]
    expect(detectar({ operaciones }).paraConfirmar).toHaveLength(1)
  })

  it('"No lo cobré" lo saca de la bandeja', () => {
    const salteados = [{ broker: 'Balanz', asset: 'KO', ex_date: '2026-09-15' }]
    expect(detectar({ salteados }).paraConfirmar).toEqual([])
  })
})

describe('sólo el último pago de cada empresa', () => {
  const dosPagos = { ...KO, pagos: [{ ex_date: '2026-06-15', por_accion: 0.53 }, { ex_date: '2026-09-15', por_accion: 0.53 }] }

  it('de dos pagos ya acreditados, propone sólo el más reciente', () => {
    const r = detectar({ positions: [lote({ entry_date: '2026-05-01' })], historial: historial({ KO: dosPagos }) })
    expect(r.paraConfirmar.map(i => i.exDate)).toEqual(['2026-09-15'])
  })

  it('si el último ya está anotado, no vuelve al anterior', () => {
    const operaciones = [{ op_type: 'Dividendo', broker: 'Balanz · USD', asset: 'KO', date: '2026-10-06', pnl_usd: 10.33 }]
    const r = detectar({ positions: [lote({ entry_date: '2026-05-01' })], historial: historial({ KO: dosPagos }), operaciones })
    expect(r.paraConfirmar).toEqual([])
  })

  it('si el último lo marcó "No lo cobré", tampoco', () => {
    const salteados = [{ broker: 'Balanz', asset: 'KO', ex_date: '2026-09-15' }]
    const r = detectar({ positions: [lote({ entry_date: '2026-05-01' })], historial: historial({ KO: dosPagos }), salteados })
    expect(r.paraConfirmar).toEqual([])
  })

  it('uno con corte pasado que todavía no llegó sigue como próximo, junto al último pagado', () => {
    const tres = { ...KO, pagos: [...dosPagos.pagos, { ex_date: '2026-10-01', por_accion: 0.53 }] }
    const r = detectar({ positions: [lote({ entry_date: '2026-05-01' })], historial: historial({ KO: tres }) })
    expect(r.paraConfirmar.map(i => i.exDate)).toEqual(['2026-09-15'])
    expect(r.proximos.map(i => i.exDate)).toEqual(['2026-10-01'])
  })

  it('cada empresa tiene su último pago (no se mezclan)', () => {
    const PEP = { pais: 'United States', tipo: 'EQUITY', pagos: [{ ex_date: '2026-06-05', por_accion: 1.48 }, { ex_date: '2026-09-04', por_accion: 1.48 }] }
    const r = detectar({
      positions: [lote({ entry_date: '2026-05-01' }), lote({ asset: 'PEP', quantity: 90, entry_date: '2026-05-01' })],
      historial: historial({ KO: dosPagos, PEP }),
    })
    expect(r.paraConfirmar.map(i => `${i.ticker} ${i.exDate}`).sort()).toEqual(['KO 2026-09-15', 'PEP 2026-09-04'])
  })
})

describe('piezas', () => {
  it('la familia del broker junta la cuenta en pesos y la en dólares', () => {
    expect([...familiaDeBroker('Balanz', BROKERS)].sort()).toEqual(['Balanz', 'Balanz · USD'])
    expect([...familiaDeBroker('Balanz · USD', BROKERS)].sort()).toEqual(['Balanz', 'Balanz · USD'])
    expect([...familiaDeBroker('Cocos', BROKERS)]).toEqual(['Cocos'])
  })

  it('yaRegistrado mira la ventana desde el corte', () => {
    const fam = new Set(['Balanz', 'Balanz · USD'])
    const op = (date) => [{ op_type: 'Dividendo', broker: 'Balanz', asset: 'KO', date, pnl_usd: 10 }]
    const q = { familia: fam, ticker: 'KO', exDate: '2026-09-15', neto: 10 }
    expect(yaRegistrado(op('2026-09-14'), q, REGLAS)).toBe(false)   // antes del corte: otro pago
    expect(yaRegistrado(op('2026-10-30'), q, REGLAS)).toBe(true)
    expect(yaRegistrado(op('2026-11-01'), q, REGLAS)).toBe(false)   // pasó la ventana
  })

  it('pide al servidor sólo los CEDEARs con ratio exacto', () => {
    expect(tickersParaHistorial([lote(), lote({ asset: 'SPY' }), lote({ asset: 'NO_EXISTE_XYZ' }),
      { asset: 'ARS', is_cash: 1, broker: 'Balanz', quantity: 1 }])).toEqual(['KO', 'SPY'])
  })
})
