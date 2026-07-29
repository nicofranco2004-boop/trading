// AdvisorDashboard — el "libro" del asesor.
// ═══════════════════════════════════════════════════════════════════════════
// Se renderiza DESDE Dashboard.jsx (mismo /dashboard) cuando isAdvisor &&
// !clientCtx — el asesor no tiene cartera propia (decisión de producto), así
// que en su propio nivel "Dashboard" muestra el libro (AUM total, motor
// estrella, colas de atención, distribución) en vez de una cartera personal.
//
// Split del 2026-07-23: esto vivía junto con el roster en AdvisorClients.jsx
// (F3). El roster puro (agregar/invitar/operación grupal) sigue ahí, en
// /clientes — esta página es SOLO el libro.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { PhoneCall, Landmark, TrendingUp, TrendingDown, Users, ArrowRight, LineChart, FileText, ExternalLink } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import { api } from '../utils/api'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import Modal from '../components/Modal'
import { useToast } from '../components/Toast'
import { usd } from '../utils/format'

// usd() formatea negativos con paréntesis — para deltas del libro queremos ±.
const signedUsd = (n) => (n >= 0 ? `+${usd(n, 0)}` : `−${usd(Math.abs(n), 0)}`)
const signedPct = (n) => (n >= 0 ? `+${n}%` : `${n}%`)

export default function AdvisorDashboard() {
  const navigate = useNavigate()
  const { enterClient } = useAdvisorContext()
  const [book, setBook] = useState(null)     // null = cargando
  const [history, setHistory] = useState(null)  // serie AUM (evolución del libro)
  const [historyError, setHistoryError] = useState(false)
  const [error, setError] = useState(false)
  const [reportOpen, setReportOpen] = useState(false)

  const load = useCallback(async () => {
    try {
      setBook(await api.get('/advisor/book'))
      setError(false)
    } catch {
      // No pisar un libro ya mostrado con nada; avisar que está desactualizado.
      setError(true)
    }
    // La serie histórica carga aparte y no bloquea el resto del libro.
    try {
      const h = await api.get('/advisor/book/history?days=730')
      setHistory(h.series || [])
      setHistoryError(false)
    } catch {
      // Distinguir error de "sin datos": el empty-state decía "en unos días
      // vas a ver la curva" ante un fallo de red (audit).
      setHistory(prev => prev ?? [])
      setHistoryError(true)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const openClient = (c) => {
    enterClient({ id: c.client_uid, label: c.label })
    navigate('/dashboard')
  }

  const noClients = book && (!book.aum || book.aum.clients === 0)

  return (
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Plan Asesor"
        title="Tu libro"
        subtitle="Cómo viene, en conjunto, todo lo que administrás."
        action={(
          <button
            type="button"
            onClick={() => setReportOpen(true)}
            disabled={!book || (book.aum?.clients ?? 0) === 0}
            className={btnPrimary}
          >
            <FileText size={13} strokeWidth={1.75} />
            Informe del período
          </button>
        )}
      />
      {reportOpen && <ReportModal onClose={() => setReportOpen(false)} />}

      {error && (
        <div className="mb-4 text-[12px] text-ink-2 bg-bg-1 border border-line/60 rounded-md px-3 py-2">
          No pudimos calcular el resumen recién{book ? ' — estás viendo la última versión' : ''}. Recargá la página para reintentar.
        </div>
      )}

      {book === null ? (
        // Con error y sin datos previos, el banner de arriba ES el estado —
        // los skeletons eternos leían como "sigue cargando" (audit).
        error ? null : (
          <div className="space-y-3">
            <Skeleton className="h-28 rounded-xl" />
            <Skeleton className="h-24 rounded-xl" />
          </div>
        )
      ) : noClients ? (
        <div className="border border-dashed border-line rounded-xl p-10 text-center">
          <Users size={28} strokeWidth={1.5} className="mx-auto text-ink-3 mb-3" />
          <h3 className="text-sm font-semibold text-ink-0 mb-1">Todavía no hay nada que mostrar acá</h3>
          <p className="text-xs text-ink-2 max-w-sm mx-auto mb-4">
            Tu libro se arma solo apenas tengas clientes con carteras cargadas.
          </p>
          <button type="button" onClick={() => navigate('/clientes')} className={btnPrimary}>
            Ir a Clientes <ArrowRight size={13} strokeWidth={2} />
          </button>
        </div>
      ) : (
        <>
          {book.aum && <BookHero book={book} />}
          <BookEvolution series={history} error={historyError} />
          {book.queues?.length > 0 && <CallQueue queues={book.queues} onOpen={openClient} />}
          {(book.star || book.distribution) && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
              {book.star && <StarSection star={book.star} />}
              {book.distribution && <DistributionCard dist={book.distribution} />}
            </div>
          )}
        </>
      )}
    </div>
  )
}

const btnPrimary = 'inline-flex items-center gap-1.5 text-xs font-medium text-white bg-data-violet hover:bg-data-violet/85 rounded-md px-3.5 py-2 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'

// ─── El libro (hero + colas + estrella + distribución) ──────────────────────
// Movido tal cual desde AdvisorClients.jsx (F3) — mismo contrato de datos
// (GET /advisor/book), solo cambió de página.

function BookHero({ book }) {
  const { aum, flows_month: flows } = book
  const [detailOpen, setDetailOpen] = useState(false)
  if (!aum || aum.clients === 0) return null
  const hasAum = aum.total_usd != null
  return (
    <div className="relative bg-bg-1 border border-line/60 rounded-xl p-5 mb-4">
      {hasAum && (
        <button
          type="button"
          onClick={() => setDetailOpen(true)}
          className="absolute top-4 right-4 inline-flex items-center gap-1 text-xs font-medium text-data-violet border border-line-3 rounded-md px-3 py-1.5 hover:bg-bg-2 transition-colors"
        >
          Detalle <ArrowRight size={12} strokeWidth={2} />
        </button>
      )}
      {detailOpen && <BookDetailModal onClose={() => setDetailOpen(false)} />}
      {/* pr-24 = reserva del ancho del botón absoluto: la columna Clientes
          (ml-auto) nunca queda abajo del "Detalle" aunque el hero se achique */}
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3 pr-24">
        <div>
          <p className="text-[11.5px] text-ink-3 mb-1">Total administrado</p>
          {hasAum ? (
            <>
              <p className="text-3xl font-semibold text-ink-0 tabular-nums leading-none">
                {usd(aum.total_usd, 0)}
              </p>
              <p className="text-[10.5px] text-ink-3 mt-1.5">
                La suma de las carteras de todos tus clientes
                {(() => {
                  // Si el snapshot más nuevo es viejo (cron caído), avisar en
                  // vez de mentir "+0" como si el mercado no se hubiera movido.
                  if (!aum.as_of) return null
                  const days = Math.floor((Date.now() - new Date(aum.as_of + 'T12:00:00').getTime()) / 86400000)
                  return days > 1 ? ` · datos al ${aum.as_of}` : null
                })()}
              </p>
            </>
          ) : (
            <p className="text-lg text-ink-3 leading-none">
              Se calcula esta noche
              <span className="block text-[11px] mt-1">cada noche sumamos el valor de las carteras cargadas</span>
            </p>
          )}
        </div>
        {aum.delta_7d_usd != null && (
          <div>
            <p className="text-[11.5px] text-ink-3 mb-1">Últimos 7 días</p>
            <p className={`text-sm font-medium tabular-nums ${aum.delta_7d_usd >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
              {signedUsd(aum.delta_7d_usd)}
              {aum.delta_7d_pct != null && ` · ${signedPct(aum.delta_7d_pct)}`}
            </p>
          </div>
        )}
        {flows && (
          <div>
            <p className="text-[11.5px] text-ink-3 mb-1">Aportes − retiros (este mes)</p>
            <p className="text-sm font-medium text-ink-0 tabular-nums">
              {signedUsd(flows.net_deposited_usd)}
            </p>
            <p className="text-[10.5px] text-ink-3 mt-0.5 tabular-nums">
              Plata que entró/salió de las cuentas · el mercado {flows.market_effect_usd >= 0 ? 'sumó ' : 'restó '}
              {usd(Math.abs(flows.market_effect_usd), 0)}
            </p>
          </div>
        )}
        <div className="ml-auto text-right">
          <p className="text-[11.5px] text-ink-3 mb-1">Clientes</p>
          <p className="text-sm font-medium text-ink-0 tabular-nums">
            {aum.clients}
            {aum.with_data < aum.clients && (
              <span className="text-ink-3 font-normal"> · {aum.clients - aum.with_data} sin datos aún</span>
            )}
          </p>
        </div>
      </div>
    </div>
  )
}

// ─── Detalle del capital administrado (idea de Nico) ────────────────────────
// Modal que abre el hero: quién pone cuánto del AUM y quién movió la aguja
// en los últimos 7 días. La variación separa mercado de aportes (un depósito
// no es ganancia) y su suma cierra EXACTO con el hero — misma regla de
// comparabilidad que /advisor/book (solo clientes con foto en ambos cortes).

const COMP_COLORS = ['#8B7DFF', '#7466E8', '#5F53C4', '#4C429E', '#3D357E']
const DETAIL_GRID = { display: 'grid', gridTemplateColumns: '1.5fr 0.9fr 1fr 1.35fr 1.25fr', gap: '12px', alignItems: 'center' }

function BookDetailModal({ onClose }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(false)
  const [sortBy, setSortBy] = useState('cap')   // 'cap' | 'var'

  useEffect(() => {
    api.get('/advisor/book/detail').then(setData).catch(() => setError(true))
  }, [])

  const { rows, edge, comp, maxShare, maxAbsDelta } = useMemo(() => {
    const cs = data?.clients ?? []
    const ok = cs.filter(c => c.state === 'ok')
    const edge = cs.filter(c => c.state !== 'ok')
    const sorted = [...ok].sort((a, b) => sortBy === 'cap'
      ? (b.value_usd ?? 0) - (a.value_usd ?? 0)
      : Math.abs(b.delta_7d_usd ?? 0) - Math.abs(a.delta_7d_usd ?? 0))
    // Composición: top 5 por capital + "Resto" (los "new" también suman AUM)
    const valued = cs.filter(c => c.value_usd != null).sort((a, b) => b.value_usd - a.value_usd)
    const top = valued.slice(0, 5)
    const restV = valued.slice(5).reduce((s, c) => s + c.value_usd, 0)
    const comp = top.map((c, i) => ({ label: c.label, pct: c.share_pct ?? 0, color: COMP_COLORS[i] }))
    if (restV > 0 && data?.total_usd > 0) {
      comp.push({ label: `Resto (${valued.length - 5})`, pct: Math.round((restV / data.total_usd) * 1000) / 10, color: '#3A4256' })
    }
    return {
      rows: sorted, edge, comp,
      maxShare: Math.max(...valued.map(c => c.share_pct ?? 0), 1),
      maxAbsDelta: Math.max(...ok.map(c => Math.abs(c.delta_7d_usd ?? 0)), 1),
    }
  }, [data, sortBy])

  return (
    <Modal title="Capital administrado — detalle" onClose={onClose} wide>
      {error ? (
        <p className="text-xs text-ink-2 py-6 text-center">
          No pudimos armar el detalle recién. Cerrá y probá de nuevo.
        </p>
      ) : !data ? (
        <div className="space-y-2 py-2">
          <Skeleton className="h-10 rounded-md" />
          <Skeleton className="h-40 rounded-md" />
        </div>
      ) : (
        <div className="space-y-4">
          {/* Composición del libro */}
          {comp.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-widest text-ink-3 mb-2">Composición del libro</p>
              <div className="flex gap-0.5 h-3 rounded overflow-hidden">
                {comp.map((s) => (
                  <div key={s.label} className="rounded-[2px]" style={{ flex: s.pct, background: s.color }} />
                ))}
              </div>
              <div className="flex flex-wrap gap-x-3.5 gap-y-1.5 mt-2">
                {comp.map((s) => (
                  <span key={s.label} className="inline-flex items-center gap-1.5 text-[11px] text-ink-2">
                    <i className="w-2 h-2 rounded-[2px]" style={{ background: s.color }} />
                    {s.label} <span className="tabular-nums">{s.pct}%</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Orden */}
          <div className="flex items-center gap-2.5">
            <span className="text-[10px] uppercase tracking-widest text-ink-3">Ordenar</span>
            <div className="inline-flex bg-bg-2 border border-line-2 rounded-md p-0.5">
              {[['cap', 'Por capital'], ['var', 'Por variación 7d']].map(([k, lbl]) => (
                <button
                  key={k} type="button" onClick={() => setSortBy(k)}
                  className={`text-[11.5px] font-medium rounded px-3 py-1 transition-colors ${sortBy === k ? 'bg-bg-3 text-ink-0' : 'text-ink-2 hover:text-ink-1'}`}
                >
                  {lbl}
                </button>
              ))}
            </div>
          </div>

          {/* Tabla */}
          <div className="overflow-x-auto">
            <div className="min-w-[620px]">
              <div style={DETAIL_GRID} className="px-3 pb-1.5">
                {['Cliente', 'Capital', 'Del libro', 'Últimos 7 días', 'Aporte a la variación'].map((h, i) => (
                  <span key={h} className={`text-[10.5px] text-ink-3 ${i > 0 ? 'text-right' : ''}`}>{h}</span>
                ))}
              </div>
              <div className="space-y-0.5">
                {rows.map((c) => {
                  const flows = c.flows_7d_usd ?? 0
                  const pos = (c.delta_7d_usd ?? 0) >= 0
                  return (
                    <div key={c.client_uid} style={DETAIL_GRID} className="bg-bg-2 rounded-md px-3 py-2.5">
                      <span className="text-[13px] font-medium text-ink-0 truncate">{c.label}</span>
                      <span className="text-right text-[13px] text-ink-0 tabular-nums">{usd(c.value_usd, 0)}</span>
                      <span className="flex items-center justify-end gap-2">
                        <b className="text-xs font-medium text-ink-1 tabular-nums">{c.share_pct != null ? `${c.share_pct}%` : '—'}</b>
                        <span className="w-12 h-1 bg-bg-3 rounded-full overflow-hidden shrink-0">
                          <i className="block h-full bg-data-violet rounded-full" style={{ width: `${Math.min((c.share_pct ?? 0) / maxShare * 100, 100)}%` }} />
                        </span>
                      </span>
                      <span className={`text-right text-[13px] font-medium tabular-nums ${pos ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                        {signedUsd(c.delta_7d_usd)}
                        <span className="block text-[10.5px] text-ink-3 font-normal mt-0.5">
                          {Math.abs(flows) >= 1
                            ? `${flows >= 0 ? 'aportó' : 'retiró'} ${usd(Math.abs(flows), 0)} · mercado ${signedUsd(c.market_7d_usd)}`
                            : `${c.delta_7d_pct != null ? signedPct(c.delta_7d_pct) : '—'} · todo mercado`}
                        </span>
                      </span>
                      <span className="flex items-center justify-end gap-2.5">
                        <span className={`text-xs tabular-nums ${pos ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{signedUsd(c.delta_7d_usd)}</span>
                        <span className="relative w-20 h-3 shrink-0">
                          <i className="absolute left-1/2 -top-0.5 -bottom-0.5 w-px bg-line-3" />
                          <i
                            className={`absolute top-0.5 bottom-0.5 rounded-[2px] ${pos ? 'left-1/2 bg-rendi-pos' : 'right-1/2 bg-rendi-neg'}`}
                            style={{ width: `${Math.abs(c.delta_7d_usd ?? 0) / maxAbsDelta * 48}%` }}
                          />
                        </span>
                      </span>
                    </div>
                  )
                })}
              </div>

              {/* Casos borde: sin base de 7 días / sin snapshot */}
              {edge.length > 0 && (
                <div className="space-y-0.5 mt-2">
                  {edge.map((c) => (
                    <div key={c.client_uid} style={DETAIL_GRID} className="border border-dashed border-line-2 rounded-md px-3 py-2.5">
                      <span className="text-[13px] text-ink-2 truncate">
                        {c.label}
                        <span className={`ml-2 text-[10px] font-semibold rounded px-1.5 py-0.5 align-[1px] ${c.state === 'new' ? 'text-data-violet bg-rendi-violet-deep' : 'text-ink-2 bg-bg-3'}`}>
                          {c.state === 'new' ? 'Sin base de 7 días' : 'Sin snapshot'}
                        </span>
                      </span>
                      {c.state === 'new' ? (
                        <>
                          <span className="text-right text-[13px] text-ink-1 tabular-nums">{usd(c.value_usd, 0)}</span>
                          <span className="flex items-center justify-end gap-2">
                            <b className="text-xs font-medium text-ink-2 tabular-nums">{c.share_pct != null ? `${c.share_pct}%` : '—'}</b>
                            <span className="w-12 h-1 bg-bg-3 rounded-full overflow-hidden shrink-0">
                              <i className="block h-full bg-line-3 rounded-full" style={{ width: `${Math.min((c.share_pct ?? 0) / maxShare * 100, 100)}%` }} />
                            </span>
                          </span>
                          <span className="text-right text-xs text-ink-3">Recién empezó a medirse</span>
                          <span className="text-right text-xs text-ink-3">No entra en la variación</span>
                        </>
                      ) : (
                        <>
                          <span className="text-right text-xs text-ink-3">Se calcula esta noche</span>
                          <span className="text-right text-xs text-ink-3">—</span>
                          <span className="text-right text-xs text-ink-3">—</span>
                          <span className="text-right text-xs text-ink-3">—</span>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <p className="text-[11.5px] text-ink-3 leading-relaxed border-t border-line pt-3">
            <span className="text-ink-2 font-medium">La variación separa mercado de aportes.</span>{' '}
            Si un cliente depositó esta semana, su suba no se disfraza de ganancia — la fila lo aclara.
            Los clientes sin foto de hace 7 días no entran en la variación del libro, por eso esta
            columna suma exacto el número del hero.
          </p>
        </div>
      )}
    </Modal>
  )
}

// ─── Evolución del capital administrado (idea de Nico) ──────────────────────
// La MISMA anatomía que el gráfico de evolución del dashboard personal:
// línea violeta = total administrado, punteada gris = plata aportada neta.
// La brecha entre las dos ES el efecto mercado — se ve a ojo si el libro
// sube porque los clientes ganan o porque entra plata/gente nueva.

const EVO_RANGES = [
  { key: '1M', days: 30 }, { key: '3M', days: 90 }, { key: '6M', days: 180 },
  { key: '1A', days: 365 }, { key: 'Todo', days: 99999 },
]

function BookEvolution({ series, error }) {
  const [range, setRange] = useState('3M')

  const { visible, baseline } = useMemo(() => {
    if (!series?.length) return { visible: [], baseline: null }
    const days = EVO_RANGES.find(r => r.key === range)?.days ?? 90
    const cutoff = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10)
    const firstIdx = series.findIndex(p => p.date >= cutoff)
    if (firstIdx === -1) return { visible: [], baseline: null }
    return {
      visible: series.slice(firstIdx),
      // Base de la descomposición: el punto ANTERIOR a la ventana (si existe)
      // — sin esto el cambio DEL PRIMER DÍA visible quedaba afuera del rótulo
      // "mercado sumó X · aportes +Y" (audit: inconsistente con el hero, que
      // usa el snapshot previo al período).
      baseline: firstIdx > 0 ? series[firstIdx - 1] : series[firstIdx],
    }
  }, [series, range])

  // Descomposición del período: ΔAUM = flujos (Δaportado) + mercado.
  const delta = useMemo(() => {
    if (visible.length < 2 || !baseline) return null
    const b = visible[visible.length - 1]
    const dAum = b.aum_usd - baseline.aum_usd
    const dFlows = b.net_deposited_usd - baseline.net_deposited_usd
    return { market: dAum - dFlows, flows: dFlows, clients: b.clients - baseline.clients }
  }, [visible, baseline])

  // U5 (audit): si la historia existe pero es más vieja que el rango default
  // (3M), auto-ampliamos UNA vez al rango más chico que muestre la curva —
  // antes caía a un empty-state falso sin botones para salir.
  const touchedRef = useRef(false)
  useEffect(() => {
    if (touchedRef.current || !series || series.length < 2 || visible.length >= 2) return
    const fit = EVO_RANGES.find(r => {
      const cut = new Date(Date.now() - r.days * 86400000).toISOString().slice(0, 10)
      return series.filter(p => p.date >= cut).length >= 2
    })
    if (fit) setRange(fit.key)
  }, [series, visible])

  if (series === null) return <Skeleton className="h-56 rounded-xl mb-4" />
  if (series.length < 2) {
    return (
      <div className="bg-bg-1 border border-line/60 rounded-xl p-4 mb-4">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-ink-0 mb-1">
          <LineChart size={13} strokeWidth={1.75} className="text-data-violet" />
          Evolución del capital administrado
        </h2>
        <p className="text-[11.5px] text-ink-3">
          {error
            ? 'No pudimos cargar la evolución recién — recargá la página para reintentar.'
            : `Se dibuja solo con los snapshots nocturnos — con un par de días de
          historia ya vas a ver la curva (y si el libro sube por el mercado o
          porque entra plata nueva).`}
        </p>
      </div>
    )
  }

  const fmtShort = (v) => {
    const abs = Math.abs(v)
    if (abs >= 1e9) return `US$${(v / 1e9).toFixed(1)}B`
    if (abs >= 1e6) return `US$${(v / 1e6).toFixed(1)}M`
    if (abs >= 1e3) return `US$${Math.round(v / 1e3)}k`
    return `US$${Math.round(v)}`
  }
  const signed = (n) => (n >= 0 ? `+${usd(n, 0)}` : `−${usd(Math.abs(n), 0)}`)
  const vals = visible.flatMap(p => [p.aum_usd, p.net_deposited_usd])
  const mn = Math.min(...vals), mx = Math.max(...vals)

  return (
    <div className="bg-bg-1 border border-line/60 rounded-xl p-4 mb-4">
      <div className="flex items-start justify-between gap-3 flex-wrap mb-2">
        <div>
          <h2 className="flex items-center gap-2 text-[13px] font-semibold text-ink-0">
            <LineChart size={13} strokeWidth={1.75} className="text-data-violet" />
            Evolución del capital administrado
          </h2>
          {delta && (
            <p className="text-[11px] text-ink-3 mt-0.5 ml-[21px]">
              En el período: el mercado {delta.market >= 0 ? 'sumó' : 'restó'}{' '}
              <span className={delta.market >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}>
                {usd(Math.abs(delta.market), 0)}
              </span>
              {' · '}aportes netos <span className="text-ink-1">{signed(delta.flows)}</span>
              {delta.clients !== 0 && (
                <> · {delta.clients > 0 ? `+${delta.clients}` : delta.clients} cliente{Math.abs(delta.clients) === 1 ? '' : 's'}</>
              )}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1">
          {EVO_RANGES.map(r => (
            <button key={r.key} type="button" onClick={() => { touchedRef.current = true; setRange(r.key) }}
              className={`text-[11px] font-medium rounded px-2 py-1 transition-colors ${
                range === r.key ? 'text-ink-0 bg-bg-2' : 'text-ink-3 hover:text-ink-1'
              }`}>
              {r.key}
            </button>
          ))}
        </div>
      </div>
      <div className="h-52">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={visible} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="bookEvoFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#8B7DFF" stopOpacity={0.18} />
                <stop offset="100%" stopColor="#8B7DFF" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1B2230" strokeOpacity={0.35} strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="date" tick={{ fill: '#7C8698', fontSize: 11 }}
                   axisLine={false} tickLine={false} minTickGap={48} dy={4}
                   tickFormatter={(d) => {
                     const dt = new Date(d + 'T12:00:00')
                     return dt.toLocaleDateString('es-AR', { day: 'numeric', month: 'short' })
                   }} />
            <YAxis tick={{ fill: '#7C8698', fontSize: 11 }} axisLine={false} tickLine={false}
                   tickFormatter={fmtShort} width={64}
                   domain={[mn > 0 ? mn * 0.97 : 0, mx * 1.02]} />
            <Tooltip
              cursor={{ stroke: '#5A5C5B', strokeWidth: 1, strokeDasharray: '3 3' }}
              contentStyle={{ background: '#10151F', border: '1px solid #262E40',
                              borderRadius: 12, padding: '10px 14px',
                              boxShadow: '0 12px 32px -12px rgba(0,0,0,.6)' }}
              labelStyle={{ color: '#E6EAF2', fontSize: 12, fontWeight: 600, marginBottom: 5 }}
              itemStyle={{ color: '#F4F4F0', fontSize: 12.5, padding: '2px 0' }}
              formatter={(v, name) => [usd(v, 0), name === 'aum_usd' ? 'Administrado' : 'Aportado neto']}
              labelFormatter={(label, payload) => {
                const p = payload?.[0]?.payload
                return p ? `${p.date} · ${p.clients} cliente${p.clients === 1 ? '' : 's'}` : label
              }}
            />
            <Area type="monotone" dataKey="net_deposited_usd" stroke="#3A4256" strokeWidth={1.5}
                  strokeDasharray="4 4" fill="none" dot={false} activeDot={false} />
            <Area type="monotone" dataKey="aum_usd" stroke="#8B7DFF" strokeWidth={1.75}
                  fill="url(#bookEvoFill)" dot={false}
                  activeDot={{ r: 4, fill: '#8B7DFF', stroke: '#0A0B0E', strokeWidth: 2 }} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10.5px] text-ink-3 mt-2">
        Línea violeta = todo lo que administrás · punteada = plata aportada neta.
        La brecha entre las dos es lo que puso (o sacó) el mercado.
      </p>
    </div>
  )
}

function CallQueue({ queues, onOpen }) {
  const KIND_STYLE = {
    drawdown:    'text-rendi-neg bg-rendi-neg/10',
    cash_ocioso: 'text-rendi-warn bg-rendi-warn/10',
    inactivo:    'text-ink-2 bg-bg-2',
    sin_cargar:  'text-data-violet bg-data-violet/10',
  }
  return (
    <div className="bg-bg-1 border border-line/60 rounded-xl p-4 mb-4">
      <div className="mb-3">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-ink-0">
          <PhoneCall size={13} strokeWidth={1.75} className="text-data-violet" />
          Clientes que necesitan tu atención
          <span className="text-ink-3 font-normal">({queues.length})</span>
        </h2>
        <p className="text-[11px] text-ink-3 mt-0.5 ml-[21px]">
          Señales automáticas: caídas fuertes, plata sin invertir o cuentas frenadas — los candidatos a un llamado.
        </p>
      </div>
      <div className="divide-y divide-line/40">
        {queues.map((q) => (
          <div key={q.client_uid} className="flex items-center gap-3 py-2 flex-wrap">
            <span className="text-sm font-medium text-ink-0 min-w-[140px]">{q.label}</span>
            <div className="flex-1 flex flex-wrap gap-1.5">
              {q.reasons.map((r, i) => (
                <span key={i} className={`text-[11px] rounded px-2 py-0.5 ${KIND_STYLE[r.kind] || 'text-ink-2 bg-bg-2'}`}>
                  {r.detail}
                </span>
              ))}
            </div>
            <button
              type="button"
              onClick={() => onOpen(q)}
              className="text-[11px] font-medium text-data-violet hover:bg-data-violet/10 border border-data-violet/30 rounded px-2 py-1 transition-colors flex-shrink-0"
            >
              Entrar →
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function StarSection({ star }) {
  const Row = ({ r, tone }) => {
    // Cada columna muestra SU plata (lo que pierden los que pierden / ganan
    // los que ganan) — el neto agregado contradecía el título cuando un
    // activo tenía clientes en ambos lados.
    const pnl = tone === 'red' ? (r.pnl_red_usd ?? r.pnl_usd) : (r.pnl_green_usd ?? r.pnl_usd)
    return (
      <div className="flex items-center gap-2 py-1.5">
        <span className="text-sm font-medium text-ink-0 w-20 truncate">{r.asset}</span>
        <span className="text-[11px] text-ink-2 flex-1">
          {tone === 'red'
            ? `${r.clients_red} de ${r.clients_total} cliente${r.clients_total === 1 ? '' : 's'} en rojo`
            : `${r.clients_green} de ${r.clients_total} cliente${r.clients_total === 1 ? '' : 's'} en verde`}
        </span>
        <span className={`text-xs font-medium tabular-nums ${pnl >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
          {signedUsd(pnl)}
        </span>
      </div>
    )
  }
  return (
    <div className="lg:col-span-2 bg-bg-1 border border-line/60 rounded-xl p-4">
      <h2 className="text-[13px] font-semibold text-ink-0 mb-3">Qué activos mueven a tus clientes</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6">
        <div>
          <p className="flex items-center gap-1.5 text-[11px] text-rendi-neg font-medium mb-1">
            <TrendingDown size={11} strokeWidth={2} /> Le hace perder a más clientes
          </p>
          {star.losers.length
            ? star.losers.map((r) => <Row key={r.asset} r={r} tone="red" />)
            : <p className="text-[11.5px] text-ink-3 py-1.5">Ningún activo les está haciendo perder plata.</p>}
        </div>
        <div>
          <p className="flex items-center gap-1.5 text-[11px] text-rendi-pos font-medium mb-1">
            <TrendingUp size={11} strokeWidth={2} /> Le hace ganar a más clientes
          </p>
          {star.winners.length
            ? star.winners.map((r) => <Row key={r.asset} r={r} tone="green" />)
            : <p className="text-[11.5px] text-ink-3 py-1.5">Todavía ningún activo les está dando ganancia.</p>}
        </div>
      </div>
      {star.skipped_no_price > 0 && (
        <p className="text-[10.5px] text-ink-3 mt-2">
          {star.skipped_no_price} posición{star.skipped_no_price === 1 ? '' : 'es'} quedaron afuera del cálculo (sin precio conocido o con broker borrado).
        </p>
      )}
    </div>
  )
}

function DistributionCard({ dist }) {
  const total = dist.green + dist.red + dist.flat
  const pct = (n) => (total > 0 ? (n / total) * 100 : 0)
  return (
    <div className="bg-bg-1 border border-line/60 rounded-xl p-4">
      <h2 className="flex items-center gap-2 text-[13px] font-semibold text-ink-0 mb-3">
        <Landmark size={13} strokeWidth={1.75} className="text-data-violet" />
        ¿Cómo vienen tus clientes?
      </h2>
      <div className="flex h-2 rounded-full overflow-hidden bg-bg-2 mb-2">
        {dist.green > 0 && <div className="bg-rendi-pos" style={{ width: `${pct(dist.green)}%` }} />}
        {dist.flat > 0 && <div className="bg-ink-3/40" style={{ width: `${pct(dist.flat)}%` }} />}
        {dist.red > 0 && <div className="bg-rendi-neg" style={{ width: `${pct(dist.red)}%` }} />}
      </div>
      <p className="text-[11.5px] text-ink-2 mb-3">
        <span className="text-rendi-pos font-medium">{dist.green} en verde</span>
        {' · '}
        <span className="text-rendi-neg font-medium">{dist.red} en rojo</span>
        {dist.flat > 0 && <> · {dist.flat} neutro{dist.flat === 1 ? '' : 's'}</>}
      </p>
      <div className="space-y-1 text-[11.5px]">
        {dist.best && (
          <p className="text-ink-2 truncate">
            Mejor: <span className="text-ink-0">{dist.best.label}</span>{' '}
            <span className={`tabular-nums ${dist.best.ret_pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{signedPct(dist.best.ret_pct)}</span>
          </p>
        )}
        {dist.worst && dist.worst.client_uid !== dist.best?.client_uid && (
          <p className="text-ink-2 truncate">
            Peor: <span className="text-ink-0">{dist.worst.label}</span>{' '}
            <span className={`tabular-nums ${dist.worst.ret_pct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{signedPct(dist.worst.ret_pct)}</span>
          </p>
        )}
      </div>
      <p className="text-[10.5px] text-ink-3 mt-2">Cuánto ganó cada uno sobre la plata que puso, según los últimos datos del cierre.</p>
    </div>
  )
}

// ─── Informe del período (prioridad #1 del research) ────────────────────────
// Genera el lote de informes brandeados: uno por cliente, congelado, con
// link público /i/{token} + texto listo para WhatsApp. La marca (nombre +
// matrícula CNV) se pide acá mismo la primera vez y queda guardada.

function ReportModal({ onClose }) {
  const toast = useToast()
  const today = new Date()
  // Fecha LOCAL (audit: toISOString es UTC — de noche en Argentina devolvía
  // la fecha de mañana en un documento con matrícula CNV).
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const firstOfMonth = new Date(today.getFullYear(), today.getMonth(), 1)
  const firstOfPrev = new Date(today.getFullYear(), today.getMonth() - 1, 1)
  const endOfPrev = new Date(today.getFullYear(), today.getMonth(), 0)
  const PERIODS = [
    { key: 'mes', label: 'Este mes', start: iso(firstOfMonth), end: iso(today) },
    { key: 'prev', label: 'Mes pasado', start: iso(firstOfPrev), end: iso(endOfPrev) },
    { key: '90d', label: '90 días', start: iso(new Date(today.getTime() - 90 * 86400000)), end: iso(today) },
    { key: 'ytd', label: 'Este año', start: iso(new Date(today.getFullYear(), 0, 1)), end: iso(today) },
  ]
  const [period, setPeriod] = useState('mes')
  const [clients, setClients] = useState(null)
  // Selección con checkboxes (feedback Nico): "Todos" + tildar un subconjunto.
  const [checked, setChecked] = useState(null)    // Set de client_uid; null hasta cargar
  const [note, setNote] = useState('')
  const [brand, setBrand] = useState({ name: '', matricula: '', logo: null })
  const [brandDirty, setBrandDirty] = useState(false)
  // Si el GET del perfil falló, editar la marca y generar PISARÍA el logo y
  // la matrícula guardados con los campos vacíos del form (audit): bloqueamos
  // el PATCH hasta que la marca guardada haya cargado de verdad.
  const [profileError, setProfileError] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [results, setResults] = useState(null)

  useEffect(() => {
    api.get('/advisor/clients').then(d => {
      const cs = d.clients || []
      setClients(cs)
      setChecked(new Set(cs.map(c => c.client_uid)))  // arranca con todos tildados
    }).catch(() => { setClients([]); setChecked(new Set()) })
    api.get('/advisor/profile').then(p => setBrand({ name: p.name || '', matricula: p.matricula || '', logo: p.logo || null })).catch(() => setProfileError(true))
  }, [])

  const allChecked = clients && checked && checked.size === clients.length
  const toggleAll = () => {
    if (!clients) return  // roster aún cargando — evita el TypeError del .map
    setChecked(allChecked ? new Set() : new Set(clients.map(c => c.client_uid)))
  }
  const toggleOne = (uid) => setChecked(prev => {
    const next = new Set(prev)
    next.has(uid) ? next.delete(uid) : next.add(uid)
    return next
  })

  // Logo: leer el archivo, achicarlo con canvas (máx 256px de alto — el
  // informe lo muestra a 40px, no hace falta más) y guardarlo como data-URI.
  const onLogoFile = (file) => {
    if (!file || !/^image\/(png|jpeg|webp)$/.test(file.type)) {
      toast.push('Subí un PNG o JPG', { type: 'error' })
      return
    }
    const img = new Image()
    img.onload = () => {
      const scale = Math.min(1, 256 / img.height, 512 / img.width)
      const canvas = document.createElement('canvas')
      canvas.width = Math.round(img.width * scale)
      canvas.height = Math.round(img.height * scale)
      canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height)
      const data = canvas.toDataURL('image/png')
      if (data.length > 390_000) {
        toast.push('El logo quedó muy pesado — probá con una imagen más simple', { type: 'error' })
        return
      }
      setBrand(b => ({ ...b, logo: data }))
      setBrandDirty(true)
    }
    img.onerror = () => toast.push('No pudimos leer esa imagen', { type: 'error' })
    img.src = URL.createObjectURL(file)
  }

  const generate = async () => {
    if (generating) return
    if (brandDirty && profileError) {
      toast.push('No pudimos cargar tu marca guardada — cerrá y reabrí el modal antes de editarla (para no pisarla).', { type: 'error' })
      return
    }
    setGenerating(true)
    try {
      if (brandDirty) {
        // Si el guardado de la marca falla, ABORTAR: el lote se congela con
        // el branding del server y no hay forma de regenerar el mismo link
        // (audit: el catch silencioso mandaba informes con la marca vieja).
        try {
          await api.patch('/advisor/profile', {
            display_name: brand.name.trim() || null,
            cnv_matricula: brand.matricula.trim() || null,
            logo_data: brand.logo ?? '',   // '' = borrar; data-URI = guardar
          })
        } catch (e) {
          // Mostrar el motivo real (audit del caso en prod: el genérico no
          // dejaba diagnosticar si era validación, red o deploy a medias).
          toast.push(`No se pudo guardar tu marca — no generé nada. ${e.message || 'Probá de nuevo.'}`, { type: 'error' })
          setGenerating(false)
          return
        }
      }
      const p = PERIODS.find(x => x.key === period)
      const body = {
        period_start: p.start, period_end: p.end,
        note: note.trim() || null,
        client_uids: allChecked ? null : [...checked],
      }
      const d = await api.post('/advisor/reports/generate', body)
      setResults(d.reports || [])
      if (!(d.reports || []).length) toast.push('No se generó ningún informe — revisá que haya clientes con datos', { type: 'error' })
    } catch (e) {
      toast.push(e.message || 'No se pudieron generar los informes', { type: 'error' })
    } finally {
      setGenerating(false)
    }
  }

  const copy = async (text, msg) => {
    try { await navigator.clipboard.writeText(text); toast.push(msg) }
    catch { toast.push('No se pudo copiar', { type: 'error' }) }
  }

  const inputCls = 'w-full bg-bg-2 border border-line rounded-md px-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-data-violet transition-colors'

  // ── Resultados ──
  if (results) {
    const p = PERIODS.find(x => x.key === period)
    return (
      <Modal title={`${results.length} informe${results.length === 1 ? '' : 's'} listo${results.length === 1 ? '' : 's'} · ${p?.label ?? ''} (${p?.start} → ${p?.end})`} onClose={onClose} wide>
        <p className="text-xs text-ink-2 mb-3">
          Cada informe quedó congelado con su link — lo que le mandás al cliente no cambia después.
          El texto de WhatsApp ya tiene sus números y el link al final.
        </p>
        <div className="border border-line/60 rounded-lg divide-y divide-line/40 max-h-80 overflow-y-auto">
          {results.map(r => (
            <div key={r.report_id} className="flex items-center gap-2 px-3 py-2.5 flex-wrap">
              <span className="text-sm font-medium text-ink-0 min-w-[110px]">{r.label}</span>
              {!r.has_data && (
                <span className="text-[10px] text-rendi-warn bg-rendi-warn/10 rounded px-1.5 py-0.5">sin datos del período</span>
              )}
              <div className="ml-auto flex items-center gap-1.5">
                <button type="button" onClick={() => copy(r.url, 'Link copiado')}
                  className="text-[11px] font-semibold text-data-violet border border-data-violet/30 hover:bg-data-violet/10 rounded-md px-2.5 py-1.5 transition-colors">
                  Copiar link
                </button>
                <button type="button" onClick={() => copy(r.wa_text, 'Texto copiado — pegalo en WhatsApp')}
                  className="text-[11px] font-medium text-ink-2 hover:text-ink-0 border border-line rounded-md px-2.5 py-1.5 transition-colors">
                  Texto WhatsApp
                </button>
                <a href={r.url} target="_blank" rel="noopener noreferrer"
                  className="text-[11px] font-medium text-ink-2 hover:text-ink-0 border border-line rounded-md px-2.5 py-1.5 transition-colors inline-flex items-center gap-1">
                  Abrir <ExternalLink size={10} strokeWidth={2} />
                </a>
              </div>
            </div>
          ))}
        </div>
        <div className="flex justify-end pt-3">
          <button type="button" onClick={onClose} className={btnPrimary}>Listo</button>
        </div>
      </Modal>
    )
  }

  return (
    <Modal title="Informe del período" onClose={onClose}>
      <div className="space-y-3">
        <div>
          <p className="text-xs text-ink-2 mb-1.5">Período</p>
          <div className="flex gap-1.5">
            {PERIODS.map(p => (
              <button key={p.key} type="button" onClick={() => setPeriod(p.key)}
                className={`text-[12px] font-medium rounded-md px-3 py-1.5 border transition-colors ${
                  period === p.key ? 'text-data-violet border-data-violet/40 bg-data-violet/10' : 'text-ink-2 border-line hover:text-ink-0'
                }`}>
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="text-xs text-ink-2 mb-1.5">¿Para quién?</p>
          <div className="border border-line rounded-md max-h-44 overflow-y-auto divide-y divide-line/40">
            <label className="flex items-center gap-2.5 px-3 py-2 text-[12.5px] font-semibold text-ink-0 cursor-pointer hover:bg-bg-2/50">
              <input type="checkbox" className="accent-[#8B7DFF]" checked={!!allChecked}
                     onChange={toggleAll} />
              Todos {clients ? `(${clients.length})` : ''}
            </label>
            {(clients || []).map(c => (
              <label key={c.client_uid} className="flex items-center gap-2.5 px-3 py-2 text-[12.5px] text-ink-1 cursor-pointer hover:bg-bg-2/50">
                <input type="checkbox" className="accent-[#8B7DFF]"
                       checked={!!checked?.has(c.client_uid)}
                       onChange={() => toggleOne(c.client_uid)} />
                <span className="truncate">{c.label}</span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <p className="text-xs text-ink-2 mb-1.5">Nota personal (va arriba del informe, igual para todos)</p>
          <textarea rows={3} className={inputCls + ' resize-y'} value={note} maxLength={1200}
            onChange={e => setNote(e.target.value)}
            placeholder="Ej: Mes tranquilo y positivo. En agosto vencen los cupones del AL30 — lo hablamos el martes." />
        </div>

        <div className="border-t border-line/40 pt-3">
          <p className="text-xs text-ink-2 mb-1.5">Tu marca en el informe</p>
          <div className="grid grid-cols-2 gap-2">
            <input className={inputCls} value={brand.name} maxLength={80}
              onChange={e => { setBrand({ ...brand, name: e.target.value }); setBrandDirty(true) }}
              placeholder="Nombre / estudio" />
            <input className={inputCls} value={brand.matricula} maxLength={40}
              onChange={e => { setBrand({ ...brand, matricula: e.target.value }); setBrandDirty(true) }}
              placeholder="Matrícula CNV (opcional)" />
          </div>
          <div className="mt-2 flex items-center gap-3">
            {brand.logo ? (
              <img src={brand.logo} alt="Logo" className="h-9 max-w-[120px] object-contain rounded bg-white/90 p-0.5" />
            ) : (
              <span className="text-[11px] text-ink-3">Sin logo — el informe usa tus iniciales</span>
            )}
            <label className="text-[11.5px] font-medium text-data-violet border border-data-violet/30 hover:bg-data-violet/10 rounded-md px-2.5 py-1.5 cursor-pointer transition-colors">
              {brand.logo ? 'Cambiar logo' : 'Subir logo'}
              <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
                onChange={e => { onLogoFile(e.target.files?.[0]); e.target.value = '' }} />
            </label>
            {brand.logo && (
              <button type="button" onClick={() => { setBrand(b => ({ ...b, logo: null })); setBrandDirty(true) }}
                className="text-[11.5px] text-ink-3 hover:text-ink-1 transition-colors">
                Quitar
              </button>
            )}
          </div>
          <p className="text-[10.5px] text-ink-3 mt-1.5">
            PNG o JPG, ideal con fondo transparente y formato apaisado (ej. 600×200 px) — lo achicamos solo.
          </p>
        </div>

        <p className="text-[11px] text-ink-3 leading-relaxed">
          El informe muestra el resultado del período separado en mercado vs. aportes,
          neto de comisiones, con la comparación contra el dólar MEP — y tu marca arriba.
          Rendi aparece solo en el pie.
        </p>

        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="text-xs text-ink-2 hover:text-ink-0 px-3 py-2 transition-colors">Cancelar</button>
          <button type="button" onClick={generate}
                  disabled={generating || clients === null || !checked?.size} className={btnPrimary}>
            <FileText size={13} strokeWidth={1.75} />
            {generating ? 'Generando…'
              : `Generar ${checked?.size ?? 0} informe${(checked?.size ?? 0) === 1 ? '' : 's'}`}
          </button>
        </div>
      </div>
    </Modal>
  )
}
