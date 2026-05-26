// OnboardingChecklist — checklist persistente en Home para users sin
// completar todos los pasos clave de configuración.
// ════════════════════════════════════════════════════════════════════════════
// Complementa el wizard /onboarding (que se ejecuta una sola vez post-signup)
// con una guía visible "en frío" durante los primeros días/semanas del user.
//
// Items trackeados:
//   1. Tu primer broker        — count(brokers) > 0
//   2. Tu primera operación    — count(positions o operations) > 0
//   3. Quiz de perfil inversor — investor_profile != null
//   4. Probaste el Coach IA    — flag localStorage 'rendi_ai_discovered'
//
// El componente:
//   - Hace 3 fetches paralelos al montar (brokers, positions, investor-profile)
//   - No se monta si el user ya completó todos los items (silent dismiss)
//   - Tiene botón "Cerrar permanentemente" (flag localStorage) para users
//     que prefieren ocultarlo
//   - Cada item incompleto es link al lugar donde se completa
//
// Tracking:
//   - checklist_viewed (al montarse)
//   - checklist_item_clicked { item }
//   - checklist_dismissed (cierre manual)

import { useEffect, useState, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  CheckCircle2, Circle, X, Briefcase, PlusCircle, Brain, Bot,
  ArrowRight, Sparkles,
} from 'lucide-react'
import { api } from '../../utils/api'
import { trackEvent } from '../../utils/analytics'
import { track } from '../../utils/track'
import { useCoachDrawer } from '../../contexts/CoachDrawerContext'
import { isAIDiscovered, AI_DISCOVERY_KEY } from '../ai/AIDiscoveryBanner'

const CHECKLIST_DISMISSED_KEY = 'rendi_checklist_dismissed'

export default function OnboardingChecklist() {
  const navigate = useNavigate()
  const location = useLocation()
  const coachDrawer = useCoachDrawer()
  const [state, setState] = useState({
    hasBroker: null,    // null = loading, true/false = known
    hasPosition: null,
    hasProfile: null,
    hasAI: isAIDiscovered(),
    loaded: false,
  })
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(CHECKLIST_DISMISSED_KEY) === '1' } catch { return false }
  })
  // Tick para forzar re-fetch (custom events incrementan este número).
  const [refreshTick, setRefreshTick] = useState(0)

  // ─── Detectar AI discovery REACTIVO ─────────────────────────────────────
  // El Coach IA es un drawer overlay — cuando el user lo cierra, Home NO se
  // desmonta y OnboardingChecklist sigue con state viejo. localStorage NO
  // dispara `storage` event para el mismo tab que escribió. Por eso antes
  // requería cambiar de tab y volver (para que onFocus disparara el re-check).
  // Fix: además de storage/focus, escuchamos un custom event 'ai-discovered'
  // que markAIDiscovered() dispara explícitamente. Más reactive cross-tab Y
  // intra-tab.
  useEffect(() => {
    function recheckAI() {
      setState((s) => ({ ...s, hasAI: isAIDiscovered() }))
    }
    function onStorage(e) {
      if (e.key === AI_DISCOVERY_KEY) recheckAI()
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener('focus', recheckAI)
    window.addEventListener('ai-discovered', recheckAI)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener('focus', recheckAI)
      window.removeEventListener('ai-discovered', recheckAI)
    }
  }, [])

  // ─── Re-fetch del estado cuando se vuelve a Home ─────────────────────────
  // Si el user navega a /perfil-inversor, completa el quiz, y vuelve a /,
  // el OnboardingChecklist no se desmonta (porque Home maneja su propio
  // lifecycle dentro de Layout) — pero como el path cambió, queremos re-leer.
  // Usamos location.pathname como dep para refetchar al volver al Home.
  const fetchState = useCallback(() => {
    let cancelled = false
    Promise.all([
      api.get('/brokers').catch(() => []),
      api.get('/positions').catch(() => []),
      // FIX (bug del audit user): el endpoint correcto es /auth/investor-profile
      // (estaba puesto /investor-profile antes → 404 → siempre hasProfile=false).
      // El backend devuelve {} si no hay perfil o el JSON del perfil si lo hay.
      api.get('/auth/investor-profile').catch(() => null),
    ]).then(([brokers, positions, profile]) => {
      if (cancelled) return
      const hasBroker = Array.isArray(brokers) && brokers.length > 0
      // FIX (reportado por user): el backend auto-crea una position cash
      // (is_cash=1, asset = ARS/USD/USDT según moneda del broker) cada vez
      // que se crea un broker — para que el botón "Depositar" aparezca
      // sin obligar al user a cargar la cash manualmente. Esa posición
      // NO es una "operación real" del user, por eso la filtramos del
      // check. "Primera operación" = primera posición no-cash cargada.
      const hasPosition = Array.isArray(positions) && positions.some((p) => !p.is_cash)
      // El endpoint devuelve {} cuando no hay perfil, así que checkeamos keys.
      // Si tiene cualquier respuesta válida del quiz (horizonte, tolerancia, etc.)
      // marcamos como completado.
      const hasProfile = profile && typeof profile === 'object' &&
                         Object.keys(profile).length > 0
      setState((s) => ({
        ...s,
        hasBroker,
        hasPosition,
        hasProfile: !!hasProfile,
        hasAI: isAIDiscovered(),  // re-leer flag local también acá
        loaded: true,
      }))
    })
    return () => { cancelled = true }
  }, [])

  // Fetch inicial + cada vez que location cambia a / (vuelve a Home) o cuando
  // refreshTick se incrementa por un evento externo.
  useEffect(() => {
    if (dismissed) return
    const cleanup = fetchState()
    return cleanup
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dismissed, location.pathname, refreshTick])

  // Track view solo en el primer load para no inflar GA con duplicados.
  useEffect(() => {
    if (state.loaded) {
      const itemsDone = [state.hasBroker, state.hasPosition, state.hasProfile, state.hasAI].filter(Boolean).length
      trackEvent('checklist_viewed', { items_done: itemsDone })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.loaded])

  if (dismissed) return null
  if (!state.loaded) return null  // Skeleton/empty mientras carga — no flash

  const items = [
    {
      id: 'broker',
      done: state.hasBroker,
      Icon: Briefcase,
      title: 'Sumá tu primer broker',
      desc: 'Cocos, IOL, Schwab, Binance — donde tengas tu plata.',
      cta: 'Agregar',
      // /posiciones es ahora el hogar del BrokerManager (movido desde /config
      // hace tiempo). En desktop, cuando no hay brokers, Positions muestra
      // BrokerManager con su botón "+ Agregar broker" arriba del EmptyState.
      onClick: () => navigate('/posiciones'),
    },
    {
      id: 'position',
      done: state.hasPosition,
      Icon: PlusCircle,
      title: 'Cargá tu primera operación',
      desc: 'Importá CSV o agregá manual. Empezás a ver tu P&L real.',
      cta: state.hasBroker ? 'Cargar' : 'Sumá broker primero',
      onClick: () => navigate(state.hasBroker ? '/posiciones' : '/config'),
      disabled: !state.hasBroker,
    },
    {
      id: 'ai',
      done: state.hasAI,
      Icon: Bot,
      title: 'Probá el Coach IA',
      desc: 'Pregúntale sobre tu cartera. Análisis con tus datos reales.',
      cta: 'Abrir',
      onClick: () => coachDrawer?.open?.(),
    },
    {
      id: 'profile',
      done: state.hasProfile,
      Icon: Brain,
      title: 'Quiz de perfil inversor',
      desc: '7 preguntas. Mejora análisis IA con tu horizonte y tolerancia.',
      cta: 'Hacer quiz',
      onClick: () => navigate('/perfil-inversor'),
    },
  ]

  const doneCount = items.filter((it) => it.done).length
  const allDone = doneCount === items.length

  // Si está todo completo y el user no ha cerrado manualmente, lo ocultamos
  // pero NO marcamos dismissed (que vuelva a aparecer si el user borra broker
  // por ejemplo). Solo silenciamos durante esta sesión.
  if (allDone) return null

  function handleItemClick(item) {
    if (item.disabled) return
    trackEvent('checklist_item_clicked', { item: item.id })
    track('checklist_item_clicked', { item: item.id })
    item.onClick()
  }

  function handleDismiss() {
    trackEvent('checklist_dismissed', { items_done: doneCount })
    track('checklist_dismissed', { items_done: doneCount })
    try { localStorage.setItem(CHECKLIST_DISMISSED_KEY, '1') } catch {}
    setDismissed(true)
  }

  return (
    <section className="relative border border-data-violet/30 bg-data-violet/[0.04] rounded-lg p-4 sm:p-5 mb-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-start gap-3 min-w-0">
          <div className="w-9 h-9 rounded bg-data-violet/15 flex items-center justify-center text-data-violet flex-shrink-0">
            <Sparkles size={16} strokeWidth={1.75} />
          </div>
          <div className="min-w-0">
            <h2 className="text-base sm:text-lg font-semibold text-ink-0 mb-0.5">
              Tu setup en Rendi
            </h2>
            <p className="text-xs sm:text-sm text-ink-2 leading-relaxed">
              {doneCount} de {items.length} listos · faltan {items.length - doneCount} para sacarle todo el jugo.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Cerrar checklist"
          className="text-ink-3 hover:text-ink-1 transition-colors p-1 -mr-1 -mt-1"
        >
          <X size={16} strokeWidth={1.75} />
        </button>
      </div>

      {/* Progress mini */}
      <div className="mb-4">
        <div className="h-1 bg-bg-2 rounded-full overflow-hidden">
          <div
            className="h-full bg-data-violet transition-all duration-500"
            style={{ width: `${(doneCount / items.length) * 100}%` }}
          />
        </div>
      </div>

      {/* Items */}
      <ul className="space-y-2">
        {items.map((item) => {
          const isDone = item.done
          return (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => handleItemClick(item)}
                disabled={item.disabled || isDone}
                className={`w-full flex items-center gap-3 p-3 border rounded text-left transition-all ${
                  isDone
                    ? 'border-rendi-pos/30 bg-rendi-pos/[0.04] cursor-default'
                    : item.disabled
                      ? 'border-line/40 bg-bg-1/40 cursor-not-allowed opacity-60'
                      : 'border-line hover:border-line-3 hover:bg-bg-2/40 cursor-pointer group'
                }`}
              >
                {/* Check icon */}
                <div className="flex-shrink-0">
                  {isDone ? (
                    <CheckCircle2 size={18} strokeWidth={2} className="text-rendi-pos" />
                  ) : (
                    <Circle size={18} strokeWidth={1.5} className="text-ink-3" />
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <h3 className={`text-sm font-medium leading-tight ${isDone ? 'text-ink-2 line-through' : 'text-ink-0'}`}>
                    {item.title}
                  </h3>
                  {!isDone && (
                    <p className="text-xs text-ink-3 leading-relaxed mt-0.5">{item.desc}</p>
                  )}
                </div>

                {/* CTA */}
                {!isDone && (
                  <div className={`flex-shrink-0 inline-flex items-center gap-1 text-xs font-medium ${
                    item.disabled ? 'text-ink-3' : 'text-data-violet group-hover:translate-x-0.5 transition-transform'
                  }`}>
                    {item.cta}
                    {!item.disabled && <ArrowRight size={12} strokeWidth={2} />}
                  </div>
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
