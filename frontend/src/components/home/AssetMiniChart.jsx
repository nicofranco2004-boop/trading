// AssetMiniChart — chart histórico compacto para AssetQuickView.
//
// Diferencia con MiniSparkline:
//   - Range selector (1S | 1M | 3M | 1A)
//   - Muestra primer/último close + delta del período
//   - Renderea ejes mínimos (high/low del período en esquinas)
//   - Mantiene la estética del modal "quick view" (sin labels innecesarios)
//   - Con el dedo o el mouse encima: línea vertical, punto y globo con la
//     fecha, el precio y el cambio desde el inicio del período. Va en HTML
//     encima del SVG: el SVG se estira (preserveAspectRatio "none") y un
//     círculo dibujado adentro saldría ovalado.
//   - Al cambiar de período la línea se redibuja de izquierda a derecha y
//     queda sólida (useTrazo, la misma pieza de las mini líneas).
//
// Backend: GET /api/prices/history?symbol=X&period=1m
// Cache backend: 1h (las velas diarias no cambian intraday)

import { useEffect, useState } from 'react'
import { api } from '../../utils/api'
import { pctVar } from '../../utils/format'
import { trendStroke } from '../../utils/chartTheme'
import { diaMes } from '../../utils/fecha'
import { useTrazo } from '../../hooks/useTrazo'

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
  if (v >= 1000) return v.toLocaleString('es-AR', { maximumFractionDigits: 0 })
  return v.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export default function AssetMiniChart({ symbol }) {
  const [range, setRange] = useState('1m')
  const [points, setPoints] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [puntero, setPuntero] = useState(null)   // índice del punto bajo el dedo/mouse
  // Se redibuja al cambiar de activo o de período y queda sólida (useTrazo).
  const trazo = useTrazo(`${symbol}-${range}`)

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
  // Tokens del tema (chartTheme): antes eran dos hex fijos pensados para fondo
  // oscuro, que en claro se veían lavados.
  const color = trendStroke(positive)
  const gradId = `assetchart-${positive ? 'p' : 'n'}`

  // Dedo o mouse → índice del punto más cercano en X.
  function moverPuntero(e) {
    if (closes.length < 2) return
    const r = e.currentTarget.getBoundingClientRect()
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width))
    setPuntero(Math.round(frac * (closes.length - 1)))
  }
  const pt = puntero != null && puntero < closes.length ? {
    x: (puntero / Math.max(closes.length - 1, 1)) * 100,
    y: (svgPoints[puntero][1] / HEIGHT) * 100,
    close: closes[puntero],
    date: points[puntero]?.date,
    pct: first ? (closes[puntero] / first - 1) * 100 : null,
  } : null

  return (
    <div className="space-y-2">
      {/* Header con delta del período + range selector */}
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] text-ink-3">
          {loading ? (
            'cargando…'
          ) : err ? (
            // Mensaje NUESTRO, no el del backend: el detail crudo ("Símbolo
            // inválido: FCI:…") expone el símbolo interno y se lee como si la
            // posición del usuario estuviera mal cargada, cuando lo que pasa es
            // que ese activo no tiene serie de precios.
            <span className="text-ink-3">Sin gráfico para este activo</span>
          ) : closes.length < 2 ? (
            'Sin historial disponible'
          ) : (
            <>
              <span className="font-mono tabular text-ink-2">${fmtPrice(first)}</span>
              <span className="mx-1">→</span>
              <span className="font-mono tabular text-ink-1">${fmtPrice(last)}</span>
              <span className={`ml-2 font-mono tabular ${positive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                {pctVar(delta)}
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
      <div
        className="relative rounded-sm bg-bg-2/40 border border-line overflow-hidden"
        style={{ aspectRatio: `${WIDTH}/${HEIGHT}`, touchAction: 'pan-y' }}
        onPointerMove={moverPuntero}
        onPointerDown={moverPuntero}
        onPointerLeave={() => setPuntero(null)}
      >
        {loading || closes.length < 2 ? (
          <div className="w-full h-full bg-bg-2/30 esqueleto" />
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
            <path key={`area-${symbol}-${range}`} className="area-aparece" d={areaPath} fill={`url(#${gradId})`} />
            <path
              key={`linea-${symbol}-${range}`}
              {...trazo}
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
        {pt && !loading && closes.length >= 2 && (
          <>
            <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-px bg-ink-2/40" style={{ left: `${pt.x}%` }} />
            <div
              aria-hidden="true"
              className={`pointer-events-none absolute w-2 h-2 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg-1 ${positive ? 'bg-rendi-pos-fill' : 'bg-rendi-neg-fill'}`}
              style={{ left: `${pt.x}%`, top: `${pt.y}%` }}
            />
            <div
              className="pointer-events-none absolute top-1 rounded border border-line-2 bg-bg-raised px-2 py-1 text-[11px] leading-tight whitespace-nowrap shadow-sm tabular"
              style={{ left: `${Math.min(80, Math.max(20, pt.x))}%`, transform: 'translateX(-50%)' }}
            >
              <span className="text-ink-3">{diaMes(pt.date)}{pt.date ? `/${pt.date.slice(2, 4)}` : ''}</span>
              <span className="mx-1 text-ink-0 font-medium">${fmtPrice(pt.close)}</span>
              {pt.pct != null && (
                <span className={pt.pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}>{pctVar(pt.pct)}</span>
              )}
            </div>
          </>
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
