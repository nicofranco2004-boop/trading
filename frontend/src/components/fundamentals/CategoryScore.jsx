// CategoryScore — card de una de las 4 categorías del scorecard.
// ═══════════════════════════════════════════════════════════════════════════
// props: { icon (lucide component), label, question, score (0-100|null) }
// Barra horizontal coloreada (width=score%) + número grande a la derecha.
// Color por score: >=70 verde, >=40 ámbar, <40 rojo. null → "Sin datos".

function colorFor(score) {
  if (score == null) return { bar: 'bg-ink-3', text: 'text-ink-3' }
  if (score >= 70) return { bar: 'bg-rendi-pos', text: 'text-rendi-pos' }
  if (score >= 40) return { bar: 'bg-rendi-warn', text: 'text-rendi-warn' }
  return { bar: 'bg-rendi-neg', text: 'text-rendi-neg' }
}

export default function CategoryScore({ icon: Icon, label, question, score }) {
  const c = colorFor(score)
  const hasScore = typeof score === 'number' && !Number.isNaN(score)
  const width = hasScore ? Math.max(0, Math.min(100, score)) : 0

  return (
    <div className="bg-bg-1 border border-line rounded p-4 flex flex-col gap-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0">
          {Icon && (
            <span className="mt-0.5 text-ink-3 flex-shrink-0">
              <Icon size={16} strokeWidth={1.75} />
            </span>
          )}
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink-0 leading-tight">{label}</p>
            {question && (
              <p className="text-xs text-ink-3 mt-0.5 leading-snug">{question}</p>
            )}
          </div>
        </div>
        <span className={`text-2xl font-semibold tabular leading-none flex-shrink-0 ${c.text}`}>
          {hasScore ? width : '—'}
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-bg-2 overflow-hidden">
        <div
          className={`h-full rounded-full ${c.bar}`}
          style={{ width: `${width}%`, transition: 'width 600ms ease-out' }}
        />
      </div>
    </div>
  )
}
