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

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { PhoneCall, Landmark, TrendingUp, TrendingDown, Users, ArrowRight, LineChart } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Skeleton from '../components/Skeleton'
import { api } from '../utils/api'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { usd } from '../utils/format'

// usd() formatea negativos con paréntesis — para deltas del libro queremos ±.
const signedUsd = (n) => (n >= 0 ? `+${usd(n, 0)}` : `−${usd(Math.abs(n), 0)}`)
const signedPct = (n) => (n >= 0 ? `+${n}%` : `${n}%`)

export default function AdvisorDashboard() {
  const navigate = useNavigate()
  const { enterClient } = useAdvisorContext()
  const [book, setBook] = useState(null)     // null = cargando
  const [history, setHistory] = useState(null)  // serie AUM (evolución del libro)
  const [error, setError] = useState(false)

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
    } catch {
      setHistory(prev => prev ?? [])
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
      />

      {error && (
        <div className="mb-4 text-[12px] text-ink-2 bg-bg-1 border border-line/60 rounded-md px-3 py-2">
          No pudimos calcular el resumen recién{book ? ' — estás viendo la última versión' : ''}. Recargá la página para reintentar.
        </div>
      )}

      {book === null ? (
        <div className="space-y-3">
          <Skeleton className="h-28 rounded-xl" />
          <Skeleton className="h-24 rounded-xl" />
        </div>
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
          <BookEvolution series={history} />
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
  if (!aum || aum.clients === 0) return null
  const hasAum = aum.total_usd != null
  return (
    <div className="bg-bg-1 border border-line/60 rounded-xl p-5 mb-4">
      <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
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

// ─── Evolución del capital administrado (idea de Nico) ──────────────────────
// La MISMA anatomía que el gráfico de evolución del dashboard personal:
// línea violeta = total administrado, punteada gris = plata aportada neta.
// La brecha entre las dos ES el efecto mercado — se ve a ojo si el libro
// sube porque los clientes ganan o porque entra plata/gente nueva.

const EVO_RANGES = [
  { key: '1M', days: 30 }, { key: '3M', days: 90 }, { key: '6M', days: 180 },
  { key: '1A', days: 365 }, { key: 'Todo', days: 99999 },
]

function BookEvolution({ series }) {
  const [range, setRange] = useState('3M')

  const visible = useMemo(() => {
    if (!series?.length) return []
    const days = EVO_RANGES.find(r => r.key === range)?.days ?? 90
    const cutoff = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10)
    return series.filter(p => p.date >= cutoff)
  }, [series, range])

  // Descomposición del período visible: ΔAUM = flujos (Δaportado) + mercado.
  const delta = useMemo(() => {
    if (visible.length < 2) return null
    const a = visible[0], b = visible[visible.length - 1]
    const dAum = b.aum_usd - a.aum_usd
    const dFlows = b.net_deposited_usd - a.net_deposited_usd
    return { market: dAum - dFlows, flows: dFlows, clients: b.clients - a.clients }
  }, [visible])

  if (series === null) return <Skeleton className="h-56 rounded-xl mb-4" />
  if (!series.length || visible.length < 2) {
    return (
      <div className="bg-bg-1 border border-line/60 rounded-xl p-4 mb-4">
        <h2 className="flex items-center gap-2 text-[13px] font-semibold text-ink-0 mb-1">
          <LineChart size={13} strokeWidth={1.75} className="text-data-violet" />
          Evolución del capital administrado
        </h2>
        <p className="text-[11.5px] text-ink-3">
          Se dibuja solo con los snapshots nocturnos — con un par de días de
          historia ya vas a ver la curva (y si el libro sube por el mercado o
          porque entra plata nueva).
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
            <button key={r.key} type="button" onClick={() => setRange(r.key)}
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
            : <p className="text-[11.5px] text-ink-3 py-1.5">Ningún activo en rojo — bien ahí.</p>}
        </div>
        <div>
          <p className="flex items-center gap-1.5 text-[11px] text-rendi-pos font-medium mb-1">
            <TrendingUp size={11} strokeWidth={2} /> Le hace ganar a más clientes
          </p>
          {star.winners.length
            ? star.winners.map((r) => <Row key={r.asset} r={r} tone="green" />)
            : <p className="text-[11.5px] text-ink-3 py-1.5">Todavía nada en verde.</p>}
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
      <p className="text-[10.5px] text-ink-3 mt-2">Retorno total vs. aportado, del último snapshot.</p>
    </div>
  )
}
