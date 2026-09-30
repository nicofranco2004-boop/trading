// Heatmap — bloques tipo Finviz para el S&P 500.
//
// Layout: squarified treemap simplificado (sin lib externa). Cada bloque:
//   - size proporcional al market_cap
//   - color por change_pct (escala verde/rojo)
//   - click → abre AssetQuickView (modal mini-ficha)
//   - con el mouse encima: borde resaltado + globo con nombre, precio y
//     variación (en el celular el toque ya abre la ficha, no hay "encima")
//   - al entrar en pantalla los cuadros aparecen en ola, de arriba a la
//     izquierda hacia abajo a la derecha (`.celda-entra`, index.css)
//
// V1: solo S&P 500 (50 nombres). V1.5 agrega Merval + cripto.
// V2: real-time prices con polling 60s.

import { useEffect, useState } from 'react'
import { useAlVerse } from '../../hooks/useAlVerse'
import { api } from '../../utils/api'
import { pctVar, pctVarSign, nfmt } from '../../utils/format'
import { polarityColor, CORTES_DIA } from '../../utils/polarityScale'
import AssetQuickView from './AssetQuickView'

// Los colores salen de la rampa única (utils/polarityScale.js), que conoce los
// dos temas. Acá vivían dos arrays de 9 hex y una función propia — construidos
// para fondo oscuro, donde "intenso" es BRILLANTE. Sobre blanco esa escala se
// leía al revés: 0,4 % se pintaba casi negro y +1 % se pintaba pálido.
//
// De los 9 pasos que declaraba, la función usaba 3 (los índices 3, 4 y 5): los
// seis restantes eran inalcanzables. La rampa nueva tiene esos 3 y nada más.
//
// Los cortes son los del DÍA (0,5 % y 1 %) porque esto mide una rueda.

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

// El globo del cuadro con el mouse encima: ticker, nombre, precio y variación
// del día. Posición en % del mapa (el SVG se estira con preserveAspectRatio
// "none", así que el globo va en HTML encima y no se deforma). Arriba del
// cuadro; si el cuadro está pegado al borde de arriba, abajo.
// De costado: centrado sobre el cuadro, salvo cerca de un borde del mapa, donde
// se alinea con el borde del cuadro — así no se sale del mapa sea cual sea su
// ancho (un tope fijo en % sólo alcanzaba con el mapa ancho).
export function GloboCelda({ b, market }) {
  if (!b) return null
  const cx = ((b.x + b.w / 2) / WIDTH) * 100
  const [left, dx] = cx < 25 ? [(b.x / WIDTH) * 100, '0%']
    : cx > 75 ? [((b.x + b.w) / WIDTH) * 100, '-100%']
    : [cx, '-50%']
  const arriba = b.y / HEIGHT > 0.18
  const top = ((arriba ? b.y : b.y + b.h) / HEIGHT) * 100
  const dir = pctVarSign(b.change_pct)
  const moneda = market === 'merval' ? '$' : 'US$'
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-lg border border-line-2 bg-bg-raised px-2.5 py-1.5 text-[12px] whitespace-nowrap shadow-lg"
      style={{
        left: `${left}%`,
        top: `${top}%`,
        transform: `translate(${dx}, ${arriba ? 'calc(-100% - 6px)' : '6px'})`,
      }}
    >
      <div className="flex items-baseline gap-1.5">
        <span className="font-semibold text-ink-0">{cleanSymbol(b.symbol)}</span>
        {b.name && <span className="text-ink-3 max-w-[140px] truncate">{b.name}</span>}
      </div>
      <div className="flex items-baseline gap-2 tabular">
        {b.price != null && <span className="text-ink-1">{moneda} {nfmt(b.price, b.price >= 1000 ? 0 : 2)}</span>}
        <span className={`font-semibold ${dir > 0 ? 'text-rendi-pos' : dir < 0 ? 'text-rendi-neg' : 'text-ink-2'}`}>{pctVar(b.change_pct)}</span>
      </div>
    </div>
  )
}

export default function Heatmap({ defaultMarket = "sp500" }) {
  const [market, setMarket] = useState(defaultMarket)
  const [blocks, setBlocks] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [selected, setSelected] = useState(null)
  const [encima, setEncima] = useState(null)   // símbolo con el mouse encima
  const [refMapa, mapaVisto] = useAlVerse()

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
          className={`px-3 py-1.5 text-[12.5px] rounded-md transition-colors font-medium ${
            market === m.key
              ? 'bg-bg-2 text-ink-0'
              : 'text-ink-2 hover:text-ink-0'
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  )

  const laid = loading || err || blocks.length === 0 ? [] : squarify(blocks, WIDTH, HEIGHT)
  // El cuadro con el mouse encima: su borde va arriba de todos y lleva el globo.
  const resaltado = encima ? laid.find(x => x.symbol === encima) : null

  return (
    <>
      <div className="flex items-center justify-between mb-2">
        <div className="text-[13px] text-ink-2 font-medium">
          {MARKETS.find(m => m.key === market)?.label || market} · {blocks.length} activos
        </div>
        {Tabs}
      </div>
      {loading && (
        <div className="rounded-sm bg-bg-2 esqueleto" style={{ aspectRatio: `${WIDTH}/${HEIGHT}` }} />
      )}
      {err && !loading && (
        <div className="text-xs text-rendi-neg p-4">Heatmap no disponible: {err}</div>
      )}
      {!loading && !err && blocks.length === 0 && (
        <div className="text-xs text-ink-3 p-4">Sin data del heatmap por ahora.</div>
      )}
      {!loading && !err && blocks.length > 0 && (
      <div
        ref={refMapa}
        className="relative rounded-sm border border-line"
        style={{ width: "100%", aspectRatio: `${WIDTH}/${HEIGHT}` }}
        onPointerLeave={() => setEncima(null)}
      >
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          preserveAspectRatio="none"
          className="absolute inset-0 w-full h-full rounded-sm overflow-hidden"
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
            // El fondo y su tinta salen juntos: el fondo cambia de luminancia
            // entre temas, así que el texto de encima también. Antes el texto
            // era `white` fijo — sobre una celda clara no se veía.
            const celda = polarityColor(b.change_pct, CORTES_DIA)
            return (
              <g
                key={b.symbol}
                onClick={() => setSelected({ ...b, symbol: cleanSymbol(b.symbol) })}
                onPointerEnter={e => { if (e.pointerType === 'mouse') setEncima(b.symbol) }}
                className={mapaVisto ? 'celda-entra' : 'celda-antes'}
                // La ola: cada cuadro arranca según qué tan lejos está de la
                // esquina de arriba a la izquierda.
                style={{ cursor: 'pointer', '--d': `${Math.round(((b.x + b.w / 2) / WIDTH + (b.y + b.h / 2) / HEIGHT) * 350)}ms` }}
              >
                <rect
                  x={b.x} y={b.y} width={b.w} height={b.h}
                  fill={celda.bg}
                  stroke="rgb(var(--bg-0))"
                  strokeWidth="1"
                />
                {isLargeEnough && (
                  <text
                    x={b.x + b.w / 2}
                    y={b.y + b.h / 2 + yOffset + symFontSize * 0.35}
                    textAnchor="middle"
                    fill={celda.ink}
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
                    fill={celda.ink}
                    fillOpacity="0.85"
                    fontSize={pctFontSize}
                    fontFamily="monospace"
                    style={{ pointerEvents: 'none', userSelect: 'none' }}
                  >
                    {pctVar(b.change_pct, 1)}
                  </text>
                )}
              </g>
            )
          })}
          {/* El borde del cuadro con el mouse encima va al FINAL, arriba de
              todos: dibujado en su lugar, los vecinos le tapaban medio borde. */}
          {resaltado && (
            <rect
              x={resaltado.x + 1} y={resaltado.y + 1}
              width={Math.max(0, resaltado.w - 2)} height={Math.max(0, resaltado.h - 2)}
              fill="none" stroke="rgb(var(--ink-0))" strokeWidth="2"
              vectorEffect="non-scaling-stroke" pointerEvents="none"
            />
          )}
        </svg>
        <GloboCelda b={resaltado} market={market} />
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
