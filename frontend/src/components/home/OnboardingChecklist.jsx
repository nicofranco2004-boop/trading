// OnboardingChecklist — checklist persistente en Home para users sin
// completar todos los pasos clave de configuración.
// ════════════════════════════════════════════════════════════════════════════
// Complementa el wizard /onboarding (que se ejecuta una sola vez post-signup)
// con una guía visible "en frío" durante los primeros días/semanas del user.
//
// Items trackeados (el broker NO es un paso aparte: el import lo crea solo):
//   1. Importá tu historial    — count(imports) > 0            (Paso 1 de cartera)
//   2. Conocé tus posiciones   — flag 'rendi_positions_discovered' (Paso 2: por
//                                DESCUBRIMIENTO, no por cargar — así el import no
//                                lo tilda solo. Ver utils/positionsDiscovered)
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
  CheckCircle2, Circle, X, PlusCircle, Brain, Bot,
  ArrowRight, Sparkles, Upload,
} from 'lucide-react'
import { api } from '../../utils/api'
import { trackEvent } from '../../utils/analytics'
import { track } from '../../utils/track'
import { useCoachDrawer } from '../../contexts/CoachDrawerContext'
import { isAIDiscovered, AI_DISCOVERY_KEY } from '../ai/AIDiscoveryBanner'
import { isPositionsDiscovered, POSITIONS_DISCOVERED_KEY } from '../../utils/positionsDiscovered'

const CHECKLIST_DISMISSED_KEY = 'rendi_checklist_dismissed'

export default function OnboardingChecklist() {
  const navigate = useNavigate()
  const location = useLocation()
  const coachDrawer = useCoachDrawer()
  const [state, setState] = useState({
    hasImported: null,  // hizo al menos un import (batch) → Paso 1 del setup
    // Paso 2 = DESCUBRIMIENTO: vio la pantalla de Posiciones (no carga real, ni
    // las que crea el import). Flag local, como hasAI.
    hasPositionsDiscovered: isPositionsDiscovered(),
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
    function recheckFlags() {
      setState((s) => ({
        ...s,
        hasAI: isAIDiscovered(),
        hasPositionsDiscovered: isPositionsDiscovered(),
      }))
    }
    function onStorage(e) {
      if (e.key === AI_DISCOVERY_KEY || e.key === POSITIONS_DISCOVERED_KEY) recheckFlags()
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener('focus', recheckFlags)
    window.addEventListener('ai-discovered', recheckFlags)
    window.addEventListener('positions-discovered', recheckFlags)
    return () => {
      window.removeEventListener('storage', onStorage)
      window.removeEventListener('focus', recheckFlags)
      window.removeEventListener('ai-discovered', recheckFlags)
      window.removeEventListener('positions-discovered', recheckFlags)
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
      // FIX (bug del audit user): el endpoint correcto es /auth/investor-profile
      // (estaba puesto /investor-profile antes → 404 → siempre hasProfile=false).
      // El backend devuelve {} si no hay perfil o el JSON del perfil si lo hay.
      api.get('/auth/investor-profile').catch(() => null),
      // Paso 1 del setup de cartera: ¿ya hizo al menos un import? GET /imports
      // lista los batches confirmados/revertidos del user.
      api.get('/imports').catch(() => []),
    ]).then(([profile, imports]) => {
      if (cancelled) return
      const hasImported = Array.isArray(imports) && imports.length > 0
      // El endpoint devuelve {} cuando no hay perfil, así que checkeamos keys.
      // Si tiene cualquier respuesta válida del quiz (horizonte, tolerancia, etc.)
      // marcamos como completado.
      const hasProfile = profile && typeof profile === 'object' &&
                         Object.keys(profile).length > 0
      setState((s) => ({
        ...s,
        hasImported,
        hasProfile: !!hasProfile,
        hasAI: isAIDiscovered(),                       // re-leer flags locales
        hasPositionsDiscovered: isPositionsDiscovered(),
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
      const itemsDone = [state.hasImported, state.hasPositionsDiscovered, state.hasProfile, state.hasAI].filter(Boolean).length
      trackEvent('checklist_viewed', { items_done: itemsDone })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.loaded])

  if (dismissed) return null
  if (!state.loaded) return null  // Skeleton/empty mientras carga — no flash

  const items = [
    // Carga de cartera en 2 pasos que NO desaparecen al hacer el primero.
    // El broker NO es un paso aparte: el import lo crea solo (importing/pipeline.py
    // auto-crea el broker referenciado en el CSV, infiriendo la moneda) y en
    // /posiciones el BrokerManager también deja crearlo inline. Antes "crear
    // broker" era un paso suelto donde mucha gente se quedaba sin llegar a importar.
    //   Paso 1 → Importaciones (historial completo por CSV, crea el broker solo)
    //   Paso 2 → Posiciones (solo las activas que tenés hoy)
    {
      id: 'import',
      done: state.hasImported,
      Icon: Upload,
      title: 'Importá tu historial',
      desc: 'Paso 1 de 2 · Subí el CSV de tu broker. Lo creamos solo y traemos todas tus operaciones, todo de una.',
      cta: 'Importar',
      onClick: () => navigate('/imports'),
    },
    {
      // Done por DESCUBRIMIENTO (ver utils/positionsDiscovered): se tilda cuando
      // el user ve la pantalla de Posiciones, NO con las posiciones que crea el
      // import. Así importar no lo tilda solo y no hace falta cargar a mano.
      id: 'positions',
      done: state.hasPositionsDiscovered,
      Icon: PlusCircle,
      title: 'Conocé tus posiciones activas',
      desc: 'Paso 2 de 2 · Entrá a Posiciones para ver tu cartera y sumar lo que el import no haya traído.',
      cta: 'Ver',
      onClick: () => navigate('/posiciones'),
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
      desc: 'Unas preguntas rápidas. Mejora análisis IA con tu horizonte y tolerancia.',
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
                      : 'border-line hover:border-line-3 hover:bg-bg-2/40 cursor-pointer group press'
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
