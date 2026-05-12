import { describe, it, expect } from 'vitest'
import {
  upcomingBondEvents,
  normalizeBackendEvents,
  mergeEvents,
  groupEventsByDate,
  eventTypeLabel,
  eventTypeIcon,
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
