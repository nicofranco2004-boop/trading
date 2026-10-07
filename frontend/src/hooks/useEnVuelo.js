// useEnVuelo — el freno de los botones que mueven plata: mientras un pedido
// está viajando al servidor, el mismo botón no manda otro.
//
// Por qué hace falta (medido 2026-10-03): el servidor ya "reclama" antes de
// editar, cobrar, vender o borrar, así que un doble click ahí no duplica nada.
// Pero en las ALTAS no puede: dos "Guardar" de la misma compra son, para el
// servidor, dos compras legítimas. El único lugar que sabe que fue un doble
// click es la pantalla.
//
// Por qué una referencia y no sólo un estado: el estado de React se aplica
// DESPUÉS de que termina el click. Si dos clicks caen en el mismo turno (un
// doble click que el navegador despacha junto, un Enter más un click), el
// segundo todavía lee "no estoy guardando" y pasa. La referencia cambia en el
// acto, antes de que llegue el segundo. El estado queda para DIBUJAR el botón
// apagado con su "Guardando…".
//
// Uso:
//   const enVuelo = useEnVuelo()
//   <button onClick={() => enVuelo.correr(onConfirm)} disabled={enVuelo.activo()}>
//     {enVuelo.activo() ? 'Guardando…' : 'Confirmar'}
//   </button>
//
// Con `clave` frena por renglón (cobrar ESTE plazo fijo no apaga los demás):
//   enVuelo.correr(() => cobrar(pf), pf.id)   ·   enVuelo.activo(pf.id)

import { useEffect, useMemo, useRef, useState } from 'react'

const SIN_CLAVE = '·'

// La lógica, sin React, para poder probarla.
export function crearEnVuelo(avisar = () => {}) {
  const claves = new Set()
  return {
    /** ¿Hay un pedido viajando con esa clave? Sin clave: el del botón único. */
    activo: (clave = SIN_CLAVE) => claves.has(clave),
    /** ¿Hay alguno viajando, de cualquier clave? */
    alguno: () => claves.size > 0,
    /**
     * Corre `fn` si no hay otro con la misma clave en vuelo; si lo hay, no hace
     * nada y devuelve undefined. Suelta el freno al terminar, salga bien o mal
     * (un error no puede dejar el botón apagado para siempre).
     */
    async correr(fn, clave = SIN_CLAVE) {
      if (claves.has(clave)) return undefined
      claves.add(clave)
      avisar()
      try {
        return await fn()
      } finally {
        claves.delete(clave)
        avisar()
      }
    },
  }
}

export function useEnVuelo() {
  const [version, setVersion] = useState(0)
  const montado = useRef(true)
  const nucleo = useRef(null)
  if (!nucleo.current) {
    // El modal que se cierra al guardar se desmonta con el pedido todavía
    // viajando: al soltarse el freno ya no hay a quién redibujar.
    nucleo.current = crearEnVuelo(() => { if (montado.current) setVersion(v => v + 1) })
  }
  useEffect(() => {
    montado.current = true
    return () => { montado.current = false }
  }, [])
  // Un objeto nuevo en cada cambio: un hijo memorizado que recibe
  // `enVuelo.activo` se entera de que tiene que redibujarse. `correr` es el
  // mismo siempre.
  return useMemo(() => {
    const n = nucleo.current
    return { correr: n.correr, activo: (c) => n.activo(c), alguno: () => n.alguno() }
  }, [version]) // eslint-disable-line react-hooks/exhaustive-deps
}
