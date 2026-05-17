// AICoach — preguntas pre-fijadas con contexto del portfolio.
// ═══════════════════════════════════════════════════════════════════════════
// Decisión de producto (AI v2 — post audit):
// El chat libre fue retirado. El user NO escribe libremente, solo elige
// entre preguntas pre-fijadas que el backend sabe responder con calidad
// consistente. Esto:
//   1) Elimina el riesgo de respuestas pobres ante preguntas vagas.
//   2) Reduce el costo (queries acotadas, prompts cacheables).
//   3) Alinea con la filosofía del manifiesto editorial: el LLM
//      interpreta datos pre-calculados, no improvisa.
//
// Si el user quiere análisis profundo de algo específico, el botón ✦ en
// cada sección del producto (AskAIAbout) le da contextual analysis con
// el tono research-note.

import { useState, useRef, useEffect } from 'react'
import { Sparkles, AlertCircle, RotateCcw } from 'lucide-react'
import { api } from '../utils/api'

// Preguntas por defecto — se usan si el caller no pasa `suggested`.
// Insights genera dinámicamente preguntas data-driven basadas en el
// snapshot real (drawdown actual, win rate, concentración, etc.).
const DEFAULT_SUGGESTED = [
  '¿Cómo está mi portfolio en general?',
  '¿Qué riesgos detectás en mi cartera?',
  '¿Mi nivel de concentración es elevado?',
  '¿Cómo evalúo mi win rate?',
]

export default function AICoach({ snapshot, suggested }) {
  const SUGGESTED = (suggested && suggested.length > 0) ? suggested.slice(0, 6) : DEFAULT_SUGGESTED
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const scrollRef = useRef(null)

  // Auto-scroll al final cuando llegan mensajes nuevos
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  async function send(text) {
    const content = (text || '').trim()
    if (!content || loading || !snapshot) return

    const userMsg = { role: 'user', content }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setLoading(true)
    setError(null)

    try {
      const res = await api.post('/ai/chat', {
        messages: newMessages,
        snapshot,
      })
      setMessages(m => [...m, { role: 'assistant', content: res.reply }])
    } catch (e) {
      setError(e.message || 'No pudimos completar la consulta. Intentalo nuevamente.')
      // Sacar el último user msg si falló — el user puede reintentar con otro chip
      setMessages(m => m.slice(0, -1))
    } finally {
      setLoading(false)
    }
  }

  function reset() {
    setMessages([])
    setError(null)
  }

  // Cuál chips mostrar: si todavía no hay mensajes, las 4-6 iniciales.
  // Si ya hubo intercambio, las restantes (las que no preguntó aún).
  const askedQuestions = new Set(
    messages.filter(m => m.role === 'user').map(m => m.content)
  )
  const availableQuestions = SUGGESTED.filter(q => !askedQuestions.has(q))

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl overflow-hidden flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-line/70 dark:border-line/40">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-sm bg-bg-3 border border-line">
            <Sparkles size={16} strokeWidth={1.5} className="text-rendi-accent" />
          </div>
          <div>
            <h2 className="font-semibold text-ink-0">Coach IA</h2>
            <p className="text-[11px] text-ink-3">Preguntas con contexto de tu portfolio</p>
          </div>
        </div>
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

      {/* Mensajes */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3 max-h-[420px] min-h-[180px]">
        {messages.length === 0 && !loading && (
          <div className="text-center py-2">
            <p className="text-sm text-ink-2 mb-3">
              Elegí una pregunta para que la analice con tu data:
            </p>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm leading-relaxed whitespace-pre-wrap ${
                m.role === 'user'
                  ? 'bg-rendi-accent/15 border border-rendi-accent/30 text-ink-0 rounded-br-sm font-medium'
                  : 'bg-bg-2 dark:bg-bg-2 text-ink-0 rounded-bl-sm'
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}

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

        {error && (
          <div className="flex items-start gap-2 p-2.5 bg-red-500/10 border border-red-500/30 rounded-md text-xs text-red-600 dark:text-red-400">
            <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
            <span className="break-all">{error}</span>
          </div>
        )}
      </div>

      {/* Chips de preguntas — siempre visibles abajo, NO hay input libre */}
      {availableQuestions.length > 0 && (
        <div className="border-t border-line/70 dark:border-line/40 px-3 py-2.5 bg-bg-1/40">
          <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2">
            {messages.length === 0 ? 'Preguntas sugeridas' : 'Otra pregunta'}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {availableQuestions.map(q => (
              <button
                key={q}
                onClick={() => send(q)}
                disabled={loading}
                className="text-xs px-3 py-1.5 bg-bg-2 hover:bg-bg-3 dark:bg-bg-2 dark:hover:bg-bg-3 border border-line text-ink-1 rounded-full transition disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {availableQuestions.length === 0 && messages.length > 0 && (
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

      <p className="text-[10px] text-ink-3 px-3 py-1.5 text-center border-t border-line/40">
        Claude Haiku · Observaciones orientativas. No constituyen asesoramiento financiero.
      </p>
    </div>
  )
}
