// AnalysisCard — render del output estructurado del LLM.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint AI v2. Renderiza el schema { tldr, sections[], follow_ups[] } con
// el sistema visual V2 (cold neutrals, mono caps, tabular). NO chat bubbles,
// NO timestamps, NO "typing dots" — solo texto bien tipografiado.

import { ArrowRight, AlertTriangle, TrendingUp, TrendingDown, Info } from 'lucide-react'

const TONE_CLASSES = {
  neutral:  { accent: 'text-ink-1',     iconCls: 'text-ink-3',     Icon: Info },
  positive: { accent: 'text-rendi-pos', iconCls: 'text-rendi-pos', Icon: TrendingUp },
  negative: { accent: 'text-rendi-neg', iconCls: 'text-rendi-neg', Icon: TrendingDown },
  warning:  { accent: 'text-rendi-warn', iconCls: 'text-rendi-warn', Icon: AlertTriangle },
}

export default function AnalysisCard({
  result,
  onFollowUp,
  followUpsDisabled = false,
  hideFollowUps = false,
}) {
  if (!result) return null

  return (
    <div className="space-y-5">
      {/* TLDR — lo primero que se lee, sin preámbulo */}
      {result.tldr && (
        <p className="text-base sm:text-lg font-medium text-ink-0 leading-snug">
          {result.tldr}
        </p>
      )}

      {/* Sections — eyebrow mono caps + body + acento por tone */}
      {Array.isArray(result.sections) && result.sections.length > 0 && (
        <div className="space-y-4">
          {result.sections.map((s, i) => {
            const tone = TONE_CLASSES[s.tone] || TONE_CLASSES.neutral
            const Icon = tone.Icon
            return (
              <section key={i} className="space-y-1.5">
                <div className="flex items-center gap-1.5">
                  <Icon size={11} strokeWidth={1.75} className={tone.iconCls} />
                  <h3 className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none">
                    {s.title}
                  </h3>
                </div>
                <p className={`text-sm leading-relaxed ${tone.accent}`}>
                  {s.body}
                </p>
              </section>
            )
          })}
        </div>
      )}

      {/* Follow-ups — chips clickeables. Solo se muestran si NO estamos
          dentro de un FollowUpBlock (hideFollowUps=true) y si hay handler. */}
      {!hideFollowUps && Array.isArray(result.follow_ups) && result.follow_ups.length > 0 && (
        <div className="pt-3 border-t border-line/40">
          <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 mb-2">
            Profundizar
          </div>
          <div className="flex flex-wrap gap-1.5">
            {result.follow_ups.map((q, i) => (
              <button
                key={i}
                onClick={() => onFollowUp?.(q)}
                disabled={followUpsDisabled || !onFollowUp}
                className="inline-flex items-center gap-1 text-xs text-ink-1 hover:text-ink-0 bg-bg-2 hover:bg-bg-3 border border-line/60 px-2.5 py-1 rounded-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed text-left"
              >
                {q}
                <ArrowRight size={10} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
