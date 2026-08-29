import { describe, it, expect } from 'vitest'
import { esTradeCerrado, computeTradeStats } from './tradeStats.js'

// ════════════════════════════════════════════════════════════════════════════
// Congela la definición de win rate de la casa (backend/reporting/builder.py).
// Cada caso de acá es una de las tres definiciones que convivían: si alguien
// vuelve a contar dividendos como wins, o vuelve a usar `wins + losses` de
// denominador, o devuelve 0 en vez de null sin trades, rompe uno de estos.
// ════════════════════════════════════════════════════════════════════════════

const op = (over = {}) => ({ op_type: 'Venta', pnl_usd: 10, ...over })

describe('esTradeCerrado', () => {
  it('una venta con P&L es un trade cerrado', () => {
    expect(esTradeCerrado(op())).toBe(true)
  })

  it('excluye Compra, Dividendo e Interés', () => {
    for (const t of ['Compra', 'Dividendo', 'Interés']) {
      expect(esTradeCerrado(op({ op_type: t }))).toBe(false)
    }
  })

  it('excluye los DOS prefijos de conversión', () => {
    expect(esTradeCerrado(op({ op_type: 'Conversión ARS→USD' }))).toBe(false)
    expect(esTradeCerrado(op({ op_type: 'CONVERSION_USD' }))).toBe(false)
  })

  it('excluye pnl_usd null o ausente, pero NO el cero', () => {
    expect(esTradeCerrado(op({ pnl_usd: null }))).toBe(false)
    expect(esTradeCerrado({ op_type: 'Venta' })).toBe(false)   // sin la clave
    expect(esTradeCerrado(op({ pnl_usd: 0 }))).toBe(true)
  })

  it('espeja el .strip() del backend: los espacios no salvan al tipo excluido', () => {
    expect(esTradeCerrado(op({ op_type: '  Dividendo  ' }))).toBe(false)
  })

  it('op_type ausente o vacío sigue siendo trade si tiene P&L (igual que el backend)', () => {
    // `(op.get("op_type") or "").strip()` → "" no está en la lista de excluidos.
    expect(esTradeCerrado({ pnl_usd: 5 })).toBe(true)
    expect(esTradeCerrado({ op_type: null, pnl_usd: 5 })).toBe(true)
  })
})

describe('computeTradeStats', () => {
  it('un Dividendo ganador no es win NI entra al denominador', () => {
    const r = computeTradeStats([
      op({ op_type: 'Venta', pnl_usd: 100 }),
      op({ op_type: 'Dividendo', pnl_usd: 50 }),
    ])
    expect(r).toEqual({ trades: 1, wins: 1, losses: 0, winRate: 1 })
  })

  it('un Interés ganador tampoco', () => {
    const r = computeTradeStats([
      op({ op_type: 'Venta', pnl_usd: 100 }),
      op({ op_type: 'Interés', pnl_usd: 3 }),
    ])
    expect(r.trades).toBe(1)
    expect(r.wins).toBe(1)
    expect(r.winRate).toBe(1)
  })

  it('un P&L exactamente 0 BAJA el win rate: entra al denominador y no al numerador', () => {
    const sinCero = computeTradeStats([op({ pnl_usd: 100 })])
    expect(sinCero.winRate).toBe(1)

    const conCero = computeTradeStats([op({ pnl_usd: 100 }), op({ pnl_usd: 0 })])
    expect(conCero).toEqual({ trades: 2, wins: 1, losses: 0, winRate: 0.5 })
    expect(conCero.winRate).toBeLessThan(sinCero.winRate)
  })

  it('las conversiones quedan afuera con los dos prefijos', () => {
    const r = computeTradeStats([
      op({ op_type: 'Venta', pnl_usd: 10 }),
      op({ op_type: 'Conversión ARS→USD', pnl_usd: 999 }),
      op({ op_type: 'CONVERSION_USD', pnl_usd: 999 }),
    ])
    expect(r.trades).toBe(1)
    expect(r.winRate).toBe(1)
  })

  it('lista vacía → winRate null, NO 0', () => {
    const r = computeTradeStats([])
    expect(r.winRate).toBeNull()
    expect(r.winRate).not.toBe(0)
    expect(r).toEqual({ trades: 0, wins: 0, losses: 0, winRate: null })
  })

  it('sólo dividendos → winRate null (no hay trades que ganar o perder)', () => {
    const r = computeTradeStats([
      op({ op_type: 'Dividendo', pnl_usd: 50 }),
      op({ op_type: 'Dividendo', pnl_usd: 20 }),
    ])
    expect(r.winRate).toBeNull()
  })

  it('tolera null/undefined como lista', () => {
    expect(computeTradeStats(null).winRate).toBeNull()
    expect(computeTradeStats(undefined).trades).toBe(0)
  })

  it('cuenta las perdedoras, y el cero no es ninguna de las dos', () => {
    // Con el cero adentro las tres definiciones divergen: 1/4 (la de la casa),
    // 1/3 (wins+losses) y 1/4 sólo por casualidad si no hubiera compras. El caso
    // sin cero no discriminaba nada.
    const r = computeTradeStats([
      op({ pnl_usd: 10 }), op({ pnl_usd: -4 }), op({ pnl_usd: -1 }), op({ pnl_usd: 0 }),
    ])
    expect(r).toEqual({ trades: 4, wins: 1, losses: 2, winRate: 0.25 })
    expect(r.wins + r.losses).toBeLessThan(r.trades)   // por eso el sub-label nombra `trades`
  })

  it('el match de tipo es EXACTO, no por prefijo (sólo las conversiones van por prefijo)', () => {
    // El backend hace `t in ("Compra", ...)`: 'Compra de bono' NO está en la
    // tupla, así que ES un trade. Si alguien "mejora" esto a startsWith, rompe acá.
    expect(esTradeCerrado(op({ op_type: 'Compra de bono' }))).toBe(true)
    expect(esTradeCerrado(op({ op_type: 'Dividendos' }))).toBe(true)
    // Y las conversiones, al revés: por prefijo, no exacto.
    expect(esTradeCerrado(op({ op_type: 'Conversión' }))).toBe(false)
    expect(esTradeCerrado(op({ op_type: 'CONVERSION cualquier cosa' }))).toBe(false)
  })

  it('Cupón y Amortización cuentan como trades cerrados (el backend no los excluye)', () => {
    // No están en la lista de excluidos de builder.py, así que entran. Queda
    // congelado a propósito: si alguien los saca, es una decisión de producto que
    // hay que tomar en el backend primero.
    const r = computeTradeStats([
      op({ op_type: 'Cupón', pnl_usd: 30 }),
      op({ op_type: 'Amortización', pnl_usd: 0 }),
    ])
    expect(r.trades).toBe(2)
    expect(r.wins).toBe(1)
    expect(r.winRate).toBe(0.5)
  })

  // ── El caso real que motivó todo esto ────────────────────────────────────
  // 495 ops de un usuario real. Las tres definiciones que convivían daban
  // 93% (desktop: wins/ops.length), 100% (mobile: wins/(wins+losses)) y
  // 85% (backend). Gana el backend: 195/229.
  it('el caso real: 195 ventas ganadoras + 258 dividendos + 34 ceros → 195/229', () => {
    const ops = [
      ...Array.from({ length: 195 }, () => op({ op_type: 'Venta', pnl_usd: 100 })),
      ...Array.from({ length: 258 }, () => op({ op_type: 'Dividendo', pnl_usd: 5 })),
      ...Array.from({ length: 34 }, () => op({ op_type: 'Venta', pnl_usd: 0 })),
    ]
    const r = computeTradeStats(ops)
    expect(r.trades).toBe(229)
    expect(r.wins).toBe(195)
    expect(r.losses).toBe(0)
    expect(r.winRate).toBeCloseTo(195 / 229, 10)
    expect(Math.round(r.winRate * 100)).toBe(85)

    // Y que NO dé ninguna de las dos definiciones viejas del frontend.
    expect(Math.round(r.winRate * 100)).not.toBe(93)   // wins / ops.length
    expect(Math.round(r.winRate * 100)).not.toBe(100)  // wins / (wins + losses)
  })
})
