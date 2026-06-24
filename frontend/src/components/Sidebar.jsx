// Sidebar — navegación lateral colapsable (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Patrón Linear/Stripe: dos estados (220px expandida / 56px colapsada a iconos),
// toggle con hamburguesa, preferencia persistida en localStorage.
//
// Estructura:
// • Ancho dinámico via CSS variable --sidebar-w (consumida por main en App.jsx)
// • Items agrupados en 3 secciones lógicas (Análisis / Data / Personal)
// • Activo: text-ink-0 + barra vertical 2px signal verde
// • Tooltips nativos (title attr) cuando está colapsada
// • Footer: Configuración + user info + theme toggle + logout
//
// Mobile: no responsive en V2. Vendrá design mobile-only aparte.

import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  Home as HomeIcon, LineChart, Briefcase, List, Settings, LogOut,
  Sun, Moon, Compass, Shield, Bell, Upload, Menu, Sparkles,
  MessageCircle, BookOpen, Gauge,
} from 'lucide-react'
// NOTA: Sparkles se mantiene importado porque lo usa el botón del Coach IA.
// Restructure 2026-05-27: sidebar de 11 → 6 items para reducir ruido visual.
// - Dashboard salió del nav (fusionado en Cartera /posiciones).
// - Comportamiento + Reportes salieron (fusionados en Análisis /analisis con tabs).
// - Insights renombrado a "Análisis" (más claro qué es).
// - "Importar CSV" se mantiene como item separado para descubrimiento (decisión
//   del user — la carga de CSV es un job crítico que tiene que estar visible).
//   Renombrado de "Importes" → "Importar CSV" 2026-06-01 (Importes confundía,
//   parecía referirse a "importes" $ — Importar es claramente la acción y CSV
//   precisa el formato).
// - Wrapped quedó fuera desde antes (futuro trigger anual de diciembre).
// - Perfil de inversor pasó a ser una TAB de Análisis (el test es input y las
//   cards de cruce son output — viven juntos). Grupo "Personal" del sidebar
//   eliminado entero.
import RendiLogo from './RendiLogo'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import { prefetchRoute } from '../utils/routePrefetch'
import RecommendationsModal from './RecommendationsModal'

const SIDEBAR_W_EXPANDED = '220px'
const SIDEBAR_W_COLLAPSED = '56px'
const LS_KEY = 'rendi_sidebar_collapsed'

// Sidebar restructurado — 6 items en 2 grupos lógicos.
// • Tu portfolio: lo que pasa con tu plata (estática + flujos)
// • Análisis: contexto y entendimiento (fusiona Insights/Comportamiento/
//             Reportes/Perfil del inversor)
//
// Objetivos se integra como tab dentro de Cartera. Perfil de inversor se
// integra como tab dentro de Análisis. Nada de "Personal" como grupo aparte.
const GROUPS = [
  {
    label: 'Tu cartera',
    items: [
      { to: '/',            label: 'Mercado',       icon: LineChart },
      { to: '/posiciones',  label: 'Cartera',       icon: Briefcase },
      { to: '/operaciones', label: 'Movimientos',   icon: List },
      { to: '/imports',     label: 'Importar CSV',  icon: Upload },
    ],
  },
  {
    label: 'Investigación',
    items: [
      { to: '/analisis',    label: 'Análisis',      icon: Compass },
      { to: '/fundamentals', label: 'Fundamentals', icon: Gauge },
      { to: '/novedades',   label: 'Novedades',     icon: Bell },
    ],
  },
]

export default function Sidebar() {
  const { user, logout } = useAuth()
  const { dark, toggle } = useTheme()
  const coachDrawer = useCoachDrawer()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(LS_KEY) === 'true')
  // Modal de recomendaciones. Trigger desde el footer del sidebar.
  const [recomOpen, setRecomOpen] = useState(false)

  // Persistir + setear CSS var consumida por <main> (margin dinámico)
  useEffect(() => {
    localStorage.setItem(LS_KEY, String(collapsed))
    document.documentElement.style.setProperty(
      '--sidebar-w',
      collapsed ? SIDEBAR_W_COLLAPSED : SIDEBAR_W_EXPANDED,
    )
  }, [collapsed])

  const allGroups = [
    ...GROUPS,
    ...(user?.is_admin
      ? [{ label: 'Admin', items: [{ to: '/admin', label: 'Admin', icon: Shield }] }]
      : []),
  ]

  return (
    <>
    <aside
      className="fixed top-0 left-0 bottom-0 bg-bg-0 border-r border-line flex flex-col z-40 transition-[width] duration-200 ease-out"
      style={{ width: collapsed ? SIDEBAR_W_COLLAPSED : SIDEBAR_W_EXPANDED }}
    >
      {/* Top: logo + toggle hamburguesa */}
      <div className="flex items-center h-14 border-b border-line flex-shrink-0 px-2">
        <NavLink
          to="/"
          className="flex items-center gap-2.5 flex-1 px-2 overflow-hidden"
          title={collapsed ? 'Rendi' : undefined}
        >
          <RendiLogo size={40} />
          {!collapsed && (
            <span className="font-semibold text-xl tracking-tight text-ink-0">rendi</span>
          )}
        </NavLink>
        <button
          onClick={() => setCollapsed(c => !c)}
          className="p-1.5 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-2 transition-colors"
          title={collapsed ? 'Expandir menú' : 'Colapsar menú'}
          aria-label={collapsed ? 'Expandir menú' : 'Colapsar menú'}
        >
          <Menu size={14} strokeWidth={1.75} aria-hidden="true" />
        </button>
      </div>

      {/* Navegación */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden py-3 px-2">
        {/* Coach IA — botón especial que abre drawer (no navega).
            Va arriba de todo con su propio bloque visualmente diferenciado
            (acento violet) para que se note como feature distintivo. */}
        <div className="mb-3">
          {!collapsed && (
            <p className="px-2.5 mb-1 font-mono text-[11px] uppercase tracking-label text-ink-2 font-medium">
              Asistente
            </p>
          )}
          <button
            type="button"
            onClick={() => coachDrawer.open()}
            title={collapsed ? 'Coach IA' : undefined}
            className={`relative w-full flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors text-data-violet hover:bg-data-violet/10`}
          >
            <Sparkles size={14} strokeWidth={1.75} aria-hidden="true" />
            {!collapsed && <span>Coach IA</span>}
          </button>
        </div>

        {allGroups.map((group, gi) => (
          <div key={group.label} className={gi > 0 ? 'mt-4' : ''}>
            {!collapsed && (
              <p className="px-2.5 mb-1 font-mono text-[11px] uppercase tracking-label text-ink-2 font-medium">
                {group.label}
              </p>
            )}
            {collapsed && gi > 0 && (
              <div className="border-t border-line/40 my-2 mx-1" aria-hidden="true" />
            )}
            <div className="space-y-0.5">
              {group.items.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  title={collapsed ? label : undefined}
                  onMouseEnter={() => prefetchRoute(to)}
                  onFocus={() => prefetchRoute(to)}
                  className={({ isActive }) =>
                    `relative flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors ${
                      isActive
                        ? 'text-ink-0 bg-bg-2'
                        : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon size={14} strokeWidth={1.75} aria-hidden="true" />
                      {!collapsed && <span>{label}</span>}
                      {isActive && !collapsed && (
                        <span
                          aria-hidden
                          className="absolute left-0 top-1 bottom-1 w-0.5 bg-data-violet rounded-full"
                        />
                      )}
                      {isActive && collapsed && (
                        <span
                          aria-hidden
                          className="absolute left-0 top-1 bottom-1 w-0.5 bg-data-violet rounded-full"
                        />
                      )}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer: guía + configuración + recomendaciones + user + toggle + logout */}
      <div className="border-t border-line px-2 py-2 flex-shrink-0">
        {/* Guía — manual completo de uso. Linkeada acá para que esté siempre
            accesible sin ocupar lugar en el nav principal (es referencia, no
            navegación frecuente). */}
        <NavLink
          to="/guia"
          title={collapsed ? 'Guía' : undefined}
          onMouseEnter={() => prefetchRoute('/guia')}
          onFocus={() => prefetchRoute('/guia')}
          className={({ isActive }) =>
            `flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors ${
              isActive
                ? 'text-ink-0 bg-bg-2'
                : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
            }`
          }
        >
          <BookOpen size={14} strokeWidth={1.75} aria-hidden="true" />
          {!collapsed && <span>Guía</span>}
        </NavLink>

        <NavLink
          to="/config"
          title={collapsed ? 'Configuración' : undefined}
          onMouseEnter={() => prefetchRoute('/config')}
          onFocus={() => prefetchRoute('/config')}
          className={({ isActive }) =>
            `flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors ${
              isActive
                ? 'text-ink-0 bg-bg-2'
                : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
            }`
          }
        >
          <Settings size={14} strokeWidth={1.75} aria-hidden="true" />
          {!collapsed && <span>Configuración</span>}
        </NavLink>

        {/* Recomendaciones — abre modal in-app. Tono violet sutil para que se
            distinga de "Configuración" sin ser invasivo. */}
        <button
          type="button"
          onClick={() => setRecomOpen(true)}
          title={collapsed ? 'Recomendaciones' : 'Mandanos una recomendación'}
          className={`w-full flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors text-ink-2 hover:text-data-violet hover:bg-data-violet/[0.06]`}
        >
          <MessageCircle size={14} strokeWidth={1.75} aria-hidden="true" />
          {!collapsed && <span>Recomendaciones</span>}
        </button>

        {/* User row: nombre + badge de plan (solo expandida) */}
        {user && !collapsed && (
          <div className="px-1 mt-1 mb-1 flex items-center gap-1.5 min-w-0">
            <span className="flex-1 text-[11px] text-ink-3 truncate font-mono" title={user.name}>
              {user.name}
            </span>
            <PlanBadge tier={user.tier} />
          </div>
        )}

        {/* Action buttons: theme + logout (siempre visibles) */}
        <div className={`flex items-center gap-1 ${collapsed ? 'flex-col mt-1' : 'px-1'}`}>
          {/* En modo colapsado, solo el badge mini centrado arriba */}
          {user && collapsed && (
            <div title={`Plan ${user.tier || 'free'}`} className="mb-1">
              <PlanBadge tier={user.tier} compact />
            </div>
          )}
          <button
            onClick={toggle}
            className="p-1.5 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-1 transition-colors"
            title={dark ? 'Modo claro' : 'Modo oscuro'}
            aria-label={dark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
          >
            {dark
              ? <Sun size={13} strokeWidth={1.75} aria-hidden="true" />
              : <Moon size={13} strokeWidth={1.75} aria-hidden="true" />}
          </button>
          <button
            onClick={logout}
            className="p-1.5 rounded-sm text-ink-3 hover:text-rendi-neg hover:bg-bg-1 transition-colors"
            title="Cerrar sesión"
            aria-label="Cerrar sesión"
          >
            <LogOut size={13} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </div>
    </aside>

    {/* Modal recomendaciones — fuera del aside porque usa fixed inset-0 */}
    <RecommendationsModal open={recomOpen} onClose={() => setRecomOpen(false)} />
    </>
  )
}

// ─── PlanBadge ───────────────────────────────────────────────────────────────
// Mini badge tier-aware. Compact=true muestra solo un dot pequeño (modo
// colapsado de la sidebar). Default muestra label corto + color.
function PlanBadge({ tier, compact = false }) {
  const t = tier || 'free'
  const styles = {
    free:  { label: 'FREE',  bg: 'bg-bg-2',                 text: 'text-ink-2',         dot: 'bg-ink-3' },
    plus:  { label: 'PLUS',  bg: 'bg-data-cyan/15',         text: 'text-data-cyan',     dot: 'bg-data-cyan' },
    pro:   { label: 'PRO',   bg: 'bg-data-violet/15',       text: 'text-data-violet',   dot: 'bg-data-violet' },
    admin: { label: 'ADMIN', bg: 'bg-rendi-pos/15',         text: 'text-rendi-pos',     dot: 'bg-rendi-pos' },
  }
  const s = styles[t] || styles.free
  if (compact) {
    return (
      <span className={`inline-block w-1.5 h-1.5 rounded-full ${s.dot}`} aria-label={`Plan ${s.label}`} />
    )
  }
  return (
    <span
      className={`shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-sm font-mono text-[9px] font-medium tracking-caps ${s.bg} ${s.text}`}
      aria-label={`Plan actual: ${s.label}`}
    >
      {s.label}
    </span>
  )
}
