// Sidebar — navegación lateral colapsable (V3).
// ═══════════════════════════════════════════════════════════════════════════
// Reestructura 2026-07: de links planos a 3 secciones ACORDEÓN que se despliegan
// al tocarlas (menos ruido, más aire). Afuera del acordeón, siempre visibles:
// Alertas e Importar (acciones a mano, no escondidas). Rendi AI arriba; utilidades
// (Guía / Config / Recomendaciones) + cuenta abajo.
//
// Dos estados de ancho (igual que antes):
// • Expandida (220px): acordeón con labels.
// • Colapsada (56px): íconos planos de cada destino (el acordeón no aplica).
//   Preferencia persistida en localStorage.
//
// La sección de la ruta activa se abre sola. Acordeón de a uno (abrir una cierra
// las demás). Mobile: design aparte.

import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  Briefcase, List, Wallet, LineChart, Activity, Newspaper, Compass, TrendingUp,
  Gauge, Bell, Upload, BookOpen, Settings, MessageCircle, Sparkles, Shield,
  Sun, Moon, LogOut, Menu, ChevronRight,
} from 'lucide-react'
import RendiLogo from './RendiLogo'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import { prefetchRoute } from '../utils/routePrefetch'
import RecommendationsModal from './RecommendationsModal'

const SIDEBAR_W_EXPANDED = '220px'
const SIDEBAR_W_COLLAPSED = '56px'
const LS_KEY = 'rendi_sidebar_collapsed'

// ── 3 secciones acordeón ──────────────────────────────────────────────────
// • Tu Cartera: lo que tenés y moviste (lo que navegás seguido).
// • Mercado:    qué pasa afuera (el pulso del día + las noticias).
// • Análisis:   entender e interpretar (performance + calidad de tenencias).
// NOTA: el ítem "Rendimiento" (/analisis) se llamaba "Análisis"; se renombró
// para no chocar con el nombre del grupo. Si preferís, volvé a "Análisis" o
// "Diagnóstico".
const GROUPS = [
  {
    id: 'cartera', label: 'Tu Cartera', icon: Wallet,
    items: [
      { to: '/posiciones',  label: 'Cartera',      icon: Briefcase },
      { to: '/operaciones', label: 'Movimientos',  icon: List },
    ],
  },
  {
    id: 'mercado', label: 'Mercado', icon: LineChart,
    items: [
      { to: '/',          label: 'Resumen',   icon: Activity },
      { to: '/novedades', label: 'Novedades', icon: Newspaper },
    ],
  },
  {
    id: 'analisis', label: 'Análisis', icon: Compass,
    items: [
      { to: '/analisis',     label: 'Rendimiento',        icon: TrendingUp },
      { to: '/fundamentals', label: 'Calidad de cartera', icon: Gauge },
    ],
  },
]

// Sueltos — siempre visibles, fuera del acordeón (acciones a mano).
const LOOSE = [
  { to: '/alertas', label: 'Alertas',  icon: Bell,    dot: true },
  { to: '/imports', label: 'Importar', icon: Upload },
]

const ALL_LEAVES = GROUPS.flatMap(g => g.items)

// ¿La ruta actual cae dentro de este `to`? '/' es exacto; el resto por prefijo.
function matchPath(pathname, to) {
  if (to === '/') return pathname === '/'
  return pathname === to || pathname.startsWith(to + '/')
}

export default function Sidebar() {
  const { user, logout } = useAuth()
  const { dark, toggle } = useTheme()
  const coachDrawer = useCoachDrawer()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(LS_KEY) === 'true')
  const [recomOpen, setRecomOpen] = useState(false)

  // Grupo de la ruta activa (para abrirlo solo).
  const activeGroupId = GROUPS.find(g => g.items.some(it => matchPath(location.pathname, it.to)))?.id
  const [openGroup, setOpenGroup] = useState(activeGroupId || 'cartera')

  // Al navegar a una ruta de otro grupo, abrir ese grupo.
  useEffect(() => {
    if (activeGroupId) setOpenGroup(activeGroupId)
  }, [activeGroupId])

  // Persistir + setear CSS var consumida por <main> (margin dinámico)
  useEffect(() => {
    localStorage.setItem(LS_KEY, String(collapsed))
    document.documentElement.style.setProperty(
      '--sidebar-w',
      collapsed ? SIDEBAR_W_COLLAPSED : SIDEBAR_W_EXPANDED,
    )
  }, [collapsed])

  // Clases compartidas de una fila-link con ícono (colapsada o utilidad).
  const rowCls = ({ isActive }) =>
    `relative flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors ${
      isActive ? 'text-ink-0 bg-bg-2' : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
    }`

  const ActiveBar = () => (
    <span aria-hidden className="absolute left-0 top-1 bottom-1 w-0.5 bg-data-violet rounded-full" />
  )

  return (
    <>
    <aside
      className="fixed top-0 left-0 bottom-0 bg-bg-0 border-r border-line flex flex-col z-40 transition-[width] duration-200 ease-out"
      style={{ width: collapsed ? SIDEBAR_W_COLLAPSED : SIDEBAR_W_EXPANDED }}
    >
      {/* Top: logo + toggle hamburguesa */}
      <div className="flex items-center h-14 border-b border-line flex-shrink-0 px-2">
        <NavLink to="/" className="flex items-center gap-2.5 flex-1 px-2 overflow-hidden" title={collapsed ? 'Rendi' : undefined}>
          <RendiLogo size={40} />
          {!collapsed && <span className="font-semibold text-xl tracking-tight text-ink-0">rendi</span>}
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
        {/* Rendi AI — botón especial que abre drawer (no navega). */}
        <div className="mb-3">
          {!collapsed && (
            <p className="px-2.5 mb-1 font-mono text-[11px] uppercase tracking-label text-ink-2 font-medium">Asistente</p>
          )}
          <button
            type="button"
            onClick={() => coachDrawer.open()}
            title={collapsed ? 'Rendi AI' : undefined}
            className={`relative w-full flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors text-data-violet hover:bg-data-violet/10`}
          >
            <Sparkles size={14} strokeWidth={1.75} aria-hidden="true" />
            {!collapsed && <span>Rendi AI</span>}
          </button>
        </div>

        {collapsed ? (
          /* ── Colapsada: íconos planos de cada destino (sin acordeón) ── */
          <div className="space-y-0.5">
            {ALL_LEAVES.map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} end={to === '/'} title={label}
                onMouseEnter={() => prefetchRoute(to)} onFocus={() => prefetchRoute(to)}
                className={rowCls}>
                {({ isActive }) => (<><Icon size={14} strokeWidth={1.75} aria-hidden="true" />{isActive && <ActiveBar />}</>)}
              </NavLink>
            ))}
          </div>
        ) : (
          /* ── Expandida: 3 secciones acordeón ── */
          <div className="space-y-1">
            {GROUPS.map((group) => {
              const isOpen = openGroup === group.id
              const GroupIcon = group.icon
              return (
                <div key={group.id}>
                  <button
                    type="button"
                    onClick={() => setOpenGroup(o => (o === group.id ? null : group.id))}
                    aria-expanded={isOpen}
                    className={`w-full flex items-center gap-2.5 pl-3 pr-2 py-2 rounded-sm text-sm font-semibold transition-colors ${
                      isOpen ? 'text-ink-0' : 'text-ink-1 hover:text-ink-0 hover:bg-bg-1'
                    }`}
                  >
                    <GroupIcon size={15} strokeWidth={1.75} aria-hidden="true"
                      className={isOpen ? 'text-data-violet' : 'text-ink-2'} />
                    <span className="flex-1 text-left">{group.label}</span>
                    <ChevronRight size={14} strokeWidth={2}
                      className={`text-ink-3 transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`} aria-hidden="true" />
                  </button>
                  <div className={`overflow-hidden transition-all duration-200 ease-out ${isOpen ? 'max-h-40 opacity-100' : 'max-h-0 opacity-0'}`}>
                    <div className="pt-0.5 pb-1 space-y-0.5">
                      {group.items.map(({ to, label, icon: Icon }) => (
                        <NavLink key={to} to={to} end={to === '/'} title={label}
                          onMouseEnter={() => prefetchRoute(to)} onFocus={() => prefetchRoute(to)}
                          className={({ isActive }) =>
                            `relative flex items-center gap-2.5 pl-9 pr-2 py-1.5 rounded-sm text-sm transition-colors ${
                              isActive ? 'text-ink-0 bg-bg-2 font-medium' : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
                            }`}>
                          {({ isActive }) => (<><Icon size={14} strokeWidth={1.75} aria-hidden="true" />{isActive && <ActiveBar />}<span>{label}</span></>)}
                        </NavLink>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </nav>

      {/* Footer: sueltos (Alertas / Importar) + utilidades + cuenta */}
      <div className="border-t border-line px-2 py-2 flex-shrink-0">
        {/* Sueltos — siempre visibles, tinta más fuerte que las utilidades */}
        {LOOSE.map(({ to, label, icon: Icon, dot }) => (
          <NavLink key={to} to={to} title={collapsed ? label : undefined}
            onMouseEnter={() => prefetchRoute(to)} onFocus={() => prefetchRoute(to)}
            className={({ isActive }) =>
              `relative flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors ${
                isActive ? 'text-ink-0 bg-bg-2' : 'text-ink-1 hover:text-ink-0 hover:bg-bg-1'
              }`}>
            {({ isActive }) => (
              <>
                <Icon size={14} strokeWidth={1.75} aria-hidden="true" />
                {!collapsed && <span className="flex-1">{label}</span>}
                {dot && (
                  <span aria-hidden
                    className={`w-1.5 h-1.5 rounded-full bg-data-violet ${collapsed ? 'absolute top-1.5 right-1.5' : ''}`}
                    style={collapsed ? undefined : { boxShadow: '0 0 0 3px rgba(139,125,255,0.12)' }} />
                )}
                {isActive && <ActiveBar />}
              </>
            )}
          </NavLink>
        ))}

        <div className="border-t border-line/40 my-1.5 mx-1" aria-hidden="true" />

        {user?.is_admin && (
          <NavLink to="/admin" title={collapsed ? 'Admin' : undefined} className={rowCls}>
            {({ isActive }) => (<><Shield size={14} strokeWidth={1.75} aria-hidden="true" />{!collapsed && <span>Admin</span>}{isActive && <ActiveBar />}</>)}
          </NavLink>
        )}

        <NavLink to="/guia" title={collapsed ? 'Guía' : undefined}
          onMouseEnter={() => prefetchRoute('/guia')} onFocus={() => prefetchRoute('/guia')}
          className={({ isActive }) =>
            `flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors ${
              isActive ? 'text-ink-0 bg-bg-2' : 'text-ink-3 hover:text-ink-1 hover:bg-bg-1'
            }`}>
          <BookOpen size={14} strokeWidth={1.75} aria-hidden="true" />
          {!collapsed && <span>Guía</span>}
        </NavLink>

        <NavLink to="/config" title={collapsed ? 'Configuración' : undefined}
          onMouseEnter={() => prefetchRoute('/config')} onFocus={() => prefetchRoute('/config')}
          className={({ isActive }) =>
            `flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors ${
              isActive ? 'text-ink-0 bg-bg-2' : 'text-ink-3 hover:text-ink-1 hover:bg-bg-1'
            }`}>
          <Settings size={14} strokeWidth={1.75} aria-hidden="true" />
          {!collapsed && <span>Configuración</span>}
        </NavLink>

        <button type="button" onClick={() => setRecomOpen(true)}
          title={collapsed ? 'Recomendaciones' : 'Mandanos una recomendación'}
          className={`w-full flex items-center gap-2.5 ${collapsed ? 'justify-center px-2' : 'pl-3 pr-2'} py-1.5 rounded-sm text-sm font-medium transition-colors text-ink-3 hover:text-data-violet hover:bg-data-violet/[0.06]`}>
          <MessageCircle size={14} strokeWidth={1.75} aria-hidden="true" />
          {!collapsed && <span>Recomendaciones</span>}
        </button>

        {/* User row: nombre + badge de plan (solo expandida) */}
        {user && !collapsed && (
          <div className="px-1 mt-1 mb-1 flex items-center gap-1.5 min-w-0">
            <span className="flex-1 text-[11px] text-ink-3 truncate font-mono" title={user.name}>{user.name}</span>
            <PlanBadge tier={user.tier} />
          </div>
        )}

        {/* Action buttons: theme + logout (siempre visibles) */}
        <div className={`flex items-center gap-1 ${collapsed ? 'flex-col mt-1' : 'px-1'}`}>
          {user && collapsed && (
            <div title={`Plan ${user.tier || 'free'}`} className="mb-1"><PlanBadge tier={user.tier} compact /></div>
          )}
          <button onClick={toggle}
            className="p-1.5 rounded-sm text-ink-3 hover:text-ink-0 hover:bg-bg-1 transition-colors"
            title={dark ? 'Modo claro' : 'Modo oscuro'} aria-label={dark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}>
            {dark ? <Sun size={13} strokeWidth={1.75} aria-hidden="true" /> : <Moon size={13} strokeWidth={1.75} aria-hidden="true" />}
          </button>
          <button onClick={logout}
            className="p-1.5 rounded-sm text-ink-3 hover:text-rendi-neg hover:bg-bg-1 transition-colors"
            title="Cerrar sesión" aria-label="Cerrar sesión">
            <LogOut size={13} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </div>
    </aside>

    <RecommendationsModal open={recomOpen} onClose={() => setRecomOpen(false)} />
    </>
  )
}

// ─── PlanBadge ───────────────────────────────────────────────────────────────
function PlanBadge({ tier, compact = false }) {
  const t = tier || 'free'
  const styles = {
    free:  { label: 'FREE',  bg: 'bg-bg-2',           text: 'text-ink-2',       dot: 'bg-ink-3' },
    plus:  { label: 'PLUS',  bg: 'bg-data-cyan/15',   text: 'text-data-cyan',   dot: 'bg-data-cyan' },
    pro:   { label: 'PRO',   bg: 'bg-data-violet/15', text: 'text-data-violet', dot: 'bg-data-violet' },
    admin: { label: 'ADMIN', bg: 'bg-rendi-pos/15',   text: 'text-rendi-pos',   dot: 'bg-rendi-pos' },
  }
  const s = styles[t] || styles.free
  if (compact) return <span className={`inline-block w-1.5 h-1.5 rounded-full ${s.dot}`} aria-label={`Plan ${s.label}`} />
  return (
    <span className={`shrink-0 inline-flex items-center px-1.5 py-0.5 rounded-sm font-mono text-[9px] font-medium tracking-caps ${s.bg} ${s.text}`}
      aria-label={`Plan actual: ${s.label}`}>{s.label}</span>
  )
}
