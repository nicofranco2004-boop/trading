// Tests del dólar de una fecha (utils/tcHistorico.js) — el que usa el hook.
// Estas filas no traen MEP: prueban la red al blue (fechas anteriores a 2018).
//
// El hook React `useFxHistory` no se testea acá (requiere @testing-library)
// — el smoke test es el build pasando + Dashboard chart funcionando.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { fetchFxHistory, _resetFxCacheForTesting } from './useFxHistory'
import { indexarSerie, tcDeFechaDetalle, tcMensualDeSerie } from '../utils/tcHistorico'

const lookupRate = (rows, d) => tcDeFechaDetalle(indexarSerie(rows), d).tc
import { api } from '../utils/api'

const ROWS = [
  { date: '2025-01-01', blue: 1200 },
  { date: '2025-01-02', blue: 1205 },
  { date: '2025-01-03', blue: 1210 },
  { date: '2025-01-06', blue: 1220 }, // lunes después del weekend
  { date: '2025-01-07', blue: 1225 },
]

describe('dólar de una fecha — sin MEP en la serie, el blue', () => {
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

describe('dólar de una fecha — el elegido (MEP) cuando la serie lo tiene', () => {
  const SERIE = [
    { date: '2018-10-26', blue: 37, mep: null },
    { date: '2018-10-29', blue: 37.5, mep: 37.2 },
    { date: '2025-10-10', blue: 1450, mep: 1500 },
    { date: '2025-10-13', blue: 1455, mep: 1510 },
    { date: '2025-10-14', blue: 1460, mep: null },   // el cron no escribió el MEP
    { date: '2025-10-31', blue: 1470, mep: 1520 },
    { date: '2025-11-03', blue: 1480, mep: 1490 },
  ]
  const idx = indexarSerie(SERIE)

  it('prefiere el MEP del día al blue', () => {
    expect(tcDeFechaDetalle(idx, '2025-10-13')).toEqual({ tc: 1510, source: 'mep', asOf: '2025-10-13' })
  })

  it('un día sin MEP usa el último MEP anterior, no el blue', () => {
    expect(tcDeFechaDetalle(idx, '2025-10-14')).toEqual({ tc: 1510, source: 'mep', asOf: '2025-10-13' })
  })

  it('antes de que exista el MEP en la serie, el blue (la red del servidor)', () => {
    expect(tcDeFechaDetalle(idx, '2018-10-27')).toEqual({ tc: 37, source: 'blue', asOf: '2018-10-26' })
  })

  it('la tabla mensual: el último MEP de cada mes; un día sin MEP no lo pisa', () => {
    expect(tcMensualDeSerie(SERIE)).toEqual({ '2018-10': 37.2, '2025-10': 1520, '2025-11': 1490 })
    expect(tcMensualDeSerie(SERIE.slice(0, 5))['2025-10']).toBe(1510)
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
