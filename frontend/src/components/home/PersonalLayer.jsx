// PersonalLayer — "Lo que te afecta" (V2).
// Grid de cards Panel compactas. Cada card: icon + headline + value tabular + cta.
// Solo se renderiza si el user tiene portfolio.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../../utils/api'
import Panel from '../Panel'
import Eyebrow from '../Eyebrow'

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
        <Eyebrow>Lo que te afecta</Eyebrow>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-24 rounded bg-bg-1 border border-line animate-pulse" />
          ))}
        </div>
      </section>
    )
  }

  if (cards.length === 0) return null

  return (
    <section>
      <Eyebrow>Lo que te afecta</Eyebrow>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-2">
        {cards.map((c, i) => {
          const Wrapper = c.cta_href ? Link : 'div'
          const wrapperProps = c.cta_href ? { to: c.cta_href } : {}
          return (
            <Wrapper key={`${c.kind}-${i}`} {...wrapperProps} className="block">
              <Panel padding="sm" hoverable={!!c.cta_href} className="h-full">
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="text-base leading-none" aria-hidden="true">{c.icon}</span>
                  <span className={`text-sm font-medium num tabular ${TONE[c.value_tone] || TONE.neutral} flex-1 text-right`}>
                    {c.value}
                  </span>
                </div>
                <div className="text-sm text-ink-1 leading-snug">{c.headline}</div>
                {c.context && (
                  <div className="text-[10px] text-ink-3 mt-0.5 font-mono">{c.context}</div>
                )}
                {c.cta_label && (
                  <div className="text-[10px] text-rendi-pos mt-1.5 font-mono uppercase tracking-caps">{c.cta_label}</div>
                )}
              </Panel>
            </Wrapper>
          )
        })}
      </div>
    </section>
  )
}
