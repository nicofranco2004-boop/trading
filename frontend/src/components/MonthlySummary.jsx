import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Plus, Pencil, Trash2, Lock, ChevronRight, CalendarClock, Eye, EyeOff, Share2 } from 'lucide-react'
import Modal from './Modal'
import Card from './Card'
import EmptyState from './EmptyState'
import ShareCardModal from './ShareCardModal'
import { usd, ars, pct, pctSigned, colorClass, MONTHS } from '../utils/format'
import { api } from '../utils/api'
import { computeBrokerValue, priceSymbol } from '../utils/valuation'
import { lookupHistoricalDolar } from '../utils/fx'
import { specFromMonth } from '../utils/shareCard'
import { track } from '../utils/track'

const RECENT_MONTHS_DEFAULT = 6

const EMPTY = {
  year: new Date().getFullYear(),
  month: new Date().getMonth() + 1,
  broker: 'global',
  deposits: 0,
  withdrawals: 0,
  pnl_realized: 0,
  pnl_unrealized: 0,
  capital_inicio: 0,
  capital_final: 0,
}

function calcFinal(f) {
  return +(f.capital_inicio + f.deposits - f.withdrawals + f.pnl_realized + f.pnl_unrealized).toFixed(2)
}

function snap(n, eps = 1e-6) {
  return Math.abs(n) < eps ? 0 : n
}

function nextMonthOf(entry) {
  let y = entry.year, m = entry.month + 1
  if (m > 12) { m = 1; y++ }
  return { year: y, month: m }
}

export default function MonthlySummary({ refreshKey = 0 } = {}) {
  // Deeplink desde /reportes?broker=Cocos → abrir el tab de Cocos por default.
  // Si el param no matchea con los brokers cargados, queda en 'global'.
  const [searchParams] = useSearchParams()
  const initialTab = searchParams.get('broker') || 'global'

  const [entries, setEntries] = useState([])
  const [brokers, setBrokers] = useState([])
  const [tab, setTab] = useState(initialTab)
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [closingEntry, setClosingEntry] = useState(null)
  const [autoCalc, setAutoCalc] = useState(true)
  const [saving, setSaving] = useState(false)
  const [tcBlue, setTcBlue] = useState(1415)
  const [bench, setBench] = useState(null)
  // Por default mostramos TODO el historial. Razón: tras un import grande,
  // la ventana de "últimos 6" puede caer entera en un período sin actividad
  // (la historia importada queda en meses anteriores). El usuario puede
  // colapsar a "solo recientes" desde el toggle si prefiere.
  const [showAll, setShowAll] = useState(true)
  const [viewMode, setViewMode] = useState('simple') // 'simple' | 'advanced'
  const [shareEntry, setShareEntry] = useState(null)
  // Live portfolio total (mismo cálculo que Dashboard) — para reconciliar
  // contra capital_final del mes en curso y dejar claro el delta.
  const [livePortfolioTotal, setLivePortfolioTotal] = useState(null)

  useEffect(() => {
    init()
    // Re-fetch cuando el caller cambia refreshKey (ej.: Dashboard tras un import).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  async function load() {
    setEntries(await api.get('/monthly'))
  }

  async function init() {
    const [bkrs, dol, cfg, ents, bnch] = await Promise.all([
      api.get('/brokers'),
      api.get('/dolar').catch(() => null),
      api.get('/config').catch(() => null),
      api.get('/monthly'),
      api.get('/benchmarks').catch(() => null),
    ])
    setBrokers(bkrs)
    const tc = dol?.blue?.venta || cfg?.tc_blue || 1415
    setTcBlue(tc)
    setEntries(ents)
    setBench(bnch)

    await autoRolloverIfNeeded(ents, bkrs)

    // Nota: la reparación de cadena (capital_inicio[N+1] = capital_final[N],
    // pnl_unrealized=0 en cerrados, fórmula canónica de capital_final) la hace
    // el backend en `_repair_monthly_chain`, llamada después de cada mutación
    // de monthly_entries (cash flow, sell, create/update/delete). Antes había
    // un repair duplicado en el frontend; lo sacamos para evitar races y
    // doble I/O.

    // Pasamos brokers + tcBlue ya fetcheados — evita re-fetch redundante.
    await syncUnrealizedForAll({ brokers: bkrs, tcBlue: tc })

    setEntries(await api.get('/monthly'))
  }

  async function autoRolloverIfNeeded(currentEntries, bkrs) {
    const todayY = new Date().getFullYear()
    const todayM = new Date().getMonth() + 1
    const allBrokerNames = ['global', ...bkrs.map(b => b.name)]
    let didChange = false

    for (const brokerName of allBrokerNames) {
      let brokerEntries = currentEntries
        .filter(e => e.broker === brokerName)
        .sort((a, b) => a.year !== b.year ? a.year - b.year : a.month - b.month)

      while (brokerEntries.length > 0) {
        const last = brokerEntries[brokerEntries.length - 1]
        if (last.year > todayY || (last.year === todayY && last.month >= todayM)) break

        const cleanCapFinal = (last.capital_inicio || 0)
          + (last.deposits || 0) - (last.withdrawals || 0)
          + (last.pnl_realized || 0)
        const closedLast = { ...last, pnl_unrealized: 0, capital_final: cleanCapFinal }
        if (last.pnl_unrealized !== 0 || Math.abs((last.capital_final || 0) - cleanCapFinal) > 1e-4) {
          await api.put(`/monthly/${last.id}`, closedLast)
        }
        const { year: ny, month: nm } = nextMonthOf(last)
        const created = await api.post('/monthly', {
          ...EMPTY,
          broker: brokerName,
          year: ny,
          month: nm,
          capital_inicio: cleanCapFinal,
          capital_final: cleanCapFinal,
        })
        brokerEntries = [...brokerEntries, created]
        didChange = true
      }
    }
    return didChange
  }

  const tabs = ['global', ...brokers.map(b => b.name)]
  const tabIsARS = tab !== 'global' && brokers.find(b => b.name === tab)?.currency === 'ARS'

  // Phase 5 — for ARS tabs, convert stored USD-eq → display ARS using the
  // historical blue rate of (year, month). Closed months use bench.dolar_blue;
  // current month uses live tcBlue. For USD/global tabs: passthrough.
  function valueAt(v, year, month) {
    if (v == null) return null
    if (!tabIsARS) return v
    const rate = lookupHistoricalDolar(bench, year, month, tcBlue)
    return v * rate
  }

  // Format a stored value (USD-eq for ARS tabs, USD for others), using the
  // historical FX rate of (year, month) for ARS tabs.
  function fmtMoney(v, year, month) {
    if (v == null) return '—'
    if (!tabIsARS) return `$${usd(v)}`
    return ars(valueAt(v, year, month))
  }

  // Format a value that's already in display units (ARS for ARS tabs, USD otherwise).
  // Used for totals: each row pre-converted with valueAt(), then summed.
  function fmtMoneyDirect(v) {
    if (v == null) return '—'
    return tabIsARS ? ars(v) : `$${usd(v)}`
  }

  const allTabData = entries
    .filter(e => e.broker === tab)
    .sort((a, b) => a.year !== b.year ? a.year - b.year : a.month - b.month)

  // Default: only show recent months. The user can expand to see the full history.
  const tabData = showAll || allTabData.length <= RECENT_MONTHS_DEFAULT
    ? allTabData
    : allTabData.slice(-RECENT_MONTHS_DEFAULT)
  const hiddenCount = allTabData.length - tabData.length

  const lastEntry = tabData.length > 0 ? tabData[tabData.length - 1] : null

  const todayYear = new Date().getFullYear()
  const todayMonth = new Date().getMonth() + 1
  const calendarAhead = lastEntry && (
    lastEntry.year < todayYear ||
    (lastEntry.year === todayYear && lastEntry.month < todayMonth)
  )

  function setField(key, val) {
    setForm(f => {
      const updated = { ...f, [key]: val }
      if (autoCalc && key !== 'capital_final') {
        updated.capital_final = calcFinal(updated)
      }
      return updated
    })
  }

  function openAdd() {
    setAutoCalc(true)
    const base = { ...EMPTY, broker: tab }
    setForm({ ...base, capital_final: calcFinal(base) })
    setModal('add')
  }

  function openEdit(e) {
    setAutoCalc(false)
    setForm({ ...e })
    setModal('edit')
  }

  function openNext(fromEntry) {
    const { year, month } = nextMonthOf(fromEntry)
    const base = {
      ...EMPTY,
      broker: tab,
      year,
      month,
      capital_inicio: fromEntry.capital_final,
    }
    setClosingEntry(fromEntry)
    setAutoCalc(true)
    setForm({ ...base, capital_final: base.capital_inicio })
    setModal('next')
  }

  async function syncUnrealizedForAll(prefetched = null) {
    // Optimización: si init() ya fetcheó brokers/tcBlue, pasarlos via
    // `prefetched` evita 3 round-trips redundantes (brokers + dolar + config).
    // Ahorro: ~400ms al montar /mensual.
    // Save flow (línea ~300) llama sin prefetched → re-fetcha como antes.
    try {
      let pos, bkrs, tc
      if (prefetched && prefetched.brokers && prefetched.tcBlue) {
        bkrs = prefetched.brokers
        tc = prefetched.tcBlue
        pos = await api.get('/positions')
      } else {
        const r = await Promise.all([api.get('/positions'), api.get('/brokers')])
        pos = r[0]
        bkrs = r[1]
        const dol = await api.get('/dolar').catch(() => null)
        const cfg = await api.get('/config').catch(() => null)
        tc = dol?.blue?.venta || cfg?.tc_blue || tcBlue
      }

      const arsBrokerSet = new Set(bkrs.filter(b => b.currency === 'ARS').map(b => b.name))
      const arsSyms = [...new Set(pos.filter(p => arsBrokerSet.has(p.broker) && !p.is_cash).map(p => priceSymbol(p.asset, true)))]
      const usdSyms = [...new Set(pos.filter(p => !arsBrokerSet.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset))]
      const allSyms = [...arsSyms, ...usdSyms].join(',')
      const pricesData = allSyms ? await api.get(`/prices?symbols=${allSyms}`).catch(() => ({})) : {}

      let globalPnlUsd = 0
      let liveTotal = 0
      const syncs = []
      for (const b of bkrs) {
        const result = computeBrokerValue(pos, pricesData, b, tc)
        // Broker entry: ARS stores pnlArs/tc (USD-eq, multiplied back by tcBlue for ARS display);
        //               USD stores pnlUsd directly.
        const pnlForBroker = b.currency === 'ARS' ? result.pnlArs / tc : result.pnlUsd
        // Global aggregate uses pnlUsd ("true USD" P&L: ARS uses tc_compra for cost basis).
        globalPnlUsd += result.pnlUsd
        liveTotal += result.value  // valor total en USD (incluye cash convertido)
        syncs.push(api.post('/monthly/sync-unrealized', { broker: b.name, pnl_unrealized_usd: +pnlForBroker.toFixed(4) }).catch(() => {}))
      }
      syncs.push(api.post('/monthly/sync-unrealized', { broker: 'global', pnl_unrealized_usd: +globalPnlUsd.toFixed(4) }).catch(() => {}))
      await Promise.all(syncs)
      setLivePortfolioTotal(liveTotal)
    } catch (e) {
      console.warn('syncUnrealizedForAll failed:', e)
    }
  }

  async function save() {
    setSaving(true)
    try {
      if (modal === 'edit') {
        await api.put(`/monthly/${form.id}`, form)

      } else if (modal === 'next') {
        const allBrokerNames = ['global', ...brokers.map(b => b.name)]
        for (const brokerName of allBrokerNames) {
          const brokerEntries = entries
            .filter(e => e.broker === brokerName)
            .sort((a, b) => a.year !== b.year ? a.year - b.year : a.month - b.month)
          const lastEnt = brokerEntries[brokerEntries.length - 1]
          if (!lastEnt) continue

          const { year: nextYear, month: nextMonth } = nextMonthOf(lastEnt)
          const nextExists = entries.some(
            e => e.broker === brokerName && e.year === nextYear && e.month === nextMonth
          )

          const cleanCapFinal = (lastEnt.capital_inicio || 0)
            + (lastEnt.deposits || 0) - (lastEnt.withdrawals || 0)
            + (lastEnt.pnl_realized || 0)
          if (lastEnt.pnl_unrealized !== 0 || Math.abs((lastEnt.capital_final || 0) - cleanCapFinal) > 1e-4) {
            await api.put(`/monthly/${lastEnt.id}`, { ...lastEnt, pnl_unrealized: 0, capital_final: cleanCapFinal })
          }

          if (!nextExists) {
            const newEntry = brokerName === tab
              ? { ...form, capital_inicio: cleanCapFinal, capital_final: cleanCapFinal }
              : { ...EMPTY, broker: brokerName, year: nextYear, month: nextMonth, capital_inicio: cleanCapFinal, capital_final: cleanCapFinal }
            await api.post('/monthly', newEntry)
          }
        }

        await syncUnrealizedForAll()

      } else {
        await api.post('/monthly', form)
      }

      setModal(null)
      setClosingEntry(null)
      await load()
    } finally {
      setSaving(false)
    }
  }

  async function del(id) {
    if (!confirm('¿Eliminar este registro mensual? La acción no se puede deshacer.')) return
    await api.delete(`/monthly/${id}`)
    load()
  }

  // Phase 5 — totals are computed in DISPLAY units (ARS for ARS tabs, USD otherwise),
  // pre-converting each row via valueAt() so per-row + totals stay consistent. retCompound
  // is rate-independent (pure ratio per month) so it's computed from raw stored values.
  const totals = tabData.reduce((acc, m, idx) => {
    const isCurrentRow = idx === tabData.length - 1
    const rawRet = snap((m.pnl_realized || 0) + (isCurrentRow ? (m.pnl_unrealized || 0) : 0))
    const retPct = m.capital_inicio > 0 ? snap(rawRet / m.capital_inicio) : 0
    const conv = (v) => valueAt(v, m.year, m.month) || 0
    return {
      deposits: acc.deposits + conv(m.deposits),
      withdrawals: acc.withdrawals + conv(m.withdrawals),
      pnl_realized: acc.pnl_realized + conv(m.pnl_realized),
      pnl_unrealized: acc.pnl_unrealized + conv(isCurrentRow ? (m.pnl_unrealized || 0) : 0),
      ret: acc.ret + conv(rawRet),
      retCompound: acc.retCompound * (1 + retPct),
    }
  }, { deposits: 0, withdrawals: 0, pnl_realized: 0, pnl_unrealized: 0, ret: 0, retCompound: 1 })
  const totalRetPct = totals.retCompound - 1

  const thClass = 'px-4 py-2 text-left text-[11px] text-ink-3 font-semibold uppercase tracking-wider'
  const tdClass = 'px-4 py-2 text-sm'
  const inputClass = 'w-full bg-bg-2 dark:bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 focus:outline-none focus:ring-1 focus:ring-rendi-accent/40 focus:border-rendi-accent/60'

  return (
    <div>
      {/* Banner de nuevo mes (calendario) — usa amber porque es una alerta accionable
          (acción pendiente del usuario), no un éxito. */}
      {calendarAhead && (
        <div className="mb-5 flex items-center justify-between gap-4 px-4 py-3 bg-rendi-warn/10 border border-rendi-warn/30 rounded">
          <div className="flex items-center gap-3">
            <CalendarClock size={18} strokeWidth={1.5} className="text-rendi-warn flex-shrink-0" />
            <p className="text-sm text-ink-1">
              Estamos en <span className="font-semibold">{MONTHS[todayMonth - 1]} {todayYear}</span> —
              el último mes registrado es <span className="font-semibold">{MONTHS[lastEntry.month - 1]} {lastEntry.year}</span>.
            </p>
          </div>
          <button
            onClick={() => openNext(lastEntry)}
            className="flex-shrink-0 flex items-center gap-1.5 text-sm font-medium bg-rendi-accent text-white hover:bg-rendi-accent/90 px-3 py-1.5 rounded-sm transition"
          >
            Abrir {MONTHS[nextMonthOf(lastEntry).month - 1]} <ChevronRight size={14} strokeWidth={1.5} />
          </button>
        </div>
      )}

      {/* Conciliación: live vs current-month-stored vs last-closed.
          Resuelve la confusión clásica "¿por qué Mayo dice $X pero el Dashboard
          dice $Y?". Solo en tab global (entries en USD), con datos válidos. */}
      {tab === 'global' && livePortfolioTotal != null && allTabData.length > 0 && (
        <ConciliationBanner
          live={livePortfolioTotal}
          entries={allTabData}
        />
      )}

      <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
        <div>
          <h2 className="text-base font-semibold text-ink-0">Resumen Mensual</h2>
          <p className="text-xs text-ink-3 mt-0.5">
            {viewMode === 'simple'
              ? 'Resultado mensual sintetizado en una vista.'
              : 'Detalle completo de flujos, P&L y capital al cierre de cada período.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex bg-bg-2 dark:bg-bg-2/60 p-0.5 rounded-md">
            <button
              onClick={() => setViewMode('simple')}
              className={`px-2.5 py-1 text-[11px] font-semibold rounded transition ${
                viewMode === 'simple'
                  ? 'bg-white dark:bg-bg-2 text-ink-0 shadow-sm'
                  : 'text-ink-3 hover:text-ink-0 dark:hover:text-ink-0'
              }`}
              title="Vista simple"
            >Simple</button>
            <button
              onClick={() => setViewMode('advanced')}
              className={`px-2.5 py-1 text-[11px] font-semibold rounded transition ${
                viewMode === 'advanced'
                  ? 'bg-white dark:bg-bg-2 text-ink-0 shadow-sm'
                  : 'text-ink-3 hover:text-ink-0 dark:hover:text-ink-0'
              }`}
              title="Vista detallada"
            >Detalle</button>
          </div>
          <button
            onClick={openAdd}
            className="flex items-center gap-1.5 text-sm bg-bg-2 text-ink-1 hover:bg-bg-3 hover:text-ink-0 border border-line px-3 py-1.5 rounded-sm font-medium transition-colors"
          >
            <Plus size={14} strokeWidth={1.5} /> Agregar mes
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5 bg-bg-2 dark:bg-bg-2/50 p-1 rounded-lg w-fit flex-wrap">
        {tabs.map(b => (
          <button
            key={b}
            onClick={() => setTab(b)}
            className={`px-4 py-1.5 text-sm rounded-md font-medium transition-colors capitalize ${
              tab === b
                ? 'bg-white dark:bg-bg-2 text-ink-0 shadow-sm'
                : 'text-ink-3 hover:text-ink-0 dark:hover:text-ink-0'
            }`}
          >
            {b === 'global' ? 'Global (USD)' : brokers.find(x => x.name === b)?.currency === 'ARS' ? `${b} (ARS)` : b}
          </button>
        ))}
      </div>

      <Card padding="none">
        {hiddenCount > 0 && (
          <div className="flex items-center justify-between gap-3 px-4 py-2 border-b border-line/70 dark:border-line/40 bg-bg-2 dark:bg-bg-2/40">
            <span className="text-xs text-ink-3">
              Mostrando los últimos {RECENT_MONTHS_DEFAULT} meses · {hiddenCount} más en el historial
            </span>
            <button
              onClick={() => setShowAll(true)}
              className="inline-flex items-center gap-1 text-xs font-medium text-rendi-accent hover:underline"
            >
              <Eye size={12} strokeWidth={1.5} /> Ver todos
            </button>
          </div>
        )}
        {showAll && allTabData.length > RECENT_MONTHS_DEFAULT && (
          <div className="flex items-center justify-end px-4 py-2 border-b border-line/70 dark:border-line/40 bg-bg-2 dark:bg-bg-2/40">
            <button
              onClick={() => setShowAll(false)}
              className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 hover:text-ink-0 dark:hover:text-ink-0"
            >
              <EyeOff size={12} /> Mostrar solo recientes
            </button>
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-line/50">
                <th className={thClass}>Mes</th>
                {viewMode === 'simple' ? (
                  <>
                    <th className={thClass}>Resultado</th>
                    <th className={thClass}>Retorno %</th>
                    <th className={thClass}>Flujo neto</th>
                    <th className={thClass}>Estado</th>
                  </>
                ) : (
                  <>
                    <th className={thClass}>Depósitos</th>
                    <th className={thClass}>Retiros</th>
                    <th className={thClass}>Flujo neto</th>
                    <th className={thClass}>P&L Real.</th>
                    <th className={thClass}>P&L No Real.</th>
                    <th className={thClass}>Cap. Inicio</th>
                    <th className={thClass}>Cap. Final</th>
                    <th className={thClass}>Retorno {tabIsARS ? 'ARS' : 'USD'}</th>
                    <th className={thClass}>Retorno %</th>
                  </>
                )}
                <th className={thClass}></th>
              </tr>
            </thead>
            <tbody>
              {tabData.length === 0 && (
                <tr>
                  <td colSpan={viewMode === 'simple' ? 6 : 11}>
                    <EmptyState
                      title="Sin registros mensuales"
                      description="Cargá tu primer mes para comenzar a registrar flujos, depósitos y P&L."
                      action={
                        <button onClick={openAdd} className="inline-flex items-center gap-1.5 text-sm bg-rendi-accent text-white hover:bg-rendi-accent/90 px-3 py-2 rounded-sm font-semibold transition">
                          <Plus size={14} strokeWidth={1.5} /> Agregar primer mes
                        </button>
                      }
                    />
                  </td>
                </tr>
              )}
              {tabData.map((m, idx) => {
                const net = m.deposits - m.withdrawals
                const isCurrent = idx === tabData.length - 1
                const ret = snap((m.pnl_realized || 0) + (isCurrent ? (m.pnl_unrealized || 0) : 0))
                const retPct = m.capital_inicio > 0 ? snap(ret / m.capital_inicio) : 0

                return (
                  <tr
                    key={m.id}
                    className={`border-b border-line/50 dark:border-line/40 hover:bg-bg-2 dark:hover:bg-bg-2 ${
                      isCurrent ? 'bg-bg-2 dark:bg-bg-2/50' : ''
                    }`}
                  >
                    <td className={`${tdClass} font-medium text-ink-0`}>
                      <div className="flex items-center gap-2">
                        {isCurrent ? (
                          <span className="inline-flex items-center text-[9px] font-mono font-semibold uppercase tracking-[0.18em] bg-bg-3 text-ink-1 px-1.5 py-0.5 rounded-sm border border-line">
                            En curso
                          </span>
                        ) : (
                          <Lock size={10} strokeWidth={1.5} className="text-ink-1 flex-shrink-0" />
                        )}
                        {MONTHS[m.month - 1]} {m.year}
                      </div>
                    </td>
                    {viewMode === 'simple' ? (
                      <>
                        <td className={`${tdClass} font-bold tabular ${colorClass(ret)}`}>{fmtMoney(ret, m.year, m.month)}</td>
                        <td className={`${tdClass} font-bold tabular ${colorClass(retPct)}`}>{pctSigned(retPct)}</td>
                        <td className={`${tdClass} tabular ${colorClass(net)}`}>{fmtMoney(net, m.year, m.month)}</td>
                        <td className={tdClass}>
                          {isCurrent ? (
                            <span className="inline-flex items-center gap-1 text-[10px] font-mono font-semibold uppercase tracking-[0.15em] px-2 py-0.5 rounded-sm bg-bg-3 text-ink-1 border border-line">
                              En curso
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-[10px] font-mono font-semibold uppercase tracking-[0.15em] px-2 py-0.5 rounded-sm bg-bg-2 dark:bg-bg-2 text-ink-3 border border-line/50 dark:border-line">
                              <Lock size={9} /> Cerrado
                            </span>
                          )}
                        </td>
                      </>
                    ) : (
                      <>
                        <td className={`${tdClass} text-ink-2 tabular`}>{fmtMoney(m.deposits, m.year, m.month)}</td>
                        <td className={`${tdClass} text-ink-2 tabular`}>{fmtMoney(m.withdrawals, m.year, m.month)}</td>
                        <td className={`${tdClass} tabular ${colorClass(net)}`}>{fmtMoney(net, m.year, m.month)}</td>
                        <td className={`${tdClass} tabular ${colorClass(m.pnl_realized)}`}>{fmtMoney(m.pnl_realized, m.year, m.month)}</td>
                        <td className={`${tdClass} tabular ${isCurrent ? colorClass(m.pnl_unrealized) : ''}`}>{isCurrent ? fmtMoney(m.pnl_unrealized, m.year, m.month) : fmtMoney(0, m.year, m.month)}</td>
                        <td className={`${tdClass} text-ink-2 tabular`}>{fmtMoney(m.capital_inicio, m.year, m.month)}</td>
                        <td className={`${tdClass} text-ink-2 tabular`}>{fmtMoney(m.capital_final, m.year, m.month)}</td>
                        <td className={`${tdClass} font-medium tabular ${colorClass(ret)}`}>{fmtMoney(ret, m.year, m.month)}</td>
                        <td className={`${tdClass} font-medium tabular ${colorClass(retPct)}`}>{pctSigned(retPct)}</td>
                      </>
                    )}
                    <td className={tdClass}>
                      <div className="flex items-center gap-2">
                        {!isCurrent && retPct !== 0 && (
                          <button
                            onClick={() => {
                              track('share_card_opened', { source: 'monthly', month: m.month, year: m.year })
                              setShareEntry({ ...m, pnl_pct: retPct, net, month_label: `${MONTHS[m.month - 1]} ${m.year}` })
                            }}
                            className="text-ink-3 hover:text-rendi-pos transition-colors"
                            title="Compartir resultado del mes"
                          >
                            <Share2 size={13} strokeWidth={1.75} />
                          </button>
                        )}
                        <button onClick={() => openEdit(m)} className="text-ink-3 hover:text-ink-1 dark:hover:text-ink-0" title="Editar">
                          <Pencil size={13} />
                        </button>
                        <button onClick={() => del(m.id)} className="text-ink-3 hover:text-red-500" title="Eliminar">
                          <Trash2 size={13} />
                        </button>
                        {isCurrent && (
                          <button
                            onClick={() => openNext(m)}
                            className="flex items-center gap-1 text-[11px] font-medium text-rendi-accent hover:underline ml-1"
                            title="Cerrar este mes y abrir el siguiente"
                          >
                            Cerrar mes <ChevronRight size={12} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
            {tabData.length > 0 && (
              <tfoot>
                <tr className="border-t border-line-2 bg-bg-2 dark:bg-bg-2/20">
                  <td className="px-4 py-2 text-xs font-semibold text-ink-3 uppercase tracking-wider">Total</td>
                  {viewMode === 'simple' ? (
                    <>
                      <td className={`px-4 py-2 text-xs font-semibold tabular ${colorClass(totals.ret)}`}>{fmtMoneyDirect(totals.ret)}</td>
                      <td className={`px-4 py-2 text-xs font-semibold tabular ${colorClass(totalRetPct)}`} title="Rendimiento compuesto (TWR)">{pctSigned(totalRetPct)}</td>
                      <td className={`px-4 py-2 text-xs tabular ${colorClass(totals.deposits - totals.withdrawals)}`}>{fmtMoneyDirect(totals.deposits - totals.withdrawals)}</td>
                      <td />
                      <td />
                    </>
                  ) : (
                    <>
                      <td className="px-4 py-2 text-xs text-ink-2 tabular">{fmtMoneyDirect(totals.deposits)}</td>
                      <td className="px-4 py-2 text-xs text-ink-2 tabular">{fmtMoneyDirect(totals.withdrawals)}</td>
                      <td className={`px-4 py-2 text-xs tabular ${colorClass(totals.deposits - totals.withdrawals)}`}>{fmtMoneyDirect(totals.deposits - totals.withdrawals)}</td>
                      <td className={`px-4 py-2 text-xs tabular ${colorClass(totals.pnl_realized)}`}>{fmtMoneyDirect(totals.pnl_realized)}</td>
                      <td className={`px-4 py-2 text-xs tabular ${colorClass(totals.pnl_unrealized)}`}>{fmtMoneyDirect(totals.pnl_unrealized)}</td>
                      <td className="px-4 py-2" />
                      <td className="px-4 py-2" />
                      <td className={`px-4 py-2 text-xs font-semibold tabular ${colorClass(totals.ret)}`}>{fmtMoneyDirect(totals.ret)}</td>
                      <td className={`px-4 py-2 text-xs font-semibold tabular ${colorClass(totalRetPct)}`} title="Rendimiento compuesto (TWR)">{pctSigned(totalRetPct)}</td>
                    </>
                  )}
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      </Card>

      {/* Modal agregar / editar / cerrar mes */}
      {modal && (
        <Modal
          title={
            modal === 'next'
              ? `Abrir ${MONTHS[form.month - 1]} ${form.year}`
              : modal === 'edit'
              ? `Editar ${MONTHS[form.month - 1]} ${form.year}`
              : 'Agregar mes'
          }
          onClose={() => setModal(null)}
        >
          <div className="space-y-4">

            {modal === 'next' && (
              <div className="flex items-start gap-2 bg-bg-2 border border-line rounded px-3 py-2.5 text-sm text-ink-1">
                <ChevronRight size={15} strokeWidth={1.5} className="text-ink-2 mt-0.5 flex-shrink-0" />
                <span>
                  Capital inicial heredado del cierre de {MONTHS[form.month - 2 < 0 ? 11 : form.month - 2]} ·
                  <span className="font-semibold text-ink-0"> ${usd(form.capital_inicio)}</span>.
                  Cargá los movimientos del mes — el capital final se recalcula automáticamente.
                </span>
              </div>
            )}

            {modal === 'add' && (
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-ink-3 mb-1">Año</label>
                  <input type="number" value={form.year}
                    onChange={e => setField('year', +e.target.value)}
                    className={inputClass} />
                </div>
                <div>
                  <label className="block text-xs text-ink-3 mb-1">Mes</label>
                  <select value={form.month} onChange={e => setField('month', +e.target.value)} className={inputClass}>
                    {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-ink-3 mb-1">Broker</label>
                  <select value={form.broker} onChange={e => setField('broker', e.target.value)} className={inputClass}>
                    <option value="global">Global</option>
                    {brokers.map(b => <option key={b.id} value={b.name}>{b.name}</option>)}
                  </select>
                </div>
              </div>
            )}

            <div>
              <label className="block text-xs text-ink-3 mb-1">Capital Inicio (USD)</label>
              <input type="number" step="any" value={form.capital_inicio}
                onChange={e => setField('capital_inicio', +e.target.value)}
                className={inputClass}
                readOnly={modal === 'next'}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              {[
                ['Depósitos', 'deposits'],
                ['Retiros', 'withdrawals'],
                ['P&L Realizado', 'pnl_realized'],
                ['P&L No Realizado', 'pnl_unrealized'],
              ].map(([label, key]) => (
                <div key={key}>
                  <label className="block text-xs text-ink-3 mb-1">{label}</label>
                  <input type="number" step="any" value={form[key]}
                    onChange={e => setField(key, +e.target.value)}
                    className={inputClass} />
                </div>
              ))}
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs text-ink-3">Capital Final (USD)</label>
                <label className="flex items-center gap-1.5 text-xs text-ink-3 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={autoCalc}
                    onChange={e => {
                      setAutoCalc(e.target.checked)
                      if (e.target.checked) setForm(f => ({ ...f, capital_final: calcFinal(f) }))
                    }}
                    className="rounded-sm accent-rendi-pos"
                  />
                  Cálculo automático
                </label>
              </div>
              <input
                type="number" step="any"
                value={form.capital_final}
                onChange={e => setField('capital_final', +e.target.value)}
                readOnly={autoCalc}
                className={`${inputClass} ${autoCalc ? 'opacity-70 cursor-default bg-bg-2 dark:bg-bg-2' : ''}`}
              />
              {autoCalc && (
                <p className="text-[11px] text-ink-3 mt-1">
                  = Inicio + Depósitos − Retiros + P&L = <span className="font-medium text-ink-2">${usd(form.capital_final)}</span>
                </p>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-1">
              <button onClick={() => setModal(null)} className="px-4 py-2 text-sm text-ink-3 hover:text-ink-0 dark:hover:text-ink-0">
                Cancelar
              </button>
              <button
                onClick={save}
                disabled={saving}
                className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 disabled:opacity-50 text-white rounded-sm font-semibold transition"
              >
                {saving ? 'Guardando...' : modal === 'next' ? `Abrir ${MONTHS[form.month - 1]}` : 'Guardar'}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {shareEntry && (
        <ShareCardModal
          spec={specFromMonth(shareEntry)}
          filename={`rendi-${shareEntry.year}-${String(shareEntry.month).padStart(2, '0')}.png`}
          source="monthly"
          onClose={() => setShareEntry(null)}
        />
      )}
    </div>
  )
}

// ─── ConciliationBanner ──────────────────────────────────────────────────────
// Aclara la confusión más común del Resumen Mensual:
//   "¿Por qué Mayo dice $X pero el Dashboard dice $Y?"
//
// Muestra los 3 números relevantes con etiquetas claras:
//   • Valor actual (live, sincroniza con Dashboard)
//   • Mes en curso (capital_final guardado del mes calendario actual)
//   • Último mes cerrado (snapshot frozen)
//
// Si live ≠ mes en curso por un margen significativo, surfacea el delta y la
// causa probable: "no se sincronizó aún" o "drift por FX cash ARS / commissions".
function ConciliationBanner({ live, entries }) {
  if (!entries || entries.length === 0) return null
  const sorted = [...entries].sort((a, b) =>
    a.year !== b.year ? a.year - b.year : a.month - b.month
  )
  const today = new Date()
  const todayY = today.getFullYear()
  const todayM = today.getMonth() + 1
  const isCurrentMonth = (e) => e.year === todayY && e.month === todayM

  const current = sorted.find(isCurrentMonth) || sorted[sorted.length - 1]
  const closed = sorted.filter(e => !isCurrentMonth(e))
  const lastClosed = closed.length > 0 ? closed[closed.length - 1] : null

  const currentCapFinal = current?.capital_final ?? null
  const drift = currentCapFinal != null ? live - currentCapFinal : null
  const driftPct = currentCapFinal && currentCapFinal !== 0 ? (drift / currentCapFinal) * 100 : 0
  // Margen de tolerancia: ~$0.50 o 0.05% — abajo de eso no vale la pena alertar.
  const significantDrift = drift != null && (Math.abs(drift) > 0.5 || Math.abs(driftPct) > 0.05)

  return (
    <div className="mb-5 bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-3">
          Conciliación
        </h3>
        <span className="text-[10px] text-ink-3">
          Te ayuda a entender qué número es qué.
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="bg-bg-2 border border-line rounded p-3">
          <div className="flex items-center gap-1.5 text-[10px] font-mono uppercase font-semibold tracking-[0.18em] text-ink-2">
            <span className="live-dot" aria-hidden />
            Valor actual (live)
          </div>
          <p className="text-lg font-medium text-ink-0 mt-1 num">
            ${usd(live)}
          </p>
          <p className="text-[10px] text-ink-3 mt-0.5 leading-tight">
            Coincide con el Dashboard. Calculado con precios actuales de mercado.
          </p>
        </div>

        <div className="bg-bg-2 dark:bg-bg-1/40 border border-line/70 dark:border-line/40 rounded-lg p-3">
          <div className="text-[10px] uppercase font-semibold tracking-wider text-ink-3">
            Mes en curso · cap. final
          </div>
          <p className={`text-lg font-bold mt-1 tabular ${significantDrift ? 'text-amber-600 dark:text-amber-400' : 'text-ink-0 dark:text-white'}`}>
            {currentCapFinal != null ? `$${usd(currentCapFinal)}` : '—'}
          </p>
          <p className="text-[10px] text-ink-3 mt-0.5 leading-tight">
            {current ? `${MONTHS[current.month - 1]} ${current.year} · ver fila marcada "EN CURSO".` : '—'}
          </p>
        </div>

        <div className="bg-bg-2 dark:bg-bg-1/40 border border-line/70 dark:border-line/40 rounded-lg p-3">
          <div className="text-[10px] uppercase font-semibold tracking-wider text-ink-3">
            Último mes cerrado
          </div>
          <p className="text-lg font-bold text-ink-0 dark:text-white mt-1 tabular">
            {lastClosed ? `$${usd(lastClosed.capital_final || 0)}` : '—'}
          </p>
          <p className="text-[10px] text-ink-3 mt-0.5 leading-tight">
            {lastClosed
              ? `${MONTHS[lastClosed.month - 1]} ${lastClosed.year} · snapshot al cierre, no se modifica.`
              : 'Cerrá un mes para visualizarlo aquí.'}
          </p>
        </div>
      </div>

      {significantDrift && (
        <div className="mt-3 flex items-start gap-2 text-xs text-amber-600 dark:text-amber-400 bg-amber-500/[0.06] border border-amber-500/20 rounded-md px-3 py-2">
          <span className="mt-0.5">⚠</span>
          <div className="leading-snug">
            Diferencia de <span className="font-semibold tabular">${usd(Math.abs(drift))}</span>
            {' '}entre el valor actual y el capital final del mes en curso. Causas habituales:
            <ul className="mt-1 ml-3 list-disc list-inside text-ink-2">
              <li>Variación del dólar blue con cash ARS en cartera: el equivalente en USD cambia sin operaciones.</li>
              <li>Sincronización pendiente: el capital final se actualiza al ingresar al Dashboard o al Resumen Mensual.</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
