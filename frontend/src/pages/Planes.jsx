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
import { useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import PageHeader from '../components/PageHeader'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { track } from '../utils/track'
import { api } from '../utils/api'

// Precio Pro en USD/mes — placeholder que vamos a iterar.
// Cambiar acá afecta toda la app (Config PlanHero, UpgradeModal, etc.).
export const PRO_PRICE_USD = '6.99'

// Precios ARS (mantener sync con backend/billing/pricing.py)
const ARS_MONTHLY = '12.100'      // base 10.000 + IVA 21%
const ARS_ANNUAL  = '123.420'     // base 102.000 + IVA 21% (15% descuento)
const ARS_ANNUAL_MONTHLY_EQ = '10.285'  // total anual / 12

// ─── Listas de features por plan ─────────────────────────────────────────────

const FREE_FEATURES = [
  'Dashboard completo (4 KPIs + curva de evolución)',
  '6 análisis IA por semana',
  'Hasta 1 broker',
  'Insights básicos (TWR + benchmark + drawdown)',
  'Diagnóstico con 3 observaciones',
  '1 análisis de comportamiento',
  'Posiciones, Operaciones, Wrapped, Objetivos',
  'Reportes: vista previa del último mes',
]

const PRO_FEATURES = [
  { label: '60 análisis IA por semana', sub: '10× más que Free' },
  { label: 'Respuestas con causalidad y comparaciones', sub: 'No solo descripción' },
  { label: 'Follow-ups: profundizá cada análisis con preguntas libres' },
  { label: 'Brokers ilimitados' },
  { label: 'Comportamiento completo (todas las tags)' },
  { label: 'Insights diagnóstico completo' },
  { label: 'Distribución por activo' },
  { label: 'Reportes históricos completos (todos los meses)' },
  { label: 'Export CSV consolidado para tu contador', sub: 'Todos los movimientos (compras, ventas, depósitos, retiros, dividendos) en un solo archivo' },
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
  const isPro = tier === 'pro'
  const isAdmin = tier === 'admin'
  // Para "tu plan actual": admin se trata como pro a efectos del marcador
  // (visualmente está en el lado Pro de la comparativa).
  const hasProTier = isPro || isAdmin

  useEffect(() => {
    track('planes_viewed', { from_tier: tier })
  }, [tier])

  async function onSubscribeClick() {
    if (subscribing) return
    track('upgrade_subscribe_clicked', {
      from_tier: tier,
      source: 'planes_page',
      period: billingPeriod,
    })
    setSubscribing(true)
    try {
      const res = await api.post('/billing/subscribe', { period: billingPeriod })
      if (res.init_point) {
        // Redirigir al checkout de MP (el user paga ahí, después MP lo devuelve
        // a /billing/success o /billing/failure)
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
          {/* Toggle mensual / anual — visible solo si el user no es Pro */}
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

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-5xl mx-auto">
            {/* ── Free card ─── */}
            <PlanCard
              name="Free"
              tagline="Lo esencial para trackear tu portfolio"
              price="Gratis"
              priceSub="Para siempre"
              features={FREE_FEATURES.map(label => ({ label }))}
              isCurrent={isFree}
              ctaLabel={isFree ? 'Tu plan actual' : 'Disponible al downgradear'}
              ctaDisabled
            />

            {/* ── Pro card (highlighted) ─── */}
            <PlanCard
              name="Pro"
              tagline="Análisis profundos + features avanzadas"
              price={billingPeriod === 'annual' ? `ARS ${ARS_ANNUAL_MONTHLY_EQ}` : `ARS ${ARS_MONTHLY}`}
              priceSub={billingPeriod === 'annual'
                ? `por mes · facturado anual (ARS ${ARS_ANNUAL})`
                : 'por mes · IVA 21% incluido'}
              priceFootnote={billingPeriod === 'annual'
                ? `Ahorrás ARS 21.780 al año vs mensual`
                : `Equivalente a USD ${PRO_PRICE_USD} al blue · IVA 21% incluido`}
              features={PRO_FEATURES}
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
              highlight
              onCtaClick={onSubscribeClick}
            />
          </div>
        </>
      )}

      <div className="text-center mt-8">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="text-xs text-ink-3 hover:text-ink-0 transition-colors inline-flex items-center gap-1"
        >
          Volver atrás
        </button>
      </div>

      <p className="text-[11px] text-ink-3 text-center max-w-2xl mx-auto mt-4 leading-relaxed">
        Los precios se muestran en USD. Suscribite cuando te conviene y cancelá cuando quieras.
        Pro está actualmente en desarrollo — cuando esté disponible te avisamos por email.
      </p>
    </div>
  )
}

// ─── Card individual ────────────────────────────────────────────────────────

function PlanCard({
  name, tagline, price, priceSub, priceFootnote, features,
  isCurrent, ctaLabel, ctaDisabled, ctaLoading, highlight, onCtaClick,
}) {
  return (
    <div
      className={`
        relative rounded-lg border p-6 sm:p-7 flex flex-col
        ${highlight
          ? 'border-data-violet/40 bg-data-violet/[0.04] shadow-lg shadow-data-violet/5'
          : 'border-line/80 bg-bg-1'
        }
      `}
    >
      {isCurrent && (
        <span className="absolute top-3 right-3 inline-flex items-center gap-1 px-2 py-0.5 rounded-sm bg-rendi-pos/15 text-rendi-pos text-[10px] font-mono uppercase tracking-caps">
          <span className="w-1.5 h-1.5 rounded-full bg-rendi-pos" /> Tu plan
        </span>
      )}

      {/* Heading */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-1">
          {highlight && <Sparkles size={16} strokeWidth={1.75} className="text-data-violet" />}
          <h2 className={`text-2xl font-bold ${highlight ? 'text-data-violet' : 'text-ink-0'}`}>
            {name}
          </h2>
        </div>
        <p className="text-sm text-ink-2">{tagline}</p>
      </div>

      {/* Price */}
      <div className="mb-5">
        <div className="flex items-baseline gap-1.5">
          <span className="text-3xl font-bold text-ink-0 tabular">{price}</span>
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
        className={`
          w-full inline-flex items-center justify-center gap-1.5
          text-sm font-medium rounded-sm py-2.5 mb-5 transition-colors
          ${ctaDisabled
            ? 'bg-bg-2/60 text-ink-3 cursor-default border border-line/40'
            : highlight
              ? 'bg-data-violet text-white hover:bg-data-violet/90 border border-data-violet'
              : 'bg-bg-2 hover:bg-bg-2/80 text-ink-1 border border-line/60'
          }
        `}
      >
        {ctaLoading
          ? <Loader2 size={13} strokeWidth={1.75} className="animate-spin" />
          : (!ctaDisabled && highlight && <Sparkles size={13} strokeWidth={1.75} />)
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
                : <Check size={12} strokeWidth={2.5} className={`mt-0.5 flex-shrink-0 ${highlight ? 'text-data-violet' : 'text-rendi-pos'}`} />
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
