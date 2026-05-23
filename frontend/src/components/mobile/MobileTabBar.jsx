// MobileTabBar — bottom tabs + FAB central (Sprint M1 mobile).
// ═══════════════════════════════════════════════════════════════════════════
// 5 tabs: Home · Posiciones · [+] · Insights · Más.
// El "+" no es navegación — abre un sheet de quick actions (Nueva op, Nueva
// posición, Watchlist, Buscar). El sheet vive como sibling acá para no tener
// que duplicar lógica en cada página.
//
// Patrón del audit:
// - Tab bar fija al fondo, h=56px, separada del body por border-line.
// - Tab activa: text-ink-0 + dot signal verde (no background pill).
// - FAB: violet accent (data-violet token), 56×56, ligeramente elevado.
// - Pulsado del FAB → bottom sheet con 4 acciones.
//
// IMPORTANTE: solo se renderiza cuando useIsMobile() es true. App.jsx hace
// el switch desktop/mobile a nivel layout.

import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  Home, Briefcase, Compass, MoreHorizontal, Plus,
  PlusCircle, Repeat, Star, Search,
} from 'lucide-react'
import BottomSheet from './BottomSheet'
import { track } from '../../utils/track'
import { prefetchRoute } from '../../utils/routePrefetch'

const TABS = [
  { to: '/',             label: 'Home',       icon: Home },
  { to: '/posiciones',   label: 'Cartera',    icon: Briefcase },
  // [+] FAB ocupa el slot 3 — no es NavLink
  { to: '/insights',     label: 'Insights',   icon: Compass },
  { to: '/mas',          label: 'Más',        icon: MoreHorizontal },
]

export default function MobileTabBar() {
  const [fabOpen, setFabOpen] = useState(false)

  return (
    <>
      {/* Spacer para que el contenido no quede tapado por la tab bar */}
      <div aria-hidden className="h-[64px]" />

      <nav
        className="fixed bottom-0 left-0 right-0 z-40 bg-bg-0/95 backdrop-blur-md border-t border-line"
        role="navigation"
        aria-label="Navegación principal"
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
      >
        <div className="grid grid-cols-5 h-14">
          {TABS.slice(0, 2).map((t) => <TabItem key={t.to} {...t} />)}

          {/* FAB central */}
          <button
            onClick={() => {
              track('mobile_fab_opened')
              setFabOpen(true)
            }}
            aria-label="Abrir acciones rápidas"
            className="relative flex items-center justify-center"
          >
            <span
              aria-hidden
              className="absolute -top-4 w-12 h-12 rounded-full bg-data-violet flex items-center justify-center shadow-lg shadow-data-violet/30 hover:bg-data-violet/90 active:scale-95 transition-transform"
            >
              <Plus size={20} strokeWidth={2} className="text-white" />
            </span>
            <span className="absolute bottom-1 text-[9px] font-mono uppercase tracking-caps text-ink-3">
              Acciones
            </span>
          </button>

          {TABS.slice(2).map((t) => <TabItem key={t.to} {...t} />)}
        </div>
      </nav>

      {fabOpen && <QuickActionsSheet onClose={() => setFabOpen(false)} />}
    </>
  )
}

// ─── Tab item ────────────────────────────────────────────────────────────

function TabItem({ to, label, icon: Icon }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      onTouchStart={() => prefetchRoute(to)}
      onFocus={() => prefetchRoute(to)}
      className={({ isActive }) =>
        `flex flex-col items-center justify-center gap-0.5 text-[10px] transition-colors ${
          isActive ? 'text-ink-0' : 'text-ink-3 hover:text-ink-1'
        }`
      }
    >
      {({ isActive }) => (
        <>
          <Icon size={18} strokeWidth={1.75} />
          <span className="font-mono uppercase tracking-caps text-[9px]">{label}</span>
          {isActive && (
            <span
              aria-hidden
              className="absolute top-1 w-1 h-1 rounded-full bg-rendi-pos"
            />
          )}
        </>
      )}
    </NavLink>
  )
}

// ─── Quick actions sheet ─────────────────────────────────────────────────
// Versión inicial M1 (sheet simple). En M2 va a usar el BottomSheet
// formal con drag handle + sticky footer.

const QUICK_ACTIONS = [
  {
    code: 'new_op',
    label: 'Nueva operación',
    sub: 'Registrar compra o venta',
    icon: Repeat,
    tone: 'pos',
    to: '/operaciones?action=new',
  },
  {
    code: 'new_position',
    label: 'Nueva posición',
    sub: 'Agregar tenencia actual',
    icon: PlusCircle,
    tone: 'accent',
    to: '/posiciones?action=new',
  },
  {
    code: 'watchlist',
    label: 'Agregar a watchlist',
    sub: 'Seguir un ticker',
    icon: Star,
    tone: 'warn',
    to: '/?action=watchlist',
  },
  {
    code: 'search',
    label: 'Buscar activo',
    sub: 'Ver precio, info, agregar',
    icon: Search,
    tone: 'info',
    to: '/buscar',
  },
]

const TONE_CLASS = {
  pos:    'bg-rendi-pos/10 text-rendi-pos border-rendi-pos/30',
  accent: 'bg-rendi-accent/10 text-rendi-accent border-rendi-accent/30',
  warn:   'bg-rendi-warn/10 text-rendi-warn border-rendi-warn/30',
  info:   'bg-data-cyan/10 text-data-cyan border-data-cyan/30',
}

function QuickActionsSheet({ onClose }) {
  const navigate = useNavigate()

  function handleAction(action) {
    track('mobile_fab_action', { code: action.code })
    onClose()
    navigate(action.to)
  }

  return (
    <BottomSheet
      open
      onClose={onClose}
      eyebrow="Acciones rápidas"
      title="¿Qué querés hacer?"
      ariaLabel="Acciones rápidas"
    >
      <ul className="px-3 py-2">
        {QUICK_ACTIONS.map((a) => {
          const Icon = a.icon
          return (
            <li key={a.code}>
              <button
                onClick={() => handleAction(a)}
                className="w-full flex items-center gap-3 px-3 py-3 rounded-lg hover:bg-bg-2/60 active:bg-bg-3 transition-colors text-left"
              >
                <span className={`w-10 h-10 rounded-full border ${TONE_CLASS[a.tone] || TONE_CLASS.info} flex items-center justify-center flex-shrink-0`}>
                  <Icon size={16} strokeWidth={1.75} />
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block text-sm font-medium text-ink-0 leading-tight">{a.label}</span>
                  <span className="block text-[11px] text-ink-3 leading-tight mt-0.5">{a.sub}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </BottomSheet>
  )
}
