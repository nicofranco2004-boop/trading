// lecturaDeCartera — la lectura de tu cartera que acompaña cada pregunta a
// Mervall-E, guardada para reusarla. Sin React: la usa VozContext (y de ahí la
// isla y la página /ai) y se prueba sola (lecturaDeCartera.test.js), por el
// mismo camino.
//
// Antes había dos lecturas iguales: la de la isla (en la primera pregunta) y
// la de /ai (cada vez que entrabas). Ahora es una, y tres reglas:
//   · UNA lectura a la vez: si la isla ya la pidió y preguntás o entrás a /ai
//     antes de que vuelva, se espera ESA lectura en vez de largar otros 4
//     pedidos. Y si ya estaba leída, /ai ni muestra el cargador.
//   · Es DE QUIÉN la leyó (`deQuien`, ver claveDePersona): el asesor que pasa
//     de un cliente a otro no recarga la página, y sin esto la isla, /ai y la
//     pregunta siguiente seguían con la cartera del cliente anterior. Y quien
//     cierra sesión y deja entrar a otro en la misma pestaña tampoco: ahí,
//     además, se olvida todo (`olvidar`).
//   · Queda VIEJA cuando algo cambia en el servidor (`invalidar`): se vuelve a
//     leer, y lo que estaba en camino tampoco se guarda al llegar. Y vence
//     sola a los VIGENCIA_MS: hay cambios que hace el servidor sin que esta
//     pestaña escriba nada (un plazo fijo que vence, un cupón, otra pestaña).
//     /ai antes releía en cada entrada; ahora relee si pasó ese rato, con el
//     chat ya a la vista (sigue con la anterior mientras llega).
//
// `alCambiar(estado)` recibe lo que se dibuja:
//   null                              → nunca se leyó
//   { estado: 'vieja', snap }         → cambió algo; hay que volver a leer
//   { estado: 'leyendo', llego, snap } → `llego[pieza]`: lo que trajo cada uno
//                                       de los 4 pedidos, o 'error'
//   { estado: 'lista', snap, resumen }
//   { estado: 'error', mensaje, snap }
// `snap` es la última lectura buena DE ESTA PERSONA mientras llega la nueva
// (o null): /ai sigue mostrando el chat con ella en vez de tirarlo y volver al
// cargador por una operación que registraste.

import { resumenDeCartera } from './aiSnapshot'

export const VIGENCIA_MS = 5 * 60 * 1000
export const VUELTAS = 3

// De quién es una lectura: la persona (su email) y el cliente que mira el
// asesor. Con el EMAIL y no con `user.id`: el usuario de la app no trae `id`
// (AuthContext.mapMeToUser no lo copia), así que con el id la clave era la
// misma para todos y quien entraba después en la misma pestaña veía —y le
// preguntaba a la IA con— la cartera del anterior (auditoría 2026-10-05).
export const claveDePersona = (user, clienteId) => `${user?.email ?? ''}|${clienteId ?? ''}`

export function crearLecturaDeCartera({ leer, deQuien, alCambiar = () => {}, ahora = () => Date.now() }) {
  let snap = null          // la lectura buena, si sigue valiendo
  let ultima = null        // { snap, de, en }: la última buena, aunque haya quedado vieja
  let enCurso = null
  let publicado = null     // lo último que se le pasó a alCambiar

  const anterior = (quien) => (ultima && ultima.de === quien ? ultima.snap : null)
  const publicar = (e) => { publicado = e; alCambiar(e) }

  function traer() {
    const quien = deQuien()
    if (snap && ultima?.de === quien && ahora() - ultima.en < VIGENCIA_MS) {
      // Volvió a una cartera que ya tenía leída (el asesor fue de A a B y
      // volvió a A): lo que estaba en camino es de OTRO y no se publica al
      // llegar, y lo que se ve tiene que ser ésta — no lo último publicado.
      if (enCurso && enCurso.de !== quien) enCurso = null
      if (publicado?.estado !== 'lista' || publicado.snap !== snap) {
        publicar({ estado: 'lista', snap, resumen: resumenDeCartera(snap) })
      }
      return Promise.resolve(snap)
    }
    if (enCurso?.de === quien) return enCurso.promesa
    const lectura = { de: quien, llego: {} }
    const vigente = () => enCurso === lectura
    enCurso = lectura
    publicar({ estado: 'leyendo', llego: {}, snap: anterior(quien) })
    lectura.promesa = leer(({ pieza, dato, error }) => {
      if (!vigente()) return
      lectura.llego = { ...lectura.llego, [pieza]: error ? 'error' : dato }
      publicar({ estado: 'leyendo', llego: lectura.llego, snap: anterior(quien) })
    }).then(
      (s) => {
        // Si en el camino quedó vieja (se guardó algo, cambió el cliente), lo
        // que trajo no se guarda ni se publica. La pregunta que la esperaba
        // se da cuenta y vuelve a leer (paraPreguntar); la isla, por el aviso.
        if (!vigente()) return s
        enCurso = null
        snap = s
        ultima = { snap: s, de: quien, en: ahora() }
        publicar({ estado: 'lista', snap: s, resumen: resumenDeCartera(s) })
        return s
      },
      (e) => {
        if (vigente()) {
          enCurso = null
          publicar({ estado: 'error', mensaje: e?.message || null, snap: anterior(quien) })
        }
        throw e
      },
    )
    return lectura.promesa
  }

  // Para la pregunta:
  //   · la lectura que hay, aunque haya pasado su rato (el servidor valúa las
  //     posiciones de nuevo al contestar), sin esperar a releerla;
  //   · si quedó vieja por una escritura, la nueva — y si la que esperaba
  //     también quedó vieja en el camino (o falló), otra vuelta;
  //   · como mucho VUELTAS lecturas: con escrituras seguidas (una importación
  //     por tanda) cada una tiraba la anterior y la pregunta no salía nunca.
  //     Después sale con la última que llegó;
  //   · si nada llegó, la anterior de esta persona: antes /ai le pasaba su
  //     foto y la pregunta salía igual; sin esto fallaba con un mensaje sobre
  //     el bot que no era la causa;
  //   · si en el medio cambió la persona (el asesor volvió al libro), no se
  //     lee para la otra: sale con lo que haya de la que preguntó.
  async function paraPreguntar() {
    const quien = deQuien()
    let llegada = null
    let error = null
    for (let vuelta = 0; vuelta < VUELTAS; vuelta++) {
      if (snap && ultima?.de === quien) return snap
      if (deQuien() !== quien) break
      try { llegada = await traer(); error = null } catch (e) {
        error = e
        // Falló de verdad (no quedó vieja en el camino): otra vuelta sería
        // esperar otra vez los reintentos de la red para nada.
        if (publicado?.estado === 'error') break
      }
    }
    if (snap && ultima?.de === quien) return snap
    if (llegada) return llegada
    const a = anterior(quien)
    if (a) return a
    throw error || new Error('No pudimos leer tu cartera.')
  }

  function invalidar() {
    snap = null
    enCurso = null
    publicar(ultima ? { estado: 'vieja', snap: anterior(deQuien()) } : null)
  }

  // Cambió la persona (cerró sesión y entró otra): no queda nada de la
  // anterior, ni siquiera como "anterior".
  function olvidar() {
    snap = null
    ultima = null
    enCurso = null
    publicar(null)
  }

  return { traer, paraPreguntar, invalidar, olvidar }
}
