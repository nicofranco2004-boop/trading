// useTrazo — las props para que la línea de un gráfico se dibuje de izquierda a
// derecha UNA vez (`.traza-dibuja`, index.css) y quede sólida al terminar.
//
//   const trazo = useTrazo(`${symbol}-${range}`)
//   <path d={d} stroke={color} {...trazo} />
//
// Vuelve a dibujarse cuando cambia `clave` (otro período, otro activo). Con la
// misma clave, un re-render (un refresco de precios) no la redibuja.
//
// Terminada la animación se le SACA la clase: el trazo "destapado" depende de
// que el navegador respete `pathLength` junto con `vector-effect:
// non-scaling-stroke`, y si alguno no lo hace (no se pudo probar en Safari) la
// línea quedaría punteada para siempre. Sin la clase es una línea común en
// todos. Con "reducir movimiento" la clase no anima ni punta (index.css).
//
// La usan la ficha de un activo (AssetMiniChart) y las mini líneas de
// Principales posiciones y Cartera (Sparkline, vía LazySparkline).

import { useState } from 'react'

export function useTrazo(clave = 'linea') {
  const [hecha, setHecha] = useState(null)
  return {
    pathLength: 1,
    className: hecha === clave ? undefined : 'traza-dibuja',
    onAnimationEnd: () => setHecha(clave),
  }
}
