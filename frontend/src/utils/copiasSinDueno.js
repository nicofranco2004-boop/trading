// copiasSinDueno — borra, al abrir la app, las copias del navegador que dejó la
// versión ANTERIOR a la regla de dueño (utils/duenoDeLaPestana).
//
// Desde la regla, cada copia con datos de una cuenta va a nombre de
// `persona|cuenta` y las viejas, sin dueño, ya no se leen: no le aparecen a
// nadie. Pero seguían ahí. En localStorage, para siempre: el valor de la
// cartera de «desde tu última visita». En sessionStorage, mientras dure la
// pestaña: la tanda del asesor con nombres de clientes y los totales vistos.
// Es lo que quedaba de la persona anterior después de una sesión que vence
// (re-test a ciegas, 30/10).
//
// Cómo distingue una vieja de una nueva: las familias de abajo son las que
// pasaron por la regla, y una clave suya sin `|` no tiene dueño (el dueño es
// siempre `email|propia` o `email|cliente-N`). El demo (`demo`) no se toca.

const FAMILIAS = [
  'rendi_snapshot_date',
  'rendi_tanda_ultima',
  'rendi_valor_visto:',
  'rendi_version_cartera:',
  'rendi_cambios_movimientos:',
  'rendi_ultimo_total:',
  'rendi_lastvisit_',
  'rendi_diag_dismissed_',
  'rendi_dibujos:',
]

export function esCopiaSinDueno(clave) {
  if (!clave || !FAMILIAS.some(f => clave.startsWith(f))) return false
  return !clave.includes('|') && !/(^|:)demo(:|$)/.test(clave)
}

function limpiar(almacen) {
  try {
    const viejas = []
    for (let i = 0; i < almacen.length; i++) {
      const k = almacen.key(i)
      if (esCopiaSinDueno(k)) viejas.push(k)
    }
    viejas.forEach(k => almacen.removeItem(k))
    return viejas.length
  } catch { return 0 }   // sin almacenamiento: no hay nada que borrar
}

/** Borra las copias sin dueño de los dos almacenes. Devuelve cuántas borró. */
export function borrarCopiasSinDueno() {
  if (typeof window === 'undefined') return 0
  return limpiar(window.localStorage) + limpiar(window.sessionStorage)
}
