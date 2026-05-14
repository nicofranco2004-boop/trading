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
  Home as HomeIcon, LayoutDashboard, Briefcase, List, Settings, LogOut,
  Sun, Moon, Compass, Shield, Target, BarChart3, Bell, Upload, Menu,
} from 'lucide-react'
import RendiLogo from './RendiLogo'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'

const SIDEBAR_W_EXPANDED = '220px'
const SIDEBAR_W_COLLAPSED = '56px'
const LS_KEY = 'rendi_sidebar_collapsed'

const GROUPS = [
  {
    label: 'Análisis',
    items: [
      { to: '/',          label: 'Home',       icon: HomeIcon },
      { to: '/novedades', label: 'Novedades',  icon: Bell },
      { to: '/dashboard', label: 'Dashboard',  icon: LayoutDashboard },
      { to: '/insights',  label: 'Insights',   icon: Compass },
      { to: '/reportes',  label: 'Reportes',   icon: BarChart3 },
    ],
  },
  {
    label: 'Data',
    items: [
      { to: '/posiciones',  label: 'Posiciones',  icon: Briefcase },
      { to: '/operaciones', label: 'Operaciones', icon: List },
      { to: '/imports',     label: 'Importes',    icon: Upload },
    ],
  },
  {
    label: 'Personal',
    items: [
      { to: '/objetivos', label: 'Objetivos', icon: Target },
    ],
  },
]

export default function Sidebar() {
  const { user, logout } = useAuth()
  const { dark, toggle } = useTheme()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(LS_KEY) === 'true')

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
          <RendiLogo size={20} />
          {!collapsed && (
            <span className="font-semibold text-base tracking-tight text-ink-0">rendi</span>
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
        {allGroups.map((group, gi) => (
          <div key={group.label} className={gi > 0 ? 'mt-4' : ''}>
            {!collapsed && (
              <p className="px-2.5 mb-1 font-mono text-[10px] uppercase tracking-label text-ink-3 font-medium">
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
                          className="absolute left-0 top-1 bottom-1 w-0.5 bg-rendi-pos rounded-full"
                        />
                      )}
                      {isActive && collapsed && (
                        <span
                          aria-hidden
                          className="absolute left-0 top-1 bottom-1 w-0.5 bg-rendi-pos rounded-full"
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

      {/* Footer: configuración + user + toggle + logout */}
      <div className="border-t border-line px-2 py-2 flex-shrink-0">
        <NavLink
          to="/config"
          title={collapsed ? 'Configuración' : undefined}
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

        <div className={`flex items-center gap-1 mt-1 ${collapsed ? 'flex-col' : 'px-1'}`}>
          {user && !collapsed && (
            <span className="flex-1 text-[11px] text-ink-3 truncate font-mono" title={user.name}>
              {user.name}
            </span>
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
  )
}
