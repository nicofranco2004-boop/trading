// usePullToRefresh — gesto pull-to-refresh nativo en mobile.
// ═══════════════════════════════════════════════════════════════════════════
// Sprint M1, item 05 del audit mobile. Detecta swipe vertical en touch device
// cuando estás en el top del scroll. Tira un callback `onRefresh` cuando el
// gesto supera el threshold y devuelve estado para animar el indicador.
//
// Patrón nativo: el user "tira" hacia abajo, ve el indicador aparecer, cuando
// llega al threshold suelta y dispara el refresh. Resistencia configurable
// (~50%) para que el gesto se sienta físico.
//
// Uso:
//   const { isPulling, pullDistance, isRefreshing } = usePullToRefresh({
//     onRefresh: () => mutate(),
//   })
//   // Render indicador con opacity/transform basado en pullDistance.

import { useEffect, useRef, useState } from 'react'

const THRESHOLD = 80      // px que hay que tirar para disparar
const MAX_PULL = 140      // tope del indicador
const RESISTANCE = 0.55   // multiplicador del delta táctil → distancia visible

export function usePullToRefresh({ onRefresh, enabled = true } = {}) {
  const [isPulling, setIsPulling] = useState(false)
  const [pullDistance, setPullDistance] = useState(0)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const startY = useRef(null)
  const armed = useRef(false)

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return
    if (!('ontouchstart' in window)) return  // sin touch → skip

    function atTop() {
      return (window.scrollY || document.documentElement.scrollTop || 0) <= 0
    }

    function onTouchStart(e) {
      if (isRefreshing) return
      if (!atTop()) return
      startY.current = e.touches[0].clientY
      armed.current = true
    }

    function onTouchMove(e) {
      if (!armed.current || startY.current == null) return
      const dy = e.touches[0].clientY - startY.current
      if (dy <= 0) {
        // se movió hacia arriba — cancelar
        setIsPulling(false)
        setPullDistance(0)
        return
      }
      // Si en cualquier momento dejamos de estar en el top → cancelar
      if (!atTop()) {
        armed.current = false
        setIsPulling(false)
        setPullDistance(0)
        return
      }
      const adjusted = Math.min(dy * RESISTANCE, MAX_PULL)
      setIsPulling(true)
      setPullDistance(adjusted)
    }

    function onTouchEnd() {
      if (!armed.current) return
      armed.current = false
      const dist = pullDistance
      if (dist >= THRESHOLD && !isRefreshing && typeof onRefresh === 'function') {
        setIsRefreshing(true)
        Promise.resolve(onRefresh())
          .catch(() => { /* swallow */ })
          .finally(() => {
            setIsRefreshing(false)
            setIsPulling(false)
            setPullDistance(0)
            startY.current = null
          })
      } else {
        setIsPulling(false)
        setPullDistance(0)
        startY.current = null
      }
    }

    document.addEventListener('touchstart', onTouchStart, { passive: true })
    document.addEventListener('touchmove', onTouchMove, { passive: true })
    document.addEventListener('touchend', onTouchEnd, { passive: true })

    return () => {
      document.removeEventListener('touchstart', onTouchStart)
      document.removeEventListener('touchmove', onTouchMove)
      document.removeEventListener('touchend', onTouchEnd)
    }
  }, [enabled, onRefresh, isRefreshing, pullDistance])

  return { isPulling, pullDistance, isRefreshing, threshold: THRESHOLD }
}
