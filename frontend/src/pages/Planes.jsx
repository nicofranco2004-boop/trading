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
import { useNavigate, Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import PageMeta from '../components/PageMeta'
import PageHeader from '../components/PageHeader'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { useAuth } from '../contexts/AuthContext'
import { track } from '../utils/track'
import { trackEvent } from '../utils/analytics'
import { isSafePaymentUrl } from '../utils/safeUrl'
import { api } from '../utils/api'

// ─── Pricing en ARS hardcoded (2026-05-31) ──────────────────────────────────
// Cobramos en pesos fijo (no convertido al blue). Razón:
//   1. Rebill cobra fee mínimo USD 500/mes si facturás en USD — inviable
//      hasta tener ~200 users pagos.
//   2. ARS fijo = pricing simple sin sorpresas para el user.
//   3. Cuando el blue suba significativamente (+15%), ajustamos manualmente
//      con anuncio previo. Ver "Playbook de ajuste" en project_rebill_pricing.md
//
// Antes: pricing en USD con conversión arsPriceRounded(usd, tcBlue) → ARS.
// Ahora: ARS hardcoded como source of truth.
export const PLUS_PRICE_ARS_MONTHLY = '5990'
export const PRO_PRICE_ARS_MONTHLY = '13990'
// Anual con ~16% off vs monthly × 12 (mismo ratio que tenían los USD)
export const PLUS_PRICE_ARS_ANNUAL = '59900'   // vs 12×5990=71880 → 16.7% off
export const PRO_PRICE_ARS_ANNUAL = '139900'   // vs 12×13990=167880 → 16.7% off

// Mensual equivalente cuando elige plan anual (para display "X/mes · facturado anual")
// Math.round(annual / 12)
export const PLUS_PRICE_ARS_ANNUAL_MONTHLY_EQ = '4992'   // 59900/12 = 4991.67
export const PRO_PRICE_ARS_ANNUAL_MONTHLY_EQ = '11658'   // 139900/12 = 11658.33

// Helper: formatea un número ARS al estilo argentino con punto miles.
//   5990 → "5.990"
//   59900 → "59.900"
//   139900 → "139.900"
export function fmtArs(amount) {
  const n = typeof amount === 'string' ? parseInt(amount, 10) : amount
  if (!Number.isFinite(n)) return String(amount)
  return n.toLocaleString('es-AR')
}

// ─── Aliases back-compat (deprecated) ───────────────────────────────────────
// Mantenemos estas exports para no romper imports existentes durante la
// transición. Los callers nuevos deben usar las constants ARS de arriba.
//
// @deprecated — usar PLUS_PRICE_ARS_MONTHLY directamente
export const PLUS_PRICE_USD = '4'
// @deprecated — usar PRO_PRICE_ARS_MONTHLY directamente
export const PRO_PRICE_USD = '9'
// @deprecated — usar PLUS_PRICE_ARS_ANNUAL directamente
export const PLUS_PRICE_ANNUAL_USD = '40'
// @deprecated — usar PRO_PRICE_ARS_ANNUAL directamente
export const PRO_PRICE_ANNUAL_USD = '90'
// @deprecated — ya no convertimos, usamos precios ARS fijos
export const ARS_PLUS_MONTHLY = PLUS_PRICE_ARS_MONTHLY
export const ARS_PLUS_ANNUAL = PLUS_PRICE_ARS_ANNUAL
export const ARS_PLUS_ANNUAL_MONTHLY_EQ = PLUS_PRICE_ARS_ANNUAL_MONTHLY_EQ
export const ARS_MONTHLY = PRO_PRICE_ARS_MONTHLY
// @deprecated — ya no hace falta convertir, precios son ARS fijos
export function arsPriceRounded(usdAmount, _tcBlueIgnored) {
  // Fallback de back-compat: si alguien todavía llama esto con USD 4 o USD 9,
  // mapeamos a los ARS hardcoded. Cualquier otro valor cae a un cálculo
  // legacy con TC 1466 (solo para no romper en lugares oscuros).
  const usd = String(usdAmount).trim()
  if (usd === '4' || usd === '4.0') return PLUS_PRICE_ARS_MONTHLY
  if (usd === '9' || usd === '9.0') return PRO_PRICE_ARS_MONTHLY
  if (usd === '40') return PLUS_PRICE_ARS_ANNUAL
  if (usd === '90') return PRO_PRICE_ARS_ANNUAL
  // Fallback genérico (no debería ejecutarse en producción)
  const raw = Number(usdAmount) * 1466
  const rounded = Math.round(raw / 100) * 100
  return rounded.toLocaleString('es-AR')
}

// ─── Listas de features por plan (template 3-secciones) ──────────────────────
// Cada feature es { label, sub? } — sub es la nota chica abajo (opcional).
// El template separa visualmente:
//   1. essentials: lo CORE del plan (4-5 items)
//   2. diff: el AHA del upgrade vs el plan anterior (Plus vs Free, Pro vs Plus)
//   3. quotas: grid mini de números (análisis/sem, chat/sem, brokers)
// Sin emojis (decisión de producto: ASCII + tipografía + color, no glyph).

export const FREE_FEATURES = {
  essentials: [
    { label: 'Dashboard completo con 4 KPIs + curva de evolución' },
    { label: 'Posiciones, Operaciones, Wrapped anual y Objetivos' },
    { label: 'Insights con TWR, benchmarks (S&P, inflación AR, dólar) y drawdown' },
    { label: '3 observaciones diagnósticas + 3 detectores de comportamiento' },
    { label: 'Coach IA con 12 preguntas guiadas (taster)' },
    { label: 'Reportes: vista previa del último mes' },
  ],
  // Free no tiene "diff" — es el baseline.
  diff: null,
  quotas: [
    { label: 'Análisis IA / sem', value: '6' },
    { label: 'Chat Coach IA / sem', value: '3' },
    { label: 'Brokers', value: '1' },
  ],
}

export const PLUS_FEATURES = {
  essentials: [
    { label: 'Todo lo del Free' },
    { label: 'Diagnóstico de Insights completo con 6 observaciones' },
    { label: '6 detectores de comportamiento visibles (de 12 disponibles)' },
    { label: 'Métricas de riesgo avanzadas (5)', sub: 'Volatilidad, beta, Sharpe, Sortino y CAGR' },
    { label: 'Distribución por activo desbloqueada' },
    { label: 'Reportes históricos completos (todos los meses)' },
    { label: 'Export CSV consolidado para tu contador', sub: 'Compras, ventas, depósitos, retiros y dividendos' },
    { label: '3× más Chat Coach IA que Free', sub: '9 consultas/semana vs 3 en Free' },
  ],
  diff: {
    title: 'Vs Free',
    items: [
      'Hasta 3 brokers (3× más)',
      '3× más Chat Coach IA (9 vs 3 /sem)',
      '6 observaciones de diagnóstico (2× más)',
      '6 detectores de comportamiento (2× más)',
      'Métricas de riesgo: Sharpe, Sortino, volatilidad y más',
      'Reportes históricos + Export CSV',
    ],
  },
  quotas: [
    { label: 'Análisis IA / sem', value: '6', note: 'igual que Free' },
    { label: 'Chat Coach IA / sem', value: '9', note: '3× Free' },
    { label: 'Brokers', value: '3' },
  ],
}

export const PRO_FEATURES = {
  essentials: [
    { label: 'Todo lo del Plus' },
    { label: '60 análisis IA / semana', sub: '10× más que Free y Plus' },
    { label: 'Chat libre con el Coach IA', sub: '40 consultas/sem · texto libre, sin restricción de preguntas' },
    { label: 'Respuestas con causalidad y comparaciones', sub: 'Modo research-note: no solo describe, infiere por qué' },
    { label: 'Follow-ups: profundizá cualquier análisis con preguntas libres' },
    { label: 'Memoria persistente del Coach', sub: 'Los hechos que le aclarás se respetan entre sesiones' },
    { label: 'Brokers ilimitados' },
    { label: '12 detectores de comportamiento completos' },
    { label: 'Diagnóstico de Insights ilimitado' },
    { label: 'Métricas exclusivas: Alpha, Information Ratio y Calmar', sub: 'Rendimiento ajustado por riesgo de mercado y drawdown' },
  ],
  diff: {
    title: 'Vs Plus',
    items: [
      '10× más análisis IA (60/sem vs 6/sem)',
      'Chat libre del Coach (vs 12 preguntas guiadas)',
      'IA con causalidad y memoria persistente',
      'Comportamiento completo (12 vs 6) + brokers ilimitados',
      'Métricas exclusivas: Alpha, Information Ratio y Calmar',
    ],
  },
  quotas: [
    { label: 'Análisis IA / sem', value: '60' },
    { label: 'Chat Coach IA / sem', value: '40' },
    { label: 'Brokers', value: '∞' },
  ],
  // Roadmap visible — features prometidas que están en construcción.
  // Diferenciadas visualmente del resto (no son CHECKS, son CLOCKS).
  // Decisión de producto: mantenerlas para señalizar dirección, pero NUNCA
  // mezcladas con las features activas.
  roadmap: [
    'AI Hub: exploración libre sobre tu portfolio',
    'Tax helper AFIP: cálculo FIFO + reporte fiscal',
  ],
}

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
    // GA4: click en CTA "Suscribirme" — funnel step 1 (intent)
    trackEvent('subscribe_clicked', {
      from_tier: tier,
      plan: planId,
      period: targetPeriod,
    })
    setSubscribing(true)
    try {
      const body = { plan: planId, period: targetPeriod }
      const res = await api.post('/billing/subscribe', body)
      // SECURITY: validar que init_point es del dominio de Rebill antes de
      // redirigir. Si el backend devuelve una URL inesperada (tampered,
      // bug, comprometido), evitamos open-redirect / phishing.
      if (res.init_point && isSafePaymentUrl(res.init_point)) {
        // GA4: payment link creado, redirect a Rebill — funnel step 2
        trackEvent('subscribe_started', { plan: planId, period: targetPeriod })
        window.location.href = res.init_point
      } else if (res.init_point) {
        console.error('Subscribe: init_point no es de un dominio Rebill confiable:', res.init_point)
        alert('No pudimos validar el checkout. Probá de nuevo o escribinos a soporte@rendi.finance.')
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
      <PageMeta
        title="Planes y precios — Rendi | Plus desde ARS 5.990/mes"
        description="Elegí el plan de Rendi: Free para empezar, Plus para multi-broker, Pro con Coach IA libre y memoria. Precios en pesos al blue del día. Cancelá cuando quieras."
        canonical="/planes"
      />
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
              features={FREE_FEATURES}
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
                isCancelledMode,
              })
              // Pricing ARS hardcoded (2026-05-31): cobramos pesos fijos.
              // No hay conversión a USD ni dependencia del blue para el display.
              const arsMonthly = billingPeriod === 'annual'
                ? fmtArs(PLUS_PRICE_ARS_ANNUAL_MONTHLY_EQ)
                : fmtArs(PLUS_PRICE_ARS_MONTHLY)
              const arsAnnualTotal = billingPeriod === 'annual' ? fmtArs(PLUS_PRICE_ARS_ANNUAL) : null
              return (
                <PlanCard
                  variant="plus"
                  name="Plus"
                  tagline="Multi-broker + features avanzadas"
                  price={`$${arsMonthly}`}
                  priceSub={billingPeriod === 'annual'
                    ? `por mes · facturado anual ($${arsAnnualTotal})`
                    : 'por mes'}
                  priceFootnote="Sin sorpresas. Pago mensual en pesos."
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
                isCancelledMode,
              })
              const arsMonthly = billingPeriod === 'annual'
                ? fmtArs(PRO_PRICE_ARS_ANNUAL_MONTHLY_EQ)
                : fmtArs(PRO_PRICE_ARS_MONTHLY)
              const arsAnnualTotal = billingPeriod === 'annual' ? fmtArs(PRO_PRICE_ARS_ANNUAL) : null
              return (
                <PlanCard
                  variant="pro"
                  name="Pro"
                  tagline="IA premium + brokers ilimitados"
                  price={`$${arsMonthly}`}
                  priceSub={billingPeriod === 'annual'
                    ? `por mes · facturado anual ($${arsAnnualTotal})`
                    : 'por mes'}
                  priceFootnote="Sin sorpresas. Pago mensual en pesos."
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
        Suscribite cuando te conviene y cancelá cuando quieras. Cobramos en pesos al TC blue del día.
      </p>

      {/* Footer legal — visible siempre. Compliance: el user puede leer T&C
          y política de reembolso ANTES de pagar. También para users no
          autenticados que llegan a /planes desde la landing. */}
      <p className="text-[11px] text-ink-3 text-center max-w-2xl mx-auto mt-3 leading-relaxed">
        Al suscribirte aceptás nuestros{' '}
        <Link to="/terminos" className="underline decoration-dotted underline-offset-2 hover:text-ink-1">
          Términos y Condiciones
        </Link>
        {' '}y nuestra{' '}
        <Link to="/reembolso" className="underline decoration-dotted underline-offset-2 hover:text-ink-1">
          Política de Reembolso
        </Link>.
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
//   - User canceló manualmente (cancelled mode, grace period): puede
//     re-suscribirse a cualquier plan. Su plan anchor muestra "Reactivar"
//     y los otros "Suscribirme". Conceptualmente la sub está terminada;
//     el acceso restante viene del período ya pagado.
function ctaForPlan({ cardPlan, cardPeriod, isCurrent, otherTier, canChangePlan, subscribing, hasCredit, isCancelledMode }) {
  if (subscribing) {
    return { label: 'Redirigiendo…', disabled: true, action: 'none' }
  }
  // Cancelled mode: NO mostramos disabled por "ya tenés ese plan" — el user
  // canceló y queremos darle todos los planes habilitados para re-suscribirse.
  // Si la card es el anchor del crédito, label "Reactivar"; si es otra,
  // "Suscribirme". Cualquiera dispara el flujo /billing/subscribe normal,
  // que respeta el crédito remanente (se suma al período nuevo).
  if (isCancelledMode) {
    const planLabel = cardPlan === 'pro' ? 'Pro' : 'Plus'
    const periodLabel = cardPeriod === 'annual' ? ' anual' : ''
    if (isCurrent) {
      return { label: `Reactivar ${planLabel}${periodLabel}`, disabled: false, action: 'subscribe' }
    }
    return { label: `Suscribirme a ${planLabel}${periodLabel}`, disabled: false, action: 'subscribe' }
  }
  if (isCurrent) {
    return { label: 'Tu plan actual', disabled: true, action: 'none' }
  }
  if (otherTier) {
    return { label: 'Ya tenés Pro', disabled: true, action: 'none' }
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
                className="flex-1 inline-flex items-center justify-center gap-1.5 text-sm font-medium bg-data-violet text-white hover:bg-data-violet/90 border border-data-violet rounded-sm py-2 transition-colors disabled:opacity-60 press"
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

      {/* ─── Features estructuradas en 3 secciones ──────────────────────── */}
      {/* Soporta dos shapes para back-compat:                                */}
      {/* - Array de strings/objs (legacy)                                    */}
      {/* - Object {essentials, diff?, quotas, roadmap?} (nuevo template)    */}
      {Array.isArray(features) ? (
        <PlanFeatureListLegacy items={features} variant={variant} />
      ) : (
        <div className="flex-1 flex flex-col gap-5">
          {/* Cuotas — grid mini de números arriba para escaneo rápido */}
          {features.quotas && features.quotas.length > 0 && (
            <PlanQuotaGrid quotas={features.quotas} variant={variant} />
          )}

          {/* Esenciales — features core del plan */}
          {features.essentials && features.essentials.length > 0 && (
            <PlanFeatureSection
              title="Lo que incluye"
              items={features.essentials}
              variant={variant}
            />
          )}

          {/* Diferenciadores — el AHA del upgrade vs el plan anterior */}
          {features.diff && (
            <PlanFeatureSection
              title={features.diff.title}
              items={features.diff.items.map(t => ({ label: t }))}
              variant={variant}
              accent
            />
          )}

          {/* Roadmap — features prometidas, visualmente DISTINTAS */}
          {features.roadmap && features.roadmap.length > 0 && (
            <PlanRoadmapSection items={features.roadmap} />
          )}
        </div>
      )}
    </div>
  )
}


// ─── Sub-componentes del PlanCard (nuevo template 3-secciones) ──────────────

function variantAccent(variant) {
  if (variant === 'pro')  return 'data-violet'
  if (variant === 'plus') return 'data-cyan'
  return 'rendi-pos'  // free → verde
}

/**
 * Grid mini de cuotas — 3 celdas con número grande + label pequeño.
 * Sirve para escaneo rápido del "qué tan grande es esto" de un plan.
 * Sin emojis (regla de producto), solo número + texto.
 */
function PlanQuotaGrid({ quotas, variant }) {
  const accent = variantAccent(variant)
  return (
    <div>
      <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">Cuotas semanales</div>
      <div className="grid grid-cols-3 gap-2">
        {quotas.map((q, i) => (
          <div key={i} className="border border-line/60 rounded bg-bg-2/30 px-2 py-2 text-center">
            <div className={`text-xl font-bold tabular leading-none mb-1 text-${accent}`}>
              {q.value}
            </div>
            <div className="text-[9px] font-mono uppercase tracking-caps text-ink-3 leading-tight">
              {q.label}
            </div>
            {q.note && (
              <div className="text-[9px] text-ink-3 mt-1 leading-tight italic">{q.note}</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * Sección de features con título mono uppercase + lista de items con check.
 * `accent=true` cambia el color del título al accent del plan (diff/AHA section).
 */
function PlanFeatureSection({ title, items, variant, accent = false }) {
  const accentColor = variantAccent(variant)
  return (
    <div>
      <div className={`text-[10px] font-mono uppercase tracking-caps mb-2 ${accent ? `text-${accentColor}` : 'text-ink-3'}`}>
        {title}
      </div>
      <ul className="space-y-2">
        {items.map((f, i) => {
          const isObj = typeof f === 'object'
          const label = isObj ? f.label : f
          const sub = isObj ? f.sub : null
          return (
            <li key={i} className="flex items-start gap-2 text-sm">
              <Check size={12} strokeWidth={2.5} className={`mt-0.5 flex-shrink-0 text-${accentColor}`} />
              <div className="leading-snug">
                <div className="text-ink-1">{label}</div>
                {sub && <div className="text-[11px] text-ink-3 mt-0.5">{sub}</div>}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/**
 * Sección "Roadmap" — features prometidas en construcción.
 * Visualmente distinta: clock en vez de check, color ámbar, mensaje "En construcción".
 * Decisión de producto: mantener visible para señalizar dirección, pero
 * SIN mezclar con las features activas (evita bait).
 */
function PlanRoadmapSection({ items }) {
  return (
    <div className="border-t border-line/40 pt-4 mt-2">
      <div className="text-[10px] font-mono uppercase tracking-caps text-data-amber mb-2 flex items-center gap-1.5">
        <Clock size={10} strokeWidth={2} />
        En construcción
      </div>
      <ul className="space-y-1.5">
        {items.map((label, i) => (
          <li key={i} className="text-[12px] text-ink-3 leading-snug pl-4 border-l border-data-amber/30">
            {label}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Legacy: renderiza features cuando vienen como array (back-compat).
 * Mantenido por si algún caller externo todavía pasa shape viejo. La nueva
 * estructura {essentials, diff, quotas} se renderiza desde PlanCard directo.
 */
function PlanFeatureListLegacy({ items, variant }) {
  const accent = variantAccent(variant)
  return (
    <ul className="space-y-2.5 flex-1">
      {items.map((f, i) => {
        const isObj = typeof f === 'object'
        const label = isObj ? f.label : f
        const sub = isObj ? f.sub : null
        const comingSoon = isObj ? f.comingSoon : false
        return (
          <li key={i} className="flex items-start gap-2 text-sm">
            {comingSoon
              ? <Lock size={12} strokeWidth={2} className="text-data-amber mt-0.5 flex-shrink-0" />
              : <Check size={12} strokeWidth={2.5} className={`mt-0.5 flex-shrink-0 text-${accent}`} />
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
  )
}
