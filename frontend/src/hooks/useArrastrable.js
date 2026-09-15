// useArrastrable — mover la isla con el dedo, y que se quede donde la dejaste.
// ═══════════════════════════════════════════════════════════════════════════
// La isla flota SIEMPRE en el mismo lugar (arriba a la derecha) y eso tapa cosas:
// justo ahí viven los botones de varias pantallas. Pedido de Nico: mantener
// apretado y deslizar para correrla adonde uno quiera, cerrada y abierta.
//
// CUATRO DECISIONES QUE NO SON OBVIAS
//
// 1. Se mueve con `transform`, no cambiándole la posición. La isla se ubica de
//    formas distintas según el caso (pegada a la derecha cuando está cerrada,
//    de borde a borde en el celular cuando está abierta). Escribirle una
//    posición fija rompería todo eso; un desplazamiento se suma encima y la
//    acomoda igual en los dos casos.
//
// 2. Arrastrar y TOCAR se hacen con el mismo dedo. El botón de abrir, el
//    parlante y la X viven adentro de la zona que arrastra. Así que se mide
//    cuánto se movió: menos de 4 píxeles es un toque y el botón hace lo suyo;
//    más, es un arrastre y el clic se descarta. Sin eso, mover la isla te la
//    abría o te la cerraba al soltar.
//
// 3. No se puede ir de la pantalla. Se recorta al arrastrar, al rotar el
//    teléfono y —la que costó— al ABRIRSE: cerrada es una burbujita y abierta
//    es una tarjeta del ancho entero, así que el desplazamiento que a una le
//    queda bien a la otra la saca de la pantalla. Medido: arrastrar 140px a la
//    izquierda y abrir dejaba la tarjeta en x = -128.
//
// 4. La posición dura LO QUE DURA LA PESTAÑA, no para siempre. Pedido de
//    Nico: al volver a entrar, la isla tiene que estar en su lugar de siempre.
//    Uno la corre porque le tapa ALGO —la pantalla que está mirando ahora—, no
//    porque quiera que viva ahí. Guardarla para siempre haría que el que la
//    corrió una vez la encuentre meses después en un rincón raro sin acordarse
//    de por qué. Es el mismo criterio que la conversación (ver
//    utils/chatSession.js): sobrevive navegar y recargar, no cerrar la pestaña.
//
// Se usan eventos de PUNTERO: el mismo código para el mouse, el dedo y el
// lápiz, en vez de tres juegos de eventos que se pisan entre sí.

import { useCallback, useLayoutEffect, useRef, useState } from 'react'

// Cuánto hay que moverse para que deje de ser un toque. 4px aguanta el
// temblor del dedo sin comerse un arrastre de verdad.
const UMBRAL = 4
// Cuánto tiene que quedar siempre visible del borde.
const MARGEN = 8

const acotar = (v, min, max) => (min > max ? min : Math.min(Math.max(v, min), max))

function leerGuardado(clave) {
  try {
    // sessionStorage y no localStorage: se borra al cerrar la pestaña, que es
    // lo que hace que la isla vuelva sola a su lugar de siempre.
    const raw = sessionStorage.getItem(clave)
    if (!raw) return { dx: 0, dy: 0 }
    const v = JSON.parse(raw)
    return (Number.isFinite(v?.dx) && Number.isFinite(v?.dy)) ? { dx: v.dx, dy: v.dy } : { dx: 0, dy: 0 }
  } catch {
    return { dx: 0, dy: 0 }          // sin almacenamiento, arranca en su lugar
  }
}

/**
 * @param clave  dónde recordar la posición mientras dure la pestaña.
 * @returns { ref, estilo, manija }
 *   ref    — al elemento que se mueve.
 *   estilo — va en su `style`.
 *   manija — los props de la ZONA que se agarra (puede ser el mismo elemento).
 */
export function useArrastrable(clave) {
  const ref = useRef(null)
  const [pos, setPos] = useState(() => leerGuardado(clave))
  // Espejo para leer la posición adentro de los manejadores sin re-suscribirlos
  // en cada movimiento.
  const posRef = useRef(pos)
  posRef.current = pos
  const arrastreRef = useRef(null)
  const arrastroRef = useRef(false)

  // Dónde estaría la isla sin desplazamiento, para poder recortar contra los
  // bordes sin arrastrar el error del desplazamiento anterior.
  const recortar = useCallback((dx, dy) => {
    const el = ref.current
    if (!el || typeof window === 'undefined') return { dx, dy }
    const r = el.getBoundingClientRect()
    const izqNatural = r.left - posRef.current.dx
    const arrNatural = r.top - posRef.current.dy
    return {
      dx: acotar(dx, MARGEN - izqNatural, window.innerWidth - MARGEN - r.width - izqNatural),
      dy: acotar(dy, MARGEN - arrNatural, window.innerHeight - MARGEN - r.height - arrNatural),
    }
  }, [])

  const guardar = useCallback((p) => {
    try { sessionStorage.setItem(clave, JSON.stringify(p)) } catch { /* sin almacenamiento */ }
  }, [clave])

  const acomodar = useCallback(() => {
    setPos((p) => {
      const nueva = recortar(p.dx, p.dy)
      // Devolver el MISMO objeto cuando no cambió nada es lo que evita que
      // esto se llame a sí mismo para siempre: React no vuelve a dibujar.
      return (nueva.dx === p.dx && nueva.dy === p.dy) ? p : nueva
    })
  }, [recortar])

  // 🔴 AL ABRIRSE, LA ISLA NO CRECE: ES OTRO ELEMENTO.
  //
  // Cerrada es una burbujita y abierta es una tarjeta — React desmonta una y
  // monta la otra, no la agranda. Este efecto corría UNA vez y dejaba al
  // vigilante de tamaño mirando el elemento viejo, que ya no existe: el
  // recorte no se ejecutaba nunca para el nuevo.
  //
  // MEDIDO en el celular: arrastrar la burbuja 140px a la izquierda y tocarla
  // abría la tarjeta en x = -128, o sea 128 píxeles afuera de la pantalla por
  // la izquierda. La burbuja mide 159px y la tarjeta ocupa el ancho entero, así
  // que el mismo desplazamiento que a una le queda bien a la otra la saca.
  //
  // Por eso corre en CADA dibujo (sin lista de dependencias): es lo único que
  // se entera de que el elemento cambió. El vigilante se vuelve a enganchar
  // sólo cuando el elemento es de verdad otro.
  const vigiaRef = useRef({ obs: null, nodo: null })
  useLayoutEffect(() => {
    acomodar()
    const nodo = ref.current
    if (vigiaRef.current.nodo === nodo) return
    vigiaRef.current.obs?.disconnect()
    vigiaRef.current = { obs: null, nodo }
    if (nodo && typeof ResizeObserver !== 'undefined') {
      const o = new ResizeObserver(acomodar)
      o.observe(nodo)
      vigiaRef.current.obs = o
    }
  })

  // Rotar el teléfono da vuelta la pantalla sin tocar la isla.
  useLayoutEffect(() => {
    window.addEventListener('resize', acomodar)
    return () => {
      window.removeEventListener('resize', acomodar)
      vigiaRef.current.obs?.disconnect()
    }
  }, [acomodar])

  const alApretar = useCallback((e) => {
    // Sólo el botón principal del mouse; el derecho abre el menú del sistema.
    if (e.button != null && e.button !== 0) return
    arrastreRef.current = { x: e.clientX, y: e.clientY, dx: posRef.current.dx, dy: posRef.current.dy }
    arrastroRef.current = false
    try { e.currentTarget.setPointerCapture(e.pointerId) } catch { /* el navegador no lo soporta */ }
  }, [])

  const alMover = useCallback((e) => {
    const a = arrastreRef.current
    if (!a) return
    const mx = e.clientX - a.x
    const my = e.clientY - a.y
    if (!arrastroRef.current && Math.abs(mx) + Math.abs(my) < UMBRAL) return   // todavía es un toque
    arrastroRef.current = true
    setPos(recortar(a.dx + mx, a.dy + my))
  }, [recortar])

  const alSoltar = useCallback((e) => {
    if (!arrastreRef.current) return
    arrastreRef.current = null
    try { e.currentTarget.releasePointerCapture(e.pointerId) } catch { /* ídem */ }
    if (arrastroRef.current) guardar(posRef.current)
  }, [guardar])

  // El clic que viene después de un arrastre no cuenta: si no, soltar la isla
  // encima de su propio botón la abría o la cerraba.
  const alHacerClic = useCallback((e) => {
    if (arrastroRef.current) {
      e.preventDefault()
      e.stopPropagation()
      arrastroRef.current = false
    }
  }, [])

  return {
    ref,
    estilo: (pos.dx || pos.dy) ? { transform: `translate3d(${pos.dx}px, ${pos.dy}px, 0)` } : undefined,
    manija: {
      onPointerDown: alApretar,
      onPointerMove: alMover,
      onPointerUp: alSoltar,
      onPointerCancel: alSoltar,
      onClickCapture: alHacerClic,
      // Sin esto el navegador se queda con el gesto para scrollear la página y
      // el arrastre no llega nunca en el celular.
      style: { touchAction: 'none' },
    },
  }
}
