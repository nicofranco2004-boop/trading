// upcomingEvents.js — eventos financieros futuros para mostrar en el calendario.
// ════════════════════════════════════════════════════════════════════════════
// Combina dos fuentes:
//   1. Backend /api/events/portfolio: earnings + ex-dividend + payment dates
//      de stocks / ETFs / CEDEARs (vía yfinance).
//   2. Frontend bondSchedule: cupones + amortizaciones + maturities de bonos
//      del portfolio del user. Generado on-the-fly desde el cronograma teórico.
//
// Por qué bonos van frontend: bondMeta + bondSchedule viven en el frontend
// (data estática informativa, no requiere backend storage). Evita duplicar
// la data en backend; el frontend ya tiene todo para calcular.
//
// La función `mergeEvents` ordena cronológicamente y deduplica si por algún
// motivo aparece la misma fecha dos veces (defensivo).

import { generateSchedule } from './bondSchedule'
import { getBondMeta } from './bondMeta'
import { isBondTicker } from './tickers'

const DEFAULT_WINDOW_DAYS = 90

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function addDays(iso, days) {
  const d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function daysBetween(from, to) {
  const a = new Date(from + 'T00:00:00Z')
  const b = new Date(to + 'T00:00:00Z')
  return Math.round((b - a) / 86400000)
}

// Genera los eventos futuros de un bono en el portfolio.
// Cada entry: { ticker, broker, eventType, eventDate, details, confirmed, daysAway }
//   • eventType: 'bond_coupon' | 'bond_amort' | 'bond_coupon_amort' | 'bond_maturity'
//   • details: { amount: monto teórico en moneda del bono, currency, qty, ... }
//
// Reglas:
//   • Skip si la posición no tiene quantity > 0
//   • Skip si el bono no tiene schedule (ETFs sin maturity)
//   • Filtra a [today, today + windowDays]
//   • Maturity solo se marca si es la última fecha del schedule
export function upcomingBondEvents(positions, options = {}) {
  const today = options.today || todayIso()
  const windowDays = options.windowDays || DEFAULT_WINDOW_DAYS
  const cutoff = addDays(today, windowDays)
  const events = []

  for (const p of positions) {
    if (!isBondTicker(p.asset)) continue
    if (p.is_cash) continue
    if (!p.quantity || p.quantity <= 0) continue
    const schedule = generateSchedule(p.asset)
    if (!schedule) continue
    const meta = getBondMeta(p.asset)
    const bondCurrency = meta?.currency || 'USD'
    const maturityDate = meta?.maturity

    for (const pmt of schedule) {
      if (pmt.date <= today) continue
      if (pmt.date > cutoff) break
      const couponAmt = pmt.coupon * p.quantity / 100
      const amortAmt = pmt.amort * p.quantity / 100
      const totalAmt = pmt.total * p.quantity / 100
      const isMaturity = pmt.date === maturityDate
      let eventType
      if (isMaturity) eventType = 'bond_maturity'
      else if (pmt.amort > 0 && pmt.coupon > 0) eventType = 'bond_coupon_amort'
      else if (pmt.amort > 0) eventType = 'bond_amort'
      else eventType = 'bond_coupon'

      events.push({
        ticker: p.asset,
        broker: p.broker,
        eventType,
        eventDate: pmt.date,
        details: {
          coupon: +couponAmt.toFixed(2),
          amort: +amortAmt.toFixed(2),
          total: +totalAmt.toFixed(2),
          currency: bondCurrency,
          quantity: p.quantity,
        },
        confirmed: false,  // schedule teórico, no confirmación de broker
        source: 'bondSchedule',
        daysAway: daysBetween(today, pmt.date),
      })
    }
  }
  return events
}

// Normaliza eventos del backend (stocks) al mismo shape que los de bonos.
// El backend devuelve { ticker, event_type, event_date, details, confirmed, source };
// los frontend usan camelCase + daysAway computado en cliente.
export function normalizeBackendEvents(backendEvents, options = {}) {
  const today = options.today || todayIso()
  return (backendEvents || []).map(e => ({
    ticker: e.ticker,
    broker: null,  // backend no sabe el broker — se llena en merge si aplica
    eventType: e.event_type,
    eventDate: e.event_date,
    details: e.details || {},
    confirmed: !!e.confirmed,
    source: e.source || 'yfinance',
    daysAway: daysBetween(today, e.event_date),
  }))
}

// Mergea eventos de bonos + stocks, ordena por fecha asc, dedup por
// (ticker, eventType, eventDate). Si hay duplicados, prioridad: confirmed > teórico.
export function mergeEvents(...arrays) {
  const all = arrays.flat()
  const map = new Map()
  for (const ev of all) {
    const key = `${ev.ticker}:${ev.eventType}:${ev.eventDate}`
    const existing = map.get(key)
    if (!existing) {
      map.set(key, ev)
    } else if (!existing.confirmed && ev.confirmed) {
      map.set(key, ev)  // confirmed gana sobre teórico
    }
  }
  return [...map.values()].sort((a, b) => a.eventDate.localeCompare(b.eventDate))
}

// Group helper: agrupa eventos por (asset) o por (date) para vistas distintas.
export function groupEventsByAsset(events) {
  const map = new Map()
  for (const ev of events) {
    if (!map.has(ev.ticker)) map.set(ev.ticker, [])
    map.get(ev.ticker).push(ev)
  }
  return map
}

export function groupEventsByDate(events) {
  const map = new Map()
  for (const ev of events) {
    if (!map.has(ev.eventDate)) map.set(ev.eventDate, [])
    map.get(ev.eventDate).push(ev)
  }
  return map
}

// Label en español según event_type. Para UI.
export function eventTypeLabel(t) {
  switch (t) {
    case 'earnings':           return 'Reporte trimestral'
    case 'ex_dividend':        return 'Ex-dividendo'
    case 'payment_date':       return 'Pago dividendo'
    case 'split':              return 'Stock split'
    case 'bond_coupon':        return 'Cupón de bono'
    case 'bond_amort':         return 'Amortización'
    case 'bond_coupon_amort':  return 'Cupón + amortización'
    case 'bond_maturity':      return 'Vencimiento de bono'
    default:                   return t
  }
}

export function eventTypeIcon(t) {
  // emojis simple para UI sin importar lucide everywhere
  switch (t) {
    case 'earnings':           return '📊'
    case 'ex_dividend':        return '💰'
    case 'payment_date':       return '💵'
    case 'split':              return '✂️'
    case 'bond_coupon':        return '🪙'
    case 'bond_amort':         return '📥'
    case 'bond_coupon_amort':  return '🪙'
    case 'bond_maturity':      return '🏁'
    default:                   return '•'
  }
}
