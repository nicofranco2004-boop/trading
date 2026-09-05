// useFxHistory — Phase C (2026-05-31).
//
// Fetcha /api/fx-rates una vez por sesión y expone helpers de lookup por
// fecha. Cuando el toggle global está en ARS y el caller necesita convertir
// un valor histórico (snapshot, monthly entry, operación vieja), debe usar
// el TC que existía en ESA fecha — no el actual.
//
// Fallbacks:
//   • Si la API falla → devuelve un map vacío + fallbackTcValuacion (el actual).
//   • Si una fecha no está en el map → busca el día anterior más cercano.
//   • Si nada existe → fallbackTcValuacion.
//
// El hook es global-cache friendly: una sola instancia mantiene el map.
// Re-renderizados no disparan nuevos fetches.

import { useEffect, useState, useMemo, useRef } from 'react'
import { api } from '../utils/api'

// ── Pure helpers (testeables sin React) ──────────────────────────────────────
//
// lookupRate(rows, dateIso) — busca el blue en `rows` para `dateIso`. Si no
// hay match exacto, devuelve el del día anterior más cercano (común para
// fines de semana / feriados donde no se publica blue). Si no hay nada
// anterior, devuelve null.

export function lookupRate(rows, dateIso) {
  if (!dateIso || !Array.isArray(rows) || rows.length === 0) return null
  // Sort once (caller pasa rows ya ordenadas para ahorrar trabajo en hot path)
  let candidate = null
  for (const r of rows) {
    if (!r?.date || r?.blue == null) continue
    if (r.date <= dateIso) candidate = r
    else break // rows están sorted asc → más adelante no aplica
  }
  return candidate ? Number(candidate.blue) : null
}


// Cache módulo-level: una sola request por sesión / página. Compartido
// entre todos los consumers (Dashboard chart, Reports cards, etc).
//
// Audit fix C3 (2026-05-31): trackeamos failure state aparte, con retry
// cooldown. Antes: si el primer fetch fallaba (network blip), _fxCacheData
// quedaba `[]` permanente y nunca reintentábamos en la sesión. Ahora: tras
// fallo esperamos RETRY_COOLDOWN_MS y permitimos un nuevo intento (típico
// next mount o cuando otro consumer llama).
let _fxCachePromise = null
let _fxCacheData = null
let _fxCacheError = false
let _fxCacheErrorAt = 0
const RETRY_COOLDOWN_MS = 30_000

export function fetchFxHistory() {
  // Request en vuelo → comparte la misma promesa
  if (_fxCachePromise) return _fxCachePromise
  // Data válida cacheada → resolve directo
  if (_fxCacheData && _fxCacheData.length > 0) return Promise.resolve(_fxCacheData)
  // Error reciente → no reintentar hasta cooldown (devuelve cache vacío sin
  // disparar más network calls; el caller usa fallback tcValuacion automáticamente)
  if (_fxCacheError && Date.now() - _fxCacheErrorAt < RETRY_COOLDOWN_MS) {
    return Promise.resolve(_fxCacheData || [])
  }
  // Reintento permitido
  _fxCacheError = false
  _fxCachePromise = api.get('/fx-rates?days=3650')
    .then(rows => {
      _fxCacheData = Array.isArray(rows) ? rows : []
      _fxCachePromise = null
      // Empty response cuenta como soft-failure (backend nunca devolvió data)
      if (_fxCacheData.length === 0) {
        _fxCacheError = true
        _fxCacheErrorAt = Date.now()
      }
      return _fxCacheData
    })
    .catch(() => {
      _fxCachePromise = null
      _fxCacheData = []
      _fxCacheError = true
      _fxCacheErrorAt = Date.now()
      return _fxCacheData
    })
  return _fxCachePromise
}

// Export para tests — permite resetear el module-level cache entre tests.
export function _resetFxCacheForTesting() {
  _fxCachePromise = null
  _fxCacheData = null
  _fxCacheError = false
  _fxCacheErrorAt = 0
}

/**
 * Hook que devuelve la historia de blue + un helper getRateForDate.
 *
 * @param {number} fallbackTcValuacion — blue actual (del context o de un fetch local)
 * @returns {{
 *   loaded: boolean,
 *   getRateForDate: (dateIso: string) => number | null,
 *   getRateOrFallback: (dateIso: string) => number,
 * }}
 */
export function useFxHistory(fallbackTcValuacion = 1415) {
  const [data, setData] = useState(_fxCacheData)
  const fallbackRef = useRef(fallbackTcValuacion)
  fallbackRef.current = fallbackTcValuacion

  useEffect(() => {
    let cancelled = false
    if (_fxCacheData) {
      setData(_fxCacheData)
      return () => { cancelled = true }
    }
    fetchFxHistory().then(rows => {
      if (!cancelled) setData(rows)
    })
    return () => { cancelled = true }
  }, [])

  // Asume que el backend devuelve rows ya ordenadas ascendentemente —
  // lookupRate hace búsqueda lineal con break temprano.
  const sortedRows = useMemo(() => {
    if (!data || !Array.isArray(data)) return []
    return data
  }, [data])

  // Índice date → blue + array de fechas ordenado, para resolver por búsqueda
  // BINARIA en vez del scan lineal. Los agregados nuevos (convert-then-sum en
  // headers de grupo y KPIs) llaman esto una vez POR OPERACIÓN en cada render:
  // con ~10 años de serie (3.650 filas) y cientos de ops, el scan lineal era
  // O(ops × filas) por render. Se construye una sola vez por cambio de `data`.
  const fxIndex = useMemo(() => {
    const dates = []
    const byDate = new Map()
    const mepByDate = new Map()
    for (const r of sortedRows) {
      if (!r?.date || r?.blue == null) continue
      dates.push(r.date)
      byDate.set(r.date, Number(r.blue))
      // MEP del día, cuando la fila lo trae. Se guarda APARTE para no cambiar lo que
      // ven los consumidores actuales (todos leen el blue); lo usa la vista previa del
      // depósito con fecha, que tiene que mostrar el mismo dólar que el backend guarda.
      if (r?.mep != null) mepByDate.set(r.date, Number(r.mep))
    }
    return { dates, byDate, mepByDate }
  }, [sortedRows])

  function getRateForDate(dateIso) {
    if (!dateIso) return null
    const { dates, byDate } = fxIndex
    if (dates.length === 0) return null
    const exact = byDate.get(dateIso)
    if (exact != null) return exact
    // Sin match exacto (fin de semana / feriado) → el día anterior más cercano.
    let lo = 0, hi = dates.length - 1, best = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (dates[mid] <= dateIso) { best = mid; lo = mid + 1 } else { hi = mid - 1 }
    }
    return best >= 0 ? byDate.get(dates[best]) : null
  }

  function getRateOrFallback(dateIso) {
    const r = getRateForDate(dateIso)
    return r != null && r > 0 ? r : fallbackRef.current
  }

  // MEP del día con TRAZA: además del TC, de dónde salió y de QUÉ FECHA.
  //
  // La fecha importa: `mep_venta` es nullable y el cron nocturno no lo escribe, así
  // que el MEP "del 15/08" puede ser en realidad el del 13/08. Quien le muestra el
  // número a un usuario tiene que poder decirle qué día está usando — si no, la
  // degradación es muda y el usuario cree que le estamos dando el dólar de su
  // liquidación. Devuelve `{tc: null}` en vez de caer al fallback: sugerir un monto
  // con el dólar de HOY para un cupón de hace dos años es peor que no sugerir nada.
  function getMepDetail(dateIso) {
    const NADA = { tc: null, source: null, asOf: null }
    if (!dateIso) return NADA
    const { dates, mepByDate, byDate } = fxIndex
    if (!mepByDate || !dates || dates.length === 0) return NADA
    const exact = mepByDate.get(dateIso)
    if (exact != null && exact > 0) return { tc: exact, source: 'mep', asOf: dateIso }
    let lo = 0, hi = dates.length - 1, best = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (dates[mid] <= dateIso) { best = mid; lo = mid + 1 } else { hi = mid - 1 }
    }
    for (let i = best; i >= 0; i--) {
      const v = mepByDate.get(dates[i])
      if (v != null && v > 0) return { tc: v, source: 'mep', asOf: dates[i] }
    }
    // Sin ningún MEP ≤ la fecha (pre-2018): red histórica al blue, declarada.
    if (best >= 0) {
      const b = byDate.get(dates[best])
      if (b != null && b > 0) return { tc: b, source: 'blue', asOf: dates[best] }
    }
    return NADA
  }

  // Espeja `fx_for_date` del backend, que prefiere el MEP: lo usa la vista previa del
  // depósito para no mostrar un dólar distinto del que se va a guardar. Los
  // consumidores viejos siguen con getRateOrFallback (blue).
  function getMepOrFallback(dateIso) {
    if (!dateIso) return fallbackRef.current
    const { tc } = getMepDetail(dateIso)
    return tc != null && tc > 0 ? tc : getRateOrFallback(dateIso)
  }

  return {
    loaded: !!data,
    getRateForDate,
    getRateOrFallback,
    getMepOrFallback,
    getMepDetail,
    // Clave estable para memoizar cálculos que dependen de la serie: cambia
    // cuando la serie termina de cargar (o se recarga), no en cada render.
    fxKey: fxIndex.dates.length,
  }
}
