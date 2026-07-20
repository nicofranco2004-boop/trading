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
import { priceSymbol, fciLabel, isArUsdBroker, costInPesos, costInUsd, pesoLotUsd, usdLotValue, isFciSym, trustMktValue, costBasisRate } from '../utils/valuation'
import { isCrypto, cryptoBrokerFactor } from '../utils/crypto'
import AskAIAbout from '../components/ai/AskAIAbout'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'

export default function PositionDetailMobile() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { valuationDollar, costBasis } = useCurrency()
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
      // Instrumento BYMA (broker ARS, o sub-broker AR "· USD") → símbolo local .BA.
      const useBA = isAR || isArUsdBroker(p.broker)
      const sym = !p.is_cash
        ? (useBA ? priceSymbol(p.asset, true, p.asset_type) : priceSymbol(p.asset, false, p.asset_type))
        : p.asset
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
          className="text-xs text-data-blue hover:text-rendi-accent font-medium"
        >
          ← Volver
        </button>
      </FullScreen>
    )
  }

  const p = position
  const isAR = brokers.find(b => b.name === p.broker)?.currency === 'ARS'
  const tcBlue = pickFinancialRate(dolar, valuationDollar) || 1415
  const tcCedear = pickFinancialRate(dolar, valuationDollar) || tcBlue  // dólar financiero p/ CEDEARs
  const tcCripto = dolar?.cripto?.venta  // dólar cripto p/ valuar crypto en broker AR
  const qty = p.quantity || 0
  const invested = p.invested || 0
  // Crypto en broker (no exchange) se valúa al dólar cripto (~MEP); en exchange queda a spot.
  const isExch = !!brokers.find(b => b.name === p.broker)?.is_exchange
  const cryptoF = cryptoBrokerFactor(p.asset, isExch, p.price_override != null, tcCripto, tcCedear)

  // Compute current value + P/L
  let valueUsd = 0, priceLocal = null, pnlUsd = null, pnlPct = null
  if (p.is_cash) {
    valueUsd = isAR ? invested / tcBlue : invested
  } else if (costInPesos(p) && !isAR) {
    // Lote en PESOS (currency='ARS') en una cuenta USD: costo Y valor a USD por el
    // dólar-MEP (.BA ÷ tcCedear), igual que un CEDEAR. NO contar los pesos como
    // dólares (inflaba invertido/P&L). pesoLotUsd suma commissions al costo.
    const u = pesoLotUsd(p, prices, tcCedear)   // valor + costo a HOY (guard/fallback)
    // Guard anti-distorsión: un ×100 (bono per-100) o colisión de ticker cae a costo.
    // Guardea con el costo de HOY (u.investedUsd) → 'purchase' no afloja el guard.
    const priced = trustMktValue(u.valueUsd, u.investedUsd, p.asset_type, p.price_override != null)
    // Costo DISPLAY del modo: solo con precio confiable (sin precio el P&L es 0 → el
    // modo no aplica, no inventamos pérdida por devaluación). En 'today' === u.investedUsd.
    const investedUsdDisplay = priced ? pesoLotUsd(p, prices, tcCedear, costBasis).investedUsd : u.investedUsd
    valueUsd = priced ? u.valueUsd : investedUsdDisplay
    priceLocal = u.priceUsd
    pnlUsd = valueUsd - investedUsdDisplay
    pnlPct = investedUsdDisplay > 0 ? pnlUsd / investedUsdDisplay : 0
  } else if (costInUsd(p) && isAR) {
    // Espejo de costInPesos: lote de COSTO EN DÓLARES (bono/ON/FCI-USD, o CEDEAR
    // comprado en dólar-MEP → currency='USD') que vive en un broker ARS (Balanz).
    // El costo YA está en USD (sin ÷blue); el valor va por el tipo de instrumento
    // (usdLotValue: CEDEAR/acción-AR por .BA÷MEP, resto por precio USD nativo). Sin
    // esto, la rama isAR de abajo dividía el costo USD por el blue → colapsaba.
    const u = usdLotValue(p, prices, tcCedear)
    valueUsd = u.valueUsd
    priceLocal = u.priceUsd
    pnlUsd = valueUsd - u.investedUsd
    pnlPct = u.investedUsd > 0 ? pnlUsd / u.investedUsd : 0
  } else if (isAR) {
    priceLocal = p.price_override ?? prices[priceSymbol(p.asset, true)]
    const investedUsd = invested / tcBlue   // hoy
    // mkt y cost comparados en la MISMA moneda (ARS, nativo → mode-independent): un
    // bono per-100 (×100) o colisión de ticker cae a costo (P&L 0 para esta posición).
    const mktArs = priceLocal != null ? priceLocal * qty : null
    const trustArs = mktArs != null && trustMktValue(mktArs, invested, p.asset_type, p.price_override != null)
    // Costo DISPLAY del modo: solo con precio confiable. En 'today' === investedUsd.
    const investedUsdDisplay = trustArs ? invested / costBasisRate(p, tcBlue, costBasis) : investedUsd
    valueUsd = trustArs ? mktArs / tcBlue : investedUsdDisplay
    pnlUsd = valueUsd - investedUsdDisplay
    pnlPct = investedUsdDisplay > 0 ? pnlUsd / investedUsdDisplay : 0
  } else if ((p.asset_type === 'CEDEAR' || isArUsdBroker(p.broker)) && !isCrypto(p.asset) && !isFciSym(p.asset) && p.price_override == null) {
    // Instrumento BYMA en broker USD (CEDEAR o acción AR en un sub-broker "· USD"):
    // precio LOCAL .BA (ARS) → USD via MEP, no el ticker US (que vale 15-100× más,
    // y las acciones AR ni existen como acción US → quedaban en "—"). El FCI-USD NO
    // entra: su precio es el NAV en USD (va al else, sin ÷MEP).
    const priceArs = prices[priceSymbol(p.asset, true, p.asset_type)]
    priceLocal = priceArs != null ? priceArs / tcCedear : null
    // mkt y cost en la MISMA moneda (USD): un bono per-100 (×100) cae a costo.
    const mktUsd = priceLocal != null ? priceLocal * qty : null
    valueUsd = (mktUsd != null && trustMktValue(mktUsd, invested, p.asset_type, p.price_override != null)) ? mktUsd : invested
    pnlUsd = valueUsd - invested
    pnlPct = invested > 0 ? pnlUsd / invested : 0
  } else {
    priceLocal = p.price_override ?? prices[p.asset]
    // Crypto en broker AR (no exchange) → factor ~MEP sobre value y costo (P/L% invariante).
    if (cryptoF !== 1 && priceLocal != null) priceLocal = priceLocal * cryptoF
    const investedF = invested * cryptoF
    // mkt y cost en la MISMA moneda (USD, ambos con el factor cripto aplicado):
    // un bono per-100 (×100) o colisión de ticker cae a costo (P&L 0).
    const mkt = priceLocal != null ? priceLocal * qty : null
    valueUsd = (mkt != null && trustMktValue(mkt, investedF, p.asset_type, p.price_override != null)) ? mkt : investedF
    pnlUsd = valueUsd - investedF
    pnlPct = investedF > 0 ? pnlUsd / investedF : 0
  }

  const avgPrice = !p.is_cash && qty > 0 ? invested / qty : null

  // Moneda de los labels de precio/costo del lote. Normalmente ARS en broker ARS,
  // USD en broker USD. PERO un lote de COSTO EN DÓLARES en un broker ARS (bono/ON/
  // FCI-USD, CEDEAR-MEP de Balanz → currency='USD') tiene invested/avgPrice/priceLocal
  // YA en USD (priceLocal = usdLotValue.priceUsd) → hay que rotularlos "USD", no "ARS"
  // (si no, se muestra un valor USD con label ARS, off por el MEP). Se decide por la
  // moneda del COSTO del lote, no solo por isAR.
  const lotShowsUsd = !isAR || costInUsd(p)

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
          <div className="text-[12.5px] text-ink-2 leading-none mt-1 font-medium">
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
          <div className="text-[12.5px] text-ink-2 mb-1.5 font-medium">
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
            <div className="text-[12.5px] text-ink-2 mb-2 font-medium">
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
        <div className="text-[12.5px] text-ink-2 mb-2 font-medium">
          Detalle
        </div>
        <div className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
          {!p.is_cash && (
            <>
              <DetailRow label="Cantidad" value={formatQty(qty)} />
              {avgPrice != null && (
                <DetailRow
                  label="Precio promedio"
                  value={lotShowsUsd ? `$${avgPrice.toFixed(2)} USD` : `${formatLocalPrice(avgPrice)} ARS`}
                  bordered
                />
              )}
              {priceLocal != null && (
                <DetailRow
                  label="Precio actual"
                  value={lotShowsUsd ? `$${priceLocal.toFixed(2)} USD` : `${formatLocalPrice(priceLocal)} ARS`}
                  bordered
                />
              )}
              <DetailRow
                label="Invertido"
                value={lotShowsUsd ? `$${Math.round(invested).toLocaleString('en-US')} USD` : `${formatLocalPrice(invested)} ARS`}
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
          <div className="text-[12.5px] text-ink-2 mb-2 font-medium">
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
