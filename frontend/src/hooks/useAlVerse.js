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
//
// Con "reducir movimiento" también arranca en true: no hay entrada que guardar
// para cuando llegues, así que no hay nada que esperar. index.css ya lo
// decidía para lo suyo (.por-entrar a la vista); el hook no, y lo que dependía
// de `visto` en JavaScript quedaba a medio camino: los números que cuentan
// escritos en 0 hasta que bajabas (medido en Chrome el 2026-10-02: "coincide
// con tu perfil en 0 de 8", "Win rate 0 %", "+USD 0,00"), el gráfico del
// Dashboard escondido.

import { useEffect, useState } from 'react'
import { prefiereSinMovimiento } from '../utils/movimiento'

// ¿Se ve lo suficiente como para arrancar? El `threshold` de un
// IntersectionObserver es una fracción DEL ELEMENTO: en una lista alta (25
// noticias, ~3.000 px) el 15 % no entra nunca en una pantalla de 860 px, y
// `visto` no pasaba a true — las noticias de Novedades quedaron invisibles
// (opacity 0 de .por-entrar) hasta que alguien bajara. Alcanza con ver esa
// fracción del elemento O esa fracción de la pantalla, lo que pase primero.
export function bastanteVisible(entry, fraccion) {
  if (!entry?.isIntersecting) return false
  if (entry.intersectionRatio >= fraccion) return true
  const alto = entry.rootBounds?.height
    || (typeof window !== 'undefined' ? window.innerHeight : 0) || 0
  return alto > 0 && entry.intersectionRect.height >= alto * fraccion
}

// Escalones a los que el observador avisa: con uno solo (el 15 %), una lista
// alta avisaría al entrar el primer pixel y nunca más.
function escalones(fraccion) {
  return [...new Set([0, 0.01, 0.025, 0.05, 0.1, fraccion])].sort((a, b) => a - b)
}

// El ref es una FUNCIÓN (callback ref) y no un useRef: así el observador se
// engancha también cuando el elemento aparece recién después de cargar (una
// lista que se arma cuando llegan los datos). Con useRef, el efecto corría al
// montar con el ref vacío y no volvía a correr nunca.
export function useAlVerse({ threshold = 0.15, rootMargin = '0px 0px -40px 0px' } = {}) {
  const [nodo, setNodo] = useState(null)
  const [visto, setVisto] = useState(() => typeof IntersectionObserver === 'undefined' || prefiereSinMovimiento())

  useEffect(() => {
    if (visto || !nodo) return
    const io = new IntersectionObserver(
      ([entry]) => { if (bastanteVisible(entry, threshold)) { setVisto(true); io.disconnect() } },
      { threshold: escalones(threshold), rootMargin },
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
