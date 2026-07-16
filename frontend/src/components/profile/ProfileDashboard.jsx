// ProfileDashboard — el Tablero del perfil de inversor (plantilla adaptativa).
// ═══════════════════════════════════════════════════════════════════════════
// La plantilla es fija; el relleno es por usuario: qué módulos aparecen, en
// qué orden y cuáles quedan bloqueados lo decide el motor determinístico
// (utils/profileDashboard.js) sobre los cruces que YA computa profileMatch.
// La IA (ProfileSummaryBlock, arriba de este tablero) narra — nunca decide el
// layout ni inventa números.
//
// Cada módulo con cruce respaldado por el backend (topic profile.card) va
// wrapeado con AskAIAbout → ✦ "Preguntar a la IA". `radar` y `return_exp` NO:
// el backend no tiene esos codes (return_exp depende del retorno real, que
// vive solo en el frontend — backlog TWR).

import {
  Layers, BarChart3, PieChart, TrendingUp, TrendingDown,
  ArrowLeftRight, Droplets, Clock, Target,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { buildProfileDashboard, tradesToActivityPos, STYLE_POS } from '../../utils/profileDashboard'
import AskAIAbout from '../ai/AskAIAbout'
import ModuleShell from './ModuleShell'
import ProfileRadar from './ProfileRadar'
import AllocationBars from './AllocationBars'
import ConcentrationDonut from './ConcentrationDonut'
import ReturnGauge from './ReturnGauge'
import StyleScale from './StyleScale'
import LiquidityBar from './LiquidityBar'
import HorizonStat from './HorizonStat'
import ObjectiveStat from './ObjectiveStat'
import DrawdownStat from './DrawdownStat'

const MODULE_META = {
  radar:         { title: 'Radar de perfil',        icon: Layers,         aiCode: null },
  allocation:    { title: 'Asignación de activos',  icon: BarChart3,      aiCode: 'allocation' },
  concentration: { title: 'Concentración',          icon: PieChart,       aiCode: 'concentration' },
  return_exp:    { title: 'Retorno vs expectativa', icon: TrendingUp,     aiCode: null },
  horizon:       { title: 'Horizonte',              icon: Clock,          aiCode: 'horizon' },
  style:         { title: 'Estilo de inversión',    icon: ArrowLeftRight, aiCode: 'style' },
  liquidity:     { title: 'Colchón de liquidez',    icon: Droplets,       aiCode: 'liquidity' },
  objective:     { title: 'Objetivo',               icon: Target,         aiCode: 'objective' },
  drawdown:      { title: 'Caída tolerada vs real', icon: TrendingDown,   aiCode: 'drawdown' },
}

const BUCKET_LABELS = [
  ['cash', 'Cash'],
  ['fixed_income', 'Renta fija'],
  ['equity', 'Renta variable'],
  ['alternative', 'Alternativos'],
]

// Body del módulo según id — adapta el shape de la card (profileMatch) a las
// props planas del componente visual. Devuelve null si la card no alcanza
// (el motor ya lo marcó locked en ese caso; esto es solo defensa en capas).
function moduleBody(id, cards, dash) {
  const card = cards[id]
  switch (id) {
    case 'radar':
      return dash.radar ? <ProfileRadar axes={dash.radar.axes} /> : null

    case 'allocation': {
      const sug = card?.declared?.suggested
      const act = card?.actual?.buckets
      if (!sug || !act) return null
      const rows = BUCKET_LABELS.map(([key, label]) => ({
        label, suggested: sug[key] ?? 0, actual: act[key] ?? 0,
      }))
      return <AllocationBars rows={rows} categoryLabel={card.declared.categoryLabel} />
    }

    case 'concentration':
      if (card?.actual?.top3Pct == null || !dash.topHoldings.length) return null
      return (
        <ConcentrationDonut
          holdings={dash.topHoldings}
          top3Pct={card.actual.top3Pct}
          comparison={card.comparison}
        />
      )

    case 'return_exp':
      if (card?.actual?.realReturnPct == null) return null
      return (
        <ReturnGauge
          realPct={card.actual.realReturnPct}
          floorPct={card.declared.floorReal}
          expectationLabel={(card.declared.expectationLabel || '').toLowerCase()}
          comparison={card.comparison}
        />
      )

    case 'horizon': {
      // % en activos de plazo largo directo de buckets (riskPct depende del
      // horizonte declarado, acá queremos siempre equity+alternativos).
      // dash.buckets ya resolvió el fallback a positions — sin él, un test a
      // medias dejaba a horizon avail pero sin body (H1 del review).
      const buckets = dash.buckets
      if (!buckets || !card?.declared) return null
      const longTermPct = Math.min(100, (buckets.equity || 0) + (buckets.alternative || 0))
      const clashes =
        (card.declared.horizon === 'short' && longTermPct > 50) ||
        (card.declared.horizon === 'medium' && longTermPct > 80)
      return (
        <HorizonStat
          longTermPct={longTermPct}
          horizonLabel={card.declared.horizonLabel}
          clashes={clashes}
        />
      )
    }

    case 'style':
      if (card?.actual?.tradesPerMonth == null) return null
      return (
        <StyleScale
          declaredPos={STYLE_POS[card.declared?.style] ?? null}
          declaredLabel={card.declared?.styleLabel}
          actualPos={tradesToActivityPos(card.actual.tradesPerMonth)}
          tradesPerMonth={card.actual.tradesPerMonth}
          inferredLabel={card.actual.inferredStyleLabel}
        />
      )

    case 'liquidity':
      if (card?.actual?.safePct == null) return null
      return (
        <LiquidityBar
          safePct={card.actual.safePct}
          volatilePct={card.actual.volatilePct}
          needsLiquidity={card.declared?.liquidity === 'yes' || card.declared?.liquidity === 'partial'}
          comparison={card.comparison}
        />
      )

    case 'objective':
      if (card?.actual?.alignedPct == null) return null
      return (
        <ObjectiveStat
          goalLabel={card.declared?.goalLabel}
          alignedPct={card.actual.alignedPct}
          alignedLabel={card.declared?.alignedLabel}
          misalignedPct={card.actual.misalignedPct}
        />
      )

    case 'drawdown':
      if (card?.actual?.drawdownPct == null) return null
      return (
        <DrawdownStat
          behaviorLabel={card.declared?.behaviorLabel}
          toleranceLabel={`${card.declared?.impliedTolerance?.min}-${card.declared?.impliedTolerance?.max}%`}
          drawdownPct={card.actual.drawdownPct}
          comparison={card.comparison}
        />
      )

    default:
      return null
  }
}

export default function ProfileDashboard({ cards, positions = [] }) {
  const dash = buildProfileDashboard({ cards, positions })

  // Sin ningún módulo disponible: el caso "sin test" lo corta antes el caller
  // (ProfileInvestorBlock, CTA al test). Si llegamos acá con todo bloqueado es
  // porque hay test pero NO cartera (todo no_portfolio) → CTA a cargarla, no
  // una sección en blanco ni 9 candados.
  if (dash.availCount === 0) {
    return (
      <div className="bg-white dark:bg-bg-1 border border-line/80 dark:border-line rounded p-6 flex flex-col items-start gap-3">
        <p className="text-sm text-ink-1 leading-snug max-w-xl">
          Tu test está cargado. Cargá tus posiciones (o importá tu cartera) y acá
          la cruzamos contra lo que declaraste: asignación, concentración,
          horizonte, liquidez y más.
        </p>
        <Link
          to="/posiciones"
          className="inline-flex items-center gap-1.5 text-xs font-medium bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border border-data-violet/40 rounded-sm px-3 py-2 transition-colors"
        >
          Cargar posiciones →
        </Link>
      </div>
    )
  }

  // ★ va al primer módulo DISPONIBLE (un candado con estrella confunde).
  const topPickId = dash.modules.find((m) => m.avail)?.id

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 grid-flow-dense">
      {dash.modules.map((m) => {
        const meta = MODULE_META[m.id]
        if (!meta) return null

        const body = m.avail ? moduleBody(m.id, cards, dash) : null
        // Card marcada avail pero sin body renderizable (data parcial rara) →
        // no ocupamos un slot con una card vacía.
        if (m.avail && !body) return null

        const shell = (
          <ModuleShell
            icon={meta.icon}
            title={meta.title}
            rel={m.rel}
            topPick={m.id === topPickId}
            lock={m.avail ? null : m.lock}
            wide={m.wide}
          >
            {body}
          </ModuleShell>
        )

        // ✦ IA per-módulo solo donde el backend tiene el code (profile.card).
        if (m.avail && meta.aiCode) {
          return (
            <div key={m.id} className={m.wide ? 'md:col-span-2' : ''}>
              <AskAIAbout topic="profile.card" params={{ code: meta.aiCode }} subtitle={meta.title} className="h-full">
                {shell}
              </AskAIAbout>
            </div>
          )
        }
        return <div key={m.id} className={m.wide ? 'md:col-span-2' : ''}>{shell}</div>
      })}
    </div>
  )
}
