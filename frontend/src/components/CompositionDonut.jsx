// CompositionDonut — torta de distribución de cartera, reusable.
// ═══════════════════════════════════════════════════════════════════════════
// Un solo componente para las dos tortas (por tipo de activo y por sector) en
// las dos superficies (Dashboard y Análisis). Es genérico sobre los items: no
// sabe qué está agregando, solo cómo dibujarlo.
//
// Por qué compartido y no dos copias: el bug recurrente de esta app es la
// misma métrica calculada por dos caminos en dos pantallas y dando distinto
// (P&L Dashboard ≠ Cartera). Un componente + un agregador = no puede divergir.
//
// Interacción:
//   • hover sobre una porción → tooltip con label, monto y %;
//   • hover sobre una fila de la leyenda → resalta la porción;
//   • CLICK en la fila (o en la porción) → despliega qué activos la componen.
//     Un "18% en Semiconductores" no dice nada hasta que ves que son NVDA y
//     AMD. Los % de los hijos suman exactamente el % del padre, así que la
//     lista se lee como una descomposición, no como otra métrica.
//
// Nota de tema: el tooltip NO hardcodea colores (el pie "Por broker" de
// Insights sí lo hace — `background:'#1e293b'`). Acá todo sale de los tokens
// del design system. La app es dark-only por decisión de producto
// (ThemeContext.LIGHT_MODE_LOCKED), así que usamos los tokens V2 planos.

import { useState, useMemo } from 'react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { ChevronRight } from 'lucide-react'
import InfoTooltip from './InfoTooltip'

// Debajo de este peso la porción no se lista aparte: se agrupa en "Otros" para
// que la leyenda no se llene de slivers ilegibles. 10 clases de activo ya es
// mucho; con 19 sectores sería inusable.
//
// Es el DEFAULT, no una constante: el eje por ACTIVO del libro del asesor
// (~486 tickers en un libro de 100 clientes) ya viene cortado en top-N + un
// "Resto" explícito desde el agregador, y volver a agrupar acá partiría ese
// resto en dos "Otros" distintos. Ese caso pasa minSlicePct={0}.
const MIN_SLICE_PCT = 1.5
const OTHERS_COLOR = '#5A6478'
// Cuántos activos mostramos al desplegar antes de cortar con "y N más".
const MAX_DETAIL_ROWS = 12

// Signo explícito y color por resultado. El '−' es el menos tipográfico
// (U+2212), que es el que usa el resto de la app para cifras.
const signed = (v) => `${v >= 0 ? '+' : '−'}`
const toneOf = (v) => (v >= 0 ? 'text-rendi-pos' : 'text-rendi-neg')

// 'FCI:FIMA-PREMIUM-A' → 'FIMA-PREMIUM-A'. El prefijo es interno (símbolo
// canónico del catálogo), no algo que el usuario reconozca.
const displayTicker = (t) => String(t || '').replace(/^FCI:/, '')

export default function CompositionDonut({
  title,
  subtitle = null,
  items = [],
  fmt = (v) => `US$ ${Math.round(v).toLocaleString('es-AR')}`,
  info = null,
  footnote = null,
  emptyLabel = 'Todavía no hay posiciones para mostrar.',
  height = 200,
  maxSlices = 10,
  minSlicePct = MIN_SLICE_PCT,
  className = '',
}) {
  const [active, setActive] = useState(null)
  const [open, setOpen] = useState(() => new Set())

  const toggle = (key) => setOpen(prev => {
    const next = new Set(prev)
    next.has(key) ? next.delete(key) : next.add(key)
    return next
  })

  // Agrupamos las porciones irrelevantes DESPUÉS de calcular los %, así el
  // "Otros" de la leyenda sigue sumando el total real. Cada porción lleva su
  // `detail`: para una porción normal son sus activos; para el "Otros"
  // agrupado son las porciones que quedaron adentro.
  const slices = useMemo(() => {
    const sorted = [...items].filter(i => i.value > 0).sort((a, b) => b.value - a.value)
    if (sorted.length === 0) return []
    const keep = []
    const rest = []
    for (const it of sorted) {
      if (keep.length < maxSlices && it.pct >= minSlicePct) keep.push(it)
      else rest.push(it)
    }
    const withDetail = keep.map(it => ({
      ...it,
      detail: (it.assets || []).map(a => ({
        key: a.asset, label: displayTicker(a.asset), value: a.value, pct: a.pct, pnl: a.pnl,
        // Dispersión entre carteras — solo la manda el libro del asesor.
        spread: a.spread,
      })),
    }))
    // Las porciones RESIDUALES van al final, pegadas al "Otros" de agrupación:
    // si no, quedan mezcladas entre porciones reales y se leen como una más.
    // Son dos casos: las "no sé qué es" (otro / sin_dato) y el "Resto" que un
    // caller puede traer ya agrupado (el eje por activo del libro del asesor
    // corta en top-N y manda el resto en una porción propia). Ese Resto puede
    // pesar más que la porción más grande — en un libro de 486 tickers pesa
    // 16% mientras el primer activo pesa 14% — y sin esto encabezaría la
    // torta, que es exactamente lo que un residual no tiene que hacer.
    const RESIDUAL = new Set(['otro', 'sin_dato', '__resto__'])
    const unknownIdx = withDetail.findIndex(i => RESIDUAL.has(i.key))
    if (unknownIdx >= 0 && unknownIdx < withDetail.length - 1) {
      withDetail.push(withDetail.splice(unknownIdx, 1)[0])
    }
    if (rest.length === 1) {
      const r = rest[0]
      return [...withDetail, {
        ...r,
        detail: (r.assets || []).map(a => ({
          key: a.asset, label: displayTicker(a.asset), value: a.value, pct: a.pct, pnl: a.pnl,
          spread: a.spread,
        })),
      }]
    }
    if (rest.length > 1) {
      withDetail.push({
        key: '__otros__',
        label: `Otros (${rest.length})`,
        color: OTHERS_COLOR,
        value: rest.reduce((s, x) => s + x.value, 0),
        pct: rest.reduce((s, x) => s + x.pct, 0),
        // Acá el detalle son las porciones agrupadas, no activos sueltos:
        // desplegar "Otros" tiene que contestar "otros QUÉ".
        detail: rest.map(r => ({ key: r.key, label: r.label, value: r.value, pct: r.pct })),
      })
    }
    return withDetail
  }, [items, maxSlices, minSlicePct])

  const isEmpty = slices.length === 0

  return (
    <div className={`border border-line rounded bg-bg-1 p-4 ${className}`}>
      <div className="flex items-baseline justify-between gap-2 mb-3">
        <div className="flex items-center gap-1.5 min-w-0">
          <h3 className="text-sm font-medium text-ink-0 truncate">{title}</h3>
          {info && <InfoTooltip size={12} align="left">{info}</InfoTooltip>}
        </div>
        {subtitle && (
          <span className="text-xs text-ink-3 flex-shrink-0">{subtitle}</span>
        )}
      </div>

      {isEmpty ? (
        <p className="text-ink-3 text-sm text-center py-10">{emptyLabel}</p>
      ) : (
        <>
          <div style={{ height }} onMouseLeave={() => setActive(null)}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={slices}
                  dataKey="value"
                  nameKey="label"
                  cx="50%"
                  cy="50%"
                  innerRadius="58%"
                  outerRadius="92%"
                  paddingAngle={2}
                  stroke="none"
                  isAnimationActive={false}
                  onMouseEnter={(_, i) => setActive(i)}
                  onClick={(_, i) => slices[i]?.detail?.length && toggle(slices[i].key)}
                  className={slices.some(s => s.detail?.length) ? 'cursor-pointer' : ''}
                >
                  {slices.map((s, i) => (
                    <Cell
                      key={s.key}
                      fill={s.color}
                      opacity={active === null || active === i ? 1 : 0.32}
                    />
                  ))}
                </Pie>
                <Tooltip
                  cursor={false}
                  wrapperStyle={{ outline: 'none' }}
                  content={<DonutTooltip fmt={fmt} />}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="mt-3">
            {slices.map((s, i) => (
              <LegendRow
                key={s.key}
                slice={s}
                fmt={fmt}
                highlighted={active === i}
                expanded={open.has(s.key)}
                onHover={() => setActive(i)}
                onLeave={() => setActive(null)}
                onToggle={() => toggle(s.key)}
              />
            ))}
          </div>
        </>
      )}

      {footnote && (
        <div className="text-[11px] text-ink-3 leading-snug mt-3 pt-3 border-t border-line/40">
          {footnote}
        </div>
      )}
    </div>
  )
}

// Una fila de la leyenda. Desplegable solo si tiene detalle — las porciones
// sintéticas (plazo fijo, que no viene de `positions`) no tienen qué mostrar,
// y darles un chevron que no hace nada es peor que no tenerlo.
function LegendRow({ slice, fmt, highlighted, expanded, onHover, onLeave, onToggle }) {
  // Se despliega si hay algo que mostrar: activos, o al menos el resultado
  // (el plazo fijo no tiene activos pero sí interés devengado).
  const canExpand = slice.detail?.length > 0 || Boolean(slice.pnl)
  const shown = slice.detail?.slice(0, MAX_DETAIL_ROWS) || []
  const hidden = (slice.detail?.length || 0) - shown.length

  const body = (
    <>
      <div className="flex items-center gap-2 min-w-0">
        {canExpand ? (
          <ChevronRight
            size={11}
            className={`flex-shrink-0 text-ink-3 transition-transform ${expanded ? 'rotate-90' : ''}`}
          />
        ) : (
          <span className="w-[11px] flex-shrink-0" />
        )}
        <span
          className="inline-block w-2 h-2 rounded-sm flex-shrink-0"
          style={{ background: slice.color }}
        />
        <span className="text-ink-1 truncate">{slice.label}</span>
      </div>
      <div className="flex items-baseline gap-2 flex-shrink-0">
        <span className="text-ink-3 tabular text-[11px]">{fmt(slice.value)}</span>
        <span className="text-ink-0 tabular font-medium min-w-[42px] text-right">
          {slice.pct.toFixed(1)}%
        </span>
      </div>
    </>
  )

  const rowCls = `w-full flex items-center justify-between gap-3 text-xs rounded-sm px-1 -mx-1 py-1 transition-colors ${
    highlighted ? 'bg-bg-2/60' : ''
  }`

  return (
    <div onMouseEnter={onHover} onMouseLeave={onLeave}>
      {canExpand ? (
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          className={`${rowCls} text-left hover:bg-bg-2/60`}
        >
          {body}
        </button>
      ) : (
        <div className={rowCls}>{body}</div>
      )}

      {expanded && (
        // El desglose lleva el COLOR de su porción (borde + fondo tenue): sin
        // eso, cinco listas grises abiertas a la vez se mezclan y no se sabe
        // cuál cuelga de cuál. Coloreamos el contenedor, no el texto — hay
        // porciones con hues grises (Efectivo, Sin clasificar) que como color
        // de tipografía quedarían ilegibles.
        <div
          className="ml-[15px] pl-2.5 pr-1 border-l-2 rounded-r-sm space-y-1 py-1.5 mb-1"
          style={{ borderColor: `${slice.color}80`, background: `${slice.color}0F` }}
        >
          {slice.pnl && (
            // El titular de la porción: cuánta plata te dejó y a qué tasa.
            // Suma no realizado + realizado + renta (cupones/dividendos).
            <div className="flex items-baseline justify-between gap-3 text-[11px] pb-1.5 mb-1 border-b border-line/40">
              <span className="text-ink-2">Resultado</span>
              <div className="flex items-baseline gap-2 flex-shrink-0">
                <span className={`tabular font-medium ${toneOf(slice.pnl.total)}`}>
                  {signed(slice.pnl.total)}{fmt(Math.abs(slice.pnl.total))}
                </span>
                {slice.pnl.pct != null && (
                  <span className={`tabular font-medium min-w-[46px] text-right ${toneOf(slice.pnl.total)}`}>
                    {signed(slice.pnl.pct)}{Math.abs(slice.pnl.pct).toFixed(1)}%
                  </span>
                )}
              </div>
            </div>
          )}
          {shown.map(d => (
            <div key={d.key}>
            <div className="flex items-baseline justify-between gap-3 text-[11px]">
              <span className="text-ink-1 font-mono font-medium truncate">{d.label}</span>
              <div className="flex items-baseline gap-2 flex-shrink-0">
                <span className="text-ink-2 tabular">{fmt(d.value)}</span>
                <span className="text-ink-0 tabular font-medium min-w-[38px] text-right">
                  {d.pct.toFixed(1)}%
                </span>
                {slice.pnl && (
                  <span
                    className={`tabular font-medium min-w-[46px] text-right ${
                      d.pnl ? toneOf(d.pnl.total) : 'text-ink-3'
                    }`}
                    // El '—' significa "no hay tasa que valga", y hay dos
                    // motivos: falta el costo de alguna venta, o el capital
                    // que generó ese resultado ya no está en la posición (un
                    // bono amortizado que siguió pagando cupones). En los dos
                    // casos el MONTO sigue siendo válido; la tasa no.
                    title={d.pnl && d.pnl.pct == null
                      ? 'Sin tasa confiable: falta el costo de alguna venta, o el capital que generó este resultado ya no está en la posición.'
                      : undefined}
                  >
                    {d.pnl?.pct != null
                      ? `${signed(d.pnl.pct)}${Math.abs(d.pnl.pct).toFixed(1)}%`
                      : '—'}
                  </span>
                )}
              </div>
            </div>
            {d.spread && (
              // El % de arriba es AGRUPADO: la plata de todas las carteras
              // junta. Este rango dice cuánto se abren los clientes por
              // adentro — un +9,8% promedio puede ser alguien en −20%. Sale
              // del mismo cálculo de tres patas que el agrupado, así que el
              // rango siempre lo contiene.
              <div className="text-[10px] text-ink-3 tabular pl-0.5 -mt-0.5">
                {d.spread.clients} carteras · de{' '}
                <span className={toneOf(d.spread.min_pct)}>
                  {signed(d.spread.min_pct)}{Math.abs(d.spread.min_pct).toFixed(1)}%
                </span>
                {' '}a{' '}
                <span className={toneOf(d.spread.max_pct)}>
                  {signed(d.spread.max_pct)}{Math.abs(d.spread.max_pct).toFixed(1)}%
                </span>
              </div>
            )}
            </div>
          ))}
          {hidden > 0 && (
            <div className="text-[11px] text-ink-3">y {hidden} más</div>
          )}
        </div>
      )}
    </div>
  )
}

// Tooltip propio: recharts pinta el default con estilos inline claros que en
// dark mode quedan ilegibles. Este usa los tokens del design system.
function DonutTooltip({ active, payload, fmt }) {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  return (
    <div className="border border-line-2 bg-bg-2 rounded px-2.5 py-1.5 shadow-lg">
      <div className="flex items-center gap-2">
        <span
          className="inline-block w-2 h-2 rounded-sm flex-shrink-0"
          style={{ background: d.color }}
        />
        <span className="text-xs font-medium text-ink-0">{d.label}</span>
      </div>
      <div className="text-[11px] text-ink-2 tabular mt-1 pl-4">
        {fmt(d.value)} · <span className="text-ink-0 font-medium">{d.pct.toFixed(1)}%</span>
      </div>
      {d.detail?.length > 0 && (
        <div className="text-[10px] text-ink-3 mt-1 pl-4">
          {d.detail.length} {d.detail.length === 1 ? 'activo' : 'activos'} · clic para ver
        </div>
      )}
    </div>
  )
}

// UnclassifiedNote — la nota al pie que dice cuánto quedó sin clasificar.
// ═══════════════════════════════════════════════════════════════════════════
// No es decoración: `unmapped_count` ya se calculaba en el backend
// (behavioral.py) y ningún consumidor lo usaba, así que la barra de sectores
// se dibujaba igual con el 72% de la cartera adentro de "Otros" sin avisar.
// Una torta con un cuarto sin clasificar no es una torta: es una pregunta.
//
// Silencio si es despreciable (<2%): no vale ensuciar la card por un resto.
export function UnclassifiedNote({ data, kind = 'tipo' }) {
  if (!data || data.pct < 2) return null

  const many = data.assets.length > 6
  const shown = many ? data.assets.slice(0, 6) : data.assets
  const alto = data.pct >= 20

  return (
    <div className={alto ? 'text-rendi-warn' : ''}>
      <span className="tabular font-medium">{data.pct.toFixed(1)}%</span> de tu
      cartera no pudo clasificarse por {kind}
      {shown.length > 0 && (
        <>
          {': '}
          <span className="font-mono">{shown.map(displayTicker).join(', ')}</span>
          {many && ` y ${data.assets.length - shown.length} más`}
        </>
      )}
      .{' '}
      {kind === 'tipo'
        ? 'Suele pasar con FCI y activos que el broker exporta con código propio.'
        : 'Son activos que todavía no están en el mapa sectorial.'}
    </div>
  )
}
