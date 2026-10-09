// cambioDeCobro — el aviso "Recalculando tu cartera" cuando el cambio pasó en
// OTRA pantalla.
//
// Caso (pedido de Nico, 2026-10-09): el usuario borra un dividendo desde
// Movimientos. El total de Cartera tiene que bajar, y la próxima vez que lo vea
// tiene que VER que se recalculó: del total que vio la última vez al nuevo.
//
//   · Movimientos, al borrar un cobro, deja anotado qué se sacó
//     (`anotarCambioDeCobro`).
//   · Cartera recuerda el último total que mostró (`recordarTotalVisto`), y al
//     entrar toma lo anotado (`tomarCambioPendiente`) y lo muestra con
//     <RecalculoDeCartera>, desde ese total hasta el que devuelve el servidor.
//
// Vive en sessionStorage: es de esta pestaña y de esta visita, nada más. Si el
// navegador no deja guardar (ventana privada), no hay aviso y nada se rompe.

const CLAVE_CAMBIO = 'rendi:cambio-de-cobro'
const CLAVE_TOTAL = 'rendi:ultimo-total-cartera'
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

/** Movimientos: se sacó (o sumó) un cobro y Cartera todavía no lo mostró. */
export function anotarCambioDeCobro({ texto, monto, deshecho = false }) {
  escribir(CLAVE_CAMBIO, { texto, monto, deshecho, cuando: Date.now() })
}

/** Cartera, al entrar: lo anotado (y lo borra), con el total que se vio antes. */
export function tomarCambioPendiente(moneda) {
  const c = leer(CLAVE_CAMBIO)
  escribir(CLAVE_CAMBIO, null)
  if (!c || !c.texto || Date.now() - (c.cuando || 0) > VENCE_MS) return null
  const t = leer(CLAVE_TOTAL)
  const antes = t && t.moneda === moneda && Number.isFinite(t.total) ? t.total : null
  return { texto: c.texto, monto: c.monto, deshecho: !!c.deshecho, antes }
}

/** Cartera: el total que se le está mostrando al usuario (ya con precios). */
export function recordarTotalVisto(total, moneda) {
  if (Number.isFinite(total)) escribir(CLAVE_TOTAL, { total, moneda })
}
