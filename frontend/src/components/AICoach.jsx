// AICoach — chat con IA contextualizado al portfolio (V2).
// ═══════════════════════════════════════════════════════════════════════════
// Visual: panel violet + gradient sutil (estilo audit "Coach IA").
// Mensajes assistant en mono con prefix `>` (terminal feel).
// Mensajes user con accent blue. Chips de preguntas sugeridas debajo.

import { useState, useRef, useEffect } from 'react'
import { Send, AlertCircle, RotateCcw, Sparkles } from 'lucide-react'
import { api } from '../utils/api'

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
      const res = await api.post('/ai/chat', { messages: newMessages, snapshot })
      setMessages(m => [...m, { role: 'assistant', content: res.reply }])
    } catch (e) {
      setError(e.message || 'No pudimos completar la consulta. Intentalo nuevamente.')
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
    <div
      className="rounded border border-data-violet/30 overflow-hidden flex flex-col"
      style={{ background: 'linear-gradient(180deg, rgba(139,125,255,0.05), rgba(139,125,255,0.01) 40%, transparent)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-data-violet/20 bg-bg-1/40">
        <div className="flex items-center gap-2.5">
          <span
            className="inline-block w-2 h-2 rounded-full bg-data-violet"
            style={{ boxShadow: '0 0 8px rgba(139,125,255,0.85)' }}
            aria-hidden="true"
          />
          <Sparkles size={13} strokeWidth={1.75} className="text-data-violet" aria-hidden="true" />
          <h2 className="text-sm font-medium text-ink-0 leading-none">Coach IA</h2>
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none">
            / contexto sobre tu portfolio
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-mono text-data-violet uppercase tracking-caps">RND-AI · Haiku</span>
          {messages.length > 0 && (
            <button
              onClick={reset}
              className="text-[10px] text-ink-3 hover:text-ink-0 inline-flex items-center gap-1 font-mono uppercase tracking-caps"
              title="Empezar de nuevo"
              aria-label="Empezar conversación de nuevo"
            >
              <RotateCcw size={10} strokeWidth={1.75} /> Nuevo
            </button>
          )}
        </div>
      </div>

      {/* Mensajes */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3 max-h-[420px] min-h-[180px]">
        {messages.length === 0 && !loading && (
          <div className="py-2">
            <p className="text-sm text-ink-1 mb-3 font-mono">
              <span className="text-data-violet">{'>'}</span> Tengo contexto completo sobre tu portfolio. ¿Qué te gustaría analizar?
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTED.map(q => (
                <button
                  key={q}
                  onClick={() => send(q)}
                  className="text-xs px-2.5 py-1 bg-bg-2 hover:bg-bg-3 border border-line hover:border-data-violet/40 text-ink-1 rounded-sm transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'flex justify-end' : ''}>
            {m.role === 'user' ? (
              <div className="max-w-[85%] bg-data-blue/10 border border-data-blue/30 text-ink-0 rounded-sm px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap">
                {m.content}
              </div>
            ) : (
              <div className="font-mono text-[13px] text-ink-1 leading-relaxed whitespace-pre-wrap">
                <span className="text-data-violet select-none">{'> '}</span>{m.content}
              </div>
            )}
          </div>
        ))}

        {loading && (
          <div className="font-mono text-sm text-ink-2">
            <span className="text-data-violet select-none">{'> '}</span>
            <span className="inline-flex gap-1 align-middle">
              <span className="w-1 h-1 bg-data-violet rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1 h-1 bg-data-violet rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1 h-1 bg-data-violet rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </span>
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 p-2.5 border border-rendi-neg/30 bg-rendi-neg/[0.06] rounded-sm text-xs text-rendi-neg">
            <AlertCircle size={13} strokeWidth={1.75} className="flex-shrink-0 mt-0.5" />
            <span className="break-all font-mono">{error}</span>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-data-violet/20 px-3 py-2.5 bg-bg-1/40">
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Escribí tu consulta…"
            rows={1}
            disabled={loading}
            className="flex-1 resize-none bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-data-violet/60 disabled:opacity-50 max-h-32 font-mono"
            style={{ minHeight: '36px' }}
          />
          <button
            onClick={() => send()}
            disabled={loading || !input.trim()}
            className="flex-shrink-0 bg-data-violet hover:bg-data-violet/85 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-sm p-2 transition-colors"
            title="Enviar (Enter)"
            aria-label="Enviar mensaje"
          >
            <Send size={14} strokeWidth={1.75} />
          </button>
        </div>
        <p className="text-[10px] font-mono text-ink-3 mt-1.5 text-center uppercase tracking-caps">
          Claude Haiku · Observaciones orientativas — no es asesoramiento financiero
        </p>
      </div>
    </div>
  )
}
