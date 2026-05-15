// Wrapped — reseña anual del usuario, carrusel tipo "stories".
// ═══════════════════════════════════════════════════════════════════════════
// Sprint 6 del plan post-auditoría. Cierre del bucle viral después de
// Behavioral. Cada slide se exporta como PNG con shareCard.js.
//
// UX:
// - Stories-like: tap derecho → next, tap izquierdo → prev. Flechas también.
// - Barra de progreso arriba (cuántos slides hay y cuál estamos viendo).
// - Auto-track de slide_viewed para medir engagement.
// - Botón de compartir → reusa ShareCardModal con spec armado del slide.

import { useEffect, useMemo, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  Sparkles, ChevronLeft, ChevronRight, Share2, ArrowRight,
} from 'lucide-react'
import PageHeader from '../components/PageHeader'
import ShareCardModal from '../components/ShareCardModal'
import { api } from '../utils/api'
import { track } from '../utils/track'

const TONE_BG = {
  positive: 'from-green-400/15 via-green-300/[0.04] to-bg-0',
  negative: 'from-red-400/15 via-red-300/[0.04] to-bg-0',
  neutral:  'from-data-blue/15 via-data-blue/[0.04] to-bg-0',
}
const TONE_ACCENT = {
  positive: 'text-rendi-pos',
  negative: 'text-rendi-neg',
  neutral:  'text-data-blue',
}
const TONE_PILL = {
  positive: 'green',
  negative: 'red',
  neutral:  'blue',
}

const CURRENT_YEAR = new Date().getFullYear()

export default function Wrapped() {
  const [year, setYear] = useState(CURRENT_YEAR)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [idx, setIdx] = useState(0)
  const [shareOpen, setShareOpen] = useState(false)

  useEffect(() => {
    track('wrapped_viewed', { year })
    setLoading(true)
    setError(null)
    setIdx(0)
    api.get(`/wrapped/${year}`)
      .then(d => setData(d))
      .catch(ex => setError(ex?.message || 'No pudimos cargar tu Wrapped.'))
      .finally(() => setLoading(false))
  }, [year])

  const slides = data?.slides || []
  const total = slides.length
  const slide = slides[idx]

  const next = useCallback(() => setIdx(i => Math.min(i + 1, total - 1)), [total])
  const prev = useCallback(() => setIdx(i => Math.max(i - 1, 0)), [])

  // Keyboard navigation
  useEffect(() => {
    const onKey = (e) => {
      if (shareOpen) return
      if (e.key === 'ArrowRight' || e.key === ' ') { e.preventDefault(); next() }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); prev() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [next, prev, shareOpen])

  // Track slide_viewed cuando cambia el slide
  useEffect(() => {
    if (slide) track('wrapped_slide_viewed', { year, code: slide.code, index: idx })
  }, [idx, slide, year])

  if (loading) {
    return (
      <div className="page-shell text-center py-20 text-ink-3 text-sm" aria-live="polite">
        Preparando tu Wrapped…
      </div>
    )
  }

  if (error) {
    return (
      <div className="page-shell">
        <PageHeader eyebrow="Resumen anual" title="Wrapped" subtitle={`Tu ${year} en Rendi.`} />
        <div className="border border-rendi-neg/30 bg-rendi-neg/[0.06] rounded p-4 text-sm text-rendi-neg">
          {error}
        </div>
      </div>
    )
  }

  if (!data || total === 0) {
    return (
      <div className="page-shell text-center py-20 text-ink-3 text-sm">
        No hay datos disponibles.
      </div>
    )
  }

  return (
    <div className="page-shell space-y-4">
      <PageHeader
        eyebrow="Resumen anual"
        title="Wrapped"
        subtitle={`Tu ${year} en Rendi. Compartí cada slide como imagen.`}
      />

      {/* Año selector — útil cuando hay más de un año cargado */}
      <YearSelector year={year} setYear={setYear} />

      {/* Progress bar de slides */}
      <SlideProgress total={total} idx={idx} onJump={setIdx} />

      {/* Stage de la slide actual */}
      <div className="relative">
        <SlideStage slide={slide} year={year} />

        {/* Controles de navegación */}
        <button
          onClick={prev}
          disabled={idx === 0}
          className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-2 sm:-translate-x-12 disabled:opacity-30 disabled:cursor-not-allowed bg-bg-2/80 hover:bg-bg-3 backdrop-blur-sm border border-line-2 rounded-full p-2 transition-colors"
          aria-label="Slide anterior"
        >
          <ChevronLeft size={18} strokeWidth={1.75} />
        </button>
        <button
          onClick={next}
          disabled={idx === total - 1}
          className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-2 sm:translate-x-12 disabled:opacity-30 disabled:cursor-not-allowed bg-bg-2/80 hover:bg-bg-3 backdrop-blur-sm border border-line-2 rounded-full p-2 transition-colors"
          aria-label="Slide siguiente"
        >
          <ChevronRight size={18} strokeWidth={1.75} />
        </button>
      </div>

      {/* Footer con compartir + counter */}
      <div className="flex items-center justify-between gap-3 pt-2">
        <span className="text-xs font-mono uppercase tracking-caps text-ink-3">
          {idx + 1} / {total}
        </span>
        <div className="flex items-center gap-2">
          {idx < total - 1 ? (
            <button
              onClick={next}
              className="inline-flex items-center gap-1 text-xs bg-bg-2 hover:bg-bg-3 text-ink-1 border border-line-2 px-3 py-1.5 rounded-sm transition-colors"
            >
              Siguiente <ChevronRight size={12} strokeWidth={1.75} />
            </button>
          ) : (
            <Link
              to="/comportamiento"
              className="inline-flex items-center gap-1 text-xs bg-bg-2 hover:bg-bg-3 text-ink-1 border border-line-2 px-3 py-1.5 rounded-sm transition-colors"
            >
              Ver tus sesgos <ArrowRight size={12} strokeWidth={1.75} />
            </Link>
          )}
          {slide.code !== 'no_data' && (
            <button
              onClick={() => {
                track('wrapped_share_opened', { year, code: slide.code, index: idx })
                setShareOpen(true)
              }}
              className="inline-flex items-center gap-1 text-xs bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-3 py-1.5 rounded-sm transition-colors"
            >
              <Share2 size={12} strokeWidth={1.75} /> Compartir
            </button>
          )}
        </div>
      </div>

      {/* Modal compartir */}
      {shareOpen && (
        <ShareCardModal
          spec={specFromSlide(slide, year)}
          filename={`rendi-wrapped-${year}-${slide.code}.png`}
          source="wrapped"
          onClose={() => setShareOpen(false)}
        />
      )}
    </div>
  )
}

// ─── Year selector ────────────────────────────────────────────────────────

function YearSelector({ year, setYear }) {
  const opts = [CURRENT_YEAR, CURRENT_YEAR - 1, CURRENT_YEAR - 2]
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">Año:</span>
      <div className="inline-flex bg-bg-2 p-0.5 rounded-md border border-line/40">
        {opts.map(y => (
          <button
            key={y}
            onClick={() => setYear(y)}
            className={`px-3 py-1 text-xs font-medium tabular rounded transition-colors ${
              year === y ? 'bg-bg-3 text-ink-0' : 'text-ink-3 hover:text-ink-0'
            }`}
          >
            {y}
          </button>
        ))}
      </div>
    </div>
  )
}

// ─── Progress bar ─────────────────────────────────────────────────────────

function SlideProgress({ total, idx, onJump }) {
  return (
    <div className="flex gap-1">
      {Array.from({ length: total }).map((_, i) => (
        <button
          key={i}
          onClick={() => onJump(i)}
          className="flex-1 h-1 bg-bg-2 rounded overflow-hidden group cursor-pointer"
          aria-label={`Ir a slide ${i + 1}`}
        >
          <div
            className={`h-full transition-all ${
              i < idx ? 'bg-ink-3 w-full' : i === idx ? 'bg-ink-0 w-full' : 'w-0'
            }`}
          />
        </button>
      ))}
    </div>
  )
}

// ─── Slide stage ──────────────────────────────────────────────────────────

function SlideStage({ slide, year }) {
  const tone = slide.tone || 'neutral'
  const bgClass = TONE_BG[tone] || TONE_BG.neutral
  const accent = TONE_ACCENT[tone] || TONE_ACCENT.neutral

  return (
    <div
      className={`relative bg-gradient-to-br ${bgClass} bg-bg-1 border border-line/50 rounded-lg overflow-hidden`}
      style={{ minHeight: '420px' }}
    >
      <div className="absolute inset-0 flex flex-col justify-between p-6 sm:p-10">
        {/* Top: eyebrow */}
        <div className="flex items-center gap-2">
          <Sparkles size={14} strokeWidth={1.75} className={accent} />
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
            {slide.metric?.label || `${year}`}
          </span>
        </div>

        {/* Middle: metric + title */}
        <div className="space-y-3 max-w-2xl">
          {slide.metric?.value && slide.kind !== 'intro' && slide.kind !== 'outro' && (
            <div className={`text-5xl sm:text-7xl font-medium tabular tracking-tight ${
              tone === 'positive' ? 'text-rendi-pos'
              : tone === 'negative' ? 'text-rendi-neg'
              : 'text-ink-0'
            }`}>
              {slide.metric.value}
            </div>
          )}
          {(slide.kind === 'intro' || slide.kind === 'outro') && slide.metric?.value && (
            <div className="text-4xl sm:text-6xl font-medium tabular tracking-tight text-ink-0">
              {slide.metric.value}
            </div>
          )}
          <h2 className="text-xl sm:text-2xl font-medium text-ink-0 leading-tight">
            {slide.title}
          </h2>
          {slide.subtitle && (
            <p className="text-sm sm:text-base text-ink-2 leading-relaxed max-w-xl">
              {slide.subtitle}
            </p>
          )}
        </div>

        {/* Bottom: stats */}
        {slide.stats?.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-3 border-t border-line/40">
            {slide.stats.slice(0, 4).map((s, i) => (
              <div key={i}>
                <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none mb-1.5">
                  {s.label}
                </div>
                <div className="text-sm font-medium text-ink-0 tabular leading-none">
                  {s.value}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── spec builder para shareCard ──────────────────────────────────────────

function specFromSlide(slide, year) {
  return {
    kind: 'performance',
    eyebrow: slide.metric?.label || `Wrapped ${year}`,
    title: slide.metric?.value && slide.kind !== 'intro' && slide.kind !== 'outro'
      ? slide.metric.value
      : slide.title,
    subtitle: slide.kind === 'intro' || slide.kind === 'outro'
      ? slide.subtitle
      : slide.title === slide.metric?.value ? slide.subtitle : slide.title,
    stats: slide.stats || [],
    pill: { label: `Wrapped ${year}`, tone: TONE_PILL[slide.tone] || 'gray' },
    date: String(year),
  }
}
