import { useState, useRef, useEffect } from 'react'
import { Sparkles, Send, AlertCircle, RotateCcw } from 'lucide-react'
import { api } from '../utils/api'

const SUGGESTED = [
  '¿Cómo está mi portfolio en general?',
  '¿Qué riesgos detectás en mi cartera?',
  '¿Mi nivel de concentración es elevado?',
  '¿Cómo evalúo mi win rate?',
]

export default function AICoach({ snapshot }) {
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
    <div className="bg-white dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/50 shadow-sm dark:shadow-none rounded-xl overflow-hidden flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200/70 dark:border-slate-700/40">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-md bg-rendi-green/10">
            <Sparkles size={16} className="text-rendi-green-dark dark:text-rendi-green" />
          </div>
          <div>
            <h2 className="font-semibold text-slate-800 dark:text-slate-200">Coach IA</h2>
            <p className="text-[11px] text-slate-500 dark:text-slate-400">Asistente con contexto sobre tu portfolio</p>
          </div>
        </div>
        {messages.length > 0 && (
          <button
            onClick={reset}
            className="text-xs text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 flex items-center gap-1"
            title="Empezar de nuevo"
          >
            <RotateCcw size={12} /> Nuevo
          </button>
        )}
      </div>

      {/* Mensajes */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3 max-h-[420px] min-h-[180px]">
        {messages.length === 0 && !loading && (
          <div className="text-center py-4">
            <p className="text-sm text-slate-600 dark:text-slate-300 mb-3">
              Tengo contexto completo sobre tu portfolio. ¿Qué te gustaría analizar?
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {SUGGESTED.map(q => (
                <button
                  key={q}
                  onClick={() => send(q)}
                  className="text-xs px-3 py-1.5 bg-rendi-green/10 hover:bg-rendi-green/20 text-rendi-green-dark dark:text-rendi-green rounded-full transition"
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
                  ? 'bg-rendi-green text-rendi-bg rounded-br-sm font-medium'
                  : 'bg-slate-100 dark:bg-slate-700/50 text-slate-800 dark:text-slate-200 rounded-bl-sm'
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-slate-100 dark:bg-slate-700/50 rounded-2xl rounded-bl-sm px-4 py-2.5">
              <div className="flex gap-1.5">
                <span className="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-slate-400 dark:bg-slate-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
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
      <div className="border-t border-slate-200/70 dark:border-slate-700/40 px-3 py-2.5">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Escribí tu consulta..."
            rows={1}
            disabled={loading}
            className="flex-1 resize-none bg-slate-50 dark:bg-slate-900/60 border border-slate-300 dark:border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-900 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-none focus:border-rendi-green/60 focus:ring-2 focus:ring-rendi-green/20 disabled:opacity-50 max-h-32"
            style={{ minHeight: '38px' }}
          />
          <button
            onClick={() => send()}
            disabled={loading || !input.trim()}
            className="flex-shrink-0 bg-rendi-green hover:bg-rendi-green-dark disabled:opacity-40 disabled:cursor-not-allowed text-rendi-bg rounded-lg p-2 transition"
            title="Enviar (Enter)"
          >
            <Send size={16} />
          </button>
        </div>
        <p className="text-[10px] text-slate-400 dark:text-slate-600 mt-1.5 text-center">
          Claude Haiku · Observaciones de carácter orientativo. No constituyen asesoramiento financiero.
        </p>
      </div>
    </div>
  )
}
