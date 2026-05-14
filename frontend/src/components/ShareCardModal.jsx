// ShareCardModal — preview + acciones de exportar/compartir una tarjeta PNG.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint 5: viralidad / Wrapped. Se invoca desde Behavioral.jsx (insights) y
// desde MonthlySummary.jsx (resumen mensual). El render real ocurre en
// utils/shareCard.js con Canvas 2D — este componente solo orquesta UI.

import { useEffect, useRef, useState } from 'react'
import { X, Download, Share2, Copy, Check, Loader2 } from 'lucide-react'
import {
  renderShareCard,
  shareCardToBlob,
  downloadShareCard,
  tryNativeShare,
} from '../utils/shareCard'
import { track } from '../utils/track'

export default function ShareCardModal({ spec, filename, source, onClose }) {
  const canvasHolderRef = useRef(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)

  // ESC para cerrar
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // Renderizar la card al montar
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    renderShareCard(spec)
      .then((canvas) => {
        if (cancelled) return
        // Limpiar holder y insertar canvas escalado al preview
        const holder = canvasHolderRef.current
        if (!holder) return
        holder.innerHTML = ''
        canvas.style.width = '100%'
        canvas.style.height = 'auto'
        canvas.style.display = 'block'
        canvas.style.borderRadius = '6px'
        canvas.setAttribute('aria-label', 'Preview de tarjeta compartible')
        holder.appendChild(canvas)
        track('share_card_generated', { source, kind: spec.kind })
      })
      .catch((ex) => {
        if (!cancelled) setError(ex?.message || 'No pudimos generar la imagen.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [spec, source])

  async function handleDownload() {
    setBusy(true)
    try {
      await downloadShareCard(spec, filename || 'rendi-card.png')
      track('share_card_downloaded', { source, kind: spec.kind })
    } catch (ex) {
      setError(ex?.message || 'No pudimos descargar la imagen.')
    } finally {
      setBusy(false)
    }
  }

  async function handleNativeShare() {
    setBusy(true)
    try {
      const ok = await tryNativeShare(spec, { title: 'Rendi', text: spec.title })
      if (ok) {
        track('share_card_shared', { source, kind: spec.kind, channel: 'native' })
      } else {
        // Fallback: descargar
        await handleDownload()
      }
    } catch (ex) {
      setError(ex?.message || 'No pudimos compartir.')
    } finally {
      setBusy(false)
    }
  }

  async function handleCopyToClipboard() {
    setBusy(true)
    try {
      if (!navigator.clipboard?.write) {
        await handleDownload()
        return
      }
      const blob = await shareCardToBlob(spec)
      if (!blob) throw new Error('No se pudo generar el PNG')
      const item = new ClipboardItem({ 'image/png': blob })
      await navigator.clipboard.write([item])
      setCopied(true)
      setTimeout(() => setCopied(false), 2200)
      track('share_card_copied', { source, kind: spec.kind })
    } catch (ex) {
      // Algunos browsers no soportan ClipboardItem con image/png. Fallback: download.
      await handleDownload()
    } finally {
      setBusy(false)
    }
  }

  const hasNativeShare = typeof navigator !== 'undefined' && !!navigator.share

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-3 bg-black/70 backdrop-blur-sm"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Compartir tarjeta"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-bg-1 border border-line-2 rounded-lg shadow-2xl w-full max-w-md max-h-[95vh] overflow-y-auto"
      >
        <header className="flex items-center justify-between gap-2 px-4 py-3 border-b border-line/40">
          <div className="min-w-0">
            <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none">
              Compartir
            </div>
            <h2 className="text-sm font-medium text-ink-0 mt-1.5 leading-none">
              Tu tarjeta lista para redes
            </h2>
          </div>
          <button
            onClick={onClose}
            className="text-ink-3 hover:text-ink-0 transition-colors p-1"
            aria-label="Cerrar"
          >
            <X size={16} strokeWidth={1.75} />
          </button>
        </header>

        <div className="p-4 space-y-3">
          <div
            ref={canvasHolderRef}
            className="relative bg-bg-0 rounded overflow-hidden min-h-[280px] flex items-center justify-center"
            aria-live="polite"
          >
            {loading && (
              <div className="text-xs font-mono text-ink-3 flex items-center gap-2">
                <Loader2 size={14} className="animate-spin" />
                Generando…
              </div>
            )}
            {error && (
              <div className="text-xs text-rendi-neg px-4 py-6 text-center">
                {error}
              </div>
            )}
          </div>

          {/* Acciones */}
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={handleDownload}
              disabled={loading || busy || !!error}
              className="inline-flex items-center justify-center gap-1.5 text-xs bg-rendi-pos/10 hover:bg-rendi-pos/15 disabled:opacity-50 disabled:cursor-not-allowed text-rendi-pos border border-rendi-pos/30 px-3 py-2 rounded-sm transition-colors"
            >
              <Download size={12} strokeWidth={1.75} />
              Descargar PNG
            </button>

            {hasNativeShare ? (
              <button
                onClick={handleNativeShare}
                disabled={loading || busy || !!error}
                className="inline-flex items-center justify-center gap-1.5 text-xs bg-bg-2 hover:bg-bg-3 disabled:opacity-50 disabled:cursor-not-allowed text-ink-1 border border-line-2 px-3 py-2 rounded-sm transition-colors"
              >
                <Share2 size={12} strokeWidth={1.75} />
                Compartir
              </button>
            ) : (
              <button
                onClick={handleCopyToClipboard}
                disabled={loading || busy || !!error}
                className="inline-flex items-center justify-center gap-1.5 text-xs bg-bg-2 hover:bg-bg-3 disabled:opacity-50 disabled:cursor-not-allowed text-ink-1 border border-line-2 px-3 py-2 rounded-sm transition-colors"
              >
                {copied ? <Check size={12} strokeWidth={1.75} /> : <Copy size={12} strokeWidth={1.75} />}
                {copied ? '¡Copiado!' : 'Copiar imagen'}
              </button>
            )}
          </div>

          <p className="text-[11px] text-ink-3 leading-relaxed text-center">
            Tarjeta 1080×1350 — ideal para Instagram, X o WhatsApp.
            <br />
            <span className="opacity-70">Solo se muestra lo que ves en pantalla. Nunca compartimos tu info sin que vos generes la card.</span>
          </p>
        </div>
      </div>
    </div>
  )
}
