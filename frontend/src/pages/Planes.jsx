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

import { Sparkles, Check, ArrowRight, Lock, Loader2, Clock } from 'lucide-react'
import { whatsappUrl } from '../utils/support'
import { WhatsAppIcon } from '../components/SupportWhatsAppFab'
import { useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import PageHeader from '../components/PageHeader'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { useAuth } from '../contexts/AuthContext'
import { track } from '../utils/track'
import { api } from '../utils/api'

// Precios USD/mes — fuente de verdad para Mobbex/dLocal (cobramos en USD,
// el procesador convierte ARS al day-rate del cliente). El display en Rendi
// muestra USD como precio principal + conversión ARS live al blue de hoy
// como subtítulo informativo.
export const PLUS_PRICE_USD = '4'
export const PRO_PRICE_USD = '9'
// Anual con ~16.5% off vs monthly × 12
export const PLUS_PRICE_ANNUAL_USD = '40'
export const PRO_PRICE_ANNUAL_USD = '90'

// Precios ARS legacy (todavía usados en algunos lugares para back-compat
// con el flow viejo de Mercado Pago). Cuando se complete la migración a
// USD-first, estos se pueden borrar.
export const ARS_PLUS_MONTHLY = '5.990'
export const ARS_PLUS_ANNUAL = '59.990'
export const ARS_PLUS_ANNUAL_MONTHLY_EQ = '4.999'
export const ARS_MONTHLY = '12.100'
const ARS_ANNUAL  = '123.420'
const ARS_ANNUAL_MONTHLY_EQ = '10.285'

// Formato ARS estilo Argentina (puntos como separador de miles, sin decimales)
function fmtArsConverted(usdPrice, tcBlue) {
  const num = Number(usdPrice) * tcBlue
  return Math.round(num).toLocaleString('es-AR')
}

// ─── Listas de features por plan ─────────────────────────────────────────────

export const FREE_FEATURES = [
  'Dashboard completo (4 KPIs + curva de evolución)',
  '6 análisis IA por semana',
  'Coach IA con 12 preguntas guiadas · 6 consultas/sem',
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
  { label: 'Coach IA con 12 preguntas guiadas', sub: 'Mismas 6 consultas/sem que Free' },
]

export const PRO_FEATURES = [
  { label: 'Todo lo del Plus' },
  { label: '60 análisis IA por semana', sub: '10× más que Free/Plus' },
  { label: 'Chat libre con Coach IA', sub: '60 consultas/sem · preguntá lo que quieras (vs 12 guiadas en Free/Plus)' },
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
  const { user } = useAuth()
  const [billingPeriod, setBillingPeriod] = useState('monthly')  // 'monthly' | 'annual'
  const [subscribing, setSubscribing] = useState(false)
  const [tcBlue, setTcBlue] = useState(1415)  // fallback
  const [changeModal, setChangeModal] = useState(null)  // null | { plan, period, preview, loading }

  useEffect(() => {
    api.get('/dolar')
      .then(d => { if (d?.blue?.venta) setTcBlue(d.blue.venta) })
      .catch(() => {})
  }, [])
  // Single source of truth: access_mode viene del backend.
  // Fallback: user con tier!=free pero sin access_mode (demo / legacy) → 'authorized'.
  const accessMode = user?.access_mode || (
    tier === 'pro' || tier === 'plus' ? 'authorized' : 'free'
  )
  const isAuthorizedMode = accessMode === 'authorized'
  const isCreditOnlyMode = accessMode === 'credit_only'
  const isCancelledMode = accessMode === 'cancelled'

  // Para back-compat con la lógica de cards: el user tiene tier vigente si
  // está en authorized o credit_only (en cancelled todavía mantiene acceso,
  // pero queremos ofrecerle "Reactivar" en vez de "Cambiar").
  const subCancelled = isCancelledMode
  const isFree = tier === 'free'
  const isPlus = tier === 'plus' && !isCancelledMode
  const isPro = tier === 'pro' && !isCancelledMode
  const isAdmin = tier === 'admin'
  const hasProTier = isPro || isAdmin
  const hasPlusOrBetter = isPlus || isPro || isAdmin

  // Estado del crédito (modelo Rendi-managed proration)
  const creditDays = Number(user?.credit_days_remaining || 0)
  const hasCredit = creditDays > 0
  const anchorPlan = user?.credit_anchor_plan || null
  const anchorPeriod = user?.credit_anchor_period || null
  const creditUsd = Number(user?.credit_remaining_usd || 0)
  const creditUntil = user?.credit_active_until || null

  // Un user puede cambiar de plan si tiene crédito activo (la conversión
  // re-acomoda el remaining al daily_rate nuevo). Si es free puro o nunca
  // pagó, el cambio se hace como subscribe nuevo.
  // Si está cancelled (manual), ofrecemos "Reactivar" en lugar de "Cambiar"
  // — el flujo de subscribe normal porque la intención del user fue parar.
  const canChangePlan = hasCredit && anchorPlan && anchorPeriod && !isCancelledMode

  useEffect(() => {
    track('planes_viewed', { from_tier: tier })
  }, [tier])

  // Match exacto entre el plan que el user tiene anclado y el plan de la card.
  // Si no hay anchor (user legacy o demo que nunca pasó por Rebill), caemos a
  // tier para que la UI no diga "Suscribirme" cuando el user ya tiene ese tier.
  function isCurrentAnchor(cardPlan, cardPeriod) {
    if (anchorPlan) {
      return anchorPlan === cardPlan && anchorPeriod === cardPeriod
    }
    // Fallback: si tier === cardPlan, lo marcamos como current SOLO si el
    // billing period matchea — los users legacy no tienen period info, pero
    // su subscription si lo tiene.
    if (tier !== cardPlan) return false
    const subPeriod = user?.subscription_period
    if (!subPeriod) return cardPeriod === 'monthly'  // default monthly para subs sin period
    return subPeriod === cardPeriod
  }

  async function onSubscribeClick(planId) {
    if (subscribing) return
    const targetPeriod = planId === 'plus' ? billingPeriod : billingPeriod
    track('upgrade_subscribe_clicked', {
      from_tier: tier,
      source: 'planes_page',
      plan: planId,
      period: targetPeriod,
    })
    setSubscribing(true)
    try {
      const body = { plan: planId, period: targetPeriod }
      const res = await api.post('/billing/subscribe', body)
      if (res.init_point) {
        window.location.href = res.init_point
      } else {
        alert('No pudimos generar el checkout. Probá de nuevo en unos minutos.')
      }
    } catch (ex) {
      // 409 con hint=use_change_plan: el user tiene sub activa, debería
      // usar el flujo de cambio de plan (no este). Abrimos el modal directamente.
      if (ex?.status === 409 && ex?.payload?.detail?.hint === 'use_change_plan') {
        await onChangePlanClick(planId, targetPeriod)
        return
      }
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

  // Cambio de plan con crédito proporcional. Pide preview al backend para
  // mostrar al user cuántos días le van a quedar con el plan nuevo antes
  // de confirmar.
  async function onChangePlanClick(planId, period) {
    if (subscribing) return
    track('upgrade_subscribe_clicked', {
      from_tier: tier,
      source: 'planes_page_change',
      plan: planId,
      period,
    })
    setChangeModal({ plan: planId, period, preview: null, loading: true })
    try {
      const preview = await api.get(
        `/billing/preview-change-plan?plan=${planId}&period=${period}`,
      )
      setChangeModal({ plan: planId, period, preview, loading: false })
    } catch (ex) {
      console.error('Preview change plan error:', ex)
      setChangeModal(null)
      alert('No pudimos calcular el cambio. ' + (ex?.message || 'Probá de nuevo.'))
    }
  }

  async function confirmChangePlan() {
    if (!changeModal || subscribing) return
    setSubscribing(true)
    try {
      await api.post('/billing/change-plan', {
        plan: changeModal.plan,
        period: changeModal.period,
      })
      track('subscription_plan_changed', {
        from_plan: anchorPlan,
        from_period: anchorPeriod,
        to_plan: changeModal.plan,
        to_period: changeModal.period,
      })
      setChangeModal(null)
      // Reload para refrescar /auth/me con el nuevo tier + credit window
      window.location.reload()
    } catch (ex) {
      console.error('Change plan error:', ex)
      const msg = ex?.payload?.detail?.error || ex?.message || 'Probá de nuevo.'
      alert('No pudimos cambiar el plan. ' + msg)
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

      {/* Banner contextual según access_mode. Cada estado tiene mensaje propio:
          - authorized: nada (auto-renueva, no hay que avisar)
          - credit_only: "tenés acceso por crédito, cambiá o configurá pago"
          - cancelled: "cancelaste, vence X, reactivá si querés seguir" */}
      {isCreditOnlyMode && hasCredit && anchorPlan && (
        <div className="max-w-3xl mx-auto mb-6 flex items-center gap-3 border border-data-cyan/40 bg-data-cyan/[0.06] rounded-lg px-4 py-3">
          <Clock size={16} strokeWidth={1.75} className="text-data-cyan flex-shrink-0" />
          <div className="flex-1 min-w-0 text-sm text-ink-1 leading-snug">
            Tu acceso a <span className="font-medium capitalize">{anchorPlan}</span>
            {' '}({anchorPeriod === 'annual' ? 'anual' : 'mensual'}) está garantizado por{' '}
            <span className="font-mono tabular text-ink-0">{Math.round(creditDays)} días más</span>
            {' '}usando el crédito de tu plan anterior.
            {' '}Si cambiás de plan, el crédito se reconvierte automáticamente.
          </div>
        </div>
      )}
      {isCancelledMode && hasCredit && anchorPlan && (
        <div className="max-w-3xl mx-auto mb-6 flex items-center gap-3 border border-line-2/70 bg-bg-2/40 rounded-lg px-4 py-3">
          <Clock size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />
          <div className="flex-1 min-w-0 text-sm text-ink-1 leading-snug">
            Cancelaste tu suscripción.
            {' '}Mantenés acceso a <span className="font-medium capitalize">{anchorPlan}</span>
            {' '}por <span className="font-mono tabular text-ink-0">{Math.round(creditDays)} días más</span>
            {' '}— después la cuenta vuelve a Free. Suscribite de nuevo para seguir.
          </div>
        </div>
      )}
      {isAuthorizedMode && hasCredit && anchorPlan && (
        <div className="max-w-3xl mx-auto mb-6 flex items-center gap-3 border border-data-violet/30 bg-data-violet/[0.05] rounded-lg px-4 py-3">
          <Clock size={16} strokeWidth={1.75} className="text-data-violet flex-shrink-0" />
          <div className="flex-1 min-w-0 text-sm text-ink-1 leading-snug">
            Tu <span className="font-medium capitalize">{anchorPlan}</span>
            {' '}({anchorPeriod === 'annual' ? 'anual' : 'mensual'}) se renueva en{' '}
            <span className="font-mono tabular text-ink-0">{Math.round(creditDays)} días</span>.
            {' '}Si cambiás de plan, el crédito se reconvierte sin cobrarte de nuevo.
          </div>
        </div>
      )}

      {loading ? (
        <div className="text-center py-12 text-ink-3 text-sm">Cargando planes…</div>
      ) : (
        <>
          {/* Toggle mensual / anual — afecta a Plus y Pro. Si el user ya es
              Pro/Admin SIN crédito, lo ocultamos (nada que cambiar). Si tiene
              crédito (modelo proration), lo mostramos siempre porque puede
              elegir un nuevo plan/period y convertir el crédito. */}
          {(!hasProTier || canChangePlan) && (
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
            {(() => {
              const plusIsCurrent = isCurrentAnchor('plus', billingPeriod)
              const plusCtaInfo = ctaForPlan({
                cardPlan: 'plus',
                cardPeriod: billingPeriod,
                isCurrent: plusIsCurrent,
                otherTier: hasProTier && !canChangePlan,
                canChangePlan,
                subscribing,
                hasCredit,
              })
              return (
                <PlanCard
                  variant="plus"
                  name="Plus"
                  tagline="Multi-broker + features avanzadas"
                  price={billingPeriod === 'annual' ? `USD ${(+PLUS_PRICE_ANNUAL_USD / 12).toFixed(2)}` : `USD ${PLUS_PRICE_USD}`}
                  priceSub={billingPeriod === 'annual'
                    ? `por mes · facturado anual (USD ${PLUS_PRICE_ANNUAL_USD})`
                    : 'por mes'}
                  priceFootnote={billingPeriod === 'annual'
                    ? `≈ ARS ${fmtArsConverted(+PLUS_PRICE_ANNUAL_USD / 12, tcBlue)} por mes al blue de hoy`
                    : `≈ ARS ${fmtArsConverted(PLUS_PRICE_USD, tcBlue)} al blue de hoy`}
                  features={PLUS_FEATURES}
                  isCurrent={plusIsCurrent || isPlus}
                  ctaLabel={plusCtaInfo.label}
                  ctaDisabled={plusCtaInfo.disabled}
                  ctaLoading={subscribing}
                  onCtaClick={() => {
                    if (plusCtaInfo.action === 'change') {
                      onChangePlanClick('plus', billingPeriod)
                    } else {
                      onSubscribeClick('plus')
                    }
                  }}
                />
              )
            })()}

            {/* ── Pro card — VIOLET PREMIUM con badge "Más completo" ─── */}
            {(() => {
              const proIsCurrent = isCurrentAnchor('pro', billingPeriod)
              const proCtaInfo = ctaForPlan({
                cardPlan: 'pro',
                cardPeriod: billingPeriod,
                isCurrent: proIsCurrent,
                otherTier: false,  // pro nunca es "Ya tenés un tier superior"
                canChangePlan,
                subscribing,
                hasCredit,
              })
              return (
                <PlanCard
                  variant="pro"
                  name="Pro"
                  tagline="IA premium + brokers ilimitados"
                  price={billingPeriod === 'annual' ? `USD ${(+PRO_PRICE_ANNUAL_USD / 12).toFixed(2)}` : `USD ${PRO_PRICE_USD}`}
                  priceSub={billingPeriod === 'annual'
                    ? `por mes · facturado anual (USD ${PRO_PRICE_ANNUAL_USD})`
                    : 'por mes'}
                  priceFootnote={billingPeriod === 'annual'
                    ? `≈ ARS ${fmtArsConverted(+PRO_PRICE_ANNUAL_USD / 12, tcBlue)} por mes al blue de hoy`
                    : `≈ ARS ${fmtArsConverted(PRO_PRICE_USD, tcBlue)} al blue de hoy`}
                  features={PRO_FEATURES}
                  badge="Más completo"
                  isCurrent={proIsCurrent || hasProTier}
                  ctaLabel={proCtaInfo.label}
                  ctaDisabled={proCtaInfo.disabled}
                  ctaLoading={subscribing}
                  onCtaClick={() => {
                    if (proCtaInfo.action === 'change') {
                      onChangePlanClick('pro', billingPeriod)
                    } else {
                      onSubscribeClick('pro')
                    }
                  }}
                />
              )
            })()}
          </div>
        </>
      )}

      {/* Modal de confirmación de cambio de plan con preview del crédito */}
      {changeModal && (
        <ChangePlanModal
          state={changeModal}
          subscribing={subscribing}
          onConfirm={confirmChangePlan}
          onClose={() => setChangeModal(null)}
        />
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

// ─── CTA logic: decide label + action según estado del user ────────────────
//
// Estados posibles para una card:
//   - Es el plan que el user tiene anchored (mismo plan + período): "Tu plan actual"
//   - User tiene crédito (puede cambiar): "Cambiar a X" → /api/billing/change-plan
//   - User es free sin crédito: "Suscribirme a X" → /api/billing/subscribe
//   - User tiene Pro sin crédito y la card es Plus: "Ya tenés Pro" (downgrade
//     no implementado vía subscribe — solo via cancel)
function ctaForPlan({ cardPlan, cardPeriod, isCurrent, otherTier, canChangePlan, subscribing, hasCredit }) {
  if (isCurrent) {
    return { label: 'Tu plan actual', disabled: true, action: 'none' }
  }
  if (otherTier) {
    return { label: 'Ya tenés Pro', disabled: true, action: 'none' }
  }
  if (subscribing) {
    return { label: 'Redirigiendo…', disabled: true, action: 'none' }
  }
  if (canChangePlan) {
    const planLabel = cardPlan === 'pro' ? 'Pro' : 'Plus'
    const periodLabel = cardPeriod === 'annual' ? ' anual' : ''
    return { label: `Cambiar a ${planLabel}${periodLabel}`, disabled: false, action: 'change' }
  }
  const periodLabel = cardPeriod === 'annual' ? ' anual' : ''
  return { label: `Suscribirme${periodLabel}`, disabled: false, action: 'subscribe' }
}


// ─── Modal de confirmación con preview del cambio ──────────────────────────
function ChangePlanModal({ state, subscribing, onConfirm, onClose }) {
  const { plan, period, preview, loading } = state
  const planLabel = plan === 'pro' ? 'Pro' : 'Plus'
  const periodLabel = period === 'annual' ? 'anual' : 'mensual'

  // Preview puede ser eligible:false si hay error de validación del backend
  const eligible = preview?.eligible

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4"
      onClick={onClose}
    >
      <div
        className="bg-bg-1 border border-line-2/70 rounded-lg max-w-md w-full p-6 shadow-[0_20px_60px_-10px_rgba(0,0,0,0.6)]"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-ink-0 mb-2">
          Cambiar a {planLabel} {periodLabel}
        </h2>

        {loading && (
          <div className="text-sm text-ink-2 py-4 flex items-center gap-2">
            <Loader2 size={14} strokeWidth={1.75} className="animate-spin" />
            Calculando tu nuevo crédito…
          </div>
        )}

        {!loading && preview && eligible && (
          <>
            <p className="text-sm text-ink-2 leading-relaxed mb-4">
              No te vamos a cobrar de nuevo. Convertimos tus{' '}
              <span className="font-mono tabular text-ink-0">${preview.remaining_usd}</span>
              {' '}de crédito (de tu plan {preview.from_plan} {preview.from_period === 'annual' ? 'anual' : 'mensual'})
              al rate del nuevo plan.
            </p>

            <div className="bg-bg-2/60 border border-line/40 rounded-md px-4 py-3 mb-5 space-y-2">
              <div className="flex items-baseline justify-between text-sm">
                <span className="text-ink-3 text-xs font-mono uppercase tracking-caps">
                  Antes ({preview.from_plan} {preview.from_period === 'annual' ? 'anual' : 'mensual'})
                </span>
                <span className="tabular text-ink-1">{Math.round(preview.current_days)} días</span>
              </div>
              <div className="flex items-baseline justify-between text-sm border-t border-line/40 pt-2">
                <span className="text-ink-3 text-xs font-mono uppercase tracking-caps">
                  Después ({planLabel} {periodLabel})
                </span>
                <span className={`tabular font-semibold ${
                  preview.new_days >= preview.current_days ? 'text-rendi-pos' : 'text-data-violet'
                }`}>
                  {Math.round(preview.new_days)} días
                </span>
              </div>
            </div>

            <p className="text-[11px] text-ink-3 leading-relaxed mb-5">
              Cuando se te acabe el crédito te avisamos por email para que te re-suscribas.
              Podés volver a cambiar de plan en cualquier momento.
            </p>

            <div className="flex gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={subscribing}
                className="flex-1 inline-flex items-center justify-center text-sm font-medium bg-bg-2/60 hover:bg-bg-2 text-ink-1 border border-line/60 rounded-sm py-2 transition-colors"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={onConfirm}
                disabled={subscribing}
                className="flex-1 inline-flex items-center justify-center gap-1.5 text-sm font-medium bg-data-violet text-white hover:bg-data-violet/90 border border-data-violet rounded-sm py-2 transition-colors disabled:opacity-60"
              >
                {subscribing
                  ? <Loader2 size={13} strokeWidth={1.75} className="animate-spin" />
                  : <Sparkles size={13} strokeWidth={1.75} />}
                <span>Confirmar cambio</span>
              </button>
            </div>
          </>
        )}

        {!loading && preview && !eligible && (
          <>
            <p className="text-sm text-ink-2 mb-4">
              {preview?.reason === 'same_plan'
                ? 'Ya estás en este plan.'
                : 'No podemos cambiar de plan en este momento. Probá suscribirte normal.'}
            </p>
            <button
              type="button"
              onClick={onClose}
              className="w-full text-sm font-medium bg-bg-2/60 hover:bg-bg-2 text-ink-1 border border-line/60 rounded-sm py-2 transition-colors"
            >
              Cerrar
            </button>
          </>
        )}
      </div>
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
