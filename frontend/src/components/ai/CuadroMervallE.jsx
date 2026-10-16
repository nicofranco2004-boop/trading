// CuadroMervallE — Mervall-E de cuerpo entero, en un cuadro, mientras charlás.
// ═══════════════════════════════════════════════════════════════════════════
// Pedido de Nico (2026-10-16): "en mobile no se llega a apreciar para nada y en
// desktop muy poco". MEDIDO antes de este cambio, con una conversación abierta:
//   · celular (375 px): sólo la cabecita de 38 px de la barra de arriba;
//   · compu (1440 px): un busto de 60 px pegado al cuadro de texto, con
//     ~200 px vacíos a cada lado de la columna del chat.
//
// Ahora, con conversación en /ai, hay UN cuadro con el personaje entero:
//   · Si al costado de la columna del chat hay lugar (compu ancha), el cuadro
//     va AHÍ, grande, a la altura del cuadro de texto. No tapa nada.
//   · Si no hay lugar (celular, tablet, compu con la ventana angosta), va en la
//     esquina de arriba a la derecha de la conversación, chico, como la cara
//     de uno en una videollamada. Tapa un pedazo: por eso se puede ARRASTRAR
//     adonde no moleste (el mismo mecanismo que la isla, hooks/useArrastrable).
//
// Cuál de los dos lo decide el lugar MEDIDO, no el ancho de la ventana: con la
// barra lateral abierta o cerrada el mismo ancho de ventana deja costados
// distintos.
//
// Es el que está en escena (estadoDelChat.enEscena → 'companero'): reacciona,
// piensa, habla y escucha. La cabecera de /ai queda congelada mientras tanto.

import { useLayoutEffect, useRef, useState } from 'react'
import MervallE from './MervallE'
import { proporcion } from './mervalle/motor'
import { useArrastrable } from '../../hooks/useArrastrable'
import { useAnchoMinimo } from '../../hooks/useIsMobile'

/** Separación entre la columna del chat y el cuadro, y del cuadro al borde. */
export const SEPARACION_COSTADO = 16
/** El cuadro al costado: más grande no suma. El mínimo sale de la notebook de
 *  1280 px con la barra lateral abierta, que deja ~170 px a la derecha: con
 *  un mínimo de 150 el cuadro se iba a la esquina y tapaba la pregunta
 *  (visto en pantalla). Al costado queda de 138, igual más grande que el de
 *  la esquina. */
export const LADO_COSTADO_MAX = 220
export const LADO_COSTADO_MIN = 112
/** El de la esquina: celular / pantalla mediana. */
export const LADO_ESQUINA_CELULAR = 104
export const LADO_ESQUINA = 128

/**
 * ¿Entra el cuadro al costado de la columna del chat? `libre` = px entre el
 * borde derecho de la columna y el borde derecho de la pantalla.
 * @returns {number|null} el lado del cuadro, o null si no entra (va en la esquina).
 */
export function ladoAlCostado(libre) {
  if (!Number.isFinite(libre)) return null
  const lado = Math.min(LADO_COSTADO_MAX, Math.floor(libre - 2 * SEPARACION_COSTADO))
  return lado >= LADO_COSTADO_MIN ? lado : null
}

/** El ancho del dibujo para que el cuerpo entero entre parado en un cuadro de `lado`. */
export function anchoDelCuerpo(lado) {
  const aire = Math.round(lado * 0.08)
  return Math.floor((lado - 2 * aire) / proporcion('full'))
}

export default function CuadroMervallE({ estado, tono }) {
  // Una marca sin tamaño adentro del contenedor del chat: su padre es la
  // columna, y contra él se mide cuánto sobra a la derecha.
  const marca = useRef(null)
  const [ladoCostado, setLadoCostado] = useState(null)
  useLayoutEffect(() => {
    const columna = marca.current?.parentElement
    if (!columna) return undefined
    const medir = () => {
      const libre = document.documentElement.clientWidth - columna.getBoundingClientRect().right
      setLadoCostado(ladoAlCostado(libre))
    }
    medir()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(medir) : null
    ro?.observe(columna)
    window.addEventListener('resize', medir)
    return () => { ro?.disconnect(); window.removeEventListener('resize', medir) }
  }, [])

  const pantallaMediana = useAnchoMinimo(640)
  const { ref, estilo, manija } = useArrastrable('rendi:cuadro:pos')
  const alCostado = ladoCostado != null
  const lado = alCostado ? ladoCostado : (pantallaMediana ? LADO_ESQUINA : LADO_ESQUINA_CELULAR)

  const cuadro = (
    <div
      className="w-full h-full rounded-xl border border-data-violet/25 bg-bg-1 overflow-hidden
                 grid place-items-center bg-gradient-to-b from-data-violet/[0.10] to-transparent"
    >
      <MervallE size={anchoDelCuerpo(lado)} forma="full" escucha estado={estado} tono={tono} />
    </div>
  )

  return (
    <>
      <span ref={marca} aria-hidden="true" className="absolute w-0 h-0" />
      {alCostado ? (
        // Al costado: afuera de la columna, a la altura del cuadro de texto.
        <div
          aria-hidden="true"
          className="absolute bottom-3 z-10"
          style={{ left: `calc(100% + ${SEPARACION_COSTADO}px)`, width: lado, height: lado }}
        >
          {cuadro}
        </div>
      ) : (
        // En la esquina: arriba a la derecha de la conversación, arrastrable.
        <div
          ref={ref}
          aria-hidden="true"
          className="absolute top-2 right-2 z-10 cursor-grab active:cursor-grabbing select-none shadow-lg rounded-xl"
          style={{ width: lado, height: lado, ...estilo, ...manija.style }}
          onPointerDown={manija.onPointerDown}
          onClickCapture={manija.onClickCapture}
        >
          {cuadro}
        </div>
      )}
    </>
  )
}
