// AvisoNotificaciones — el cartel que explica por qué las notificaciones no se
// pueden activar en este dispositivo y qué hacer. Lo usan todas las pantallas
// que ofrecen «Activar»: la lista de primeros pasos, Más, Alertas y la alerta
// de clientes del asesor. Los textos viven en utils/notificaciones.js.
//
// En iPhone sin Rendi en el inicio trae el botón «Ver cómo agregarla», que abre
// el mismo paso a paso de «Descargar app» (InstalarAppModal) ahí mismo.
import { useEffect, useState } from 'react'
import { BellOff, Smartphone } from 'lucide-react'
import InstalarAppModal, { precargarFotosDeInstalar } from './InstalarAppModal'
import { textoSinPush } from '../utils/notificaciones'

export default function AvisoNotificaciones({ motivo, plataforma, origen, className = '' }) {
  const [instalarOpen, setInstalarOpen] = useState(false)
  const texto = textoSinPush(motivo, plataforma, typeof navigator === 'undefined' ? '' : navigator.userAgent)
  // Si el cartel ofrece el paso a paso, las fotos se piden ya: en Safari tardan
  // en aparecer si se piden recién al abrirlo (ver InstalarAppModal).
  useEffect(() => { if (texto?.boton) precargarFotosDeInstalar() }, [texto?.boton])
  if (!texto) return null

  const Icono = motivo === 'iphone-sin-instalar' ? Smartphone : BellOff
  return (
    <div role="status" className={`bg-data-violet/[0.04] border border-data-violet/30 rounded-xl p-3.5 ${className}`}>
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-full bg-data-violet/15 text-data-violet flex items-center justify-center flex-shrink-0">
          <Icono size={16} strokeWidth={1.75} aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink-0 leading-snug">{texto.titulo}</p>
          <p className="text-xs text-ink-2 leading-relaxed mt-1">{texto.cuerpo}</p>
          {texto.boton && (
            <button type="button" onClick={() => setInstalarOpen(true)}
              className="mt-3 inline-flex items-center justify-center gap-1.5 bg-data-violet hover:bg-data-violet/90 text-white text-xs font-medium rounded px-3.5 py-2 transition-colors press">
              <Smartphone size={13} strokeWidth={2} aria-hidden="true" />
              {texto.boton}
            </button>
          )}
        </div>
      </div>
      <InstalarAppModal open={instalarOpen} onClose={() => setInstalarOpen(false)} origen={origen} />
    </div>
  )
}
