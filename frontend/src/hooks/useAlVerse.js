// useAlVerse — [ref, visto]: `visto` pasa a true la PRIMERA vez que el elemento
// entra en pantalla, y queda en true.
//
// Para las entradas animadas de las secciones del inicio (filas que aparecen
// de a una, números que cuentan): los movers, la watchlist y las noticias están
// más abajo del primer pantallazo, y animados al montar se terminaban antes de
// que nadie llegara con el scroll.
//
// Sin IntersectionObserver (navegador viejo, o el render del servidor en los
// tests) `visto` arranca en true: sin eso, lo que espera "a ser visto" para
// aparecer no aparecería nunca.

import { useEffect, useState } from 'react'

// El ref es una FUNCIÓN (callback ref) y no un useRef: así el observador se
// engancha también cuando el elemento aparece recién después de cargar (una
// lista que se arma cuando llegan los datos). Con useRef, el efecto corría al
// montar con el ref vacío y no volvía a correr nunca.
export function useAlVerse({ threshold = 0.15, rootMargin = '0px 0px -40px 0px' } = {}) {
  const [nodo, setNodo] = useState(null)
  const [visto, setVisto] = useState(() => typeof IntersectionObserver === 'undefined')

  useEffect(() => {
    if (visto || !nodo) return
    const io = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setVisto(true); io.disconnect() } },
      { threshold, rootMargin },
    )
    io.observe(nodo)
    return () => io.disconnect()
  }, [nodo, visto, threshold, rootMargin])

  return [setNodo, visto]
}

// Las props de un elemento que entra en escalera: `.entra` cuando la sección ya
// se vio (`.por-entrar` —escondido— mientras no), y su lugar en la fila en
// --i, que index.css convierte en la demora. `clases` son las que el elemento
// ya tenía. Una sola definición para todas las listas y grillas que entran de a
// una (movers, watchlist, noticias, eventos, tarjetas del inicio, diagnóstico,
// comportamiento, chips de "desde tu última visita").
//   <div key={x.id} {...entrada(visto, i, 'h-full')}>
export function entrada(visto, i, clases = '') {
  return {
    className: `${clases} ${visto ? 'entra' : 'por-entrar'}`.trim(),
    style: { '--i': i },
  }
}
