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
//   · Lo que quedó viejo SE CANCELA (los 4 pedidos), y la relectura espera
//     PAUSA_TRAS_CAMBIO_MS: el cambio de mes guarda un PUT y un POST por broker,
//     y con la isla abierta eran 11 lecturas completas por 10 escrituras.
//   · Una lectura que no vuelve se corta a los TOPE_MS: compartida, una
//     colgada colgaba también todas las preguntas siguientes.
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
export const PAUSA_TRAS_CAMBIO_MS = 400
export const TOPE_MS = 30 * 1000

// De quién es una lectura: la persona (su email) y el cliente que mira el
// asesor. Con el EMAIL y no con `user.id`: el usuario de la app no trae `id`
// (AuthContext.mapMeToUser no lo copia), así que con el id la clave era la
// misma para todos y quien entraba después en la misma pestaña veía —y le
// preguntaba a la IA con— la cartera del anterior (auditoría 2026-10-05).
// En minúsculas y sin espacios: al iniciar sesión el email provisorio es el
// que se tipeó ("Ana@X.com") y después llega el de /auth/me ("ana@x.com").
export const claveDePersona = (user, clienteId) =>
  `${String(user?.email ?? '').trim().toLowerCase()}|${clienteId ?? ''}`

// Un error con el texto que ve la persona: el chat muestra `detail` tal cual
// (utils/errorChat.traducirErrorDeChat). NO es un AbortError: ése el chat lo
// toma por "el usuario canceló" y no muestra nada.
function errorParaMostrar(texto) {
  const e = new Error(texto)
  e.detail = texto
  return e
}
export const CAMBIO_DE_PERSONA = 'Cambiaste de cliente mientras Mervall-E leía la cartera. Volvé a preguntar.'

const dormir = (ms) => new Promise((r) => setTimeout(r, ms))
function programarConReloj(fn, ms) {
  const t = setTimeout(fn, ms)
  t?.unref?.()
  return () => clearTimeout(t)
}

export function crearLecturaDeCartera({
  leer, deQuien, alCambiar = () => {}, ahora = () => Date.now(),
  pausaTrasCambio = PAUSA_TRAS_CAMBIO_MS, tope = TOPE_MS,
  esperar = dormir, programar = programarConReloj,
}) {
  let snap = null          // la lectura buena, si sigue valiendo
  let ultima = null        // { snap, de, en }: la última buena, aunque haya quedado vieja
  let enCurso = null
  let publicado = null     // lo último que se le pasó a alCambiar
  let cambioEn = -Infinity // cuándo quedó vieja por última vez

  const anterior = (quien) => (ultima && ultima.de === quien ? ultima.snap : null)
  const publicar = (e) => { publicado = e; alCambiar(e) }
  // La lectura en camino deja de valer: no se guarda al llegar y sus pedidos
  // se cancelan.
  function soltar() {
    if (!enCurso) return
    enCurso.control?.abort()
    enCurso = null
  }

  function traer() {
    const quien = deQuien()
    if (snap && ultima?.de === quien && ahora() - ultima.en < VIGENCIA_MS) {
      // Volvió a una cartera que ya tenía leída (el asesor fue de A a B y
      // volvió a A): lo que estaba en camino es de OTRO y no se publica al
      // llegar, y lo que se ve tiene que ser ésta — no lo último publicado.
      if (enCurso && enCurso.de !== quien) soltar()
      if (publicado?.estado !== 'lista' || publicado.snap !== snap) {
        publicar({ estado: 'lista', snap, resumen: resumenDeCartera(snap) })
      }
      return Promise.resolve(snap)
    }
    if (enCurso?.de === quien) return enCurso.promesa
    soltar()                                   // si había una, era de otra persona
    const lectura = { de: quien, llego: {}, vencida: false,
      control: typeof AbortController === 'function' ? new AbortController() : null }
    const vigente = () => enCurso === lectura
    enCurso = lectura
    publicar({ estado: 'leyendo', llego: {}, snap: anterior(quien) })
    const alLlegar = ({ pieza, dato, error }) => {
      if (!vigente()) return
      lectura.llego = { ...lectura.llego, [pieza]: error ? 'error' : dato }
      publicar({ estado: 'leyendo', llego: lectura.llego, snap: anterior(quien) })
    }
    const arrancar = () => {
      // Otra escritura durante la pausa: ésta ni sale (la reemplaza la próxima).
      if (!vigente()) return null
      const cortar = programar(() => {
        if (vigente()) { lectura.vencida = true; lectura.control?.abort() }
      }, tope)
      return leer(alLlegar, lectura.control?.signal).then(
        (s) => {
          cortar()
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
          cortar()
          if (!vigente()) throw e
          enCurso = null
          const falla = lectura.vencida
            ? errorParaMostrar('Tu cartera tardó demasiado en llegar. Probá de nuevo en un rato.')
            : e
          publicar({ estado: 'error', mensaje: falla?.message || null, snap: anterior(quien) })
          throw falla
        },
      )
    }
    const falta = cambioEn + pausaTrasCambio - ahora()
    lectura.promesa = falta > 0 ? esperar(falta).then(arrancar) : arrancar()
    return lectura.promesa
  }

  // Para la pregunta:
  //   · la lectura que hay, aunque haya pasado su rato (el servidor valúa las
  //     posiciones de nuevo al contestar), sin esperar a releerla;
  //   · si quedó vieja por una escritura, la nueva — y si la que esperaba
  //     también quedó vieja en el camino, otra vuelta;
  //   · como mucho VUELTAS lecturas: con escrituras seguidas (una importación
  //     por tanda) cada una tiraba la anterior y la pregunta no salía nunca.
  //     Después sale con la última que llegó;
  //   · si falló de verdad, no se reintenta (serían otra vez los reintentos de
  //     la red) y sale con la anterior de esta persona: antes /ai le pasaba su
  //     foto y la pregunta salía igual;
  //   · si en el medio cambió la persona (el asesor pasó a otro cliente o
  //     volvió al libro), SE CORTA: saldría con la cartera de uno y el
  //     encabezado del otro (el cliente lo pone utils/api al mandar), y el
  //     servidor mezclaría las dos.
  async function paraPreguntar() {
    const quien = deQuien()
    let llegada = null
    let error = null
    for (let vuelta = 0; vuelta < VUELTAS; vuelta++) {
      if (deQuien() !== quien) break           // antes que nada: ver abajo
      if (snap && ultima?.de === quien) return snap
      try {
        const s = await traer()
        if (s) llegada = s
        error = null
      } catch (e) {
        error = e
        if (publicado?.estado === 'error') break
      }
    }
    if (deQuien() !== quien) throw errorParaMostrar(CAMBIO_DE_PERSONA)
    if (snap && ultima?.de === quien) return snap
    if (llegada) return llegada
    const a = anterior(quien)
    if (a) return a
    if (!error || error.name === 'AbortError') throw errorParaMostrar('No pudimos leer tu cartera. Probá de nuevo en un rato.')
    throw error
  }

  function invalidar() {
    cambioEn = ahora()
    soltar()
    snap = null
    publicar(ultima ? { estado: 'vieja', snap: anterior(deQuien()) } : null)
  }

  // Cambió la persona (cerró sesión y entró otra): no queda nada de la
  // anterior, ni siquiera como "anterior".
  function olvidar() {
    soltar()
    snap = null
    ultima = null
    publicar(null)
  }

  return { traer, paraPreguntar, invalidar, olvidar }
}
