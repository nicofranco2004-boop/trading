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
// Dispatcher: cada kind tiene un layout específico para sacarle jugo al espacio.
// Los kinds genéricos (stats, dominant_bias) caen al layout default.

function SlideStage({ slide, year }) {
  const tone = slide.tone || 'neutral'
  const bgClass = TONE_BG[tone] || TONE_BG.neutral
  const accent = TONE_ACCENT[tone] || TONE_ACCENT.neutral
  const accentHex =
    tone === 'positive' ? '#21D07A' :
    tone === 'negative' ? '#FF5360' :
    '#4E83FF'

  // Header común a todos los layouts
  const eyebrow = (
    <div className="flex items-center gap-2">
      <Sparkles size={14} strokeWidth={1.75} className={accent} />
      <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
        {slide.metric?.label || `${year}`}
      </span>
    </div>
  )

  return (
    <div
      className={`relative bg-gradient-to-br ${bgClass} bg-bg-1 border border-line/50 rounded-lg overflow-hidden`}
      style={{ minHeight: '480px' }}
    >
      <div className="absolute inset-0 flex flex-col justify-between p-6 sm:p-10">
        {eyebrow}
        <SlideContent slide={slide} tone={tone} accentHex={accentHex} year={year} />
      </div>
    </div>
  )
}

function SlideContent({ slide, tone, accentHex, year }) {
  // ─── Layout específico por kind ─────────────────────────────────────────
  if (slide.kind === 'intro') return <IntroLayout slide={slide} year={year} />
  if (slide.kind === 'outro') return <OutroLayout slide={slide} />
  if (slide.kind === 'pnl') return <PnlLayout slide={slide} tone={tone} />
  if (slide.kind === 'vs_benchmark' || slide.kind === 'vs_inflation') {
    return <VsLayout slide={slide} tone={tone} accentHex={accentHex} />
  }
  if (slide.code === 'activity') return <ActivityLayout slide={slide} accentHex={accentHex} />
  if (slide.kind === 'best_trade') return <BestTradeLayout slide={slide} />
  if (slide.kind === 'dominant_bias') return <BiasLayout slide={slide} tone={tone} />
  // Default (best_month, worst_month, no_data, fallback)
  return <DefaultLayout slide={slide} tone={tone} />
}

// ─── Layouts ──────────────────────────────────────────────────────────────

function IntroLayout({ slide, year }) {
  return (
    <>
      {/* Middle: año GIGANTE + titulo + subtitle */}
      <div className="space-y-3">
        <div className="text-7xl sm:text-9xl font-medium tabular tracking-tighter text-ink-0 leading-none">
          {year}
        </div>
        <h2 className="text-xl sm:text-3xl font-medium text-ink-0 leading-tight">
          {slide.title}
        </h2>
        <p className="text-sm sm:text-base text-ink-2 leading-relaxed max-w-xl">
          {slide.subtitle}
        </p>
      </div>

      {/* Bottom: teaser stats grid — vista rápida de qué incluye el wrapped */}
      {slide.stats?.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-4 border-t border-line/40">
          {slide.stats.slice(0, 4).map((s, i) => (
            <TeaserStat key={i} label={s.label} value={s.value} />
          ))}
        </div>
      )}
    </>
  )
}

function OutroLayout({ slide }) {
  return (
    <>
      <div className="space-y-3 max-w-xl">
        <div className="text-4xl sm:text-6xl font-medium tabular tracking-tight text-ink-0">
          {slide.metric?.value}
        </div>
        <h2 className="text-xl sm:text-2xl font-medium text-ink-0 leading-tight">
          {slide.title}
        </h2>
        <p className="text-sm sm:text-base text-ink-2 leading-relaxed">
          {slide.subtitle}
        </p>
      </div>
      <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 pt-4 border-t border-line/40">
        Tocá compartir para guardar o enviar cualquiera de los slides.
      </div>
    </>
  )
}

function PnlLayout({ slide, tone }) {
  const big = slide.metric?.value
  const isPositive = tone === 'positive'
  return (
    <>
      <div className="space-y-2">
        <div className={`text-6xl sm:text-8xl font-medium tabular tracking-tight ${
          isPositive ? 'text-rendi-pos' : tone === 'negative' ? 'text-rendi-neg' : 'text-ink-0'
        }`}>
          {slide.title}
        </div>
        <p className="text-base sm:text-lg text-ink-1">{slide.subtitle}</p>
        {big && (
          <p className={`text-2xl sm:text-3xl font-medium tabular ${
            isPositive ? 'text-rendi-pos' : tone === 'negative' ? 'text-rendi-neg' : 'text-ink-0'
          }`}>
            {big}
          </p>
        )}
      </div>

      {slide.stats?.length > 0 && (
        <div className="grid grid-cols-3 gap-3 pt-4 border-t border-line/40">
          {slide.stats.slice(0, 3).map((s, i) => (
            <TeaserStat key={i} label={s.label} value={s.value} />
          ))}
        </div>
      )}
    </>
  )
}

function VsLayout({ slide, tone, accentHex }) {
  const bars = slide.bars || []
  // Normalizar a fracciones. Calcular escala: max abs + algo de aire
  const maxAbs = Math.max(0.001, ...bars.map(b => Math.abs(Number(b.value) || 0)))
  const fmtPct = (v) => `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(2)}%`

  return (
    <>
      <div className="space-y-2">
        <h2 className="text-xl sm:text-3xl font-medium text-ink-0 leading-tight">
          {slide.title}
        </h2>
        <p className="text-sm sm:text-base text-ink-2 max-w-xl">{slide.subtitle}</p>
      </div>

      {bars.length > 0 && (
        <div className="space-y-2.5 pt-2">
          {bars.map((b, i) => {
            const v = Number(b.value) || 0
            const pctOfMax = Math.abs(v) / maxAbs
            const isHighlight = b.highlight
            const barColor = v >= 0
              ? (isHighlight ? '#21D07A' : '#46C6E0')
              : (isHighlight ? '#FF5360' : '#8B7DFF')
            return (
              <div key={i}>
                <div className="flex items-baseline justify-between mb-1">
                  <span className={`text-xs font-mono uppercase tracking-caps ${
                    isHighlight ? 'text-ink-0 font-semibold' : 'text-ink-3'
                  }`}>
                    {b.label}
                  </span>
                  <span className={`text-sm font-medium tabular ${
                    isHighlight ? 'text-ink-0' : 'text-ink-2'
                  }`}>
                    {fmtPct(v)}
                  </span>
                </div>
                <div className="h-3 bg-bg-2 rounded-sm overflow-hidden">
                  <div
                    className="h-full transition-all duration-500"
                    style={{
                      width: `${Math.max(2, pctOfMax * 100)}%`,
                      background: barColor,
                      opacity: isHighlight ? 1 : 0.6,
                    }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}

function ActivityLayout({ slide, accentHex }) {
  const bars = slide.bars || []
  const maxCount = Math.max(1, ...bars.map(b => Number(b.value) || 0))
  const total = slide.metric?.value
  const distinct = slide.stats?.find(s => s.label === 'Distintos activos')?.value

  return (
    <>
      <div className="space-y-2">
        <div className="text-6xl sm:text-7xl font-medium tabular tracking-tight text-ink-0">
          {total}
        </div>
        <h2 className="text-xl sm:text-2xl font-medium text-ink-0 leading-tight">
          {slide.title}
        </h2>
        <p className="text-sm sm:text-base text-ink-2">{slide.subtitle}</p>
      </div>

      <div className="space-y-3 pt-4 border-t border-line/40">
        <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
          Top activos operados
        </div>
        {bars.length > 0 ? bars.map((b, i) => {
          const w = (Number(b.value) / maxCount) * 100
          return (
            <div key={i} className="flex items-center gap-3">
              <div className="text-xs font-mono uppercase tracking-caps text-ink-2 w-16 flex-shrink-0">
                {b.label}
              </div>
              <div className="flex-1 h-2 bg-bg-2 rounded-sm overflow-hidden">
                <div
                  className="h-full bg-data-blue transition-all duration-500"
                  style={{ width: `${Math.max(4, w)}%`, opacity: 1 - i * 0.2 }}
                />
              </div>
              <div className="text-xs font-mono text-ink-1 tabular w-12 text-right flex-shrink-0">
                {b.value}×
              </div>
            </div>
          )
        }) : (
          <div className="text-xs text-ink-3">Sin datos.</div>
        )}
        {distinct && (
          <div className="text-[11px] text-ink-3 pt-1">
            Operaste {distinct} activos distintos este año.
          </div>
        )}
      </div>
    </>
  )
}

function BestTradeLayout({ slide }) {
  const asset = slide.stats?.find(s => s.label === 'Activo')?.value || slide.metric?.label
  const date = slide.stats?.find(s => s.label === 'Fecha')?.value
  return (
    <>
      <div className="space-y-2">
        <div className="text-2xl sm:text-3xl font-mono uppercase tracking-tight text-ink-3 leading-none">
          {asset}
        </div>
        <div className="text-5xl sm:text-7xl font-medium tabular tracking-tight text-rendi-pos">
          {slide.metric?.value}
        </div>
        <h2 className="text-xl sm:text-2xl font-medium text-ink-0 leading-tight pt-2">
          {slide.title}
        </h2>
        <p className="text-sm sm:text-base text-ink-2">{slide.subtitle}</p>
      </div>
      {date && (
        <div className="flex items-center justify-between pt-4 border-t border-line/40">
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">Fecha de cierre</span>
          <span className="text-sm font-mono tabular text-ink-1">{date}</span>
        </div>
      )}
    </>
  )
}

function BiasLayout({ slide, tone }) {
  return (
    <>
      <div className="space-y-3 max-w-2xl">
        <div className={`inline-flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-caps px-2 py-1 rounded-sm border ${
          tone === 'negative' ? 'bg-rendi-neg/[0.06] border-rendi-neg/25 text-rendi-neg'
          : tone === 'positive' ? 'bg-rendi-pos/[0.06] border-rendi-pos/25 text-rendi-pos'
          : 'bg-data-blue/[0.06] border-data-blue/25 text-data-blue'
        }`}>
          {slide.metric?.value}
        </div>
        <h2 className="text-2xl sm:text-4xl font-medium text-ink-0 leading-tight">
          {slide.title}
        </h2>
        <p className="text-sm sm:text-base text-ink-2 leading-relaxed">
          {slide.subtitle}
        </p>
      </div>

      {slide.stats?.length > 0 && (
        <div className="grid grid-cols-2 gap-3 pt-4 border-t border-line/40">
          {slide.stats.slice(0, 2).map((s, i) => (
            <TeaserStat key={i} label={s.label} value={s.value} />
          ))}
        </div>
      )}
    </>
  )
}

function DefaultLayout({ slide, tone }) {
  return (
    <>
      <div className="space-y-3 max-w-2xl">
        {slide.metric?.value && (
          <div className={`text-5xl sm:text-7xl font-medium tabular tracking-tight ${
            tone === 'positive' ? 'text-rendi-pos'
            : tone === 'negative' ? 'text-rendi-neg'
            : 'text-ink-0'
          }`}>
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
      {slide.stats?.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-3 border-t border-line/40">
          {slide.stats.slice(0, 4).map((s, i) => (
            <TeaserStat key={i} label={s.label} value={s.value} />
          ))}
        </div>
      )}
    </>
  )
}

function TeaserStat({ label, value }) {
  return (
    <div>
      <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none mb-1.5">
        {label}
      </div>
      <div className="text-base sm:text-lg font-medium text-ink-0 tabular leading-none">
        {value}
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
