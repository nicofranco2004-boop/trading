// WelcomeStep — primer paso del onboarding wizard.
// ════════════════════════════════════════════════════════════════════════════
// 10s. Welcome + valor prop concisa + CTA "Empezar". El user todavía no hizo
// nada — solo verificó email. Acá le decimos qué viene y le damos el "start".

import { Sparkles, ArrowRight, Briefcase, BarChart3, Bot } from 'lucide-react'

export default function WelcomeStep({ userName, onNext, onSkip }) {
  return (
    <div className="text-center">
      {/* Logo + Bienvenida */}
      <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-data-violet/15 mb-5">
        <Sparkles size={24} strokeWidth={1.75} className="text-data-violet" />
      </div>

      <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-0 mb-3 leading-[1.15]">
        {userName ? `Hola ${userName.split(' ')[0]}, ` : 'Hola, '}
        <br className="hidden sm:inline" />
        <span className="text-ink-2">bienvenido a Rendi.</span>
      </h1>

      <p className="text-base md:text-lg text-ink-2 max-w-md mx-auto leading-relaxed mb-8">
        En 2 minutos vamos a tener tu primera cartera funcionando. Te guío paso a paso.
      </p>

      {/* 3 features highlights */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 max-w-xl mx-auto mb-10 text-left">
        <FeatureMini
          Icon={Briefcase}
          title="Tu broker"
          desc="Conectás Cocos, IOL, Schwab, Binance o el que uses."
        />
        <FeatureMini
          Icon={BarChart3}
          title="Tu cartera"
          desc="Cargás CSV o manual. P&L en USD real."
        />
        <FeatureMini
          Icon={Bot}
          title="Coach IA"
          desc="Hace análisis con tus datos, no en abstracto."
        />
      </div>

      {/* CTAs */}
      <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
        <button
          type="button"
          onClick={onNext}
          className="group inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-6 py-3 transition-colors text-sm sm:text-base min-w-[200px] justify-center"
        >
          Empezar
          <ArrowRight size={16} strokeWidth={2} className="group-hover:translate-x-0.5 transition-transform" />
        </button>
        <button
          type="button"
          onClick={onSkip}
          className="text-sm text-ink-3 hover:text-ink-1 transition-colors px-4 py-2"
        >
          Saltar y explorar yo solo
        </button>
      </div>
    </div>
  )
}

function FeatureMini({ Icon, title, desc }) {
  return (
    <div className="p-4 border border-line rounded bg-bg-1/40">
      <div className="w-7 h-7 rounded bg-bg-2 border border-line flex items-center justify-center text-data-violet mb-2">
        <Icon size={14} strokeWidth={1.75} />
      </div>
      <h3 className="text-sm font-medium text-ink-0 mb-0.5">{title}</h3>
      <p className="text-xs text-ink-2 leading-relaxed">{desc}</p>
    </div>
  )
}
