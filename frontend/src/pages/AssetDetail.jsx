// AssetDetail — ficha completa de un activo (/activo/:ticker).
// ═══════════════════════════════════════════════════════════════════════════
// Drill-down pedido en el design audit (#1): al clickear un activo en la cartera
// se abre TODO sobre ese ticker, agregando lotes de todos los brokers:
//   • Hero: valor actual + P&L total (USD + %)
//   • Chart 30d
//   • Stats: P&L realizado de toda la vida, win rate, veces operado, costo prom
//   • Lotes abiertos (orden FIFO: más viejo primero = el que se vende primero)
//   • Historial de operaciones (cada trade con su P&L realizado, win/loss)
//   • Link a Fundamentals (si es acción/CEDEAR)
//
// Responsive: una sola página sirve desktop y mobile (max-w centrado en desktop,
// full-width en mobile). Reusa la matriz de valuación de PositionDetailMobile.

import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft, TrendingUp, TrendingDown, Calendar, BarChart3, Layers,
} from 'lucide-react'
import AssetLogo from '../components/AssetLogo'
import AssetMiniChart from '../components/home/AssetMiniChart'
import Skeleton from '../components/Skeleton'
import EmptyState from '../components/EmptyState'
import { api } from '../utils/api'
import { pctSigned, colorClass } from '../utils/format'
import { priceSymbol, fciLabel, isArUsdBroker, costInPesos } from '../utils/valuation'
import { isCrypto, cryptoBrokerFactor } from '../utils/crypto'
import { inferType } from '../utils/tickers'
import AskAIAbout from '../components/ai/AskAIAbout'

// ─── Matriz de valuación por lote (reusa la lógica de PositionDetailMobile) ──
// Devuelve { valueUsd, investedUsd, pnlUsd, priceLocal } para UN lote.
function valueLot(p, { brokers, prices, tcBlue, tcCedear, tcCripto }) {
  const broker = brokers.find(b => b.name === p.broker)
  const isAR = broker?.currency === 'ARS'
  const qty = p.quantity || 0
  const invested = p.invested || 0
  if (p.is_cash) {
    const v = isAR ? invested / tcBlue : invested
    return { valueUsd: v, investedUsd: v, pnlUsd: 0, priceLocal: null }
  }
  // Lote en PESOS (currency='ARS') en una cuenta USD → estilo-ARS por el MEP
  // (tcCedear): costo Y valor a USD por el mismo rate, no el costo en pesos como dólares.
  if (costInPesos(p) && !isAR) {
    const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true, p.asset_type)]
    const investedUsd = invested / tcCedear
    const priceLocal = priceArs != null ? priceArs / tcCedear : null
    const valueUsd = priceLocal != null ? priceLocal * qty : investedUsd
    return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd, priceLocal }
  }
  if (isAR && !isCrypto(p.asset)) {
    const priceLocal = p.price_override ?? prices[priceSymbol(p.asset, true)]
    const valueUsd = priceLocal != null ? (priceLocal * qty) / tcBlue : invested / tcBlue
    const investedUsd = invested / tcBlue
    return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd, priceLocal }
  }
  if ((p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && p.price_override == null && !isCrypto(p.asset)) {
    const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
    const priceLocal = priceArs != null ? priceArs / tcCedear : null
    const valueUsd = priceLocal != null ? priceLocal * qty : invested
    return { valueUsd, investedUsd: invested, pnlUsd: valueUsd - invested, priceLocal }
  }
  // Cripto en broker AR (no exchange) se valúa al dólar MEP; en exchange queda a spot.
  // El factor multiplica valor Y costo por igual → el P&L% no cambia.
  const f = cryptoBrokerFactor(p.asset, !!broker?.is_exchange, p.price_override != null, tcCripto, tcCedear)
  const priceLocal = p.price_override ?? prices[p.asset]
  const valueUsd = (priceLocal != null ? priceLocal * qty : invested) * f
  const investedUsd = invested * f
  return { valueUsd, investedUsd, pnlUsd: valueUsd - investedUsd, priceLocal }
}

// Símbolo de precio que necesita un lote (para fetchear el set correcto).
function symbolFor(p, brokers) {
  if (p.is_cash) return null
  const isAR = brokers.find(b => b.name === p.broker)?.currency === 'ARS'
  // Lote en pesos (currency='ARS') aunque viva en cuenta USD → precio LOCAL .BA.
  const useBA = isAR || isArUsdBroker(p.broker) || costInPesos(p)
  return priceSymbol(p.asset, useBA, p.asset_type)
}

export default function AssetDetail() {
  const { ticker } = useParams()
  const navigate = useNavigate()
  const asset = (ticker || '').toUpperCase()

  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [dolar, setDolar] = useState(null)
  const [operations, setOperations] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => { loadAll() /* eslint-disable-next-line */ }, [asset])

  async function loadAll() {
    setLoading(true)
    try {
      const [pos, bkrs, dol, ops] = await Promise.all([
        api.get('/positions').catch(() => []),
        api.get('/brokers').catch(() => []),
        api.get('/dolar').catch(() => null),
        api.get('/operations').catch(() => []),
      ])
      const myLots = (pos || []).filter(p => (p.asset || '').toUpperCase() === asset)
      setPositions(myLots)
      setBrokers(bkrs || [])
      setDolar(dol)
      setOperations((ops || []).filter(o => (o.asset || '').toUpperCase() === asset))
      // Fetchar todos los símbolos de precio que necesitan los lotes
      const syms = [...new Set(myLots.map(p => symbolFor(p, bkrs || [])).filter(Boolean))]
      if (syms.length) {
        try { setPrices(await api.get(`/prices?symbols=${syms.join(',')}`)) } catch { /* silent */ }
      }
    } finally {
      setLoading(false)
    }
  }

  const tcBlue = dolar?.mep?.venta || dolar?.ccl?.venta || dolar?.blue?.venta || 1415
  const tcCedear = dolar?.mep?.venta || dolar?.ccl?.venta || tcBlue
  const tcCripto = dolar?.cripto?.venta

  // ── Agregados ──────────────────────────────────────────────────────────
  const agg = useMemo(() => {
    const openLots = positions.filter(p => !p.is_cash)
    let valueUsd = 0, investedUsd = 0, qty = 0
    const lots = openLots.map(p => {
      const v = valueLot(p, { brokers, prices, tcBlue, tcCedear, tcCripto })
      valueUsd += v.valueUsd; investedUsd += v.investedUsd; qty += (p.quantity || 0)
      return { ...p, ...v }
    }).sort((a, b) => (a.entry_date || '').localeCompare(b.entry_date || '')) // FIFO: viejo primero
    const pnlUsd = valueUsd - investedUsd
    const pnlPct = investedUsd > 0 ? pnlUsd / investedUsd : null
    const avgCostUsd = qty > 0 ? investedUsd / qty : null

    // Operaciones cerradas (tienen pnl_usd) → stats de operatoria
    const closed = operations.filter(o => o.pnl_usd != null)
    const realizedTotal = closed.reduce((s, o) => s + (o.pnl_usd || 0), 0)
    const wins = closed.filter(o => o.pnl_usd > 0).length
    const losses = closed.filter(o => o.pnl_usd < 0).length
    const winRate = (wins + losses) > 0 ? Math.round((wins / (wins + losses)) * 100) : null
    const best = closed.reduce((m, o) => (m == null || o.pnl_usd > m.pnl_usd ? o : m), null)
    const worst = closed.reduce((m, o) => (m == null || o.pnl_usd < m.pnl_usd ? o : m), null)

    return {
      lots, valueUsd, investedUsd, qty, pnlUsd, pnlPct, avgCostUsd,
      realizedTotal, wins, losses, winRate, best, worst,
      tradesCount: closed.length,
      brokerCount: new Set(openLots.map(p => p.broker)).size,
    }
  }, [positions, operations, brokers, prices, tcBlue, tcCedear, tcCripto])

  const type = inferType(asset)
  const hasFundamentals = type === 'stock_us' || type === 'cedear'
  const name = fciLabel(asset)

  if (loading) {
    return (
      <div className="page-shell-wide py-4 space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-20 w-full max-w-md rounded-lg" />
        <Skeleton className="h-40 w-full rounded-lg" />
      </div>
    )
  }

  const hasAnything = positions.length > 0 || operations.length > 0
  if (!hasAnything) {
    return (
      <div className="page-shell-wide py-4">
        <BackBar onBack={() => navigate(-1)} asset={asset} name={name} brokerCount={0} />
        <EmptyState
          icon={<Layers size={20} />}
          eyebrow={asset}
          title="No tenés movimientos en este activo"
          description="Cuando cargues una posición o una operación de este ticker, vas a ver acá todo su detalle: lotes, historial y P&L."
          action={
            <button
              type="button"
              onClick={() => navigate('/posiciones')}
              className="text-sm bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 px-4 py-2 rounded-sm transition-colors"
            >
              Ir a mi cartera
            </button>
          }
        />
      </div>
    )
  }

  return (
    <div className="page-shell-wide py-2 sm:py-4 max-w-3xl">
      <BackBar onBack={() => navigate(-1)} asset={asset} name={name} brokerCount={agg.brokerCount} />

      {/* Hero: valor + P&L total */}
      <AskAIAbout topic="position" params={{ asset }} subtitle={`${name} · todos los lotes`}>
        <section className="mb-5">
          <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-1.5">
            Valor actual {agg.brokerCount > 1 && `· ${agg.brokerCount} brokers`}
          </div>
          <div className="text-4xl font-medium tabular tracking-tight text-ink-0 leading-none">
            ${Math.round(agg.valueUsd).toLocaleString('en-US')}
            <span className="text-base text-ink-3 ml-1.5 font-normal">USD</span>
          </div>
          {agg.pnlPct != null && (
            <div className={`flex items-center gap-2 mt-3 text-sm font-medium tabular ${colorClass(agg.pnlPct)}`}>
              {agg.pnlPct >= 0 ? <TrendingUp size={13} strokeWidth={1.75} /> : <TrendingDown size={13} strokeWidth={1.75} />}
              <span>{agg.pnlUsd >= 0 ? '+' : '−'}${Math.abs(Math.round(agg.pnlUsd)).toLocaleString('en-US')}</span>
              <span className="text-ink-3 font-mono text-xs">·</span>
              <span>{pctSigned(agg.pnlPct)}</span>
              <span className="text-ink-3 text-xs ml-1">no realizado</span>
            </div>
          )}
        </section>
      </AskAIAbout>

      {/* Chart 30d */}
      {agg.lots.length > 0 && (
        <section className="mb-5">
          <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">Precio · últimos 30 días</div>
          <div className="bg-bg-1 border border-line/60 rounded-lg p-3">
            <AssetMiniChart symbol={symbolFor(agg.lots[0], brokers)} />
          </div>
        </section>
      )}

      {/* Stats de operatoria */}
      <section className="mb-5">
        <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">Tu operatoria en {asset}</div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <StatCell label="Costo promedio" value={agg.avgCostUsd != null ? `$${agg.avgCostUsd.toFixed(2)}` : '—'} sub="por unidad (USD)" />
          <StatCell label="Cantidad" value={agg.qty ? formatQty(agg.qty) : '—'} sub={`${agg.lots.length} lote${agg.lots.length !== 1 ? 's' : ''} abierto${agg.lots.length !== 1 ? 's' : ''}`} />
          <StatCell label="Invertido" value={`$${Math.round(agg.investedUsd).toLocaleString('en-US')}`} sub="costo total (USD)" />
          {agg.tradesCount > 0 && (
            <>
              <StatCell
                label="P&L realizado"
                value={`${agg.realizedTotal >= 0 ? '+' : '−'}$${Math.abs(Math.round(agg.realizedTotal)).toLocaleString('en-US')}`}
                sub={`${agg.tradesCount} op${agg.tradesCount !== 1 ? 's' : ''} cerrada${agg.tradesCount !== 1 ? 's' : ''}`}
                tone={agg.realizedTotal}
              />
              {agg.winRate != null && (
                <StatCell label="Win rate" value={`${agg.winRate}%`} sub={`${agg.wins} ganadas · ${agg.losses} perdidas`} tone={agg.winRate >= 50 ? 1 : -1} />
              )}
              {agg.best && (
                <StatCell label="Mejor trade" value={`${agg.best.pnl_usd >= 0 ? '+' : '−'}$${Math.abs(Math.round(agg.best.pnl_usd)).toLocaleString('en-US')}`} sub={agg.best.date || ''} tone={agg.best.pnl_usd} />
              )}
            </>
          )}
        </div>
      </section>

      {/* Lotes abiertos (FIFO) */}
      {agg.lots.length > 0 && (
        <section className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2">Lotes abiertos · orden FIFO</div>
            <div className="text-[10px] font-mono text-ink-3">el más viejo se vende primero</div>
          </div>
          <div className="bg-bg-1 border border-line/60 rounded-lg overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] font-mono uppercase tracking-caps text-ink-3 border-b border-line/40">
                  <th scope="col" className="text-left font-normal px-3 py-2">Fecha</th>
                  <th scope="col" className="text-left font-normal px-3 py-2 hidden sm:table-cell">Broker</th>
                  <th scope="col" className="text-right font-normal px-3 py-2">Cantidad</th>
                  <th scope="col" className="text-right font-normal px-3 py-2">Costo</th>
                  <th scope="col" className="text-right font-normal px-3 py-2">P&L</th>
                </tr>
              </thead>
              <tbody>
                {agg.lots.map((lot, i) => {
                  const lotPct = lot.investedUsd > 0 ? lot.pnlUsd / lot.investedUsd : null
                  return (
                    <tr key={lot.id ?? i} className={i > 0 ? 'border-t border-line/30' : ''}>
                      <td className="px-3 py-2.5 text-ink-1">{lot.entry_date || '—'}{i === 0 && <span className="ml-1.5 text-[9px] font-mono uppercase tracking-caps text-rendi-warn">próximo</span>}</td>
                      <td className="px-3 py-2.5 text-ink-3 text-xs hidden sm:table-cell">{lot.broker}</td>
                      <td className="px-3 py-2.5 text-right tabular text-ink-1">{formatQty(lot.quantity)}</td>
                      <td className="px-3 py-2.5 text-right tabular text-ink-3">${Math.round(lot.investedUsd).toLocaleString('en-US')}</td>
                      <td className={`px-3 py-2.5 text-right tabular font-medium ${colorClass(lotPct)}`}>
                        {lot.pnlUsd >= 0 ? '+' : '−'}${Math.abs(Math.round(lot.pnlUsd)).toLocaleString('en-US')}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Historial de operaciones */}
      {operations.length > 0 && (
        <AskAIAbout topic="position.lots" params={{ asset }} subtitle={`Historial · ${name}`}>
          <section className="mb-5">
            <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">Historial · {operations.length} operacion{operations.length !== 1 ? 'es' : ''}</div>
            <ul className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
              {operations.map((op, i) => {
                const isClosed = op.pnl_usd != null
                const win = isClosed && op.pnl_usd >= 0
                return (
                  <li key={op.id ?? i} className={`flex items-center gap-3 px-3 py-2.5 ${i > 0 ? 'border-t border-line/30' : ''}`}>
                    <Calendar size={11} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-ink-1 leading-none">
                        {op.date} · <span className="text-ink-3">{op.op_type || 'op'}</span>
                        <span className="text-ink-3 hidden sm:inline"> · {op.broker}</span>
                      </div>
                      {op.quantity != null && (
                        <div className="text-[10px] font-mono text-ink-3 leading-none mt-1">{formatQty(op.quantity)} u.</div>
                      )}
                    </div>
                    {isClosed && (
                      <span className={`text-[9px] font-mono uppercase tracking-caps px-1.5 py-0.5 rounded-sm border ${win ? 'text-rendi-pos border-rendi-pos/30 bg-rendi-pos/10' : 'text-rendi-neg border-rendi-neg/30 bg-rendi-neg/10'}`}>
                        {win ? 'ganada' : 'perdida'}
                      </span>
                    )}
                    {isClosed && (
                      <div className={`text-sm font-medium tabular leading-none w-20 text-right ${colorClass(op.pnl_usd)}`}>
                        {op.pnl_usd >= 0 ? '+' : '−'}${Math.abs(Math.round(op.pnl_usd)).toLocaleString('en-US')}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        </AskAIAbout>
      )}

      {/* Link a Fundamentals */}
      {hasFundamentals && (
        <button
          onClick={() => navigate(`/fundamentals?ticker=${encodeURIComponent(asset)}`)}
          className="w-full flex items-center justify-between px-4 py-3 rounded-lg bg-bg-1 border border-line hover:border-data-violet/40 hover:bg-data-violet/[0.04] transition-colors group"
        >
          <span className="flex items-center gap-2.5 text-sm text-ink-1">
            <BarChart3 size={15} strokeWidth={1.75} className="text-data-violet" />
            Ver fundamentals de {asset}
          </span>
          <span className="text-data-violet group-hover:translate-x-0.5 transition-transform">→</span>
        </button>
      )}
    </div>
  )
}

// ─── helpers ──────────────────────────────────────────────────────────────

function BackBar({ onBack, asset, name, brokerCount }) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <button type="button" onClick={onBack} aria-label="Volver" className="text-ink-2 hover:text-ink-0 -ml-2 rounded-sm hover:bg-bg-2 transition-colors flex items-center justify-center min-w-[44px] min-h-[44px]">
        <ArrowLeft size={18} strokeWidth={1.75} />
      </button>
      <AssetLogo asset={asset} size={32} />
      <div className="min-w-0">
        <div className="text-base font-semibold text-ink-0 leading-tight truncate">{name}</div>
        <div className="text-[11px] font-mono uppercase tracking-caps text-ink-3 leading-none mt-0.5">
          {asset}{brokerCount > 1 ? ` · ${brokerCount} brokers` : ''}
        </div>
      </div>
    </div>
  )
}

function StatCell({ label, value, sub, tone }) {
  const toneCls = tone == null ? 'text-ink-0' : colorClass(tone)
  return (
    <div className="bg-bg-1 border border-line/60 rounded-lg px-3 py-2.5 min-w-0">
      <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1">{label}</div>
      <div className={`text-base font-medium tabular truncate ${toneCls}`}>{value}</div>
      {sub && <div className="text-[10px] text-ink-3 mt-0.5 truncate" title={sub}>{sub}</div>}
    </div>
  )
}

function formatQty(q) {
  if (q == null || isNaN(q)) return '—'
  if (Math.abs(q) >= 1000) return Math.round(q).toLocaleString('en-US')
  if (Math.abs(q) >= 1) return q.toFixed(2).replace(/\.00$/, '')
  return q.toFixed(4)
}
