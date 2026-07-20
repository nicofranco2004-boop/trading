// CarteraList — la HOME de Calidad de cartera (holding-first, sin pestañas).
// ═══════════════════════════════════════════════════════════════════════════
// Abre con TUS acciones y CEDEARs valuadas (peso, P&L) y los dos ejes Negocio /
// Precio por fila. Debajo, "Que seguís" (watchlist que no tenés). Tocar una fila
// abre su ficha; comparar se arranca DESDE la ficha (botón "Comparar"), no desde
// acá. Honestidad: mostramos qué % de la cartera es analizable.
//
// Reusa la valuación canónica (valueEquityLot/computeBrokerValue) y
// /api/fundamentals/{base} (cacheado) por fila para el split negocio/precio.

import { useState, useEffect, useMemo, useRef } from 'react'
import { Layers, AlertCircle, ChevronRight } from 'lucide-react'
import Panel from '../Panel'
import Pill from '../Pill'
import EmptyState from '../EmptyState'
import Skeleton from '../Skeleton'
import AssetLogo from '../AssetLogo'
import { api } from '../../utils/api'
import { inferType, cedearEspecieBase } from '../../utils/tickers'
import { useCurrency, pickFinancialRate } from '../../contexts/CurrencyContext'
import {
  computeBrokerValue, valueEquityLot, priceSymbol, isArUsdBroker, costInPesos,
  holdingHasReliableFundamentals,
} from '../../utils/valuation'
import { businessQuality, priceRead, AXIS_PILL } from './axes'

const baseTicker = (a) => (a || '').replace(/\.BA$/i, '').toUpperCase()

function isEquityLike(p) {
  if (!p || p.is_cash) return false
  const t = inferType(p.asset)
  return t === 'stock_us' || t === 'cedear'
}
const symHasFund = (s) => { const t = inferType(s); return t === 'stock_us' || t === 'cedear' }

const fmtPct = (n) => (n == null ? '—' : (n >= 0 ? '+' : '') + n.toFixed(1) + '%')

export default function CarteraList({ onOpenTicker, watchlist }) {
  const { valuationDollar } = useCurrency()
  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [dolar, setDolar] = useState(null)
  const [prices, setPrices] = useState({})
  const [funda, setFunda] = useState({})           // { [base]: data | false }
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

  const totalValue = useMemo(() => {
    if (!brokers.length) return 0
    let v = 0
    for (const b of brokers) v += computeBrokerValue(positions, prices, b, tcBlue, tcCedear, tcCripto).value || 0
    return v
  }, [brokers, positions, prices, tcBlue, tcCedear, tcCripto])

  const { holdings, heldBases, analizableValue, excludedCount } = useMemo(() => {
    const brokerByName = Object.fromEntries(brokers.map(b => [b.name, b]))
    const arsBrokers = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
    const map = new Map()
    let excluded = 0
    for (const p of positions) {
      if (p.is_cash) continue
      // Fuera lo no-equity (cripto/bono/FCI) Y las tenencias SIN fundamentals
      // confiables: una acción local o una especie dólar-MEP (ej. 'SID') en un
      // broker AR NO se analiza como su homónima yanqui al azar (que daría dos
      // "empresas" con veredictos opuestos). Ver holdingHasReliableFundamentals.
      if (!isEquityLike(p) || !holdingHasReliableFundamentals(p, arsBrokers)) { excluded += 1; continue }
      // Base canónica: en contexto AR aplicamos alias de especie → la pata pesos
      // 'SI' y la dólar 'SID' del CEDEAR de CSN colapsan en UN holding, analizado
      // por su ticker NYSE real. En broker US el ticker queda como está.
      const onBA = arsBrokers.has(p.broker) || isArUsdBroker(p.broker) || costInPesos(p)
      const base = onBA ? cedearEspecieBase(p.asset) : baseTicker(p.asset)
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
        base: h.base, valueUsd: h.valueUsd, brokers: [...h.brokers],
        pnlPct: h.investedUsd > 0 ? (pnlUsd / h.investedUsd) * 100 : null,
        weight: totalValue > 0 ? (h.valueUsd / totalValue) * 100 : null,
      }
    })
    arr.sort((a, b) => (b.valueUsd || 0) - (a.valueUsd || 0))
    return { holdings: arr, heldBases: new Set(arr.map(h => h.base)), analizableValue: analizable, excludedCount: excluded }
  }, [positions, brokers, prices, tcBlue, tcCedear, totalValue])

  // "Que seguís" = watchlist equity/CEDEAR que NO tenés (las que tenés ya están arriba).
  const followed = useMemo(() => {
    const syms = (watchlist?.symbols || []).filter(symHasFund).map(baseTicker)
    return [...new Set(syms)].filter(b => !heldBases.has(b))
  }, [watchlist?.symbols, heldBases])

  // Fundamentals lazy por ticker base (cartera + seguidas). Freno solo al desmontar.
  useEffect(() => {
    const all = [...holdings.map(h => h.base), ...followed]
    all.forEach(base => {
      if (requested.current.has(base)) return
      requested.current.add(base)
      api.get('/fundamentals/' + encodeURIComponent(base))
        .then(res => { if (mounted.current) setFunda(prev => ({ ...prev, [base]: res?.available ? res : false })) })
        .catch(() => { if (mounted.current) setFunda(prev => ({ ...prev, [base]: false })) })
    })
  }, [holdings, followed])

  // ── Fila reutilizable (cartera + seguidas) ───────────────────────────────
  const Row = ({ base, brokers: brks, weight, pnlPct }) => {
    const data = funda[base]
    const loadingFund = data === undefined
    const cats = data && data.available ? (data.score?.categories || []) : null
    const neg = cats ? businessQuality(cats) : null
    const prc = cats ? priceRead(cats) : null
    const pnlColor = pnlPct == null ? 'text-ink-2' : pnlPct >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'
    return (
      <button
        type="button"
        onClick={() => onOpenTicker(base)}
        className="w-full grid grid-cols-[1.6fr_auto_auto] sm:grid-cols-[1.7fr_0.7fr_0.9fr_0.9fr_0.8fr] gap-x-3 gap-y-1 px-4 py-3 items-center text-left hover:bg-bg-2/60 transition-colors"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <AssetLogo asset={base} size={28} />
          <div className="min-w-0">
            <div className="font-mono text-sm font-medium text-ink-0">{base}</div>
            <div className="text-[11px] text-ink-3 truncate">{brks?.length ? brks.join(' · ') : 'No la tenés'}</div>
          </div>
        </div>

        <div className="hidden sm:block text-sm text-ink-1 tabular">{weight != null ? weight.toFixed(1) + '%' : '—'}</div>

        <div>
          {loadingFund ? <Skeleton className="h-4 w-16 rounded" />
            : neg ? <Pill tone={AXIS_PILL[neg.tone]}>{neg.label}</Pill>
            : <span className="text-[11px] text-ink-3">Sin datos</span>}
        </div>
        <div>
          {loadingFund ? <Skeleton className="h-4 w-16 rounded" />
            : prc ? <Pill tone={AXIS_PILL[prc.tone]}>{prc.label}</Pill>
            : <span className="text-[11px] text-ink-3" />}
        </div>

        <div className="flex items-center justify-end gap-2">
          <span className={`hidden sm:block text-sm tabular ${pnlColor}`}>{pnlPct == null ? '' : fmtPct(pnlPct)}</span>
          <ChevronRight size={15} className="text-ink-3 flex-shrink-0" />
        </div>
      </button>
    )
  }

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

  const pctAnalizable = totalValue > 0 ? Math.round((analizableValue / totalValue) * 100) : null
  const nothing = holdings.length === 0 && followed.length === 0

  if (nothing) {
    return (
      <Panel padding="lg">
        <EmptyState
          icon={<Layers size={20} strokeWidth={1.75} />}
          eyebrow="TU CARTERA"
          title="Todavía no tenés acciones ni CEDEARs para analizar"
          description="Cuando tengas equities o CEDEARs los vas a ver acá con su calidad de negocio y su precio. Mientras tanto, tocá “Buscar activo” para mirar cualquiera."
        />
      </Panel>
    )
  }

  return (
    <div className="space-y-5">
      {holdings.length > 0 && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-ink-2">Tus acciones y CEDEARs, ordenadas por peso en la cartera.</p>
            {pctAnalizable != null && (
              <p className="text-[11px] text-ink-3">
                {pctAnalizable}% de tu cartera analizable
                {excludedCount > 0 && ` · ${excludedCount} ${excludedCount === 1 ? 'tenencia' : 'tenencias'} sin fundamentals (cripto, bonos, FCI, acciones locales)`}
              </p>
            )}
          </div>
          <Panel padding="none">
            <div role="table" className="divide-y divide-line">
              <div role="row" className="hidden sm:grid grid-cols-[1.7fr_0.7fr_0.9fr_0.9fr_0.8fr] gap-3 px-4 py-2.5">
                {['Activo', 'Peso', 'Negocio', 'Precio hoy', 'Tu P&L'].map((h, i) => (
                  <span key={h} className={`text-[12px] text-ink-3 ${i === 4 ? 'text-right' : ''} font-medium`}>{h}</span>
                ))}
              </div>
              {holdings.map(h => (
                <Row key={h.base} base={h.base} brokers={h.brokers} weight={h.weight} pnlPct={h.pnlPct} />
              ))}
            </div>
          </Panel>
        </div>
      )}

      {followed.length > 0 && (
        <div className="space-y-3">
          <p className="text-[12.5px] text-ink-3 font-medium">Que seguís</p>
          <Panel padding="none">
            <div role="table" className="divide-y divide-line">
              {followed.map(base => (
                <Row key={base} base={base} brokers={null} weight={null} pnlPct={null} />
              ))}
            </div>
          </Panel>
        </div>
      )}
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
