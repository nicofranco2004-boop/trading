// useRecienLlegadas — qué filas de una lista llegaron recién porque el usuario
// las agregó, para que destellen al aparecer (`.destello-nueva`, index.css).
//
//   const [nuevas, marcar] = useRecienLlegadas()
//   const antes = new Set(filas.map(f => f.id))   // ANTES de guardar
//   … guardar, volver a pedir la lista …
//   marcar(antes, filasNuevas)                    // las que no estaban
//
// Sólo se llama después de un alta: al entrar, al filtrar o al editar no hay
// nada "nuevo". La marca se borra sola cuando termina el destello, para que un
// cambio de filtro que vuelva a dibujar la fila no la haga destellar otra vez.
//
// Lo usan las dos listas de Movimientos (Operations: "Solo P/L" y "Todos los
// movimientos"), que se enteran de la misma alta por caminos distintos.

import { useCallback, useEffect, useRef, useState } from 'react'

// Las claves de `filas` que no estaban en `antes`. Pura, para las pruebas.
// A diferencia de las noticias (NewsPreview.urlsNuevas), `antes` vacío NO quiere
// decir "primera carga": acá siempre se anota justo antes de un alta, así que la
// primera operación de una cuenta vacía también es nueva.
export function nuevasDe(antes, filas, clave = f => f?.id) {
  return new Set((filas || []).map(clave).filter(k => k != null && !antes.has(k)))
}

// En qué página (desde 0) de una lista paginada de a `tam` quedó la primera
// fila recién llegada; -1 si no está (un filtro la esconde). Las listas saltan
// ahí: un destello en otra página no le dice a nadie dónde quedó la operación.
export function paginaDeLaNueva(lista, nuevas, tam, clave = f => f?.id) {
  if (!nuevas?.size || !tam) return -1
  const i = (lista || []).findIndex(f => nuevas.has(clave(f)))
  return i < 0 ? -1 : Math.floor(i / tam)
}

export function useRecienLlegadas(duracionMs = 2600) {
  const [nuevas, setNuevas] = useState(() => new Set())
  const reloj = useRef(null)
  useEffect(() => () => clearTimeout(reloj.current), [])
  const marcar = useCallback((antes, filas, clave) => {
    const ids = nuevasDe(antes, filas, clave)
    if (ids.size === 0) return
    setNuevas(ids)
    clearTimeout(reloj.current)
    reloj.current = setTimeout(() => setNuevas(new Set()), duracionMs)
  }, [duracionMs])
  return [nuevas, marcar]
}
