// useReportsTimeline — fetchea la timeline del backend y la agrupa por año.
//
// El backend devuelve los últimos N meses (descendentes), cada uno con sus
// semanas como children. Acá agrupamos por año para que el frontend pueda
// renderizar bandas tipo "2026", "2025" entre los meses.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../utils/api'
import { useModoRendimiento } from '../contexts/ModoRendimientoContext'

/**
 * @param {string} broker        broker_filter: 'global' | nombre del broker
 * @param {number} months        cantidad de meses a mostrar (default 12)
 * @param {string} [modo]        'certero' | 'estimado'. Sin él, la elección guardada
 *                               del usuario (ModoRendimientoContext).
 * @param {string} moneda        'usd' | 'ars' — sigue al selector global de moneda
 * @returns {{
 *   loading: boolean,
 *   error: string | null,
 *   yearGroups: Array<{ year: number, months: PeriodReport[] }>,
 *   rankingPorAnio: { [year: string]: { base, mejor, peor, positivos, total, sin_medir_a_mercado } },
 *   hasAnyData: boolean,
 *   reload: () => void,
 * }}
 */
export default function useReportsTimeline(broker = 'global', months = 12,
                                          modoPedido, moneda = 'usd') {
  const [modoApp] = useModoRendimiento()
  const modo = modoPedido || modoApp
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [reports, setReports] = useState([])
  // El mejor y el peor mes de cada año, elegidos por el servidor
  // (`twr.mejor_y_peor_mes`). Se lee, no se recalcula: ver PerformanceCalendar.
  const [rankingPorAnio, setRankingPorAnio] = useState({})
  const [trigger, setTrigger] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.get(`/reports/timeline?broker=${encodeURIComponent(broker)}&months=${months}`
            + `&modo=${encodeURIComponent(modo)}&moneda=${encodeURIComponent(moneda)}`)
      .then(data => {
        if (cancelled) return
        setReports(data?.reports || [])
        setRankingPorAnio(data?.ranking_por_anio || {})
      })
      .catch(ex => {
        if (cancelled) return
        setError(ex.message || 'No pudimos cargar la timeline.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [broker, months, modo, moneda, trigger])

  // Group por año (cronológico descendente — año en curso arriba).
  // Memoizado: sin memo se crea una referencia nueva en cada render y
  // rompe los useEffect downstream con dependencia sobre yearGroups.
  const yearGroups = useMemo(() => {
    const groups = new Map()
    for (const r of reports) {
      const y = parseInt(r.period_key.slice(0, 4), 10)
      if (!groups.has(y)) groups.set(y, [])
      groups.get(y).push(r)
    }
    return [...groups.entries()]
      .sort((a, b) => b[0] - a[0])
      .map(([year, months]) => ({ year, months }))
  }, [reports])

  return {
    loading,
    error,
    yearGroups,
    rankingPorAnio,
    hasAnyData: reports.length > 0,
    reload: () => setTrigger(t => t + 1),
  }
}
