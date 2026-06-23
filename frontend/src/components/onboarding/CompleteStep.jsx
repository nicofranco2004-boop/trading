// CompleteStep — paso 3 del wizard: cierre.
// ════════════════════════════════════════════════════════════════════════════
// 10-20s. Celebración minimal + 3 cards que tipean qué hacer ahora:
//   1. Ver primer Insight (lo lleva a Insights)
//   2. Probar el Coach IA (abre el drawer)
//   3. Hacer el quiz de perfil (lleva a /perfil-inversor)
//
// CTA principal: "Ir a mi cartera" → /dashboard.

import { Link, useNavigate } from 'react-router-dom'
import { CheckCircle2, Sparkles, Bot, Brain, BarChart3, ArrowRight } from 'lucide-react'
import { useCoachDrawer } from '../../contexts/CoachDrawerContext'

export default function CompleteStep({ skipped, position }) {
  const navigate = useNavigate()
  const coachDrawer = useCoachDrawer()

  function openCoach() {
    navigate('/dashboard')
    setTimeout(() => coachDrawer?.open?.(), 300)
  }

  return (
    <div className="text-center">
      {/* Icon de check */}
      <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-rendi-pos/15 mb-5">
        <CheckCircle2 size={28} strokeWidth={1.75} className="text-rendi-pos" />
      </div>

      <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-0 mb-3 leading-[1.15]">
        Todo listo
      </h1>

      <p className="text-base md:text-lg text-ink-2 max-w-lg mx-auto leading-relaxed mb-10">
        {skipped
          ? 'Tu cuenta quedó lista. Cuando cargues tus posiciones vas a ver el dashboard cobrar vida.'
          : position
            ? <>Tu posición en <strong className="text-ink-1">{position.asset}</strong> ya está en tu cartera. Bienvenido a Rendi.</>
            : 'Tu cartera está cargada. Bienvenido a Rendi.'}
      </p>

      {/* Cards de siguientes pasos */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-3xl mx-auto mb-10 text-left">
        <ActionCard
          Icon={BarChart3}
          title="Ver tu Insight"
          desc="Análisis automático de tu cartera: P&L, concentración, drawdown."
          onClick={() => navigate('/analisis?tab=diagnostico')}
          highlight={!skipped}
        />
        <ActionCard
          Icon={Bot}
          title="Coach IA"
          desc="Pregúntale lo que quieras. Tiene contexto de tu cartera."
          onClick={openCoach}
        />
        <ActionCard
          Icon={Brain}
          title="Quiz de perfil"
          desc="7 preguntas. Mejora la precisión de los análisis IA."
          onClick={() => navigate('/analisis?tab=perfil')}
        />
      </div>

      {/* CTA principal */}
      <button
        type="button"
        onClick={() => navigate('/posiciones?tab=evolucion')}
        className="group inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-6 py-3 transition-colors text-sm sm:text-base min-w-[200px] justify-center"
      >
        <Sparkles size={16} strokeWidth={2} />
        Ir a mi cartera
        <ArrowRight size={16} strokeWidth={2} className="group-hover:translate-x-0.5 transition-transform" />
      </button>

      <p className="text-xs text-ink-3 mt-5 max-w-md mx-auto">
        Podés volver al onboarding desde Configuración si necesitás.
      </p>
    </div>
  )
}

function ActionCard({ Icon, title, desc, onClick, highlight }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`p-4 border rounded text-left transition-all group ${
        highlight
          ? 'border-data-violet/40 bg-data-violet/[0.04] hover:bg-data-violet/[0.08]'
          : 'border-line hover:border-line-3 hover:bg-bg-2/40'
      }`}
    >
      <div className="w-9 h-9 rounded bg-bg-2 border border-line flex items-center justify-center text-data-violet mb-3 group-hover:border-data-violet/30 transition-colors">
        <Icon size={16} strokeWidth={1.75} />
      </div>
      <h3 className="text-sm font-medium text-ink-0 mb-1">{title}</h3>
      <p className="text-xs text-ink-2 leading-relaxed">{desc}</p>
    </button>
  )
}
