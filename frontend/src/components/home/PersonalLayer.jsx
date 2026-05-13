// PersonalLayer — "Lo que te afecta". Cards de holdings que se mueven +
// earnings/dividendos próximos. Solo se renderiza si el user tiene portfolio.
//
// Backend: GET /api/home/personal → { cards: [...] }
// Card shape: { kind, icon, headline, value, value_tone, context, cta_href }

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../utils/api'

const TONE = {
  positive: 'text-rendi-pos',
  negative: 'text-rendi-neg',
  neutral:  'text-ink-1',
}

export default function PersonalLayer() {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    api.get('/home/personal')
      .then(d => { if (!cancelled) setCards(d.cards || []) })
      .catch(() => { if (!cancelled) setCards([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  if (loading) {
    return (
      <section>
        <h2 className="font-display text-sm uppercase tracking-wider text-ink-3 mb-2">
          Lo que te afecta
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-24 rounded-sm bg-bg-2 animate-pulse" />
          ))}
        </div>
      </section>
    )
  }

  // Sin cards: no renderizamos la sección (no agregamos ruido visual)
  if (cards.length === 0) return null

  return (
    <section>
      <h2 className="font-display text-sm uppercase tracking-wider text-ink-3 mb-2">
        Lo que te afecta
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {cards.map((c, i) => {
          const Wrapper = c.cta_href ? Link : 'div'
          const wrapperProps = c.cta_href ? { to: c.cta_href } : {}
          return (
            <Wrapper
              key={`${c.kind}-${i}`}
              {...wrapperProps}
              className="rounded-sm border border-line bg-bg-1 px-3 py-2.5 hover:bg-bg-2/40 transition-colors block"
            >
              <div className="flex items-baseline gap-2 mb-0.5">
                <span className="text-base leading-none" aria-hidden="true">{c.icon}</span>
                <span className={`text-sm font-mono tabular ${TONE[c.value_tone] || TONE.neutral} flex-1 text-right`}>
                  {c.value}
                </span>
              </div>
              <div className="text-sm text-ink-1 leading-snug">{c.headline}</div>
              {c.context && (
                <div className="text-[10px] text-ink-3 mt-0.5">{c.context}</div>
              )}
              {c.cta_label && (
                <div className="text-[10px] text-ink-2 mt-1">{c.cta_label}</div>
              )}
            </Wrapper>
          )
        })}
      </div>
    </section>
  )
}
