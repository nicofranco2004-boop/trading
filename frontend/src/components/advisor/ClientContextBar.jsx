// ClientContextBar — barra persistente mientras el asesor mira la cuenta de
// un cliente (Plan Asesor). Vive arriba del content area en ambos shells.
// ═══════════════════════════════════════════════════════════════════════════
// Diseño: banda violeta finita, imposible de confundir con la app "normal" —
// el asesor SIEMPRE sabe de quién es la cuenta que está viendo y tiene la
// salida a un click. "Volver" limpia el contexto (header fuera) y vuelve al
// roster (/clientes).
//
// En el celular va ADENTRO de la barra de arriba (MobileTopBar la dibuja con
// `enLaBarra`), debajo de la cinta de cotizaciones. Antes iba en el contenido,
// pegada a 64 px del borde: eso era el alto de la barra hasta que se le sumó la
// cinta (≈93 px), y desde entonces al bajar la pantalla quedaba escondida
// detrás. Adentro de la barra no hay ningún alto que mantener sincronizado.
// La copia del contenido se apaga en el celular con el MISMO useIsMobile con el
// que App.jsx elige el armado de celular o de compu.

import { useNavigate } from 'react-router-dom'
import { Eye, ArrowLeft } from 'lucide-react'
import { useAdvisorContext } from '../../contexts/AdvisorContext'
import { useIsMobile } from '../../hooks/useIsMobile'

export default function ClientContextBar({ enLaBarra = false }) {
  const { clientCtx, exitClient } = useAdvisorContext()
  const navigate = useNavigate()
  const isMobile = useIsMobile()

  if (!clientCtx) return null
  if (isMobile !== enLaBarra) return null

  const onExit = () => {
    exitClient()
    navigate('/clientes')
  }

  return (
    <div className={`${enLaBarra ? 'border-t' : 'sticky top-0 z-20 border-b'} border-data-violet/30 flex items-center gap-2.5 px-4 py-2 bg-data-violet/[0.12] backdrop-blur-sm`}>
      <Eye size={14} strokeWidth={1.75} className="text-data-violet flex-shrink-0" aria-hidden="true" />
      <p className="flex-1 min-w-0 text-[13px] text-ink-1 truncate">
        Estás viendo la cuenta de{' '}
        <span className="font-semibold text-ink-0">{clientCtx.label || `Cliente ${clientCtx.id}`}</span>
        <span className="hidden sm:inline text-ink-3"> · visión Pro (tu plan Asesor)</span>
      </p>
      <button
        type="button"
        onClick={onExit}
        className="inline-flex items-center gap-1.5 text-xs font-medium text-data-violet hover:text-ink-0 bg-data-violet/10 hover:bg-data-violet/25 border border-data-violet/40 rounded-md px-2.5 py-1.5 transition-colors flex-shrink-0"
      >
        <ArrowLeft size={12} strokeWidth={2} aria-hidden="true" />
        Volver a mis clientes
      </button>
    </div>
  )
}
