// cambioDeMovimiento — el aviso "Recalculando tu cartera" cuando el cambio pasó
// en OTRA pantalla.
//
// Caso (pedido de Nico, 2026-10-09): el usuario borra un movimiento desde
// Movimientos —un dividendo, un depósito, una venta—. El total de la cartera
// cambia, y la PRÓXIMA pantalla que lo muestre (Cartera o Dashboard) tiene que
// dejar VER que se recalculó: del total que se vio ahí la última vez al nuevo.
//
//   · Movimientos, al borrar (o deshacer un borrado), deja anotado qué cambió
//     (`anotarCambioDeMovimiento`). Se ACUMULA: dos borrados antes de volver a
//     Cartera son "2 cambios", no el último solo; borrar y deshacer lo mismo se
//     cancela (auditoría 2026-10-09: decía "Borrado: US$ 500" después de sacar
//     1.000 y 500).
//   · Cada pantalla con total recuerda el último que mostró
//     (`recordarTotalVisto`, por pantalla: Cartera y Dashboard no calculan
//     exactamente lo mismo, y mezclarlos inventaría una diferencia).
//   · La primera que se abre toma lo anotado (`tomarCambioPendiente`) y lo
//     muestra con <RecalculoDeCartera>. Se muestra UNA vez.
//
// TODO ES DE UNA CUENTA. Las claves llevan la cuenta que se está mirando (la
// propia o la del cliente del asesor): sin eso, un asesor que miraba el cliente
// A (US$ 500.000) y borraba un depósito de B veía "US$ 500.000 → US$ 20.000" —
// un número falso y además el total de otro cliente (auditoría 2026-10-09). Y
// empiezan con `rendi_`, el prefijo que borra el cierre de sesión
// (AuthContext): la persona que entra después en la misma pestaña no hereda
// nada de la anterior.
//
// Vive en sessionStorage: es de esta pestaña y de esta visita. Si el navegador
// no deja guardar (ventana privada), no hay aviso y nada se rompe.

import { getClientContext } from './api'

const VENCE_MS = 30 * 60 * 1000   // un aviso de hace más de media hora ya no dice nada

function cuenta() {
  const id = getClientContext()?.id
  return id != null ? `cliente-${id}` : 'propia'
}
const claveCambios = () => `rendi_cambios_movimientos:${cuenta()}`
const claveTotal = (pantalla) => `rendi_ultimo_total:${cuenta()}:${pantalla}`

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
  const ahora = Date.now()
  const lista = (leer(claveCambios()) || []).filter(c => ahora - (c.cuando || 0) <= VENCE_MS)
  // Borrar y deshacer lo mismo (o al revés) se cancela: el total volvió a donde estaba.
  const opuesto = lista.findIndex(c => c.texto === texto && c.monto === monto && c.deshecho === !deshecho)
  if (opuesto >= 0) lista.splice(opuesto, 1)
  else lista.push({ texto, articulo, monto, deshecho, cuando: ahora })
  escribir(claveCambios(), lista.length ? lista : null)
}

/**
 * La pantalla, al entrar: lo anotado (y lo borra), con el total que se vio ahí
 * antes. Con un solo cambio, ése; con varios, un resumen ("3 cambios en
 * Movimientos", sin monto: no hay UN monto que explique la diferencia).
 */
export function tomarCambioPendiente(moneda, pantalla) {
  const lista = (leer(claveCambios()) || []).filter(c => c && c.texto && Date.now() - (c.cuando || 0) <= VENCE_MS)
  escribir(claveCambios(), null)
  if (!lista.length) return null
  const t = leer(claveTotal(pantalla))
  const antes = t && t.moneda === moneda && Number.isFinite(t.total) ? t.total : null
  if (lista.length === 1) {
    const c = lista[0]
    return { texto: c.texto, articulo: c.articulo || 'el', monto: c.monto, deshecho: !!c.deshecho, antes }
  }
  return { texto: `${lista.length} cambios en Movimientos`, articulo: 'tus', monto: null,
           deshecho: false, varios: true, antes }
}

/** La pantalla: el total que se le está mostrando al usuario (ya con precios). */
export function recordarTotalVisto(total, moneda, pantalla) {
  if (Number.isFinite(total)) escribir(claveTotal(pantalla), { total, moneda })
}
