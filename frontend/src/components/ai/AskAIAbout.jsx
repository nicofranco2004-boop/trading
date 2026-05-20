// AskAIAbout — wrapper que agrega un "Preguntar a la IA" a CUALQUIER componente.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint AI v2 — patrón "AI everywhere". Envolvés cualquier sección del
// producto (un chart, una tabla, una card, una lista de eventos) y queda
// con un ✦ pequeño en la esquina superior derecha que aparece al hover.
//
// UX:
//   - Desktop: ✦ aparece con fade al hover, top-right del wrapper
//   - Mobile: ✦ siempre visible pero chico (cuando isMobile)
//   - Double-click sobre el wrapper → atajo de power user (también abre)
//   - Tooltip "Preguntar a la IA sobre esto" en hover del botón
//   - Click del ✦ NO propaga al wrapper (no rompe interacciones del child)
//
// Topic: usa la registry del backend (notación con puntos):
//   dashboard.composition · dashboard.evolution · dashboard.top_holdings
//
// Uso:
//   <AskAIAbout
//     topic="dashboard.composition"
//     subtitle="Composición del portfolio"
//   >
//     <ComponentePropio />
//   </AskAIAbout>

import { useState, useEffect } from 'react'
import { Sparkles } from 'lucide-react'
import { useIsMobile } from '../../hooks/useIsMobile'
import { track } from '../../utils/track'
import AnalysisDrawer from './AnalysisDrawer'
import { isAIDiscovered, markAIDiscovered } from './AIDiscoveryBanner'

export default function AskAIAbout({
  topic,
  params,
  subtitle,
  title = 'Análisis',
  children,
  className = '',
  enableDoubleClick = true,
  // Si el child tiene padding propio, podés desactivar el rounded del wrapper
  rounded = true,
}) {
  const [open, setOpen] = useState(false)
  const [hovered, setHovered] = useState(false)
  // Si el user NUNCA descubrió la feature, dejamos el ✦ siempre visible
  // (con un pulse sutil) hasta el primer click. Después pasa a hover-only.
  const [discovered, setDiscovered] = useState(true)
  const isMobile = useIsMobile()

  // Refresh discovered flag al montar — sigue al banner si el user lo cierra
  useEffect(() => {
    setDiscovered(isAIDiscovered())
    function onStorage(e) {
      if (e.key === 'rendi_ai_discovered') setDiscovered(isAIDiscovered())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  function openDrawer(source) {
    if (!discovered) {
      markAIDiscovered()
      setDiscovered(true)
    }
    track('ai_analyze_opened', { screen: topic, source })
    setOpen(true)
  }

  // Double-click detection (sin pasar por el child)
  function handleDoubleClick(e) {
    if (!enableDoubleClick) return
    // Si el target es un <button>, <a>, <input> — no robarse el dbl-click
    const tag = (e.target?.tagName || '').toLowerCase()
    if (['button', 'a', 'input', 'select', 'textarea'].includes(tag)) return
    e.preventDefault()
    openDrawer('dblclick')
  }

  return (
    <div
      className={`relative ${className}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onDoubleClick={handleDoubleClick}
    >
      {/* Children — el componente real (chart, tabla, etc.) */}
      {children}

      {/* Botón flotante — top-right del wrapper.
          Desktop: solo ícono que aparece al hover (UX minimalista).
          Mobile:  pill "✦ Analizar" siempre visible, más prominente —
                   no hay hover, hay que dar señal visual clara. */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          openDrawer('hover_button')
        }}
        aria-label="Analizar con IA"
        title="Analizar con IA"
        className={[
          'absolute z-10 inline-flex items-center justify-center',
          'top-2 right-2',
          'bg-bg-1/95 backdrop-blur-sm border text-data-violet',
          'transition-all duration-150',
          isMobile
            // Mobile: pill con icono + label, mayor área tappable
            ? 'h-8 px-2.5 gap-1 rounded-sm border-data-violet/45 shadow-sm shadow-data-violet/10 active:bg-data-violet/15 text-[11px] font-medium'
            // Desktop: solo icono, hover-reveal (o always-on en pre-discovery)
            : [
              rounded ? 'w-7 h-7 rounded-sm' : 'w-6 h-6 rounded-sm',
              !discovered
                ? 'opacity-100 border-data-violet/70 shadow-md shadow-data-violet/20 hover:bg-data-violet/15 ai-discover-pulse'
                : hovered
                  ? 'opacity-100 translate-y-0 border-data-violet/40 hover:bg-data-violet/15 hover:border-data-violet/60'
                  : 'opacity-0 -translate-y-1 pointer-events-none border-data-violet/40',
            ].join(' '),
        ].join(' ')}
      >
        <Sparkles size={isMobile ? 12 : 13} strokeWidth={1.75} />
        {isMobile && <span>Analizar</span>}
      </button>

      {/* Pulse animation para pre-discovery */}
      {!discovered && (
        <style>{`
          @keyframes ai-discover-pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(125, 140, 255, 0.4); }
            50%      { box-shadow: 0 0 0 5px rgba(125, 140, 255, 0); }
          }
          .ai-discover-pulse { animation: ai-discover-pulse 2.2s ease-in-out infinite; }
        `}</style>
      )}

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
    </div>
  )
}
