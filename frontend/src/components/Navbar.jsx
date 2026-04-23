import { NavLink } from 'react-router-dom'
import { LayoutDashboard, Briefcase, BarChart3, List, Settings } from 'lucide-react'
import RendiLogo from './RendiLogo'

const links = [
  { to: '/',           label: 'Dashboard',   icon: LayoutDashboard },
  { to: '/posiciones', label: 'Posiciones',  icon: Briefcase },
  { to: '/mensual',    label: 'Mensual',     icon: BarChart3 },
  { to: '/operaciones',label: 'Operaciones', icon: List },
  { to: '/config',     label: 'Config',      icon: Settings },
]

export default function Navbar() {
  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-slate-900 border-b border-slate-700/60 px-6 h-14 flex items-center gap-1">
      <NavLink to="/" className="flex items-center gap-2 mr-8">
        <RendiLogo size={28} />
        <span className="font-bold text-lg tracking-tight text-white">rendi</span>
      </NavLink>
      {links.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === '/'}
          className={({ isActive }) =>
            `flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
              isActive
                ? 'bg-blue-600/20 text-blue-400'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
            }`
          }
        >
          <Icon size={15} />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
