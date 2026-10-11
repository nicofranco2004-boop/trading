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
import { prefiereSinMovimiento } from '../utils/movimiento'

// `desde`: de dónde arranca la PRIMERA cuenta (por defecto 0). Lo usa
// useNumeroQueCambia para contar desde el valor que el número tenía la última
// vez que se vio, y no desde 0.
export function useCountUp(target, { duration = 600, desde = 0 } = {}) {
  const numericTarget = Number(target)
  const safeTarget = Number.isFinite(numericTarget) ? numericTarget : 0

  // Arranca en 0 para que el hero "cuente" hacia el valor al montar (momento
  // dopamina). En updates posteriores anima desde el último valor (no desde 0).
  // Sin navegador (un render a texto: las pruebas que leen lo que se ve) no hay
  // cuadros que dibujar ni efectos que corran: el número sale en su valor
  // final, que es lo que la persona termina viendo. Sin esto, cualquier número
  // que cuenta se leía "0" en esas pruebas.
  const sinNavegador = typeof window === 'undefined'
  const arranque = Number.isFinite(Number(desde)) ? Number(desde) : 0
  const [value, setValue] = useState(() => (sinNavegador ? safeTarget : arranque))
  const fromRef = useRef(sinNavegador ? safeTarget : arranque)
  const rafRef = useRef(null)
  // Último valor renderizado (para cleanup sin stale closure). Arranca donde
  // arranca la cuenta: en 0 fijo, una cuenta cortada antes de su primer cuadro
  // hacía que la siguiente saliera de 0 y no de `desde`.
  const latestRef = useRef(sinNavegador ? safeTarget : arranque)

  useEffect(() => {
    // Sin animación: reduced-motion o valor no numérico → salto directo.
    if (prefiereSinMovimiento() || !Number.isFinite(numericTarget)) {
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

    // Garantía de llegada: el número TERMINA en su valor aunque el navegador
    // no dibuje. Con la pestaña de fondo, en ahorro de energía o en un visor
    // que no está a la vista, requestAnimationFrame se frena o se para, y el
    // conteo quedaba clavado a mitad de camino — medido: todos los movers al
    // 48,5 % de su valor. En una pantalla de plata eso es un número mal
    // mostrado, aunque dure un instante. Los relojes siguen corriendo cuando
    // los cuadros no: al vencer la duración, se escribe el valor final.
    const llegada = setTimeout(() => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
      fromRef.current = to
      latestRef.current = to
      setValue(to)
    }, duration + 100)

    return () => {
      clearTimeout(llegada)
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
