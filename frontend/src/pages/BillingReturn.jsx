// BillingReturn — páginas de retorno tras el checkout de Rebill.
// ═══════════════════════════════════════════════════════════════════════════
// Rebill redirige al user a una de estas URLs después del checkout:
//   /billing/success?provider=rebill — pago confirmado (esperar webhook)
//   /billing/pending                  — pago en proceso (transferencia)
//   /billing/failure                  — pago rechazado o user canceló
//
// Estrategia post-Rebill:
//   1. Llegamos a la página con el pago ya hecho del lado de Rebill
//   2. Polleamos /auth/me cada 2s para ver cuándo el webhook nos activa
//      el tier (users.tier pasa a 'plus' o 'pro')
//   3. Si llegamos a 'plus' / 'pro' → success absoluto
//   4. Si pasaron 30s sin update → mensaje "se está procesando"
//
// Nota: el migration a Rebill mantiene la URL /billing/success para no romper
// links viejos. El webhook va a /api/billing/rebill-webhook.
//
// (Pre-migración usábamos /api/billing/sync que pegaba a MP — eso quedó
// muerto pero el endpoint todavía existe en el backend hasta que limpiemos.)

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CheckCircle2, Clock, XCircle, ArrowRight, Sparkles, Loader2 } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import PageMeta from '../components/PageMeta'
import { refreshPlanFeatures } from '../hooks/usePlanFeatures'
import { track } from '../utils/track'
import { api } from '../utils/api'

const POLL_INTERVAL_MS = 2_000   // /auth/me cada 2s
const POLL_TIMEOUT_MS = 30_000   // hasta 30s totales

// Polleo del tier: refresca /auth/me cada 2s. Devuelve { tier, loading, timedOut, unauthenticated }.
function useTierPolling(intent) {
  const [tier, setTier] = useState(null)
  const [loading, setLoading] = useState(true)
  const [timedOut, setTimedOut] = useState(false)
  const [unauthenticated, setUnauthenticated] = useState(false)

  useEffect(() => {
    track('billing_return', { intent })
    let cancelled = false
    let interval = null
    const startedAt = Date.now()

    async function poll() {
      try {
        const me = await api.get('/auth/me')
        if (cancelled) return
        const currentTier = me?.tier || 'free'
        setTier(currentTier)
        setLoading(false)
        refreshPlanFeatures()
        if (currentTier === 'plus' || currentTier === 'pro' || currentTier === 'admin') {
          if (interval) clearInterval(interval)
        } else if (Date.now() - startedAt >= POLL_TIMEOUT_MS) {
          setTimedOut(true)
          if (interval) clearInterval(interval)
        }
      } catch (ex) {
        if (cancelled) return
        // Si /auth/me devuelve 401, el user no está logueado — parar el poll.
        // api.js tira `new Error('Unauthorized')` (sin .status), entonces
        // matcheamos por message.
        const is401 = ex?.status === 401 || ex?.message === 'Unauthorized'
        if (is401) {
          setUnauthenticated(true)
          setLoading(false)
          if (interval) clearInterval(interval)
          return
        }
        // Otros errores transitorios: seguimos polleando hasta el timeout.
        setLoading(false)
      }
    }

    poll()
    interval = setInterval(poll, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      if (interval) clearInterval(interval)
    }
  }, [intent])

  return { tier, loading, timedOut, unauthenticated }
}

export function BillingSuccess() {
  const navigate = useNavigate()
  const { tier, loading, timedOut, unauthenticated } = useTierPolling('success')
  const isActivated = tier === 'plus' || tier === 'pro' || tier === 'admin'

  useEffect(() => {
    if (isActivated) {
      const t = setTimeout(() => navigate('/dashboard'), 4500)
      return () => clearTimeout(t)
    }
  }, [isActivated, navigate])

  if (unauthenticated) {
    return (
      <ReturnLayout
        icon={<Clock size={56} className="text-data-amber" strokeWidth={1.5} />}
        tone="pending"
        title="Iniciá sesión para ver tu suscripción"
        description="Tu pago se procesó, pero necesitamos que inicies sesión para confirmar la activación de tu cuenta."
        cta="Iniciar sesión"
        onCta={() => navigate('/login')}
      />
    )
  }

  if (loading) {
    return (
      <ReturnLayout
        icon={<Loader2 size={56} className="text-data-violet animate-spin" strokeWidth={1.5} />}
        tone="pending"
        title="Confirmando tu pago…"
        description="Estamos esperando la confirmación de Rebill. Esto suele tardar 5-15 segundos."
      />
    )
  }

  if (isActivated) {
    const tierLabel = tier === 'plus' ? 'Plus' : 'Pro'
    return (
      <ReturnLayout
        icon={<CheckCircle2 size={56} className="text-rendi-pos" strokeWidth={1.5} />}
        tone="success"
        title={`¡Bienvenido a Rendi ${tierLabel}!`}
        description={tier === 'pro'
          ? 'Tu suscripción Pro está activa. Tenés acceso a 60 análisis IA por semana, follow-ups, brokers ilimitados, export CSV y todas las features avanzadas.'
          : 'Tu suscripción Plus está activa. Tenés multi-broker, insights completos, comportamiento avanzado y export CSV.'
        }
        cta="Ir al dashboard"
        onCta={() => navigate('/dashboard')}
        footer="Te vamos a redirigir automáticamente en unos segundos…"
      />
    )
  }

  if (timedOut) {
    return (
      <ReturnLayout
        icon={<Clock size={56} className="text-data-amber" strokeWidth={1.5} />}
        tone="pending"
        title="Tu pago se está procesando"
        description="Rebill todavía no nos confirmó la activación. Es normal que tarde unos minutos en algunos casos. Refrescá esta página o esperá un email de confirmación."
        cta="Ir a mi cuenta"
        onCta={() => navigate('/config')}
      />
    )
  }

  // Fallback raro: free todavía, pero no timedOut. Mantener loader visual.
  return (
    <ReturnLayout
      icon={<Loader2 size={56} className="text-data-violet animate-spin" strokeWidth={1.5} />}
      tone="pending"
      title="Activando tu suscripción…"
      description="Esperando confirmación del webhook. Si no se activa en un minuto, refrescá la página."
    />
  )
}

export function BillingPending() {
  const navigate = useNavigate()
  const { tier, loading } = useTierPolling('pending')
  return (
    <ReturnLayout
      icon={loading
        ? <Loader2 size={56} className="text-data-amber animate-spin" strokeWidth={1.5} />
        : <Clock size={56} className="text-data-amber" strokeWidth={1.5} />
      }
      tone="pending"
      title="Tu pago está en proceso"
      description={loading
        ? "Verificando estado…"
        : "Rebill todavía está procesando tu pago. Apenas se acredite, tu cuenta pasa al tier nuevo automáticamente. Esto puede tardar minutos según el medio de pago elegido."
      }
      cta="Ver mi cuenta"
      onCta={() => navigate('/config')}
      footer={!loading && tier && `Tier actual: ${tier}`}
    />
  )
}

export function BillingFailure() {
  const navigate = useNavigate()
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
      <PageMeta
        title="Suscripción — Rendi"
        description="Estado de tu pago en Rendi."
        canonical="/billing/success"
        noindex={true}
      />
      <PageHeader eyebrow="Suscripción / Resultado" title="" subtitle="" />
      <div className={`${borderColor} border rounded-lg p-8 text-center mt-4`}>
        <div className="flex justify-center mb-4">{icon}</div>
        <h1 className="text-2xl font-bold text-ink-0 mb-3">{title}</h1>
        <p className="text-sm text-ink-2 leading-relaxed max-w-md mx-auto mb-6">
          {description}
        </p>
        {cta && (
          <button
            type="button"
            onClick={onCta}
            className="inline-flex items-center gap-1.5 text-sm font-medium bg-data-violet hover:bg-data-violet/90 text-white border border-data-violet rounded-sm px-6 py-2.5 transition-colors"
          >
            {tone === 'success' && <Sparkles size={13} strokeWidth={1.75} />}
            {cta}
            <ArrowRight size={13} strokeWidth={1.75} />
          </button>
        )}
        {footer && (
          <p className="text-xs text-ink-3 mt-4">{footer}</p>
        )}
      </div>
    </div>
  )
}
