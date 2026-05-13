import { useState, useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { LayoutDashboard, Briefcase, List, Settings, LogOut, Sun, Moon, Compass, Shield, Target, Menu, X, BarChart3, Bell } from 'lucide-react'
import RendiLogo from './RendiLogo'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'

const links = [
  { to: '/',            label: 'Dashboard',   icon: LayoutDashboard },
  { to: '/operaciones', label: 'Operaciones', icon: List },
  { to: '/posiciones',  label: 'Posiciones',  icon: Briefcase },
  { to: '/insights',    label: 'Insights',    icon: Compass },
  { to: '/novedades',   label: 'Novedades',   icon: Bell },
  { to: '/reportes',    label: 'Reportes',    icon: BarChart3 },
  { to: '/objetivos',   label: 'Objetivos',   icon: Target },
  { to: '/config',      label: 'Configuración', icon: Settings },
]

export default function Navbar() {
  const { user, logout } = useAuth()
  const { dark, toggle } = useTheme()
  const [open, setOpen] = useState(false)
  const location = useLocation()

  useEffect(() => { setOpen(false) }, [location.pathname])
  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  const allLinks = [...links, ...(user?.is_admin ? [{ to: '/admin', label: 'Admin', icon: Shield }] : [])]

  return (
    <>
      <nav className="fixed top-0 left-0 right-0 z-50 bg-white dark:bg-bg-0 border-b border-slate-200 dark:border-line px-3 md:px-6 h-12 flex items-center">
        <NavLink to="/" className="flex items-center gap-2 flex-shrink-0 group">
          <RendiLogo size={24} />
          <span className="font-semibold text-base tracking-tight text-slate-900 dark:text-ink-0">rendi</span>
        </NavLink>

        {/* Desktop nav — active state es underline 2px en rendi-pos, no pill verde.
            Inspirado en Linear/Vercel: monocromático, jerarquía por peso, no por fondo. */}
        <div className="hidden lg:flex flex-1 items-center justify-center gap-1">
          {allLinks.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `relative flex items-center gap-2 px-3 py-1.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'text-slate-900 dark:text-ink-0'
                    : 'text-slate-500 dark:text-ink-2 hover:text-slate-900 dark:hover:text-ink-0'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <Icon size={15} strokeWidth={1.5} />
                  {label}
                  {isActive && (
                    <span
                      aria-hidden
                      className="absolute -bottom-[13px] left-2 right-2 h-[2px] bg-rendi-pos"
                    />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </div>

        <div className="flex-1 lg:hidden" />

        {/* Acciones derecha desktop */}
        <div className="hidden lg:flex flex-shrink-0 items-center gap-2">
          {user && (
            <span className="text-xs text-slate-400 dark:text-ink-3 hidden xl:block font-mono">{user.name}</span>
          )}
          <button
            onClick={toggle}
            className="p-1.5 rounded-sm text-slate-500 dark:text-ink-2 hover:text-slate-900 dark:hover:text-ink-0 transition-colors"
            title={dark ? 'Modo claro' : 'Modo oscuro'}
            aria-label={dark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
          >
            {dark ? <Sun size={15} strokeWidth={1.5} aria-hidden="true" /> : <Moon size={15} strokeWidth={1.5} aria-hidden="true" />}
          </button>
          <button
            onClick={logout}
            className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-ink-2 hover:text-slate-900 dark:hover:text-ink-0 transition-colors px-2 py-1.5"
            title="Cerrar sesión"
          >
            <LogOut size={14} strokeWidth={1.5} />
            <span>Salir</span>
          </button>
        </div>

        {/* Hamburger mobile */}
        <div className="lg:hidden flex items-center gap-1">
          <button
            onClick={toggle}
            className="p-2 rounded-sm text-slate-500 dark:text-ink-2 hover:bg-slate-100 dark:hover:bg-bg-2 transition"
            title={dark ? 'Modo claro' : 'Modo oscuro'}
            aria-label={dark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
          >
            {dark ? <Sun size={16} strokeWidth={1.5} aria-hidden="true" /> : <Moon size={16} strokeWidth={1.5} aria-hidden="true" />}
          </button>
          <button
            onClick={() => setOpen(o => !o)}
            className="p-2 rounded-sm text-slate-700 dark:text-ink-1 hover:bg-slate-100 dark:hover:bg-bg-2 transition"
            aria-label="Menú"
          >
            {open ? <X size={20} strokeWidth={1.5} /> : <Menu size={20} strokeWidth={1.5} />}
          </button>
        </div>
      </nav>

      {/* Drawer mobile */}
      {open && (
        <>
          <div
            className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm lg:hidden"
            onClick={() => setOpen(false)}
          />
          <div className="fixed top-12 left-0 right-0 z-40 bg-white dark:bg-bg-0 border-b border-slate-200 dark:border-line lg:hidden max-h-[calc(100vh-3rem)] overflow-y-auto">
            <div className="p-3 space-y-1">
              {allLinks.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm font-medium transition-colors ${
                      isActive
                        ? 'text-slate-900 dark:text-ink-0 bg-slate-100 dark:bg-bg-2'
                        : 'text-slate-700 dark:text-ink-1 hover:bg-slate-100 dark:hover:bg-bg-2'
                    }`
                  }
                >
                  <Icon size={18} strokeWidth={1.5} />
                  {label}
                </NavLink>
              ))}
              <div className="border-t border-slate-200 dark:border-line my-2" />
              {user && (
                <div className="px-3 py-2 text-xs text-slate-400 dark:text-ink-3 font-mono">
                  Conectado como <span className="text-slate-700 dark:text-ink-1 font-medium font-sans">{user.name}</span>
                </div>
              )}
              <button
                onClick={logout}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm font-medium text-rendi-neg hover:bg-rendi-neg/10 transition"
              >
                <LogOut size={18} strokeWidth={1.5} />
                Cerrar sesión
              </button>
            </div>
          </div>
        </>
      )}
    </>
  )
}
