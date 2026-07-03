// Cartera — página consolidada que reemplaza /posiciones + /dashboard +
// /objetivos en el sidebar (3 items del nav viejo → 1 item nuevo).
// ═══════════════════════════════════════════════════════════════════════════
// Restructure 2026-05-27. Cada tab renderiza el componente original sin
// tocarlo — preserva código probado, permite revertir si la decisión de
// fusionar no funciona en producción.
//
// Tabs (3):
//   • Posiciones (default) → contenido completo de /posiciones (lista,
//                            chart, modales de venta/compra)
//   • Evolución            → contenido completo de /dashboard (equity curve,
//                            TWRR, net deposited, composición, heatmap).
//                            Dashboard ya está diseñado como vista unificada;
//                            partir en sub-secciones requeriría refactorearlo
//                            (~2000 líneas) sin agregar valor real al user.
//   • Objetivos            → contenido de /objetivos
//
// Iteración del restructure: arrancamos con 4 tabs (Posiciones / Evolución /
// Composición / Objetivos). En testing detectamos que Evolución y Composición
// mostraban el mismo Dashboard (porque el prop `_focus` no estaba implementado
// adentro). Decisión de producto: unificar en "Evolución" en lugar de invertir
// en partir Dashboard. Menos tabs = menos density, que es el principio core
// de este refactor.

import { lazy, Suspense, useEffect, useState } from 'react'
import { useSearchParams, useLocation } from 'react-router-dom'
import { Briefcase, TrendingUp, Target } from 'lucide-react'
import { track } from '../utils/track'
import Skeleton from '../components/Skeleton'
import CurrencyRail from '../components/CurrencyRail'
import { markPositionsDiscovered } from '../utils/positionsDiscovered'

const Positions = lazy(() => import('./Positions'))
const Dashboard = lazy(() => import('./Dashboard'))
const Goals = lazy(() => import('./Goals'))

const TABS = [
  { id: 'posiciones',  label: 'Posiciones',   icon: Briefcase,  desc: 'Tus tenencias actuales' },
  // ID se mantiene 'evolucion' para no romper bookmarks ni el alias
  // legacy de ?tab=composicion (TAB_ALIASES abajo).
  { id: 'evolucion',   label: 'Dashboard',    icon: TrendingUp, desc: 'Equity curve, composición y heatmap' },
  { id: 'objetivos',   label: 'Objetivos',    icon: Target,     desc: 'Tus metas financieras y proyección' },
]

const VALID_TAB_IDS = new Set(TABS.map(t => t.id))
const DEFAULT_TAB = 'posiciones'

// Aliases legacy: bookmarks / links externos / códigos viejos pueden tener
// `?tab=composicion` (cuando hacíamos 4 tabs). Lo mapeamos a Evolución que
// es donde quedó la composición unificada.
const TAB_ALIASES = {
  composicion: 'evolucion',
}

export default function Cartera() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()

  const urlTab = searchParams.get('tab')
  const resolvedTab = TAB_ALIASES[urlTab] || urlTab
  const initialTab = resolvedTab && VALID_TAB_IDS.has(resolvedTab) ? resolvedTab : DEFAULT_TAB
  const [tab, setTab] = useState(initialTab)

  useEffect(() => {
    const current = searchParams.get('tab') || DEFAULT_TAB
    if (current !== tab) {
      const next = new URLSearchParams(searchParams)
      if (tab === DEFAULT_TAB) next.delete('tab')
      else next.set('tab', tab)
      setSearchParams(next, { replace: true })
    }
    track('cartera_tab_viewed', { tab })
  }, [tab])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const fromUrl = searchParams.get('tab')
    const resolved = TAB_ALIASES[fromUrl] || fromUrl
    if (resolved && VALID_TAB_IDS.has(resolved) && resolved !== tab) {
      setTab(resolved)
    } else if (!fromUrl && tab !== DEFAULT_TAB) {
      setTab(DEFAULT_TAB)
    }
  }, [location.search])  // eslint-disable-line react-hooks/exhaustive-deps

  // Onboarding Paso 2 (descubrimiento): apenas se ve la tab de Posiciones —donde
  // aparece seleccionar/crear broker y el alta de posiciones— marcamos el paso
  // como descubierto. No requiere cargar una posición real. (El import no pasa
  // por acá, así que no tilda este paso solo.)
  useEffect(() => {
    if (tab === 'posiciones') markPositionsDiscovered()
  }, [tab])

  return (
    // Posiciones = tabla densa → usa el shell extra-ancho (menos negro al costado,
    // sin scroll horizontal). Evolución/Objetivos quedan en el ancho normal.
    <div className={tab === 'posiciones' ? 'page-shell-xwide' : 'page-shell-wide'}>
      {/* Tab strip — filled pills con violet en la activa. Diseño deliberadamente
          prominente: en testing el user no descubría las tabs (tab strip chico
          + dentro de Posiciones con botones de acción competía por atención).
          Solución: pills más grandes (text-sm font-semibold, padding amplio) +
          violet/15 + borde violet/40 en la activa para que sea inconfundible.
          A la derecha de la fila va el toggle de divisa (USD/ARS): vive a nivel
          Cartera para que esté disponible en las 3 tabs (Posiciones / Evolución
          / Objetivos) y no solo en una. Es global —cambiarlo acá lo cambia en
          toda la app— pero la opción tiene que estar donde el user está. */}
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
      {/* Riel de moneda de valuación — barra ancha (USD MEP / USD CCL / Pesos).
          Global: cambiarlo acá lo cambia en toda la app. Vive a nivel Cartera
          para estar disponible en las 3 tabs (Posiciones / Evolución / Objetivos). */}
      <div className="mb-5 max-w-2xl mx-auto">
        <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-1.5 select-none text-center">Ver en</div>
        <CurrencyRail />
      </div>

      <Suspense fallback={
        <div className="space-y-4 py-6" aria-busy="true">
          <Skeleton className="h-12 w-56" />
          <Skeleton className="h-4 w-full max-w-md" />
          <Skeleton className="h-64 w-full rounded" />
        </div>
      }>
        {tab === 'posiciones' && <Positions />}
        {tab === 'evolucion'  && <Dashboard />}
        {tab === 'objetivos'  && <Goals />}
      </Suspense>
    </div>
  )
}
