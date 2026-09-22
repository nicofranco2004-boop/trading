// AdvisorCobros — el calendario de cobros de TODOS los clientes del asesor.
// ═══════════════════════════════════════════════════════════════════════════
// Pedido de un tester del plan asesor (2026-09-20): "cashflow agrupado de
// clientes". Cupones, amortizaciones y vencimientos de los bonos y letras que
// tienen sus clientes, en un solo calendario, con quién cobra cuánto.
//
// Data: POST /advisor/cashflows/positions → qué renta fija tiene cada cliente
// elegido. El cronograma NO viene del servidor: lo arma el navegador con el
// mismo motor que la Cartera (`utils/aggregateCashflows.js` sobre
// `bondSchedule.js`), así que un cupón vale lo mismo acá y en la cuenta del
// cliente. Sólo lectura: acá no se registra ningún cobro.
import { useEffect, useMemo, useState } from 'react'
import { CalendarDays, Users } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import Skeleton from '../components/Skeleton'
import ClientPicker from '../components/advisor/ClientPicker'
import { api } from '../utils/api'
import { useCerSeries } from '../hooks/useCerSeries'
import { aggregateCashflows, groupDaysByMonth } from '../utils/aggregateCashflows'
import { formatRelativeDate } from '../utils/upcomingEvents'
import { usd, ars } from '../utils/format'
import { hoyISO } from '../utils/fecha'

const RANGES = [
  { value: '30d',  label: '30 días' },
  { value: '90d',  label: '90 días' },
  { value: 'year', label: 'Este año' },
]
const KIND_LABEL = {
  cupon: 'cupón', amort: 'amortización', 'cupon+amort': 'cupón + amortización', vencimiento: 'vencimiento',
}
// Dos motivos distintos para marcar un monto como estimado, y conviene que se
// note cuál es: el del CER depende de un índice que todavía no se publicó; el de
// una letra, del precio de mercado de hoy.
const ESTIMADO_LABEL = { cer: 'estimado con CER', letra: 'estimado al mercado' }
const ESTIMADO_AYUDA = {
  cer: 'El cupón se ajusta por CER y el índice de esa fecha todavía no existe: se proyecta con el último publicado.',
  letra: 'Una letra devuelve el capital más el interés que capitalizó. El monto se estima con el precio de mercado de hoy y su tasa mensual, así que se mueve con el mercado.',
}
const MES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
             'septiembre', 'octubre', 'noviembre', 'diciembre']

export default function AdvisorCobros() {
  const [data, setData] = useState(null)      // respuesta del servidor (todo el libro)
  const [error, setError] = useState(false)
  const [selected, setSelected] = useState(null)   // Set de client_uid; null hasta cargar
  const [range, setRange] = useState('90d')
  // La serie CER sólo hace falta si algún cliente tiene un bono CER; el hook ya
  // cachea por sesión, así que pedirla siempre es barato.
  const { series: cerSeries } = useCerSeries(true)

  useEffect(() => {
    let cancelled = false
    api.post('/advisor/cashflows/positions', {})
      .then(d => {
        if (cancelled) return
        setData(d)
        setSelected(new Set((d.clients || []).map(c => c.client_uid)))
      })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [])

  const today = hoyISO()
  const result = useMemo(() => {
    if (!data || !selected) return null
    const clients = (data.clients || []).filter(c => selected.has(c.client_uid))
    const positions = (data.positions || []).filter(p => selected.has(p.client_uid))
    return aggregateCashflows(positions, clients, {
      today, range, tcMep: data.tc_mep, cerSeries, letras: data.letras,
    })
  }, [data, selected, range, cerSeries, today])

  const months = useMemo(() => result ? groupDaysByMonth(result.days) : [], [result])
  const conRf = new Set((data?.positions || []).map(p => p.client_uid))

  return (
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Plan Asesor"
        title="Cobros de tus clientes"
        subtitle="Cupones, amortizaciones y vencimientos de los bonos y letras que tienen tus clientes, en un solo calendario. Cada cobro dice de quién es y cuánto le entra."
        meta={data?.fx_date ? `Dólar MEP del ${fechaCorta(data.fx_date)}` : undefined}
      />

      {error && (
        <div className="mb-4 text-[12px] text-ink-2 bg-bg-1 border border-line/60 rounded px-3 py-2">
          No pudimos cargar las tenencias de tus clientes. Recargá la página para reintentar.
        </div>
      )}

      {/* Toolbar: clientes + rango */}
      <Panel padding="sm" className="mb-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5">
          <div className="min-w-0">
            {data
              ? <ClientPicker clients={data.clients} selected={selected} onChange={setSelected}
                              hint={c => conRf.has(c.client_uid) ? null : 'sin renta fija'} />
              : <Skeleton className="h-8 w-44" />}
          </div>
          <div className="inline-flex border border-line rounded-lg overflow-hidden ml-auto" role="radiogroup" aria-label="Rango">
            {RANGES.map(r => (
              <button key={r.value} type="button" role="radio" aria-checked={range === r.value}
                onClick={() => setRange(r.value)}
                className={`text-[12.5px] px-3 py-1.5 transition-colors ${
                  range === r.value ? 'bg-bg-3 text-ink-0 font-semibold' : 'text-ink-2 hover:text-ink-0'}`}>
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </Panel>

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
        <Kpi label="Próximos 30 días" value={result ? `US$ ${usd(result.totals.usd30, 0)}` : null}
             sub={result ? `${plural(result.totals.count30, 'cobro', 'cobros')}` : null} />
        <Kpi label={`Próximos ${labelRango(range)}`} value={result ? `US$ ${usd(result.totals.usdRange, 0)}` : null}
             sub={result ? `${plural(result.totals.countRange, 'cobro', 'cobros')} · ${plural(result.byClient.length, 'cliente', 'clientes')}` : null} />
        <Kpi label="Sin cobros en el período"
             value={result ? plural(result.clientesSinCobros.length, 'cliente', 'clientes') : null}
             sub={result && result.clientesSinCobros.length > 0
               ? result.clientesSinCobros.slice(0, 3).map(c => c.label).join(', ') + (result.clientesSinCobros.length > 3 ? '…' : '')
               : result ? 'Todos los elegidos tienen algo por cobrar' : null} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_320px] gap-4 items-start">
        {/* Calendario */}
        <div className="space-y-3">
          {!result && [...Array(3)].map((_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}
          {result && months.length === 0 && (
            <div className="border border-dashed border-line rounded-xl p-10 text-center">
              <CalendarDays size={22} strokeWidth={1.5} className="mx-auto text-ink-3 mb-2" />
              <p className="text-[13.5px] text-ink-1">Ningún cobro en {labelRango(range)} para los clientes elegidos.</p>
              <p className="text-[12px] text-ink-3 mt-1">Probá con un rango más largo, o revisá que tengan bonos o letras cargados.</p>
            </div>
          )}
          {months.map(m => (
            <Panel key={m.ym} padding="none" as="section" aria-label={labelMes(m.ym)}>
              <div className="flex items-baseline justify-between px-4 py-3 border-b border-line">
                <h2 className="text-[14px] font-semibold text-ink-0">{labelMes(m.ym)}</h2>
                <span className="text-[13px] font-semibold text-rendi-pos tabular">US$ {usd(m.totalUsd, 0)}</span>
              </div>
              {m.days.map(d => (
                <div key={d.date} className="grid grid-cols-[64px_minmax(0,1fr)] gap-x-3.5 px-4 py-2.5 border-b border-line last:border-b-0">
                  <div className="leading-tight">
                    <div className="text-[13px] font-semibold text-ink-0 tabular">{diaCorto(d.date)}</div>
                    <div className="text-[11.5px] text-ink-3">{formatRelativeDate(d.date, today)}</div>
                    {d.note && <div className="text-[10.5px] text-ink-3 mt-0.5 leading-snug">{d.note}</div>}
                  </div>
                  <div>
                    {d.payments.map(p => <PaymentRow key={p.asset} p={p} />)}
                  </div>
                </div>
              ))}
            </Panel>
          ))}
          {result && result.sinCronograma.length > 0 && (
            <p className="text-[11.5px] text-ink-3 px-1">
              Sin cronograma conocido, no entran al calendario: {result.sinCronograma.join(', ')}.
            </p>
          )}
        </div>

        {/* Por cliente */}
        <Panel padding="none" as="aside" aria-label="Por cliente">
          <h3 className="px-4 py-3 text-[13px] font-semibold text-ink-0 border-b border-line flex items-center gap-2">
            <Users size={14} strokeWidth={1.75} className="text-ink-2" /> Por cliente · {labelRango(range)}
          </h3>
          {!result && <div className="p-4 space-y-2">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-9" />)}</div>}
          {result && result.byClient.length === 0 && (
            <p className="px-4 py-4 text-[12.5px] text-ink-3">Nadie cobra nada en este período.</p>
          )}
          {result && result.byClient.map((c, i, arr) => {
            const max = arr[0]?.totalUsd || 1
            return (
              <div key={c.client_uid} className="px-4 py-2.5 border-b border-line last:border-b-0">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[13px] font-medium text-ink-0 truncate">{c.label}</span>
                  <span className="text-[13px] font-semibold text-ink-0 tabular whitespace-nowrap">US$ {usd(c.totalUsd, 0)}</span>
                </div>
                <div className="text-[11.5px] text-ink-3 truncate">{plural(c.count, 'cobro', 'cobros')} · {c.assets.join(', ')}</div>
                <div className="h-[3px] bg-bg-3 rounded-xs mt-1.5 overflow-hidden">
                  <i className="block h-full bg-data-violet" style={{ width: `${Math.max(2, Math.round(c.totalUsd / max * 100))}%` }} />
                </div>
              </div>
            )
          })}
          <p className="text-[11.5px] text-ink-3 px-4 py-3 border-t border-line leading-snug">
            Los montos en pesos se muestran al dólar MEP de hoy y cambian con la cotización. Los cupones CER se estiman con el último índice publicado, y las letras —que devuelven el capital con el interés capitalizado— con su precio de mercado de hoy.
          </p>
        </Panel>
      </div>
    </div>
  )
}

function PaymentRow({ p }) {
  const esArs = p.payCurrency === 'ARS'
  return (
    <div className="py-1 border-t border-dashed border-line first:border-t-0">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3.5 items-start">
        <div className="min-w-0">
          <span className="text-[12.5px] font-semibold text-ink-0 tabular">{p.asset}</span>
          <span className={`text-[11px] ml-1.5 ${p.kind === 'cupon' ? 'text-ink-2' : 'text-data-cyan'}`}>{KIND_LABEL[p.kind] || p.kind}</span>
          {p.estimated && (
            <span className="text-[10.5px] ml-1.5 px-1.5 py-px rounded-xs text-rendi-warn bg-rendi-warn/10"
                  title={ESTIMADO_AYUDA[p.estimateKind] || undefined}>
              {ESTIMADO_LABEL[p.estimateKind] || 'estimado'}
            </span>
          )}
        </div>
        <div className="text-right whitespace-nowrap leading-tight">
          {p.totalUsd != null
            ? <div className="text-[13px] font-semibold text-rendi-pos tabular">US$ {usd(p.totalUsd, 0)}</div>
            : <div className="text-[13px] font-semibold text-rendi-pos tabular">ARS {ars(p.totalNative)}</div>}
          {esArs && p.totalUsd != null && (
            <div className="text-[10.5px] text-ink-3 tabular">ARS {ars(p.totalNative)} · al dólar de hoy</div>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-1 mt-1">
        {p.holders.map(h => (
          <span key={h.client_uid} className="text-[11.5px] text-ink-1 bg-bg-2 rounded-full px-2 py-px tabular">
            {h.label} <span className="text-ink-2">· {h.amountUsd != null ? `US$ ${usd(h.amountUsd, 0)}` : `ARS ${ars(h.amountNative)}`}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function Kpi({ label, value, sub }) {
  return (
    <Panel padding="md">
      <div className="text-[12px] text-ink-2">{label}</div>
      {value == null
        ? <Skeleton className="h-7 w-28 mt-1" />
        : <div className="text-[22px] font-semibold text-ink-0 tracking-tight tabular mt-0.5">{value}</div>}
      {sub && <div className="text-[12px] text-ink-2 mt-0.5 truncate">{sub}</div>}
    </Panel>
  )
}

function plural(n, uno, varios) { return `${n} ${n === 1 ? uno : varios}` }
function labelRango(r) { return r === '30d' ? '30 días' : r === '90d' ? '90 días' : 'este año' }
function labelMes(ym) { const [y, m] = ym.split('-'); return `${MES[Number(m) - 1][0].toUpperCase()}${MES[Number(m) - 1].slice(1)} ${y}` }
function diaCorto(iso) {
  const d = new Date(iso + 'T00:00:00')
  const wd = d.toLocaleDateString('es-AR', { weekday: 'short' }).replace('.', '')
  return `${wd[0].toUpperCase()}${wd.slice(1)} ${d.getDate()}`
}
function fechaCorta(iso) {
  const d = new Date(iso + 'T00:00:00')
  return `${d.getDate()}/${d.getMonth() + 1}`
}
