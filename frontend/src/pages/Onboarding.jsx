// Onboarding — wizard de bienvenida para users nuevos.
// ════════════════════════════════════════════════════════════════════════════
// Ruta: /onboarding
//
// Flow (3 steps):
//   1. Welcome — bienvenida + valor prop + CTA "Empezar"
//   2. Position — cargar cartera: CSV import / manual (con broker inline) / saltar
//   3. Complete — celebración + 3 cards (Insights, Coach, Quiz)
//
// Trigger automático: en VerifyEmail.jsx, tras login OK redirigimos acá si
// el user no tiene brokers cargados (es fresh signup).
//
// Skip / abandono:
//   - LocalStorage flag `rendi_onboarding_skipped` evita re-mostrar.
//   - El user puede volver al onboarding manualmente desde Config (link
//     "Repetir tour" para los que se equivocaron).
//
// Tracking GA4: cada paso emite eventos para medir embudo de activación:
//   - onboarding_started
//   - onboarding_step_completed { step }
//   - onboarding_skipped { at_step }
//   - onboarding_completed

import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'
import { useAuth } from '../contexts/AuthContext'
import { trackEvent } from '../utils/analytics'
import { track } from '../utils/track'
import ProgressBar from '../components/onboarding/ProgressBar'
import WelcomeStep from '../components/onboarding/WelcomeStep'
import PositionStep from '../components/onboarding/PositionStep'
import CompleteStep from '../components/onboarding/CompleteStep'

export const ONBOARDING_SKIPPED_KEY = 'rendi_onboarding_skipped'
export const ONBOARDING_COMPLETED_KEY = 'rendi_onboarding_completed'

const STEP_LABELS = ['Bienvenida', 'Cartera', 'Listo']
const STEP_NAMES = ['welcome', 'position', 'complete']

export default function Onboarding() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // Permite saltar directo a un step específico via ?step=complete
  // (usado por VerifyEmail → /imports → /bienvenida → /onboarding?step=complete
  // cuando el user termina el CSV import).
  const initialStep = (() => {
    const requested = searchParams.get('step')
    const idx = STEP_NAMES.indexOf(requested)
    return idx >= 0 ? idx : 0
  })()

  const [step, setStep] = useState(initialStep)
  const [data, setData] = useState({}) // acumulador: { broker, position, skipped }

  useEffect(() => {
    // Si el user entra directamente al step=complete (vuelta del CSV import),
    // no contar como un nuevo inicio del onboarding — ya empezó antes.
    if (initialStep === 0) {
      trackEvent('onboarding_started', { at_step: STEP_NAMES[0] })
      track('onboarding_started', { at_step: STEP_NAMES[0] })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Guard: si el user no está logueado o es admin/demo, no debería estar acá.
  useEffect(() => {
    if (!user) {
      navigate('/login', { replace: true })
    }
  }, [user, navigate])

  function goNext(extra = {}) {
    setData((prev) => ({ ...prev, ...extra }))
    trackEvent('onboarding_step_completed', { step: STEP_NAMES[step] })
    track('onboarding_step_completed', { step: STEP_NAMES[step] })
    if (step < STEP_NAMES.length - 1) {
      setStep((s) => s + 1)
    } else {
      // Completó el último step
      finishOnboarding()
    }
  }

  function goBack() {
    if (step > 0) setStep((s) => s - 1)
  }

  function handleSkip() {
    trackEvent('onboarding_skipped', { at_step: STEP_NAMES[step] })
    track('onboarding_skipped', { at_step: STEP_NAMES[step] })
    try {
      localStorage.setItem(ONBOARDING_SKIPPED_KEY, '1')
    } catch {}
    // FR-01: mandar a la CARTERA (su empty-state con CTA de carga), no a la Home
    // de mercado genérica — que no contiene nada del usuario y posterga el aha.
    navigate('/posiciones', { replace: true })
  }

  function finishOnboarding() {
    trackEvent('onboarding_completed', { had_position: !!data.position })
    track('onboarding_completed', { had_position: !!data.position })
    try {
      localStorage.setItem(ONBOARDING_COMPLETED_KEY, '1')
    } catch {}
    // No navegamos automáticamente — el CompleteStep tiene CTAs propios.
  }

  // Marcar completado al entrar a complete step (por si el user cierra el tab)
  useEffect(() => {
    if (step === STEP_NAMES.length - 1) {
      try {
        localStorage.setItem(ONBOARDING_COMPLETED_KEY, '1')
      } catch {}
    }
  }, [step])

  return (
    <div className="min-h-screen bg-bg-0 text-ink-0 flex flex-col">
      <PageMeta
        title="Empezá con Rendi"
        description="Configurá tu cuenta en 2 minutos: broker, primera operación y a invertir."
        canonical="/onboarding"
        noindex={true}
      />

      {/* Header minimal — solo logo + opción skip */}
      <header className="border-b border-line/40 sticky top-0 bg-bg-0/95 backdrop-blur-sm z-10">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <RendiLogo size={28} />
            <span className="font-semibold text-base tracking-tight">rendi</span>
          </div>
          {step < STEP_NAMES.length - 1 && (
            <button
              type="button"
              onClick={handleSkip}
              className="text-xs text-ink-3 hover:text-ink-1 transition-colors px-3 py-1.5"
            >
              Saltar onboarding
            </button>
          )}
        </div>
      </header>

      {/* Progress bar */}
      <div className="max-w-3xl mx-auto w-full px-4 sm:px-6 pt-8 pb-2">
        <ProgressBar steps={STEP_LABELS} currentIndex={step} />
      </div>

      {/* Body — contenido del step actual */}
      <main className="flex-1 max-w-3xl mx-auto w-full px-4 sm:px-6 py-8 md:py-12">
        {step === 0 && (
          <WelcomeStep
            userName={user?.name}
            onNext={() => goNext()}
            onSkip={handleSkip}
          />
        )}
        {step === 1 && (
          <PositionStep
            onNext={(extra) => goNext(extra)}
            onBack={goBack}
          />
        )}
        {step === 2 && (
          <CompleteStep
            skipped={!!data.skipped}
            position={data.position}
          />
        )}
      </main>

      {/* Footer mini — copy reassurance */}
      <footer className="border-t border-line/40">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 text-center">
          <p className="text-[11px] text-ink-3">
            Podés cambiar todo después desde{' '}
            <button
              type="button"
              onClick={() => navigate('/config')}
              className="text-ink-2 hover:text-ink-1 underline-offset-2 hover:underline"
            >
              Configuración
            </button>
            .
          </p>
        </div>
      </footer>
    </div>
  )
}
