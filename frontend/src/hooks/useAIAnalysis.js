// useAIAnalysis — orquesta el flow de /api/ai/analyze.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint AI v2 — hook reutilizable que cualquier "Analizar" usa.
//
// API:
//   const { result, usage, cached, loading, error, analyze, refresh } =
//     useAIAnalysis({ screen, params, autoload: true })
//
// Behavior:
//   - autoload: true → llama analyze() al montar
//   - refresh(): DELETE /api/ai/cache/{screen} + reanalyze
//   - El backend devuelve result + cached (bool) + usage (quota actual)

import { useCallback, useEffect, useState } from 'react'
import { api } from '../utils/api'
import { track } from '../utils/track'

export function useAIAnalysis({ screen, params, autoload = true } = {}) {
  const [result, setResult] = useState(null)
  const [usage, setUsage] = useState(null)
  const [tier, setTier] = useState(null)
  const [cached, setCached] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [upgradePayload, setUpgradePayload] = useState(null)

  const analyze = useCallback(async () => {
    if (!screen) return
    setLoading(true)
    setError(null)
    setUpgradePayload(null)
    try {
      const t0 = performance.now()
      const data = await api.post('/ai/analyze', { screen, params: params || {} })
      const ms = Math.round(performance.now() - t0)
      setResult(data.result)
      setCached(!!data.cached)
      setUsage(data.usage)
      setTier(data.tier || data.usage?.tier || null)
      track('ai_analyze_loaded', { screen, cached: !!data.cached, tier: data.tier, ms })
    } catch (ex) {
      // El backend devuelve 429 con detail={error, usage, upgrade} cuando
      // se acaba el cupo. api.js extrae el .error como ex.message y deja el
      // payload completo en ex.payload.detail para que actualicemos badge
      // y mostremos el upgrade card.
      const msg = ex?.message || 'No pudimos generar el análisis.'
      setError(msg)
      const detail = ex?.payload?.detail
      const usagePayload = detail?.usage
      const upgrade = detail?.upgrade
      if (usagePayload) {
        setUsage(usagePayload)
        setTier(usagePayload.tier || null)
      }
      if (upgrade) setUpgradePayload(upgrade)
      track('ai_analyze_error', { screen, status: ex?.status, error: msg })
    } finally {
      setLoading(false)
    }
  }, [screen, JSON.stringify(params)]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = useCallback(async () => {
    if (!screen) return
    try {
      await api.delete(`/ai/cache/${screen}`)
      track('ai_analyze_refresh', { screen })
    } catch {
      // Si falla el delete (404 raro), seguimos al analyze igual
    }
    await analyze()
  }, [screen, analyze])

  useEffect(() => {
    if (autoload && screen) analyze()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [screen, JSON.stringify(params), autoload])

  return {
    result,
    usage,
    tier,
    cached,
    loading,
    error,
    upgrade: upgradePayload,
    analyze,
    refresh,
  }
}
