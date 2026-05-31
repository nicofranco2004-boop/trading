// useFxHistory — Phase C (2026-05-31).
//
// Fetcha /api/fx-rates una vez por sesión y expone helpers de lookup por
// fecha. Cuando el toggle global está en ARS y el caller necesita convertir
// un valor histórico (snapshot, monthly entry, operación vieja), debe usar
// el TC que existía en ESA fecha — no el actual.
//
// Fallbacks:
//   • Si la API falla → devuelve un map vacío + fallbackTcBlue (el actual).
//   • Si una fecha no está en el map → busca el día anterior más cercano.
//   • Si nada existe → fallbackTcBlue.
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
let _fxCachePromise = null
let _fxCacheData = null

function fetchFxHistory() {
  if (_fxCachePromise) return _fxCachePromise
  if (_fxCacheData) return Promise.resolve(_fxCacheData)
  _fxCachePromise = api.get('/fx-rates?days=3650')
    .then(rows => {
      _fxCacheData = Array.isArray(rows) ? rows : []
      _fxCachePromise = null
      return _fxCacheData
    })
    .catch(() => {
      _fxCachePromise = null
      _fxCacheData = []
      return _fxCacheData
    })
  return _fxCachePromise
}

/**
 * Hook que devuelve la historia de blue + un helper getRateForDate.
 *
 * @param {number} fallbackTcBlue — blue actual (del context o de un fetch local)
 * @returns {{
 *   loaded: boolean,
 *   getRateForDate: (dateIso: string) => number | null,
 *   getRateOrFallback: (dateIso: string) => number,
 * }}
 */
export function useFxHistory(fallbackTcBlue = 1415) {
  const [data, setData] = useState(_fxCacheData)
  const fallbackRef = useRef(fallbackTcBlue)
  fallbackRef.current = fallbackTcBlue

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

  function getRateForDate(dateIso) {
    return lookupRate(sortedRows, dateIso)
  }

  function getRateOrFallback(dateIso) {
    const r = getRateForDate(dateIso)
    return r != null && r > 0 ? r : fallbackRef.current
  }

  return {
    loaded: !!data,
    getRateForDate,
    getRateOrFallback,
  }
}
