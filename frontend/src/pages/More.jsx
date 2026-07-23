// More — "Más" drawer en mobile (Sprint M1, item 11 anticipado).
// ═══════════════════════════════════════════════════════════════════════════
// Aloja todas las rutas secundarias que no entran en las 4 tabs visibles.
// En mobile es una página real (/mas). En desktop esta ruta no se usa
// porque la sidebar muestra todo directamente.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  LayoutDashboard, Bell, BarChart3, Brain, List, Upload, Gauge,
  Target, Sparkles, Settings, Shield, ChevronRight, LogOut, BellRing, BellOff, Send, UserRound, MessageCircle,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import { useAuth } from '../contexts/AuthContext'
import RecommendationsModal from '../components/RecommendationsModal'
import { useToast } from '../components/Toast'
import { usePushNotifications } from '../hooks/usePushNotifications'
import { useCoachDrawer } from '../contexts/CoachDrawerContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'

// Restructure 2026-05-27: 7 items en 3 grupos, espejado del sidebar desktop.
// Las URLs viejas (/dashboard, /insights, etc.) redirigen al wrapper consolidado
// con el tab correspondiente (ver App.jsx).
const GROUPS = [
  {
    label: 'Tu portfolio',
    items: [
      { to: '/dashboard',   label: 'Dashboard',    icon: LayoutDashboard, sub: 'Evolución, composición y heatmap' },
      { to: '/posiciones',  label: 'Cartera',      icon: List,   sub: 'Tus tenencias y objetivos' },
      { to: '/operaciones', label: 'Movimientos',  icon: List,   sub: 'Trades + depósitos + dividendos' },
      { to: '/imports',     label: 'Importar CSV', icon: Upload, sub: 'Subí CSVs de tus brokers' },
      { to: '/alertas',     label: 'Alertas',      icon: BellRing, sub: 'Avisos de precio y variación' },
    ],
  },
  {
    label: 'Análisis',
    items: [
      { to: '/analisis',        label: 'Métricas',           icon: Brain,     sub: 'Diagnóstico, comportamiento, reportes' },
      { to: '/fundamentals',    label: 'Calidad de cartera', icon: Gauge,     sub: 'Calidad de tus tenencias + buscador' },
      { to: '/perfil-inversor', label: 'Perfil de inversor', icon: UserRound, sub: 'Tu perfil declarado vs. tu cartera' },
      { to: '/novedades',       label: 'Novedades',          icon: Bell,      sub: 'Noticias + eventos' },
    ],
  },
]

export default function More() {
  const { user, logout } = useAuth()
  const coachDrawer = useCoachDrawer()
  const { clientCtx } = useAdvisorContext()
  const [recomOpen, setRecomOpen] = useState(false)

  // El asesor en su propio nivel (sin haber entrado a un cliente) no tiene
  // cartera propia — "Tu portfolio"/"Análisis" no aplican, mismo criterio
  // que el sidebar desktop. Adentro de un cliente (clientCtx) es SU cartera.
  const atOwnLevel = user?.tier === 'advisor' && !clientCtx

  const allGroups = [
    // Plan Asesor: el roster es SU home — sin esta entrada, en mobile no había
    // forma de volver a /clientes navegando (solo tipeando la URL). Dashboard
    // (el libro) solo tiene sentido en su propio nivel — adentro de un
    // cliente, "Dashboard" ya aparece más abajo como el de ESE cliente.
    ...(user?.tier === 'advisor' ? [{
      label: 'Plan Asesor',
      items: [
        ...(atOwnLevel ? [{ to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard, sub: 'Tu libro: AUM total, estrella, colas' }] : []),
        { to: '/clientes', label: 'Clientes', icon: UserRound, sub: 'Tus clientes y el resumen de sus carteras' },
      ],
    }] : []),
    // Filtra items adminOnly (ej. Fundamentals) para los que no son admin.
    ...(atOwnLevel ? [] : GROUPS.map(g => ({
      ...g,
      items: g.items.filter(it => !it.adminOnly || user?.is_admin),
    }))),
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
        <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
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
          <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
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
        <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
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
            type="button"
            onClick={() => setRecomOpen(true)}
            className="w-full flex items-center gap-3 px-4 py-3 border-t border-line/40 hover:bg-data-violet/[0.04] active:bg-data-violet/[0.08] transition-colors text-left"
          >
            <MessageCircle size={16} strokeWidth={1.75} className="text-data-violet flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-ink-0 leading-tight">Recomendaciones</div>
              <div className="text-[11px] text-ink-3 leading-tight mt-0.5">Mandanos ideas, bugs o feedback</div>
            </div>
            <ChevronRight size={14} strokeWidth={1.75} className="text-ink-3" />
          </button>
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

      {/* Modal de recomendaciones — trigger desde el botón "Recomendaciones"
          de la sección Cuenta arriba. */}
      <RecommendationsModal open={recomOpen} onClose={() => setRecomOpen(false)} />
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
        <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
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
      <h2 className="text-[12.5px] text-ink-2 mb-2 px-1 font-medium">
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
              <span className={`text-[12px] ${statusTone} font-medium`}>
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
          <span className={`text-[12px] ${subscribed ? 'text-rendi-neg' : 'text-rendi-pos'} font-medium`}>
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
            <span className="text-[12px] text-data-blue font-medium">
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
