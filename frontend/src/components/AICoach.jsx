import { useState, useRef, useEffect } from 'react'
import { Sparkles, Send, AlertCircle, RotateCcw } from 'lucide-react'
import { api } from '../utils/api'

// Preguntas por defecto — se usan si el caller no pasa `suggested` o si la
// generación dinámica no produjo lo suficiente. Insights las reemplaza por
// preguntas data-driven basadas en el snapshot real.
const DEFAULT_SUGGESTED = [
  '¿Cómo está mi portfolio en general?',
  '¿Qué riesgos detectás en mi cartera?',
  '¿Mi nivel de concentración es elevado?',
  '¿Cómo evalúo mi win rate?',
]

export default function AICoach({ snapshot, suggested }) {
  const SUGGESTED = (suggested && suggested.length > 0) ? suggested.slice(0, 4) : DEFAULT_SUGGESTED
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  // Auto-scroll al final cuando llegan mensajes nuevos
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, loading])

  async function send(text) {
    const content = (text ?? input).trim()
    if (!content || loading || !snapshot) return

    const userMsg = { role: 'user', content }
    const newMessages = [...messages, userMsg]
    setMessages(newMessages)
    setInput('')
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
      // Sacar el último user msg si falló, para que pueda reintentarlo
      setMessages(m => m.slice(0, -1))
      setInput(content)
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  function reset() {
    setMessages([])
    setError(null)
    setInput('')
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

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
            <p className="text-[11px] text-ink-3">Asistente con contexto sobre tu portfolio</p>
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
          <div className="text-center py-4">
            <p className="text-sm text-ink-2 mb-3">
              Tengo contexto completo sobre tu portfolio. ¿Qué te gustaría analizar?
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {SUGGESTED.map(q => (
                <button
                  key={q}
                  onClick={() => send(q)}
                  className="text-xs px-3 py-1.5 bg-bg-2 hover:bg-bg-2 dark:bg-bg-2 dark:hover:bg-bg-3 border border-line text-ink-1 rounded-full transition"
                >
                  {q}
                </button>
              ))}
            </div>
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

      {/* Input */}
      <div className="border-t border-line/70 dark:border-line/40 px-3 py-2.5">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Escribí tu consulta..."
            rows={1}
            disabled={loading}
            className="flex-1 resize-none bg-bg-2 dark:bg-bg-2 border border-line rounded-lg px-3 py-2 text-sm text-ink-0 placeholder-ink-3 dark:placeholder-ink-3 focus:outline-none focus:border-rendi-accent/60 focus:ring-2 focus:ring-rendi-accent/20 disabled:opacity-50 max-h-32"
            style={{ minHeight: '38px' }}
          />
          <button
            onClick={() => send()}
            disabled={loading || !input.trim()}
            className="flex-shrink-0 bg-rendi-accent hover:bg-rendi-accent/90 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-lg p-2 transition"
            title="Enviar (Enter)"
            aria-label="Enviar mensaje"
          >
            <Send size={16} />
          </button>
        </div>
        <p className="text-[10px] text-ink-3 mt-1.5 text-center">
          Claude Haiku · Observaciones de carácter orientativo. No constituyen asesoramiento financiero.
        </p>
      </div>
    </div>
  )
}
