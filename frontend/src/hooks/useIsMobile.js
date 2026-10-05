// useIsMobile — breakpoint hook para split desktop/mobile.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint M1 del audit mobile. Threshold: 768px (Tailwind `md`).
// Por debajo, layout mobile (tab bar + topbar + sheets); por arriba, layout
// desktop (sidebar + modales). Mismo URL, mismo bundle, mismo state.
//
// Implementación: matchMedia con cleanup. Devuelve boolean. SSR-safe (false
// inicial cuando window undefined).

import { useEffect, useState } from 'react'

export const MOBILE_BREAKPOINT_PX = 768

export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX - 1}px)`).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined') return
    const mq = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX - 1}px)`)
    const handler = (e) => setIsMobile(e.matches)
    // Compat: addEventListener moderno, addListener legacy
    if (mq.addEventListener) {
      mq.addEventListener('change', handler)
      return () => mq.removeEventListener('change', handler)
    } else {
      mq.addListener(handler)
      return () => mq.removeListener(handler)
    }
  }, [])

  return isMobile
}


/**
 * ¿La ventana mide al menos `px` de ancho? Para lo que necesita más lugar que
 * "no es celular" (por ejemplo, el compañero de Mervall-E al costado del
 * cuadro de texto, que en una tablet le comía el ancho). SSR-safe.
 */
export function useAnchoMinimo(px) {
  const consulta = `(min-width: ${px}px)`
  const [cumple, setCumple] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(consulta).matches
  })
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mq = window.matchMedia(consulta)
    const handler = (e) => setCumple(e.matches)
    setCumple(mq.matches)
    if (mq.addEventListener) {
      mq.addEventListener('change', handler)
      return () => mq.removeEventListener('change', handler)
    }
    mq.addListener(handler)
    return () => mq.removeListener(handler)
  }, [consulta])
  return cumple
}
