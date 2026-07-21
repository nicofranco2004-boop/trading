// AIBlocks — renderizadores de los bloques visuales de las respuestas de
// Rendi AI (catálogo V1: compare / alloc / scenario / table / actions).
// ═══════════════════════════════════════════════════════════════════════════
// El modelo elige el bloque y manda SOLO datos ({type, ...}) — acá vive el
// componente de cada tipo. La sanitización (caps, tonos, whitelist de rutas)
// ya ocurrió en utils/aiStructured.js: esto confía en ese shape.
// Tipo desconocido no llega (el parser lo descarta) — forward-compatible.

import { useNavigate } from 'react-router-dom'

// Paleta para la barra de composición (por índice; el último cae en gris).
const ALLOC_COLORS = ['#7c6df0', '#4bd0e8', '#2ad17f', '#f5b752', '#ff6472', '#5f6a7e']

const TONE_TEXT = {
  pos: 'text-rendi-pos', warn: 'text-rendi-warn', neg: 'text-rendi-neg', neutral: 'text-ink-0',
}

export default function AIBlocks({ blocks }) {
  if (!blocks?.length) return null
  return (
    <div className="space-y-3 mt-3">
      {blocks.map((b, i) => {
        switch (b.type) {
          case 'compare':  return <CompareBlock key={i} {...b} />
          case 'alloc':    return <AllocBlock key={i} {...b} />
          case 'scenario': return <ScenarioBlock key={i} {...b} />
          case 'table':    return <TableBlock key={i} {...b} />
          case 'actions':  return <ActionsBlock key={i} {...b} />
          default:         return null
        }
      })}
    </div>
  )
}

// ── 01 · Comparación en barras ──────────────────────────────────────────────
// pct opcional (0-100). Si falta, se deriva del número parseado de `v`
// normalizado contra el máximo (best-effort — el modelo debería mandarlo).
function CompareBlock({ items }) {
  const parsed = items.map(it => ({ ...it, n: it.pct ?? (Math.abs(parseFloat(String(it.v).replace(',', '.').replace(/[^\d.,-]/g, ''))) || 0) }))
  const max = Math.max(...parsed.map(p => p.n), 1)
  return (
    <div className="space-y-2">
      {parsed.map((it, i) => (
        <div key={i} className="grid items-center gap-3" style={{ gridTemplateColumns: '104px 1fr 72px' }}>
          <span className="text-[12.5px] text-ink-2 truncate">{it.l}</span>
          <div className="h-2.5 rounded-md bg-bg-1 border border-line/40 overflow-hidden">
            <div
              className="h-full rounded-md"
              style={{
                width: `${Math.max(4, Math.min(100, (it.n / max) * 100))}%`,
                background: i === 0 ? '#9d8cff' : '#5f6a7e',
                opacity: i === 0 ? 1 : 0.75,
              }}
            />
          </div>
          <span className={`text-[13px] font-semibold num tabular text-right ${i === 0 ? 'text-data-violet' : 'text-ink-2'}`}>{it.v}</span>
        </div>
      ))}
    </div>
  )
}

// ── 02 · Composición (barra apilada) ────────────────────────────────────────
function AllocBlock({ items }) {
  const total = items.reduce((s, it) => s + it.pct, 0) || 1
  return (
    <div>
      <div className="flex h-6 rounded-lg overflow-hidden border border-line/40">
        {items.map((it, i) => {
          const w = (it.pct / total) * 100
          return (
            <div key={i} className="grid place-items-center text-[10px] font-bold text-white/90 min-w-0"
              style={{ width: `${w}%`, background: ALLOC_COLORS[Math.min(i, ALLOC_COLORS.length - 1)] }}>
              {w >= 12 ? `${it.l} ${Math.round(it.pct)}%` : ''}
            </div>
          )
        })}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[12px] text-ink-2">
        {items.map((it, i) => (
          <span key={i} className="inline-flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm inline-block" style={{ background: ALLOC_COLORS[Math.min(i, ALLOC_COLORS.length - 1)] }} />
            {it.l} <span className="num tabular text-ink-3">{Math.round(it.pct)}%</span>
          </span>
        ))}
      </div>
    </div>
  )
}

// ── 03 · Escenario si→entonces ──────────────────────────────────────────────
function ScenarioBlock({ if: ifTxt, then, tone }) {
  const thenBg = tone === 'pos' ? 'bg-rendi-pos/10' : tone === 'warn' ? 'bg-rendi-warn/10' : tone === 'neg' ? 'bg-rendi-neg/10' : 'bg-bg-2'
  return (
    <div className="flex items-stretch border border-line rounded-xl overflow-hidden">
      <div className="flex-1 bg-bg-1 px-4 py-3">
        <div className="text-[10.5px] text-ink-3 font-semibold mb-0.5">SI</div>
        <div className="text-[14px] font-semibold text-ink-0">{ifTxt}</div>
      </div>
      <div className="grid place-items-center px-1 text-ink-3" aria-hidden>→</div>
      <div className={`flex-1 px-4 py-3 ${thenBg}`}>
        <div className="text-[10.5px] text-ink-3 font-semibold mb-0.5">TU CARTERA</div>
        <div className={`text-[14px] font-semibold num tabular ${TONE_TEXT[tone] || TONE_TEXT.neutral}`}>{then}</div>
      </div>
    </div>
  )
}

// ── 05 · Mini-tabla (ranking) ───────────────────────────────────────────────
function TableBlock({ cols, rows }) {
  return (
    <div className="border border-line rounded-xl overflow-hidden">
      <table className="w-full text-[13px] border-collapse">
        <thead>
          <tr className="bg-bg-1">
            {cols.map((c, i) => (
              <th key={i} className={`px-3 py-2 text-[11.5px] text-ink-3 font-semibold ${i === 0 ? 'text-left' : 'text-right'}`}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={i > 0 ? 'border-t border-line/40' : 'border-t border-line/40'}>
              {r.map((cell, j) => {
                const s = String(cell)
                const toneCls = s.trim().startsWith('+') ? 'text-rendi-pos' : s.trim().startsWith('−') || s.trim().startsWith('-') ? 'text-rendi-neg' : 'text-ink-1'
                return (
                  <td key={j} className={`px-3 py-2 ${j === 0 ? 'text-left font-medium text-ink-0' : `text-right num tabular ${toneCls}`}`}>{s}</td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── 06 · Acciones (deep-links internos, ya whitelisted por el parser) ───────
function ActionsBlock({ items }) {
  const navigate = useNavigate()
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((it, i) => (
        <button key={i} type="button" onClick={() => navigate(it.to)}
          className={i === 0
            ? 'inline-flex items-center gap-1.5 text-[13px] font-semibold text-data-violet bg-data-violet/10 border border-data-violet/30 hover:bg-data-violet/20 rounded-xl px-3.5 py-2 transition-colors'
            : 'inline-flex items-center gap-1.5 text-[13px] font-medium text-ink-1 bg-bg-1 border border-line hover:border-ink-3 rounded-xl px-3.5 py-2 transition-colors'}>
          {it.label} <span aria-hidden>→</span>
        </button>
      ))}
    </div>
  )
}
