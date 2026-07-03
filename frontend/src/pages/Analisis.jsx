// Analisis — página consolidada que reemplaza /insights + /comportamiento +
// /reportes en el sidebar (3 items del nav viejo → 1 item nuevo).
// ═══════════════════════════════════════════════════════════════════════════
// Restructure 2026-05-27. Cada tab renderiza el componente original sin
// tocarlo — eso preserva ~3500 líneas de código probado y permite revertir
// fácil si la decisión de fusionar no funciona en producción.
//
// Tabs:
//   • Diagnóstico    → contenido de /insights (cards de diagnóstico arriba,
//                      benchmarks, comparativa) — la narrativa "qué te dice
//                      el sistema sobre tu performance"
//   • Métricas Pro   → /insights pero scrolleado a la sección de métricas
//                      Pro (Sharpe, Sortino, Alpha, IR, Vol, Beta)
//   • Comportamiento → contenido completo de /comportamiento (12 sesgos)
//   • Reportes       → contenido completo de /reportes (timeline mensual)
//
// Nota técnica: Insights.jsx tiene TANTO el diagnóstico arriba como las
// métricas Pro adentro. Para separarlos en 2 tabs distintos sin tocar
// Insights.jsx, usamos un hash en la URL (`#metrics`) y scroll auto. Eso
// permite mostrar el mismo componente pero scrolleado a la sección
// relevante. Phase 2 (si vale la pena) sería partir Insights en 2 sub-pages.

import { lazy, Suspense, useEffect, useState } from 'react'
import { useSearchParams, useNavigate, useLocation } from 'react-router-dom'
import { Compass, TrendingUp, Brain, BarChart3, UserRound } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import CurrencyRail from '../components/CurrencyRail'
import { track } from '../utils/track'

const Insights = lazy(() => import('./Insights'))
const Behavioral = lazy(() => import('./Behavioral'))
const Reports = lazy(() => import('./Reports'))
const PerfilInversor = lazy(() => import('./PerfilInversor'))

const TABS = [
  { id: 'diagnostico',    label: 'Diagnóstico',         icon: Compass,    desc: 'Lo que te dice el sistema sobre tu performance' },
  { id: 'metricas',       label: 'Métricas Pro',        icon: TrendingUp, desc: 'Sharpe, Sortino, Alpha, IR, Volatilidad, Beta' },
  { id: 'perfil',         label: 'Perfil del inversor', icon: UserRound,  desc: 'Test + cruce con tu cartera real' },
  { id: 'comportamiento', label: 'Comportamiento',      icon: Brain,      desc: 'Sesgos detectados sobre tu historial' },
  { id: 'reportes',       label: 'Reportes',            icon: BarChart3,  desc: 'Performance mensual y timeline' },
]

const VALID_TAB_IDS = new Set(TABS.map(t => t.id))
const DEFAULT_TAB = 'diagnostico'

export default function Analisis() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const location = useLocation()

  // Tab desde URL (?tab=metricas). Default = diagnostico. Inválidos caen al default.
  const urlTab = searchParams.get('tab')
  const initialTab = urlTab && VALID_TAB_IDS.has(urlTab) ? urlTab : DEFAULT_TAB
  const [tab, setTab] = useState(initialTab)

  // Sync URL ↔ state. Cuando el user navega entre tabs, actualizamos el query
  // param para que sea compartible y para que back/forward del browser funcione.
  useEffect(() => {
    const current = searchParams.get('tab') || DEFAULT_TAB
    if (current !== tab) {
      const next = new URLSearchParams(searchParams)
      if (tab === DEFAULT_TAB) next.delete('tab')
      else next.set('tab', tab)
      setSearchParams(next, { replace: true })
    }
    track('analisis_tab_viewed', { tab })
  }, [tab])  // eslint-disable-line react-hooks/exhaustive-deps

  // Si el query param cambia desde afuera (ej. un link interno con ?tab=...),
  // syncroneamos el state local.
  useEffect(() => {
    const fromUrl = searchParams.get('tab')
    if (fromUrl && VALID_TAB_IDS.has(fromUrl) && fromUrl !== tab) {
      setTab(fromUrl)
    } else if (!fromUrl && tab !== DEFAULT_TAB) {
      setTab(DEFAULT_TAB)
    }
  }, [location.search])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Tu análisis"
        title="Análisis"
        subtitle="Diagnóstico, métricas, sesgos y reportes de tu cartera — todo en un lugar."
      />

      {/* Tab strip — filled pills con violet en la activa. Mismo diseño que
          Cartera.jsx para consistencia visual entre las 2 páginas con tabs
          principales del producto. A la derecha, el toggle de divisa (mismo
          que Cartera) para que el user pueda cambiar USD/ARS desde acá también. */}
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <div className="inline-flex flex-wrap gap-2">
          {TABS.map(t => {
            const Icon = t.icon
            const active = tab === t.id
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`inline-flex items-center gap-2 px-4 py-2.5 text-sm font-semibold rounded-md border transition-all ${
                  active
                    ? 'bg-data-violet/15 text-data-violet border-data-violet/40 shadow-sm'
                    : 'bg-bg-1 text-ink-2 border-line hover:text-ink-0 hover:border-line-2 hover:bg-bg-2'
                }`}
                aria-pressed={active}
              >
                <Icon size={15} strokeWidth={1.75} aria-hidden="true" />
                {t.label}
              </button>
            )
          })}
        </div>
      </div>
      {/* Riel de moneda — mismo control global que Cartera (USD MEP / USD CCL / Pesos). */}
      <div className="mb-5 max-w-2xl mx-auto">
        <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1.5 select-none text-center">Ver en</div>
        <CurrencyRail />
      </div>

      {/* Tab content — lazy boundary por tab (cada uno es un chunk separado) */}
      <Suspense fallback={<div className="text-center py-20 text-ink-3 text-sm">Cargando…</div>}>
        {tab === 'diagnostico' && <Insights _embeddedTab="diagnostico" />}
        {tab === 'metricas' && <Insights _embeddedTab="metricas" />}
        {tab === 'perfil' && (
          <>
            {/* Test arriba (input) + cards de cruce abajo (output del input).
                ProfileInvestorBlock dentro de Insights muestra empty state
                amistoso si el test no está completo, así que no necesitamos
                lógica condicional acá — siempre mostramos ambos bloques. */}
            <div className="border-b border-line/40 pb-6 mb-6">
              <h2 className="text-lg font-semibold text-ink-0 mb-1">Tu test de inversor</h2>
              <p className="text-sm text-ink-3 mb-4">7 preguntas que alimentan el Coach IA + las cards de cruce de abajo.</p>
              <PerfilInversor _embeddedInAnalisis />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-ink-0 mb-1">Tu cartera vs. tu perfil declarado</h2>
              <p className="text-sm text-ink-3 mb-4">Cómo se alinea lo que hacés con lo que dijiste en el test.</p>
              <Insights _embeddedTab="perfil" />
            </div>
          </>
        )}
        {tab === 'comportamiento' && <Behavioral />}
        {tab === 'reportes' && <Reports />}
      </Suspense>
    </div>
  )
}
