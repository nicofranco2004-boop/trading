// AnalyzeButton — el botón "✦ Analizar" de cada pantalla.
// ═══════════════════════════════════════════════════════════════════════════
// Le pregunta a Rendi por lo que estás mirando. La respuesta cae en el
// acompañante flotante, no en un panel aparte.
//
// ANTES abría un panel lateral: análisis largo, se leía, se cerraba, y ahí
// terminaba. Si querías seguir tirando del hilo no había dónde — el panel
// permitía UNA repregunta y sólo en Pro, "no para tener una conversación
// encadenada" según su propio comentario.
//
// AHORA la respuesta llega a la conversación de siempre: es más corta, se
// puede escuchar, se le puede contestar, y sigue ahí cuando te vas a otra
// sección. La pregunta la escribe el servidor a partir de `screen` — ver
// backend/ai/preguntas.py, que explica por qué no la arma el navegador.
//
// Sigue costando un ANÁLISIS del plan, no una consulta: cambió dónde aparece
// la respuesta, no cuánto vale.
//
// Variants:
//   - 'default'  → botón estándar con borde violeta
//   - 'subtle'   → solo ícono (cuando el botón vive en una barra apretada)

import { Sparkles } from 'lucide-react'
import { useVoz } from '../../contexts/VozContext'
import { track } from '../../utils/track'

export default function AnalyzeButton({
  screen,
  params,
  // title/subtitle eran los encabezados del panel. Ya no hay panel: la
  // pregunta que se ve arriba de la respuesta hace ese trabajo. Se siguen
  // aceptando para no tener que tocar los ~20 lugares que los pasan.
  title,       // eslint-disable-line no-unused-vars
  subtitle,    // eslint-disable-line no-unused-vars
  variant = 'default',
  label = 'Analizar',
  className = '',
}) {
  const { analizar } = useVoz()

  function handleClick() {
    track('ai_analyze_opened', { screen })
    analizar({ screen, params })
  }

  if (variant === 'subtle') {
    return (
      <button
        onClick={handleClick}
        aria-label={label}
        title={label}
        className={`inline-flex items-center justify-center w-8 h-8 rounded-sm text-data-violet hover:bg-data-violet/10 transition-colors ${className}`}
      >
        <Sparkles size={14} strokeWidth={1.75} />
      </button>
    )
  }

  return (
    <button
      onClick={handleClick}
      className={`inline-flex items-center gap-1.5 text-xs font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors press ${className}`}
    >
      <Sparkles size={12} strokeWidth={1.75} />
      {label}
    </button>
  )
}
