// AIBlocks — renderizadores de los bloques visuales de las respuestas de
// Rendi AI (catálogo V1: compare / alloc / scenario / table / actions).
// ═══════════════════════════════════════════════════════════════════════════
// El modelo elige el bloque y manda SOLO datos ({type, ...}) — acá vive el
// componente de cada tipo. La sanitización (caps, tonos, whitelist de rutas)
// ya ocurrió en utils/aiStructured.js: esto confía en ese shape.
// Tipo desconocido no llega (el parser lo descarta) — forward-compatible.
//
// v2 (mockup ai-blocks-v2 aprobado por Nico): mismas plantillas, render más
// rico — títulos de card, compare con gradiente, alloc pasa de barra a DONUT,
// scenario con resultado tintado grande, tabla con zebra + pills, actions con
// ícono por ruta. Todo client-side: cero tokens extra por respuesta.

import { useNavigate } from 'react-router-dom'
import {
  Bell, LineChart, Briefcase, List, Gauge, Newspaper, TrendingUp, Upload,
  Sparkles, ChevronRight,
} from 'lucide-react'

// Paleta de composición (por índice; el último cae en gris).
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

// Card contenedora con mini-título uppercase + punto violeta. El título viene
// del modelo (opcional, sanitizado ≤40) o cae al genérico del tipo.
function BlockCard({ title, children }) {
  return (
    <div className="bg-bg-1 border border-line rounded-2xl px-4 py-3.5">
      {title && (
        <p className="flex items-center gap-2 text-[11px] font-bold tracking-[0.07em] uppercase text-ink-3 mb-3">
          <span className="w-1.5 h-1.5 rounded-full bg-data-violet inline-block" aria-hidden />
          {title}
        </p>
      )}
      {children}
    </div>
  )
}

// ── 01 · Comparación en barras ──────────────────────────────────────────────
// pct opcional (0-100). Si falta, se deriva del número parseado de `v`
// normalizado contra el máximo (best-effort — el modelo debería mandarlo).
// Primer item = el usuario → barra con gradiente violeta→cyan.
function CompareBlock({ items, title }) {
  const parsed = items.map(it => ({ ...it, n: it.pct ?? (Math.abs(parseFloat(String(it.v).replace(',', '.').replace(/[^\d.,-]/g, ''))) || 0) }))
  const max = Math.max(...parsed.map(p => p.n), 1)
  return (
    <BlockCard title={title || 'Comparación'}>
      <div className="space-y-2.5">
        {parsed.map((it, i) => (
          <div key={i} className="grid items-center gap-3" style={{ gridTemplateColumns: '104px 1fr 74px' }}>
            <span className={`text-[12.5px] truncate font-medium ${i === 0 ? 'text-ink-0' : 'text-ink-2'}`}>{it.l}</span>
            <div className="h-[20px] rounded-lg bg-bg-2 overflow-hidden">
              <div
                className="h-full rounded-lg transition-[width] duration-500"
                style={{
                  width: `${Math.max(5, Math.min(100, (it.n / max) * 100))}%`,
                  background: i === 0 ? 'linear-gradient(90deg, #9d8cff, #4bd0e8)' : '#5f6a7e',
                  opacity: i === 0 ? 1 : 0.55,
                }}
              />
            </div>
            <span className={`text-[13px] font-bold num tabular text-right ${i === 0 ? 'text-data-violet' : 'text-ink-2'}`}>{it.v}</span>
          </div>
        ))}
      </div>
    </BlockCard>
  )
}

// ── 02 · Composición (donut + leyenda) ──────────────────────────────────────
// r=15.9155 → circunferencia 100: los dasharray mapean 1:1 con los %.
function AllocBlock({ items, title }) {
  const total = items.reduce((s, it) => s + it.pct, 0) || 1
  const sorted = [...items].sort((a, b) => b.pct - a.pct)
  const segs = []
  let acc = 0
  for (let i = 0; i < sorted.length; i++) {
    const w = (sorted[i].pct / total) * 100
    segs.push({ ...sorted[i], w, offset: 25 - acc, color: ALLOC_COLORS[Math.min(i, ALLOC_COLORS.length - 1)] })
    acc += w
  }
  const top = segs[0]
  return (
    <BlockCard title={title || 'Composición'}>
      <div className="flex items-center gap-5 flex-wrap">
        <svg viewBox="0 0 42 42" className="w-[110px] h-[110px] flex-none" aria-hidden="true">
          <circle cx="21" cy="21" r="15.9155" fill="none" stroke="currentColor" className="text-bg-2" strokeWidth="6" />
          {segs.map((s, i) => (
            <circle key={i} cx="21" cy="21" r="15.9155" fill="none" stroke={s.color} strokeWidth="6"
              strokeDasharray={`${s.w} ${100 - s.w}`} strokeDashoffset={s.offset} />
          ))}
          <text x="21" y="20.2" textAnchor="middle" className="fill-ink-0" style={{ fontSize: 7, fontWeight: 700 }}>
            {Math.round(top.pct)}%
          </text>
          <text x="21" y="26.5" textAnchor="middle" className="fill-ink-3" style={{ fontSize: 3.4 }}>
            {String(top.l).slice(0, 12)}
          </text>
        </svg>
        <div className="grid gap-1.5 flex-1 min-w-[170px]">
          {segs.map((s, i) => (
            <div key={i} className="flex items-center gap-2.5 text-[12.5px]">
              <span className="w-2.5 h-2.5 rounded inline-block flex-none" style={{ background: s.color }} />
              <span className="font-semibold text-ink-0 truncate">{s.l}</span>
              <span className="ml-auto font-bold num tabular text-ink-1">{Math.round(s.pct)}%</span>
            </div>
          ))}
        </div>
      </div>
    </BlockCard>
  )
}

// ── 03 · Escenario si→entonces ──────────────────────────────────────────────
function ScenarioBlock({ if: ifTxt, then, tone }) {
  const resBg = tone === 'pos' ? 'bg-rendi-pos/[0.08] border-rendi-pos/30'
    : tone === 'warn' ? 'bg-rendi-warn/[0.08] border-rendi-warn/30'
    : tone === 'neg' ? 'bg-rendi-neg/[0.08] border-rendi-neg/30'
    : 'bg-bg-2 border-line'
  return (
    <div className="grid items-stretch gap-2.5" style={{ gridTemplateColumns: '1fr auto 1fr' }}>
      <div className="bg-bg-1 border border-line rounded-xl px-4 py-3">
        <div className="text-[10.5px] text-ink-3 font-bold tracking-[0.08em] mb-1">ESCENARIO</div>
        <div className="text-[13.5px] font-semibold text-ink-0 leading-snug">{ifTxt}</div>
      </div>
      <div className="grid place-items-center text-ink-3 text-[17px]" aria-hidden>→</div>
      <div className={`border rounded-xl px-4 py-3 ${resBg}`}>
        <div className="text-[10.5px] text-ink-3 font-bold tracking-[0.08em] mb-1">TU CARTERA</div>
        <div className={`text-[17px] font-bold num tabular leading-snug ${TONE_TEXT[tone] || TONE_TEXT.neutral}`}>{then}</div>
      </div>
    </div>
  )
}

// ── 05 · Mini-tabla (ranking) — zebra + pills en los % con signo ────────────
function TableBlock({ cols, rows, title }) {
  return (
    <BlockCard title={title}>
      <div className="overflow-x-auto -mx-1 px-1">
        <table className="w-full text-[12.5px] border-collapse">
          <thead>
            <tr>
              {cols.map((c, i) => (
                <th key={i} className={`px-2.5 pb-2 text-[10.5px] tracking-[0.07em] uppercase text-ink-3 font-bold ${i === 0 ? 'text-left' : 'text-right'}`}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={`border-t border-line/40 ${i % 2 === 1 ? 'bg-bg-2/40' : ''}`}>
                {r.map((cell, j) => <TableCell key={j} cell={cell} first={j === 0} />)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </BlockCard>
  )
}

function TableCell({ cell, first }) {
  const s = String(cell)
  const t = s.trim()
  const signed = t.startsWith('+') || t.startsWith('−') || t.startsWith('-')
  if (first) return <td className="px-2.5 py-2 text-left font-semibold text-ink-0">{s}</td>
  // % con signo → pill de color; monto con signo → texto de color; resto plano.
  if (signed && t.endsWith('%')) {
    const pos = t.startsWith('+')
    return (
      <td className="px-2.5 py-2 text-right">
        <span className={`inline-block text-[11px] font-bold rounded-full px-2 py-0.5 num tabular ${pos ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-rendi-neg/10 text-rendi-neg'}`}>{s}</span>
      </td>
    )
  }
  const toneCls = signed ? (t.startsWith('+') ? 'text-rendi-pos' : 'text-rendi-neg') : 'text-ink-1'
  return <td className={`px-2.5 py-2 text-right num tabular ${toneCls}`}>{s}</td>
}

// ── 06 · Acciones (deep-links internos, ya whitelisted por el parser) ───────
const ROUTE_ICONS = [
  ['/alertas', Bell], ['/analisis', LineChart], ['/posiciones', Briefcase],
  ['/operaciones', List], ['/fundamentals', Gauge], ['/novedades', Newspaper],
  ['/activo/', TrendingUp], ['/imports', Upload],
]
function iconForRoute(to) {
  const hit = ROUTE_ICONS.find(([p]) => to.startsWith(p))
  return hit ? hit[1] : Sparkles
}

function ActionsBlock({ items, title }) {
  const navigate = useNavigate()
  return (
    <BlockCard title={title || 'Siguientes pasos'}>
      <div className="flex flex-wrap gap-2">
        {items.map((it, i) => {
          const Icon = iconForRoute(it.to)
          return (
            <button key={i} type="button" onClick={() => navigate(it.to)}
              className="group inline-flex items-center gap-2.5 text-[13px] font-semibold text-ink-0 bg-bg-2 border border-data-violet/30 hover:bg-data-violet/10 hover:-translate-y-px rounded-xl px-3.5 py-2.5 transition-all">
              <span className="w-6 h-6 rounded-lg bg-data-violet/10 text-data-violet grid place-items-center flex-none">
                <Icon size={13} strokeWidth={1.75} aria-hidden="true" />
              </span>
              {it.label}
              <ChevronRight size={13} strokeWidth={2} className="text-ink-3 group-hover:text-data-violet transition-colors" aria-hidden="true" />
            </button>
          )
        })}
      </div>
    </BlockCard>
  )
}
