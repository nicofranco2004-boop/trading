// OnboardingChecklist — checklist persistente en Home para users sin
// completar todos los pasos clave de configuración.
// ════════════════════════════════════════════════════════════════════════════
// Complementa el wizard /onboarding (que se ejecuta una sola vez post-signup)
// con una guía visible "en frío" durante los primeros días/semanas del user.
//
// Dos grupos (pedido de Nico, 2026-10-19: que entrar a Rendi se vuelva hábito,
// y para eso lo primero es tenerla a mano y que le lleguen avisos):
//
//   Para tener Rendi a mano
//   1. Agregá Rendi a tu celular — se abrió alguna vez desde el ícono del inicio
//      (servidor: /api/primeros-pasos.app_instalada, que sale del uso que anota
//      utils/uso.js) o está abierta así ahora mismo.
//   2. Activá las notificaciones — algún dispositivo suscripto (servidor).
//   3. Armá tu primera alerta    — al menos una alerta (servidor).
//
//   Para tener tu cartera bien (los de antes)
//   4. Importá tu historial    — count(imports) > 0            (Paso 1 de cartera)
//   5. Conocé tus posiciones   — flag 'rendi_positions_discovered' (Paso 2: por
//                                DESCUBRIMIENTO, no por cargar — así el import no
//                                lo tilda solo. Ver utils/positionsDiscovered)
//   6. Probá Mervall-E AI      — flag localStorage 'rendi_ai_discovered'
//   7. Quiz de perfil inversor — investor_profile != null
//
// Los pasos 1 y 2 son SUGERENCIAS, no obligaciones: tienen «Ahora no», que los
// manda al final como «para después» (con «Retomar») y cuenta como resuelto para
// que la lista pueda terminarse sin hacerlos. Pasados DIAS_PARA_VOLVER días el
// paso vuelve solo a su lugar, como sugerencia otra vez (pedido de Nico: «que
// cada 3-4 días se lo vuelva a mostrar»); otro «Ahora no» lo esconde otros tantos.
// Se guarda en ESTE navegador a propósito: quien lo deja para después en la
// compu lo vuelve a ver en el celular, que es donde se hace. Y nunca se pide el
// permiso del navegador sin que la persona toque «Activar».
//
// Los tres pasos de «Para tener Rendi a mano» se VAN de la lista apenas se
// hacen (no quedan tachados): son sugerencias, y una sugerencia cumplida no
// tiene nada más que decir. Los de la cartera siguen quedando tachados.
//
// Si las notificaciones no se pueden activar acá (iPhone sin Rendi en el
// inicio, permiso bloqueado), el paso abre el cartel compartido
// AvisoNotificaciones con el porqué y el botón al paso a paso de instalar.
//
// El componente:
//   - No se monta si el user ya resolvió todos los items (silent dismiss)
//   - Tiene botón "Cerrar permanentemente" (flag localStorage) para users
//     que prefieren ocultarlo
//   - Cada item incompleto es link al lugar donde se completa
//
// Tracking:
//   - checklist_viewed (al montarse)
//   - checklist_item_clicked { item }
//   - checklist_paso_omitido { item }
//   - checklist_push_activado / checklist_resumen_activado
//   - checklist_dismissed (cierre manual)

import { useEffect, useState, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  CheckCircle2, Circle, X, PlusCircle, Brain, Bot,
  ArrowRight, Sparkles, Upload, Smartphone, Bell, BellRing,
} from 'lucide-react'
import { api } from '../../utils/api'
import { trackEvent } from '../../utils/analytics'
import { track } from '../../utils/track'
import { useCoachDrawer } from '../../contexts/CoachDrawerContext'
import { isAIDiscovered, AI_DISCOVERY_KEY } from '../ai/AIDiscoveryBanner'
import { isPositionsDiscovered, POSITIONS_DISCOVERED_KEY } from '../../utils/positionsDiscovered'
import { useAdvisorContext } from '../../contexts/AdvisorContext'
import { usePushNotifications } from '../../hooks/usePushNotifications'
import { yaInstalada, instalarAhora, useHayInstalador } from '../../utils/instalarApp'
import { MENSAJE_FALLA, textoSinPush } from '../../utils/notificaciones'
import InstalarAppModal, { precargarFotosDeInstalar } from '../InstalarAppModal'
import AvisoNotificaciones from '../AvisoNotificaciones'
import { useToast } from '../Toast'

const CHECKLIST_DISMISSED_KEY = 'rendi_checklist_dismissed'
const OMITIDOS_KEY = 'rendi_checklist_omitidos'
export const DIAS_PARA_VOLVER = 3
const MS_PARA_VOLVER = DIAS_PARA_VOLVER * 24 * 60 * 60 * 1000

// { [paso]: cuándo tocó «Ahora no» (ms) }. Cualquier otra forma se descarta:
// el paso vuelve a mostrarse, que es lo seguro para una sugerencia.
function leerOmitidos() {
  try {
    const v = JSON.parse(localStorage.getItem(OMITIDOS_KEY) || '{}')
    return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
  } catch { return {} }
}

function guardarOmitidos(omitidos) {
  try { localStorage.setItem(OMITIDOS_KEY, JSON.stringify(omitidos)) } catch {}
}

const GRUPOS = [
  { id: 'a_mano', titulo: 'Para tener Rendi a mano' },
  { id: 'cartera', titulo: 'Para tener tu cartera bien' },
]

export default function OnboardingChecklist() {
  const { clientCtx } = useAdvisorContext()
  const navigate = useNavigate()
  const location = useLocation()
  const coachDrawer = useCoachDrawer()
  const toast = useToast()
  const push = usePushNotifications()
  const hayInstalador = useHayInstalador()
  const [instaladaAca] = useState(() => yaInstalada())
  const [state, setState] = useState({
    hasImported: null,  // hizo al menos un import (batch) → Paso 1 del setup
    // Paso 2 = DESCUBRIMIENTO: vio la pantalla de Posiciones (no carga real, ni
    // las que crea el import). Flag local, como hasAI.
    hasPositionsDiscovered: isPositionsDiscovered(),
    hasProfile: null,
    hasAI: isAIDiscovered(),
    // Lo que sabe el servidor (/api/primeros-pasos). Si no responde, los tres
    // pasos quedan sin tildar: mejor sugerir de más que dar por hecho algo.
    pasos: { app_instalada: false, dispositivos_push: 0, alertas: 0, resumen_activo: false },
    loaded: false,
  })
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(CHECKLIST_DISMISSED_KEY) === '1' } catch { return false }
  })
  const [omitidos, setOmitidos] = useState(leerOmitidos)
  const [instalarOpen, setInstalarOpen] = useState(false)
  const [verAvisoPush, setVerAvisoPush] = useState(false)
  // Recién activó las notificaciones y no tiene el resumen: se lo ofrecemos una vez.
  const [ofrecerResumen, setOfrecerResumen] = useState(false)
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
      api.get('/primeros-pasos').catch(() => null),
    ]).then(([profile, imports, pasos]) => {
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
        pasos: pasos && typeof pasos === 'object' ? { ...s.pasos, ...pasos } : s.pasos,
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

  const instalada = instaladaAca || !!state.pasos.app_instalada
  // Las fotos del paso a paso se piden por adelantado (en Safari tardan si se
  // piden recién al abrir el cartel — ver InstalarAppModal).
  useEffect(() => {
    if (state.loaded && !instalada && !dismissed) precargarFotosDeInstalar()
  }, [state.loaded, instalada, dismissed])

  const enCompu = push.plataforma === 'otro'
  const items = [
    {
      id: 'instalar',
      grupo: 'a_mano',
      seVaAlHacerse: true,
      omitible: true,
      recomendado: true,
      done: instalada,
      Icon: Smartphone,
      title: 'Agregá Rendi a tu celular',
      desc: enCompu
        ? 'Abrí rendi.finance en el celular y agregala a tu inicio: queda con su ícono, como una app.'
        : 'Queda con su ícono en tu inicio, como una app. Sin App Store ni Play Store.',
      cta: hayInstalador ? 'Instalar' : 'Ver cómo',
      onClick: async () => {
        // Chrome en Android instala con un toque; si no, el paso a paso.
        if (hayInstalador) {
          const r = await instalarAhora()
          track('instalar_app_un_toque', { resultado: r, origen: 'lista' })
          if (r === 'accepted' || r === 'dismissed') return
        }
        setInstalarOpen(true)
      },
    },
    {
      id: 'push',
      grupo: 'a_mano',
      seVaAlHacerse: true,
      omitible: true,
      done: state.pasos.dispositivos_push > 0 || push.subscribed,
      Icon: Bell,
      title: 'Activá las notificaciones',
      desc: 'Te avisamos al momento cuando se mueve lo que seguís, aunque no tengas Rendi abierta.',
      cta: push.loading ? 'Activando…' : 'Activar',
      onClick: activarPush,
    },
    {
      id: 'alerta',
      grupo: 'a_mano',
      seVaAlHacerse: true,
      done: state.pasos.alertas > 0,
      Icon: BellRing,
      title: 'Armá tu primera alerta',
      desc: 'Elegí un precio o un movimiento y te avisamos cuando pase.',
      cta: 'Crear',
      onClick: () => navigate('/alertas'),
    },
    // Carga de cartera en 2 pasos que NO desaparecen al hacer el primero.
    // El broker NO es un paso aparte: el import lo crea solo (importing/pipeline.py
    // auto-crea el broker referenciado en el CSV, infiriendo la moneda) y en
    // /posiciones el BrokerManager también deja crearlo inline. Antes "crear
    // broker" era un paso suelto donde mucha gente se quedaba sin llegar a importar.
    //   Paso 1 → Importaciones (historial completo por CSV, crea el broker solo)
    //   Paso 2 → Posiciones (solo las activas que tenés hoy)
    {
      id: 'import',
      grupo: 'cartera',
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
      grupo: 'cartera',
      done: state.hasPositionsDiscovered,
      Icon: PlusCircle,
      title: 'Conocé tus posiciones activas',
      desc: 'Paso 2 de 2 · Entrá a Posiciones para ver tu cartera y sumar lo que el import no haya traído.',
      cta: 'Ver',
      onClick: () => navigate('/posiciones'),
    },
    {
      id: 'ai',
      grupo: 'cartera',
      done: state.hasAI,
      Icon: Bot,
      title: 'Probá Mervall-E AI',
      desc: 'Preguntale sobre tu cartera. Análisis con tus datos reales.',
      cta: 'Abrir',
      onClick: () => coachDrawer?.open?.(),
    },
    {
      id: 'profile',
      grupo: 'cartera',
      done: state.hasProfile,
      Icon: Brain,
      title: 'Quiz de perfil inversor',
      desc: 'Unas preguntas rápidas. Mejora análisis IA con tu horizonte y tolerancia.',
      cta: 'Hacer quiz',
      onClick: () => navigate('/perfil-inversor'),
    },
  ]

  const doneCount = items.filter((it) => it.done).length
  const ahora = Date.now()
  const esOmitido = (it) => {
    const cuando = Number(omitidos[it.id])
    return !it.done && !!it.omitible && cuando > 0 && ahora - cuando < MS_PARA_VOLVER
  }
  const resueltos = items.filter((it) => it.done || esOmitido(it)).length

  // Track view solo en el primer load para no inflar GA con duplicados.
  useEffect(() => {
    if (state.loaded) trackEvent('checklist_viewed', { items_done: doneCount })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.loaded])

  async function activarPush() {
    // Acá no se puede (iPhone sin Rendi en el inicio, navegador sin soporte,
    // permiso bloqueado): en vez de un error, el cartel con qué hacer.
    if (push.motivo) { setVerAvisoPush(true); return }
    try {
      await push.subscribe()
      track('checklist_push_activado')
      setVerAvisoPush(false)
      setState((s) => ({ ...s, pasos: { ...s.pasos, dispositivos_push: (s.pasos.dispositivos_push || 0) + 1 } }))
      toast.push(enCompu
        ? 'Listo: te llegan a esta compu. Para el celular, activalas también desde ahí.'
        : 'Notificaciones activadas', { type: 'success', duration: enCompu ? 7000 : 4000 })
      if (!state.pasos.resumen_activo) setOfrecerResumen(true)
    } catch (ex) {
      // Un motivo con cartel (bloqueadas, o uno que cambió desde que se dibujó): el cartel.
      if (textoSinPush(ex?.motivo, push.plataforma)) setVerAvisoPush(true)
      else toast.push(ex?.message || MENSAJE_FALLA, { type: ex?.motivo === 'cerro-el-pedido' ? 'info' : 'error' })
    }
  }

  async function prenderResumen() {
    setOfrecerResumen(false)
    try {
      await api.patch('/market-brief/prefs', { enabled: true })
      track('checklist_resumen_activado')
      setState((s) => ({ ...s, pasos: { ...s.pasos, resumen_activo: true } }))
      toast.push('Listo: te llega cada día hábil a las 11.', { type: 'success' })
    } catch {
      toast.push('No pudimos prenderlo. Lo encontrás en Alertas → Resumen del mercado.', { type: 'error' })
    }
  }

  if (clientCtx) return null      // en la cuenta de un cliente el checklist
                                  // mezclaba estado del asesor (perfil, flags
                                  // de descubrimiento) con datos del cliente
  if (dismissed) return null
  if (!state.loaded) return null  // Skeleton/empty mientras carga — no flash

  // Si está todo resuelto y el user no ha cerrado manualmente, lo ocultamos
  // pero NO marcamos dismissed (que vuelva a aparecer si el user borra broker
  // por ejemplo). Solo silenciamos durante esta sesión. La oferta del resumen,
  // si está abierta, se deja terminar: aparece justo al resolver el último paso.
  if (resueltos === items.length && !ofrecerResumen) return null

  function handleItemClick(item) {
    if (item.disabled) return
    trackEvent('checklist_item_clicked', { item: item.id })
    track('checklist_item_clicked', { item: item.id })
    item.onClick()
  }

  function omitir(item) {
    track('checklist_paso_omitido', { item: item.id })
    const lista = { ...omitidos, [item.id]: Date.now() }
    guardarOmitidos(lista)
    setOmitidos(lista)
    if (item.id === 'push') setVerAvisoPush(false)
  }

  function retomar(item) {
    const { [item.id]: _, ...lista } = omitidos
    guardarOmitidos(lista)
    setOmitidos(lista)
  }

  function handleDismiss() {
    trackEvent('checklist_dismissed', { items_done: doneCount })
    track('checklist_dismissed', { items_done: doneCount })
    try { localStorage.setItem(CHECKLIST_DISMISSED_KEY, '1') } catch {}
    setDismissed(true)
  }

  const paraDespues = items.filter(esOmitido)

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

      {/* Oferta del resumen: una vez, justo después de activar las notificaciones */}
      {ofrecerResumen && (
        <div className="mb-4 border border-data-violet/30 bg-bg-1 rounded-lg p-3.5">
          <p className="text-sm font-medium text-ink-0 leading-snug">¿Te mandamos también el resumen del mercado?</p>
          <p className="text-xs text-ink-2 leading-relaxed mt-1">
            Cada día hábil a las 11, cuando abre la Bolsa: qué pasó con lo que tenés y qué viene hoy.
            Te llega por mail y como notificación.
          </p>
          <div className="flex gap-2 mt-3">
            <button type="button" onClick={prenderResumen}
              className="bg-data-violet hover:bg-data-violet/90 text-white text-xs font-medium rounded px-3.5 py-2 transition-colors press">
              Sí, mandámelo
            </button>
            <button type="button" onClick={() => setOfrecerResumen(false)}
              className="text-xs text-ink-2 hover:text-ink-0 px-3 py-2 transition-colors">
              No, gracias
            </button>
          </div>
        </div>
      )}

      {/* Items, por grupo */}
      {GRUPOS.map((g) => {
        const delGrupo = items.filter((it) => it.grupo === g.id && !esOmitido(it)
          && !(it.done && it.seVaAlHacerse))
        if (!delGrupo.length) return null
        return (
          <div key={g.id} className="mb-3 last:mb-0">
            <h3 className="text-xs text-ink-2 font-medium mb-2 px-0.5">{g.titulo}</h3>
            <ul className="space-y-2">
              {delGrupo.map((item) => (
                <li key={item.id}>
                  <Paso item={item} onClick={() => handleItemClick(item)}
                    onOmitir={item.omitible ? () => omitir(item) : null} />
                  {item.id === 'push' && !item.done && verAvisoPush && push.motivo && (
                    <AvisoNotificaciones motivo={push.motivo} plataforma={push.plataforma}
                      origen="lista" className="mt-2" />
                  )}
                </li>
              ))}
            </ul>
          </div>
        )
      })}

      {/* Lo que dejó para después: a la vista pero sin insistir */}
      {paraDespues.length > 0 && (
        <ul className="mt-3 pt-3 border-t border-line/60 space-y-1.5">
          {paraDespues.map((item) => (
            <li key={item.id} className="flex items-center gap-2 text-xs text-ink-3">
              <Circle size={12} strokeWidth={1.5} className="flex-shrink-0" aria-hidden="true" />
              <span className="flex-1 min-w-0 truncate">{item.title} · para después</span>
              <button type="button" onClick={() => retomar(item)}
                className="text-data-violet font-medium hover:underline flex-shrink-0">
                Retomar
              </button>
            </li>
          ))}
        </ul>
      )}

      <InstalarAppModal open={instalarOpen} onClose={() => setInstalarOpen(false)} origen="lista" />
    </section>
  )
}

function Paso({ item, onClick, onOmitir }) {
  const isDone = item.done
  return (
    // En el celular «Ahora no» va abajo, en una línea finita: al costado le
    // comía un tercio del ancho al texto y los títulos se partían en tres.
    <div className={`flex flex-col sm:flex-row sm:items-stretch border rounded transition-all ${
      isDone
        ? 'border-rendi-pos/30 bg-rendi-pos/[0.04]'
        : item.disabled
          ? 'border-line/40 bg-bg-1/40 opacity-60'
          : 'border-line hover:border-line-3 hover:bg-bg-2/40'
    }`}>
      <button
        type="button"
        onClick={onClick}
        disabled={item.disabled || isDone}
        className={`flex-1 min-w-0 flex items-center gap-3 p-3 text-left ${
          isDone ? 'cursor-default' : item.disabled ? 'cursor-not-allowed' : 'cursor-pointer group press'
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
            {item.recomendado && !isDone && (
              <span className="ml-2 align-middle text-[11px] font-medium text-data-violet bg-data-violet/10 rounded px-1.5 py-0.5">
                Recomendado
              </span>
            )}
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

      {/* «Ahora no»: los pasos que son sugerencia se pueden dejar para después */}
      {!isDone && onOmitir && (
        <button type="button" onClick={onOmitir}
          className="flex-shrink-0 px-3 py-1.5 sm:py-0 text-right sm:text-center text-[11px] text-ink-3 hover:text-ink-1 border-t sm:border-t-0 sm:border-l border-line/60 transition-colors">
          Ahora no
        </button>
      )}
    </div>
  )
}
