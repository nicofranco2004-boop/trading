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
//
// 🔴 "ALGUIEN LA MOVIÓ" NO SIEMPRE ES EL USUARIO: TAMBIÉN LA MUEVE CHROME.
//
// En el celular, la SEGUNDA respuesta de una conversación no se seguía: la
// pregunta de seguimiento quedaba arriba y la respuesta terminaba 555px abajo
// de lo que se veía. La primera sí se seguía, y en la compu las dos.
//
// MEDIDO en Chrome a 390×664 (modo demo, origin/main fca238e8), cuadro por
// cuadro:
//   1. Termina la respuesta 1: la barra queda en 1066 (el fondo). Chrome elige
//      un elemento visible como REFERENCIA ("ancla") para que, si algo de
//      arriba cambia de tamaño, lo que se está leyendo no salte. Acá eligió la
//      fila "Basado en… datos de la demo" de la respuesta 1.
//   2. Se manda la pregunta 2. De la respuesta 1 desaparecen la línea "Esta
//      respuesta no trajo resumen para escuchar" (23px, ARRIBA de la
//      referencia) y los botones de seguimiento. Chrome quiere subir la barra
//      23px para dejar la referencia donde estaba: 1066 − 23 = 1043. Pero el
//      contenido se achicó y lo máximo es 1024: queda en 1024, y Chrome se
//      ACUERDA de que le deben 19px. Nosotros pedimos el fondo, que también es
//      1024: como la barra no cambió, Chrome no se olvida de la deuda.
//   3. Llega la respuesta 2 y el contenido crece. Ahora hay lugar y Chrome
//      cobra la deuda: 1024 → 1043, sin que nadie toque nada.
//   4. Acá (abajo) se veía 1043 ≠ 1024 → "el usuario se movió" → se medía la
//      distancia al fondo CON LA RESPUESTA NUEVA YA ADENTRO (1766 − 1043 − 168
//      = 555) → "se fue lejos" → se le soltaba el control.
// En la compu no pasa porque la ventana es alta: al mandar la pregunta 2 el
// contenido CRECE en vez de achicarse, la barra no topa y no queda deuda. En
// la primera respuesta tampoco: antes de ella no había nada que scrollear (la
// barra en cero), así que no había nada que topar ni deuda que cobrar.
//
// Por eso, cada cosa con su test (usePegadoAlFondo.test.js):
//   · MIENTRAS SEGUIMOS, Chrome no ancla (overflow-anchor: none). La barra la
//     manejamos nosotros, y que otro la mueva sólo puede confundirnos. Medido:
//     apagarlo con la deuda pendiente hace que Chrome se olvide de ella.
//   · APENAS EL USUARIO SUBE, se le devuelve el ancla, sin esperar al próximo
//     dibujo: ahí sí sirve. Pasando los 40 mensajes se borra el más viejo,
//     ARRIBA de lo que está leyendo, y el ancla es lo que evita que el texto
//     le salte. (Auditoría: devolverla recién en el dibujo siguiente dejaba
//     ese dibujo sin ancla, y el primer pedazo de la respuesta es justo el que
//     borra el mensaje viejo: al que subió a releer durante el "pensando…" el
//     texto le saltaba todo lo que medía ese mensaje.) Para eso se escucha el
//     aviso de scroll del navegador — sólo para devolver el ancla, NUNCA para
//     decidir si se sigue: ese aviso llega un cuadro tarde (ver arriba).
//   · Si la barra BAJÓ POQUITO desde donde la dejamos (menos de 80px), no es
//     alguien que se fue a leer: se sigue. Es el empujón que medimos (+19),
//     por si Chrome u otra cosa que todavía no se nos ocurrió lo vuelve a dar.
//     Poquito y no cualquier bajada (auditoría): si algo creció sin redibujar
//     la pantalla y el usuario bajó a leerlo, no se lo tira al fondo.
//     ⚠️ NO se cambió cómo se juzga una SUBIDA (lejos del fondo = se fue).
//     Medirla "contra donde la dejamos" en vez de contra el fondo nuevo se
//     probó y se descartó en la auditoría: al que empieza a subir justo cuando
//     entra un bloque grande (las tarjetas) lo volvía a bajar a la fuerza
//     hasta que subiera 80px, que es exactamente lo que este hook existe para
//     no hacer.
//   · CAJA NUEVA = ARRANCA ABAJO. La isla, al cerrarse, desarma su lista de
//     mensajes; al reabrir nace una caja nueva con la barra en cero, y se la
//     comparaba con la posición anotada de la vieja → "se fue lejos" → no se
//     seguía. MEDIDO en Chrome (ya pasaba en main): tres preguntas, cerrar,
//     reabrir → mostraba los mensajes más viejos, 440px arriba del último.
//     Ahora una caja nueva arranca como la primera vez: en el último mensaje.

import { useCallback, useLayoutEffect, useRef } from 'react'

// A cuánto del final se considera "pegado". 80px es aprox. dos renglones: si
// se movió menos que eso, no se movió a propósito.
const CERCA_DEL_FONDO = 80
// La posición puede ser fraccionaria (medido: 1167,5) y el navegador redondea
// distinto según el zoom. 2px de tolerancia para no leer un redondeo como un
// movimiento del usuario.
const TOLERANCIA = 2

// Apenas la barra SUBE de donde la dejamos, el ancla vuelve a Chrome — antes
// del próximo dibujo. No toca si se sigue o no: eso lo decide seguir().
function devolverElAncla(el, ultimoAutoRef) {
  if (el.style.overflowAnchor === 'none'
      && ultimoAutoRef.current >= 0
      && el.scrollTop < ultimoAutoRef.current - TOLERANCIA) {
    el.style.overflowAnchor = ''
  }
}

/**
 * Lo que se hace después de CADA dibujo con conversación. Vive afuera del hook
 * para que el test corra exactamente esto contra una caja que se porta como la
 * de Chrome — con el chat activo, el hook no hace otra cosa que llamarla (con
 * el chat vacío se queda arriba: ver `activo`).
 *
 * @param el             el contenedor que scrollea.
 * @param pegadoRef      { current: bool } ¿estamos siguiendo la respuesta?
 * @param ultimoAutoRef  { current: number } dónde dejamos la barra la última
 *                       vez (-1 = nunca, o "volvé a seguir").
 * @param cajaRef        { current: Element } la caja de la vez pasada.
 */
export function seguir(el, pegadoRef, ultimoAutoRef, cajaRef) {
  if (!el) return
  if (cajaRef.current !== el) {
    // Caja nueva (la isla se reabrió): arranca abajo, como la primera vez. La
    // posición anotada era de la caja vieja.
    cajaRef.current = el
    volverASeguir(pegadoRef, ultimoAutoRef)
    el.addEventListener('scroll', () => devolverElAncla(el, ultimoAutoRef), { passive: true })
  }
  const seMovioSolo = ultimoAutoRef.current >= 0
    && Math.abs(el.scrollTop - ultimoAutoRef.current) > TOLERANCIA
  if (seMovioSolo) {
    // Alguien la movió. Que sigamos o no depende de dónde la dejó…
    const lejosDelFondo = el.scrollHeight - el.scrollTop - el.clientHeight
    // …salvo que la haya BAJADO POQUITO: eso no es irse a leer.
    const bajo = el.scrollTop - ultimoAutoRef.current
    pegadoRef.current = lejosDelFondo < CERCA_DEL_FONDO
      || (pegadoRef.current && bajo > 0 && bajo < CERCA_DEL_FONDO)
  }
  // Mientras seguimos, Chrome no ancla; si el usuario se fue a leer, sí.
  // ('' = lo que haga el navegador por defecto.) Va ANTES de mover la barra:
  // después de "volvé a seguir" todavía no se leyó la barra en este dibujo, así
  // que el acomodo que dispara leer el alto ya se hace sin ancla. En los demás
  // casos el acomodo de este dibujo ya pasó, y el cambio rige desde el próximo.
  const ancla = pegadoRef.current ? 'none' : ''
  if (el.style.overflowAnchor !== ancla) el.style.overflowAnchor = ancla
  if (pegadoRef.current) {
    el.scrollTop = el.scrollHeight
    ultimoAutoRef.current = el.scrollTop
  }
}

/** "Volvé a seguir la respuesta", esté donde esté el usuario. */
export function volverASeguir(pegadoRef, ultimoAutoRef) {
  pegadoRef.current = true
  ultimoAutoRef.current = -1
}

/**
 * @param {{ activo?: boolean }} [opciones]
 *   activo — false mientras no haya nada que seguir (el chat vacío): el
 *            contenedor se queda arriba de todo. Por defecto true.
 * @returns {{ ref, alFondo }}
 *   ref     — al contenedor que scrollea.
 *   alFondo — "volvé a seguir la respuesta". Se llama al mandar una pregunta
 *             nueva: ahí el usuario quiere ver lo que viene, esté donde esté.
 */
export function usePegadoAlFondo({ activo = true } = {}) {
  const ref = useRef(null)
  const pegadoRef = useRef(true)
  // Dónde quedó la barra la última vez que la movimos NOSOTROS. -1 = todavía
  // nunca, así que el primer dibujo baja al fondo sin preguntar.
  const ultimoAutoRef = useRef(-1)
  const activoAntesRef = useRef(activo)
  // La caja de la vez pasada: si cambia, la posición anotada no le sirve.
  const cajaRef = useRef(null)

  // useLayoutEffect y no useEffect: corre ANTES de que el navegador pinte, así
  // que el salto al fondo no se ve como un salto.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    // Sin nada que seguir (el chat vacío) no se pega al fondo: si la portada no
    // entra, lo que queda afuera tiene que ser lo de ABAJO (la explicación), no
    // la cara y el título. Pegado al fondo, en un iPhone con Safari no se veía
    // ni el personaje ni "¿Qué querés saber de tu plata?" (auditoría ronda 2).
    // Queda listo para pegarse apenas haya conversación.
    // Vuelve arriba SÓLO al quedar vacío (venía con conversación): el efecto
    // corre en cada render, y cada tecla es un render — mandarlo arriba siempre
    // le arrancaba de las manos la explicación al que la estaba leyendo en un
    // celular bajo (auditoría final 2026-10-05).
    if (!activo) {
      if (activoAntesRef.current) el.scrollTop = 0
      activoAntesRef.current = false
      pegadoRef.current = true
      ultimoAutoRef.current = -1
      // Sin nada que seguir, el ancla es la de siempre del navegador: la
      // portada se porta igual que antes de que se apagara para seguir.
      if (el.style.overflowAnchor) el.style.overflowAnchor = ''
      return
    }
    activoAntesRef.current = true
    seguir(el, pegadoRef, ultimoAutoRef, cajaRef)
  })

  const alFondo = useCallback(() => volverASeguir(pegadoRef, ultimoAutoRef), [])

  return { ref, alFondo }
}
