// useEsperaConTope — una pantalla no se muestra hasta que lo que va ARRIBA de
// todo ya sabe cuánto ocupa (`listo`), y si eso no llega a tiempo, se muestra
// igual. Lo usan los dos inicios (la lista de primeros pasos y el fuera de
// horario, ver useEsperaDeLaLista) y, por el fuera de horario, el Dashboard,
// Cartera y la ficha de un activo (useFueraDeHorarioDeConEspera).
// ═══════════════════════════════════════════════════════════════════════════
// Por qué: una pieza que se dibuja DESPUÉS que la pantalla, arriba, empuja
// todo lo de abajo justo cuando la persona va a tocar algo. Es lo que Google
// mide como CLS, y lo que tenía al sitio en rojo con usuarios reales (auditoría
// SEO 16/11/2026). Reservar el lugar no alcanza cuando el alto depende de la
// respuesta (una lista de 0 px o de casi un metro; con o sin sección de
// post-mercado), así que la pantalla espera.
//
// El tope corre desde `desde` (la pantalla ya tiene lo suyo): una pieza trabada
// no puede dejar a nadie mirando un esqueleto. En ese caso raro la pieza vuelve
// a aparecer tarde, que es lo que pasaba siempre antes.

import { useEffect, useState } from 'react'

export const TOPE_ESPERA_MS = 1500

/**
 * @param {boolean} desde  la pantalla ya tiene sus propios datos: desde acá corre el tope
 * @param {boolean} listo  lo de arriba ya sabe si va y cuánto ocupa
 * @returns {boolean} se puede mostrar el contenido (listo, o venció el tope)
 */
export function useEsperaConTope({ desde = true, listo }) {
  const [vencida, setVencida] = useState(false)
  // Una vez mostrada, queda mostrada: si después lo de arriba vuelve a
  // «no listo» (cambió la cartera y el fuera de horario se pide de nuevo), la
  // pantalla no vuelve al esqueleto.
  const [mostrada, setMostrada] = useState(false)
  // Sólo cuenta desde `desde`. Antes de que llegue la cartera no hay nada que
  // pedir al fuera de horario y «ya respondió» da true: contado antes, la
  // traba de abajo se cerraba al montar y la pantalla ya no esperaba nada
  // (medido: el Dashboard se dibujó a los 846 ms y el chip llegó a los 1060).
  const ya = desde && (!!listo || vencida)

  useEffect(() => { if (ya) setMostrada(true) }, [ya])

  // Si la pantalla vuelve a SU esqueleto (`desde` otra vez false: en la ficha,
  // otro activo elegido en el buscador, con la misma página sin rearmarse), la
  // vez siguiente espera de nuevo. Si no, el chip del segundo llegaba tarde.
  useEffect(() => {
    if (desde) return
    setMostrada(false)
    setVencida(false)
  }, [desde])

  useEffect(() => {
    if (!desde || listo || mostrada) return undefined
    const t = setTimeout(() => setVencida(true), TOPE_ESPERA_MS)
    return () => clearTimeout(t)
  }, [desde, listo, mostrada])

  return ya || mostrada
}
