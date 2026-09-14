// usePegadoAlFondo — seguir la respuesta mientras se escribe, SIN arrastrar al
// que se fue para arriba a leer.
// ═══════════════════════════════════════════════════════════════════════════
// Las dos pantallas de la conversación —la isla flotante y el chat grande—
// tenían cada una su copia de esto, y las dos fallaban igual. Va acá una sola
// vez: es el mismo problema y merece la misma respuesta.
//
// 🔴 POR QUÉ ESCUCHAR EL GESTO NO ALCANZA, que era como estaba.
//
// La versión anterior se enteraba de que el usuario se había movido por dos
// avisos del navegador: la rueda del mouse y el dedo arrastrando. El problema
// es que hay muchas formas de scrollear que NO disparan ninguno de los dos:
//
//   · arrastrar la barra de scroll,
//   · las flechas y AvPág del teclado,
//   · y la que de verdad importa: LA INERCIA DEL DEDO en el celular. El dedo
//     se levanta, el contenido sigue corriendo solo, y durante ese rato el
//     navegador ya no avisa "el dedo se está moviendo".
//
// En esos casos el único aviso que llega es "la barra se movió", que llega UN
// CUADRO TARDE. Y en ese cuadro entra una palabra nueva de la respuesta, que
// dispara el auto-scroll: para cuando el aviso llega, ya lo tiramos abajo.
//
// MEDIDO en la isla, con Rendi escribiendo: subir a cero sin rueda ni dedo y
// mirar la posición cada 400 ms daba 0 → 1031 → 1167 (el fondo). Menos de un
// segundo arriba. Con rueda, en cambio, se quedaba en cero — por eso el
// arreglo anterior parecía funcionar cuando uno lo probaba con el mouse.
//
// ── LO QUE SE HACE EN VEZ ───────────────────────────────────────────────────
// No se adivina el gesto: se compara la posición con LA QUE DEJAMOS NOSOTROS
// la última vez. Si no coinciden, alguien la movió — no importa cómo — y ahí
// se decide mirando dónde quedó: cerca del fondo, seguimos; lejos, se le suelta
// el control hasta que él mismo vuelva.
//
// No depende de ningún aviso del navegador ni de en qué orden lleguen, así que
// cubre también las formas de scrollear que todavía no se nos ocurrieron.

import { useCallback, useLayoutEffect, useRef } from 'react'

// A cuánto del final se considera "pegado". 80px es aprox. dos renglones: si
// se movió menos que eso, no se movió a propósito.
const CERCA_DEL_FONDO = 80
// La posición puede ser fraccionaria (medido: 1167,5) y el navegador redondea
// distinto según el zoom. 2px de tolerancia para no leer un redondeo como un
// movimiento del usuario.
const TOLERANCIA = 2

/**
 * @returns {{ ref, alFondo }}
 *   ref     — al contenedor que scrollea.
 *   alFondo — "volvé a seguir la respuesta". Se llama al mandar una pregunta
 *             nueva: ahí el usuario quiere ver lo que viene, esté donde esté.
 */
export function usePegadoAlFondo() {
  const ref = useRef(null)
  const pegadoRef = useRef(true)
  // Dónde quedó la barra la última vez que la movimos NOSOTROS. -1 = todavía
  // nunca, así que el primer dibujo baja al fondo sin preguntar.
  const ultimoAutoRef = useRef(-1)

  // useLayoutEffect y no useEffect: corre ANTES de que el navegador pinte, así
  // que el salto al fondo no se ve como un salto.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const seMovioSolo = ultimoAutoRef.current >= 0
      && Math.abs(el.scrollTop - ultimoAutoRef.current) > TOLERANCIA
    if (seMovioSolo) {
      // Lo movió el usuario. Que siga o no depende de dónde lo dejó.
      pegadoRef.current =
        (el.scrollHeight - el.scrollTop - el.clientHeight) < CERCA_DEL_FONDO
    }
    if (pegadoRef.current) {
      el.scrollTop = el.scrollHeight
      ultimoAutoRef.current = el.scrollTop
    }
  })

  const alFondo = useCallback(() => {
    pegadoRef.current = true
    ultimoAutoRef.current = -1
  }, [])

  return { ref, alFondo }
}
