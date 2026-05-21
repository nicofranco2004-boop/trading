// More — "Más" drawer en mobile (Sprint M1, item 11 anticipado).
// ═══════════════════════════════════════════════════════════════════════════
// Aloja todas las rutas secundarias que no entran en las 4 tabs visibles.
// En mobile es una página real (/mas). En desktop esta ruta no se usa
// porque la sidebar muestra todo directamente.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  LayoutDashboard, Bell, BarChart3, Brain, List, Upload,
  Target, Sparkles, Settings, Shield, ChevronRight, LogOut, BellRing, BellOff, Send, UserRound,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../components/Toast'
import { usePushNotifications } from '../hooks/usePushNotifications'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'

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
      { to: '/perfil-inversor', label: 'Perfil de inversor', icon: UserRound, sub: 'Contexto para el Coach IA' },
      { to: '/objetivos',       label: 'Objetivos',          icon: Target,    sub: 'Metas financieras' },
      { to: '/wrapped',         label: 'Wrapped',            icon: Sparkles,  sub: 'Reseña anual' },
    ],
  },
]

export default function More() {
  const { user, logout } = useAuth()
  const coachDrawer = useCoachDrawer()

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

      {/* Asistente — Coach IA abre el drawer global, no navega a una ruta */}
      <section>
        <h2 className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2 px-1">
          Asistente
        </h2>
        <div className="bg-bg-1 border border-data-violet/30 rounded-lg overflow-hidden">
          <button
            type="button"
            onClick={() => coachDrawer.open()}
            className="w-full flex items-center gap-3 px-4 py-3 hover:bg-data-violet/[0.04] active:bg-data-violet/[0.08] transition-colors text-left"
          >
            <Sparkles size={16} strokeWidth={1.75} className="text-data-violet flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-ink-0 leading-tight">Coach IA</div>
              <div className="text-[11px] text-ink-3 leading-tight mt-0.5">Asistente con contexto de tu portfolio</div>
            </div>
            <ChevronRight size={14} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
          </button>
        </div>
      </section>

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

      {/* Notificaciones push */}
      <PushNotificationsSection />

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

// ─── Push notifications section ─────────────────────────────────────────

function PushNotificationsSection() {
  const toast = useToast()
  const {
    supported, permission, subscribed, loading, error,
    subscribe, unsubscribe, sendTest,
  } = usePushNotifications()
  const [testing, setTesting] = useState(false)

  if (!supported) {
    return (
      <section>
        <h2 className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2 px-1">
          Notificaciones
        </h2>
        <div className="bg-bg-1 border border-line/60 rounded-lg p-4">
          <div className="flex items-center gap-3">
            <BellOff size={16} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
            <p className="text-xs text-ink-2 leading-relaxed">
              Tu navegador no soporta notificaciones push. En iOS necesitás
              instalar Rendi como PWA primero (Compartir → Agregar a inicio).
            </p>
          </div>
        </div>
      </section>
    )
  }

  async function handleToggle() {
    try {
      if (subscribed) {
        await unsubscribe()
        toast?.show?.({ kind: 'success', text: 'Notificaciones desactivadas' })
      } else {
        await subscribe()
        toast?.show?.({ kind: 'success', text: 'Notificaciones activadas' })
      }
    } catch (ex) {
      toast?.show?.({ kind: 'error', text: ex?.message || 'Hubo un error' })
    }
  }

  async function handleTest() {
    setTesting(true)
    try {
      const sent = await sendTest()
      if (sent > 0) {
        toast?.show?.({ kind: 'success', text: `Push enviado a ${sent} ${sent === 1 ? 'device' : 'devices'}` })
      } else {
        toast?.show?.({ kind: 'warning', text: 'No hay devices suscritos.' })
      }
    } catch (ex) {
      toast?.show?.({ kind: 'error', text: ex?.message || 'No se pudo enviar' })
    } finally {
      setTesting(false)
    }
  }

  const statusLabel = subscribed
    ? 'Activadas'
    : permission === 'denied'
      ? 'Bloqueadas por el navegador'
      : 'Desactivadas'
  const statusTone = subscribed ? 'text-rendi-pos' : permission === 'denied' ? 'text-rendi-neg' : 'text-ink-3'

  return (
    <section>
      <h2 className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2 px-1">
        Notificaciones
      </h2>
      <div className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
        {/* Toggle activar/desactivar */}
        <button
          onClick={handleToggle}
          disabled={loading || permission === 'denied'}
          className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-bg-2/60 active:bg-bg-3 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {subscribed
            ? <BellRing size={16} strokeWidth={1.75} className="text-rendi-pos flex-shrink-0" />
            : <Bell size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />}
          <div className="flex-1 min-w-0">
            <div className="text-sm font-medium text-ink-0 leading-tight flex items-center gap-2">
              Notificaciones push
              <span className={`text-[10px] font-mono uppercase tracking-caps ${statusTone}`}>
                {statusLabel}
              </span>
            </div>
            <div className="text-[11px] text-ink-3 leading-tight mt-0.5">
              {subscribed
                ? 'Recibís alertas de earnings, drawdowns y nuevos sesgos.'
                : permission === 'denied'
                  ? 'Reactivá en los ajustes del navegador.'
                  : 'Recibí alertas cuando algo importante pasa en tu cartera.'}
            </div>
          </div>
          <span className={`text-[10px] font-mono uppercase tracking-caps ${subscribed ? 'text-rendi-neg' : 'text-rendi-pos'}`}>
            {loading ? '...' : subscribed ? 'Desactivar' : 'Activar'}
          </span>
        </button>

        {/* Test button */}
        {subscribed && (
          <button
            onClick={handleTest}
            disabled={testing}
            className="w-full flex items-center gap-3 px-4 py-3 border-t border-line/40 text-left hover:bg-bg-2/60 active:bg-bg-3 transition-colors disabled:opacity-60"
          >
            <Send size={16} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-ink-0 leading-tight">
                Mandame un test
              </div>
              <div className="text-[11px] text-ink-3 leading-tight mt-0.5">
                Verificá que las notificaciones llegan correctamente.
              </div>
            </div>
            <span className="text-[10px] font-mono uppercase tracking-caps text-data-blue">
              {testing ? '...' : 'Enviar'}
            </span>
          </button>
        )}

        {error && (
          <div className="px-4 py-2 border-t border-line/40 bg-rendi-neg/[0.04] text-[11px] text-rendi-neg">
            {error}
          </div>
        )}
      </div>
    </section>
  )
}
