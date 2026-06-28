// CarteraList — vista "Tu cartera" de Calidad de cartera (holding-first).
// ═══════════════════════════════════════════════════════════════════════════
// Lo que diferencia a Rendi de un screener genérico: abrimos con TUS acciones y
// CEDEARs, cada una con dos ejes — el negocio (calidad) y el precio (qué pagás) —
// + su peso real y tu P&L. No un buscador vacío. El que no tenés se busca en la
// tab "Explorar". Honestidad: mostramos qué % de la cartera es analizable (cripto,
// bonos AR, FCI y cash no tienen estados financieros que puntuar).
//
// Reusa la matriz de valuación canónica (valueEquityLot/computeBrokerValue) para
// valuar IGUAL que el resto de la app, y /api/fundamentals/{base} (cacheado) por
// fila para el split negocio/precio.

import { useState, useEffect, useMemo, useRef } from 'react'
import { Layers, AlertCircle, ChevronRight } from 'lucide-react'
import Panel from '../Panel'
import Pill from '../Pill'
import EmptyState from '../EmptyState'
import Skeleton from '../Skeleton'
import AssetLogo from '../AssetLogo'
import { api } from '../../utils/api'
import { inferType } from '../../utils/tickers'
import { useCurrency, pickFinancialRate } from '../../contexts/CurrencyContext'
import {
  computeBrokerValue, valueEquityLot, priceSymbol, isArUsdBroker, costInPesos,
} from '../../utils/valuation'
import { businessQuality, priceRead, AXIS_PILL } from './axes'

const baseTicker = (a) => (a || '').replace(/\.BA$/i, '').toUpperCase()

function isEquityLike(p) {
  if (!p || p.is_cash) return false
  const t = inferType(p.asset)
  return t === 'stock_us' || t === 'cedear'
}

const fmtUsd = (n) => (n == null ? '—' : '$' + Math.round(n).toLocaleString('en-US'))
const fmtPct = (n) => (n == null ? '—' : (n >= 0 ? '+' : '') + n.toFixed(1) + '%')

export default function CarteraList({ onOpenTicker }) {
  const { valuationDollar } = useCurrency()
  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [dolar, setDolar] = useState(null)
  const [prices, setPrices] = useState({})
  const [funda, setFunda] = useState({})   // { [base]: data | false }
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const requested = useRef(new Set())
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.get('/positions'),
      api.get('/brokers'),
      api.get('/dolar').catch(() => null),
    ])
      .then(([pos, bkrs, dol]) => {
        if (cancelled) return
        setPositions(Array.isArray(pos) ? pos : (pos?.items || []))
        setBrokers(Array.isArray(bkrs) ? bkrs : (bkrs?.items || []))
        setDolar(dol)
      })
      .catch(e => { if (!cancelled) setErr(e?.message || 'No pudimos cargar tu cartera.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const tcBlue = pickFinancialRate(dolar, valuationDollar) || 1415
  const tcCedear = tcBlue
  const tcCripto = dolar?.cripto?.venta || null

  // Precios de TODAS las posiciones (para el total) + de los equities (para la fila).
  useEffect(() => {
    if (!positions.length || !brokers.length) return
    let cancelled = false
    const arsBrokers = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
    const syms = new Set()
    for (const p of positions) {
      if (p.is_cash || p.asset === 'USDT') continue
      const useBA = arsBrokers.has(p.broker) || isArUsdBroker(p.broker) || costInPesos(p)
      const s = priceSymbol(p.asset, useBA, p.asset_type)
      if (s) syms.add(s)
    }
    const all = [...syms].join(',')
    if (!all) return
    api.get(`/prices?symbols=${encodeURIComponent(all)}`)
      .then(d => { if (!cancelled) setPrices(d || {}) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [positions, brokers])

  // Total de cartera (denominador del peso) — incluye cripto/bonos/cash.
  const totalValue = useMemo(() => {
    if (!brokers.length) return 0
    let v = 0
    for (const b of brokers) v += computeBrokerValue(positions, prices, b, tcBlue, tcCedear, tcCripto).value || 0
    return v
  }, [brokers, positions, prices, tcBlue, tcCedear, tcCripto])

  // Holdings equity/CEDEAR agregados por ticker base.
  const { holdings, analizableValue, excludedCount } = useMemo(() => {
    const brokerByName = Object.fromEntries(brokers.map(b => [b.name, b]))
    const map = new Map()
    let excluded = 0
    for (const p of positions) {
      if (p.is_cash) continue
      if (!isEquityLike(p)) { excluded += 1; continue }
      const base = baseTicker(p.asset)
      const { valueUsd, investedUsd } = valueEquityLot(p, brokerByName[p.broker], prices, tcBlue, tcCedear)
      const h = map.get(base) || { base, valueUsd: 0, investedUsd: 0, brokers: new Set() }
      h.valueUsd += valueUsd || 0
      h.investedUsd += investedUsd || 0
      h.brokers.add(p.broker)
      map.set(base, h)
    }
    let analizable = 0
    const arr = [...map.values()].map(h => {
      analizable += h.valueUsd
      const pnlUsd = h.valueUsd - h.investedUsd
      return {
        base: h.base,
        valueUsd: h.valueUsd,
        investedUsd: h.investedUsd,
        brokers: [...h.brokers],
        pnlUsd,
        pnlPct: h.investedUsd > 0 ? (pnlUsd / h.investedUsd) * 100 : null,
        weight: totalValue > 0 ? (h.valueUsd / totalValue) * 100 : null,
      }
    })
    arr.sort((a, b) => (b.valueUsd || 0) - (a.valueUsd || 0))
    return { holdings: arr, analizableValue: analizable, excludedCount: excluded }
  }, [positions, brokers, prices, tcBlue, tcCedear, totalValue])

  // Fundamentals lazy por ticker base (cacheado en backend; 1 request por activo).
  // NO cancelamos por re-run del effect: `holdings` cambia de identidad cuando
  // llegan precios/total, y un cleanup por-run cancelaría los fetch en vuelo
  // (los dropea → loading eterno). Solo frenamos al desmontar; `requested` evita
  // pedir el mismo ticker dos veces.
  useEffect(() => {
    holdings.forEach(h => {
      if (requested.current.has(h.base)) return
      requested.current.add(h.base)
      api.get('/fundamentals/' + encodeURIComponent(h.base))
        .then(res => { if (mounted.current) setFunda(prev => ({ ...prev, [h.base]: res?.available ? res : false })) })
        .catch(() => { if (mounted.current) setFunda(prev => ({ ...prev, [h.base]: false })) })
    })
  }, [holdings])

  if (loading) return <CarteraSkeleton />

  if (err) {
    return (
      <Panel padding="lg">
        <div className="flex items-start gap-2 text-sm text-rendi-neg">
          <AlertCircle size={16} className="mt-0.5 flex-shrink-0" />
          <span>{err}</span>
        </div>
      </Panel>
    )
  }

  if (!holdings.length) {
    return (
      <Panel padding="lg">
        <EmptyState
          icon={<Layers size={20} strokeWidth={1.75} />}
          eyebrow="TU CARTERA"
          title="Todavía no tenés acciones ni CEDEARs para analizar"
          description="Cuando tengas equities o CEDEARs en tu cartera, los vas a ver acá con su calidad de negocio y su precio. Mientras tanto, podés buscar cualquier activo en la pestaña Explorar."
        />
      </Panel>
    )
  }

  const pctAnalizable = totalValue > 0 ? Math.round((analizableValue / totalValue) * 100) : null

  return (
    <div className="space-y-4">
      {/* Honestidad de cobertura */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-ink-2">
          Tus acciones y CEDEARs, ordenadas por peso en la cartera.
        </p>
        {pctAnalizable != null && (
          <p className="text-[11px] text-ink-3">
            {pctAnalizable}% de tu cartera analizable
            {excludedCount > 0 && ` · ${excludedCount} ${excludedCount === 1 ? 'tenencia' : 'tenencias'} sin fundamentals (cripto, bonos, FCI)`}
          </p>
        )}
      </div>

      <Panel padding="none">
        <div role="table" className="divide-y divide-line">
          {/* header */}
          <div role="row" className="hidden sm:grid grid-cols-[1.6fr_0.7fr_1fr_1fr_0.9fr] gap-3 px-4 py-2.5">
            {['Activo', 'Peso', 'Negocio', 'Precio hoy', 'Tu P&L'].map((h, i) => (
              <span key={h} className={`text-[10px] font-mono uppercase tracking-caps text-ink-3 ${i >= 4 ? 'text-right' : ''}`}>{h}</span>
            ))}
          </div>

          {holdings.map(h => {
            const data = funda[h.base]
            const loadingFund = data === undefined
            const cats = data && data.available ? (data.score?.categories || []) : null
            const neg = cats ? businessQuality(cats) : null
            const prc = cats ? priceRead(cats) : null
            const pnlColor = h.pnlPct == null ? 'text-ink-2' : h.pnlPct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'
            return (
              <button
                key={h.base}
                type="button"
                onClick={() => onOpenTicker(h.base)}
                className="w-full grid grid-cols-[1fr_auto] sm:grid-cols-[1.6fr_0.7fr_1fr_1fr_0.9fr] gap-3 px-4 py-3 items-center text-left hover:bg-bg-2/60 transition-colors"
              >
                {/* activo */}
                <div className="flex items-center gap-2.5 min-w-0">
                  <AssetLogo asset={h.base} size={28} />
                  <div className="min-w-0">
                    <div className="font-mono text-sm font-medium text-ink-0">{h.base}</div>
                    <div className="text-[11px] text-ink-3 truncate">{h.brokers.join(' · ')}</div>
                  </div>
                </div>

                {/* peso (oculto en mobile, se ve en P&L) */}
                <div className="hidden sm:block text-sm text-ink-1 tabular">
                  {h.weight != null ? h.weight.toFixed(1) + '%' : '—'}
                </div>

                {/* negocio */}
                <div className="hidden sm:block">
                  {loadingFund ? <Skeleton className="h-4 w-16 rounded" />
                    : neg ? <Pill tone={AXIS_PILL[neg.tone]}>{neg.label}</Pill>
                    : <span className="text-[11px] text-ink-3">Sin datos</span>}
                </div>

                {/* precio */}
                <div className="hidden sm:block">
                  {loadingFund ? <Skeleton className="h-4 w-16 rounded" />
                    : prc ? <Pill tone={AXIS_PILL[prc.tone]}>{prc.label}</Pill>
                    : <span className="text-[11px] text-ink-3">Sin datos</span>}
                </div>

                {/* P&L + chevron */}
                <div className="flex items-center justify-end gap-2">
                  <div className="text-right">
                    <div className={`text-sm tabular ${pnlColor}`}>{fmtPct(h.pnlPct)}</div>
                    <div className="text-[11px] text-ink-3 tabular sm:hidden">{h.weight != null ? h.weight.toFixed(1) + '% · ' : ''}{fmtUsd(h.valueUsd)}</div>
                  </div>
                  <ChevronRight size={15} className="text-ink-3 flex-shrink-0" />
                </div>

                {/* mobile: pills negocio/precio debajo */}
                <div className="col-span-2 flex gap-2 sm:hidden -mt-1">
                  {loadingFund ? <Skeleton className="h-4 w-24 rounded" /> : (
                    <>
                      {neg && <Pill tone={AXIS_PILL[neg.tone]}>{neg.label}</Pill>}
                      {prc && <Pill tone={AXIS_PILL[prc.tone]}>{prc.label}</Pill>}
                      {!neg && !prc && <span className="text-[11px] text-ink-3">Sin fundamentals</span>}
                    </>
                  )}
                </div>
              </button>
            )
          })}
        </div>
      </Panel>
    </div>
  )
}

function CarteraSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <Skeleton className="h-4 w-64" />
      <Panel padding="none">
        <div className="divide-y divide-line">
          {[0, 1, 2, 3, 4].map(i => (
            <div key={i} className="flex items-center gap-3 px-4 py-3.5">
              <Skeleton className="h-7 w-7 rounded-full" />
              <Skeleton className="h-4 w-20" />
              <div className="flex-1" />
              <Skeleton className="h-4 w-16" />
              <Skeleton className="h-4 w-16" />
            </div>
          ))}
        </div>
      </Panel>
    </div>
  )
}
