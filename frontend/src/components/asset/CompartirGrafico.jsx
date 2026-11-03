// CompartirGrafico — el botón «Compartir» del gráfico técnico de la ficha.
// ════════════════════════════════════════════════════════════════════════════
// Arma la imagen del gráfico tal como se está mirando (utils/imagenGrafico.js
// dice qué lleva; utils/shareCard.js la pinta) y abre la ventana de compartir
// de siempre (ShareCardModal): la vista previa y, en el celular, el compartir
// del sistema (WhatsApp y los demás) con la imagen; donde no se puede, la
// descarga y, si el navegador deja, «Copiar imagen».
//
// La imagen se arma AL TOCAR (`armar()`) y queda congelada: si mientras está
// abierta llega un precio nuevo o se mueve el gráfico, lo que se manda es lo
// que se vio en la vista previa. No lleva nada de tu cartera (ver imagenGrafico).
// `antes`: lo que el gráfico tiene que cambiar ANTES de armarla (con «Desde
// que lo tenés» pasa a «Todo»: ver LecturaTecnica). Entonces se arma recién
// después de que el gráfico se vuelve a dibujar (dos vueltas: en la primera el
// gráfico también vuelve su escala a automática), así la imagen es lo que se ve.
//
// Dónde va (LecturaTecnica): en la compu, en el encabezado del gráfico, con
// su nombre. En el celular ese renglón ya está lleno (pantalla completa, línea
// o velas, «1D» y «US$ · Todo» suman 340 de los 343 px de un iPhone de 375, y
// Nico pidió que sea UN renglón): ahí va el ícono solo, de 44 px, a la derecha
// de la ayuda que está pegada a las fechas. Es el mismo botón con otra clase
// (`className`), no otra versión (R6).
//
// La ventana va por portal al <body> y por encima de la pantalla completa del
// gráfico (z-70): sin eso, con el gráfico en grande se abría detrás. Mientras
// está abierta, las teclas no llegan al gráfico: Esc cierra sólo la ventana (no
// también la pantalla completa) y Suprimir no borra el dibujo elegido. Se
// frenan en `window` en la bajada (captura), antes que nadie: frenarlas en
// `document` no alcanzaba, porque la ventana se cierra con el mismo Esc y React
// saca el freno antes de que le llegue la tecla (auditoría 29/10).

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Share2 } from 'lucide-react'
import ShareCardModal from '../ShareCardModal'

export default function CompartirGrafico({ armar, antes = null, archivo = 'rendi-grafico.png', className = '' }) {
  const [spec, setSpec] = useState(null)
  // Vueltas de dibujo que faltan para armar la imagen (ver `antes`).
  const [esperando, setEsperando] = useState(0)
  const abierto = spec !== null
  useEffect(() => {
    if (!esperando) return
    if (esperando > 1) { setEsperando(esperando - 1); return }
    setEsperando(0)
    setSpec(armar() || false)
  }, [esperando, armar])
  useEffect(() => {
    if (!abierto) return undefined
    const frenar = (e) => {
      e.stopPropagation()
      e.stopImmediatePropagation?.()
      if (e.key === 'Escape') setSpec(null)
    }
    window.addEventListener('keydown', frenar, true)
    return () => window.removeEventListener('keydown', frenar, true)
  }, [abierto])
  const tocar = () => {
    if (antes) { antes(); setEsperando(2) } else setSpec(armar() || false)
  }
  return (
    <>
      <button type="button" data-capa="compartir" onClick={tocar}
        title="Una imagen de este gráfico, como lo estás viendo, para mandar por WhatsApp"
        className={`inline-flex items-center justify-center gap-1.5 min-h-11 min-w-11 sm:min-h-8 sm:min-w-0 sm:px-3 rounded-lg border border-line-2 bg-bg-2 text-ink-0 text-xs font-medium hover:border-ink-3 transition-colors ${className}`}>
        <Share2 size={16} aria-hidden="true" />
        <span className="sr-only sm:not-sr-only">Compartir</span>
      </button>
      {abierto && typeof document !== 'undefined' && createPortal(
        <div className="relative z-[80]">
          {/* `spec` false = no hubo con qué armarla: la ventana lo dice. */}
          <ShareCardModal spec={spec || null} source="grafico_tecnico" filename={archivo} onClose={() => setSpec(null)} />
        </div>,
        document.body,
      )}
    </>
  )
}
