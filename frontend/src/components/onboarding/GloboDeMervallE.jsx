// GloboDeMervallE — lo que dice Mervall-E en la bienvenida, en un globo de
// historieta con la punta hacia él (arriba en el celular, a la izquierda en la
// compu, donde él está parado al costado).
// ═══════════════════════════════════════════════════════════════════════════
// El texto se escribe solo, letra por letra (~28 ms, un respiro después de un
// punto o una coma), con el cursor que parpadea mientras escribe. Tocar el
// globo lo completa al instante. Con «reducir movimiento» aparece entero.
//
// Tres decisiones que no se ven y que importan:
//   · EL GLOBO NO CRECE MIENTRAS ESCRIBE. El texto entero va debajo, invisible,
//     y lo escrito encima en la misma celda: el globo nace con su tamaño final
//     y lo de abajo (los brokers, el botón) no salta a cada renglón nuevo.
//   · EL LECTOR DE PANTALLA LEE LA FRASE ENTERA, UNA VEZ. Lo que se va
//     escribiendo es `aria-hidden` (si no, lo leería letra por letra); la frase
//     completa va en un nodo `aria-live="polite"` que no se ve. Mervall-E es
//     decorativo (aria-hidden): lo que «dice» es este texto.
//   · AVISA CUANDO TERMINA (`onTermino`), también si se completó con un toque o
//     apareció entero. La página pasa a Mervall-E de `hablando` a otra cara:
//     `hablando` se mueve en cada cuadro y gasta batería si queda prendido.
//
// `texto`: una frase o una lista de párrafos. Para que vuelva a escribir desde
// cero con otro texto, quien lo usa le cambia el `key`.

import { useEffect, useMemo, useRef, useState } from 'react'
import CursorEscribiendo from '../ai/CursorEscribiendo'
import { prefiereSinMovimiento } from '../../utils/movimiento'

const MS_POR_LETRA = 28
// Después de un punto el ojo descansa; después de una coma, un poco.
const PAUSA = { '.': 260, '!': 260, '?': 260, ',': 110, ':': 140, '…': 260 }

/** Cuánto esperar después de escribir la letra `c`. */
export function esperaDespuesDe(c) {
  return PAUSA[c] ?? MS_POR_LETRA
}

/** Los párrafos con las primeras `n` letras del total (lo que ya se escribió). */
export function escritoHasta(parrafos, n) {
  let quedan = n
  return parrafos.map(p => {
    const parte = p.slice(0, Math.max(0, quedan))
    quedan -= p.length
    return parte
  })
}

export default function GloboDeMervallE({ texto, onTermino, className = '', demora = 0 }) {
  const parrafos = useMemo(() => (Array.isArray(texto) ? texto : [texto]).filter(Boolean), [texto])
  const total = useMemo(() => parrafos.reduce((n, p) => n + p.length, 0), [parrafos])
  const [n, setN] = useState(() => (prefiereSinMovimiento() ? total : 0))
  const avisado = useRef(false)
  const terminoRef = useRef(onTermino)
  terminoRef.current = onTermino

  const completo = n >= total

  // Lo que anuncia el lector de pantalla: el nodo nace vacío y se llena
  // después de montarse. Un aviso que ya está escrito cuando aparece, varios
  // lectores no lo leen.
  const [anuncio, setAnuncio] = useState('')
  useEffect(() => { setAnuncio(parrafos.join(' ')) }, [parrafos])

  // Letra por letra. Un solo temporizador vivo a la vez: cada letra programa la
  // siguiente con la pausa que le toca.
  useEffect(() => {
    if (completo) return
    const todo = parrafos.join('')
    const espera = n === 0 ? demora : esperaDespuesDe(todo[n - 1])
    const t = setTimeout(() => setN(x => Math.min(total, x + 1)), espera)
    return () => clearTimeout(t)
  }, [n, completo, parrafos, total, demora])

  useEffect(() => {
    if (!completo || avisado.current) return
    avisado.current = true
    terminoRef.current?.()
  }, [completo])

  const escrito = escritoHasta(parrafos, n)
  // El cursor va al final del párrafo que se está escribiendo.
  const enCurso = completo ? -1 : escrito.findIndex((p, i) => p.length < parrafos[i].length)

  return (
    <div
      className={`relative rounded-xl border border-data-violet/30 bg-bg-1 px-4 py-3.5 sm:px-5 sm:py-4 text-left cursor-default bv-globo ${className}`}
      onClick={() => setN(total)}
      style={{ '--d': `${Math.max(0, demora - 200)}ms` }}
    >
      {/* La punta: un cuadrado girado con el mismo fondo y borde que el globo
          (como el cartel de Tour.jsx). Celular: arriba, hacia Mervall-E que está
          encima. Compu: a la izquierda, hacia Mervall-E parado al costado. */}
      <span
        aria-hidden="true"
        className="absolute w-3.5 h-3.5 rotate-45 bg-bg-1 border-data-violet/30 border-l border-t left-8 -top-[7.5px] md:-left-[7.5px] md:top-7 md:border-t-0 md:border-b"
      />
      <p className="sr-only" aria-live="polite">{anuncio}</p>
      <div aria-hidden="true" className="grid text-[15.5px] sm:text-base leading-relaxed text-ink-0">
        {/* Debajo: el texto entero, invisible, que le da al globo su tamaño final. */}
        <div className="invisible col-start-1 row-start-1 space-y-2">
          {parrafos.map((p, i) => <p key={i}>{p}</p>)}
        </div>
        {/* Encima: lo que ya se escribió. */}
        <div className="col-start-1 row-start-1 space-y-2">
          {escrito.map((p, i) => (p || i === enCurso) && (
            <p key={i}>{p}{i === enCurso && <CursorEscribiendo />}</p>
          ))}
        </div>
      </div>
    </div>
  )
}
