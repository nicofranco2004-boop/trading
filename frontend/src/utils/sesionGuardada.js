// sesionGuardada — «quién está logueado en este navegador», lo guardado en común.
// ═══════════════════════════════════════════════════════════════════════════
// Lo guardado (`rendi_user`) es UNO para todas las pestañas, como la cookie. Lo
// escribe sólo AuthContext (guardarSesion, al entrar o refrescar); lo BORRA sólo
// esta función, y sólo si todavía es de la persona que lo quiere borrar.
//
// 🔴 POR QUÉ (re-test a ciegas 7 y 8, 31/10). Había cinco lugares que lo
// borraban por su cuenta —las cuatro salidas de utils/api ante un 401, el 401
// del «¿quién soy?» al abrir, cerrar sesión, salir del demo—, y cada uno
// borraba lo que hubiera: un 401 que llegaba tarde de la pestaña de Ana, o Ana
// saliendo del demo, borraban a Bruno, que acababa de entrar en otra pestaña, y
// esa pestaña se recargaba. Se arregló en cuatro y quedó el quinto. Ahora es
// uno, y el guardián __guards__/puerta-de-la-sesion.test.js no deja otro.
import { quienEs } from './quienEs'
import { borrar, leer } from './almacen'
import { CATALOGO } from './catalogoDelAlmacen'

/** La persona guardada en común (email en minúsculas) o null. */
export function personaGuardada() {
  try { return quienEs(JSON.parse(leer(CATALOGO.usuario) || 'null')) } catch { return null }
}

/** ¿Lo guardado en común es de `persona` (o no hay nadie)? */
export function sesionGuardadaEsDe(persona) {
  const guardada = personaGuardada()
  return !guardada || guardada === (persona || null)
}

/** Borra lo guardado SÓLO si es de `persona`. Devuelve si lo borró. */
export function olvidarLaSesionSiEsDe(persona) {
  const guardada = personaGuardada()
  if (!guardada || !persona || guardada !== String(persona).trim().toLowerCase()) return false
  borrar(CATALOGO.usuario)
  return true
}
