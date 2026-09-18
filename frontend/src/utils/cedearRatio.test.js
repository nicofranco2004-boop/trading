// Tests de cedearRatio — la conversión "tenencia → acciones del subyacente".
//
// El caso que originó el módulo está abajo con los números REALES del reporte
// del usuario (2026-09-17): Rendi anunciaba US$40 de dividendo de GOOGL y el
// broker depositó US$0,70.
import { describe, it, expect, beforeEach } from 'vitest'
import { setBrokersRegistry } from './valuation'
import {
  CEDEAR_RATIOS, CEDEAR_RATIO_DESCONOCIDO, AR_ADR_RATIOS,
  cedearRatio, arAdrRatio, deriveCedearRatio,
  underlyingShares, underlyingSharesForTicker,
} from './cedearRatio'

const BROKERS = [
  { id: 1, name: 'Balanz',        currency: 'ARS' },
  { id: 2, name: 'Balanz · USD',  currency: 'USD', parent_broker_id: 1 },
  { id: 3, name: 'Schwab',        currency: 'USD' },
]
beforeEach(() => setBrokersRegistry(BROKERS))

const pos = (o) => ({ asset: 'GOOGL', quantity: 100, broker: 'Balanz', is_cash: 0, ...o })

describe('la tabla', () => {
  it('tiene los dos ratios verificados contra el caso real del usuario', () => {
    expect(CEDEAR_RATIOS.GOOGL).toBe(58)
    expect(CEDEAR_RATIOS.AVGO).toBe(39)
  })

  it('admite ratios fraccionarios (1 CEDEAR = varias acciones)', () => {
    expect(CEDEAR_RATIOS.ABEV).toBeCloseTo(1 / 3, 6)
    expect(CEDEAR_RATIOS.SPCE).toBeCloseTo(0.5, 6)
  })

  it('BAC lleva el ratio de Bank of America, no el de Boeing', () => {
    // En BYMA el símbolo 'BAC' es la pata cable de Boeing, así que derivarlo del
    // precio da 10.269. El ratio correcto (4) viene de la lista de Comafi, y el
    // derivado tiene que quedar descartado — ver el test de cotas más abajo.
    expect(CEDEAR_RATIOS.BAC).toBe(4)
  })

  it('lo que no se pudo determinar queda listado, no adivinado', () => {
    expect(CEDEAR_RATIO_DESCONOCIDO.size).toBeGreaterThan(0)
    for (const t of CEDEAR_RATIO_DESCONOCIDO) expect(CEDEAR_RATIOS[t]).toBeUndefined()
  })

  it('cedearRatio devuelve null para lo desconocido, no un número inventado', () => {
    expect(cedearRatio('GOOGL')).toBe(58)
    expect(cedearRatio('NO_EXISTE_XYZ')).toBeNull()
    expect(cedearRatio(null)).toBeNull()
  })

  it('las acciones argentinas van por el ratio del ADR', () => {
    expect(AR_ADR_RATIOS.GGAL).toBe(10)
    expect(arAdrRatio('BBAR')).toBe(3)
    expect(arAdrRatio('PAMP')).toBeNull()   // sin ADR de mismo símbolo → sin evento
  })
})

describe('underlyingShares — el bug del usuario', () => {
  it('130 CEDEARs de AVGO son 3,33 acciones, no 130', () => {
    const eq = underlyingShares(pos({ asset: 'AVGO', quantity: 130 }))
    expect(eq.ratio).toBe(39)
    expect(eq.shares).toBeCloseTo(130 / 39, 6)
    // El cobro que publicaba Rendi vs el real, con el dividendo de la captura:
    expect(130 * 0.65).toBeCloseTo(84.5, 2)          // lo que decía la app
    expect(eq.shares * 0.65).toBeCloseTo(2.17, 2)    // lo que corresponde
  })

  it('el caso GOOGL reconcilia con lo que depositó el broker', () => {
    // El usuario vio ~US$40 con un dividendo de US$0,21 → tenía ~190 CEDEARs.
    const eq = underlyingShares(pos({ asset: 'GOOGL', quantity: 190 }))
    expect(190 * 0.21).toBeCloseTo(39.9, 1)          // lo que decía la app
    expect(eq.shares * 0.21).toBeCloseTo(0.69, 2)    // el broker depositó 0,70
  })

  it('una acción real en un broker en dólares NO se divide', () => {
    const eq = underlyingShares(pos({ asset: 'AVGO', quantity: 130, broker: 'Schwab' }))
    expect(eq.ratio).toBe(1)
    expect(eq.shares).toBe(130)
    expect(eq.scale).toBe('share')
  })

  it('un sub-broker "· USD" de un padre argentino SIGUE siendo BYMA', () => {
    // Comprar el CEDEAR por dólar-MEP no lo convierte en la acción US.
    const eq = underlyingShares(pos({ asset: 'AVGO', quantity: 130, broker: 'Balanz · USD' }))
    expect(eq.ratio).toBe(39)
  })

  it('asset_type CEDEAR manda aunque el broker no sea argentino', () => {
    const eq = underlyingShares(pos({ asset: 'AAPL', quantity: 40, broker: 'Schwab', asset_type: 'CEDEAR' }))
    expect(eq.ratio).toBe(20)
    expect(eq.shares).toBe(2)
  })

  it('acción argentina local: 5.000 GGAL son 500 ADRs', () => {
    const eq = underlyingShares(pos({ asset: 'GGAL', quantity: 5000 }))
    expect(eq.scale).toBe('adr')
    expect(eq.shares).toBe(500)
  })

  it('sin ratio conocido devuelve null — no adivina', () => {
    expect(underlyingShares(pos({ asset: 'ZZZZ', quantity: 100 }))).toBeNull()
  })

  it('cash y cantidad 0 quedan afuera', () => {
    expect(underlyingShares(pos({ is_cash: 1 }))).toBeNull()
    expect(underlyingShares(pos({ quantity: 0 }))).toBeNull()
  })
})

describe('deriveCedearRatio — el respaldo cuando la tabla no cubre', () => {
  const prices = { GOOGL: 347.45, 'GOOGL.BA': 9565 }

  it('deriva del precio con el orden de magnitud correcto', () => {
    const r = deriveCedearRatio('GOOGL', prices, 1533.8)
    expect(r).toBeGreaterThan(50)
    expect(r).toBeLessThan(60)
  })

  it('sin uno de los dos precios devuelve null', () => {
    expect(deriveCedearRatio('GOOGL', { GOOGL: 347.45 }, 1533.8)).toBeNull()
    expect(deriveCedearRatio('GOOGL', { 'GOOGL.BA': 9565 }, 1533.8)).toBeNull()
    expect(deriveCedearRatio('GOOGL', prices, 0)).toBeNull()
  })

  it('rechaza el resultado absurdo en vez de propagarlo', () => {
    // El caso BAC/Boeing daba 10.269: dos instrumentos distintos bajo el mismo
    // símbolo. Un ratio así no es un ratio.
    expect(deriveCedearRatio('BAC', { BAC: 58.18, 'BAC.BA': 8.69 }, 1533.8)).toBeNull()
  })

  it('se usa SOLO si la tabla no tiene el símbolo', () => {
    // GOOGL está en la tabla → gana 58 exacto, no el derivado con sesgo.
    const eq = underlyingShares(pos({ asset: 'GOOGL', quantity: 58 }), { prices, tc: 1533.8 })
    expect(eq.source).toBe('table')
    expect(eq.shares).toBe(1)
  })
})

describe('underlyingSharesForTicker — la misma empresa en dos escalas', () => {
  it('suma CEDEAR y acción real en la escala correcta', () => {
    const positions = [
      { asset: 'AVGO', quantity: 39, broker: 'Balanz', is_cash: 0 },   // 39 CEDEARs = 1 acción
      { asset: 'AVGO', quantity: 2,  broker: 'Schwab', is_cash: 0 },   // 2 acciones reales
    ]
    const r = underlyingSharesForTicker(positions, 'AVGO')
    expect(r.shares).toBeCloseTo(3, 6)   // NO 41
    expect(r.partial).toBe(false)
    expect([...r.scales].sort()).toEqual(['cedear', 'share'])
  })

  it('marca partial cuando alguna posición no tiene ratio', () => {
    const positions = [
      { asset: 'ZZZZ', quantity: 100, broker: 'Balanz', is_cash: 0 },
      { asset: 'ZZZZ', quantity: 5,   broker: 'Schwab', is_cash: 0 },
    ]
    const r = underlyingSharesForTicker(positions, 'ZZZZ')
    expect(r.partial).toBe(true)
    expect(r.shares).toBe(5)   // sólo lo que sí supimos convertir
  })

  it('ignora posiciones de otros tickers y el cash', () => {
    const positions = [
      { asset: 'AVGO', quantity: 39,   broker: 'Balanz', is_cash: 0 },
      { asset: 'GOOGL', quantity: 580, broker: 'Balanz', is_cash: 0 },
      { asset: 'USDT', quantity: 1000, broker: 'Balanz', is_cash: 1 },
    ]
    expect(underlyingSharesForTicker(positions, 'AVGO').shares).toBeCloseTo(1, 6)
    expect(underlyingSharesForTicker(positions, 'GOOGL').shares).toBeCloseTo(10, 6)
  })
})

// ════════════════════════════════════════════════════════════════════════════
// El registro de brokers vacío — el agujero por el que el bug volvía entero.
//
// `setBrokersRegistry([])` corre en CADA login, y sólo algunas pantallas lo
// repueblan. Reproducido en la app el 2026-09-17: entrando derecho a Novedades,
// un CEDEAR sin asset_type ni currency volvía a mostrar US$84,50.
// ════════════════════════════════════════════════════════════════════════════
describe('registro de brokers vacío', () => {
  beforeEach(() => setBrokersRegistry([]))

  it('un CEDEAR sin señal propia NO se cuenta como acción: devuelve null', () => {
    const p = { asset: 'AVGO', quantity: 130, broker: 'Balanz', is_cash: 0 }
    expect(underlyingShares(p)).toBeNull()
  })

  it('con asset_type marcado sí se puede decidir, aunque falte el registro', () => {
    const p = { asset: 'AVGO', quantity: 130, broker: 'Balanz', is_cash: 0, asset_type: 'CEDEAR' }
    expect(underlyingShares(p).ratio).toBe(39)
  })

  it('con el lote en pesos también', () => {
    const p = { asset: 'AVGO', quantity: 130, broker: 'Balanz', is_cash: 0, currency: 'ARS' }
    expect(underlyingShares(p).ratio).toBe(39)
  })

  it('un ticker que NO es CEDEAR no se ve afectado por el guard', () => {
    // ZZZZ no está en el universo de CEDEARs: no hay ambigüedad que resolver.
    const p = { asset: 'ZZZZ', quantity: 10, broker: 'Schwab', is_cash: 0 }
    expect(underlyingShares(p).shares).toBe(10)
  })
})
