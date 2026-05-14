// LazySparkline — sparkline 30d que solo fetchea cuando entra al viewport.
// ═══════════════════════════════════════════════════════════════════════════
// Pensado para tablas largas (Posiciones) donde renderear N requests a la vez
// sería pesado. IntersectionObserver dispara el fetch al scrollear hasta ese
// row. Cache global de series por símbolo (no re-fetch entre re-renders).
//
// Uso:
//   <LazySparkline symbol="NVDA" width={80} height={20} />
//   <LazySparkline symbol="BTC"  variant="row" />

import { useEffect, useRef, useState } from 'react'
import { api } from '../utils/api'
import Sparkline from './Sparkline'

// Cache global de series → no duplicar requests cuando varias filas comparten
// el mismo símbolo, ni re-fetchear al re-render. TTL implícito = vida de sesión
// (el backend cachea 1h internamente, así que esto es más bien deduplicación).
const seriesCache = new Map()      // symbol → number[] | 'empty'
const inFlight = new Map()         // symbol → Promise

async function fetchSeries(symbol) {
  if (seriesCache.has(symbol)) {
    const v = seriesCache.get(symbol)
    return v === 'empty' ? [] : v
  }
  if (inFlight.has(symbol)) return inFlight.get(symbol)

  const p = (async () => {
    try {
      const res = await api.get(`/prices/history?symbol=${encodeURIComponent(symbol)}&period=1m`)
      const points = (res?.points || [])
        .map(p => Number(p.close))
        .filter(n => Number.isFinite(n))
      if (points.length < 2) {
        seriesCache.set(symbol, 'empty')
        return []
      }
      seriesCache.set(symbol, points)
      return points
    } catch {
      seriesCache.set(symbol, 'empty')
      return []
    } finally {
      inFlight.delete(symbol)
    }
  })()
  inFlight.set(symbol, p)
  return p
}

export function useLazySparkline(symbol, options = {}) {
  const ref = useRef(null)
  const [data, setData] = useState(() => {
    // Si ya está cacheado, no esperar al observer
    if (symbol && seriesCache.has(symbol)) {
      const v = seriesCache.get(symbol)
      return v === 'empty' ? [] : v
    }
    return null
  })
  const [ready, setReady] = useState(() => symbol && seriesCache.has(symbol))

  useEffect(() => {
    if (!symbol || ready) return
    const el = ref.current
    if (!el) return
    if (typeof IntersectionObserver === 'undefined') {
      // Fallback: fetch inmediato
      fetchSeries(symbol).then(d => { setData(d); setReady(true) })
      return
    }
    let cancelled = false
    const obs = new IntersectionObserver(
      entries => {
        if (cancelled) return
        for (const e of entries) {
          if (e.isIntersecting) {
            fetchSeries(symbol).then(d => {
              if (!cancelled) {
                setData(d)
                setReady(true)
              }
            })
            obs.disconnect()
            break
          }
        }
      },
      { rootMargin: options.rootMargin || '100px', threshold: 0 }
    )
    obs.observe(el)
    return () => { cancelled = true; obs.disconnect() }
  }, [symbol, ready, options.rootMargin])

  return { ref, data, ready }
}

export default function LazySparkline({ symbol, variant = 'row', width, height, className = '' }) {
  const { ref, data, ready } = useLazySparkline(symbol)
  // Tamaño placeholder consistente para que el layout no salte al cargar
  const dims = variant === 'inline'
    ? { w: width || 80, h: height || 20 }
    : variant === 'kpi'
      ? { w: width || 200, h: height || 48 }
      : { w: width || 100, h: height || 24 }

  return (
    <span ref={ref} className={`inline-block align-middle ${className}`} style={{ width: dims.w, height: dims.h }}>
      {ready && data && data.length >= 2 ? (
        <Sparkline data={data} variant={variant} width={dims.w} height={dims.h} />
      ) : (
        // Placeholder sutil — línea horizontal tenue mientras carga / sin datos
        <svg
          width={dims.w}
          height={dims.h}
          viewBox={`0 0 ${dims.w} ${dims.h}`}
          aria-hidden="true"
          className="opacity-40"
        >
          <line
            x1="2" x2={dims.w - 2}
            y1={dims.h / 2} y2={dims.h / 2}
            stroke="currentColor" strokeWidth="0.75" strokeDasharray="2 3"
            className="text-ink-3"
          />
        </svg>
      )}
    </span>
  )
}
