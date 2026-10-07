// AIBlocks — renderizadores de los bloques visuales de las respuestas de
// Mervall-E AI (catálogo V1: compare / alloc / scenario / table / actions).
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

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bell, LineChart, Briefcase, List, Gauge, Newspaper, TrendingUp, Upload,
  Sparkles, ChevronRight, PencilLine, Check, Loader2, Users, LayoutDashboard,
} from 'lucide-react'
import { useAdvisorContext } from '../../contexts/AdvisorContext'
import { parseNum } from '../../utils/format'
import { porcionColor, PORCION_RESTO } from '../../utils/chartTheme'
import { entrada } from '../../hooks/useAlVerse'

// Composición: la rampa violeta de utils/chartTheme (porcionColor), la misma
// de toda torta o barra de composición de la app. Hasta 2026-09-29 usaba la
// paleta de series: Bitcoin salía con el verde de ganancia e YPF con el rojo
// de pérdida — se leía "este va bien, este va mal".

const TONE_TEXT = {
  pos: 'text-rendi-pos', warn: 'text-rendi-warn', neg: 'text-rendi-neg', neutral: 'text-ink-0',
}

// onSendMessage(text): manda un mensaje al chat como si el usuario lo tipeara
// (submit del form de registro / botón Confirmar). interactive: solo el ÚLTIMO
// mensaje del hilo tiene controles vivos — forms de turnos viejos se congelan.
// animarDesde: null = quieto (una respuesta vieja, o una conversación que se
// vuelve a abrir). Un número = la respuesta ACABA de llegar (esRecienLlegada,
// VozContext): cada bloque entra en escalera empezando en ese turno (lo que va
// antes —veredicto y cifras— ya usó los primeros), y adentro las barras
// crecen y la torta de "Composición" aparece por porciones.
export default function AIBlocks({ blocks, onSendMessage = null, interactive = false, animarDesde = null }) {
  if (!blocks?.length) return null
  const animar = animarDesde != null
  return (
    <div className="space-y-3 mt-3">
      {blocks.map((b, i) => {
        let bloque
        switch (b.type) {
          case 'compare':  bloque = <CompareBlock {...b} animar={animar} />; break
          case 'alloc':    bloque = <AllocBlock {...b} animar={animar} />; break
          case 'scenario': bloque = <ScenarioBlock {...b} />; break
          case 'table':    bloque = <TableBlock {...b} />; break
          case 'actions':  bloque = <ActionsBlock {...b} />; break
          case 'form':     bloque = <FormBlock {...b} onSendMessage={onSendMessage} interactive={interactive} />; break
          case 'confirm':  bloque = <ConfirmBlock {...b} onSendMessage={onSendMessage} interactive={interactive} />; break
          case 'client_list': bloque = <ClientListBlock {...b} animar={animar} />; break
          default:         return null
        }
        return <div key={i} {...(animar ? entrada(true, animarDesde + i) : {})}>{bloque}</div>
      })}
    </div>
  )
}

// La barra de un bloque de barras ("Comparación" y "Tus clientes"): el mismo
// dibujo en los dos, antes copiado. La primera fila va con el color propio del
// bloque; las demás en gris. Con `animar` crece desde la izquierda
// (.crece-ancho), una detrás de otra: la transición de ancho que tenía nunca
// se veía, porque la barra nacía ya con su ancho final.
function BarraDeBloque({ n, max, i, colorPrimera, animar }) {
  return (
    <div className="h-[20px] rounded-lg bg-bg-2 overflow-hidden">
      <div
        className={`h-full rounded-lg transition-[width] duration-500 ${animar ? 'crece-ancho' : ''}`}
        style={{
          '--fila': i,   // --i lo hereda del bloque (su turno de entrada)
          width: `${Math.max(5, Math.min(100, (n / max) * 100))}%`,
          background: i === 0 ? colorPrimera : 'rgb(var(--ink-3))',
          opacity: i === 0 ? 1 : 0.55,
        }}
      />
    </div>
  )
}

// Fallback de la barra cuando el modelo no manda pct: parsear el VALOR
// formateado. Formato es-AR: puntos = miles ("US$ 1.500.000"), coma =
// decimal — el parseFloat ingenuo leía 1.5 y el ranking salía INVERTIDO
// (audit). Reglas: hay coma → puntos son miles; solo puntos en grupos de
// 3 → miles; si no, decimal normal.
function parseMoneyish(v) {
  const n = parseNum(v)
  return Number.isFinite(n) ? Math.abs(n) : 0
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
function CompareBlock({ items, title, animar = false }) {
  const parsed = items.map(it => ({ ...it, n: it.pct ?? parseMoneyish(it.v) }))
  const max = Math.max(...parsed.map(p => p.n), 1)
  return (
    <BlockCard title={title || 'Comparación'}>
      <div className="space-y-2.5">
        {parsed.map((it, i) => (
          <div key={i} className="grid items-center gap-3" style={{ gridTemplateColumns: '104px 1fr 74px' }}>
            <span className={`text-[12.5px] truncate font-medium ${i === 0 ? 'text-ink-0' : 'text-ink-2'}`}>{it.l}</span>
            <BarraDeBloque n={it.n} max={max} i={i} animar={animar}
              colorPrimera="linear-gradient(90deg, rgb(var(--data-violet)), rgb(var(--data-cyan)))" />
            <span className={`text-[13px] font-bold num tabular text-right ${i === 0 ? 'text-data-violet' : 'text-ink-2'}`}>{it.v}</span>
          </div>
        ))}
      </div>
    </BlockCard>
  )
}

// ── 02 · Composición (donut + leyenda) ──────────────────────────────────────
// r=15.9155 → circunferencia 100: los dasharray mapean 1:1 con los %.
// "Otros"/"Resto" lo manda el modelo como una porción más, y puede ser la
// MAYOR: en el demo salía primero, con el violeta más fuerte y de titular del
// centro ("53% Otros"). Lo que sobra va al final y en gris, como en el
// Dashboard y el libro del asesor; el centro lo lleva el activo más grande.
const ES_RESTO = /^(otros|otras|resto|el resto|los dem[aá]s|dem[aá]s)\b/i

function AllocBlock({ items, title, animar = false }) {
  const total = items.reduce((s, it) => s + it.pct, 0) || 1
  const porPeso = (a, b) => b.pct - a.pct
  const reales = items.filter(it => !ES_RESTO.test(String(it.l).trim())).sort(porPeso)
  const resto = items.filter(it => ES_RESTO.test(String(it.l).trim())).sort(porPeso)
  const segs = []
  let acc = 0
  ;[...reales, ...resto].forEach((it, i) => {
    const w = (it.pct / total) * 100
    const color = i < reales.length ? porcionColor(i) : PORCION_RESTO
    segs.push({ ...it, w, offset: 25 - acc, color })
    acc += w
  })
  const top = segs[0]
  return (
    <BlockCard title={title || 'Composición'}>
      <div className="flex items-center gap-5 flex-wrap">
        <svg viewBox="0 0 42 42" className="w-[110px] h-[110px] flex-none" aria-hidden="true">
          <circle cx="21" cy="21" r="15.9155" fill="none" stroke="currentColor" className="text-bg-2" strokeWidth="6" />
          {segs.map((s, i) => (
            <circle key={i} cx="21" cy="21" r="15.9155" fill="none" stroke={s.color} strokeWidth="6"
              strokeDasharray={`${s.w} ${100 - s.w}`} strokeDashoffset={s.offset}
              className={animar ? 'porcion-aparece' : undefined} style={animar ? { '--fila': i } : undefined} />
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
  // En el celular, uno arriba del otro: lado a lado, el resultado ("Tu
  // cartera cae ~13% (unos US$ 1.480)") quedaba en una columna de ~130px y
  // se partía en cuatro renglones. Desde sm, lado a lado como siempre.
  return (
    <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto_1fr] items-stretch gap-1.5 sm:gap-2.5">
      <div className="bg-bg-1 border border-line rounded-xl px-4 py-3">
        <div className="text-[10.5px] text-ink-3 font-bold tracking-[0.08em] mb-1">ESCENARIO</div>
        <div className="text-[13.5px] font-semibold text-ink-0 leading-snug">{ifTxt}</div>
      </div>
      <div className="grid place-items-center text-ink-3 text-[15px] sm:text-[17px]" aria-hidden>
        <span className="sm:hidden">↓</span><span className="hidden sm:inline">→</span>
      </div>
      <div className={`border rounded-xl px-4 py-3 ${resBg}`}>
        <div className="text-[10.5px] text-ink-3 font-bold tracking-[0.08em] mb-1">TU CARTERA</div>
        <div className={`text-[16px] sm:text-[17px] font-bold num tabular leading-snug ${TONE_TEXT[tone] || TONE_TEXT.neutral}`}>{then}</div>
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

// ── 07 · Ranking de clientes (book-mode del Plan Asesor) ───────────────────
// Una barra por cliente, ordenadas — el bloque estrella del asesor (mockup
// aprobado por Nico). "Entrar" setea el contexto de cliente y navega a SU
// dashboard, igual que la card del roster. Solo si el item trae `id` (y un
// id inventado no filtra nada: el resolver valida el vínculo en cada request).
function ClientListBlock({ items, title, animar = false }) {
  const navigate = useNavigate()
  const { enterClient } = useAdvisorContext()
  const parsed = items.map(it => ({ ...it, n: it.pct ?? parseMoneyish(it.v) }))
  const max = Math.max(...parsed.map(p => p.n), 1)
  const enter = (it) => {
    enterClient({ id: it.id, label: it.l })
    navigate('/dashboard')
  }
  return (
    <BlockCard title={title || 'Tus clientes'}>
      <div className="space-y-2.5">
        {parsed.map((it, i) => (
          <div key={i} className="grid items-center gap-3" style={{ gridTemplateColumns: '92px 1fr auto' }}>
            <span className={`text-[12.5px] truncate font-medium ${i === 0 ? 'text-ink-0' : 'text-ink-2'}`}>{it.l}</span>
            <BarraDeBloque n={it.n} max={max} i={i} animar={animar}
              colorPrimera="linear-gradient(90deg, rgb(var(--rendi-violet-hover)), rgb(var(--data-violet)))" />
            <div className="flex items-center gap-2.5 justify-end">
              <span className="text-right num tabular">
                <span className={`block text-[13px] font-bold ${i === 0 ? 'text-data-violet' : 'text-ink-1'}`}>{it.v}</span>
                {it.sub && <span className="block text-[10.5px] text-ink-3">{it.sub}</span>}
              </span>
              {it.id != null && (
                <button
                  type="button"
                  onClick={() => enter(it)}
                  className="text-[11px] font-semibold text-data-violet border border-data-violet/30 hover:bg-data-violet/10 rounded-md px-2 py-1 transition-colors whitespace-nowrap"
                >
                  Entrar →
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </BlockCard>
  )
}

// ── 06 · Acciones (deep-links internos, ya whitelisted por el parser) ───────
const ROUTE_ICONS = [
  ['/alertas', Bell], ['/analisis', LineChart], ['/posiciones', Briefcase],
  ['/operaciones', List], ['/fundamentals', Gauge], ['/novedades', Newspaper],
  ['/activo/', TrendingUp], ['/imports', Upload],
  ['/clientes', Users], ['/dashboard', LayoutDashboard],
]
function iconForRoute(to) {
  const hit = ROUTE_ICONS.find(([p]) => to.startsWith(p))
  return hit ? hit[1] : Sparkles
}

// Sin card ni título: son atajos, no un gráfico. Con card + título + botones
// grandes ocupaban media pantalla del celular, y encima venían las
// repreguntas debajo — seis botones por respuesta. Ahora es una fila de
// pastillas con ícono (el ícono dice "te lleva a otra pantalla"; las
// repreguntas de abajo, sin ícono, "le pregunto a Rendi").
function ActionsBlock({ items }) {
  const navigate = useNavigate()
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((it, i) => {
        const Icon = iconForRoute(it.to)
        return (
          <button key={i} type="button" onClick={() => navigate(it.to)}
            className="group inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-ink-0 bg-bg-1 border border-line hover:border-data-violet/40 hover:bg-data-violet/[0.06] rounded-full pl-2 pr-2.5 py-1.5 transition-colors">
            <Icon size={13} strokeWidth={1.75} className="text-data-violet flex-none" aria-hidden="true" />
            {it.label}
            <ChevronRight size={12} strokeWidth={2} className="text-ink-3 group-hover:text-data-violet transition-colors" aria-hidden="true" />
          </button>
        )
      })}
    </div>
  )
}

// ── 07 · Formulario de registro (datos faltantes) ───────────────────────────
// Lo emite el SERVER desde el draft del registro por chat (determinístico).
// Submit → onSendMessage("broker: Cocos · precio: 18650") → el pipeline de
// registro existente completa el draft. Cubre compra/venta/depósito/retiro/
// transferencia/conversión — el server decide los campos.
function FormBlock({ title, subtitle, fields, submitLabel, onSendMessage, interactive }) {
  const [vals, setVals] = useState(() => Object.fromEntries(
    fields.map(f => [f.k, f.value ?? (f.kind === 'select' && f.options?.length === 1 ? f.options[0] : '')])
  ))
  const [sent, setSent] = useState(false)
  const live = interactive && !sent && typeof onSendMessage === 'function'
  const complete = fields.every(f => String(vals[f.k] ?? '').trim() !== '')
  const submit = () => {
    if (!live || !complete) return
    setSent(true)
    onSendMessage(fields.map(f => `${f.k}: ${String(vals[f.k]).trim()}`).join(' · '))
  }
  return (
    <BlockCard title={title || 'Completá el registro'}>
      {subtitle && <p className="text-[11.5px] text-ink-3 -mt-2 mb-3">{subtitle}</p>}
      <div className="space-y-3">
        {fields.map(f => (
          <div key={f.k}>
            <label className="block text-[11px] font-semibold text-ink-2 mb-1.5">{f.label}</label>
            {f.kind === 'select' && f.options?.length ? (
              <div className="flex gap-2 flex-wrap">
                {f.options.map(opt => (
                  <button key={opt} type="button" disabled={!live}
                    onClick={() => setVals(v => ({ ...v, [f.k]: opt }))}
                    className={`text-[12.5px] font-semibold rounded-xl px-3.5 py-2 border transition disabled:opacity-60 ${
                      vals[f.k] === opt
                        ? 'text-data-violet border-data-violet/40 bg-data-violet/10'
                        : 'text-ink-1 border-line bg-bg-2 hover:border-ink-3'}`}>
                    {opt}
                  </button>
                ))}
              </div>
            ) : (
              <div className="flex items-center gap-2 bg-bg-2 border border-line rounded-xl px-3 py-2 max-w-[260px] focus-within:border-data-violet/50">
                <input
                  type={f.kind === 'number' ? 'number' : f.kind === 'date' ? 'date' : 'text'}
                  inputMode={f.kind === 'number' ? 'decimal' : undefined}
                  step={f.kind === 'number' ? 'any' : undefined}
                  value={vals[f.k]}
                  disabled={!live}
                  onChange={e => setVals(v => ({ ...v, [f.k]: e.target.value }))}
                  onKeyDown={e => { if (e.key === 'Enter') submit() }}
                  className="bg-transparent outline-none border-none text-[13.5px] text-ink-0 w-full num tabular disabled:opacity-60"
                  placeholder="0"
                />
                {f.unit && <span className="text-[10.5px] text-ink-3 flex-none">{f.unit}</span>}
              </div>
            )}
            {f.hint && <p className="text-[10.5px] text-data-cyan mt-1">{f.hint}</p>}
          </div>
        ))}
      </div>
      <button type="button" onClick={submit} disabled={!live || !complete}
        className="mt-4 w-full max-w-[260px] inline-flex items-center justify-center gap-2 text-[13px] font-bold text-white bg-data-violet hover:bg-data-violet/90 rounded-xl px-4 py-2.5 transition disabled:opacity-40 disabled:cursor-not-allowed">
        {sent ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <PencilLine size={13} aria-hidden />}
        {sent ? 'Enviando…' : (submitLabel || 'Enviar')}
      </button>
    </BlockCard>
  )
}

// ── 08 · Confirmación del registro con botones ──────────────────────────────
// "Confirmar" manda el sí por el usuario; "Corregir" enfoca el input del chat
// (evento global — sin prop-drilling) para tipear el ajuste.
function ConfirmBlock({ title, rows, yes, no, onSendMessage, interactive }) {
  const [sent, setSent] = useState(false)
  const live = interactive && !sent && typeof onSendMessage === 'function'
  return (
    <BlockCard title={title || 'Confirmá el registro'}>
      <div className="space-y-1 mb-3.5">
        {rows.map(([k, v], i) => (
          <div key={i} className="flex justify-between gap-3 text-[12.5px]">
            <span className="text-ink-3">{k}</span>
            <span className="font-semibold text-ink-0 num tabular text-right">{v}</span>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <button type="button" disabled={!live}
          onClick={() => { if (!live) return; setSent(true); onSendMessage('sí, confirmá') }}
          className="flex-1 max-w-[240px] inline-flex items-center justify-center gap-1.5 text-[13px] font-bold rounded-xl px-4 py-2.5 bg-rendi-pos text-[rgb(var(--pol-up-3-ink))] hover:opacity-90 transition disabled:opacity-40 disabled:cursor-not-allowed">
          {sent ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <Check size={13} strokeWidth={2.5} aria-hidden />}
          {sent ? 'Registrando…' : (yes || 'Confirmar')}
        </button>
        <button type="button" disabled={!live}
          onClick={() => window.dispatchEvent(new Event('rendi:chat-focus'))}
          className="text-[12.5px] font-medium text-ink-1 border border-line hover:border-ink-3 rounded-xl px-3.5 py-2.5 transition disabled:opacity-40">
          {no || 'Corregir'}
        </button>
      </div>
    </BlockCard>
  )
}
