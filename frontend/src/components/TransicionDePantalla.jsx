// TransicionDePantalla — al pasar de una SECCIÓN a otra (Dashboard → Cartera),
// el contenido se funde en 220 ms mientras el menú, la cinta de cotizaciones y
// las barras de arriba quedan quietos, como en una app nativa. Lo usan los dos
// marcos (compu y celular, App.jsx): es el único lugar por donde pasan todas
// las pantallas.
//
// Sólo cambia de sección cuando cambia el primer tramo de la dirección: las
// pestañas o filtros de una misma pantalla (`?tab=…`, `/posiciones/3`) no
// funden, porque no son "otra pantalla".
//
// Por qué así y no de otra forma:
//  · Sólo opacidad, sin desplazar: mover el contenedor (transform) cambia a
//    qué se pegan los elementos `fixed` de adentro mientras dura la animación.
//  · useLayoutEffect: arranca ANTES de que se dibuje la pantalla nueva; con
//    useEffect se veía un cuadro entero y recién después el fundido.
//  · Element.animate y no una clase: no deja nada puesto al terminar.
//  · "Reducir movimiento" → cambia de golpe, como antes.
import { useLayoutEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { prefiereSinMovimiento } from '../utils/movimiento'

export const FUNDIDO_MS = 220

export function seccionDe(pathname) {
  return (pathname || '/').split('/').filter(Boolean)[0] || ''
}

export default function TransicionDePantalla({ children }) {
  const ref = useRef(null)
  const seccion = seccionDe(useLocation().pathname)
  const anterior = useRef(seccion)

  useLayoutEffect(() => {
    if (anterior.current === seccion) return
    anterior.current = seccion
    const el = ref.current
    if (!el || typeof el.animate !== 'function' || prefiereSinMovimiento()) return
    el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: FUNDIDO_MS, easing: 'ease-out' })
  }, [seccion])

  return <div ref={ref}>{children}</div>
}
