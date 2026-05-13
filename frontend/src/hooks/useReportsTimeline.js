// useReportsTimeline — fetchea la timeline del backend y la agrupa por año.
//
// El backend devuelve los últimos N meses (descendentes), cada uno con sus
// semanas como children. Acá agrupamos por año para que el frontend pueda
// renderizar bandas tipo "2026", "2025" entre los meses.

import { useEffect, useState } from 'react'
import { api } from '../utils/api'

/**
 * @param {string} broker        broker_filter: 'global' | nombre del broker
 * @param {number} months        cantidad de meses a mostrar (default 12)
 * @returns {{
 *   loading: boolean,
 *   error: string | null,
 *   yearGroups: Array<{ year: number, months: PeriodReport[] }>,
 *   hasAnyData: boolean,
 *   reload: () => void,
 * }}
 */
export default function useReportsTimeline(broker = 'global', months = 12) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [reports, setReports] = useState([])
  const [trigger, setTrigger] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.get(`/reports/timeline?broker=${encodeURIComponent(broker)}&months=${months}`)
      .then(data => {
        if (cancelled) return
        setReports(data?.reports || [])
      })
      .catch(ex => {
        if (cancelled) return
        setError(ex.message || 'No pudimos cargar la timeline.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [broker, months, trigger])

  // Group por año (cronológico descendente — año en curso arriba)
  const yearGroups = (() => {
    const groups = new Map()
    for (const r of reports) {
      const y = parseInt(r.period_key.slice(0, 4), 10)
      if (!groups.has(y)) groups.set(y, [])
      groups.get(y).push(r)
    }
    return [...groups.entries()]
      .sort((a, b) => b[0] - a[0])
      .map(([year, months]) => ({ year, months }))
  })()

  return {
    loading,
    error,
    yearGroups,
    hasAnyData: reports.length > 0,
    reload: () => setTrigger(t => t + 1),
  }
}
