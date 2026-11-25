// FirstInsight — pantalla de "primer insight" post-import (Sprint 2).
// ═══════════════════════════════════════════════════════════════════════════
// Cuando el user completa su PRIMER import exitoso, lo redirigimos acá en
// lugar de a la tabla administrativa /imports. Es el primer momento de
// dopamina: "Acá está tu portfolio. Esto vale tu plata. Esto es lo que
// movió la aguja". Después, CTA al Dashboard.
// El valor de la cartera cuenta hasta su número (AnimatedNumber) y los tres
// paneles entran de a uno: es la primera vez que esta persona ve su plata en
// Rendi. Con "reducir movimiento", todo aparece quieto.
//
// Cuándo se llega: al cerrar el importador después del PRIMER import en este
// navegador (pages/Imports.jsx y pages/Config.jsx miran la marca
// `primeraImportacion` del catálogo del almacén). La bienvenida obligatoria
// (pages/Onboarding.jsx) no pasa por acá: tiene su propio paso «tu cartera»,
// con el mismo cálculo (hooks/useCarteraRecienCargada.js), y deja la marca
// puesta para que el próximo import no traiga a nadie de vuelta.

import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { rutaParaImportar } from '../utils/navegacion'
import { Sparkles, TrendingUp, TrendingDown, ArrowRight } from 'lucide-react'
import { fmtUsd as fmtUsdRaw, usd as usdRaw, pctSigned } from '../utils/format'
import { usePrivacy, OCULTO } from '../contexts/PrivacyContext'
import AssetLogo from '../components/AssetLogo'
import { track } from '../utils/track'
import Panel from '../components/Panel'
import AnimatedNumber from '../components/AnimatedNumber'
import { entrada } from '../hooks/useAlVerse'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import MervallE from '../components/ai/MervallE'
import { useCarteraRecienCargada } from '../hooks/useCarteraRecienCargada'

export default function FirstInsight() {
  // «Ocultar saldos»: el valor, lo invertido y lo ganado salen tapados; quedan
  // los % y los activos (30/10: la bienvenida no miraba el ojito).
  const { hidden: oculto } = usePrivacy()
  const fmtUsd = (v) => (oculto ? OCULTO : fmtUsdRaw(v))
  const usd = (v) => (oculto ? OCULTO : usdRaw(v))
  const navigate = useNavigate()
  const coachDrawer = useCoachDrawer()
  // El cálculo es el mismo que el del paso «tu cartera» de la bienvenida
  // obligatoria (pages/Onboarding.jsx): vive en un solo lugar.
  const { loading, stats } = useCarteraRecienCargada()

  // CTA al Coach IA post-import: abre el drawer con una pregunta pre-cargada
  // que el bot responde con contexto de la cartera recién importada. Navegamos
  // al dashboard primero (el drawer vive a nivel App; FirstInsight es full-screen).
  // La pregunta está en la whitelist (main.py).
  function askCoach() {
    track('first_insight_coach_cta')
    navigate('/dashboard')
    setTimeout(() => coachDrawer?.open?.('¿Mi nivel de concentración es elevado?'), 300)
  }

  useEffect(() => { track('first_insight_viewed') }, [])

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
          <span className="text-xs font-medium">Primer reporte</span>
        </div>
        <h1 className="display-heading mb-3">Bienvenido a Rendi.</h1>
        <p className="text-ink-2 text-sm max-w-md mx-auto leading-relaxed">
          Importamos tu cartera. Esto es lo que tenés hoy, calculado a precios de mercado.
        </p>
      </div>

      {/* Valor del portfolio */}
      <div className="border border-line rounded-xl bg-bg-1 px-6 py-8 mb-4">
        <div className="text-xs text-ink-3 mb-1">Valor de tu cartera</div>
        {/* Cuenta hasta el valor: es el primer número que ve alguien que
            acaba de importar. Real y ya calculado (esta pantalla espera los
            precios antes de mostrarse), así que no salta después. */}
        <div className="text-5xl font-medium tabular num text-ink-0 tracking-tight">
          <AnimatedNumber value={stats.value} format={fmtUsd} />
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

      {/* 3 stats simples — entran de a uno mientras el total cuenta. */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
        <Panel padding="md" {...entrada(true, 2)}>
          <div className="text-xs text-ink-3 mb-1">Posiciones</div>
          <div className="text-2xl font-medium tabular text-ink-0">{stats.positionCount}</div>
          <div className="text-[11px] text-ink-3 mt-0.5">
            en {stats.brokerCount} {stats.brokerCount === 1 ? 'broker' : 'brokers'}
          </div>
        </Panel>

        {stats.best && stats.best.pnl_usd > 0 && (
          <Panel padding="md" {...entrada(true, 3)}>
            <div className="text-xs text-ink-3 mb-1">Mejor activo</div>
            <div className="flex items-center gap-2">
              <AssetLogo asset={stats.best.asset} size={20} />
              <span className="text-base font-medium text-ink-0">{stats.best.asset}</span>
            </div>
            <div className="text-[11px] text-rendi-pos tabular mt-0.5">
              +{usd(stats.best.pnl_usd)} USD
            </div>
          </Panel>
        )}

        {stats.worst && stats.worst.pnl_usd < 0 && (
          // Su turno depende de si hubo "Mejor activo": sin él, entra justo
          // después de "Posiciones" en vez de dejar un hueco en la escalera.
          <Panel padding="md" {...entrada(true, stats.best && stats.best.pnl_usd > 0 ? 4 : 3)}>
            <div className="text-xs text-ink-3 mb-1">Peor activo</div>
            <div className="flex items-center gap-2">
              <AssetLogo asset={stats.worst.asset} size={20} />
              <span className="text-base font-medium text-ink-0">{stats.worst.asset}</span>
            </div>
            <div className="text-[11px] text-rendi-neg tabular mt-0.5">
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
          <MervallE size={28} forma="head" quieto />
        </div>
        <div className="flex-1">
          <div className="text-sm font-medium text-ink-0 mb-0.5">Preguntale a Mervall-E sobre tu cartera</div>
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
            En <strong className="text-ink-1">Métricas</strong>, análisis de concentración, drawdown y atribución del crecimiento.
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
          to={rutaParaImportar('primer-insight')}
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
