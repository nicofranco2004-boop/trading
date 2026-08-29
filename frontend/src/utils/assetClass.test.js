import { describe, it, expect } from 'vitest'
import { classifyAsset, computeClassBreakdown, ASSET_CLASS_META } from './assetClass.js'

// Brokers como los devuelve GET /api/brokers.
const BROKERS = [
  { name: 'Balanz', currency: 'ARS' },
  { name: 'Balanz · USD', currency: 'USD' },   // sub-broker MEP → sigue siendo BYMA
  { name: 'Cocos', currency: 'ARS' },
  { name: 'Schwab', currency: 'USD' },
  { name: 'Binance', currency: 'USD' },
]

const pos = (asset, broker, extra = {}) => ({ asset, broker, is_cash: 0, ...extra })

describe('classifyAsset — el mercado decide qué significa el ticker', () => {
  it('el mismo ticker es CEDEAR en un broker AR y acción US en el exterior', () => {
    expect(classifyAsset(pos('AAPL', 'Balanz'), BROKERS)).toBe('cedear')
    expect(classifyAsset(pos('AAPL', 'Schwab'), BROKERS)).toBe('accion_us')
  })

  it('SPY es CEDEAR en BYMA y ETF en el exterior', () => {
    expect(classifyAsset(pos('SPY', 'Cocos'), BROKERS)).toBe('cedear')
    expect(classifyAsset(pos('SPY', 'Schwab'), BROKERS)).toBe('etf')
  })

  it('el sub-broker "· USD" es BYMA aunque la moneda sea USD', () => {
    expect(classifyAsset(pos('MSFT', 'Balanz · USD'), BROKERS)).toBe('cedear')
    expect(classifyAsset(pos('PAMP', 'Balanz · USD'), BROKERS)).toBe('accion_ar')
  })

  it('acciones argentinas del panel local NO son CEDEARs', () => {
    expect(classifyAsset(pos('GGAL', 'Balanz'), BROKERS)).toBe('accion_ar')
    expect(classifyAsset(pos('YPFD', 'Cocos'), BROKERS)).toBe('accion_ar')
    expect(classifyAsset(pos('MIRG', 'Balanz'), BROKERS)).toBe('accion_ar')
  })

  it('un ADR argentino en un broker del exterior sigue siendo acción AR', () => {
    expect(classifyAsset(pos('YPF', 'Schwab'), BROKERS)).toBe('accion_ar')
    expect(classifyAsset(pos('GGAL', 'Schwab'), BROKERS)).toBe('accion_ar')
  })
})

describe('classifyAsset — renta fija', () => {
  it('soberanos AR', () => {
    expect(classifyAsset(pos('AL30', 'Balanz'), BROKERS)).toBe('bono')
    expect(classifyAsset(pos('GD30', 'Balanz'), BROKERS)).toBe('bono')
    expect(classifyAsset(pos('TZX28', 'Cocos'), BROKERS)).toBe('bono')
  })

  it('ONs — las del allowlist y las que solo matchean el patrón', () => {
    expect(classifyAsset(pos('YCA0O', 'Balanz'), BROKERS)).toBe('bono')
    expect(classifyAsset(pos('MGC9O', 'Balanz'), BROKERS)).toBe('bono')  // fuera del allowlist
  })

  it('letras: por prefijo y por formato fecha', () => {
    expect(classifyAsset(pos('LECAPSA', 'Balanz'), BROKERS)).toBe('bono')
    expect(classifyAsset(pos('S31E5', 'Balanz'), BROKERS)).toBe('bono')
  })

  it('respeta el asset_type de renta fija venga como venga', () => {
    expect(classifyAsset(pos('XXYY', 'Balanz', { asset_type: 'BOND' }), BROKERS)).toBe('bono')
    expect(classifyAsset(pos('XXYY', 'Balanz', { asset_type: 'letra' }), BROKERS)).toBe('bono')
  })

  it('NO marca como bono a una acción argentina que empieza con prefijo de bono', () => {
    // Regresión: la heurística de profileAllocations.js manda TGSU2 y TGNO4
    // (Transportadora de Gas — acciones) a fixed_income por el prefijo 'TG'.
    expect(classifyAsset(pos('TGSU2', 'Balanz'), BROKERS)).toBe('accion_ar')
    expect(classifyAsset(pos('TGNO4', 'Balanz'), BROKERS)).toBe('accion_ar')
  })

  it('NO marca como bono a Paramount', () => {
    // Regresión: inferType() manda 'PARA' a bono por el prefijo 'PAR'.
    expect(classifyAsset(pos('PARA', 'Schwab'), BROKERS)).toBe('accion_us')
  })
})

describe('classifyAsset — cripto y efectivo', () => {
  it('cripto por la lista que gobierna la valuación', () => {
    expect(classifyAsset(pos('BTC', 'Binance'), BROKERS)).toBe('cripto')
    expect(classifyAsset(pos('eth', 'Binance'), BROKERS)).toBe('cripto')
    // Regresión: inferType() devolvía 'stock_us' para SUSHI (está en la lista
    // CRYPTO del propio tickers.js, pero inferType no la consulta).
    expect(classifyAsset(pos('SUSHI', 'Binance'), BROKERS)).toBe('cripto')
  })

  it('los stablecoins son efectivo, no cripto', () => {
    expect(classifyAsset(pos('USDT', 'Binance'), BROKERS)).toBe('cash')
    expect(classifyAsset(pos('USDC', 'Binance'), BROKERS)).toBe('cash')
  })

  it('is_cash gana sobre todo lo demás', () => {
    expect(classifyAsset(pos('ARS', 'Balanz', { is_cash: 1 }), BROKERS)).toBe('cash')
    expect(classifyAsset(pos('USDT', 'Balanz · USD', { is_cash: 1 }), BROKERS)).toBe('cash')
  })
})

describe('classifyAsset — FCI', () => {
  it('reconoce el símbolo canónico y el tipo del importador', () => {
    expect(classifyAsset(pos('FCI:FIMA-PREMIUM-A', 'Balanz'), BROKERS)).toBe('fci')
    expect(classifyAsset(pos('BCMMA', 'Balanz', { asset_type: 'FUND' }), BROKERS)).toBe('fci')
  })

  it('un FCI propietario sin tipo queda sin clasificar (no se adivina)', () => {
    // Códigos internos de Balanz: no hay patrón que los distinga de una acción.
    // Que caigan en 'otro' es el comportamiento correcto — la UI los lista.
    expect(classifyAsset(pos('INSTITUA', 'Balanz'), BROKERS)).toBe('otro')
    expect(classifyAsset(pos('BCMMA', 'Balanz'), BROKERS)).toBe('otro')
  })
})

describe('classifyAsset — higiene del asset_type', () => {
  it('es case-insensitive', () => {
    // Hay una fila real en la DB con asset_type='cedear' en minúscula.
    expect(classifyAsset(pos('AAPL', 'Balanz', { asset_type: 'cedear' }), BROKERS)).toBe('cedear')
    expect(classifyAsset(pos('AAPL', 'Balanz', { asset_type: 'CEDEAR' }), BROKERS)).toBe('cedear')
  })

  it('asset_type=CEDEAR marca mercado AR aunque no conozcamos el broker', () => {
    expect(classifyAsset(pos('NU', 'BrokerRaro', { asset_type: 'CEDEAR' }), [])).toBe('cedear')
  })
})

describe('classifyAsset — desconocidos: la asimetría es deliberada', () => {
  it('desconocido en broker AR → sin clasificar', () => {
    expect(classifyAsset(pos('ZZZQ', 'Balanz'), BROKERS)).toBe('otro')
  })

  it('desconocido en broker del exterior → acción US', () => {
    expect(classifyAsset(pos('ARM', 'Schwab'), BROKERS)).toBe('accion_us')
  })

  it('entradas inválidas no explotan', () => {
    expect(classifyAsset(null, BROKERS)).toBe('otro')
    expect(classifyAsset(pos('', 'Balanz'), BROKERS)).toBe('otro')
    expect(classifyAsset(pos('AAPL', 'Schwab'))).toBe('accion_us')  // sin brokers
  })
})

describe('computeClassBreakdown', () => {
  const positions = [
    { asset: 'AAPL', broker: 'Balanz', value_usd: 400 },      // cedear
    { asset: 'GGAL', broker: 'Balanz', value_usd: 200 },      // accion_ar
    { asset: 'AL30', broker: 'Balanz', value_usd: 200 },      // bono
    { asset: 'BTC',  broker: 'Binance', value_usd: 100 },     // cripto
    { asset: 'ARS',  broker: 'Balanz', is_cash: 1, value_usd: 100 },  // cash
  ]

  it('agrega por clase y devuelve porcentajes sobre el total', () => {
    const { items, total } = computeClassBreakdown(positions, BROKERS)
    expect(total).toBe(1000)
    const byKey = Object.fromEntries(items.map(i => [i.key, i.pct]))
    expect(byKey.cedear).toBe(40)
    expect(byKey.accion_ar).toBe(20)
    expect(byKey.bono).toBe(20)
    expect(byKey.cripto).toBe(10)
    expect(byKey.cash).toBe(10)
  })

  it('los porcentajes suman 100', () => {
    const { items } = computeClassBreakdown(positions, BROKERS)
    const sum = items.reduce((s, i) => s + i.pct, 0)
    expect(sum).toBeCloseTo(100, 6)
  })

  it('respeta el orden del vocabulario, no el del input', () => {
    const { items } = computeClassBreakdown(positions, BROKERS)
    expect(items.map(i => i.key)).toEqual(['cedear', 'accion_ar', 'bono', 'cripto', 'cash'])
  })

  it('cada item trae label y color del vocabulario', () => {
    const { items } = computeClassBreakdown(positions, BROKERS)
    for (const i of items) {
      expect(i.label).toBe(ASSET_CLASS_META[i.key].label)
      expect(i.color).toBe(ASSET_CLASS_META[i.key].color)
    }
  })

  it('ignora posiciones sin valor de mercado resuelto', () => {
    const { total } = computeClassBreakdown(
      [...positions, { asset: 'MSFT', broker: 'Balanz', value_usd: null },
                     { asset: 'TSLA', broker: 'Balanz', value_usd: 0 }],
      BROKERS,
    )
    expect(total).toBe(1000)
  })

  it('reporta lo que quedó sin clasificar, con los tickers', () => {
    const { unclassified } = computeClassBreakdown(
      [...positions, { asset: 'INSTITUA', broker: 'Balanz', value_usd: 250 },
                     { asset: 'BCMMA', broker: 'Balanz', value_usd: 250 }],
      BROKERS,
    )
    expect(unclassified.value).toBe(500)
    expect(unclassified.pct).toBeCloseTo(33.33, 1)
    expect(unclassified.assets).toEqual(['BCMMA', 'INSTITUA'])
  })

  it('cartera vacía devuelve estructura vacía, no null', () => {
    const r = computeClassBreakdown([], BROKERS)
    expect(r.items).toEqual([])
    expect(r.total).toBe(0)
    expect(r.unclassified.pct).toBe(0)
  })
})

describe('detalle por activo dentro de cada porción', () => {
  const BR = [
    { name: 'Balanz', currency: 'ARS' },
    { name: 'Schwab', currency: 'USD' },
    { name: 'IBKR', currency: 'USD' },
  ]

  it('cada porción trae los activos que la componen, ordenados desc', () => {
    const { items } = computeClassBreakdown([
      { asset: 'AAPL', broker: 'Balanz', asset_type: 'CEDEAR', value_usd: 100 },
      { asset: 'NVDA', broker: 'Balanz', asset_type: 'CEDEAR', value_usd: 300 },
      { asset: 'MSFT', broker: 'Balanz', asset_type: 'CEDEAR', value_usd: 200 },
    ], BR)
    const cedear = items.find(i => i.key === 'cedear')
    expect(cedear.assets.map(a => a.asset)).toEqual(['NVDA', 'MSFT', 'AAPL'])
    expect(cedear.assets.map(a => a.value)).toEqual([300, 200, 100])
  })

  it('los % de los hijos suman el % del padre', () => {
    const { items } = computeClassBreakdown([
      { asset: 'AAPL', broker: 'Schwab', value_usd: 300 },
      { asset: 'AMD',  broker: 'Schwab', value_usd: 200 },
      { asset: 'AL30', broker: 'Balanz', asset_type: 'BOND', value_usd: 500 },
    ], BR)
    for (const it of items) {
      expect(it.assets.reduce((s, a) => s + a.pct, 0)).toBeCloseTo(it.pct, 6)
      expect(it.assets.reduce((s, a) => s + a.value, 0)).toBeCloseTo(it.value, 6)
    }
  })

  it('consolida el mismo ticker en dos brokers de la MISMA clase', () => {
    const { items } = computeClassBreakdown([
      { asset: 'AAPL', broker: 'Schwab', value_usd: 300 },
      { asset: 'AAPL', broker: 'IBKR',   value_usd: 200 },
    ], BR)
    const us = items.find(i => i.key === 'accion_us')
    expect(us.assets).toMatchObject([{ asset: 'AAPL', value: 500, pct: 100 }])
  })

  it('NO mezcla el mismo ticker cuando cae en clases distintas', () => {
    // El caso que motivó todo: AAPL en Balanz es un CEDEAR, en Schwab es la acción.
    const { items } = computeClassBreakdown([
      { asset: 'AAPL', broker: 'Balanz', asset_type: 'CEDEAR', value_usd: 400 },
      { asset: 'AAPL', broker: 'Schwab', value_usd: 600 },
    ], BR)
    expect(items.find(i => i.key === 'cedear').assets).toMatchObject([{ asset: 'AAPL', value: 400, pct: 40 }])
    expect(items.find(i => i.key === 'accion_us').assets).toMatchObject([{ asset: 'AAPL', value: 600, pct: 60 }])
  })

  it('las porciones sintéticas (plazo fijo) no traen detalle', () => {
    const { items } = computeClassBreakdown(
      [{ asset: 'AAPL', broker: 'Schwab', value_usd: 500 }], BR,
      [{ key: 'plazo_fijo', value: 500 }],
    )
    expect(items.find(i => i.key === 'plazo_fijo').assets).toEqual([])
  })
})

describe('normalización del ticker', () => {
  const BR = [{ name: 'Balanz', currency: 'ARS' }, { name: 'Schwab', currency: 'USD' }]

  it('el sufijo .BA no cambia la clase', () => {
    expect(classifyAsset({ asset: 'AMD.BA', broker: 'Balanz', asset_type: 'CEDEAR' }, BR)).toBe('cedear')
    expect(classifyAsset({ asset: 'GGAL.BA', broker: 'Balanz' }, BR)).toBe('accion_ar')
  })

  it('la pata en dólares de un bono del allowlist se reconoce', () => {
    expect(classifyAsset({ asset: 'AL30D', broker: 'Balanz' }, BR)).toBe('bono')
    expect(classifyAsset({ asset: 'GD30C', broker: 'Balanz' }, BR)).toBe('bono')
  })

  it('NO barre tickers que terminan en D o C por casualidad', () => {
    // El sufijo solo cuenta si el ticker pelado está en el allowlist de bonos.
    expect(classifyAsset({ asset: 'DOC', broker: 'Schwab' }, BR)).toBe('accion_us')
    expect(classifyAsset({ asset: 'GOOD', broker: 'Schwab' }, BR)).toBe('accion_us')
  })
})

// ─── El mercado pre-resuelto (libro del asesor) ─────────────────────────────
// La fila del endpoint /advisor/book/composition no trae broker ni lista de
// brokers: trae `is_ar_market` ya decidido por el backend. La prueba que
// importa no es "clasifica algo", es que clasifique EXACTAMENTE IGUAL que la
// misma posición con un broker de verdad — si divergen, la torta del asesor y
// la del cliente muestran cosas distintas para la misma cartera, que es el
// bug entero que este parámetro existe para evitar.
describe('classifyAsset — is_ar_market pre-resuelto', () => {
  const preAr = (asset, extra = {}) => ({ asset, is_ar_market: true, is_cash: 0, ...extra })
  const preUs = (asset, extra = {}) => ({ asset, is_ar_market: false, is_cash: 0, ...extra })

  it('paridad con un broker ARS: mismo veredicto sin lista de brokers', () => {
    for (const t of ['AAPL', 'SPY', 'GGAL', 'YPFD', 'MIRG', 'NVDA', 'MELI']) {
      expect(classifyAsset(preAr(t), [])).toBe(classifyAsset(pos(t, 'Balanz'), BROKERS))
    }
  })

  it('paridad con un broker del exterior', () => {
    for (const t of ['AAPL', 'SPY', 'YPF', 'GGAL', 'NVDA', 'QQQ']) {
      expect(classifyAsset(preUs(t), [])).toBe(classifyAsset(pos(t, 'Schwab'), BROKERS))
    }
  })

  it('paridad con el sub-broker "· USD" (BYMA con moneda USD)', () => {
    expect(classifyAsset(preAr('MSFT'), [])).toBe(classifyAsset(pos('MSFT', 'Balanz · USD'), BROKERS))
    expect(classifyAsset(preAr('PAMP'), [])).toBe(classifyAsset(pos('PAMP', 'Balanz · USD'), BROKERS))
  })

  it('el flag decide el mercado: AAPL es CEDEAR con true y acción US con false', () => {
    expect(classifyAsset(preAr('AAPL'), [])).toBe('cedear')
    expect(classifyAsset(preUs('AAPL'), [])).toBe('accion_us')
  })

  it('is_ar_market:false NO fuerza a "otro" un ticker AR desconocido — cae a accion_us', () => {
    // La asimetría de la rama del exterior se mantiene: el flag elige la rama,
    // no cortocircuita el resto del clasificador.
    expect(classifyAsset(preUs('ZZZZ'), [])).toBe('accion_us')
    expect(classifyAsset(preAr('ZZZZ'), [])).toBe('otro')
  })

  it('no pisa las reglas que corren ANTES del mercado', () => {
    // Bono, cripto, FCI y stablecoin se resuelven sin mirar el mercado: el
    // flag no puede cambiarlos.
    expect(classifyAsset(preUs('AL30'), [])).toBe('bono')
    expect(classifyAsset(preAr('BTC'), [])).toBe('cripto')
    expect(classifyAsset(preAr('FCI:FIMA-PREMIUM-A'), [])).toBe('fci')
    expect(classifyAsset(preUs('USDT'), [])).toBe('cash')
    expect(classifyAsset(preUs('ARS', { is_cash: 1 }), [])).toBe('cash')
  })

  it('asset_type CEDEAR sigue mandando aunque el flag diga que no es BYMA', () => {
    // Los dos caminos coinciden en producción (el backend marca is_ar_market
    // en las CEDEAR), pero el orden se mantiene igual que en retail.
    expect(classifyAsset(preUs('AAPL', { asset_type: 'CEDEAR' }), [])).toBe('cedear')
  })

  it('sin el campo, el comportamiento de retail queda intacto', () => {
    expect(classifyAsset({ asset: 'AAPL', broker: 'Balanz', is_cash: 0 }, BROKERS)).toBe('cedear')
    expect(classifyAsset({ asset: 'AAPL', broker: 'Schwab', is_cash: 0, is_ar_market: undefined }, BROKERS)).toBe('accion_us')
    // null se trata como ausente (JSON puede mandarlo).
    expect(classifyAsset({ asset: 'AAPL', broker: 'Balanz', is_cash: 0, is_ar_market: null }, BROKERS)).toBe('cedear')
  })
})
