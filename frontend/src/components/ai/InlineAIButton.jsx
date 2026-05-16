// InlineAIButton — botón ✦ chico para usar dentro de celdas de tabla u otros
// contextos donde AskAIAbout (que usa un <div relative>) rompe la semántica
// HTML (típicamente <tr> y <td>).
//
// Usage:
//   <InlineAIButton
//     topic="position"
//     params={{ asset: p.asset, broker: p.broker }}
//     subtitle={`${p.asset} · ${p.broker}`}
//   />
//
// UX:
//   - Botón compacto (16x16) con el icono Sparkles violeta.
//   - Click → abre AnalysisDrawer.
//   - Trackea ai_analyze_opened con source='inline_button'.

import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { track } from '../../utils/track'
import AnalysisDrawer from './AnalysisDrawer'

export default function InlineAIButton({
  topic,
  params,
  subtitle,
  title = 'Análisis',
  ariaLabel = 'Analizar con IA',
  size = 13,
  className = '',
}) {
  const [open, setOpen] = useState(false)

  function handleClick(e) {
    e.stopPropagation()
    e.preventDefault()
    track('ai_analyze_opened', { screen: topic, source: 'inline_button' })
    setOpen(true)
  }

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        aria-label={ariaLabel}
        title={ariaLabel}
        className={[
          'inline-flex items-center justify-center w-6 h-6 rounded-sm',
          'text-data-violet/70 hover:text-data-violet',
          'hover:bg-data-violet/10 border border-transparent hover:border-data-violet/30',
          'transition-colors',
          className,
        ].join(' ')}
      >
        <Sparkles size={size} strokeWidth={1.75} />
      </button>
      {open && (
        <AnalysisDrawer
          open
          onClose={() => setOpen(false)}
          screen={topic}
          params={params}
          title={title}
          subtitle={subtitle}
        />
      )}
    </>
  )
}
