// AICoach — chat tiered: Free/Plus solo preguntas pre-armadas, Pro chat libre.
// ═══════════════════════════════════════════════════════════════════════════
// Decisión de producto (chat tiered post-Ola 3 audit):
// - Free/Plus: SOLO eligen entre 12 preguntas pre-armadas (whitelist). NO
//   pueden tipear libre. Cuota 6/sem (rolling 7d) compartida con analyses.
//   Razón: control de costos + diferenciación clara para upgrade a Pro.
// - Pro/Admin: TEXTO LIBRE + chips como sugerencia. Cuota 60/sem.
//
// Backend valida la whitelist server-side (gating /api/ai/chat) — el frontend
// solo aplica feature flag visual. Si Free intenta tipear, el botón Enviar
// no aparece. Si por algún bug envía igual, el backend devuelve 403.
//
// Si el user quiere análisis profundo de algo específico, el botón ✦ en
// cada sección del producto (AskAIAbout) le da contextual analysis con
// el tono research-note.

import { useState, useRef, useEffect } from 'react'
import { Sparkles, AlertCircle, RotateCcw, Send, Lock, TrendingUp, TrendingDown, AlertTriangle, Activity, Volume2, Pause, Loader2 } from 'lucide-react'
import { api } from '../utils/api'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { useAuth } from '../contexts/AuthContext'
import { useAdvisorContext } from '../contexts/AdvisorContext'
import { trackEvent } from '../utils/analytics'
import { markAIDiscovered } from './ai/AIDiscoveryBanner'
import UpgradePromoCard from './ai/UpgradePromoCard'
import { Link } from 'react-router-dom'
import { useVoz } from '../contexts/VozContext'
import { contadorCorto, restantesTexto, costoDeEscuchar, avisoDeCuota, fechaLegible } from '../utils/cuotaTexto'

// Preguntas por defecto — se usan si el caller no pasa `suggested`.
// Insights genera dinámicamente preguntas data-driven basadas en el
// snapshot real (drawdown actual, win rate, concentración, etc.) y
// puede sumar hasta 12.
// Las 12 deben matchear la _FREE_QUESTIONS_WHITELIST del backend
// (case-insensitive, NFKC). Si cambiás una acá, cambiá también allá.
// Slots #5 y #8 introducidos en Pack A v2 — disparan get_value_scorecard y
// get_earnings_history respectivamente. Buscan que el user descubra
// orgánicamente las nuevas tools de mercado al elegir el chip.
const DEFAULT_SUGGESTED = [
  '¿Cómo está mi portfolio en general?',
  '¿Qué riesgos detectás en mi cartera?',
  '¿Mi nivel de concentración es elevado?',
  '¿Cómo evalúo mi win rate?',
  '¿Está cara mi posición más grande?',
  '¿Detectás algún sesgo en mi forma de operar?',
  '¿Mi exposure por sector/región está equilibrado?',
  '¿Cuándo reportan earnings los activos de mi cartera?',
  'Si tuvieras que mejorar UNA cosa de mi cartera, ¿cuál sería?',
  '¿Cómo voy vs el S&P 500?',
  '¿Le estoy ganando a la inflación argentina?',
  '¿Qué activo es el que más riesgo me agrega?',
]

// Chips del ASESOR en su propio nivel (book-mode): preguntas sobre el LIBRO,
// no sobre una cartera. No necesitan whitelist — el tier advisor tiene chat
// libre (es premium); son solo sugerencias de arranque.
const ADVISOR_SUGGESTED = [
  '¿Cómo viene mi libro en general?',
  '¿Qué cliente necesita mi atención hoy?',
  '¿Qué clientes tienen plata sin invertir?',
  '¿Quién está más concentrado en un solo activo?',
  '¿Qué activo le está haciendo perder plata a más clientes?',
  '¿Cómo está repartido el libro entre mis clientes?',
  '¿Qué cliente rindió mejor y cuál peor?',
  'Armame un resumen del libro para una reunión',
]

// stripMarkdown vive en utils/stripMarkdown.js (testeable sin la cadena de
// imports de React; ver B-14 del audit IA #2 — el regex viejo mutilaba
// aritmética con asteriscos).
import { stripMarkdown } from '../utils/stripMarkdown'
import { parseStructured } from '../utils/aiStructured'
import AIBlocks from './ai/AIBlocks'

// Tonos del bloque estructurado (v2: veredicto = banda con ícono y gradiente
// lateral; stats = cards con lavado de color y barra izquierda por tono).
const VERDICT_BAND = {
  pos:     { wash: 'from-rendi-pos/10',  ic: 'bg-rendi-pos/10 text-rendi-pos',   label: 'text-rendi-pos',  Icon: TrendingUp },
  warn:    { wash: 'from-rendi-warn/10', ic: 'bg-rendi-warn/10 text-rendi-warn', label: 'text-rendi-warn', Icon: AlertTriangle },
  neg:     { wash: 'from-rendi-neg/10',  ic: 'bg-rendi-neg/10 text-rendi-neg',   label: 'text-rendi-neg',  Icon: TrendingDown },
  neutral: { wash: 'from-bg-2',          ic: 'bg-bg-2 text-ink-2',               label: 'text-ink-2',      Icon: Activity },
}
const STAT_TONE = {
  pos:     { v: 'text-rendi-pos',  wash: 'from-rendi-pos/10',  bar: 'bg-rendi-pos' },
  warn:    { v: 'text-rendi-warn', wash: 'from-rendi-warn/10', bar: 'bg-rendi-warn' },
  neg:     { v: 'text-rendi-neg',  wash: 'from-rendi-neg/10',  bar: 'bg-rendi-neg' },
  neutral: { v: 'text-ink-0',      wash: '',                    bar: '' },
}

// fullHeight: modo página (/ai) — sin card-shell ni header propio (la página
// pone su chrome), mensajes flex-1 que llenan el alto disponible.
export default function AICoach({ snapshot, suggested, autoAsk, fullHeight = false }) {
  const { isPro, isAdmin, tier, loading: tierLoading } = usePlanFeatures()
  const { user } = useAuth()
  const { clientCtx } = useAdvisorContext()
  // ESTA PANTALLA NO TIENE SU PROPIA CONVERSACIÓN. Es una vista de la que vive
  // en VozContext, la misma que muestra la isla flotante. Ver el comentario de
  // `thread` allá: eran dos hilos que se copiaban al final, y por eso se
  // desincronizaban.
  const { escuchar: vozEscuchar, toggle: vozToggle,
          status: vozStatus, current: vozCurrent,
          thread: messages, ask, limpiar,
          sending, loading, paso, askError: error,
          upgradeInfo, usageDelError } = useVoz()
  // ¿El audio de ESTE mensaje está CARGADO en el reproductor?
  //
  // No alcanza con que coincida el texto: la respuesta se guarda como "actual"
  // aunque el parlante esté silenciado (para que el acompañante la tenga a
  // mano), pero en ese caso NUNCA se pidió el audio. Sin el chequeo de `url`,
  // el botón creía que ya estaba sonando y llamaba a "pausar" —que sin audio
  // cargado no hace nada—, así que tocabas Escuchar y no pasaba nada.
  // `url` la escribe speak(), o sea que sólo está cuando el audio existe.
  const esteSuena = (voz) => !!(voz && vozCurrent && vozCurrent.url && vozCurrent.text === voz.text)
  // Book-mode: el asesor en su propio nivel chatea sobre EL LIBRO (backend
  // arma el contexto server-side). Por IDENTIDAD (useAuth), no por plan
  // features — en contexto de cliente el lente es 'pro' y ahí el chat es el
  // normal de ESA cartera.
  const bookMode = user?.tier === 'advisor' && !clientCtx
  const canChatFree = isPro || isAdmin || bookMode  // chat libre = Pro/Admin/asesor
  const SUGGESTED = bookMode
    ? ADVISOR_SUGGESTED
    : (suggested && suggested.length > 0) ? suggested.slice(0, 12) : DEFAULT_SUGGESTED
  // La conversación PERSISTE al navegar (pedido de Nico: ir al Dashboard y
  // volver sin perder el chat). Se hidrata del sessionStorage y solo se borra
  // con "Nueva conversación" / "Nuevo" (reset). Ver utils/chatSession.js —
  // al modelo viaja solo la ventana final, el costo no crece.
  const [freeText, setFreeText] = useState('')
  // Usage: { chat_count, chat_limit, chat_remaining, resets_on }
  const [usage, setUsage] = useState(null)
  const scrollRef = useRef(null)
  // ¿el user está pegado al fondo? Solo auto-scrolleamos si sí (ver useEffect).
  const stickToBottomRef = useRef(true)
  // La posición sola no alcanza: el auto-scroll corre al llegar cada palabra y
  // el aviso de que el usuario se movió llega un cuadro después, así que el
  // tirón gana la carrera. Escuchamos también la INTENCIÓN (rueda o dedo).
  const tomoElControlRef = useRef(false)
  const tomarControlDelScroll = () => {
    tomoElControlRef.current = true
    stickToBottomRef.current = false
  }
  // Ya NO se aborta el stream al desmontar. Era justo el bug: irse a otra
  // sección en medio de una respuesta la CANCELABA —y la ficha se cobraba
  // igual—. Ahora el stream lo maneja el proveedor, que no se desmonta.

  // La cuota que viene pegada a un error de cuota, para que el pie del chat
  // muestre el número nuevo sin pedirlo otra vez.
  useEffect(() => { if (usageDelError) setUsage(usageDelError) }, [usageDelError])

  // "Corregir" del ConfirmBlock enfoca el input (evento global, sin drilling).
  const freeInputRef = useRef(null)
  useEffect(() => {
    const onFocus = () => freeInputRef.current?.focus()
    window.addEventListener('rendi:chat-focus', onFocus)
    return () => window.removeEventListener('rendi:chat-focus', onFocus)
  }, [])

  // Cargar cuota inicial — solo lectura, sin gating front (el server tiene la
  // verdad). Si falla, no rompemos UX — el server devolverá 429 si excede.
  useEffect(() => {
    let cancelled = false
    api.get('/ai/usage').then(u => {
      if (!cancelled) setUsage(u)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  // Auto-scroll al final SOLO si el user está pegado al fondo. Durante el
  // streaming los mensajes cambian en cada token; si el user scrolleó para
  // arriba a leer el principio, NO lo forzamos abajo (antes cada token lo
  // tiraba al final y no podía leer hasta que terminaba de escribir).
  useEffect(() => {
    if (scrollRef.current && stickToBottomRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  // Auto-envío de pregunta pre-cargada (ej. botón ✦ "Analizar" de otra
  // pantalla). Se dispara una sola vez al montar, cuando ya hay snapshot.
  // Con la conversación persistida, la pregunta se APPENDEA al chat en curso
  // (antes exigía messages.length === 0 → el deep-link se perdía si volvías
  // con una conversación restaurada). La pregunta debe estar whitelisted o 403.
  const autoAskedRef = useRef(false)
  useEffect(() => {
    if (autoAsk && snapshot && !autoAskedRef.current) {
      autoAskedRef.current = true
      send(autoAsk)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoAsk, snapshot])

  // Mandar la pregunta. Todo el trabajo —el streaming, el hilo, el audio, las
  // tarjetas, los errores— lo hace el proveedor: acá sólo se pasa el texto.
  //
  // ANTES esto eran 180 líneas que hacían exactamente lo mismo que `ask()` del
  // proveedor: acumular los pedacitos, pintar la burbuja, parsear el bloque,
  // pegar el audio, decidir el autoplay. Dos copias de la misma función es
  // como se desincronizaban las dos pantallas.
  //
  // El `snapshot` se pasa porque en el modo LIBRO del asesor lo arma la página
  // (la cuenta del asesor está vacía; el contexto es el libro de sus clientes).
  // En el uso normal el proveedor lo resuelve solo.
  function send(text) {
    if (!snapshot) return          // la página todavía está armando la foto
    stickToBottomRef.current = true   // pregunta nueva → pegados al fondo
    tomoElControlRef.current = false
    trackEvent('ai_chat_sent', { is_freeform: !!(isPro || isAdmin), tier })
    const _q = (text || '').toLowerCase()
    if (_q.includes('s&p') || _q.includes('inflación') || _q.includes('inflacion')) {
      trackEvent('ai_benchmark_question', { tier })
    }
    // Marca el Coach como "descubierto" — lo lee la checklist de Home.
    markAIDiscovered()
    ask(text, { snapshot })
  }

  function handleFreeSubmit(e) {
    e.preventDefault()
    // El input ahora es para TODOS: Pro = chat libre; Free/Plus = registrar
    // operaciones ("compré 2000 USD de BTC a 65.000"). El gate del CONTENIDO
    // es server-side (whitelist + detector de intención de registro) — si un
    // Free manda otra cosa, el 403 del server trae la card de upgrade.
    const text = freeText.trim()
    if (!text) return
    setFreeText('')
    send(text)
  }

  function reset() {
    limpiar()
  }

  // Cuál chips mostrar: si todavía no hay mensajes, las 4-6 iniciales.
  // Si ya hubo intercambio, las restantes (las que no preguntó aún).
  const askedQuestions = new Set(
    messages.filter(m => m.role === 'user').map(m => m.content)
  )
  const availableQuestions = SUGGESTED.filter(q => !askedQuestions.has(q))

  return (
    <div className={fullHeight
      ? 'flex flex-col h-full min-h-0'
      : 'bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl overflow-hidden flex flex-col'}>
      {/* Header — solo en modo embebido; la página /ai trae su propio chrome */}
      {!fullHeight && (
      <div className="flex items-center justify-between px-4 py-3 border-b border-line/70 dark:border-line/40">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-sm bg-bg-3 border border-line">
            <Sparkles size={16} strokeWidth={1.5} className="text-rendi-accent" />
          </div>
          <div>
            <h2 className="font-semibold text-ink-0">
              Coach IA
              {canChatFree && (
                <span className="ml-2 text-[12.5px] text-data-violet border border-data-violet/40 bg-data-violet/5 px-1.5 py-0.5 rounded-sm align-middle font-medium">
                  Pro · libre
                </span>
              )}
            </h2>
            <p className="text-[11px] text-ink-3">
              {canChatFree
                ? 'Preguntale lo que quieras sobre tu cartera'
                : 'Preguntas con contexto de tu cartera'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Cuota — visible para todos los tiers cuando ya cargó */}
          {usage && usage.chat_limit > 0 && (
            <span
              className="text-[10px] font-mono text-ink-3 tabular hidden sm:inline"
              title={costoDeEscuchar(usage) + (usage.resets_on ? ` Se renueva el ${fechaLegible(usage.resets_on)}.` : '')}
            >
              {contadorCorto(usage)}
            </span>
          )}
          {messages.length > 0 && (
            <button
              onClick={reset}
              className="text-xs text-ink-3 hover:text-ink-1 dark:hover:text-ink-0 flex items-center gap-1"
              title="Empezar de nuevo"
              aria-label="Empezar conversación de nuevo"
            >
              <RotateCcw size={12} /> Nuevo
            </button>
          )}
        </div>
      </div>
      )}

      {/* Mensajes */}
      <div
        ref={scrollRef}
        onScroll={(e) => {
          const el = e.currentTarget
          // pegado al fondo si está a menos de 80px del final
          const abajo = (el.scrollHeight - el.scrollTop - el.clientHeight) < 80
          if (abajo) tomoElControlRef.current = false
          stickToBottomRef.current = abajo && !tomoElControlRef.current
        }}
        onWheel={tomarControlDelScroll}
        onTouchMove={tomarControlDelScroll}
        className={`overflow-y-auto px-4 py-3 space-y-4 ${
          messages.length === 0 && fullHeight
            ? ''                                     /* vacío: hero+chips juntos, sin estirar */
            : 'flex-1'
        } ${fullHeight ? 'min-h-0' : 'max-h-[420px] min-h-[180px]'}`}
      >
        {/* Empty state — hero de bienvenida (clean pass 2026-07) */}
        {messages.length === 0 && !loading && (
          <div className="text-center pt-6 pb-2">
            <div className="w-12 h-12 rounded-2xl mx-auto grid place-items-center text-white text-xl"
              style={{ background: 'linear-gradient(135deg, #9d8cff, #4bd0e8)' }}>✦</div>
            <p className="text-[22px] font-semibold text-ink-0 tracking-tight mt-3 mb-1.5">
              ¿Qué querés saber de tu plata?
            </p>
            <p className="text-[13.5px] text-ink-2 max-w-md mx-auto">
              {bookMode ? 'Respondo mirando las carteras de todos tus clientes.' : 'Respondo mirando tus posiciones, tu historial y el mercado de hoy.'}
              También puedo <b className="text-ink-1">registrar operaciones</b> si me las dictás.
            </p>
          </div>
        )}

        {/* Mensajes — user: burbuja violeta a la derecha; asistente: avatar ✦ +
            respuesta ESTRUCTURADA (veredicto + titular + prosa + tarjetas +
            fuentes + repreguntas) cuando el modelo emite el bloque ---RENDI---;
            fallback transparente a texto plano si no viene (clean pass 2026-07). */}
        {messages.map((m, i) => {
          if (m.role === 'user') {
            return (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] bg-data-violet/12 border border-data-violet/30 text-ink-0 rounded-2xl rounded-br-md px-4 py-2.5 text-[14px] leading-relaxed whitespace-pre-wrap">
                  {m.content}
                </div>
              </div>
            )
          }
          const { prose, meta } = parseStructured(m.content)
          const isLastMsg = i === messages.length - 1
          return (
            <div key={i} className="flex items-start gap-3">
              <div className="w-7 h-7 rounded-lg grid place-items-center text-white text-[12px] flex-none mt-0.5"
                style={{ background: 'linear-gradient(135deg, #9d8cff, #4bd0e8)' }}>✦</div>
              <div className="flex-1 min-w-0 pt-0.5">
                {(meta?.verdict || meta?.headline) && (() => {
                  const band = VERDICT_BAND[meta.tone] || VERDICT_BAND.neutral
                  const BandIcon = band.Icon
                  return (
                    <div className={`flex items-center gap-3 rounded-xl border border-line px-3.5 py-2.5 mb-3 bg-gradient-to-r ${band.wash} to-transparent`}>
                      <span className={`w-8 h-8 rounded-lg grid place-items-center flex-none ${band.ic}`}>
                        <BandIcon size={16} strokeWidth={1.75} aria-hidden="true" />
                      </span>
                      <div className="min-w-0">
                        {meta.verdict && (
                          <div className={`text-[10.5px] font-bold tracking-[0.07em] uppercase ${band.label}`}>{meta.verdict}</div>
                        )}
                        {meta.headline && (
                          <div className="text-[14px] font-semibold text-ink-0 leading-snug">{meta.headline}</div>
                        )}
                      </div>
                    </div>
                  )
                })()}
                <div className="text-[14.5px] text-ink-1 leading-relaxed whitespace-pre-wrap">{prose}</div>
                {meta?.stats?.length > 0 && (
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3">
                    {meta.stats.map((s, k) => {
                      const t = STAT_TONE[s.t] || STAT_TONE.neutral
                      return (
                        <div key={k} className={`relative overflow-hidden bg-bg-1 border border-line rounded-xl px-3.5 py-3 ${t.wash ? `bg-gradient-to-b ${t.wash} to-transparent` : ''}`}>
                          {t.bar && <span className={`absolute left-0 top-0 bottom-0 w-[3px] rounded-r ${t.bar}`} aria-hidden />}
                          <div className="text-[11px] text-ink-2 font-semibold mb-1.5">{s.l}</div>
                          <div className={`text-[17px] font-bold num tabular leading-tight ${t.v}`}>{s.v}</div>
                        </div>
                      )
                    })}
                  </div>
                )}
                {meta?.blocks?.length > 0 && (
                  <AIBlocks
                    blocks={meta.blocks}
                    onSendMessage={send}
                    interactive={isLastMsg && !loading && !sending}
                  />
                )}
                {/* ESCUCHAR. Va acá, debajo de la respuesta, porque es donde el
                    usuario está mirando: la burbujita flotante existe para
                    cuando te vas a otra pantalla, no para descubrir la función.
                    Aparece en TODA respuesta que tenga audio, así se puede
                    volver a escuchar cualquiera, no sólo la última. */}
                {m.voz && (
                  <button
                    type="button"
                    onClick={() => (esteSuena(m.voz) ? vozToggle() : vozEscuchar(m.voz))}
                    className={`inline-flex items-center gap-1.5 mt-2.5 rounded-full border px-2.5 py-1
                      text-[11.5px] font-medium transition-colors ${
                        esteSuena(m.voz)
                          ? 'border-data-violet/45 bg-data-violet/[0.12] text-data-violet'
                          : 'border-line text-ink-2 hover:text-ink-0 hover:border-ink-3'}`}
                  >
                    {vozStatus === 'preparing' && esteSuena(m.voz)
                      ? <><Loader2 size={12} className="animate-spin" aria-hidden="true" /> Preparando…</>
                      : vozStatus === 'playing' && esteSuena(m.voz)
                        ? <><Pause size={12} aria-hidden="true" /> Pausar</>
                        : <><Volume2 size={12} aria-hidden="true" /> Escuchar</>}
                  </button>
                )}
                {meta?.sources?.length > 0 && (
                  <div className="flex items-center gap-1.5 mt-2.5 flex-wrap text-[11px] text-ink-3">
                    <span>Basado en</span>
                    {meta.sources.map((s, k) => (
                      <span key={k} className="bg-bg-1 border border-line/60 rounded-full px-2 py-0.5">{s}</span>
                    ))}
                  </div>
                )}
                {/* Repreguntas del modelo — solo en el último mensaje, y solo
                    para tiers con chat libre (Free mandaría texto no-whitelisted
                    → 403; su prompt tampoco las pide). */}
                {isLastMsg && !loading && !sending && canChatFree && meta?.followups?.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {meta.followups.map((f, k) => (
                      <button key={k} type="button" onClick={() => send(f)}
                        className="text-[12.5px] px-3 py-1.5 border border-data-violet/30 text-data-violet hover:bg-data-violet/10 rounded-full transition text-left">
                        {f}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )
        })}

        {/* Los puntitos, y al lado QUÉ está haciendo. Tres puntos rebotando
            durante 15 segundos no dicen nada; "Buscando los precios de hoy" sí,
            y la misma espera se hace corta cuando se entiende en qué se va el
            tiempo. La frase la manda el backend (_PASOS_HUMANOS en main.py). */}
        {loading && (
          <div className="flex justify-start items-center gap-2.5">
            <div className="bg-bg-2 dark:bg-bg-2/50 rounded-2xl rounded-bl-sm px-4 py-2.5">
              <div className="flex gap-1.5">
                <span className="w-1.5 h-1.5 bg-ink-3 dark:bg-bg-20 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-ink-3 dark:bg-bg-20 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-ink-3 dark:bg-bg-20 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
            {paso && <span className="text-[12.5px] text-ink-3">{paso}…</span>}
          </div>
        )}

        {/* Upgrade promo: cuando hubo 429 con upgrade.available=true,
            reemplaza el banner rojo con la card promocional. Tono explicativo
            + CTA a /planes. Si NO hay upgrade (ej. error 500 genérico),
            cae al banner rojo de abajo. */}
        {upgradeInfo && !loading && (
          <UpgradePromoCard
            usage={usage}
            upgrade={upgradeInfo}
            kind="chat"
            source="coach_drawer_429"
          />
        )}

        {error && !upgradeInfo && (
          <div className="flex items-start gap-2 p-2.5 bg-red-500/10 border border-red-500/30 rounded-md text-xs text-red-600 dark:text-red-400">
            <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
            <span className="break-all">{error}</span>
          </div>
        )}
      </div>

      {/* Chips de preguntas — siempre visibles abajo, NO hay input libre.
          Scrolleable cuando son muchas (Insights genera hasta 12 data-driven). */}
      {availableQuestions.length > 0 && messages.length === 0 && (
        /* Estado inicial: chips como CARDS en grilla (clean pass 2026-07) */
        <div className="px-4 pb-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 max-h-[240px] overflow-y-auto pr-1">
            {availableQuestions.map(q => (
              <button
                key={q}
                onClick={() => send(q)}
                disabled={loading || sending}
                className="flex items-start gap-2.5 text-left bg-bg-1 hover:bg-bg-2 border border-line hover:border-data-violet/40 rounded-xl px-3.5 py-3 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <span className="w-6 h-6 rounded-lg bg-data-violet/12 text-data-violet grid place-items-center flex-none text-[11px]">✦</span>
                <span className="text-[13px] text-ink-1 font-medium leading-snug">{q}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      {availableQuestions.length > 0 && messages.length > 0 && (
        /* Con conversación en curso: chips compactos como repreguntas */
        <div className="border-t border-line/40 px-4 py-2.5">
          <div className="flex flex-wrap gap-1.5 max-h-[104px] overflow-y-auto pr-1">
            {availableQuestions.map(q => (
              <button
                key={q}
                onClick={() => send(q)}
                disabled={loading || sending}
                className="text-[12.5px] px-3 py-1.5 border border-data-violet/30 text-data-violet hover:bg-data-violet/10 rounded-full transition disabled:opacity-40 disabled:cursor-not-allowed text-left"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {availableQuestions.length === 0 && messages.length > 0 && !canChatFree && (
        <div className="border-t border-line/70 dark:border-line/40 px-3 py-3 bg-bg-1/40 text-center">
          <p className="text-xs text-ink-3 mb-2">Ya recorriste todas las preguntas sugeridas.</p>
          <button
            onClick={reset}
            className="text-xs text-rendi-accent hover:underline inline-flex items-center gap-1"
          >
            <RotateCcw size={11} /> Empezar de nuevo
          </button>
        </div>
      )}

      {/* Input libre — SOLO Pro/Admin. Free/Plus ven los chips o el upsell. */}
      {/* Input de texto para TODOS los tiers: Pro = chat libre; Free/Plus =
          registrar operaciones dictadas ("compré 2000 USD de BTC a 65.000").
          El gate del contenido es server-side (whitelist + intención de
          registro) — acá solo cambia el placeholder por tier. */}
      <div className="border-t border-line/40 px-4 py-3 mt-auto">
        {/* AVISO DE CUOTA. Aparece SÓLO cuando queda poco (2 consultas, o al
            agotarse en Free, que tiene una sola): un cartel permanente se
            vuelve decorado y deja de leerse. El atajo a Planes va sólo si hay
            adónde ir — a un Pro, que ya está en el techo, ofrecerle "mejorá tu
            plan" es ruido; a ése se le dice cuándo se le renueva y nada más. */}
        {(() => {
          const av = avisoDeCuota(usage)
          if (!av) return null
          return (
            <div className={`flex items-center justify-between gap-3 mb-2 rounded-lg border px-3 py-2 text-[12px] ${
              av.agotado ? 'border-data-violet/40 bg-data-violet/[0.10] text-ink-1'
                         : 'border-line bg-bg-1 text-ink-2'}`}>
              <span>{av.texto}</span>
              {av.cta && (
                <Link to="/planes"
                  className="flex-none font-semibold text-data-violet hover:underline underline-offset-2 whitespace-nowrap">
                  Ver planes →
                </Link>
              )}
            </div>
          )
        })()}
        <form
          onSubmit={handleFreeSubmit}
          className="flex items-center gap-2.5 bg-bg-1 border border-line focus-within:border-data-violet/50 rounded-2xl pl-4 pr-2 py-1.5 transition-colors"
        >
          <input
            type="text"
            ref={freeInputRef}
            value={freeText}
            onChange={e => setFreeText(e.target.value)}
            disabled={loading || sending}
            placeholder={canChatFree
              ? 'Preguntale a Rendi AI sobre tu cartera…'
              : 'Registrá: "compré 2000 USD de BTC" o "deposité 600.000 pesos en Balanz"'}
            className="flex-1 bg-transparent text-[14px] text-ink-0 placeholder:text-ink-3 py-2 focus:outline-none disabled:opacity-50"
            maxLength={500}
            aria-label={canChatFree ? 'Pregunta libre a Rendi AI' : 'Registrar una operación con Rendi AI'}
          />
          <button
            type="submit"
            disabled={loading || sending || !freeText.trim()}
            className="bg-data-violet hover:bg-data-violet/90 text-white rounded-xl w-9 h-9 transition-colors disabled:opacity-40 disabled:cursor-not-allowed inline-flex items-center justify-center flex-none"
            title="Enviar"
            aria-label="Enviar"
          >
            <Send size={15} strokeWidth={2} />
          </button>
        </form>
        <div className="flex items-center justify-between mt-2 px-1 text-[11.5px] text-ink-3">
          <span>Rendi AI puede equivocarse — no es asesoramiento financiero.</span>
          {usage && usage.chat_limit > 0 && (
            <span className="tabular num" title={costoDeEscuchar(usage)}>
              {restantesTexto(usage)}
            </span>
          )}
        </div>
      </div>

      {/* Upsell Free/Plus → Pro: visible cuando NO tiene chat libre. Muestra
          qué desbloquea Pro sin ser intrusivo (un slot debajo de los chips). */}
      {!canChatFree && !tierLoading && (
        <div className="border-t border-line/70 dark:border-line/40 px-3 py-2 bg-data-violet/5 flex items-center gap-2">
          <Lock size={11} className="text-data-violet flex-shrink-0" />
          <p className="text-[10px] text-ink-2 leading-snug flex-1">
            Con tu plan podés registrar operaciones acá. ¿Análisis y preguntas libres? Eso es Pro (40 consultas/sem).
          </p>
          <a
            href="/planes"
            className="text-[12px] text-data-violet hover:underline whitespace-nowrap font-medium"
          >
            Ver Pro →
          </a>
        </div>
      )}

    </div>
  )
}
