// ¿La persona pidió menos movimiento? ("Reducir movimiento" en iOS/macOS,
// "Mostrar animaciones" apagado en Windows/Android.)
//
// Las animaciones de CSS lo respetan solas: el bloque
// `@media (prefers-reduced-motion: reduce)` de index.css las apaga. Esta
// función es para las que corren en JavaScript y ese bloque no alcanza: el
// contador de los números (useCountUp), el foco al cambiar de moneda
// (enfocarCambios) y el giro de las tortas (recharts, CompositionDonut).
// Una sola pregunta para todas: si mañana hay un interruptor propio en
// Configuración, se agrega acá y lo respetan todas.

export function prefiereSinMovimiento() {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
