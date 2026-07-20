// RecommendationsModal — modal para que el user mande recomendaciones / ideas
// / bugs al equipo de Rendi.
// ════════════════════════════════════════════════════════════════════════════
// Dos formas de mandar:
//   1. Form in-app: completa subject + body y dispara POST /api/feedback/recommendation
//      → backend envía mail a recomendaciones@rendi.finance vía Resend con
//      reply-to=user_email, así Nico responde desde su Gmail directo al user.
//   2. Mailto: link a recomendaciones@rendi.finance que abre el cliente de
//      mail del user (Gmail web, Mail.app, Outlook, etc).
//
// Trigger: items "Recomendaciones" en Sidebar (footer) + Config.

import { useState } from 'react'
import { Mail, Send, Copy, Check, X, Loader2, MessageCircle } from 'lucide-react'
import { api } from '../utils/api'
import { track } from '../utils/track'

const RECOMMENDATIONS_EMAIL = 'recomendaciones@rendi.finance'

export default function RecommendationsModal({ open, onClose }) {
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [sending, setSending] = useState(false)
  const [phase, setPhase] = useState('form')  // 'form' | 'success' | 'error'
  const [errorMsg, setErrorMsg] = useState('')
  const [copied, setCopied] = useState(false)

  if (!open) return null

  function resetAndClose() {
    if (sending) return  // no permitir cerrar mientras se envía
    setSubject('')
    setBody('')
    setPhase('form')
    setErrorMsg('')
    setCopied(false)
    onClose()
  }

  async function handleSend(e) {
    e.preventDefault()
    if (sending) return
    if (!subject.trim() || subject.trim().length < 2) {
      setErrorMsg('El asunto es muy corto.')
      return
    }
    if (!body.trim() || body.trim().length < 5) {
      setErrorMsg('Escribí un mensaje un poco más largo así te podemos entender bien.')
      return
    }
    setErrorMsg('')
    setSending(true)
    try {
      await api.post('/feedback/recommendation', { subject: subject.trim(), body: body.trim() })
      track('recommendation_sent', { length: body.length })
      setPhase('success')
    } catch (ex) {
      const msg = ex?.payload?.detail?.message || ex?.message
        || 'No pudimos enviar tu mensaje. Probá de nuevo o escribinos directo a ' + RECOMMENDATIONS_EMAIL
      setErrorMsg(msg)
      setPhase('error')
    } finally {
      setSending(false)
    }
  }

  function copyEmail() {
    try {
      navigator.clipboard.writeText(RECOMMENDATIONS_EMAIL)
      setCopied(true)
      track('recommendation_email_copied')
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore — algunos browsers bloquean clipboard fuera de https */
    }
  }

  // mailto: con subject + body pre-llenado del form (si el user escribió algo).
  // El usuario hace click → su cliente de mail abre con el contenido ya cargado.
  // Útil si quiere enviar desde su propio mail (no desde Rendi) — por ejemplo
  // si quiere adjuntar un archivo (que no soportamos en el form in-app).
  const mailtoHref = (() => {
    const params = []
    if (subject.trim()) params.push(`subject=${encodeURIComponent(subject.trim())}`)
    if (body.trim()) params.push(`body=${encodeURIComponent(body.trim())}`)
    const qs = params.length ? `?${params.join('&')}` : ''
    return `mailto:${RECOMMENDATIONS_EMAIL}${qs}`
  })()

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4"
      onClick={resetAndClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="recom-modal-title"
    >
      <div
        className="bg-bg-1 border border-line-2/70 rounded-lg max-w-lg w-full p-6 shadow-[0_20px_60px_-10px_rgba(0,0,0,0.6)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <MessageCircle size={14} strokeWidth={1.75} className="text-data-violet" />
              <span className="text-[12px] text-data-violet font-medium">
                Recomendaciones
              </span>
            </div>
            <h2 id="recom-modal-title" className="text-lg font-semibold text-ink-0">
              {phase === 'success' ? '¡Recibimos tu mensaje!' : 'Mandanos una recomendación'}
            </h2>
          </div>
          <button
            type="button"
            onClick={resetAndClose}
            disabled={sending}
            className="text-ink-3 hover:text-ink-0 disabled:opacity-50"
            aria-label="Cerrar"
          >
            <X size={18} strokeWidth={1.75} />
          </button>
        </div>

        {phase === 'success' && (
          <>
            <p className="text-sm text-ink-2 leading-relaxed mb-5">
              Gracias por escribirnos. Lo leemos personalmente y, si hace falta una
              respuesta, te contestamos a tu mail en un plazo máximo de 48hs.
            </p>
            <button
              type="button"
              onClick={resetAndClose}
              className="w-full inline-flex items-center justify-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-4 py-2.5 transition-colors"
            >
              Cerrar
            </button>
          </>
        )}

        {phase !== 'success' && (
          <>
            <p className="text-xs text-ink-2 leading-relaxed mb-4">
              ¿Algo que falte? ¿Algún bug? ¿Una idea para una feature?
              Lo que se te ocurra para mejorar Rendi nos sirve. Escribilo acá o mandanos un mail directo a{' '}
              <span className="text-ink-0 font-mono">{RECOMMENDATIONS_EMAIL}</span>.
            </p>

            <form onSubmit={handleSend} className="space-y-3">
              <div>
                <label className="block text-[12.5px] text-ink-2 mb-1.5 font-medium">
                  Asunto
                </label>
                <input
                  type="text"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="Ej. Sería útil que…"
                  maxLength={200}
                  disabled={sending}
                  className="w-full bg-bg-2 border border-line/60 hover:border-line-3 focus:border-data-violet text-sm rounded-sm px-3 py-2 text-ink-0 placeholder:text-ink-3 outline-none transition-colors disabled:opacity-50"
                />
              </div>
              <div>
                <label className="block text-[12.5px] text-ink-2 mb-1.5 font-medium">
                  Mensaje
                </label>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  placeholder="Contanos qué tenés en mente…"
                  maxLength={5000}
                  rows={6}
                  disabled={sending}
                  className="w-full bg-bg-2 border border-line/60 hover:border-line-3 focus:border-data-violet text-sm rounded-sm px-3 py-2 text-ink-0 placeholder:text-ink-3 outline-none transition-colors resize-y disabled:opacity-50"
                />
                <div className="text-[10px] text-ink-3 mt-1 text-right tabular">
                  {body.length}/5000
                </div>
              </div>

              {(errorMsg || phase === 'error') && (
                <div className="text-xs text-rendi-neg border border-rendi-neg/30 bg-rendi-neg/[0.06] rounded-sm px-3 py-2">
                  {errorMsg || 'Hubo un error al enviar.'}
                </div>
              )}

              <div className="flex items-center gap-2 pt-1">
                <button
                  type="submit"
                  disabled={sending}
                  className="flex-1 inline-flex items-center justify-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-4 py-2.5 transition-colors disabled:opacity-60 disabled:cursor-wait"
                >
                  {sending ? (
                    <>
                      <Loader2 size={14} strokeWidth={2} className="animate-spin" />
                      Enviando…
                    </>
                  ) : (
                    <>
                      <Send size={14} strokeWidth={2} />
                      Enviar desde Rendi
                    </>
                  )}
                </button>
              </div>
            </form>

            {/* Alternativas: copiar mail / abrir cliente de mail */}
            <div className="mt-5 pt-4 border-t border-line/40">
              <p className="text-[12.5px] text-ink-2 mb-2 font-medium">
                O escribinos directo a este mail
              </p>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={copyEmail}
                  className="flex-1 inline-flex items-center justify-between gap-2 bg-bg-2 hover:bg-bg-2/80 border border-line/60 hover:border-line-3 rounded-sm px-3 py-2 text-sm text-ink-1 transition-colors"
                  title="Copiar mail"
                >
                  <span className="font-mono text-xs">{RECOMMENDATIONS_EMAIL}</span>
                  {copied ? (
                    <Check size={12} strokeWidth={2} className="text-rendi-pos" />
                  ) : (
                    <Copy size={12} strokeWidth={1.75} className="text-ink-3" />
                  )}
                </button>
                <a
                  href={mailtoHref}
                  className="inline-flex items-center gap-1.5 text-xs font-medium bg-bg-2 hover:bg-bg-2/80 text-ink-1 border border-line/60 hover:border-line-3 rounded-sm px-3 py-2 transition-colors"
                  title="Abrir cliente de mail"
                >
                  <Mail size={12} strokeWidth={1.75} />
                  Abrir mail
                </a>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
