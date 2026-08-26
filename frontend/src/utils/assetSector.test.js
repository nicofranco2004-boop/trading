import { describe, it, expect } from 'vitest'
import { classifySector, computeSectorBreakdown, SECTOR_META } from './assetSector.js'
import {
  STOCKS_US, CEDEARS_LIST, ARG_LIDER, ARG_GENERAL, ETFS,
} from './tickers.js'

const BROKERS = [
  { name: 'Balanz', currency: 'ARS' },
  { name: 'Balanz · USD', currency: 'USD' },
  { name: 'Schwab', currency: 'USD' },
  { name: 'Binance', currency: 'USD' },
]

const pos = (asset, broker, extra = {}) => ({ asset, broker, is_cash: 0, ...extra })

describe('classifySector — lo que no tiene sector no se fuerza a tenerlo', () => {
  it('los bonos van a renta fija, no a "sin dato"', () => {
    // Ésta es LA causa del 72% de "Otros" del mapa del backend: le pregunta
    // el sector a instrumentos que no tienen.
    expect(classifySector(pos('AL30', 'Balanz'), BROKERS)).toBe('renta_fija')
    expect(classifySector(pos('YCA0O', 'Balanz'), BROKERS)).toBe('renta_fija')
    expect(classifySector(pos('LECAPSA', 'Balanz'), BROKERS)).toBe('renta_fija')
    expect(classifySector(pos('TLT', 'Schwab'), BROKERS)).toBe('renta_fija')
  })

  it('FCI, cripto y efectivo tienen su propia porción', () => {
    expect(classifySector(pos('FCI:FIMA-PREMIUM-A', 'Balanz'), BROKERS)).toBe('fci')
    expect(classifySector(pos('BTC', 'Binance'), BROKERS)).toBe('cripto')
    expect(classifySector(pos('USDT', 'Binance'), BROKERS)).toBe('efectivo')
    expect(classifySector(pos('ARS', 'Balanz', { is_cash: 1 }), BROKERS)).toBe('efectivo')
  })
})

describe('classifySector — acciones y CEDEARs', () => {
  it('un CEDEAR expone al MISMO sector que su subyacente', () => {
    expect(classifySector(pos('NVDA', 'Balanz'), BROKERS)).toBe('semis')
    expect(classifySector(pos('NVDA', 'Schwab'), BROKERS)).toBe('semis')
  })

  it('separa semiconductores de tecnología', () => {
    expect(classifySector(pos('AMD', 'Schwab'), BROKERS)).toBe('semis')
    expect(classifySector(pos('TSM', 'Schwab'), BROKERS)).toBe('semis')
    expect(classifySector(pos('MSFT', 'Schwab'), BROKERS)).toBe('tecnologia')
  })

  it('acciones argentinas caen en su sector real', () => {
    expect(classifySector(pos('GGAL', 'Balanz'), BROKERS)).toBe('financiero')
    expect(classifySector(pos('YPFD', 'Balanz'), BROKERS)).toBe('energia')
    expect(classifySector(pos('ALUA', 'Balanz'), BROKERS)).toBe('materiales')
    expect(classifySector(pos('CEPU', 'Balanz'), BROKERS)).toBe('utilities')
    expect(classifySector(pos('IRSA', 'Balanz'), BROKERS)).toBe('inmobiliario')
  })

  it('un ADR argentino comparte sector con la acción local', () => {
    expect(classifySector(pos('YPF', 'Schwab'), BROKERS)).toBe('energia')
    expect(classifySector(pos('TGS', 'Schwab'), BROKERS)).toBe('utilities')
  })

  it('un ETF sectorial va a su sector, no a "diversificado"', () => {
    // Comprar XLE es una apuesta a energía, no diversificación.
    expect(classifySector(pos('XLE', 'Schwab'), BROKERS)).toBe('energia')
    expect(classifySector(pos('SOXX', 'Schwab'), BROKERS)).toBe('semis')
    expect(classifySector(pos('SPY', 'Schwab'), BROKERS)).toBe('diversificado')
  })

  it('un equity desconocido NO se adivina', () => {
    // VXUS es un ETF real, pero no está en el allowlist de la app: no hay
    // forma de saber que lo es. "Sin dato" es la respuesta correcta — la UI
    // lo lista para que se pueda agregar al universo curado.
    expect(classifySector(pos('VXUS', 'Schwab'), BROKERS)).toBe('sin_dato')
    expect(classifySector(pos('ZZZQ', 'Schwab'), BROKERS)).toBe('sin_dato')
  })
})

describe('cobertura del mapa sectorial', () => {
  // El guard que importa: si alguien agrega un ticker al universo curado sin
  // darle sector, la torta lo muestra como "Sin dato" y este test lo avisa
  // antes de que llegue a producción.
  const universes = {
    STOCKS_US: STOCKS_US.map(x => x.s),
    CEDEARS_LIST: CEDEARS_LIST.map(x => x.s),
    ARG_LIDER: ARG_LIDER.map(x => x.s),
    ARG_GENERAL: ARG_GENERAL.map(x => x.s),
    ETFS: ETFS.map(x => x.s),
  }

  for (const [name, tickers] of Object.entries(universes)) {
    it(`${name}: todos los tickers tienen sector`, () => {
      const broker = name.startsWith('ARG') ? 'Balanz' : 'Schwab'
      const missing = tickers.filter(t => {
        const s = classifySector(pos(t, broker), BROKERS)
        // 'diversificado' es un default legítimo para ETFs; 'renta_fija' lo es
        // para los ETFs de bonos (TLT, AGG…), que se clasifican como bono.
        return s === 'sin_dato'
      })
      expect(missing).toEqual([])
    })
  }
})

describe('computeSectorBreakdown', () => {
  const positions = [
    { asset: 'NVDA', broker: 'Balanz', value_usd: 300 },   // semis
    { asset: 'AAPL', broker: 'Balanz', value_usd: 200 },   // tecnologia
    { asset: 'GGAL', broker: 'Balanz', value_usd: 200 },   // financiero
    { asset: 'AL30', broker: 'Balanz', value_usd: 200 },   // renta_fija
    { asset: 'ARS',  broker: 'Balanz', is_cash: 1, value_usd: 100 },  // efectivo
  ]

  it('agrega por sector con porcentajes sobre el total', () => {
    const { items, total } = computeSectorBreakdown(positions, BROKERS)
    expect(total).toBe(1000)
    const byKey = Object.fromEntries(items.map(i => [i.key, i.pct]))
    expect(byKey.semis).toBe(30)
    expect(byKey.tecnologia).toBe(20)
    expect(byKey.financiero).toBe(20)
    expect(byKey.renta_fija).toBe(20)
    expect(byKey.efectivo).toBe(10)
  })

  it('los porcentajes suman 100', () => {
    const { items } = computeSectorBreakdown(positions, BROKERS)
    expect(items.reduce((s, i) => s + i.pct, 0)).toBeCloseTo(100, 6)
  })

  it('el plazo fijo entra como renta fija vía extraSlices', () => {
    const { items, total } = computeSectorBreakdown(
      positions, BROKERS, [{ key: 'renta_fija', value: 1000 }],
    )
    expect(total).toBe(2000)
    const rf = items.find(i => i.key === 'renta_fija')
    expect(rf.value).toBe(1200)
    expect(rf.pct).toBe(60)
  })

  it('reporta lo desconocido con los tickers', () => {
    const { unclassified } = computeSectorBreakdown(
      [...positions, { asset: 'ZZZQ', broker: 'Schwab', value_usd: 1000 }], BROKERS,
    )
    expect(unclassified.value).toBe(1000)
    expect(unclassified.assets).toEqual(['ZZZQ'])
  })

  it('cada item trae label y color del vocabulario', () => {
    const { items } = computeSectorBreakdown(positions, BROKERS)
    for (const i of items) {
      expect(i.label).toBe(SECTOR_META[i.key].label)
      expect(i.color).toBe(SECTOR_META[i.key].color)
    }
  })

  it('cartera vacía no explota', () => {
    expect(computeSectorBreakdown([], BROKERS).items).toEqual([])
  })
})

describe('el sufijo de mercado no puede costar el sector', () => {
  it('un CEDEAR con .BA cuenta en el sector de su subyacente', () => {
    // Rendi guarda el activo sin sufijo, pero no todos los importadores
    // respetan la convención. Un AMD.BA sin sector era un agujero silencioso.
    expect(classifySector(pos('AMD.BA', 'Balanz', { asset_type: 'CEDEAR' }), BROKERS)).toBe('semis')
    expect(classifySector(pos('NVDA.BA', 'Balanz'), BROKERS)).toBe('semis')
    expect(classifySector(pos('GGAL.BA', 'Balanz'), BROKERS)).toBe('financiero')
  })

  it('el CEDEAR y la acción del mismo subyacente comparten sector', () => {
    // El eje TIPO los separa (cedear vs accion_us); el eje SECTOR no debe.
    expect(classifySector(pos('AMD', 'Balanz', { asset_type: 'CEDEAR' }), BROKERS)).toBe('semis')
    expect(classifySector(pos('AMD', 'Schwab'), BROKERS)).toBe('semis')
  })

  it('la pata en dólares de un bono sigue siendo renta fija', () => {
    // AL30D es el mismo bono que AL30, liquidado en dólares.
    expect(classifySector(pos('AL30D', 'Balanz'), BROKERS)).toBe('renta_fija')
    expect(classifySector(pos('GD30C', 'Balanz'), BROKERS)).toBe('renta_fija')
  })
})
