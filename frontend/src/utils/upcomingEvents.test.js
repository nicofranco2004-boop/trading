import { describe, it, expect, beforeEach } from 'vitest'
import { setBrokersRegistry } from './valuation'
import {
  upcomingBondEvents,
  normalizeBackendEvents,
  mergeEvents,
  groupEventsByDate,
  eventTypeLabel,
  eventTypeIcon,
  eventCategoryColor,
  eventCategoryLabel,
  formatRelativeDate,
  countryFlag,
  isMacroEvent,
  dividendPayout,
} from './upcomingEvents.js'

// ════════════════════════════════════════════════════════════════════════════
// Tests del agregador de eventos futuros para el calendario.
// ════════════════════════════════════════════════════════════════════════════

const POS_AL30 = {
  broker: 'Cocos',
  asset: 'AL30',
  quantity: 1000,
  is_cash: false,
  entry_date: '2024-01-01',
}

const POS_YPF = {
  broker: 'Cocos',
  asset: 'YCA0O',
  quantity: 100,
  is_cash: false,
  entry_date: '2024-01-01',
}

const POS_NON_BOND = {
  broker: 'Cocos',
  asset: 'GGAL',
  quantity: 100,
  is_cash: false,
}

// ─── upcomingBondEvents ──────────────────────────────────────────────────────

describe('upcomingBondEvents', () => {
  it('AL30 con qty=1000 dentro de los próximos 90 días → eventos válidos', () => {
    const events = upcomingBondEvents([POS_AL30], { today: '2026-05-12', windowDays: 90 })
    expect(events.length).toBeGreaterThan(0)
    const next = events[0]
    expect(next.ticker).toBe('AL30')
    expect(next.broker).toBe('Cocos')
    expect(next.eventDate).toBe('2026-07-09')
    expect(next.eventType).toBe('bond_coupon_amort')
    expect(next.details.coupon).toBeGreaterThan(0)
    expect(next.details.amort).toBeGreaterThan(0)
    expect(next.details.currency).toBe('USD')
    expect(next.confirmed).toBe(false)  // teórico
    expect(next.daysAway).toBeGreaterThan(0)
  })

  it('window angosta (7 días) → sin eventos cercanos', () => {
    const events = upcomingBondEvents([POS_AL30], { today: '2026-05-12', windowDays: 7 })
    expect(events).toEqual([])
  })

  it('window larga (365 días) → varios eventos del cronograma AL30', () => {
    const events = upcomingBondEvents([POS_AL30], { today: '2026-05-12', windowDays: 365 })
    // AL30 paga 2026-07-09, 2027-01-09 (semestral) → 2 eventos en 1 año
    expect(events.length).toBe(2)
  })

  it('detecta el vencimiento como "bond_maturity"', () => {
    // AL30 vence 2030-07-09. Si miramos cerca del maturity:
    const events = upcomingBondEvents([POS_AL30], { today: '2030-05-12', windowDays: 90 })
    const maturity = events.find(e => e.eventType === 'bond_maturity')
    expect(maturity).toBeDefined()
    expect(maturity.eventDate).toBe('2030-07-09')
  })

  it('YCA0O (bullet) sólo paga cupón hasta antes del maturity', () => {
    // YCA0O matures 2026-02-12. En 2025-08-01, próximo cupón es 2026-02-12 (= maturity).
    const events = upcomingBondEvents([POS_YPF], { today: '2025-08-15', windowDays: 365 })
    const maturity = events.find(e => e.eventType === 'bond_maturity')
    expect(maturity).toBeDefined()
    expect(maturity.eventDate).toBe('2026-02-12')
  })

  it('excluye posiciones cash', () => {
    const cash = { broker: 'Cocos', asset: 'ARS', is_cash: true, invested: 5000, quantity: 0 }
    const events = upcomingBondEvents([cash], { today: '2026-05-12', windowDays: 365 })
    expect(events).toEqual([])
  })

  it('excluye posiciones no-bono (acciones)', () => {
    const events = upcomingBondEvents([POS_NON_BOND], { today: '2026-05-12', windowDays: 365 })
    expect(events).toEqual([])
  })

  it('excluye posiciones con quantity 0', () => {
    const empty = { ...POS_AL30, quantity: 0 }
    const events = upcomingBondEvents([empty], { today: '2026-05-12', windowDays: 365 })
    expect(events).toEqual([])
  })

  it('múltiples posiciones de bonos: agrega todas', () => {
    const events = upcomingBondEvents(
      [POS_AL30, POS_YPF],
      { today: '2025-08-15', windowDays: 365 }
    )
    expect(events.length).toBeGreaterThan(1)
    const tickers = new Set(events.map(e => e.ticker))
    expect(tickers.has('AL30')).toBe(true)
    expect(tickers.has('YCA0O')).toBe(true)
  })

  it('los amounts se escalan por quantity', () => {
    const qty500 = { ...POS_AL30, quantity: 500 }
    const qty1000 = POS_AL30
    const e500 = upcomingBondEvents([qty500], { today: '2026-05-12', windowDays: 90 })[0]
    const e1000 = upcomingBondEvents([qty1000], { today: '2026-05-12', windowDays: 90 })[0]
    // total con qty 1000 debe ser exactamente 2x total con qty 500
    expect(e1000.details.total).toBeCloseTo(e500.details.total * 2, 1)
  })
})

// ─── normalizeBackendEvents ──────────────────────────────────────────────────

describe('normalizeBackendEvents', () => {
  it('convierte event_type → eventType y agrega daysAway', () => {
    const backend = [
      { ticker: 'AAPL', event_type: 'earnings', event_date: '2026-07-25',
        details: { eps_estimate: 1.45 }, confirmed: 1, source: 'yfinance' },
    ]
    const normalized = normalizeBackendEvents(backend, { today: '2026-05-12' })
    expect(normalized).toHaveLength(1)
    expect(normalized[0].eventType).toBe('earnings')
    expect(normalized[0].eventDate).toBe('2026-07-25')
    expect(normalized[0].confirmed).toBe(true)
    expect(normalized[0].daysAway).toBeGreaterThan(0)
  })

  it('default details a {} si vienen undefined', () => {
    const [r] = normalizeBackendEvents(
      [{ ticker: 'X', event_type: 'split', event_date: '2026-06-01' }],
      { today: '2026-05-12' }
    )
    expect(r.details).toEqual({})
  })

  it('vacío para input null/empty', () => {
    expect(normalizeBackendEvents(null)).toEqual([])
    expect(normalizeBackendEvents([])).toEqual([])
  })
})

// ─── mergeEvents ──────────────────────────────────────────────────────────────

describe('mergeEvents', () => {
  it('ordena cronológicamente', () => {
    const a = { ticker: 'X', eventType: 'earnings', eventDate: '2026-08-01', confirmed: true }
    const b = { ticker: 'Y', eventType: 'earnings', eventDate: '2026-07-01', confirmed: true }
    const c = { ticker: 'Z', eventType: 'earnings', eventDate: '2026-09-01', confirmed: true }
    const merged = mergeEvents([a, b, c])
    expect(merged.map(e => e.ticker)).toEqual(['Y', 'X', 'Z'])
  })

  it('dedupe (ticker, type, date) — confirmed gana sobre teórico', () => {
    const teorico = { ticker: 'AL30', eventType: 'bond_coupon', eventDate: '2026-07-09', confirmed: false }
    const real = { ticker: 'AL30', eventType: 'bond_coupon', eventDate: '2026-07-09', confirmed: true }
    const merged = mergeEvents([teorico, real])
    expect(merged).toHaveLength(1)
    expect(merged[0].confirmed).toBe(true)
  })

  it('arrays de fuentes distintas se combinan sin duplicar', () => {
    const bonds = [{ ticker: 'AL30', eventType: 'bond_coupon', eventDate: '2026-07-09', confirmed: false }]
    const stocks = [{ ticker: 'AAPL', eventType: 'earnings', eventDate: '2026-07-25', confirmed: true }]
    const merged = mergeEvents(bonds, stocks)
    expect(merged).toHaveLength(2)
  })
})

// ─── groupEventsByDate ────────────────────────────────────────────────────────

describe('groupEventsByDate', () => {
  it('agrupa eventos del mismo día', () => {
    const events = [
      { ticker: 'AL30', eventType: 'bond_coupon', eventDate: '2026-07-09' },
      { ticker: 'AAPL', eventType: 'earnings', eventDate: '2026-07-09' },
      { ticker: 'MSFT', eventType: 'earnings', eventDate: '2026-07-25' },
    ]
    const grouped = groupEventsByDate(events)
    expect(grouped.get('2026-07-09').length).toBe(2)
    expect(grouped.get('2026-07-25').length).toBe(1)
  })
})

// ─── eventTypeLabel / eventTypeIcon ──────────────────────────────────────────

describe('eventCategoryColor', () => {
  it('earnings → purple', () => {
    expect(eventCategoryColor('earnings')).toBe('purple')
  })
  it('dividendos (ex_dividend / payment_date) → blue', () => {
    expect(eventCategoryColor('ex_dividend')).toBe('blue')
    expect(eventCategoryColor('payment_date')).toBe('blue')
  })
  it('bond_* → amber', () => {
    expect(eventCategoryColor('bond_coupon')).toBe('amber')
    expect(eventCategoryColor('bond_amort')).toBe('amber')
    expect(eventCategoryColor('bond_coupon_amort')).toBe('amber')
    expect(eventCategoryColor('bond_maturity')).toBe('amber')
  })
  it('macro / economic → green', () => {
    expect(eventCategoryColor('macro')).toBe('green')
    expect(eventCategoryColor('economic')).toBe('green')
  })
  it('desconocido / null → gray', () => {
    expect(eventCategoryColor('mystery')).toBe('gray')
    expect(eventCategoryColor(null)).toBe('gray')
    expect(eventCategoryColor(undefined)).toBe('gray')
  })
})

describe('eventCategoryLabel', () => {
  it('labels en uppercase estilo Delta', () => {
    expect(eventCategoryLabel('earnings')).toBe('EARNINGS')
    expect(eventCategoryLabel('ex_dividend')).toBe('DIVIDENDO')
    expect(eventCategoryLabel('bond_coupon')).toBe('BONO')
    expect(eventCategoryLabel('bond_coupon_amort')).toBe('BONO')
    expect(eventCategoryLabel('macro')).toBe('ECONÓMICO')
  })
  it('desconocido se uppercasea', () => {
    expect(eventCategoryLabel('mystery_type')).toBe('MYSTERY_TYPE')
  })
})

describe('formatRelativeDate', () => {
  it('Hoy / Mañana / Ayer para diff ±1 día', () => {
    expect(formatRelativeDate('2026-05-13', '2026-05-13')).toBe('Hoy')
    expect(formatRelativeDate('2026-05-14', '2026-05-13')).toBe('Mañana')
    expect(formatRelativeDate('2026-05-12', '2026-05-13')).toBe('Ayer')
  })
  it('mismo año: "Lun 9 jul"', () => {
    const r = formatRelativeDate('2026-07-09', '2026-05-13')
    // formato: "Jue 9 Jul" (sin punto, capitalized)
    expect(r).toMatch(/^[A-ZÁÉÍÓÚ][a-záéíóú]{2} \d{1,2} [A-ZÁÉÍÓÚ][a-záéíóú]{2,3}$/)
    expect(r).toContain('9')
    expect(r.toLowerCase()).toContain('jul')
  })
  it('año distinto: incluye el año', () => {
    const r = formatRelativeDate('2027-07-09', '2026-05-13')
    expect(r).toMatch(/2027$/)
  })
  it('ISO inválido → devuelve el input tal cual', () => {
    expect(formatRelativeDate('not-a-date', '2026-05-13')).toBe('not-a-date')
  })
  it('null / vacío → ""', () => {
    expect(formatRelativeDate(null, '2026-05-13')).toBe('')
    expect(formatRelativeDate('', '2026-05-13')).toBe('')
  })
})

describe('countryFlag', () => {
  it('USA → 🇺🇸', () => {
    expect(countryFlag('USA')).toBe('🇺🇸')
    expect(countryFlag('US')).toBe('🇺🇸')
  })
  it('AR → 🇦🇷', () => {
    expect(countryFlag('AR')).toBe('🇦🇷')
  })
  it('UK / EU otros también', () => {
    expect(countryFlag('UK')).toBe('🇬🇧')
    expect(countryFlag('EU')).toBe('🇪🇺')
  })
  it('desconocido → globo', () => {
    expect(countryFlag('XX')).toBe('🌐')
    expect(countryFlag(null)).toBe('🌐')
  })
})

describe('isMacroEvent', () => {
  it('detecta eventType="macro" (frontend camelCase)', () => {
    expect(isMacroEvent({ eventType: 'macro' })).toBe(true)
  })
  it('detecta event_type="macro" (backend snake_case)', () => {
    expect(isMacroEvent({ event_type: 'macro' })).toBe(true)
  })
  it('false para earnings, bonos, dividendos', () => {
    expect(isMacroEvent({ eventType: 'earnings' })).toBe(false)
    expect(isMacroEvent({ eventType: 'bond_coupon' })).toBe(false)
    expect(isMacroEvent({ eventType: 'ex_dividend' })).toBe(false)
  })
  it('null / undefined / objeto sin tipo → false', () => {
    expect(isMacroEvent(null)).toBe(false)
    expect(isMacroEvent(undefined)).toBe(false)
    expect(isMacroEvent({})).toBe(false)
  })
})

describe('eventTypeLabel + eventTypeIcon', () => {
  it('labels conocidos vienen en español', () => {
    expect(eventTypeLabel('earnings')).toBe('Reporte trimestral')
    expect(eventTypeLabel('bond_coupon_amort')).toBe('Cupón + amortización')
    expect(eventTypeLabel('bond_maturity')).toBe('Vencimiento de bono')
  })

  it('label desconocido → mismo string', () => {
    expect(eventTypeLabel('mystery')).toBe('mystery')
  })

  it('icon devuelve string siempre', () => {
    expect(typeof eventTypeIcon('earnings')).toBe('string')
    expect(typeof eventTypeIcon('mystery')).toBe('string')
  })
})

// ════════════════════════════════════════════════════════════════════════════
// dividendPayout — el cobro de dividendos en la escala de TU tenencia.
//
// Estos tests entran por donde entra producción: el evento arranca con la forma
// EXACTA que devuelve /api/events/portfolio (snake_case, details crudos) y pasa
// por normalizeBackendEvents antes de llegar al cálculo. Un test que armara el
// evento ya normalizado a mano se saltearía ese paso y certificaría en verde un
// camino que la app no recorre.
// ════════════════════════════════════════════════════════════════════════════
describe('dividendPayout', () => {
  beforeEach(() => setBrokersRegistry([
    { id: 1, name: 'Balanz',       currency: 'ARS' },
    { id: 2, name: 'Balanz · USD', currency: 'USD', parent_broker_id: 1 },
    { id: 3, name: 'Schwab',       currency: 'USD' },
  ]))

  // Tal cual sale de _fetch_yf_events → /api/events/portfolio.
  const backendEvent = (ticker, perShare, extra = {}) => ({
    ticker,
    event_type: 'ex_dividend',
    event_date: '2026-09-21',
    details: { dividend_per_share: perShare, dividend_scale: 'underlying_share', ...extra },
    confirmed: true,
    source: 'yfinance',
  })
  const norm = (...evs) => normalizeBackendEvents(evs)[0]

  it('el caso reportado: 130 CEDEARs de AVGO cobran US$2,17 y no US$84,50', () => {
    const ev = norm(backendEvent('AVGO', 0.65))
    const positions = [{ asset: 'AVGO', quantity: 130, broker: 'Balanz', is_cash: 0 }]
    const r = dividendPayout(ev, positions)
    expect(r.units).toBe(130)                 // lo que tenés
    expect(r.shares).toBeCloseTo(130 / 39, 6) // lo que eso es en acciones
    expect(r.amount).toBeCloseTo(2.17, 2)     // lo que vas a cobrar
    expect(130 * 0.65).toBeCloseTo(84.5, 2)   // lo que decía la app
  })

  it('el caso GOOGL reconcilia con el depósito real del broker', () => {
    const ev = norm(backendEvent('GOOGL', 0.21))
    const r = dividendPayout(ev, [{ asset: 'GOOGL', quantity: 190, broker: 'Balanz', is_cash: 0 }])
    expect(r.amount).toBeCloseTo(0.69, 2)     // el broker depositó 0,70
    expect(r.ratio).toBe(58)
  })

  it('una acción real en broker USD no se divide', () => {
    const ev = norm(backendEvent('AVGO', 0.65))
    const r = dividendPayout(ev, [{ asset: 'AVGO', quantity: 130, broker: 'Schwab', is_cash: 0 }])
    expect(r.amount).toBeCloseTo(84.5, 2)
    expect(r.scale).toBe('share')
  })

  it('CEDEAR y acción real del mismo ticker se suman cada uno en su escala', () => {
    const ev = norm(backendEvent('AVGO', 0.65))
    const r = dividendPayout(ev, [
      { asset: 'AVGO', quantity: 39, broker: 'Balanz', is_cash: 0 },  // = 1 acción
      { asset: 'AVGO', quantity: 2,  broker: 'Schwab', is_cash: 0 },  // = 2 acciones
    ])
    expect(r.shares).toBeCloseTo(3, 6)
    expect(r.amount).toBeCloseTo(3 * 0.65, 6)
    expect(r.scale).toBe('mixed')
    expect(r.perUnit).toBeNull()   // dos escalas → no hay "por unidad" único
    expect(r.units).toBe(41)
  })

  it('marca partial cuando hay tenencia sin ratio conocido', () => {
    const ev = norm(backendEvent('ZZZZ', 0.26))
    const r = dividendPayout(ev, [
      { asset: 'ZZZZ', quantity: 400, broker: 'Balanz', is_cash: 0 },  // sin ratio
      { asset: 'ZZZZ', quantity: 10,  broker: 'Schwab', is_cash: 0 },
    ])
    expect(r.partial).toBe(true)
    expect(r.amount).toBeCloseTo(10 * 0.26, 6)   // sólo lo que supimos convertir
  })

  it('si NADA se puede convertir devuelve null en vez de un número inventado', () => {
    const ev = norm(backendEvent('ZZZZ', 0.26))
    const r = dividendPayout(ev, [{ asset: 'ZZZZ', quantity: 400, broker: 'Balanz', is_cash: 0 }])
    expect(r).toBeNull()
  })

  it('sin tenencia (tab Populares) informa el por-acción, sin monto propio', () => {
    const ev = norm(backendEvent('KO', 0.53))
    const r = dividendPayout(ev, [])
    expect(r.amount).toBeNull()
    expect(r.perShare).toBe(0.53)
    expect(r.units).toBe(0)
  })

  it('propaga que el monto es del período anterior', () => {
    const ev = norm(backendEvent('AVGO', 0.65, {
      dividend_amount_estimated: true, dividend_as_of: '2026-06-22',
    }))
    const r = dividendPayout(ev, [{ asset: 'AVGO', quantity: 39, broker: 'Balanz', is_cash: 0 }])
    expect(r.estimated).toBe(true)
    expect(r.asOf).toBe('2026-06-22')
  })

  it('no toca earnings ni macro ni bonos', () => {
    const earn = normalizeBackendEvents([{ ticker: 'AVGO', event_type: 'earnings', event_date: '2026-09-21', details: { eps_estimate: 1.2 } }])[0]
    expect(dividendPayout(earn, [{ asset: 'AVGO', quantity: 39, broker: 'Balanz', is_cash: 0 }])).toBeNull()
  })

  it('un evento sin monto no produce cobro', () => {
    const ev = normalizeBackendEvents([{ ticker: 'AVGO', event_type: 'ex_dividend', event_date: '2026-09-21', details: {} }])[0]
    expect(dividendPayout(ev, [{ asset: 'AVGO', quantity: 39, broker: 'Balanz', is_cash: 0 }])).toBeNull()
  })

  it('rechaza el dato si viniera en una escala que no sabe convertir', () => {
    // Defensivo: si algún día el backend publicara el monto ya por CEDEAR, este
    // módulo no debe volver a dividir. Mejor no publicar que publicar mal.
    const ev = norm(backendEvent('AVGO', 0.0167, { dividend_scale: 'cedear' }))
    expect(dividendPayout(ev, [{ asset: 'AVGO', quantity: 130, broker: 'Balanz', is_cash: 0 }])).toBeNull()
  })

  it('un evento SIN dividend_scale (cacheado antes del fix) se trata como subyacente', () => {
    // La tabla financial_events tiene filas viejas sin el campo. Asumir la
    // escala histórica es correcto: siempre fue la del subyacente.
    const ev = normalizeBackendEvents([{ ticker: 'AVGO', event_type: 'ex_dividend', event_date: '2026-09-21', details: { dividend_per_share: 0.65 } }])[0]
    const r = dividendPayout(ev, [{ asset: 'AVGO', quantity: 130, broker: 'Balanz', is_cash: 0 }])
    expect(r.amount).toBeCloseTo(2.17, 2)
  })
})
