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
//   - Sin `label`: botón compacto (icono Sparkles violeta) para celdas densas.
//   - Con `label`: pill "✦ Analizar" con el mismo tratamiento que AnalyzeButton
//     (bg-data-violet/10, texto data-violet, borde /30) para que el usuario vea
//     que puede pedir el análisis on-demand. Reutilizado en Novedades.
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
  label,
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

  // Con label → pill con texto (mismo look que AnalyzeButton default).
  // Sin label → botón-icono compacto (comportamiento histórico en tablas).
  const buttonClass = label
    ? [
        'inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-sm',
        'bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30',
        'transition-colors press',
        className,
      ].join(' ')
    : [
        'inline-flex items-center justify-center w-6 h-6 rounded-sm',
        'text-data-violet/70 hover:text-data-violet',
        'hover:bg-data-violet/10 border border-transparent hover:border-data-violet/30',
        'transition-colors',
        className,
      ].join(' ')

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        aria-label={ariaLabel}
        title={ariaLabel}
        className={buttonClass}
      >
        <Sparkles size={label ? 12 : size} strokeWidth={1.75} />
        {label}
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
