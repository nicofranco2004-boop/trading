// rutasSensibles — una sola definición de "esta URL lleva un secreto o un dato
// personal, así que NO se le manda a terceros (Meta Pixel, Google Analytics)".
// ════════════════════════════════════════════════════════════════════════════
// Antes cada medidor tenía su propia copia de la lista y sólo cubría /i/, /claim
// y /acceso: /reset-password (token que cambia la contraseña) y /verify-email
// (el email en la URL) se filtraban a Meta y a Google (audit RENDI-09). Acá la
// lista es una sola.
//
// Y además FALLA CERRADO: cualquier URL que lleve un parámetro sensible en la
// query (token, email, code) tampoco se reporta, esté o no su ruta en la lista.
// Así no depende de acordarse de sumar cada ruta nueva.
//
// index.html tiene su PROPIA copia inline de este criterio (corre antes que el
// bundle): si se cambia acá, cambiarlo allá también. `medicion.test.js` corre
// aquel bloque tal como está escrito.

export const RUTAS_SENSIBLES = ['/i/', '/claim', '/acceso', '/reset-password', '/verify-email']

const PARAMS_SENSIBLES = ['token', 'email', 'code']

export function urlTieneDatosSensibles(pathname, search) {
  const p = typeof pathname === 'string' ? pathname : ''
  if (RUTAS_SENSIBLES.some((r) => p.startsWith(r))) return true
  try {
    const qs = new URLSearchParams(search || '')
    return PARAMS_SENSIBLES.some((k) => qs.has(k))
  } catch {
    return true // query ilegible → no arriesgar
  }
}
