// Tests del helper puro `lookupRate` (Phase C — FX histórico).
//
// El hook React `useFxHistory` no se testea acá (requiere @testing-library)
// — el smoke test es el build pasando + Dashboard chart funcionando.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { lookupRate, fetchFxHistory, _resetFxCacheForTesting } from './useFxHistory'
import { api } from '../utils/api'

const ROWS = [
  { date: '2025-01-01', blue: 1200 },
  { date: '2025-01-02', blue: 1205 },
  { date: '2025-01-03', blue: 1210 },
  { date: '2025-01-06', blue: 1220 }, // lunes después del weekend
  { date: '2025-01-07', blue: 1225 },
]

describe('lookupRate', () => {
  it('match exacto devuelve el blue de esa fecha', () => {
    expect(lookupRate(ROWS, '2025-01-02')).toBe(1205)
  })

  it('fecha sin match exacto devuelve el día anterior más cercano', () => {
    // Sábado 2025-01-04 no tiene blue (no se publica) → usa viernes 2025-01-03
    expect(lookupRate(ROWS, '2025-01-04')).toBe(1210)
    // Domingo 2025-01-05 → mismo viernes anterior
    expect(lookupRate(ROWS, '2025-01-05')).toBe(1210)
  })

  it('fecha posterior al último row devuelve el último blue', () => {
    expect(lookupRate(ROWS, '2025-02-15')).toBe(1225)
  })

  it('fecha anterior al primer row devuelve null', () => {
    expect(lookupRate(ROWS, '2024-12-31')).toBe(null)
  })

  it('rows vacío devuelve null', () => {
    expect(lookupRate([], '2025-01-01')).toBe(null)
  })

  it('null / undefined / dateIso vacío devuelve null', () => {
    expect(lookupRate(ROWS, null)).toBe(null)
    expect(lookupRate(ROWS, undefined)).toBe(null)
    expect(lookupRate(ROWS, '')).toBe(null)
    expect(lookupRate(null, '2025-01-01')).toBe(null)
  })

  it('rows con entries inválidos (sin date o blue=null) los skipea', () => {
    const dirty = [
      { date: '2025-01-01', blue: 1200 },
      { date: '2025-01-02', blue: null },  // inválido
      { /* no date */ blue: 1300 },        // inválido
      { date: '2025-01-03', blue: 1210 },
    ]
    expect(lookupRate(dirty, '2025-01-02')).toBe(1200) // skipea null, usa día previo
    expect(lookupRate(dirty, '2025-01-03')).toBe(1210)
  })
})

// ─── Audit fix C3: retry cooldown tras failure ───────────────────────────────
// Verifica que el cache module-level NO queda permanentemente "failed" si
// el primer fetch falla — tras RETRY_COOLDOWN_MS un nuevo intento procede.

describe('fetchFxHistory retry cooldown (audit fix C3)', () => {
  beforeEach(() => {
    _resetFxCacheForTesting()
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
    _resetFxCacheForTesting()
  })

  it('primer fetch exitoso cachea data y subsequent calls no re-fetchean', async () => {
    const rows = [{ date: '2025-01-01', blue: 1200 }]
    const spy = vi.spyOn(api, 'get').mockResolvedValue(rows)
    const r1 = await fetchFxHistory()
    expect(r1).toEqual(rows)
    expect(spy).toHaveBeenCalledTimes(1)
    const r2 = await fetchFxHistory()
    expect(r2).toEqual(rows)
    expect(spy).toHaveBeenCalledTimes(1)  // cache hit, no segunda call
  })

  it('fetch falla → próximo intento dentro del cooldown NO reintenta', async () => {
    const spy = vi.spyOn(api, 'get').mockRejectedValue(new Error('Network down'))
    const r1 = await fetchFxHistory()
    expect(r1).toEqual([])
    expect(spy).toHaveBeenCalledTimes(1)
    // Dentro del cooldown — no reintenta
    const r2 = await fetchFxHistory()
    expect(r2).toEqual([])
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('fetch falla → tras cooldown, próximo intento SÍ reintenta', async () => {
    const spy = vi.spyOn(api, 'get').mockRejectedValue(new Error('Network down'))
    await fetchFxHistory()
    expect(spy).toHaveBeenCalledTimes(1)
    // Avanzamos el reloj > 30s cooldown
    vi.advanceTimersByTime(31_000)
    // Esta vez el mock devuelve data válida
    spy.mockResolvedValue([{ date: '2025-01-01', blue: 1500 }])
    const r = await fetchFxHistory()
    expect(r).toEqual([{ date: '2025-01-01', blue: 1500 }])
    expect(spy).toHaveBeenCalledTimes(2)  // reintentó
  })

  it('respuesta vacía cuenta como soft-failure (también espera cooldown)', async () => {
    const spy = vi.spyOn(api, 'get').mockResolvedValue([])
    const r1 = await fetchFxHistory()
    expect(r1).toEqual([])
    // Dentro del cooldown no debería reintentar
    const r2 = await fetchFxHistory()
    expect(r2).toEqual([])
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('requests concurrentes comparten la misma promise (no duplica network call)', async () => {
    let resolve
    const promise = new Promise(r => { resolve = r })
    const spy = vi.spyOn(api, 'get').mockReturnValue(promise)
    const p1 = fetchFxHistory()
    const p2 = fetchFxHistory()
    expect(spy).toHaveBeenCalledTimes(1)  // 1 sola call para 2 callers
    resolve([{ date: '2025-01-01', blue: 1200 }])
    const [r1, r2] = await Promise.all([p1, p2])
    expect(r1).toEqual(r2)
  })
})
