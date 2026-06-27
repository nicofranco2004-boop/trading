import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Target, Plus, Pencil, Trash2, TrendingUp, Calendar, DollarSign, CheckCircle2, AlertTriangle, Compass, Zap, ArrowRight } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine, Legend } from 'recharts'
import Modal from '../components/Modal'
import DateInput from '../components/DateInput'
import PageHeader from '../components/PageHeader'
import EmptyState from '../components/EmptyState'
import { PageSkeleton } from '../components/Skeleton'
import InfoTooltip from '../components/InfoTooltip'
import { useToast } from '../components/Toast'
import { usd, fmtUsd } from '../utils/format'
import { priceSymbol, computeBrokerValue, isArUsdBroker } from '../utils/valuation'
import { api } from '../utils/api'
import { pickFinancialRate, useCurrency } from '../contexts/CurrencyContext'
import AskAIAbout from '../components/ai/AskAIAbout'

const PRESETS = [
  { label: 'Conservador', pct: 6, hint: 'Bonos y exposición pasiva al S&P' },
  { label: 'Moderado', pct: 10, hint: 'Promedio histórico del S&P 500' },
  { label: 'Agresivo', pct: 15, hint: 'Acciones de crecimiento y cripto' },
]

const today = () => new Date().toISOString().slice(0, 10)
const addYears = (years) => {
  const d = new Date()
  d.setFullYear(d.getFullYear() + years)
  return d.toISOString().slice(0, 10)
}

export default function Goals() {
  const [goals, setGoals] = useState([])
  const [cagr, setCagr] = useState(null)
  const [currentValue, setCurrentValue] = useState(0)
  const [loading, setLoading] = useState(true)
  const [modal, setModal] = useState(null) // 'add' | 'edit' | null
  const [form, setForm] = useState({ id: null, target_usd: '', target_date: addYears(1), expected_return_pct: 10, label: '' })
  const { valuationDollar } = useCurrency()
  const toast = useToast()

  // valuationDollar en deps: al cambiar MEP/CCL, recomputar valor actual + proyecciones.
  useEffect(() => { loadAll() }, [valuationDollar])

  async function loadAll() {
    setLoading(true)
    try {
      const [gs, c, positions, brokers, dolar, prices] = await Promise.all([
        api.get('/goals'),
        api.get('/goals/cagr').catch(() => null),
        api.get('/positions'),
        api.get('/brokers'),
        api.get('/dolar').catch(() => null),
        // prices loaded after we know symbols
      ])
      setGoals(gs)
      setCagr(c)

      // Calcular valor actual del portfolio (USD) — usar computeBrokerValue (única
      // fuente de verdad), igual que Positions.jsx / Insights.jsx. Así CEDEARs y
      // sub-brokers "· USD" se valúan por su precio LOCAL .BA ÷ dólar-MEP, no por el
      // ticker US (que estaría órdenes de magnitud mal).
      const tcBlue = pickFinancialRate(dolar, valuationDollar) || 1415
      // dólar-MEP (la plata local) para valuar CEDEARs/acciones AR en USD.
      const tcCedear = pickFinancialRate(dolar, valuationDollar) || tcBlue
      const tcCripto = dolar?.cripto?.venta
      const arsBrokers = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
      const usdtBrokers = new Set(brokers.filter(b => b.currency !== 'ARS').map(b => b.name))
      // Símbolos a pedir: ARS y sub-brokers "· USD" piden el .BA (BYMA); brokers USD
      // reales piden el ticker US pelado. Espejo de fetchPrices() en Positions.jsx.
      const arsSyms = [...new Set(positions.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => priceSymbol(p.asset, true, p.asset_type)))]
      const usdtSyms = [...new Set(positions.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => isArUsdBroker(p.broker) ? priceSymbol(p.asset, true, p.asset_type) : priceSymbol(p.asset, false, p.asset_type)))]
      const all = [...arsSyms, ...usdtSyms].join(',')
      let pr = {}
      if (all) {
        try { pr = await api.get(`/prices?symbols=${all}`) } catch {}
      }
      const val = brokers.reduce(
        (s, b) => s + computeBrokerValue(positions, pr, b, tcBlue, tcCedear, tcCripto).value,
        0
      )
      setCurrentValue(val)
    } finally {
      setLoading(false)
    }
  }

  function openAdd() {
    setForm({ id: null, target_usd: '', target_date: addYears(1), expected_return_pct: cagr?.cagr ?? 10, label: '' })
    setModal('add')
  }
  function openEdit(g) {
    setForm({
      id: g.id,
      target_usd: g.target_usd,
      target_date: g.target_date,
      expected_return_pct: g.expected_return_pct,
      label: g.label || '',
    })
    setModal('edit')
  }

  async function save() {
    if (!form.target_usd || !form.target_date) return
    const body = {
      target_usd: +form.target_usd,
      target_date: form.target_date,
      expected_return_pct: +form.expected_return_pct,
      label: form.label || null,
    }
    try {
      if (modal === 'edit') {
        await api.put(`/goals/${form.id}`, body)
      } else {
        await api.post('/goals', body)
      }
      setModal(null)
      loadAll()
    } catch (e) {
      toast.push('Ocurrió un error: ' + e.message, { type: 'error' })
    }
  }

  async function del(id) {
    if (!confirm('¿Eliminar este objetivo? La acción no se puede deshacer.')) return
    await api.delete(`/goals/${id}`)
    loadAll()
  }

  if (loading) return <PageSkeleton />

  return (
    <div className="page-shell space-y-6">
      <PageHeader
        title="Objetivos"
        subtitle="Definí tus metas financieras y proyectá el camino para alcanzarlas."
        action={
          <button
            onClick={openAdd}
            className="flex items-center gap-1.5 text-sm px-3 py-2 bg-rendi-accent text-white hover:bg-rendi-accent/90 rounded-md font-semibold transition-colors"
          >
            <Plus size={14} /> Nuevo objetivo
          </button>
        }
      />

      {/* CAGR card */}
      <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl p-5">
        <div className="flex items-center gap-1.5 mb-2">
          <TrendingUp size={16} className="text-ink-3" />
          <h2 className="font-semibold text-ink-0">Rendimiento histórico (CAGR)</h2>
          <InfoTooltip>
            <p className="font-semibold text-ink-0">Qué es</p>
            <p>
              <span className="font-medium">Tasa de crecimiento anual compuesto</span> (CAGR) — expresa tu rendimiento total como una tasa fija por año.
            </p>
            <div className="border-t border-line/60 my-1.5" />
            <p className="font-semibold text-ink-0">Para qué sirve</p>
            <p className="text-ink-3">
              Comparar tu performance contra otras inversiones en la misma unidad (% por año): plazos fijos, S&P 500, inflación INDEC, FCIs.
            </p>
            <p className="text-ink-3">
              Distinto al <span className="font-medium">retorno total acumulado</span> que ves en el Dashboard, que muestra la ganancia desde el inicio sin anualizar.
            </p>
            <div className="border-t border-line/60 my-1.5" />
            <p className="font-semibold text-ink-0">Cómo se calcula</p>
            <p className="text-ink-3">
              Con <span className="font-medium">TWR</span> (rendimiento ajustado por flujos) — neutraliza el efecto de tus aportes y retiros para que solo veas la performance pura del mercado sobre tu capital.
            </p>
          </InfoTooltip>
        </div>
        {cagr?.cagr != null ? (
          <p className="text-sm text-ink-2">
            Basado en {cagr.months} {cagr.months === 1 ? 'mes' : 'meses'} cargados:
            <span className={`ml-2 text-2xl font-bold ${cagr.cagr >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>
              {cagr.cagr >= 0 ? '+' : ''}{cagr.cagr.toFixed(2)}%
            </span>
            <span className="text-xs text-ink-3 ml-2">anualizado (TWR)</span>
          </p>
        ) : (
          <p className="text-sm text-ink-3">
            {cagr?.reason || 'Cargá al menos 2 meses en el Resumen Mensual para calcular tu CAGR real.'}
          </p>
        )}
        <p className="text-xs text-ink-3 mt-2">
          Capital actual estimado · <span className="font-medium text-ink-1">{fmtUsd(currentValue)}</span>
        </p>
      </div>

      {/* Goals list */}
      {goals.length === 0 ? (
        <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl">
          <EmptyState
            icon={<Target size={20} />}
            title="Sin objetivos definidos"
            description="Creá tu primer objetivo (por ejemplo, USD 8.000 en 1 año) y vamos a calcular cuánto necesitás aportar por mes para alcanzarlo."
            action={
              <button onClick={openAdd} className="inline-flex items-center gap-1.5 text-sm bg-rendi-accent text-white hover:bg-rendi-accent/90 px-3 py-2 rounded-md font-semibold transition">
                <Plus size={14} /> Crear primer objetivo
              </button>
            }
          />
        </div>
      ) : (
        <div className="space-y-4">
          {goals.map(g => (
            <GoalCard
              key={g.id}
              goal={g}
              currentValue={currentValue}
              userCagr={cagr?.cagr}
              onEdit={() => openEdit(g)}
              onDelete={() => del(g.id)}
            />
          ))}
        </div>
      )}

      {modal && (
        <Modal title={modal === 'edit' ? 'Editar objetivo' : 'Nuevo objetivo'} onClose={() => setModal(null)}>
          <GoalForm form={form} setForm={setForm} cagr={cagr?.cagr} onSave={save} onCancel={() => setModal(null)} />
        </Modal>
      )}
    </div>
  )
}

function GoalCard({ goal, currentValue, userCagr, onEdit, onDelete }) {
  const target = goal.target_usd
  const r = goal.expected_return_pct / 100  // anual
  const targetDate = new Date(goal.target_date)
  const now = new Date()
  const monthsLeft = Math.max(0, Math.round((targetDate - now) / (1000 * 60 * 60 * 24 * 30.4375)))
  const yearsLeft = monthsLeft / 12

  // Cuánto necesitás aportar/mes para llegar al target
  // FV = PV*(1+r/12)^n + PMT*((1+r/12)^n - 1)/(r/12)
  // PMT = (FV - PV*(1+r/12)^n) / (((1+r/12)^n - 1) / (r/12))
  const monthly = monthsLeft > 0 ? requiredMonthly(currentValue, target, r, monthsLeft) : null

  // Cuál sería tu valor final SIN aportes, solo rindiendo
  const noContribValue = currentValue * Math.pow(1 + r, yearsLeft)
  // Qué % anual necesitás SIN aportes
  const requiredReturnNoContrib = yearsLeft > 0 && currentValue > 0
    ? (Math.pow(target / currentValue, 1 / yearsLeft) - 1) * 100
    : null

  // Trayectoria mensual ideal (con aportes mensuales del valor calculado)
  // Usamos tasa mensual EQUIVALENTE a la efectiva anual para consistencia
  const trajectory = []
  let acc = currentValue
  const rMonthly = Math.pow(1 + r, 1 / 12) - 1
  for (let m = 0; m <= monthsLeft; m++) {
    trajectory.push({
      mes: m,
      ideal: +acc.toFixed(2),
      target: target,
    })
    acc = acc * (1 + rMonthly) + (monthly || 0)
  }

  const progressPct = target > 0 ? Math.min(100, (currentValue / target) * 100) : 0
  const reached = currentValue >= target

  return (
    <AskAIAbout
      topic="goal"
      params={{ goal_id: goal.id }}
      subtitle={goal.label || `Objetivo · $${usd(target)}`}
    >
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl p-5">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-ink-0 text-lg">
              {goal.label || `$${usd(target)}`}
            </h3>
            {reached && <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 font-semibold"><CheckCircle2 size={12} /> Alcanzado</span>}
          </div>
          <p className="text-xs text-ink-3 mt-1">
            <DollarSign size={11} className="inline -mt-0.5" /> ${usd(target)} ·
            <Calendar size={11} className="inline -mt-0.5 ml-2" /> {goal.target_date} ({monthsLeft} {monthsLeft === 1 ? 'mes' : 'meses'}) ·
            <TrendingUp size={11} className="inline -mt-0.5 ml-2" /> {goal.expected_return_pct}% anual
          </p>
        </div>
        <div className="flex gap-1">
          <button onClick={onEdit} className="text-ink-3 hover:text-ink-1 dark:hover:text-ink-0 p-1" title="Editar objetivo" aria-label={`Editar objetivo ${goal.name || ''}`}><Pencil size={14} aria-hidden="true" /></button>
          <button onClick={onDelete} className="text-ink-3 hover:text-rendi-neg p-1" title="Eliminar objetivo" aria-label={`Eliminar objetivo ${goal.name || ''}`}><Trash2 size={14} aria-hidden="true" /></button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs text-ink-3 mb-1">
          <span>${usd(currentValue)}</span>
          <span className="font-medium">{progressPct.toFixed(1)}%</span>
          <span>${usd(target)}</span>
        </div>
        <div className="h-2 bg-bg-2 dark:bg-bg-2 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-[width] duration-300 ease-out motion-reduce:transition-none ${reached ? 'bg-rendi-pos' : 'bg-rendi-accent'}`}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {/* Cómo llegar — escenarios principales */}
      {!reached && monthsLeft > 0 && (
        <>
          <p className="text-xs uppercase tracking-wider font-semibold text-ink-3 mt-2 mb-2">Cómo llegar</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
            <Scenario
              title="Con aportes mensuales"
              value={monthly != null ? `${fmtUsd(monthly)} / mes` : '—'}
              sub={`Aporte mensual necesario para alcanzar la meta asumiendo ${goal.expected_return_pct}% anual.`}
            />
            <Scenario
              title="Solo con rendimiento"
              value={requiredReturnNoContrib != null ? `${requiredReturnNoContrib.toFixed(1)}% anual` : '—'}
              sub="Rendimiento anual requerido para alcanzar la meta sin aportes adicionales."
              warn={requiredReturnNoContrib != null && userCagr != null && requiredReturnNoContrib > userCagr * 1.5}
            />
            <Scenario
              title="Sin aportes"
              value={fmtUsd(noContribValue)}
              sub={`Capital final proyectado en ${monthsLeft} ${monthsLeft === 1 ? 'mes' : 'meses'} con un rendimiento del ${goal.expected_return_pct}% anual.`}
            />
          </div>

          {/* Escenarios alternativos — Conservador / Histórico / Agresivo */}
          <p className="text-xs uppercase tracking-wider font-semibold text-ink-3 mt-2 mb-2">Escenarios alternativos</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {buildAltScenarios({ currentValue, target, monthsLeft, userCagr }).map(s => (
              <AltScenarioCard key={s.id} scenario={s} />
            ))}
          </div>
        </>
      )}

      {/* Chart trayectoria */}
      {!reached && trajectory.length > 1 && (
        <div className="mt-5">
          <p className="text-xs text-ink-3 mb-2">Proyección mes a mes con un aporte mensual de <span className="font-medium text-ink-1">{monthly != null ? fmtUsd(monthly) : 'USD 0'}</span> al {goal.expected_return_pct}% anual.</p>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={trajectory} margin={{ top: 5, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#334155" strokeOpacity={0.3} vertical={false} />
              <XAxis dataKey="mes" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `${v}m`} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `$${(v / 1000).toFixed(0)}k`} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
                labelStyle={{ color: '#f1f5f9' }}
                formatter={(v) => `$${usd(v)}`}
                labelFormatter={(l) => `Mes ${l}`}
              />
              <ReferenceLine y={target} stroke="#22c55e" strokeDasharray="4 4" label={{ value: 'Meta', fill: '#22c55e', fontSize: 11, position: 'right' }} />
              <Line type="monotone" dataKey="ideal" stroke="#4FFF78" strokeWidth={2.5} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Hint con userCagr — sin emojis, con tono direct */}
      {userCagr != null && !reached && (
        <div className={`mt-4 px-3 py-2 rounded-lg border text-xs leading-snug ${
          userCagr >= goal.expected_return_pct
            ? 'bg-emerald-500/[0.06] border-emerald-500/25 text-emerald-700 dark:text-emerald-300'
            : 'bg-amber-500/[0.06] border-amber-500/25 text-amber-700 dark:text-amber-300'
        }`}>
          {userCagr >= goal.expected_return_pct
            ? `Tu rendimiento histórico (${userCagr.toFixed(1)}%) supera al asumido (${goal.expected_return_pct}%). El plan está alineado.`
            : `Tu rendimiento histórico (${userCagr.toFixed(1)}%) se ubica por debajo del asumido (${goal.expected_return_pct}%). Conviene aumentar los aportes o revisar la meta.`}
        </div>
      )}

      {/* Sprint 7: Goal diagnostic + sugerencia accionable basada en behavioral */}
      <GoalDiagnostic goalId={goal.id} reached={reached} />
    </div>
    </AskAIAbout>
  )
}

function GoalDiagnostic({ goalId, reached }) {
  const [diag, setDiag] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (reached) return
    setLoading(true)
    setError(null)
    api.get(`/goals/${goalId}/diagnostic`)
      .then(setDiag)
      .catch(ex => setError(ex?.message))
      .finally(() => setLoading(false))
  }, [goalId, reached])

  if (reached || loading || error || !diag) return null
  if (diag.status === 'unknown') return null

  const STATUS_STYLE = {
    on_track: { tone: 'pos', label: 'En camino', Icon: CheckCircle2 },
    ahead:    { tone: 'pos', label: 'Adelantado', Icon: TrendingUp },
    behind:   { tone: 'warn', label: 'Atrasado', Icon: AlertTriangle },
    unreachable: { tone: 'neg', label: 'Inalcanzable al ritmo actual', Icon: AlertTriangle },
  }
  const meta = STATUS_STYLE[diag.status] || STATUS_STYLE.behind
  const { Icon } = meta
  const toneClasses = meta.tone === 'pos'
    ? 'bg-rendi-pos/[0.06] border-rendi-pos/25 text-rendi-pos'
    : meta.tone === 'warn'
    ? 'bg-rendi-warn/[0.06] border-rendi-warn/25 text-rendi-warn'
    : 'bg-rendi-neg/[0.06] border-rendi-neg/25 text-rendi-neg'

  return (
    <div className="mt-4 border border-line/60 rounded-lg bg-bg-2/40 overflow-hidden">
      <div className="flex items-start gap-2 px-3 py-2.5 border-b border-line/40">
        <Compass size={13} strokeWidth={1.75} className="text-ink-3 mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 leading-none mb-1.5">
            Diagnóstico
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-caps px-1.5 py-0.5 rounded-sm border ${toneClasses}`}>
              <Icon size={10} strokeWidth={1.75} /> {meta.label}
            </span>
            {diag.eta_months_at_current_rate != null && (
              <span className="text-[11px] font-mono uppercase tracking-caps text-ink-2">
                ETA · {diag.eta_months_at_current_rate} meses
              </span>
            )}
            {diag.required_annual_pct != null && (
              <span className="text-[11px] font-mono uppercase tracking-caps text-ink-2">
                Necesario · {diag.required_annual_pct.toFixed(1)}%/año
              </span>
            )}
          </div>
          <p className="text-xs text-ink-1 leading-relaxed mt-2">{diag.diagnostic}</p>
        </div>
      </div>

      {/* Sugerencia accionable basada en el sesgo dominante */}
      {diag.suggestion && (
        <div className="px-3 py-2.5 flex items-start gap-2 bg-bg-1">
          <Zap size={13} strokeWidth={1.75} className="text-rendi-warn mt-0.5 flex-shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 leading-none mb-1.5">
              Sugerencia · {diag.suggestion.code}
            </div>
            <p className="text-sm font-medium text-ink-0 leading-snug mb-1">{diag.suggestion.title}</p>
            <p className="text-xs text-ink-2 leading-relaxed">{diag.suggestion.action}</p>
            {diag.suggestion.evidence && (
              <p className="text-[11px] text-ink-3 italic mt-1.5 leading-relaxed">
                {diag.suggestion.evidence}
              </p>
            )}
            <Link
              to="/comportamiento"
              className="inline-flex items-center gap-1 text-[11px] font-mono uppercase tracking-caps text-data-blue hover:text-rendi-accent mt-2"
            >
              Ver detalle en Comportamiento <ArrowRight size={11} strokeWidth={1.75} />
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}

function Scenario({ title, value, sub, warn }) {
  return (
    <div className={`rounded-lg p-3 border ${warn ? 'border-amber-500/40 bg-amber-500/5' : 'border-line/60 bg-bg-2 dark:bg-bg-2/20'}`}>
      <p className="text-xs text-ink-3 mb-1 flex items-center gap-1">
        {warn && <AlertTriangle size={11} className="text-amber-500" />}
        {title}
      </p>
      <p className="text-lg font-bold text-ink-0">{value}</p>
      <p className="text-xs text-ink-3 mt-0.5">{sub}</p>
    </div>
  )
}

function GoalForm({ form, setForm, cagr, onSave, onCancel }) {
  const inputClass = 'w-full bg-bg-2 dark:bg-bg-2 border border-line-2 rounded-md px-3 py-2 text-sm text-ink-0'

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-xs text-ink-3 mb-1">Etiqueta (opcional)</label>
        <input
          value={form.label}
          onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
          placeholder="Ej.: Auto, Casa, Vacaciones"
          className={inputClass}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-ink-3 mb-1">Objetivo (USD)</label>
          <input
            type="number"
            value={form.target_usd}
            onChange={e => setForm(f => ({ ...f, target_usd: e.target.value }))}
            placeholder="8000"
            className={inputClass}
          />
        </div>
        <div>
          <label className="block text-xs text-ink-3 mb-1">Fecha objetivo</label>
          <DateInput
            value={form.target_date}
            min={today()}
            onChange={v => setForm(f => ({ ...f, target_date: v }))}
          />
        </div>
      </div>
      <div>
        <label className="block text-xs text-ink-3 mb-2">Rendimiento esperado anual (%)</label>
        <div className="flex gap-2 mb-3 flex-wrap">
          {cagr != null && (
            <button
              type="button"
              onClick={() => setForm(f => ({ ...f, expected_return_pct: cagr }))}
              className={`text-xs px-3 py-1.5 rounded-md border ${
                Math.abs(form.expected_return_pct - cagr) < 0.01
                  ? 'border-rendi-accent bg-rendi-accent/15 text-rendi-accent'
                  : 'border-line-2 text-ink-2 hover:bg-bg-2 dark:hover:bg-bg-2/50'
              }`}
            >
              Tu CAGR ({cagr.toFixed(1)}%)
            </button>
          )}
          {PRESETS.map(p => (
            <button
              key={p.label}
              type="button"
              onClick={() => setForm(f => ({ ...f, expected_return_pct: p.pct }))}
              className={`text-xs px-3 py-1.5 rounded-md border ${
                +form.expected_return_pct === p.pct
                  ? 'border-rendi-accent bg-rendi-accent/15 text-rendi-accent'
                  : 'border-line-2 text-ink-2 hover:bg-bg-2 dark:hover:bg-bg-2/50'
              }`}
              title={p.hint}
            >
              {p.label} ({p.pct}%)
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={-10}
            max={50}
            step={0.5}
            value={form.expected_return_pct}
            onChange={e => setForm(f => ({ ...f, expected_return_pct: +e.target.value }))}
            className="flex-1"
          />
          <input
            type="number"
            step={0.1}
            value={form.expected_return_pct}
            onChange={e => setForm(f => ({ ...f, expected_return_pct: e.target.value }))}
            className="w-20 bg-bg-2 dark:bg-bg-2 border border-line-2 rounded-md px-2 py-1 text-sm text-ink-0 text-center"
          />
          <span className="text-sm text-ink-3">%</span>
        </div>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        <button onClick={onCancel} className="px-4 py-2 text-sm text-ink-3 hover:text-ink-0 dark:hover:text-ink-0">Cancelar</button>
        <button onClick={onSave} className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-md font-medium">Guardar</button>
      </div>
    </div>
  )
}

// PMT mensual para alcanzar FV desde PV en n meses al rAnnual EFECTIVO anual
// (consistente con (1+rAnnual)^años en los otros escenarios)
function requiredMonthly(pv, fv, rAnnual, months) {
  if (months <= 0) return null
  // tasa mensual equivalente a la efectiva anual
  const r = Math.pow(1 + rAnnual, 1 / 12) - 1
  if (Math.abs(r) < 1e-9) return Math.max(0, (fv - pv) / months)
  const factor = Math.pow(1 + r, months)
  const pmt = (fv - pv * factor) / ((factor - 1) / r)
  return Math.max(0, pmt)
}

// Conservador / Histórico / Agresivo — tres escenarios alternativos para que
// el usuario compare rápido qué cambia si asume otra tasa.
function buildAltScenarios({ currentValue, target, monthsLeft, userCagr }) {
  const yearsLeft = monthsLeft / 12
  const histRate = userCagr != null ? +userCagr.toFixed(1) : 10
  const list = [
    { id: 'cons', label: 'Conservador', rate: 6,  hint: 'Bonos y exposición pasiva al S&P' },
    { id: 'hist', label: 'Histórico',   rate: histRate, hint: userCagr != null ? `Basado en tu CAGR real (${histRate}%)` : 'Aproximación al 10% anual' },
    { id: 'agr',  label: 'Agresivo',    rate: 15, hint: 'Acciones de crecimiento y cripto' },
  ]
  return list.map(s => {
    const r = s.rate / 100
    const monthly = requiredMonthly(currentValue, target, r, monthsLeft)
    const projected = currentValue * Math.pow(1 + r, yearsLeft)
    return { ...s, monthly, projected }
  })
}

function AltScenarioCard({ scenario }) {
  // Single alt-scenario card — assumes annual return + how-to-get-there.
  const { label, rate, hint, monthly, projected } = scenario
  return (
    <div className="rounded-lg border border-line/60 bg-bg-2 dark:bg-bg-1/30 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-ink-1">{label}</span>
        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg-2 dark:bg-bg-2/60 text-ink-2">
          {rate}% anual
        </span>
      </div>
      <p className="text-[11px] text-ink-3 mb-2 leading-snug">{hint}</p>
      <div className="space-y-1 tabular">
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-ink-3">Aportar</span>
          <span className="font-semibold text-ink-0">
            {monthly != null ? `${fmtUsd(monthly)} / mes` : '—'}
          </span>
        </div>
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-ink-3">Sin aportar</span>
          <span className="font-semibold text-ink-1">{fmtUsd(projected)}</span>
        </div>
      </div>
    </div>
  )
}
