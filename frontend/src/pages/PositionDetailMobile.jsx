// PositionDetailMobile — detalle full-screen de una posición (Sprint M3, item 14).
// ═══════════════════════════════════════════════════════════════════════════
// Ruta /posiciones/:id mobile-only. El desktop tiene su detalle expandible
// en la tabla — en mobile preferimos pantalla dedicada para no perder densidad.
//
// Layout:
//   Top bar con back + ticker
//   Hero: P/L USD grande + %, value actual debajo
//   Chart 30d full-width
//   Stats: qty, precio promedio, precio actual, invested, value
//   Lots: lista de operaciones de ese ticker (compra/venta histórico)

import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, TrendingUp, TrendingDown, Calendar } from 'lucide-react'
import AssetLogo from '../components/AssetLogo'
import AssetMiniChart from '../components/home/AssetMiniChart'
import { api } from '../utils/api'
import { usd, pctSigned, colorClass } from '../utils/format'
import { priceSymbol, fciLabel } from '../utils/valuation'
import AskAIAbout from '../components/ai/AskAIAbout'

export default function PositionDetailMobile() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [position, setPosition] = useState(null)
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [dolar, setDolar] = useState(null)
  const [operations, setOperations] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => { loadAll() }, [id])

  async function loadAll() {
    setLoading(true)
    try {
      const [positions, bkrs, dol, ops] = await Promise.all([
        api.get('/positions').catch(() => []),
        api.get('/brokers').catch(() => []),
        api.get('/dolar').catch(() => null),
        api.get('/operations').catch(() => []),
      ])
      const p = (positions || []).find(x => String(x.id) === String(id))
      if (!p) {
        setError('Posición no encontrada.')
        return
      }
      setPosition(p)
      setBrokers(bkrs || [])
      setDolar(dol)
      // Filtrar ops del mismo asset + broker
      setOperations((ops || []).filter(o => o.asset === p.asset && o.broker === p.broker))
      // Fetchar precio
      const isAR = (bkrs || []).find(b => b.name === p.broker)?.currency === 'ARS'
      const sym = !p.is_cash ? priceSymbol(p.asset, isAR) : p.asset
      if (!p.is_cash) {
        try { setPrices(await api.get(`/prices?symbols=${sym}`)) } catch { /* silent */ }
      }
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <FullScreen><div className="text-ink-3 text-sm">Cargando posición…</div></FullScreen>
  }

  if (error || !position) {
    return (
      <FullScreen>
        <div className="text-rendi-neg text-sm mb-4">{error || 'Posición no disponible.'}</div>
        <button
          onClick={() => navigate(-1)}
          className="text-xs font-mono uppercase tracking-caps text-data-blue hover:text-rendi-accent"
        >
          ← Volver
        </button>
      </FullScreen>
    )
  }

  const p = position
  const isAR = brokers.find(b => b.name === p.broker)?.currency === 'ARS'
  const tcBlue = dolar?.blue?.venta || 1415
  const tcCcl = dolar?.ccl?.venta || dolar?.mep?.venta || tcBlue  // dólar financiero p/ CEDEARs
  const qty = p.quantity || 0
  const invested = p.invested || 0

  // Compute current value + P/L
  let valueUsd = 0, priceLocal = null, pnlUsd = null, pnlPct = null
  if (p.is_cash) {
    valueUsd = isAR ? invested / tcBlue : invested
  } else if (isAR) {
    priceLocal = p.price_override ?? prices[priceSymbol(p.asset, true)]
    valueUsd = priceLocal != null ? (priceLocal * qty) / tcBlue : invested / tcBlue
    const investedUsd = invested / tcBlue
    pnlUsd = valueUsd - investedUsd
    pnlPct = investedUsd > 0 ? pnlUsd / investedUsd : 0
  } else if (p.asset_type === 'CEDEAR' && p.price_override == null) {
    // CEDEAR en broker USD: precio LOCAL .BA (ARS) → USD via CCL (dólar
    // financiero), no la acción US del ticker (que vale 15-100× más).
    const priceArs = prices[priceSymbol(p.asset, true, 'CEDEAR')]
    priceLocal = priceArs != null ? priceArs / tcCcl : null
    valueUsd = priceLocal != null ? priceLocal * qty : invested
    pnlUsd = valueUsd - invested
    pnlPct = invested > 0 ? pnlUsd / invested : 0
  } else {
    priceLocal = p.price_override ?? prices[p.asset]
    valueUsd = priceLocal != null ? priceLocal * qty : invested
    pnlUsd = valueUsd - invested
    pnlPct = invested > 0 ? pnlUsd / invested : 0
  }

  const avgPrice = !p.is_cash && qty > 0 ? invested / qty : null

  return (
    <div
      className="min-h-screen bg-bg-0 pb-8"
      style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
    >
      {/* Top bar */}
      <header className="sticky top-0 z-30 flex items-center gap-3 px-3 py-2.5 border-b border-line/40 bg-bg-0/95 backdrop-blur-md">
        <button
          onClick={() => navigate(-1)}
          aria-label="Volver"
          className="text-ink-2 hover:text-ink-0 p-1.5"
        >
          <ArrowLeft size={18} strokeWidth={1.75} />
        </button>
        <AssetLogo asset={p.asset} isCash={!!p.is_cash} size={28} />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-ink-0 leading-none truncate">{fciLabel(p.asset)}</div>
          <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 leading-none mt-1">
            {p.broker}
          </div>
        </div>
      </header>

      {/* Hero: value + P/L — wrappeado con AskAIAbout para análisis general */}
      <AskAIAbout
        topic="position"
        params={{ asset: p.asset, broker: p.broker }}
        subtitle={`${fciLabel(p.asset)} · ${p.broker}`}
      >
        <section className="px-4 pt-5 pb-3">
          <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-1.5">
            Valor actual
          </div>
          <div className="text-4xl font-medium tabular tracking-tight text-ink-0 leading-none">
            ${Math.round(valueUsd).toLocaleString('en-US')}
            <span className="text-base text-ink-3 ml-1.5 font-normal">USD</span>
          </div>
          {!p.is_cash && pnlUsd != null && (
            <div className={`flex items-center gap-2 mt-3 text-sm font-medium tabular ${colorClass(pnlPct)}`}>
              {pnlPct >= 0
                ? <TrendingUp size={13} strokeWidth={1.75} />
                : <TrendingDown size={13} strokeWidth={1.75} />}
              <span>
                {pnlUsd >= 0 ? '+' : '−'}${Math.abs(Math.round(pnlUsd)).toLocaleString('en-US')}
              </span>
              <span className="text-ink-3 font-mono text-xs">·</span>
              <span>{pctSigned(pnlPct)}</span>
            </div>
          )}
        </section>
      </AskAIAbout>

      {/* Chart 30d (solo non-cash) — sub-topic position.chart */}
      {!p.is_cash && (
        <AskAIAbout
          topic="position.chart"
          params={{ asset: p.asset, broker: p.broker }}
          subtitle={`Precio reciente · ${fciLabel(p.asset)}`}
        >
          <section className="px-4 mb-5">
            <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">
              Precio · últimos 30 días
            </div>
            <div className="bg-bg-1 border border-line/60 rounded-lg p-3">
              <AssetMiniChart symbol={priceSymbol(p.asset, isAR)} />
            </div>
          </section>
        </AskAIAbout>
      )}

      {/* Stats */}
      <section className="px-4 mb-5">
        <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">
          Detalle
        </div>
        <div className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
          {!p.is_cash && (
            <>
              <DetailRow label="Cantidad" value={formatQty(qty)} />
              {avgPrice != null && (
                <DetailRow
                  label="Precio promedio"
                  value={isAR ? `${formatLocalPrice(avgPrice)} ARS` : `$${avgPrice.toFixed(2)} USD`}
                  bordered
                />
              )}
              {priceLocal != null && (
                <DetailRow
                  label="Precio actual"
                  value={isAR ? `${formatLocalPrice(priceLocal)} ARS` : `$${priceLocal.toFixed(2)} USD`}
                  bordered
                />
              )}
              <DetailRow
                label="Invertido"
                value={isAR ? `${formatLocalPrice(invested)} ARS` : `$${Math.round(invested).toLocaleString('en-US')} USD`}
                bordered
              />
              <DetailRow
                label="P/L"
                value={pnlUsd != null
                  ? `${pnlUsd >= 0 ? '+' : '−'}$${Math.abs(Math.round(pnlUsd)).toLocaleString('en-US')} USD`
                  : '—'}
                bordered
                valueTone={pnlPct}
              />
            </>
          )}
          {p.is_cash && (
            <>
              <DetailRow label="Tipo" value="Cash" />
              <DetailRow
                label="Saldo"
                value={isAR ? `${formatLocalPrice(invested)} ARS` : `$${Math.round(invested).toLocaleString('en-US')} USD`}
                bordered
              />
              <DetailRow
                label="Equivalente USD"
                value={`$${Math.round(valueUsd).toLocaleString('en-US')}`}
                bordered
              />
            </>
          )}
          {p.entry_date && (
            <DetailRow label="Fecha de entrada" value={p.entry_date} bordered />
          )}
        </div>
      </section>

      {/* Histórico de operaciones — sub-topic position.lots */}
      {operations.length > 0 && (
      <AskAIAbout
        topic="position.lots"
        params={{ asset: p.asset, broker: p.broker }}
        subtitle={`Historial · ${fciLabel(p.asset)}`}
      >
        <section className="px-4 mb-5">
          <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">
            Operaciones de este activo · {operations.length}
          </div>
          <ul className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
            {operations.map((op, i) => (
              <li
                key={op.id}
                className={`flex items-center gap-3 px-3 py-2.5 ${i > 0 ? 'border-t border-line/30' : ''}`}
              >
                <Calendar size={11} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-ink-1 leading-none">
                    {op.date} · <span className="text-ink-3">{op.op_type || 'op'}</span>
                  </div>
                  {op.quantity != null && (
                    <div className="text-[10px] font-mono text-ink-3 leading-none mt-1">
                      {formatQty(op.quantity)} u.
                    </div>
                  )}
                </div>
                {op.pnl_usd != null && (
                  <div className={`text-sm font-medium tabular leading-none ${colorClass(op.pnl_usd)}`}>
                    {op.pnl_usd >= 0 ? '+' : '−'}${Math.abs(Math.round(op.pnl_usd)).toLocaleString('en-US')}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      </AskAIAbout>
      )}
    </div>
  )
}

// ─── helpers ──────────────────────────────────────────────────────────────

function FullScreen({ children }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center text-center px-6">
      {children}
    </div>
  )
}

function DetailRow({ label, value, bordered, valueTone }) {
  const colorCls = valueTone != null ? colorClass(valueTone) : 'text-ink-0'
  return (
    <div className={`flex items-baseline justify-between px-4 py-2.5 ${bordered ? 'border-t border-line/30' : ''}`}>
      <span className="text-xs text-ink-3">{label}</span>
      <span className={`text-sm font-medium tabular ${colorCls}`}>{value}</span>
    </div>
  )
}

function formatQty(q) {
  if (q == null || isNaN(q)) return '—'
  if (Math.abs(q) >= 1000) return Math.round(q).toLocaleString('en-US')
  if (Math.abs(q) >= 1) return q.toFixed(2).replace(/\.00$/, '')
  return q.toFixed(4)
}

function formatLocalPrice(n) {
  if (n == null || isNaN(n)) return '—'
  return Math.round(n).toLocaleString('es-AR')
}
