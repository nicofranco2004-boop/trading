// cambioDeMovimiento — el aviso "Recalculando tu cartera" cuando el cambio pasó
// en OTRA pantalla.
//
// Caso (pedido de Nico, 2026-10-09): el usuario borra un movimiento desde
// Movimientos —un dividendo, un depósito, una venta—. El total de la cartera
// cambia, y la PRÓXIMA pantalla que lo muestre (Cartera o Dashboard) tiene que
// dejar VER que se recalculó: del total que se vio ahí la última vez al nuevo.
//
//   · Movimientos, al borrar (o deshacer un borrado), deja anotado qué cambió
//     (`anotarCambioDeMovimiento`).
//   · Cada pantalla con total recuerda el último que mostró
//     (`recordarTotalVisto`, por pantalla: Cartera y Dashboard no calculan
//     exactamente lo mismo, y mezclarlos inventaría una diferencia).
//   · La primera que se abre toma lo anotado (`tomarCambioPendiente`) y lo
//     muestra con <RecalculoDeCartera>. Se muestra UNA vez.
//
// Vive en sessionStorage: es de esta pestaña y de esta visita. Si el navegador
// no deja guardar (ventana privada), no hay aviso y nada se rompe.

const CLAVE_CAMBIO = 'rendi:cambio-de-movimiento'
const clave_total = (pantalla) => `rendi:ultimo-total:${pantalla}`
const VENCE_MS = 30 * 60 * 1000   // un aviso de hace más de media hora ya no dice nada

function leer(clave) {
  try { return JSON.parse(window.sessionStorage.getItem(clave) || 'null') } catch { return null }
}
function escribir(clave, valor) {
  try {
    if (valor == null) window.sessionStorage.removeItem(clave)
    else window.sessionStorage.setItem(clave, JSON.stringify(valor))
  } catch { /* sin almacenamiento: no hay aviso */ }
}

/**
 * Movimientos: cambió algo que mueve el total y ninguna pantalla con total lo
 * mostró todavía.
 *   texto    'dividendo de KO', 'depósito', 'venta de AAPL'
 *   articulo 'el' | 'la'  ("sin el depósito", "sin la venta de AAPL")
 *   monto    'US$ 1.000,00' (sin signo) o null
 *   deshecho true = se borró; false = volvió (el "Deshacer" de un borrado)
 */
export function anotarCambioDeMovimiento({ texto, articulo = 'el', monto = null, deshecho = true }) {
  escribir(CLAVE_CAMBIO, { texto, articulo, monto, deshecho, cuando: Date.now() })
}

/** La pantalla, al entrar: lo anotado (y lo borra), con el total que se vio ahí antes. */
export function tomarCambioPendiente(moneda, pantalla) {
  const c = leer(CLAVE_CAMBIO)
  escribir(CLAVE_CAMBIO, null)
  if (!c || !c.texto || Date.now() - (c.cuando || 0) > VENCE_MS) return null
  const t = leer(clave_total(pantalla))
  const antes = t && t.moneda === moneda && Number.isFinite(t.total) ? t.total : null
  return { texto: c.texto, articulo: c.articulo || 'el', monto: c.monto, deshecho: !!c.deshecho, antes }
}

/** La pantalla: el total que se le está mostrando al usuario (ya con precios). */
export function recordarTotalVisto(total, moneda, pantalla) {
  if (Number.isFinite(total)) escribir(clave_total(pantalla), { total, moneda })
}
