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
import { Sparkles, AlertCircle, RotateCcw, Send, Lock } from 'lucide-react'
import { api } from '../utils/api'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { trackEvent } from '../utils/analytics'
import { markAIDiscovered } from './ai/AIDiscoveryBanner'
import UpgradePromoCard from './ai/UpgradePromoCard'

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

// stripMarkdown vive en utils/stripMarkdown.js (testeable sin la cadena de
// imports de React; ver B-14 del audit IA #2 — el regex viejo mutilaba
// aritmética con asteriscos).
import { stripMarkdown } from '../utils/stripMarkdown'
import { parseStructured } from '../utils/aiStructured'

// Tonos del bloque estructurado (veredicto pill + valores de las tarjetas).
const VERDICT_TONE = {
  pos:     'bg-rendi-pos/10 text-rendi-pos',
  warn:    'bg-rendi-warn/10 text-rendi-warn',
  neg:     'bg-rendi-neg/10 text-rendi-neg',
  neutral: 'bg-bg-2 text-ink-1',
}
const STAT_TONE = {
  pos:     'text-rendi-pos',
  warn:    'text-rendi-warn',
  neg:     'text-rendi-neg',
  neutral: 'text-ink-0',
}

// fullHeight: modo página (/ai) — sin card-shell ni header propio (la página
// pone su chrome), mensajes flex-1 que llenan el alto disponible.
export default function AICoach({ snapshot, suggested, autoAsk, fullHeight = false }) {
  const { isPro, isAdmin, tier, loading: tierLoading } = usePlanFeatures()
  const canChatFree = isPro || isAdmin  // chat libre = solo Pro/Admin
  const SUGGESTED = (suggested && suggested.length > 0) ? suggested.slice(0, 12) : DEFAULT_SUGGESTED
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [freeText, setFreeText] = useState('')
  // Usage: { chat_count, chat_limit, chat_remaining, resets_on }
  const [usage, setUsage] = useState(null)
  // Upgrade payload — solo se setea cuando llega un 429 con upgrade.available.
  // Si está seteado, mostramos UpgradePromoCard en lugar del banner rojo.
  const [upgradeInfo, setUpgradeInfo] = useState(null)
  const scrollRef = useRef(null)
  // ¿el user está pegado al fondo? Solo auto-scrolleamos si sí (ver useEffect).
  const stickToBottomRef = useRef(true)
  // B-5 (audit IA #2): `loading` se apaga al PRIMER token (para ocultar los
  // puntitos) → desde ahí el guard quedaba abierto durante TODO el stream y una
  // 2da pregunta mezclaba deltas en la misma burbuja + cobraba doble cuota.
  // `sending` cubre la ventana completa (hasta el finally de chatStream):
  // - sendingRef: guard SINCRÓNICO race-proof (el estado tarda un render)
  // - sending (estado): deshabilita chips/input/submit con re-render
  const sendingRef = useRef(false)
  const [sending, setSending] = useState(false)
  // Abort del stream en curso al tocar "Nuevo" o cerrar el drawer — sin esto
  // los deltas del stream viejo seguían llegando y re-poblaban una burbuja
  // fantasma sobre el chat "nuevo".
  const abortRef = useRef(null)
  useEffect(() => () => { abortRef.current?.abort() }, [])

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

  // Auto-envío de pregunta pre-cargada (ej. CTA del Coach en FirstInsight
  // post-import). Se dispara una sola vez al montar, cuando ya hay snapshot y
  // no hubo mensajes. El drawer remonta AICoach en cada apertura → el ref de
  // "ya enviado" se resetea solo. La pregunta debe estar whitelisted o 403.
  const autoAskedRef = useRef(false)
  useEffect(() => {
    if (autoAsk && snapshot && !autoAskedRef.current && messages.length === 0) {
      autoAskedRef.current = true
      send(autoAsk)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoAsk, snapshot])

  async function send(text) {
    const content = (text || '').trim()
    if (!content || loading || sendingRef.current || !snapshot) return
    sendingRef.current = true
    setSending(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl

    const userMsg = { role: 'user', content }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setLoading(true)
    setError(null)
    stickToBottomRef.current = true  // pregunta nueva → arrancamos pegados al fondo

    // Streaming: los puntitos se muestran hasta que llega el PRIMER token; a
    // partir de ahí ocultamos el loader y vamos rellenando la burbuja del
    // asistente en vivo (typewriter). `acc` acumula el texto crudo; renderizamos
    // stripMarkdown(acc) para limpiar cualquier markdown que se cuele.
    let acc = ''
    let assistantAdded = false
    const onDelta = (chunk) => {
      acc += chunk
      const clean = stripMarkdown(acc)
      if (!assistantAdded) {
        assistantAdded = true
        setLoading(false)  // ocultar puntitos: ya hay texto que mostrar
        setMessages(m => [...m, { role: 'assistant', content: clean }])
      } else {
        setMessages(m => {
          const copy = m.slice()
          copy[copy.length - 1] = { role: 'assistant', content: clean }
          return copy
        })
      }
    }
    // B-13: el turno terminó en tool_use — lo streameado era el PREÁMBULO
    // ("déjame consultar los precios…"), no la respuesta. Limpiamos la burbuja
    // y volvemos al loader mientras corren las tools; la síntesis final llega
    // en el próximo turno con su propio stream.
    const onReset = () => {
      acc = ''
      if (assistantAdded) {
        assistantAdded = false
        setMessages(m => m.slice(0, -1))
      }
      setLoading(true)
    }

    try {
      // GA4: engagement metric. No mandamos el content del mensaje (PII potential).
      trackEvent('ai_chat_sent', {
        is_freeform: !!(isPro || isAdmin),
        tier,
      })
      // M-benchmark (hipótesis de conversión): trackear la pregunta de
      // benchmark por separado — es el momento de upsell que estamos midiendo
      // (pregunta → respuesta con data real → CTA Pro → ¿upgrade?).
      const _q = content.toLowerCase()
      if (_q.includes('s&p') || _q.includes('inflación') || _q.includes('inflacion')) {
        trackEvent('ai_benchmark_question', { tier })
      }
      // Marcar Coach IA como "descubierto" — usado por OnboardingChecklist
      // en Home para detectar que el user ya probó el chat.
      markAIDiscovered()
      const res = await api.chatStream({ messages: newMessages, snapshot }, { onDelta, onReset, signal: ctrl.signal })
      // Edge: el stream cerró sin emitir texto → mostrar algo en vez de nada.
      if (!assistantAdded) {
        setMessages(m => [...m, { role: 'assistant', content: stripMarkdown(acc) || '…' }])
      }
      // El turno ESCRIBIÓ en la cartera (registro/undo): avisar a la app para
      // que Cartera y el snapshot del drawer se refresquen al instante, sin
      // que el usuario tenga que recargar a mano.
      if (res?.portfolioChanged) {
        window.dispatchEvent(new Event('rendi:portfolio-changed'))
      }
      // Refrescar cuota tras success — no es crítico, best-effort.
      api.get('/ai/usage').then(u => setUsage(u)).catch(() => {})
    } catch (e) {
      // Abort deliberado (tocó "Nuevo" o cerró el drawer): salir en silencio —
      // no es un error del usuario y reset() ya dejó el chat como corresponde.
      if (e?.name === 'AbortError' || ctrl.signal.aborted) {
        return
      }
      // Manejo de errores tier-aware. El backend devuelve `detail` de 3 formas:
      //   1. dict { error, message, usage? }  → 403 gate, 429 cuota (shape custom)
      //   2. array [{ type, loc, msg, input }] → 422 validation Pydantic
      //   3. string  → 500 genérico
      // Renderear el array Pydantic crudo es UX inaceptable (JSON técnico al
      // usuario). Detectamos cada caso y damos mensaje amigable.
      //
      // El api.js wrapper guarda el detail crudo en `err.payload.detail`
      // (línea 89 de api.js). El `e.message` que prepara el wrapper para
      // arrays Pydantic es JSON.stringify del detail — feo, no lo usamos
      // como fallback si tenemos algo mejor.
      let msg = 'No pudimos completar la consulta. Intentalo nuevamente.'
      const detail = e?.payload?.detail ?? e?.detail ?? e?.response?.data?.detail
      const status = e?.status

      // Caso especial: payload null (body no es JSON) → típicamente Vercel
      // 504 Gateway Timeout devolviendo HTML genérico cuando el backend
      // tarda > 30s. El detail vendrá undefined. Damos mensaje útil al user.
      // Síntoma reportado: pregunta sobre P/E en follow-up → tools cache
      // miss + 2-3 round-trips Anthropic → > 30s → Vercel corta.
      if (e?.truncated) {
        // B-6: el stream se cortó sin frame terminal (Vercel 30s, red móvil).
        // Antes esto se mostraba como respuesta COMPLETA; ahora avisamos y el
        // user reintenta (el mensaje parcial se remueve abajo).
        msg = 'La respuesta se cortó a mitad de camino. Volvé a intentarlo — si pasa seguido, probá una pregunta más corta.'
      } else if (!detail && (status === 504 || status === 502 || status === 503 || e?.payload === null)) {
        msg = 'El bot tardó más de lo normal en responder. Intentá una pregunta más simple, o esperá unos segundos y reintentá.'
      } else if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message) {
        // Caso 1: error estructurado del backend (gate Free, cuota agotada)
        msg = detail.message
        if (detail.usage) setUsage(detail.usage)
        // Si el backend mandó upgrade.available=true (429 chat_quota_exceeded
        // o 403 free_chat_not_allowed), seteamos upgradeInfo → render de
        // UpgradePromoCard reemplaza al banner rojo de error. Audit #4.
        if (detail.upgrade && detail.upgrade.available) {
          setUpgradeInfo(detail.upgrade)
        }
      } else if (Array.isArray(detail) && detail.length > 0) {
        // Caso 2: array Pydantic — no lo mostramos crudo. Inferimos el tipo.
        const firstErr = detail[0] || {}
        const errType = String(firstErr.type || '').toLowerCase()
        if (errType === 'string_too_long' || errType.includes('too_long')) {
          // Causa típica: la conversación acumuló muchos turnos y el history
          // del bot superó el cap. Tras subir el cap a 5000 esto no debería
          // pasar normalmente, pero mantenemos el mensaje como red de
          // seguridad si el assistant genera output extraordinariamente largo.
          msg = 'La conversación se hizo muy larga. Tocá "Nuevo" para empezar de cero y volvé a preguntar.'
        } else {
          msg = 'El mensaje no pasó la validación del servidor. Tocá "Nuevo" para refrescar el chat.'
        }
      } else if (typeof detail === 'string') {
        msg = detail
      }
      setError(msg)
      // Sacar del historial lo que falló para que el user pueda reintentar:
      // si el stream alcanzó a agregar la burbuja del asistente (texto parcial),
      // la sacamos también; siempre sacamos el user msg.
      setMessages(m => {
        const mm = assistantAdded ? m.slice(0, -1) : m
        return mm.slice(0, -1)
      })
    } finally {
      setLoading(false)
      sendingRef.current = false
      setSending(false)
      if (abortRef.current === ctrl) abortRef.current = null
    }
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
    // Abortar el stream en curso ANTES de limpiar: sin esto, los deltas del
    // stream viejo re-poblaban una burbuja fantasma sobre el chat nuevo.
    abortRef.current?.abort()
    setMessages([])
    setError(null)
    setUpgradeInfo(null)
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
              title={usage.resets_on ? `Se renueva el ${usage.resets_on}` : 'Cuota semanal'}
            >
              {usage.chat_count}/{usage.chat_limit} esta semana
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
          stickToBottomRef.current = (el.scrollHeight - el.scrollTop - el.clientHeight) < 80
        }}
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
              Respondo mirando tus posiciones, tu historial y el mercado de hoy.
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
                {meta?.verdict && (
                  <span className={`inline-block text-[11.5px] font-bold px-2.5 py-1 rounded-full mb-2 ${VERDICT_TONE[meta.tone] || VERDICT_TONE.neutral}`}>
                    {meta.verdict}
                  </span>
                )}
                {meta?.headline && (
                  <p className="text-[15.5px] font-semibold text-ink-0 leading-snug mb-1.5">{meta.headline}</p>
                )}
                <div className="text-[14.5px] text-ink-1 leading-relaxed whitespace-pre-wrap">{prose}</div>
                {meta?.stats?.length > 0 && (
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3">
                    {meta.stats.map((s, k) => (
                      <div key={k} className="bg-bg-1 border border-line rounded-xl px-3 py-2.5">
                        <div className="text-[11px] text-ink-3 font-medium mb-1">{s.l}</div>
                        <div className={`text-[15px] font-semibold num tabular ${STAT_TONE[s.t] || STAT_TONE.neutral}`}>{s.v}</div>
                      </div>
                    ))}
                  </div>
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

        {loading && (
          <div className="flex justify-start">
            <div className="bg-bg-2 dark:bg-bg-2/50 rounded-2xl rounded-bl-sm px-4 py-2.5">
              <div className="flex gap-1.5">
                <span className="w-1.5 h-1.5 bg-ink-3 dark:bg-bg-20 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-ink-3 dark:bg-bg-20 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-ink-3 dark:bg-bg-20 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
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
        <form
          onSubmit={handleFreeSubmit}
          className="flex items-center gap-2.5 bg-bg-1 border border-line focus-within:border-data-violet/50 rounded-2xl pl-4 pr-2 py-1.5 transition-colors"
        >
          <input
            type="text"
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
            <span className="tabular num" title={usage.resets_on ? `Se renueva el ${usage.resets_on}` : 'Cuota semanal'}>
              {Math.max(0, usage.chat_limit - usage.chat_count)} consultas restantes
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
