// useCountUp — interpola un número viejo→nuevo con requestAnimationFrame.
// ════════════════════════════════════════════════════════════════════════════
// Para el hero del portfolio: cuando el valor cambia (refetch de precios,
// toggle de moneda), el número "cuenta" de la cifra anterior a la nueva en
// ~600ms con easing cubic-out. Respeta prefers-reduced-motion (mismo criterio
// que el bloque de index.css): si el user lo pide, salta directo al valor final
// sin animar.
//
// Devuelve un número crudo. El call-site (o <AnimatedNumber>) lo formatea en
// cada frame — así el hook no sabe nada de formato.

import { useEffect, useRef, useState } from 'react'

function prefersReducedMotion() {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useCountUp(target, { duration = 600 } = {}) {
  const numericTarget = Number(target)
  const safeTarget = Number.isFinite(numericTarget) ? numericTarget : 0

  // Arranca en 0 para que el hero "cuente" hacia el valor al montar (momento
  // dopamina). En updates posteriores anima desde el último valor (no desde 0).
  const [value, setValue] = useState(0)
  const fromRef = useRef(0)
  const rafRef = useRef(null)
  const latestRef = useRef(0) // último valor renderizado (para cleanup sin stale closure)

  useEffect(() => {
    // Sin animación: reduced-motion o valor no numérico → salto directo.
    if (prefersReducedMotion() || !Number.isFinite(numericTarget)) {
      fromRef.current = safeTarget
      latestRef.current = safeTarget
      setValue(safeTarget)
      return
    }

    const from = fromRef.current
    const to = safeTarget
    if (from === to) return

    const t0 = performance.now()
    const tick = (t) => {
      const p = Math.min(1, (t - t0) / duration)
      const eased = 1 - Math.pow(1 - p, 3) // cubic-out
      const current = from + (to - from) * eased
      setValue(current)
      latestRef.current = current
      if (p < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        fromRef.current = to
        latestRef.current = to
      }
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      // Si el efecto se reejecuta a mitad de animación, la próxima arranca
      // desde el último frame renderizado (continuidad sin saltos).
      fromRef.current = latestRef.current
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [safeTarget, duration])

  return value
}

export default useCountUp
