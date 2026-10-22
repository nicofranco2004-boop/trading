// useDialogo — lo que hace falta para que una ventana emergente se pueda usar
// con el teclado (y con un lector de pantalla), no sólo con el mouse:
//
//   1. al abrir, el foco entra a la ventana (si un campo ya lo tomó con
//      `autoFocus`, se respeta);
//   2. Tab y Shift+Tab dan la vuelta ADENTRO de la ventana, en vez de irse a
//      la página de atrás, que sigue ahí pero tapada;
//   3. Escape la cierra;
//   4. al cerrar, el foco vuelve a donde estaba (el botón que la abrió).
//
// Sin esto, quien navega con teclado abría una ventana y seguía tabulando por
// la cartera de atrás sin ver dónde estaba, y no tenía cómo cerrarla.
//
// Ventanas apiladas (una confirmación encima de un formulario): sólo la de
// ARRIBA responde a Escape y a Tab. Si no, un Escape cerraba las dos.

import { useEffect, useRef } from 'react'

const FOCUSABLES =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

const pila = []

export function useDialogo(ref, onClose) {
  // El último onClose, sin re-armar los listeners cada vez que el padre
  // re-renderiza con una función nueva (eso movía el foco en cada tecla).
  const cerrar = useRef(onClose)
  cerrar.current = onClose

  useEffect(() => {
    const caja = ref.current
    // Sin una página de verdad atrás (las pruebas montan con un renderizador
    // que no es el navegador) no hay foco que mover.
    if (!caja || typeof caja.contains !== 'function' || typeof document === 'undefined') {
      return undefined
    }
    const yo = {}
    pila.push(yo)
    const anterior = document.activeElement

    if (!caja.contains(document.activeElement)) caja.focus()

    const alTeclado = (e) => {
      if (pila[pila.length - 1] !== yo) return
      // Si el foco está en OTRA capa encima (una confirmación o el buscador,
      // que manejan su propio teclado y no usan este hook), la tecla es de ella.
      const actual = document.activeElement
      if (actual && actual !== document.body && !caja.contains(actual)) return
      if (e.key === 'Escape') {
        e.stopPropagation()
        cerrar.current?.()
        return
      }
      if (e.key !== 'Tab') return
      const items = [...caja.querySelectorAll(FOCUSABLES)].filter((el) => el.offsetParent !== null)
      if (!items.length) {
        e.preventDefault()
        caja.focus()
        return
      }
      const primero = items[0]
      const ultimo = items[items.length - 1]
      if (e.shiftKey && (actual === primero || actual === caja)) {
        e.preventDefault()
        ultimo.focus()
      } else if (!e.shiftKey && (actual === ultimo || !caja.contains(actual))) {
        e.preventDefault()
        primero.focus()
      }
    }
    document.addEventListener('keydown', alTeclado)
    return () => {
      document.removeEventListener('keydown', alTeclado)
      const i = pila.indexOf(yo)
      if (i >= 0) pila.splice(i, 1)
      if (anterior && typeof anterior.focus === 'function' && document.contains(anterior)) {
        anterior.focus()
      }
    }
  }, [ref])
}
