// HomeMobile — Home mobile (Sprint M1, item 01 del audit).
// ═══════════════════════════════════════════════════════════════════════════
// Render priorizado para "una mirada de 8 segundos":
//   1. Hero balance (USD) + delta + sparkline 30d
//   2. KPI strip 2-col (P&L día · P&L mes · capital aportado · mejor activo hoy)
//   3. "Hoy en tu cartera" — PersonalLayer reducido a movimientos relevantes
//   4. Heatmap mini al fondo
//
// NO va watchlist en home mobile (audit: "vive en su tab propio").

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, TrendingUp, TrendingDown } from 'lucide-react'
import MiniSparkline from '../components/MiniSparkline'
import PersonalLayer from '../components/home/PersonalLayer'
import Heatmap from '../components/home/Heatmap'
import { api } from '../utils/api'
import { computeBrokerValue } from '../utils/valuation'
import { fmtUsd, pctSigned, colorClass } from '../utils/format'

export default function HomeMobile() {
  const [positions, setPositions] = useState([])
  const [monthly, setMonthly] = useState([])
  const [brokers, setBrokers] = useState([])
  const [dolar, setDolar] = useState(null)
  const [prices, setPrices] = useState({})
  const [snapshots, setSnapshots] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    try {
      const [pos, mon, bkrs, dol, snaps] = await Promise.all([
        api.get('/positions').catch(() => []),
        api.get('/monthly').catch(() => []),
        api.get('/brokers').catch(() => []),
        api.get('/dolar').catch(() => null),
        api.get('/snapshots?days=30').catch(() => []),
      ])
      setPositions(pos || [])
      setMonthly(mon || [])
      setBrokers(bkrs || [])
      setDolar(dol)
      setSnapshots(snaps || [])
      await loadPrices(pos, bkrs)
    } finally {
      setLoading(false)
    }
  }

  async function loadPrices(pos, bkrs) {
    if (!pos?.length || !bkrs?.length) return
    const arsBrokers = new Set(bkrs.filter(b => b.currency === 'ARS').map(b => b.name))
    const usdtBrokers = new Set(bkrs.filter(b => b.currency !== 'ARS').map(b => b.name))
    const arsSyms = [...new Set(pos.filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => p.asset + '.BA'))]
    const usdtSyms = [...new Set(pos.filter(p => usdtBrokers.has(p.broker) && !p.is_cash && p.asset !== 'USDT').map(p => p.asset))]
    const all = [...arsSyms, ...usdtSyms].join(',')
    if (!all) return
    try { setPrices(await api.get(`/prices?symbols=${all}`)) } catch { /* silent */ }
  }

  const tcBlue = dolar?.blue?.venta || 1415

  const totals = useMemo(() => {
    const bt = brokers.map(b => ({ ...b, ...computeBrokerValue(positions, prices, b, tcBlue) }))
    const totalValue = bt.reduce((s, b) => s + b.value, 0)
    const totalCost = bt.reduce((s, b) => s + b.invested, 0)
    const totalPnl = totalValue - totalCost
    const pct = totalCost > 0 ? totalPnl / totalCost : 0
    return { totalValue, totalCost, totalPnl, pct }
  }, [positions, prices, brokers, tcBlue])

  // Sparkline 30d desde snapshots (total_value por día)
  const sparkData = useMemo(() => {
    if (!snapshots?.length) return null
    const sorted = [...snapshots].sort((a, b) => (a.snapshot_date > b.snapshot_date ? 1 : -1))
    return sorted.map(s => Number(s.total_value || 0))
  }, [snapshots])

  // KPIs derivados de monthly (P&L mes en curso) + delta vs día anterior (snapshots)
  const kpis = useMemo(() => {
    const sortedMonthly = monthly
      .filter(m => m.broker === 'global')
      .sort((a, b) => (a.year !== b.year ? a.year - b.year : a.month - b.month))
    const lastMonth = sortedMonthly[sortedMonthly.length - 1]
    const pnlMonth = lastMonth
      ? (lastMonth.pnl_realized || 0) + (lastMonth.pnl_unrealized || 0)
      : null
    // P&L día: delta del último vs penúltimo snapshot
    const sortedSnaps = [...snapshots].sort((a, b) => (a.snapshot_date > b.snapshot_date ? 1 : -1))
    let pnlDay = null
    if (sortedSnaps.length >= 2) {
      const last = Number(sortedSnaps[sortedSnaps.length - 1].total_value || 0)
      const prev = Number(sortedSnaps[sortedSnaps.length - 2].total_value || 0)
      pnlDay = last - prev
    }
    // Capital aportado = baseline + flujos
    const baseline = sortedMonthly[0]?.capital_inicio || 0
    const flows = sortedMonthly.reduce((s, m) => s + (m.deposits || 0) - (m.withdrawals || 0), 0)
    const aportado = baseline + flows
    // Mejor activo hoy = mayor change_pct del día (necesitaría /prices con change — usamos % del PnL no real por ahora)
    let bestAsset = null
    let bestPct = -Infinity
    for (const p of positions) {
      if (p.is_cash) continue
      const px = p.price_override ?? prices[p.asset] ?? prices[p.asset + '.BA']
      if (!px || !p.invested) continue
      const value = px * (p.quantity || 0)
      const pct = (value - p.invested) / p.invested
      if (pct > bestPct) {
        bestPct = pct
        bestAsset = { symbol: p.asset, pct }
      }
    }
    return { pnlMonth, pnlDay, aportado, bestAsset }
  }, [monthly, snapshots, positions, prices])

  if (loading) {
    return (
      <div className="px-4 py-8 text-center text-ink-3 text-sm" aria-live="polite">
        Cargando tu portfolio…
      </div>
    )
  }

  return (
    <div className="pb-8">
      {/* ── 1. Hero balance ─────────────────────────────────────────── */}
      <section className="px-4 pt-5 pb-4">
        <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1.5">
          Tu portfolio
        </div>
        <div className="flex items-end justify-between gap-3 mb-1">
          <div className="min-w-0">
            <div className="text-4xl font-medium tabular tracking-tight text-ink-0 leading-none">
              ${fmtNumber(totals.totalValue)}
              <span className="text-base text-ink-3 ml-1.5 font-normal">USD</span>
            </div>
            <div className={`mt-2 text-sm tabular font-medium ${colorClass(totals.pct)} flex items-center gap-1`}>
              {totals.pct >= 0
                ? <TrendingUp size={13} strokeWidth={1.75} />
                : <TrendingDown size={13} strokeWidth={1.75} />}
              {pctSigned(totals.pct)} <span className="text-ink-3 font-mono text-xs">total</span>
            </div>
          </div>
          {sparkData?.length > 1 && (
            <div className="flex-shrink-0">
              <MiniSparkline
                data={sparkData}
                positive={(sparkData[sparkData.length - 1] || 0) >= (sparkData[0] || 0)}
                width={88}
                height={36}
              />
              <div className="text-[9px] font-mono uppercase tracking-caps text-ink-3 text-right mt-1">
                30d
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── 2. KPI strip 2x2 ────────────────────────────────────────── */}
      <section className="px-4 mb-5">
        <div className="grid grid-cols-2 border border-line/60 rounded-lg overflow-hidden bg-bg-1">
          <KpiCell
            label="P&L Día"
            value={kpis.pnlDay != null ? `${kpis.pnlDay >= 0 ? '+' : '−'}$${fmtNumber(Math.abs(kpis.pnlDay))}` : '—'}
            tone={kpis.pnlDay != null ? (kpis.pnlDay >= 0 ? 'pos' : 'neg') : null}
            bordered
          />
          <KpiCell
            label="P&L Mes"
            value={kpis.pnlMonth != null ? `${kpis.pnlMonth >= 0 ? '+' : '−'}$${fmtNumber(Math.abs(kpis.pnlMonth))}` : '—'}
            tone={kpis.pnlMonth != null ? (kpis.pnlMonth >= 0 ? 'pos' : 'neg') : null}
            bordered
            leftBorder
          />
          <KpiCell
            label="Capital aportado"
            value={kpis.aportado > 0 ? `$${fmtNumber(kpis.aportado)}` : '—'}
            sub="USD neto"
            topBorder
          />
          <KpiCell
            label="Mejor activo"
            value={kpis.bestAsset ? kpis.bestAsset.symbol : '—'}
            sub={kpis.bestAsset ? pctSigned(kpis.bestAsset.pct) : null}
            subTone={kpis.bestAsset?.pct >= 0 ? 'pos' : 'neg'}
            topBorder
            leftBorder
          />
        </div>
      </section>

      {/* ── 3. Hoy en tu cartera ───────────────────────────────────── */}
      <section className="px-4 mb-5">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
            Hoy en tu cartera
          </h2>
          <Link
            to="/posiciones"
            className="text-[11px] font-mono uppercase tracking-caps text-ink-2 hover:text-ink-0 inline-flex items-center gap-1"
          >
            Ver todas <ArrowRight size={11} strokeWidth={1.75} />
          </Link>
        </div>
        <PersonalLayer />
      </section>

      {/* ── 4. Heatmap mini al fondo ───────────────────────────────── */}
      <section className="px-4">
        <h2 className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2">
          S&P 500 hoy
        </h2>
        <Heatmap defaultMarket="sp500" />
      </section>
    </div>
  )
}

// ─── KpiCell mobile ───────────────────────────────────────────────────────

function KpiCell({ label, value, sub, tone, subTone, bordered, leftBorder, topBorder }) {
  const valueColor =
    tone === 'pos' ? 'text-rendi-pos'
    : tone === 'neg' ? 'text-rendi-neg'
    : 'text-ink-0'
  const subColor =
    subTone === 'pos' ? 'text-rendi-pos'
    : subTone === 'neg' ? 'text-rendi-neg'
    : 'text-ink-3'
  return (
    <div className={`px-3 py-3 ${leftBorder ? 'border-l border-line/40' : ''} ${topBorder ? 'border-t border-line/40' : ''}`}>
      <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1.5 leading-none">
        {label}
      </div>
      <div className={`text-base font-medium tabular leading-none ${valueColor}`}>
        {value}
      </div>
      {sub && (
        <div className={`text-[10px] font-mono tabular mt-1 leading-none ${subColor}`}>
          {sub}
        </div>
      )}
    </div>
  )
}

function fmtNumber(n) {
  if (n == null || isNaN(n)) return '—'
  return Math.round(n).toLocaleString('en-US')
}
