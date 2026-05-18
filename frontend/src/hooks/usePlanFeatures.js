// usePlanFeatures — feature flags + límites del tier del user.
// ═══════════════════════════════════════════════════════════════════════════
// Fuente única de verdad para "qué puede ver/hacer el user". Consume el
// endpoint /api/plan/features que el backend resuelve desde ai/plan.py.
//
// API:
//   const { tier, limits, loading, can, isFree, isPro, isAdmin } = usePlanFeatures()
//
// Helpers:
//   can('insights.distribucion_activo')  → bool
//   limit('insights_diagnostic_visible') → number | null (null = sin tope)
//
// Cache: el hook usa useRef compartido por modulo + invalidate via versión
// global incrementada. Esto evita refetch en cada montaje de componente y
// permite forzar refresh post-upgrade.

import { useEffect, useState } from 'react'
import { api } from '../utils/api'

// Cache módulo-level: 1 fetch por sesión, compartido entre todos los hooks.
let _cached = null
let _inflight = null
let _version = 0
const _listeners = new Set()

function _notify() {
  _listeners.forEach(fn => fn(_version))
}

/**
 * Forzar refetch (ej. después de un upgrade exitoso o cambio de tier).
 * Cualquier componente con usePlanFeatures se va a actualizar.
 */
export function refreshPlanFeatures() {
  _cached = null
  _inflight = null
  _version += 1
  _notify()
}

async function _fetch() {
  if (_cached) return _cached
  if (_inflight) return _inflight
  _inflight = api.get('/plan/features')
    .then(data => { _cached = data; _inflight = null; return data })
    .catch(err => { _inflight = null; throw err })
  return _inflight
}

export function usePlanFeatures() {
  const [features, setFeatures] = useState(_cached)
  const [loading, setLoading] = useState(!_cached)
  const [error, setError] = useState(null)
  const [, setLocalVersion] = useState(_version)

  useEffect(() => {
    let cancelled = false

    const listener = () => {
      setLocalVersion(_version)
      setLoading(true)
      _fetch()
        .then(data => { if (!cancelled) { setFeatures(data); setLoading(false) } })
        .catch(err => { if (!cancelled) { setError(err); setLoading(false) } })
    }
    _listeners.add(listener)

    if (!_cached) {
      _fetch()
        .then(data => { if (!cancelled) { setFeatures(data); setLoading(false) } })
        .catch(err => { if (!cancelled) { setError(err); setLoading(false) } })
    } else {
      setLoading(false)
    }

    return () => { cancelled = true; _listeners.delete(listener) }
  }, [])

  const tier = features?.tier || 'free'
  const limits = features?.limits || {}
  const access = features?.access || {}

  return {
    features,
    loading,
    error,
    tier,
    limits,
    access,
    // Helpers
    can: (featureId) => access[featureId] === true,
    limit: (key) => limits[key],
    isFree: tier === 'free',
    isPro: tier === 'pro',
    isAdmin: tier === 'admin',
    // Convenience: cualquier tier pago/admin tiene "features completas"
    hasFullAccess: tier === 'pro' || tier === 'admin',
  }
}
