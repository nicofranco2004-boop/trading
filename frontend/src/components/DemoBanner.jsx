// DemoBanner — barra superior persistente cuando el user está en modo demo.
// ═══════════════════════════════════════════════════════════════════════════
// Visible en TODAS las pages. Recordatorio sutil de que la data es simulada
// + CTA para crear cuenta real. Sticky abajo del Sidebar para no tapar el
// contenido pero estar siempre visible.

import { useNavigate } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { Sparkles, ArrowRight } from 'lucide-react'

export default function DemoBanner() {
  const { isDemo, exitDemo } = useAuth()
  const navigate = useNavigate()
  if (!isDemo) return null

  // El CTA del demo es el momento de MÁXIMA intención de conversión. Antes
  // exitDemo() solo limpiaba el modo demo y dejaba al user en la Landing — un
  // callejón. Ahora lo llevamos directo al form de registro.
  function handleCreateAccount() {
    exitDemo()
    navigate('/login?mode=register')
  }

  return (
    <div
      className="sticky top-0 z-40 border-b border-data-violet/30 bg-bg-1/95 backdrop-blur-sm"
      style={{ borderTopWidth: '1px', borderTopColor: 'rgba(139,125,255,0.3)' }}
    >
      <div className="flex items-center justify-between gap-3 px-4 py-2 max-w-7xl mx-auto">
        <div className="flex items-center gap-2 min-w-0">
          <Sparkles size={13} strokeWidth={1.75} className="text-data-violet flex-shrink-0" aria-hidden="true" />
          <p className="text-xs text-ink-1 truncate">
            <span className="font-medium text-ink-0">Modo demo activo.</span>{' '}
            <span className="text-ink-3">Estás viendo data simulada. Para usar Rendi con tu cartera real, creá una cuenta.</span>
          </p>
        </div>
        <button
          onClick={handleCreateAccount}
          className="flex-shrink-0 inline-flex items-center gap-1 text-xs bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors"
        >
          Crear cuenta
          <ArrowRight size={11} strokeWidth={2} />
        </button>
      </div>
    </div>
  )
}
