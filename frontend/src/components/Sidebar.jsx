// Sidebar — navegación lateral fija (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Reemplaza el top Navbar. Patrón Linear/Vercel/Stripe:
// • Ancho fijo ~220px desktop
// • Background ink (más oscuro que el page bg)
// • Items agrupados en 3 secciones lógicas (Análisis / Data / Personal)
// • Activo = text-ink-0 + border-left 2px signal verde
// • Footer con user info + theme toggle + logout
//
// Mobile: no responsive en V2. Vendrá un design mobile-only aparte.

import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  Home as HomeIcon, LayoutDashboard, Briefcase, List, Settings, LogOut,
  Sun, Moon, Compass, Shield, Target, BarChart3, Bell, Upload,
} from 'lucide-react'
import RendiLogo from './RendiLogo'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'

// Estructura: grupos lógicos para que con N=9 items la lista no se sienta plana.
// Orden de Análisis: mercado general → específico tuyo (Home/Novedades primero
// porque son contexto externo; Dashboard/Insights/Reportes son tu lente).
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
  const location = useLocation()

  const allGroups = [
    ...GROUPS,
    ...(user?.is_admin
      ? [{ label: 'Admin', items: [{ to: '/admin', label: 'Admin', icon: Shield }] }]
      : []),
  ]

  return (
    <aside className="fixed top-0 left-0 bottom-0 w-[220px] bg-bg-0 border-r border-line flex flex-col z-40">
      {/* Logo / marca */}
      <NavLink
        to="/"
        className="flex items-center gap-2.5 px-4 h-14 border-b border-line group flex-shrink-0"
      >
        <RendiLogo size={20} />
        <span className="font-semibold text-base tracking-tight text-ink-0">rendi</span>
      </NavLink>

      {/* Navegación */}
      <nav className="flex-1 overflow-y-auto py-3 px-2">
        {allGroups.map((group, gi) => (
          <div key={group.label} className={gi > 0 ? 'mt-4' : ''}>
            <p className="px-2.5 mb-1 font-mono text-[10px] uppercase tracking-label text-ink-3 font-medium">
              {group.label}
            </p>
            <div className="space-y-0.5">
              {group.items.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `relative flex items-center gap-2.5 pl-3 pr-2 py-1.5 rounded-sm text-sm font-medium transition-colors ${
                      isActive
                        ? 'text-ink-0 bg-bg-2'
                        : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <Icon size={14} strokeWidth={1.75} aria-hidden="true" />
                      <span>{label}</span>
                      {isActive && (
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

      {/* Footer: user + toggle + logout */}
      <div className="border-t border-line px-2 py-2 flex-shrink-0">
        <NavLink
          to="/config"
          className={({ isActive }) =>
            `flex items-center gap-2.5 pl-3 pr-2 py-1.5 rounded-sm text-sm font-medium transition-colors ${
              isActive
                ? 'text-ink-0 bg-bg-2'
                : 'text-ink-2 hover:text-ink-0 hover:bg-bg-1'
            }`
          }
        >
          <Settings size={14} strokeWidth={1.75} aria-hidden="true" />
          <span>Configuración</span>
        </NavLink>

        <div className="flex items-center gap-1 mt-1 px-1">
          {user && (
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
