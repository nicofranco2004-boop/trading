// ClientContextBar — barra persistente mientras el asesor mira la cuenta de
// un cliente (Plan Asesor). Vive arriba del content area en ambos shells.
// ═══════════════════════════════════════════════════════════════════════════
// Diseño: banda violeta finita, imposible de confundir con la app "normal" —
// el asesor SIEMPRE sabe de quién es la cuenta que está viendo y tiene la
// salida a un click. "Volver" limpia el contexto (header fuera) y vuelve al
// roster (/clientes).
//
// En el celular va ADENTRO de la barra de arriba (App.jsx la pasa a
// MobileTopBar con `enLaBarra`), debajo de la cinta de cotizaciones. Antes iba
// en el contenido, pegada a 64 px del borde: eso era el alto de la barra hasta
// que se le sumó la cinta (≈93 px), y desde entonces al bajar quedaba
// escondida detrás. Ver components/mobile/avisos.js.

import { useNavigate } from 'react-router-dom'
import { Eye, ArrowLeft } from 'lucide-react'
import { useAdvisorContext } from '../../contexts/AdvisorContext'
import { ubicacionDeAviso } from '../mobile/avisos'
import { nombreDelCliente } from '../../utils/navegacion'

export default function ClientContextBar({ enLaBarra = false }) {
  const { clientCtx, exitClient } = useAdvisorContext()
  const navigate = useNavigate()

  if (!clientCtx) return null

  const onExit = () => {
    exitClient()
    navigate('/clientes')
  }

  return (
    <div className={`${ubicacionDeAviso(enLaBarra, { delante: false })} border-data-violet/30 flex items-center gap-2.5 px-4 py-2 bg-data-violet/[0.12] backdrop-blur-sm`}>
      <Eye size={14} strokeWidth={1.75} className="text-data-violet flex-shrink-0" aria-hidden="true" />
      {/* En el celular, corto: a 360-375 px "Estás viendo la cuenta de" más
          "Volver a mis clientes" no dejaban lugar y el NOMBRE del cliente —lo
          único que importa— quedaba cortado. */}
      <p className="flex-1 min-w-0 text-[13px] text-ink-1 truncate">
        {enLaBarra ? 'Cuenta de' : 'Estás viendo la cuenta de'}{' '}
        <span className="font-semibold text-ink-0">{nombreDelCliente(clientCtx)}</span>
        {!enLaBarra && <span className="hidden sm:inline text-ink-3"> · visión Pro (tu plan Asesor)</span>}
      </p>
      <button
        type="button"
        onClick={onExit}
        aria-label="Volver a mis clientes"
        className="inline-flex items-center gap-1.5 text-xs font-medium text-data-violet hover:text-ink-0 bg-data-violet/10 hover:bg-data-violet/25 border border-data-violet/40 rounded-md px-2.5 py-1.5 transition-colors flex-shrink-0"
      >
        <ArrowLeft size={12} strokeWidth={2} aria-hidden="true" />
        {enLaBarra ? 'Volver' : 'Volver a mis clientes'}
      </button>
    </div>
  )
}
