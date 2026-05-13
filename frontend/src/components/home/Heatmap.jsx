// Heatmap — bloques tipo Finviz para el S&P 500.
//
// Layout: squarified treemap simplificado (sin lib externa). Cada bloque:
//   - size proporcional al market_cap
//   - color por change_pct (escala verde/rojo)
//   - click → abre AssetQuickView (modal mini-ficha)
//
// V1: solo S&P 500 (50 nombres). V1.5 agrega Merval + cripto.
// V2: real-time prices con polling 60s.

import { useEffect, useState } from 'react'
import { api } from '../../utils/api'
import AssetQuickView from './AssetQuickView'

function colorForChange(pct) {
  // Escala continua: -5% rojo fuerte → 0% gris → +5% verde fuerte
  if (pct == null) return '#475569' // ink-2-ish (sin data)
  const clamp = Math.max(-5, Math.min(5, pct))
  const intensity = Math.abs(clamp) / 5  // 0 to 1
  if (clamp >= 0) {
    // Green: from neutral to rendi-pos (#22c55e)
    const r = Math.round(60 + (34 - 60) * intensity)
    const g = Math.round(80 + (197 - 80) * intensity)
    const b = Math.round(80 + (94 - 80) * intensity)
    return `rgb(${r},${g},${b})`
  }
  // Red: from neutral to rendi-neg (#ef4444)
  const r = Math.round(80 + (239 - 80) * intensity)
  const g = Math.round(80 + (68 - 80) * intensity)
  const b = Math.round(80 + (68 - 80) * intensity)
  return `rgb(${r},${g},${b})`
}

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(1)}%`
}

// ─── Squarified-ish layout ───────────────────────────────────────────────────
// Layout simple: dividimos el área en filas, cada fila proporcional a un grupo
// de blocks. Para V1 usamos un algoritmo greedy: tomamos los más grandes en una
// fila hasta que el aspect ratio se vuelve mejor en una nueva.
// El resultado es aproximado pero visualmente decente para ~50 bloques.

function squarify(blocks, width, height) {
  // Total para normalizar
  const total = blocks.reduce((s, b) => s + Math.max(b.market_cap, 1), 0)
  if (total === 0) return []
  const totalArea = width * height
  const items = blocks.map(b => ({
    ...b,
    area: (Math.max(b.market_cap, 1) / total) * totalArea,
  }))
  // Ordenar desc
  items.sort((a, b) => b.area - a.area)

  const result = []
  let x = 0, y = 0
  let availW = width, availH = height
  let i = 0

  while (i < items.length) {
    // Tomamos una "fila" en la dirección más corta
    const isHoriz = availW >= availH
    const lineLen = isHoriz ? availW : availH
    const lineThickness = isHoriz ? availH : availW

    // Acumulamos hasta que el aspect ratio empeore
    let row = []
    let rowArea = 0
    let bestAspect = Infinity

    while (i < items.length) {
      const next = items[i]
      const tryArea = rowArea + next.area
      const tryRowDepth = tryArea / lineLen
      // Aspect ratio peor de la fila
      let worst = 0
      for (const it of [...row, next]) {
        const w = isHoriz ? (it.area / tryRowDepth) : tryRowDepth
        const h = isHoriz ? tryRowDepth : (it.area / tryRowDepth)
        const ar = Math.max(w / h, h / w)
        if (ar > worst) worst = ar
      }
      if (worst < bestAspect || row.length === 0) {
        row.push(next)
        rowArea = tryArea
        bestAspect = worst
        i++
      } else {
        break
      }
    }

    // Render fila
    const rowDepth = Math.min(rowArea / lineLen, lineThickness)
    let cursor = 0
    for (const it of row) {
      const sideLen = it.area / rowDepth
      const block = {
        ...it,
        x: isHoriz ? (x + cursor) : x,
        y: isHoriz ? y : (y + cursor),
        w: isHoriz ? sideLen : rowDepth,
        h: isHoriz ? rowDepth : sideLen,
      }
      result.push(block)
      cursor += sideLen
    }

    if (isHoriz) {
      y += rowDepth
      availH -= rowDepth
    } else {
      x += rowDepth
      availW -= rowDepth
    }
  }
  return result
}


// ─── Componente ──────────────────────────────────────────────────────────────

const WIDTH = 1200
const HEIGHT = 540

const MARKETS = [
  { key: 'sp500',  label: 'S&P 500' },
  { key: 'merval', label: 'Merval' },
  { key: 'crypto', label: 'Cripto' },
]

export default function Heatmap({ defaultMarket = "sp500" }) {
  const [market, setMarket] = useState(defaultMarket)
  const [blocks, setBlocks] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setErr(null)
    api.get(`/home/heatmap?market=${market}`)
      .then(d => { if (!cancelled) setBlocks(d.blocks || []) })
      .catch(ex => { if (!cancelled) setErr(ex.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [market])

  // Tabs siempre visibles (incluso durante loading), así el user no pierde el switcher
  const Tabs = (
    <div className="inline-flex gap-1 bg-bg-2 border border-line rounded-sm p-0.5">
      {MARKETS.map(m => (
        <button
          key={m.key}
          onClick={() => setMarket(m.key)}
          className={`px-2.5 py-1 text-xs rounded-sm transition-colors ${
            market === m.key
              ? 'bg-bg-1 text-ink-0 font-medium'
              : 'text-ink-2 hover:text-ink-0'
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  )

  const laid = loading || err || blocks.length === 0 ? [] : squarify(blocks, WIDTH, HEIGHT)

  return (
    <>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-wider text-ink-3 font-mono">
          {MARKETS.find(m => m.key === market)?.label || market} · {blocks.length} activos
        </div>
        {Tabs}
      </div>
      {loading && (
        <div className="rounded-sm bg-bg-2 animate-pulse" style={{ aspectRatio: `${WIDTH}/${HEIGHT}` }} />
      )}
      {err && !loading && (
        <div className="text-xs text-rendi-neg p-4">Heatmap no disponible: {err}</div>
      )}
      {!loading && !err && blocks.length === 0 && (
        <div className="text-xs text-ink-3 p-4">Sin data del heatmap por ahora.</div>
      )}
      {!loading && !err && blocks.length > 0 && (
      <div
        className="relative rounded-sm overflow-hidden border border-line"
        style={{ width: "100%", aspectRatio: `${WIDTH}/${HEIGHT}` }}
      >
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          preserveAspectRatio="none"
          className="absolute inset-0 w-full h-full"
        >
          {laid.map(b => (
            <g key={b.symbol} onClick={() => setSelected(b)} style={{ cursor: 'pointer' }}>
              <rect
                x={b.x} y={b.y} width={b.w} height={b.h}
                fill={colorForChange(b.change_pct)}
                stroke="#0a0a0b"
                strokeWidth="1"
              />
              {b.w > 50 && b.h > 28 && (
                <>
                  <text
                    x={b.x + b.w / 2} y={b.y + b.h / 2 - 4}
                    textAnchor="middle"
                    fill="white"
                    fontSize={Math.min(b.w / 4, b.h / 3, 22)}
                    fontWeight="600"
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {b.symbol}
                  </text>
                  {b.h > 50 && (
                    <text
                      x={b.x + b.w / 2} y={b.y + b.h / 2 + 14}
                      textAnchor="middle"
                      fill="rgba(255,255,255,0.85)"
                      fontSize={Math.min(b.w / 7, 12)}
                      fontFamily="monospace"
                      style={{ pointerEvents: 'none', userSelect: 'none' }}
                    >
                      {fmtPct(b.change_pct)}
                    </text>
                  )}
                </>
              )}
            </g>
          ))}
        </svg>
      </div>
      )}
      {selected && (
        <AssetQuickView
          symbol={selected.symbol}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  )
}
