// AnalyzeButton — botón "✦ Analizar" reutilizable.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint AI v2. Trigger del AnalysisDrawer. Cada pantalla del producto
// monta uno con su `screen` + opcional `params`.
//
// Variants:
//   - 'default'  → botón estándar con borde violet
//   - 'subtle'   → solo ícono (cuando el botón vive en una toolbar densa)

import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import AnalysisDrawer from './AnalysisDrawer'
import { track } from '../../utils/track'

export default function AnalyzeButton({
  screen,
  params,
  title = 'Análisis',
  subtitle,
  variant = 'default',
  label = 'Analizar',
  className = '',
}) {
  const [open, setOpen] = useState(false)

  function handleClick() {
    track('ai_analyze_opened', { screen })
    setOpen(true)
  }

  if (variant === 'subtle') {
    return (
      <>
        <button
          onClick={handleClick}
          aria-label={label}
          title={label}
          className={`inline-flex items-center justify-center w-8 h-8 rounded-sm text-data-violet hover:bg-data-violet/10 transition-colors ${className}`}
        >
          <Sparkles size={14} strokeWidth={1.75} />
        </button>
        {open && (
          <AnalysisDrawer
            open
            onClose={() => setOpen(false)}
            screen={screen}
            params={params}
            title={title}
            subtitle={subtitle}
          />
        )}
      </>
    )
  }

  return (
    <>
      <button
        onClick={handleClick}
        className={`inline-flex items-center gap-1.5 text-xs font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors ${className}`}
      >
        <Sparkles size={12} strokeWidth={1.75} />
        {label}
      </button>
      {open && (
        <AnalysisDrawer
          open
          onClose={() => setOpen(false)}
          screen={screen}
          params={params}
          title={title}
          subtitle={subtitle}
        />
      )}
    </>
  )
}
