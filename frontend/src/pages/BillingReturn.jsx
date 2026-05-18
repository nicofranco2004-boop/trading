// BillingReturn — páginas de retorno tras el checkout de Mercado Pago.
// ═══════════════════════════════════════════════════════════════════════════
// MP redirige al user a una de estas 3 URLs después del checkout:
//   /billing/success  — pago autorizado (tier='pro' ya seteado por webhook)
//   /billing/pending  — pago en proceso (ej. transferencia bancaria pendiente)
//   /billing/failure  — pago rechazado o user canceló el flow
//
// Después de 1-2 segundos refresheamos plan features (por si el webhook ya
// pegó) y mostramos un mensaje claro con CTA para seguir.

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, Clock, XCircle, ArrowRight, Sparkles } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'
import { track } from '../utils/track'

export function BillingSuccess() {
  const navigate = useNavigate()

  useEffect(() => {
    track('billing_return', { status: 'success' })
    // El webhook ya debería haber seteado tier='pro' en backend.
    // Forzamos refetch del plan features para que la UI se actualice.
    refreshPlanFeatures()
    // Auto-redirect a /dashboard tras 4 seg (UX común post-checkout)
    const t = setTimeout(() => navigate('/dashboard'), 4000)
    return () => clearTimeout(t)
  }, [navigate])

  return (
    <ReturnLayout
      icon={<CheckCircle2 size={56} className="text-rendi-pos" strokeWidth={1.5} />}
      tone="success"
      title="¡Bienvenido a Rendi Pro!"
      description="Tu suscripción está activa. Ya tenés acceso a todas las features Pro: 60 análisis IA por semana, follow-ups, brokers ilimitados, export CSV y todo lo demás."
      cta="Ir al dashboard"
      onCta={() => navigate('/dashboard')}
      footer="Te vamos a redirigir automáticamente en unos segundos…"
    />
  )
}

export function BillingPending() {
  const navigate = useNavigate()
  useEffect(() => {
    track('billing_return', { status: 'pending' })
    refreshPlanFeatures()
  }, [])
  return (
    <ReturnLayout
      icon={<Clock size={56} className="text-data-amber" strokeWidth={1.5} />}
      tone="pending"
      title="Tu pago está en proceso"
      description="Mercado Pago todavía está procesando tu pago. Apenas se acredite, tu cuenta pasa a Pro automáticamente. Esto puede tardar de minutos a 1 día hábil según el medio de pago."
      cta="Ver mi cuenta"
      onCta={() => navigate('/config')}
      footer="Te vamos a avisar por email cuando se confirme."
    />
  )
}

export function BillingFailure() {
  const navigate = useNavigate()
  useEffect(() => {
    track('billing_return', { status: 'failure' })
    refreshPlanFeatures()
  }, [])
  return (
    <ReturnLayout
      icon={<XCircle size={56} className="text-rendi-neg" strokeWidth={1.5} />}
      tone="failure"
      title="El pago no se completó"
      description="No pudimos procesar tu suscripción. Puede haber sido por: tarjeta rechazada, datos incorrectos, o que cerraste el checkout sin terminar. Probá de nuevo y, si el problema persiste, contactanos."
      cta="Volver a /planes"
      onCta={() => navigate('/planes')}
      footer="No se realizó ningún cobro a tu tarjeta."
    />
  )
}

function ReturnLayout({ icon, tone, title, description, cta, onCta, footer }) {
  const borderColor =
    tone === 'success' ? 'border-rendi-pos/30 bg-rendi-pos/[0.04]'
    : tone === 'pending' ? 'border-data-amber/30 bg-data-amber/[0.04]'
    : 'border-rendi-neg/30 bg-rendi-neg/[0.04]'
  return (
    <div className="page-shell max-w-2xl">
      <PageHeader eyebrow="Suscripción / Resultado" title="" subtitle="" />
      <div className={`${borderColor} border rounded-lg p-8 text-center mt-4`}>
        <div className="flex justify-center mb-4">{icon}</div>
        <h1 className="text-2xl font-bold text-ink-0 mb-3">{title}</h1>
        <p className="text-sm text-ink-2 leading-relaxed max-w-md mx-auto mb-6">
          {description}
        </p>
        <button
          type="button"
          onClick={onCta}
          className="inline-flex items-center gap-1.5 text-sm font-medium bg-data-violet hover:bg-data-violet/90 text-white border border-data-violet rounded-sm px-6 py-2.5 transition-colors"
        >
          {tone === 'success' && <Sparkles size={13} strokeWidth={1.75} />}
          {cta}
          <ArrowRight size={13} strokeWidth={1.75} />
        </button>
        {footer && (
          <p className="text-xs text-ink-3 mt-4">{footer}</p>
        )}
      </div>
    </div>
  )
}
