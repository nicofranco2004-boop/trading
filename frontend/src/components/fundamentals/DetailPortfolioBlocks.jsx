// DetailPortfolioBlocks — lo que DIFERENCIA a Rendi de un screener genérico, en
// el detalle de un activo: (1) "Tu posición" — tu costo/P&L y el espectro de
// precio con TU costo marcado (tu costo · hoy · valor justo); (2) "¿Rinde más
// que?" — el retorno fundamental de la acción (en USD) contra tus alternativas
// reales del inversor AR (plazo fijo en pesos, quedarte en dólar). Vesty no puede
// hacer esto porque no conoce tu cartera ni el contexto argentino.
//
// Descriptivo, nunca prescriptivo (no "comprá/vendé"): respeta el guardrail de
// Rendi y CNV. El plazo fijo se muestra en PESOS, sin convertir a dólares con un
// supuesto escondido — la diferencia de moneda/riesgo se explica en el pie.

import { useState, useEffect } from 'react'
import { Wallet, Scale } from 'lucide-react'
import Panel from '../Panel'
import { api } from '../../utils/api'
import { costInPesos, costInUsd, valueEquityLot, isArUsdBroker } from '../../utils/valuation'
import { useCurrency, pickFinancialRate } from '../../contexts/CurrencyContext'

const baseOf = (a) => (a || '').replace(/\.BA$/i, '').toUpperCase()
const fmtUsd = (n) => (n == null ? '—' : '$' + Math.round(n).toLocaleString('en-US'))
const fmtUsd2 = (n) => (n == null ? '—' : '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }))
const fmtPct = (n, sign = false) => (n == null ? '—' : (sign && n >= 0 ? '+' : '') + n.toFixed(1) + '%')

// Costo USD de un lote (sin precio live): pesos→USD por el dólar financiero, USD
// queda como está. Espeja la convención de valueLot/valueEquityLot para el COSTO.
function lotCostUsd(p, isAR, tc) {
  const invested = p.invested || 0
  // Lote de COSTO EN DÓLARES (bono/ON/FCI-USD, o CEDEAR comprado en dólar-MEP →
  // currency='USD') que vive en un broker ARS: el costo YA está en USD → NO se
  // divide por el dólar (va antes que isAR, que sí dividiría y lo colapsaría).
  // Gateado a broker ARS: una acción US genuina en broker USD cae al último return
  // (invested, ya en USD) — mismo resultado, pero sin aplicarle semántica "es-ARS".
  if (isAR && costInUsd(p)) return invested
  if (costInPesos(p) || isAR) return invested / tc
  return invested
}

// ── Espectro de precio: 52w low → high, con marcadores hoy / valor justo / tu costo ──
function PriceSpectrum({ low, high, current, fairValue, cost }) {
  const lo = low, hi = high
  if (lo == null || hi == null || !(hi > lo)) return null
  const pos = (v) => (v == null ? null : Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100)))
  const markers = [
    cost != null && { p: pos(cost), color: 'var(--ink-2, #888)', cls: 'bg-ink-2', label: 'Tu costo', val: fmtUsd2(cost) },
    { p: pos(fairValue), cls: 'bg-rendi-pos', label: 'Valor justo', val: fmtUsd2(fairValue) },
    { p: pos(current), cls: 'bg-rendi-warn', label: 'Hoy', val: fmtUsd2(current), big: true },
  ].filter(Boolean).filter(m => m.p != null)
  return (
    <div>
      <div className="relative h-1.5 rounded-full bg-bg-2 border border-line mt-7 mb-2 mx-1.5">
        {markers.map((m, i) => (
          <div key={i} className={`absolute top-1/2 rounded-full ${m.cls} ${m.big ? 'w-3 h-3' : 'w-2.5 h-2.5'}`}
            style={{ left: `${m.p}%`, transform: 'translate(-50%,-50%)' }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mx-1.5">
        {markers.map((m, i) => (
          <span key={i} className="inline-flex items-center gap-1.5 text-[11px] text-ink-2">
            <span className={`inline-block w-2 h-2 rounded-full ${m.cls}`} />
            {m.label} {m.val}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function DetailPortfolioBlocks({ ticker, data }) {
  const { valuationDollar } = useCurrency()
  const [positions, setPositions] = useState(null)
  const [brokers, setBrokers] = useState([])
  const [dolar, setDolar] = useState(null)
  const [pfs, setPfs] = useState([])
  const [prices, setPrices] = useState({})

  // Precios live del activo, incluído el símbolo .BA (CEDEAR / acción AR). Se usan
  // para valuar la posición a mercado y para llevar tu costo del CEDEAR a la escala
  // de la acción US (ratio = precioAcciónUS ÷ precioCEDEAR_USD).
  useEffect(() => {
    const b = baseOf(ticker)
    if (!b) return
    let cancelled = false
    api.get(`/prices?symbols=${b},${b}.BA`)
      .then(pr => { if (!cancelled) setPrices(pr || {}) })
      .catch(() => { /* silent — sin precios caemos a costo */ })
    return () => { cancelled = true }
  }, [ticker])

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.get('/positions').catch(() => []),
      api.get('/brokers').catch(() => []),
      api.get('/dolar').catch(() => null),
      api.get('/plazos-fijos').catch(() => []),
    ]).then(([pos, bkrs, dol, pf]) => {
      if (cancelled) return
      setPositions(Array.isArray(pos) ? pos : (pos?.items || []))
      setBrokers(Array.isArray(bkrs) ? bkrs : (bkrs?.items || []))
      setDolar(dol)
      setPfs(Array.isArray(pf) ? pf : (pf?.items || []))
    })
    return () => { cancelled = true }
  }, [])

  if (!data?.available) return null
  const tc = pickFinancialRate(dolar, valuationDollar) || 1415
  const base = baseOf(ticker)
  const price = data.price || {}
  const m = data.metrics || {}

  // ── Tu posición (si la tenés) ──────────────────────────────────────────────
  let owned = null
  if (positions) {
    const brokerByName = Object.fromEntries(brokers.map(b => [b.name, b]))
    let qty = 0, costUsd = 0; const brk = new Set(); const lots = []
    // ¿La posición es un instrumento de BYMA (se valúa por su precio LOCAL .BA ÷ MEP,
    // no por el ticker US)? CEDEAR, broker AR, o sub-broker AR "· USD" con acciones AR.
    // price.current_usd es la ACCIÓN US → para estos infla ~ratio× vs el CEDEAR.
    let anyLocal = false, allLocal = true
    for (const p of positions) {
      if (p.is_cash || baseOf(p.asset) !== base) continue
      const broker = brokerByName[p.broker]
      const isAR = broker?.currency === 'ARS'
      qty += p.quantity || 0
      costUsd += lotCostUsd(p, isAR, tc)
      brk.add(p.broker)
      lots.push({ p, broker })
      const local = p.asset_type === 'CEDEAR' || isAR || isArUsdBroker(p.broker)
      anyLocal = anyLocal || local
      allLocal = allLocal && local
    }
    if (qty > 1e-9) {
      const avgCostUsd = costUsd / qty
      const cur = price.current_usd
      // Valor real a mercado: cada lote por su propio tipo (CEDEAR→.BA÷MEP, acción
      // US→precio US). valueEquityLot ya trae el clamp anti-distorsión (trustMktValue).
      let valueUsd = 0
      for (const { p, broker } of lots) valueUsd += valueEquityLot(p, broker, prices, tc, tc).valueUsd

      // costOnAxis = tu costo EN LA ESCALA del precio mostrado (la acción US). Para un
      // CEDEAR/acción AR hay que multiplicar por el ratio (CEDEARs por acción); sino
      // "Tu costo" cae abajo de todo y parece que compraste baratísimo.
      let costOnAxis = avgCostUsd
      let converted = false
      if (allLocal) {
        const priceBa = prices[base + '.BA']
        const nowUsdPerUnit = priceBa > 0 && tc > 0 ? priceBa / tc : null   // precio USD del CEDEAR
        const ratio = nowUsdPerUnit != null && cur > 0 ? cur / nowUsdPerUnit : null  // acción US ÷ CEDEAR
        if (ratio != null && Number.isFinite(ratio) && ratio > 0) {
          costOnAxis = avgCostUsd * ratio   // tu costo, llevado a la acción US
          converted = true
        } else {
          costOnAxis = null   // sin precio .BA → no marcamos "Tu costo" (evita el falso barato)
        }
      } else if (anyLocal) {
        costOnAxis = null   // mezcla CEDEAR + acción US bajo el mismo ticker → dos escalas
      }

      const pnlUsd = valueUsd - costUsd
      owned = {
        qty, costUsd, brokers: [...brk],
        avgCostUsd, costOnAxis, isLocalByma: anyLocal, converted,
        valueUsd, pnlUsd,
        pnlPct: costUsd > 0 && costOnAxis != null ? (pnlUsd / costUsd) * 100 : null,
      }
    }
  }

  // ── ¿Rinde más que? ────────────────────────────────────────────────────────
  const ey = m.trailing_pe > 0 ? 100 / m.trailing_pe : null         // earnings yield %
  const dy = m.dividend_yield_pct != null ? m.dividend_yield_pct : null
  const fundReturn = ey != null ? ey + (dy || 0) : null
  // Plazo fijo representativo del user → TEA en pesos.
  let pfTea = null
  for (const pf of pfs) {
    const t = Number(pf.tasa)
    if (!Number.isFinite(t) || t <= 0) continue
    const tea = (pf.rate_type === 'TEA') ? t : Math.pow(1 + t / 12, 12) - 1
    pfTea = Math.max(pfTea ?? 0, tea * 100)
  }

  const isCedear = data.currency && data.currency !== 'USD' ? false : true
  const unitWord = owned && (data.sector || isCedear) ? 'nominales' : 'unidades'

  return (
    <>
      {/* Tu posición — el ancla portfolio-aware. Solo si la tenés. */}
      <Panel padding="lg">
        <div className="flex items-center gap-2 mb-3">
          <Wallet size={15} strokeWidth={1.75} className="text-data-violet" />
          <h3 className="text-sm font-semibold text-ink-0">{owned ? 'Tu posición' : 'Precio vs valor justo'}</h3>
        </div>

        {owned && (
          <p className="text-sm text-ink-1 leading-relaxed mb-1">
            Tenés <span className="font-medium text-ink-0">{owned.qty.toLocaleString('en-US')} {base}</span>
            {' '}en {owned.brokers.join(' · ')}
            {owned.costOnAxis != null && (<>
              {' '}· costo prom <span className="font-medium">{fmtUsd2(owned.costOnAxis)}</span>
              {' '}· hoy <span className="font-medium">{fmtUsd2(price.current_usd)}</span>
              {owned.pnlPct != null && (
                <span className={owned.pnlPct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}> ({fmtPct(owned.pnlPct, true)})</span>
              )}
            </>)}
          </p>
        )}

        {owned?.isLocalByma && (
          <p className="text-[11px] text-ink-3 leading-relaxed mb-1">
            {owned.converted
              ? `${base} lo tenés vía CEDEAR (una fracción de la acción US): tu costo se muestra llevado a la acción para poder compararlo (≈ ${fmtUsd2(owned.avgCostUsd)} por CEDEAR).`
              : `${base} lo tenés vía CEDEAR (una fracción de la acción US). El precio y el valor justo de abajo son de la acción US.`}
          </p>
        )}

        <PriceSpectrum
          low={m.week_52_low_usd}
          high={m.week_52_high_usd}
          current={price.current_usd}
          fairValue={price.fair_value_usd}
          cost={owned?.costOnAxis}
        />

        {price.margin_of_safety_pct != null && (
          <p className="text-xs text-ink-2 mt-3 leading-relaxed">
            {price.margin_of_safety_pct >= 0
              ? `Cotiza ~${Math.abs(price.margin_of_safety_pct).toFixed(0)}% por debajo del valor justo que estiman los analistas`
              : `Cotiza ~${Math.abs(price.margin_of_safety_pct).toFixed(0)}% por encima del valor justo que estiman los analistas`}
            {data.analysts?.n_analysts ? ` (consenso de ${data.analysts.n_analysts}).` : '.'}
          </p>
        )}
      </Panel>

      {/* ¿Rinde más que? — el benchmark del inversor AR. */}
      {fundReturn != null && (
        <Panel padding="lg">
          <div className="flex items-center gap-2 mb-1">
            <Scale size={15} strokeWidth={1.75} className="text-data-violet" />
            <h3 className="text-sm font-semibold text-ink-0">¿Rinde más que tus alternativas?</h3>
          </div>
          <p className="text-[11px] text-ink-3 mb-4">Lo que genera el negocio por año, en dólares.</p>

          <div className="space-y-3">
            <YieldRow label={`${base} (retorno fundamental)`} pct={fundReturn} max={Math.max(fundReturn, 6)} tone="bg-rendi-pos" />
            <YieldRow label="Quedarte en dólar" pct={0} max={Math.max(fundReturn, 6)} tone="bg-ink-3" />
          </div>

          <p className="text-xs text-ink-2 mt-4 leading-relaxed">
            {dy != null && `Incluye ~${ey.toFixed(1)}% de earnings yield + ~${dy.toFixed(1)}% de dividendos. `}
            Es retorno de acción (con riesgo), no garantizado.
            {pfTea != null
              ? ` Tu plazo fijo rinde ~${pfTea.toFixed(0)}% TEA pero en pesos: en dólares solo te gana si el dólar sube menos que esa tasa.`
              : ' Compará contra tu plazo fijo (en pesos) y la inflación según tu caso.'}
          </p>
        </Panel>
      )}
    </>
  )
}

function YieldRow({ label, pct, max, tone }) {
  const w = max > 0 ? Math.max(2, Math.min(100, (pct / max) * 100)) : 2
  return (
    <div className="grid grid-cols-[1fr_auto] sm:grid-cols-[200px_1fr_56px] gap-x-3 gap-y-1 items-center">
      <span className="text-sm text-ink-1">{label}</span>
      <div className="hidden sm:block h-2 rounded-full bg-bg-2 overflow-hidden">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${w}%` }} />
      </div>
      <span className="text-sm text-ink-1 tabular text-right">{pct.toFixed(1)}%</span>
    </div>
  )
}
