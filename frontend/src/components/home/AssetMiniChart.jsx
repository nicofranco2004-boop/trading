// AssetMiniChart — chart histórico compacto para AssetQuickView.
//
// Diferencia con MiniSparkline:
//   - Range selector (1S | 1M | 3M | 1A)
//   - Muestra primer/último close + delta del período
//   - Renderea ejes mínimos (high/low del período en esquinas)
//   - Mantiene la estética del modal "quick view" (sin labels innecesarios)
//
// Backend: GET /api/prices/history?symbol=X&period=1m
// Cache backend: 1h (las velas diarias no cambian intraday)

import { useEffect, useState } from 'react'
import { api } from '../../utils/api'

const RANGES = [
  { key: '1w',  label: '1S' },
  { key: '1m',  label: '1M' },
  { key: '3m',  label: '3M' },
  { key: '1y',  label: '1A' },
]

const WIDTH = 320
const HEIGHT = 100

function fmtPrice(v) {
  if (v == null) return '—'
  if (v >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 0 })
  return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(2)}%`
}

export default function AssetMiniChart({ symbol }) {
  const [range, setRange] = useState('1m')
  const [points, setPoints] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (!symbol) return
    let cancelled = false
    setLoading(true)
    setErr(null)
    api.get(`/prices/history?symbol=${encodeURIComponent(symbol)}&period=${range}`)
      .then(d => { if (!cancelled) setPoints(d.points || []) })
      .catch(ex => { if (!cancelled) setErr(ex.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [symbol, range])

  const closes = points.map(p => p.close)
  const first = closes[0]
  const last = closes[closes.length - 1]
  const delta = (first != null && last != null) ? ((last / first - 1) * 100) : null
  const positive = delta == null ? true : delta >= 0
  const min = closes.length > 0 ? Math.min(...closes) : 0
  const max = closes.length > 0 ? Math.max(...closes) : 1
  const range_ = max - min || 1

  // SVG path
  const stepX = WIDTH / Math.max(closes.length - 1, 1)
  const svgPoints = closes.map((v, i) => [
    i * stepX,
    HEIGHT - ((v - min) / range_) * HEIGHT,
  ])
  const path = svgPoints
    .map(([x, y], i) => (i === 0 ? `M${x.toFixed(1)},${y.toFixed(1)}` : `L${x.toFixed(1)},${y.toFixed(1)}`))
    .join(' ')
  const areaPath = svgPoints.length >= 2
    ? `${path} L${WIDTH.toFixed(1)},${HEIGHT} L0,${HEIGHT} Z`
    : ''
  const color = positive ? '#6FE3A3' : '#F17A7A'
  const gradId = `assetchart-${positive ? 'p' : 'n'}`

  return (
    <div className="space-y-2">
      {/* Header con delta del período + range selector */}
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] text-ink-3">
          {loading ? (
            'cargando…'
          ) : err ? (
            <span className="text-rendi-neg">{err}</span>
          ) : closes.length < 2 ? (
            'Sin historial disponible'
          ) : (
            <>
              <span className="font-mono tabular text-ink-2">${fmtPrice(first)}</span>
              <span className="mx-1">→</span>
              <span className="font-mono tabular text-ink-1">${fmtPrice(last)}</span>
              <span className={`ml-2 font-mono tabular ${positive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                {fmtPct(delta)}
              </span>
            </>
          )}
        </div>
        <div className="inline-flex gap-0.5 bg-bg-2 border border-line rounded-sm p-0.5">
          {RANGES.map(r => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={`px-1.5 py-0.5 text-[10px] rounded-sm transition-colors ${
                range === r.key
                  ? 'bg-bg-1 text-ink-0 font-medium'
                  : 'text-ink-2 hover:text-ink-0'
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div className="rounded-sm bg-bg-2/40 border border-line overflow-hidden" style={{ aspectRatio: `${WIDTH}/${HEIGHT}` }}>
        {loading || closes.length < 2 ? (
          <div className="w-full h-full bg-bg-2/30 animate-pulse" />
        ) : (
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            preserveAspectRatio="none"
            className="w-full h-full"
            aria-hidden="true"
          >
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.25} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <path d={areaPath} fill={`url(#${gradId})`} />
            <path
              d={path}
              stroke={color}
              strokeWidth={1.5}
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        )}
      </div>

      {/* Footer min/max */}
      {!loading && closes.length >= 2 && (
        <div className="flex justify-between text-[10px] text-ink-3 font-mono">
          <span>min ${fmtPrice(min)}</span>
          <span>max ${fmtPrice(max)}</span>
        </div>
      )}
    </div>
  )
}
