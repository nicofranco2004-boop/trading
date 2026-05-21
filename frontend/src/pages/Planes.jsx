// Planes — página dedicada de comparativa Free vs Pro.
// ═══════════════════════════════════════════════════════════════════════════
// Inspirado en pricing pages tipo Claude / Stripe: dos cards, Free a la
// izquierda, Pro destacado a la derecha, lista de features con ✓ y CTA
// principal en el card que el user no tiene aún.
//
// Linkeada desde:
//   • Config PlanHero ("Mejorar plan" button)
//   • LockedSection CTAs (cuando el user toca un gate)
//   • UpgradeModal y UpgradePromoCard
//
// CTA "Suscribirme" pega a /api/billing/subscribe → MP devuelve init_point
// → redirigimos al user al checkout de MP. Tras pagar, MP nos vuelve a
// /billing/success y el webhook activa tier='pro'.

import { Sparkles, Check, ArrowRight, Lock, Loader2 } from 'lucide-react'
import { whatsappUrl } from '../utils/support'
import { WhatsAppIcon } from '../components/SupportWhatsAppFab'
import { useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import PageHeader from '../components/PageHeader'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { track } from '../utils/track'
import { api } from '../utils/api'

// Precio Pro en USD/mes — placeholder que vamos a iterar.
// Cambiar acá afecta toda la app (Config PlanHero, UpgradeModal, etc.).
export const PRO_PRICE_USD = '6.99'
export const PLUS_PRICE_USD = '4'

// Precios ARS (mantener sync con backend/billing/pricing.py)
export const ARS_PLUS_MONTHLY = '5.990'  // base 4.950 + IVA 21% (~1.040)
export const ARS_PLUS_ANNUAL = '59.990'  // base 49.580 + IVA 21% (~10.410), 16.5% off
export const ARS_PLUS_ANNUAL_MONTHLY_EQ = '4.999'  // total anual / 12
export const ARS_MONTHLY = '12.100'      // base 10.000 + IVA 21%
const ARS_ANNUAL  = '123.420'     // base 102.000 + IVA 21% (15% descuento)
const ARS_ANNUAL_MONTHLY_EQ = '10.285'  // total anual / 12

// ─── Listas de features por plan ─────────────────────────────────────────────

export const FREE_FEATURES = [
  'Dashboard completo (4 KPIs + curva de evolución)',
  '6 análisis IA por semana',
  'Hasta 1 broker',
  'Insights básicos (TWR + benchmark + drawdown)',
  'Diagnóstico con 3 observaciones',
  '1 análisis de comportamiento',
  'Posiciones, Operaciones, Wrapped, Objetivos',
  'Reportes: vista previa del último mes',
]

export const PLUS_FEATURES = [
  { label: 'Todo lo del Free' },
  { label: 'Hasta 3 brokers', sub: '3× más' },
  { label: 'Insights diagnóstico completo (6 obs)' },
  { label: '4 análisis de comportamiento', sub: 'la mitad de los detectores' },
  { label: 'Distribución por activo' },
  { label: 'Reportes históricos completos (todos los meses)' },
  { label: 'Export CSV consolidado para tu contador', sub: 'Compras, ventas, depósitos, retiros y dividendos' },
  { label: '6 análisis IA por semana', sub: 'Misma cuota que Free (Pro multiplica 10×)' },
]

export const PRO_FEATURES = [
  { label: 'Todo lo del Plus' },
  { label: '60 análisis IA por semana', sub: '10× más que Free/Plus' },
  { label: 'Respuestas con causalidad y comparaciones', sub: 'No solo descripción' },
  { label: 'Follow-ups: profundizá cada análisis con preguntas libres' },
  { label: 'Brokers ilimitados' },
  { label: 'Comportamiento completo', sub: 'Todos los detectores (8+)' },
  { label: 'AI Hub: exploración libre sobre tu portfolio', comingSoon: true },
  { label: 'Tax helper AFIP: cálculo FIFO + reporte fiscal', comingSoon: true },
]

// ─── Página ──────────────────────────────────────────────────────────────────

export default function Planes() {
  const navigate = useNavigate()
  const { tier, loading } = usePlanFeatures()
  const [billingPeriod, setBillingPeriod] = useState('monthly')  // 'monthly' | 'annual'
  const [subscribing, setSubscribing] = useState(false)
  const isFree = tier === 'free'
  const isPlus = tier === 'plus'
  const isPro = tier === 'pro'
  const isAdmin = tier === 'admin'
  // Admin se trata como pro a efectos del marcador (visualmente está en el
  // lado Pro de la comparativa).
  const hasProTier = isPro || isAdmin
  const hasPlusOrBetter = isPlus || isPro || isAdmin

  useEffect(() => {
    track('planes_viewed', { from_tier: tier })
  }, [tier])

  async function onSubscribeClick(planId) {
    if (subscribing) return
    track('upgrade_subscribe_clicked', {
      from_tier: tier,
      source: 'planes_page',
      plan: planId,
      period: planId === 'plus' ? 'monthly' : billingPeriod,
    })
    setSubscribing(true)
    try {
      const body = planId === 'plus'
        ? { plan: 'plus', period: 'monthly' }
        : { plan: 'pro', period: billingPeriod }
      const res = await api.post('/billing/subscribe', body)
      if (res.init_point) {
        window.location.href = res.init_point
      } else {
        alert('No pudimos generar el checkout. Probá de nuevo en unos minutos.')
      }
    } catch (ex) {
      if (ex?.status === 409) {
        alert('Ya tenés una suscripción activa. Revisá tu estado en Configuración.')
        navigate('/config')
        return
      }
      console.error('Subscribe error:', ex)
      alert('No pudimos iniciar la suscripción. ' + (ex?.message || 'Probá de nuevo más tarde.'))
    } finally {
      setSubscribing(false)
    }
  }

  return (
    <div className="page-shell">
      <PageHeader
        eyebrow="Planes / Mejora tu cuenta"
        title="Elegí el plan que mejor te sirve"
        subtitle="Empezá gratis. Mejorá cuando necesites análisis más profundos, más brokers o features pro."
      />

      {loading ? (
        <div className="text-center py-12 text-ink-3 text-sm">Cargando planes…</div>
      ) : (
        <>
          {/* Toggle mensual / anual — afecta a Plus y Pro. Ocultamos si el
              user ya es Pro/Admin (no le mostramos opciones de upgrade). */}
          {!hasProTier && (
            <div className="flex justify-center mb-6">
              <div className="inline-flex bg-bg-2 border border-line/60 rounded-sm p-0.5">
                <button
                  type="button"
                  onClick={() => setBillingPeriod('monthly')}
                  className={`px-4 py-1.5 text-xs font-medium rounded-sm transition-colors ${
                    billingPeriod === 'monthly'
                      ? 'bg-bg-3 text-ink-0'
                      : 'text-ink-2 hover:text-ink-0'
                  }`}
                >
                  Mensual
                </button>
                <button
                  type="button"
                  onClick={() => setBillingPeriod('annual')}
                  className={`px-4 py-1.5 text-xs font-medium rounded-sm transition-colors inline-flex items-center gap-2 ${
                    billingPeriod === 'annual'
                      ? 'bg-bg-3 text-ink-0'
                      : 'text-ink-2 hover:text-ink-0'
                  }`}
                >
                  Anual
                  <span className="text-[9px] font-mono uppercase tracking-caps px-1 py-px rounded-sm bg-rendi-pos/15 text-rendi-pos">
                    −15%
                  </span>
                </button>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-6xl mx-auto pt-6">
            {/* ── Free card — gris neutral ─── */}
            <PlanCard
              variant="free"
              name="Free"
              tagline="Lo esencial para empezar"
              price="Gratis"
              priceSub="Para siempre"
              features={FREE_FEATURES.map(label => ({ label }))}
              isCurrent={isFree}
              ctaLabel={isFree ? 'Tu plan actual' : 'Tu plan base'}
              ctaDisabled
            />

            {/* ── Plus card — cyan distintivo (tier intermedio) ─── */}
            <PlanCard
              variant="plus"
              name="Plus"
              tagline="Multi-broker + features avanzadas"
              price={billingPeriod === 'annual' ? `ARS ${ARS_PLUS_ANNUAL_MONTHLY_EQ}` : `ARS ${ARS_PLUS_MONTHLY}`}
              priceSub={billingPeriod === 'annual'
                ? `por mes · facturado anual (ARS ${ARS_PLUS_ANNUAL})`
                : 'por mes · precio final'}
              priceFootnote={billingPeriod === 'annual'
                ? `Ahorrás ARS 11.890 al año vs mensual`
                : `Equivalente a USD ${PLUS_PRICE_USD} al blue`}
              features={PLUS_FEATURES}
              isCurrent={isPlus}
              ctaLabel={
                isPlus
                  ? 'Tu plan actual'
                  : hasProTier
                    ? 'Ya tenés Pro'
                    : subscribing
                      ? 'Redirigiendo…'
                      : (billingPeriod === 'annual' ? 'Suscribirme anual' : 'Suscribirme a Plus')
              }
              ctaDisabled={isPlus || hasProTier || subscribing}
              ctaLoading={subscribing}
              onCtaClick={() => onSubscribeClick('plus')}
            />

            {/* ── Pro card — VIOLET PREMIUM con badge "Más completo" ─── */}
            <PlanCard
              variant="pro"
              name="Pro"
              tagline="IA premium + brokers ilimitados"
              price={billingPeriod === 'annual' ? `ARS ${ARS_ANNUAL_MONTHLY_EQ}` : `ARS ${ARS_MONTHLY}`}
              priceSub={billingPeriod === 'annual'
                ? `por mes · facturado anual (ARS ${ARS_ANNUAL})`
                : 'por mes · precio final'}
              priceFootnote={billingPeriod === 'annual'
                ? `Ahorrás ARS 21.780 al año vs mensual`
                : `Equivalente a USD ${PRO_PRICE_USD} al blue`}
              features={PRO_FEATURES}
              badge="Más completo"
              isCurrent={hasProTier}
              ctaLabel={
                hasProTier
                  ? 'Tu plan actual'
                  : subscribing
                    ? 'Redirigiendo…'
                    : (billingPeriod === 'annual' ? 'Suscribirme anual' : 'Suscribirme a Pro')
              }
              ctaDisabled={hasProTier || subscribing}
              ctaLoading={subscribing}
              onCtaClick={() => onSubscribeClick('pro')}
            />
          </div>
        </>
      )}

      <div className="text-center mt-8 space-y-3">
        <a
          href={whatsappUrl('Hola, tengo una consulta sobre los planes de Rendi.')}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1.5 text-xs text-ink-2 hover:text-[#25D366] transition-colors"
        >
          <WhatsAppIcon size={13} />
          ¿Dudas sobre el plan? Hablanos por WhatsApp
        </a>
        <div>
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="text-xs text-ink-3 hover:text-ink-0 transition-colors inline-flex items-center gap-1"
          >
            Volver atrás
          </button>
        </div>
      </div>

      <p className="text-[11px] text-ink-3 text-center max-w-2xl mx-auto mt-4 leading-relaxed">
        Suscribite cuando te conviene y cancelá cuando quieras.
        Pro está actualmente en desarrollo — cuando esté disponible te avisamos por email.
      </p>
    </div>
  )
}

// ─── Card individual ────────────────────────────────────────────────────────

// Jerarquía visual:
//   - 'free' (default): gris neutral, sin acento
//   - 'plus':           acento cyan suave (tier intermedio, "buena opción")
//   - 'pro':            VIOLET PREMIUM con glow + gradient + badge — el más llamativo
function PlanCard({
  name, tagline, price, priceSub, priceFootnote, features,
  isCurrent, ctaLabel, ctaDisabled, ctaLoading, onCtaClick,
  variant = 'free',  // 'free' | 'plus' | 'pro'
  badge,             // ej: "Recomendado", "Más completo"
}) {
  const isPlus = variant === 'plus'
  const isPro  = variant === 'pro'
  // Hover: cada card levanta + intensifica shadow / border. Pro suma escala.
  const wrapperClass = isPro
    ? 'border-2 border-data-violet/60 bg-gradient-to-br from-data-violet/[0.08] via-bg-1 to-data-violet/[0.04] shadow-[0_0_50px_-12px_rgba(139,125,255,0.35)] ring-1 ring-data-violet/20 hover:-translate-y-1.5 hover:scale-[1.02] hover:shadow-[0_0_70px_-8px_rgba(139,125,255,0.55)] hover:border-data-violet hover:ring-data-violet/40'
    : isPlus
      ? 'border border-data-cyan/30 bg-bg-1 hover:-translate-y-1.5 hover:border-data-cyan/60 hover:shadow-[0_0_40px_-12px_rgba(70,198,224,0.35)]'
      : 'border border-line/80 bg-bg-1 hover:-translate-y-1.5 hover:border-line/100 hover:shadow-[0_0_30px_-12px_rgba(255,255,255,0.08)]'
  const titleColor = isPro ? 'text-data-violet' : isPlus ? 'text-data-cyan' : 'text-ink-0'
  const ctaBg = ctaDisabled
    ? 'bg-bg-2/60 text-ink-3 cursor-default border border-line/40'
    : isPro
      ? 'bg-data-violet text-white hover:bg-data-violet/90 border border-data-violet shadow-md shadow-data-violet/20'
      : isPlus
        ? 'bg-data-cyan/10 text-data-cyan hover:bg-data-cyan/15 border border-data-cyan/40'
        : 'bg-bg-2 hover:bg-bg-2/80 text-ink-1 border border-line/60'

  return (
    <div className={`relative rounded-lg p-6 sm:p-7 flex flex-col transition-all duration-300 ease-out ${wrapperClass}`}>
      {/* Badge (ej. "Más completo" para Pro) */}
      {badge && (
        <span className={`absolute -top-2.5 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 px-2.5 py-0.5 rounded-sm text-[10px] font-mono uppercase tracking-caps ${
          isPro ? 'bg-data-violet text-white shadow-sm shadow-data-violet/40' : 'bg-data-cyan/15 text-data-cyan border border-data-cyan/30'
        }`}>
          {badge}
        </span>
      )}

      {isCurrent && (
        <span className="absolute top-3 right-3 inline-flex items-center gap-1 px-2 py-0.5 rounded-sm bg-rendi-pos/15 text-rendi-pos text-[10px] font-mono uppercase tracking-caps">
          <span className="w-1.5 h-1.5 rounded-full bg-rendi-pos" /> Tu plan
        </span>
      )}

      {/* Heading */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-1">
          {isPro && <Sparkles size={18} strokeWidth={1.75} className="text-data-violet" />}
          <h2 className={`text-2xl font-bold ${titleColor}`}>
            {name}
          </h2>
        </div>
        <p className="text-sm text-ink-2">{tagline}</p>
      </div>

      {/* Price — más grande para Pro */}
      <div className="mb-5">
        <div className="flex items-baseline gap-1.5">
          <span className={`${isPro ? 'text-4xl' : 'text-3xl'} font-bold text-ink-0 tabular`}>{price}</span>
          {priceSub && <span className="text-xs text-ink-3">{priceSub}</span>}
        </div>
        {priceFootnote && (
          <p className="text-[10px] text-ink-3 mt-1.5 leading-snug">{priceFootnote}</p>
        )}
      </div>

      {/* CTA */}
      <button
        type="button"
        onClick={onCtaClick}
        disabled={ctaDisabled}
        className={`w-full inline-flex items-center justify-center gap-1.5 text-sm font-medium rounded-sm py-2.5 mb-5 transition-colors ${ctaBg}`}
      >
        {ctaLoading
          ? <Loader2 size={13} strokeWidth={1.75} className="animate-spin" />
          : (!ctaDisabled && isPro && <Sparkles size={13} strokeWidth={1.75} />)
        }
        <span>{ctaLabel}</span>
        {!ctaDisabled && !ctaLoading && <ArrowRight size={13} strokeWidth={1.75} />}
      </button>

      {/* Feature list */}
      <ul className="space-y-2.5 flex-1">
        {features.map((f, i) => {
          // Item puede ser string o {label, sub, comingSoon}
          const isObj = typeof f === 'object'
          const label = isObj ? f.label : f
          const sub = isObj ? f.sub : null
          const comingSoon = isObj ? f.comingSoon : false
          return (
            <li key={i} className="flex items-start gap-2 text-sm">
              {comingSoon
                ? <Lock size={12} strokeWidth={2} className="text-data-amber mt-0.5 flex-shrink-0" />
                : <Check size={12} strokeWidth={2.5} className={`mt-0.5 flex-shrink-0 ${isPro ? 'text-data-violet' : isPlus ? 'text-data-cyan' : 'text-rendi-pos'}`} />
              }
              <div className="leading-snug">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className={comingSoon ? 'text-ink-2' : 'text-ink-1'}>{label}</span>
                  {comingSoon && (
                    <span className="font-mono text-[9px] uppercase tracking-caps px-1 py-px rounded-sm bg-data-amber/15 text-data-amber">
                      Próximamente
                    </span>
                  )}
                </div>
                {sub && <div className="text-[11px] text-ink-3 mt-0.5">{sub}</div>}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
