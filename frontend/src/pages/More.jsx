// More — "Más" drawer en mobile (Sprint M1, item 11 anticipado).
// ═══════════════════════════════════════════════════════════════════════════
// Aloja todas las rutas secundarias que no entran en las 4 tabs visibles.
// En mobile es una página real (/mas). En desktop esta ruta no se usa
// porque la sidebar muestra todo directamente.

import { Link } from 'react-router-dom'
import {
  LayoutDashboard, Bell, BarChart3, Brain, List, Upload,
  Target, Sparkles, Settings, Shield, ChevronRight, LogOut,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { useAuth } from '../contexts/AuthContext'

const GROUPS = [
  {
    label: 'Análisis',
    items: [
      { to: '/dashboard',      label: 'Dashboard',      icon: LayoutDashboard, sub: 'Resumen consolidado' },
      { to: '/novedades',      label: 'Novedades',      icon: Bell,            sub: 'Noticias + eventos' },
      { to: '/comportamiento', label: 'Comportamiento', icon: Brain,           sub: 'Sesgos detectados' },
      { to: '/reportes',       label: 'Reportes',       icon: BarChart3,       sub: 'Performance mensual' },
    ],
  },
  {
    label: 'Data',
    items: [
      { to: '/operaciones', label: 'Operaciones', icon: List,   sub: 'Historial de trades' },
      { to: '/imports',     label: 'Importaciones', icon: Upload, sub: 'CSV de brokers' },
    ],
  },
  {
    label: 'Personal',
    items: [
      { to: '/objetivos', label: 'Objetivos', icon: Target,    sub: 'Metas financieras' },
      { to: '/wrapped',   label: 'Wrapped',   icon: Sparkles,  sub: 'Reseña anual' },
    ],
  },
]

export default function More() {
  const { user, logout } = useAuth()

  const allGroups = [
    ...GROUPS,
    ...(user?.is_admin
      ? [{
          label: 'Admin',
          items: [{ to: '/admin', label: 'Admin', icon: Shield, sub: 'Panel administrativo' }],
        }]
      : []),
  ]

  return (
    <div className="page-shell space-y-5">
      <PageHeader
        eyebrow="Menú"
        title="Más"
        subtitle="Todas las secciones de Rendi."
      />

      {allGroups.map((group) => (
        <section key={group.label}>
          <h2 className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2 px-1">
            {group.label}
          </h2>
          <div className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
            {group.items.map((item, i) => {
              const Icon = item.icon
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`flex items-center gap-3 px-4 py-3 hover:bg-bg-2/60 active:bg-bg-3 transition-colors ${
                    i > 0 ? 'border-t border-line/40' : ''
                  }`}
                >
                  <Icon size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-ink-0 leading-tight">{item.label}</div>
                    <div className="text-[11px] text-ink-3 leading-tight mt-0.5">{item.sub}</div>
                  </div>
                  <ChevronRight size={14} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
                </Link>
              )
            })}
          </div>
        </section>
      ))}

      {/* Configuración + logout */}
      <section>
        <h2 className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2 px-1">
          Cuenta
        </h2>
        <div className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
          <Link
            to="/config"
            className="flex items-center gap-3 px-4 py-3 hover:bg-bg-2/60 active:bg-bg-3 transition-colors"
          >
            <Settings size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-ink-0 leading-tight">Configuración</div>
              <div className="text-[11px] text-ink-3 leading-tight mt-0.5">Brokers · workspace · contraseña</div>
            </div>
            <ChevronRight size={14} strokeWidth={1.75} className="text-ink-3" />
          </Link>
          <button
            onClick={logout}
            className="w-full flex items-center gap-3 px-4 py-3 border-t border-line/40 text-left text-rendi-neg hover:bg-rendi-neg/[0.04] active:bg-rendi-neg/[0.08] transition-colors"
          >
            <LogOut size={16} strokeWidth={1.75} className="flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium leading-tight">Cerrar sesión</div>
              {user?.name && (
                <div className="text-[11px] text-ink-3 leading-tight mt-0.5 font-mono">{user.name}</div>
              )}
            </div>
          </button>
        </div>
      </section>
    </div>
  )
}
