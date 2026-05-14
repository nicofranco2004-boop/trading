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

// Escala G/R 9 pasos en lugar de continuo — más operativo, replica Finviz.
// Bins: <-3, -3 a -1.5, -1.5 a -0.5, -0.5 a 0, 0, 0 a 0.5, 0.5 a 1.5, 1.5 a 3, >3
const GREEN_BINS = ['#06160E', '#072A18', '#0B4127', '#0F5C36', '#14A560', '#21D07A', '#5FE19D', '#9CEDC0', '#CFF7DF']
const RED_BINS   = ['#1F0A0C', '#3E1418', '#5E1F25', '#8E2B33', '#C8333E', '#FF5360', '#FF8A93', '#FFB4BA', '#FFDADD']
const NEUTRAL    = '#1B2230'  // gunmetal (line)

function colorForChange(pct) {
  if (pct == null) return NEUTRAL
  if (Math.abs(pct) < 0.05) return NEUTRAL  // banda neutra muy chica
  const abs = Math.abs(pct)
  // Buckets: 0–0.5, 0.5–1, 1–2, 2–3, 3–5, 5+
  let idx = 4  // mid (default = G500/R400 — el "fuerte sobrio")
  if (abs < 0.5)      idx = 3
  else if (abs < 1)   idx = 4
  else if (abs < 2)   idx = 5  // = signal/red base (#21D07A / #FF5360)
  else if (abs < 3)   idx = 5
  else                idx = 5
  return pct >= 0 ? GREEN_BINS[idx] : RED_BINS[idx]
}

function fmtPct(p) {
  if (p == null) return '—'
  const sign = p >= 0 ? '+' : ''
  return `${sign}${p.toFixed(1)}%`
}

// Tickers crypto del backend vienen como `BTC-USD`, `ETH-USD`. El endpoint
// /api/prices/history valida con regex `[A-Z0-9]{1,10}(\.BA)?` y rechaza `-`.
// Limpiamos al abrir AssetQuickView así el modal puede pedir el chart.
function cleanSymbol(symbol) {
  if (!symbol) return symbol
  const m = symbol.match(/^([A-Z0-9]+)-(USD|USDT|USDC)$/)
  return m ? m[1] : symbol
}

// Versión chica del ticker para celdas que no entran: AAPL → AAPL, NVDA → NVDA,
// BTC-USD → BTC, AAPL.BA → AAPL.
function shortSymbol(symbol) {
  if (!symbol) return ''
  const clean = cleanSymbol(symbol)
  return clean.length > 6 ? clean.slice(0, 5) : clean
}

// ─── Squarified-ish layout ───────────────────────────────────────────────────
// Layout simple: dividimos el área en filas, cada fila proporcional a un grupo
// de blocks. Para V1 usamos un algoritmo greedy: tomamos los más grandes en una
// fila hasta que el aspect ratio se vuelve mejor en una nueva.
//
// Compresión de pesos: usamos sqrt(market_cap) para que cripto y Merval
// (donde 1-2 nombres dominan) no aplaste el resto en celdas invisibles.
// Con market_cap raw, BTC vs AVAX es ratio ~120:1; con sqrt queda ~11:1.

function weightOf(b) {
  return Math.sqrt(Math.max(b.market_cap, 1))
}

function squarify(blocks, width, height) {
  const total = blocks.reduce((s, b) => s + weightOf(b), 0)
  if (total === 0) return []
  const totalArea = width * height
  const items = blocks.map(b => ({
    ...b,
    area: (weightOf(b) / total) * totalArea,
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
    <div className="inline-flex gap-0.5 bg-bg-1 border border-line rounded-sm p-0.5">
      {MARKETS.map(m => (
        <button
          key={m.key}
          onClick={() => setMarket(m.key)}
          className={`px-2 py-1 text-[11px] rounded-sm transition-colors font-mono uppercase tracking-caps ${
            market === m.key
              ? 'bg-bg-2 text-ink-0 font-medium'
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
        <div className="text-[10px] uppercase tracking-label text-ink-3 font-mono font-medium">
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
          {laid.map(b => {
            // Texto si la celda es razonable. Para celdas muy chicas mostramos
            // solo el ticker truncado en una sola línea, sin %.
            const isLargeEnough = b.w > 38 && b.h > 22
            const isMediumPlus  = b.w > 60 && b.h > 36
            const showPct       = b.w > 50 && b.h > 42
            const displaySymbol = b.w < 55 ? shortSymbol(b.symbol) : b.symbol
            // FontSize: escalado por dimensión menor para que entre siempre.
            const baseSize = Math.min(b.w / Math.max(displaySymbol.length, 4) * 1.4, b.h / 2.4)
            const symFontSize = Math.max(9, Math.min(baseSize, 22))
            const pctFontSize = Math.max(8, Math.min(symFontSize * 0.62, 12))
            const yOffset = showPct ? -symFontSize * 0.25 : 0
            return (
              <g
                key={b.symbol}
                onClick={() => setSelected({ ...b, symbol: cleanSymbol(b.symbol) })}
                style={{ cursor: 'pointer' }}
              >
                <rect
                  x={b.x} y={b.y} width={b.w} height={b.h}
                  fill={colorForChange(b.change_pct)}
                  stroke="#07090C"
                  strokeWidth="1"
                />
                {isLargeEnough && (
                  <text
                    x={b.x + b.w / 2}
                    y={b.y + b.h / 2 + yOffset + symFontSize * 0.35}
                    textAnchor="middle"
                    fill="white"
                    fontSize={symFontSize}
                    fontWeight="600"
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {displaySymbol}
                  </text>
                )}
                {isMediumPlus && showPct && (
                  <text
                    x={b.x + b.w / 2}
                    y={b.y + b.h / 2 + symFontSize * 0.85}
                    textAnchor="middle"
                    fill="rgba(255,255,255,0.85)"
                    fontSize={pctFontSize}
                    fontFamily="monospace"
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {fmtPct(b.change_pct)}
                  </text>
                )}
              </g>
            )
          })}
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
