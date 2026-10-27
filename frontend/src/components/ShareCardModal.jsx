// ShareCardModal — preview + acciones de exportar/compartir una tarjeta PNG.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint 5: viralidad / Wrapped. Se invoca desde Behavioral.jsx (insights),
// MonthlySummary.jsx (resumen mensual) y, vía BotonCompartir, desde las
// métricas (tortas de distribución y "Cartera vs benchmark"). El render real
// ocurre en utils/shareCard.js con Canvas 2D — este componente solo orquesta UI.
//
// Dos formas de llamarlo:
//   • `spec`      — la tarjeta ya armada (insights, resumen mensual).
//   • `buildSpec` — una función ({ mostrarMontos }) → spec. Antes de generar
//     la imagen el modal PREGUNTA si van los montos o sólo los porcentajes:
//     la tarjeta se va a compartir, y cuánta plata tiene alguien no es algo
//     que la app deba decidir por él. La respuesta se puede cambiar desde el
//     preview sin cerrar.
//
// Renderizamos el canvas a data: URL y lo mostramos como <img>. Eso evita
// problemas de layout (canvas en flex-center colapsa altura en algunos
// browsers) y deja un único árbol React fácil de testear.
//
// La tarjeta que se descarga es la MISMA que se previsualizó: se congela el
// spec al generar el preview. Los datos de la página se recalculan con cada
// refresco de precios, y sin congelarlo el PNG podía decir otro número que la
// imagen que el usuario acaba de mirar.

import { useEffect, useRef, useState } from 'react'
import { X, Download, Share2, Copy, Check, Loader2, Eye, EyeOff } from 'lucide-react'
import {
  shareCardToBlob,
  shareCardToDataURL,
  downloadShareCard,
  tryNativeShare,
} from '../utils/shareCard'
import { track } from '../utils/track'
import PreguntaMontos from './PreguntaMontos'

export default function ShareCardModal({ spec: specFijo, buildSpec = null, filename, source, onClose }) {
  const pregunta = typeof buildSpec === 'function'
  // null = todavía no contestó (sólo cuando hay que preguntar).
  const [mostrarMontos, setMostrarMontos] = useState(pregunta ? null : false)
  const [dataUrl, setDataUrl] = useState(null)
  const [loading, setLoading] = useState(!pregunta)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const specRef = useRef(specFijo || null)
  const buildRef = useRef(buildSpec)
  buildRef.current = buildSpec

  const esperandoRespuesta = pregunta && mostrarMontos == null
  const montosProp = pregunta ? (mostrarMontos ? 'visibles' : 'ocultos') : undefined

  // ESC para cerrar
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // Render una vez por montaje (o por respuesta a la pregunta de los montos).
  // El `spec` se congela acá: es el que usan después descargar/compartir/copiar.
  useEffect(() => {
    if (esperandoRespuesta) return
    let cancelled = false
    const spec = pregunta ? buildRef.current({ mostrarMontos }) : specFijo
    specRef.current = spec
    setLoading(true)
    setError(null)
    setDataUrl(null)
    shareCardToDataURL(spec)
      .then((url) => {
        if (cancelled) return
        setDataUrl(url)
        track('share_card_generated', { source, kind: spec.kind, montos: montosProp })
      })
      .catch((ex) => {
        if (cancelled) return
        setError(ex?.message || 'No pudimos generar la imagen.')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
    // Solo dependemos del source y de la respuesta para evitar re-render por
    // nueva referencia de `spec`. Si el caller cambia la card, debería
    // re-montar el modal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source, mostrarMontos])

  async function handleDownload() {
    setBusy(true)
    try {
      await downloadShareCard(specRef.current, filename || 'rendi-card.png')
      track('share_card_downloaded', { source, kind: specRef.current.kind, montos: montosProp })
    } catch (ex) {
      setError(ex?.message || 'No pudimos descargar la imagen.')
    } finally {
      setBusy(false)
    }
  }

  async function handleNativeShare() {
    setBusy(true)
    try {
      const spec = specRef.current
      const ok = await tryNativeShare(spec, { title: 'Rendi', text: spec.title })
      if (ok) {
        track('share_card_shared', { source, kind: spec.kind, channel: 'native', montos: montosProp })
      } else {
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
      if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') {
        await handleDownload()
        return
      }
      const blob = await shareCardToBlob(specRef.current)
      if (!blob) throw new Error('No se pudo generar el PNG')
      const item = new ClipboardItem({ 'image/png': blob })
      await navigator.clipboard.write([item])
      setCopied(true)
      setTimeout(() => setCopied(false), 2200)
      track('share_card_copied', { source, kind: specRef.current.kind, montos: montosProp })
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
            <div className="text-[12.5px] text-ink-2 leading-none font-medium">
              Compartir
            </div>
            <h2 className="text-sm font-medium text-ink-0 mt-1.5 leading-none">
              {esperandoRespuesta ? '¿Mostramos los montos?' : 'Tu tarjeta lista para redes'}
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

        {esperandoRespuesta ? (
          <div className="p-4">
            <PreguntaMontos onElegir={setMostrarMontos} />
          </div>
        ) : (
        <div className="p-4 space-y-3">
          {/* Preview con aspect-ratio 4:5 para reservar espacio antes que cargue
              la imagen. Evita el "salto" de layout y el flicker en negro. */}
          <div
            className="relative bg-bg-0 rounded overflow-hidden border border-line/40"
            style={{ aspectRatio: '1080 / 1350' }}
            aria-live="polite"
          >
            {loading && (
              <div className="absolute inset-0 flex items-center justify-center text-xs text-ink-3 gap-2">
                <Loader2 size={14} className="animate-spin" />
                Generando…
              </div>
            )}
            {error && !loading && (
              <div className="absolute inset-0 flex items-center justify-center text-xs text-rendi-neg px-4 text-center">
                {error}
              </div>
            )}
            {dataUrl && !loading && !error && (
              <img
                src={dataUrl}
                alt="Preview de tu tarjeta compartible"
                className="absolute inset-0 w-full h-full block"
              />
            )}
          </div>

          {pregunta && (
            <div className="flex items-center justify-between gap-2 text-[11.5px] text-ink-3">
              <span>{mostrarMontos ? 'Con montos' : 'Solo porcentajes, sin montos'}</span>
              <button
                type="button"
                onClick={() => setMostrarMontos(v => !v)}
                disabled={loading || busy}
                className="inline-flex items-center gap-1 text-data-violet hover:text-data-violet/80 disabled:opacity-50 transition-colors"
              >
                {mostrarMontos ? <EyeOff size={12} strokeWidth={1.75} /> : <Eye size={12} strokeWidth={1.75} />}
                {mostrarMontos ? 'Ocultar montos' : 'Mostrar montos'}
              </button>
            </div>
          )}

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
        )}
      </div>
    </div>
  )
}
