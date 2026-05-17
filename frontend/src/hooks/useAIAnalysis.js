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

// Hard cap a 2 follow-ups por análisis — coincide con el cap del schema
// backend. Después de eso las chips dejan de mostrarse.
const MAX_FOLLOWUPS_PER_ANALYSIS = 2

export function useAIAnalysis({ screen, params, autoload = true } = {}) {
  const [result, setResult] = useState(null)
  const [usage, setUsage] = useState(null)
  const [tier, setTier] = useState(null)
  const [cached, setCached] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [upgradePayload, setUpgradePayload] = useState(null)
  // Follow-ups acumulados por sesión: cada uno es {question, result}
  const [followups, setFollowups] = useState([])
  const [followupLoading, setFollowupLoading] = useState(false)

  const analyze = useCallback(async () => {
    if (!screen) return
    setLoading(true)
    setError(null)
    setUpgradePayload(null)
    setFollowups([])  // reset cuando se hace un análisis nuevo
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

  // askFollowUp(question) — dispara una request al mismo topic + packet
  // pero con la pregunta puntual del user. Cuesta como cualquier análisis
  // (descuenta del cupo). Cap a 2 follow-ups por análisis principal.
  const askFollowUp = useCallback(async (question) => {
    if (!screen || !question) return
    if (followups.length >= MAX_FOLLOWUPS_PER_ANALYSIS) {
      track('ai_followup_blocked_cap', { screen, count: followups.length })
      return
    }
    setFollowupLoading(true)
    try {
      const t0 = performance.now()
      const data = await api.post('/ai/analyze', {
        screen,
        params: params || {},
        followup_question: question,
      })
      const ms = Math.round(performance.now() - t0)
      setFollowups(prev => [...prev, { question, result: data.result }])
      if (data.usage) {
        setUsage(data.usage)
        setTier(data.tier || data.usage?.tier || null)
      }
      track('ai_followup_loaded', { screen, ms, count_after: followups.length + 1 })
    } catch (ex) {
      const msg = ex?.message || 'No pudimos generar la respuesta.'
      const detail = ex?.payload?.detail
      const upgrade = detail?.upgrade
      const usagePayload = detail?.usage
      if (usagePayload) {
        setUsage(usagePayload)
        setTier(usagePayload.tier || null)
      }
      if (upgrade) setUpgradePayload(upgrade)
      // El error se muestra como un follow-up "fallido" para que el user
      // entienda qué pasó sin perder los anteriores
      setFollowups(prev => [
        ...prev,
        { question, error: msg },
      ])
      track('ai_followup_error', { screen, status: ex?.status, error: msg })
    } finally {
      setFollowupLoading(false)
    }
  }, [screen, JSON.stringify(params), followups.length]) // eslint-disable-line react-hooks/exhaustive-deps

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
    followups,
    followupLoading,
    followupsExhausted: followups.length >= MAX_FOLLOWUPS_PER_ANALYSIS,
    analyze,
    refresh,
    askFollowUp,
  }
}
