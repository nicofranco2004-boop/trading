// FirstInsight — pantalla de "primer insight" post-import (Sprint 2).
// ═══════════════════════════════════════════════════════════════════════════
// Cuando el user completa su PRIMER import exitoso, lo redirigimos acá en
// lugar de a la tabla administrativa /imports. Es el primer momento de
// dopamina: "Acá está tu portfolio. Esto vale tu plata. Esto es lo que
// movió la aguja". Después, CTA al Dashboard.
//
// Trigger: localStorage flag `rendi_first_import_done` se setea acá la
// primera vez y nunca más vuelve. Si el user importa de nuevo no aparece.

import { useEffect, useState, useMemo } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Sparkles, TrendingUp, TrendingDown, ArrowRight, Wallet } from 'lucide-react'
import { api } from '../utils/api'
import { computeBrokerValue, priceSymbol, costInPesos, pesoLotUsd } from '../utils/valuation'
import { isCrypto, cryptoBrokerFactor } from '../utils/crypto'
import { fmtUsd, usd, pctSigned } from '../utils/format'
import AssetLogo from '../components/AssetLogo'
import { track } from '../utils/track'
import Panel from '../components/Panel'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import { useCurrency, pickFinancialRate } from '../contexts/CurrencyContext'

export default function FirstInsight() {
  const navigate = useNavigate()
  const coachDrawer = useCoachDrawer()
  const { valuationDollar } = useCurrency()
  const [positions, setPositions] = useState([])
  const [brokers, setBrokers] = useState([])
  const [prices, setPrices] = useState({})
  const [dolar, setDolar] = useState(null)
  const [loading, setLoading] = useState(true)

  // CTA al Coach IA post-import: abre el drawer con una pregunta pre-cargada
  // que el bot responde con contexto de la cartera recién importada. Navegamos
  // al dashboard primero (el drawer vive a nivel App; FirstInsight es full-screen)
  // — mismo patrón que CompleteStep. La pregunta está en la whitelist (main.py).
  function askCoach() {
    track('first_insight_coach_cta')
    navigate('/dashboard')
    setTimeout(() => coachDrawer?.open?.('¿Mi nivel de concentración es elevado?'), 300)
  }

  // Si el user llega acá desde el flow de onboarding (ImportWizard lo seteó),
  // lo redirigimos al CompleteStep del wizard en lugar del FirstInsight clásico.
  // Mejor UX: cierra el loop del onboarding con celebración + 3 cards CTAs
  // en vez de quedar varado en FirstInsight sin guidance hacia el dashboard.
  useEffect(() => {
    let pending = false
    try { pending = localStorage.getItem('rendi_onboarding_pending') === '1' } catch {}
    if (pending) {
      try { localStorage.removeItem('rendi_onboarding_pending') } catch {}
      navigate('/onboarding?step=complete', { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    track('first_insight_viewed')
    Promise.all([
      api.get('/positions'),
      api.get('/brokers'),
      api.get('/dolar').catch(() => null),
    ]).then(async ([pos, bkrs, dol]) => {
      setPositions(pos || [])
      setBrokers(bkrs || [])
      setDolar(dol)
      // Fetch precios de los assets
      const arsBrokers = new Set((bkrs || []).filter(b => b.currency === 'ARS').map(b => b.name))
      // Un lote en pesos (currency='ARS') alojado en cuenta USD pide su precio LOCAL .BA.
      const usdSyms = [...new Set((pos || []).filter(p => !arsBrokers.has(p.broker) && !p.is_cash).map(p => priceSymbol(p.asset, costInPesos(p), p.asset_type)))]
      const arsSyms = [...new Set((pos || []).filter(p => arsBrokers.has(p.broker) && !p.is_cash).map(p => priceSymbol(p.asset, true)))]
      const all = [...usdSyms, ...arsSyms].join(',')
      if (all) {
        try {
          const data = await api.get(`/prices?symbols=${all}`)
          setPrices(data || {})
        } catch {}
      }
    }).finally(() => setLoading(false))
  }, [])

  const tcBlue = pickFinancialRate(dolar, valuationDollar) || 1415
  const tcCedear = pickFinancialRate(dolar, valuationDollar) || tcBlue  // dólar financiero p/ CEDEARs
  const tcCripto = dolar?.cripto?.venta

  const stats = useMemo(() => {
    if (!brokers.length || !positions.length) return null
    let value = 0, invested = 0
    for (const b of brokers) {
      const r = computeBrokerValue(positions, prices, b, tcBlue, tcCedear, tcCripto)
      value += r.value || 0
      invested += r.invested || 0
    }
    const pnl = value - invested
    const pnlPct = invested > 0 ? pnl / invested : 0

    // Mejor y peor activo por P&L USD individual
    const arsBrokers = new Set(brokers.filter(b => b.currency === 'ARS').map(b => b.name))
    const exchangeBrokers = new Set((brokers || []).filter(b => b.is_exchange).map(b => b.name))
    const byAsset = new Map()
    for (const p of positions) {
      if (p.is_cash) continue
      const isARS = arsBrokers.has(p.broker)
      const cost = (p.invested || 0) + (p.commissions || 0)
      let valueUsd = null, pnlUsd = null
      if (isARS) {
        const priceArs = p.price_override ?? prices[priceSymbol(p.asset, true)]
        if (priceArs != null) {
          valueUsd = (priceArs * (p.quantity || 0)) / tcBlue
          pnlUsd = valueUsd - cost / tcBlue
        }
      } else if (costInPesos(p)) {
        // Lote en PESOS en cuenta USD → costo Y valor por el MEP (no peso como dólar).
        const u = pesoLotUsd(p, prices, tcCedear)
        valueUsd = u.valueUsd
        pnlUsd = u.valueUsd - u.investedUsd
      } else {
        const price = p.price_override ?? prices[p.asset]
        if (price != null) {
          // Premium dólar-cripto (broker no-exchange) a valor Y costo → ranking
          // best/worst consistente con el resto de la app. f=1 para todo lo demás.
          const f = cryptoBrokerFactor(p.asset, exchangeBrokers.has(p.broker), p.price_override != null, tcCripto, tcCedear)
          valueUsd = price * (p.quantity || 0) * f
          pnlUsd = valueUsd - cost * f
        }
      }
      if (pnlUsd == null) continue
      const cur = byAsset.get(p.asset) || { asset: p.asset, pnl_usd: 0, value_usd: 0 }
      cur.pnl_usd += pnlUsd
      cur.value_usd += (valueUsd || 0)
      byAsset.set(p.asset, cur)
    }
    const arr = Array.from(byAsset.values())
    arr.sort((a, b) => b.pnl_usd - a.pnl_usd)
    const best = arr[0] || null
    const worst = arr[arr.length - 1] || null
    const positionCount = positions.filter(p => !p.is_cash).length
    const brokerCount = brokers.length

    return { value, invested, pnl, pnlPct, best, worst, positionCount, brokerCount }
  }, [positions, brokers, prices, tcBlue])

  if (loading) {
    return (
      <div className="page-shell text-center py-20 text-ink-3 text-sm" aria-live="polite">
        Armando tu primer reporte…
      </div>
    )
  }

  if (!stats || stats.value <= 0) {
    // Caso edge: el import no dejó posiciones valuables. Mandamos al dashboard.
    return (
      <div className="page-shell text-center py-20 space-y-3">
        <p className="text-ink-2">Tu cartera importada todavía no tiene precios valuables.</p>
        <button
          onClick={() => navigate('/dashboard')}
          className="inline-flex items-center gap-1.5 text-sm bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-4 py-2 rounded-sm transition-colors"
        >
          Ir al Dashboard <ArrowRight size={13} strokeWidth={1.75} />
        </button>
      </div>
    )
  }

  const isPositive = stats.pnl >= 0

  return (
    <div className="page-shell max-w-3xl">
      {/* Hero — el momento de dopamina */}
      <div className="text-center pt-8 pb-6">
        <div className="inline-flex items-center gap-2 mb-3 text-data-violet">
          <Sparkles size={16} strokeWidth={1.75} />
          <span className="text-xs font-mono uppercase tracking-caps">Primer reporte</span>
        </div>
        <h1 className="display-heading mb-3">Bienvenido a Rendi.</h1>
        <p className="text-ink-2 text-sm max-w-md mx-auto leading-relaxed">
          Importamos tu cartera. Esto es lo que tenés hoy, calculado a precios de mercado.
        </p>
      </div>

      {/* Valor del portfolio */}
      <div className="border border-line rounded bg-bg-1 px-6 py-8 mb-4">
        <div className="text-xs text-ink-3 mb-1">Valor de tu cartera</div>
        <div className="text-5xl font-medium tabular num text-ink-0 tracking-tight">
          {fmtUsd(stats.value)}
        </div>
        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <span className={`inline-flex items-center gap-1 text-sm font-medium ${isPositive ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
            {isPositive ? <TrendingUp size={14} strokeWidth={1.75} /> : <TrendingDown size={14} strokeWidth={1.75} />}
            {isPositive ? '+' : '−'}{fmtUsd(Math.abs(stats.pnl))}
          </span>
          <span className={`text-sm tabular ${isPositive ? 'text-rendi-pos/80' : 'text-rendi-neg/80'}`}>
            ({pctSigned(stats.pnlPct)})
          </span>
          <span className="text-xs text-ink-3">
            sobre {fmtUsd(stats.invested)} invertidos
          </span>
        </div>
      </div>

      {/* 3 stats simples */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
        <Panel padding="md">
          <div className="text-xs text-ink-3 mb-1">Posiciones</div>
          <div className="text-2xl font-medium tabular text-ink-0">{stats.positionCount}</div>
          <div className="text-[11px] text-ink-3 mt-0.5">
            en {stats.brokerCount} {stats.brokerCount === 1 ? 'broker' : 'brokers'}
          </div>
        </Panel>

        {stats.best && stats.best.pnl_usd > 0 && (
          <Panel padding="md">
            <div className="text-xs text-ink-3 mb-1">Mejor activo</div>
            <div className="flex items-center gap-2">
              <AssetLogo asset={stats.best.asset} size={20} />
              <span className="text-base font-medium text-ink-0">{stats.best.asset}</span>
            </div>
            <div className="text-[11px] text-rendi-pos tabular mt-0.5 font-mono">
              +{usd(stats.best.pnl_usd)} USD
            </div>
          </Panel>
        )}

        {stats.worst && stats.worst.pnl_usd < 0 && (
          <Panel padding="md">
            <div className="text-xs text-ink-3 mb-1">Peor activo</div>
            <div className="flex items-center gap-2">
              <AssetLogo asset={stats.worst.asset} size={20} />
              <span className="text-base font-medium text-ink-0">{stats.worst.asset}</span>
            </div>
            <div className="text-[11px] text-rendi-neg tabular mt-0.5 font-mono">
              −{usd(Math.abs(stats.worst.pnl_usd))} USD
            </div>
          </Panel>
        )}
      </div>

      {/* CTA al Coach IA — el diferencial de Rendi en el pico post-import. Abre
          el drawer con una pregunta pre-cargada que el bot responde con contexto
          de la cartera recién importada. */}
      <button
        type="button"
        onClick={askCoach}
        className="w-full text-left mb-4 p-4 border border-data-violet/40 bg-data-violet/[0.04] hover:bg-data-violet/[0.08] rounded transition-colors group flex items-start gap-3"
      >
        <div className="w-9 h-9 rounded bg-bg-2 border border-line flex items-center justify-center text-data-violet flex-shrink-0 group-hover:border-data-violet/30 transition-colors">
          <Sparkles size={16} strokeWidth={1.75} />
        </div>
        <div className="flex-1">
          <div className="text-sm font-medium text-ink-0 mb-0.5">Preguntale al Coach IA sobre tu cartera</div>
          <p className="text-xs text-ink-2 leading-relaxed">
            Empezá por “¿Mi nivel de concentración es elevado?” — lo analiza con tu data en segundos.
          </p>
        </div>
        <ArrowRight size={15} strokeWidth={1.75} className="text-data-violet flex-shrink-0 mt-0.5 group-hover:translate-x-0.5 transition-transform" />
      </button>

      {/* Próximos pasos */}
      <Panel padding="md" className="mb-6">
        <h2 className="text-sm font-medium text-ink-0 mb-2">Próximos pasos</h2>
        <ul className="space-y-1.5 text-sm text-ink-2">
          <li className="flex items-baseline gap-2">
            <span className="text-rendi-pos">›</span>
            En <strong className="text-ink-1">Reportes</strong> vas a ver tu performance mes a mes con benchmark vs S&amp;P 500.
          </li>
          <li className="flex items-baseline gap-2">
            <span className="text-rendi-pos">›</span>
            En <strong className="text-ink-1">Insights</strong>, análisis de concentración, drawdown y atribución del crecimiento.
          </li>
          <li className="flex items-baseline gap-2">
            <span className="text-rendi-pos">›</span>
            Tu primer Reporte Mensual está listo cuando cierre el mes — te avisamos.
          </li>
        </ul>
      </Panel>

      {/* CTAs */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          to="/imports"
          className="text-xs text-ink-3 hover:text-ink-0 transition-colors"
        >
          Importar otro CSV →
        </Link>
        <Link
          to="/dashboard"
          className="inline-flex items-center gap-1.5 text-sm bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-4 py-2 rounded-sm transition-colors"
        >
          Ver mi dashboard
          <ArrowRight size={13} strokeWidth={1.75} />
        </Link>
      </div>
    </div>
  )
}
