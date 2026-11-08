// Sigue el borrado de «Empezar de cero» hasta que el servidor dice cómo terminó.
//
// Vive aparte de Config.jsx para que la prueba (seguirElBorrado.test.js) recorra
// el MISMO código que la pantalla, con el pedido y la espera de mentira.
//
// Cómo puede terminar, y por qué cada uno:
//   · 'listo'        → el servidor dijo listo. Es el ÚNICO final bueno.
//   · 'error'        → el servidor dijo error; trae su motivo.
//   · 'cortado'      → el servidor dice 'inactivo' en medio del seguimiento: se
//                      reinició (una publicación, una caída) y el trabajo quedó a
//                      medias. Antes esto mandaba al inicio como si hubiera salido
//                      bien, con la cartera a medio borrar.
//   · 'sin_conexion' → muchos pedidos seguidos sin respuesta. El trabajo sigue en
//                      el servidor, pero no se espera para siempre callado.
//   · 'desmontado'   → la persona se fue a otra pantalla: se deja de mirar, sin
//                      mover a nadie de donde está.

export const FALLAS_SEGUIDAS_MAX = 20     // ~15 s con la espera de 700 ms
export const ESPERA_MS = 700

export const MENSAJE = {
  cortado: 'El borrado se cortó a mitad. Lo que ya se borró quedó borrado: tocá ' +
    '«Empezar de cero» otra vez y termina el trabajo.',
  sin_conexion: 'Perdimos la conexión con el servidor. El borrado sigue allá: recargá ' +
    'esta página en un rato para ver cómo terminó.',
  error: 'No se pudo terminar de borrar. Tocá «Empezar de cero» otra vez.',
}

/**
 * @param {object} p
 * @param {() => Promise<object>} p.pedir      GET /me/reset-data/status
 * @param {() => boolean}         p.sigue      false si la pantalla se desmontó
 * @param {(st: object) => void}  [p.alAvanzar] cada estado 'corriendo'
 * @param {(ms: number) => Promise<void>} [p.esperar]
 * @returns {Promise<{fin: string, mensaje?: string}>}
 */
export async function seguirElBorrado({ pedir, sigue, alAvanzar, esperar = (ms) => new Promise(r => setTimeout(r, ms)) }) {
  let fallas = 0
  while (sigue()) {
    await esperar(ESPERA_MS)
    if (!sigue()) break
    let st
    try {
      st = await pedir()
      fallas = 0
    } catch {
      if (++fallas < FALLAS_SEGUIDAS_MAX) continue
      return { fin: 'sin_conexion', mensaje: MENSAJE.sin_conexion }
    }
    const estado = st?.estado
    if (estado === 'corriendo') {
      alAvanzar?.(st)
      continue
    }
    if (estado === 'listo') return { fin: 'listo' }
    if (estado === 'error') return { fin: 'error', mensaje: st?.error || MENSAJE.error }
    // 'inactivo' o cualquier cosa que no se conoce: no se da por terminado.
    return { fin: 'cortado', mensaje: MENSAJE.cortado }
  }
  return { fin: 'desmontado' }
}
