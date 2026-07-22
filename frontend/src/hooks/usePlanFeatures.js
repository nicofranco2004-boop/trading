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
//
// Además, cacheamos en localStorage para evitar el "flash" entre page loads:
// sin cache, cada hard refresh empieza con tier=free durante 100-500ms y los
// componentes que gateaban por tier mostraban brevemente la versión Free
// (Insights ocultaba métricas pro, Behavioral mostraba previews lockeadas).
// Con localStorage el primer render es instantáneo con el tier conocido —
// el fetch real corre en background y reconcilia si cambió.
//
// SECURITY: el tier en localStorage NO sustituye el gate del backend (el
// backend valida el JWT del user y resuelve tier server-side). Es solo
// hint visual para UX — manipular localStorage no desbloquea features.
const LS_KEY = 'rendi_plan_features_v1'
let _cached = null
let _inflight = null
let _version = 0
const _listeners = new Set()

// Hydrate desde localStorage al cargar el módulo. Si hay basura corrupta,
// fail-open: simplemente arrancamos sin cache (igual que antes).
try {
  if (typeof window !== 'undefined') {
    const raw = localStorage.getItem(LS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      // Validación mínima de shape — evita usar cache de un formato viejo
      if (parsed && typeof parsed === 'object' && typeof parsed.tier === 'string') {
        _cached = parsed
      }
    }
  }
} catch { /* ignore */ }

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
  try { localStorage.removeItem(LS_KEY) } catch { /* ignore */ }
  _notify()
}

async function _fetch() {
  if (_inflight) return _inflight
  _inflight = api.get('/plan/features')
    .then(data => {
      _cached = data
      _inflight = null
      // Persistir en localStorage para próximo page load (hidratación instant)
      try { localStorage.setItem(LS_KEY, JSON.stringify(data)) } catch { /* ignore */ }
      return data
    })
    .catch(err => { _inflight = null; throw err })
  return _inflight
}

export function usePlanFeatures() {
  // Si hay cache (memoria o localStorage), arrancamos con tier conocido —
  // no hay flash. Si no hay nada, arrancamos con loading=true.
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

    // Siempre revalidamos en background — incluso con cache hidratado de
    // localStorage. Esto detecta upgrades hechos en otra pestaña/sesión sin
    // necesidad de reload manual.
    _fetch()
      .then(data => {
        if (cancelled) return
        setFeatures(data)
        setLoading(false)
      })
      .catch(err => { if (!cancelled) { setError(err); setLoading(false) } })

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
    isPlus: tier === 'plus',
    isPro: tier === 'pro',
    isAdvisor: tier === 'advisor',
    isAdmin: tier === 'admin',
    // Plan Asesor: true cuando el asesor está mirando la cuenta de un cliente
    // (el backend resolvió el header y devolvió el lente Pro sobre ella).
    clientCtx: features?.client_ctx === true,
    // Convenience flags — 'advisor' cuenta como pago y con acceso full: para
    // su PROPIA cuenta el asesor tiene features nivel Pro (paga 4-8× un Pro).
    isPaid: tier === 'plus' || tier === 'pro' || tier === 'advisor' || tier === 'admin',
    // hasFullAccess es Pro/Advisor/Admin — Plus tiene features parciales (sin
    // IA avanzada). Componentes que gateaban con `hasFullAccess` siguen
    // bloqueando Plus en features Pro-only (ai.followup, ai.hub).
    hasFullAccess: tier === 'pro' || tier === 'advisor' || tier === 'admin',
  }
}
