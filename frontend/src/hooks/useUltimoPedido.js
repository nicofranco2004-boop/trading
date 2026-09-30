// useUltimoPedido — para los componentes que piden sus datos más de una vez
// (el refresco periódico de movers, watchlist y noticias).
//
// Cada pedido llama a `nuevoPedido()` y recibe `vigente()`: true sólo si ese
// pedido sigue siendo el último y el componente sigue montado. Sin esto, una
// respuesta lenta (el servidor despertando, 8 s) llegaba DESPUÉS de una más
// nueva y la pisaba con datos viejos. Es el `cancelled` que tenían estos
// efectos antes de que se refrescaran solos, generalizado a "el último gana".

import { useEffect, useRef } from 'react'

// La lógica, sin React, para poder probarla.
export function crearUltimoPedido() {
  let ultimo = 0
  let montado = true
  return {
    nuevoPedido() {
      const mio = ++ultimo
      return () => montado && mio === ultimo
    },
    montar() { montado = true },
    desmontar() { montado = false },
  }
}

export function useUltimoPedido() {
  const ref = useRef(null)
  if (!ref.current) ref.current = crearUltimoPedido()
  useEffect(() => {
    ref.current.montar()
    return () => ref.current.desmontar()
  }, [])
  return ref.current.nuevoPedido
}
