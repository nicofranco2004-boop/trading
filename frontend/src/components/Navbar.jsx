import { useState, useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { LayoutDashboard, Briefcase, List, Settings, LogOut, Sun, Moon, Sparkles, Shield, Target, Menu, X } from 'lucide-react'
import RendiLogo from './RendiLogo'
import { useAuth } from '../contexts/AuthContext'
import { useTheme } from '../contexts/ThemeContext'

const links = [
  { to: '/',            label: 'Dashboard',   icon: LayoutDashboard },
  { to: '/operaciones', label: 'Operaciones', icon: List },
  { to: '/posiciones',  label: 'Posiciones',  icon: Briefcase },
  { to: '/insights',    label: 'Insights',    icon: Sparkles },
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
      <nav className="fixed top-0 left-0 right-0 z-50 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700/60 shadow-sm dark:shadow-none px-3 md:px-6 h-14 flex items-center">
        <NavLink to="/" className="flex items-center gap-2 flex-shrink-0">
          <RendiLogo size={28} />
          <span className="font-bold text-lg tracking-tight text-slate-900 dark:text-white">rendi</span>
        </NavLink>

        {/* Desktop nav */}
        <div className="hidden lg:flex flex-1 items-center justify-center gap-1">
          {allLinks.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-rendi-green/10 dark:bg-rendi-green/15 text-rendi-green-dark dark:text-rendi-green'
                    : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`
              }
            >
              <Icon size={15} />
              {label}
            </NavLink>
          ))}
        </div>

        <div className="flex-1 lg:hidden" />

        {/* Acciones derecha desktop */}
        <div className="hidden lg:flex flex-shrink-0 items-center gap-2">
          {user && (
            <span className="text-xs text-slate-400 dark:text-slate-500 hidden xl:block">{user.name}</span>
          )}
          <button
            onClick={toggle}
            className="p-1.5 rounded-md text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            title={dark ? 'Modo claro' : 'Modo oscuro'}
          >
            {dark ? <Sun size={15} /> : <Moon size={15} />}
          </button>
          <button
            onClick={logout}
            className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 transition-colors px-2 py-1.5 rounded-md hover:bg-slate-100 dark:hover:bg-slate-800"
            title="Cerrar sesión"
          >
            <LogOut size={14} />
            <span>Salir</span>
          </button>
        </div>

        {/* Hamburger mobile */}
        <div className="lg:hidden flex items-center gap-1">
          <button
            onClick={toggle}
            className="p-2 rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
            title={dark ? 'Modo claro' : 'Modo oscuro'}
          >
            {dark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button
            onClick={() => setOpen(o => !o)}
            className="p-2 rounded-md text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
            aria-label="Menú"
          >
            {open ? <X size={20} /> : <Menu size={20} />}
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
          <div className="fixed top-14 left-0 right-0 z-40 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700/60 shadow-lg lg:hidden max-h-[calc(100vh-3.5rem)] overflow-y-auto">
            <div className="p-3 space-y-1">
              {allLinks.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-rendi-green/10 dark:bg-rendi-green/15 text-rendi-green-dark dark:text-rendi-green'
                        : 'text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'
                    }`
                  }
                >
                  <Icon size={18} />
                  {label}
                </NavLink>
              ))}
              <div className="border-t border-slate-200 dark:border-slate-700/60 my-2" />
              {user && (
                <div className="px-3 py-2 text-xs text-slate-400 dark:text-slate-500">
                  Conectado como <span className="text-slate-700 dark:text-slate-300 font-medium">{user.name}</span>
                </div>
              )}
              <button
                onClick={logout}
                className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-red-500 dark:text-red-400 hover:bg-red-500/10 transition"
              >
                <LogOut size={18} />
                Cerrar sesión
              </button>
            </div>
          </div>
        </>
      )}
    </>
  )
}
