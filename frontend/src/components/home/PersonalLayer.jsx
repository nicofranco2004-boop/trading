// PersonalLayer — "Lo que te afecta" (V2).
// Grid de cards Panel compactas. Cada card: icon + headline + value tabular + cta.
// Solo se renderiza si el user tiene portfolio.
//
// Movimiento (2026-09-29): al entrar en pantalla las tarjetas aparecen de a una
// y el porcentaje cuenta hasta su valor. Para contar hace falta el número, no
// el texto: lo manda el servidor en `value_num` (home/briefing.py). Una tarjeta
// sin número (un balance que se viene) muestra `value` tal cual.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { TrendingUp, TrendingDown, BarChart3, Coins, Bell } from 'lucide-react'
import { api } from '../../utils/api'
import { pctVar } from '../../utils/format'
import { useAlVerse } from '../../hooks/useAlVerse'
import AnimatedNumber from '../AnimatedNumber'
import Panel from '../Panel'
import Eyebrow from '../Eyebrow'

const TONE = {
  positive: 'text-rendi-pos',
  negative: 'text-rendi-neg',
  neutral:  'text-ink-1',
}

// Mapeo kind → icono lucide. Reemplaza los emojis que mandaba el backend.
function iconFor(card) {
  switch (card.kind) {
    case 'holding_move':
      return card.value_tone === 'negative' ? TrendingDown : TrendingUp
    case 'earnings_soon':
      return BarChart3
    case 'dividend_soon':
      return Coins
    default:
      return Bell
  }
}

const ICON_TONE = {
  positive: 'text-rendi-pos',
  negative: 'text-rendi-neg',
  neutral:  'text-ink-2',
}

export default function PersonalLayer() {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [ref, visto] = useAlVerse()

  useEffect(() => {
    let cancelled = false
    api.get('/home/personal')
      .then(d => { if (!cancelled) setCards(d.cards || []) })
      .catch(() => { if (!cancelled) setCards([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  if (!loading && cards.length === 0) return null

  return (
    <section ref={ref}>
      <Eyebrow>Lo que te afecta</Eyebrow>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 mt-2">
        {loading && Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-24 rounded bg-bg-1 border border-line esqueleto" />
        ))}
        {cards.map((c, i) => {
          const Wrapper = c.cta_href ? Link : 'div'
          const wrapperProps = c.cta_href ? { to: c.cta_href } : {}
          const Icon = iconFor(c)
          const iconClass = ICON_TONE[c.value_tone] || ICON_TONE.neutral
          return (
            <Wrapper
              key={`${c.kind}-${i}`}
              {...wrapperProps}
              className={`block ${visto ? 'entra' : 'por-entrar'}`}
              style={{ '--i': i }}
            >
              <Panel padding="sm" hoverable={!!c.cta_href} className="h-full">
                <div className="flex items-center gap-2 mb-1">
                  <span className="inline-flex items-center justify-center w-6 h-6 rounded-sm bg-bg-2 flex-shrink-0" aria-hidden="true">
                    <Icon size={13} strokeWidth={1.75} className={iconClass} />
                  </span>
                  <span className={`text-sm font-medium num tabular ${TONE[c.value_tone] || TONE.neutral} flex-1 text-right`}>
                    {typeof c.value_num === 'number'
                      ? <AnimatedNumber value={visto ? c.value_num : 0} format={n => pctVar(n, 1)} />
                      : c.value}
                  </span>
                </div>
                <div className="text-sm text-ink-1 leading-snug">{c.headline}</div>
                {c.context && (
                  <div className="text-[12px] text-ink-3 mt-0.5 num tabular">{c.context}</div>
                )}
                {c.cta_label && (
                  <div className="text-[12.5px] text-rendi-pos mt-1.5 font-medium">{c.cta_label}</div>
                )}
              </Panel>
            </Wrapper>
          )
        })}
      </div>
    </section>
  )
}
