// BotonCompartir — el ícono chico de "compartir" de una tarjeta de métricas.
// ═══════════════════════════════════════════════════════════════════════════
// Abre ShareCardModal con `buildSpec`: el modal pregunta primero si la imagen
// lleva los montos o sólo los porcentajes, y recién ahí la genera. Lo usan las
// tortas de distribución (vía la prop `compartir` de CompositionDonut) y el
// gráfico "Cartera vs benchmark" de Análisis.
//
// Va arriba a la derecha de la tarjeta. Si la tarjeta está envuelta en
// AskAIAbout, el ✦ de Mervall-E se corre solo al primer hueco libre a la
// izquierda de este botón (ver lugarDelBoton): no hace falta coordinarlos.
//
// El modal va por portal al <body>: las tarjetas pueden tener `transform`
// (animaciones de entrada) y un `position: fixed` adentro de un transform se
// posiciona contra la tarjeta, no contra la pantalla.

import { useState } from 'react'
import { createPortal } from 'react-dom'
import { Share2 } from 'lucide-react'
import ShareCardModal from './ShareCardModal'

export default function BotonCompartir({ buildSpec, source, filename = 'rendi.png', etiqueta = 'Compartir', className = '' }) {
  const [abierto, setAbierto] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setAbierto(true) }}
        aria-label={etiqueta}
        title={etiqueta}
        className={`inline-flex items-center justify-center w-6 h-6 rounded-sm text-ink-3 hover:text-data-violet hover:bg-data-violet/10 transition-colors flex-shrink-0 ${className}`}
      >
        <Share2 size={13} strokeWidth={1.75} />
      </button>
      {abierto && typeof document !== 'undefined' && createPortal(
        // Los eventos de React atraviesan el portal hacia los ancestros del
        // BOTÓN: sin este corte, un doble clic en el modal le preguntaba a
        // Mervall-E por la tarjeta (AskAIAbout escucha onDoubleClick).
        <div onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
          <ShareCardModal
            buildSpec={buildSpec}
            source={source}
            filename={filename}
            onClose={() => setAbierto(false)}
          />
        </div>,
        document.body,
      )}
    </>
  )
}
