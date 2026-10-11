// registrar — lo que se puede anotar a mano en Rendi, y cómo se le pide a la
// Cartera que abra cada formulario. UNA lista para el botón «Registrar» del
// menú lateral, el "+" del celular y las dos Carteras (compu y celular): si
// cada uno tuviera la suya, una acción nueva terminaría yendo a una pantalla
// que no la entiende y cae en la Cartera sin abrir nada (le pasó a "Agregar a
// watchlist", que iba a `/?action=watchlist`).
//
// Los formularios viven en la Cartera (compra, venta, efectivo y conversión
// comparten sus datos y su recálculo), así que registrar desde cualquier
// pantalla es ir a `/posiciones?action=<valor>`: la Cartera lee el pedido, abre
// el formulario y limpia la dirección para que recargar no lo vuelva a abrir.
import { DollarSign, ShoppingCart, ArrowDownCircle, ArrowUpCircle, ArrowLeftRight } from 'lucide-react'

// El orden es el del menú (pedido de Nico, 2026-10-11). `valor` es lo que viaja
// en la dirección: 'new' y 'sell' son los que ya usaba el "+" del celular.
// `grupo` sólo decide dónde va una línea divisoria en el menú.
export const ACCIONES_REGISTRAR = [
  { id: 'vender',    valor: 'sell',     grupo: 'operacion', label: 'Venta',      sub: 'Vender una tenencia',                  icon: DollarSign,      tone: 'pos' },
  { id: 'comprar',   valor: 'new',      grupo: 'operacion', label: 'Compra',     sub: 'Agregar una tenencia nueva',           icon: ShoppingCart,    tone: 'accent' },
  { id: 'depositar', valor: 'deposit',  grupo: 'efectivo',  label: 'Depósito',   sub: 'Entra plata al broker',                icon: ArrowDownCircle, tone: 'pos' },
  { id: 'retirar',   valor: 'withdraw', grupo: 'efectivo',  label: 'Retiro',     sub: 'Sale plata del broker',                icon: ArrowUpCircle,   tone: 'warn' },
  { id: 'convertir', valor: 'convert',  grupo: 'moneda',    label: 'Movimiento', sub: 'Pasar de pesos a dólares, o al revés', icon: ArrowLeftRight,  tone: 'info' },
]

const PARAMETRO = 'action'

// A dónde hay que ir para registrar `id` ('comprar', 'vender', …).
export function direccionDeRegistrar(id) {
  const accion = ACCIONES_REGISTRAR.find(a => a.id === id)
  if (!accion) throw new Error(`registrar: no existe la acción «${id}»`)
  return `/posiciones?${PARAMETRO}=${accion.valor}`
}

// Qué pide la dirección: el `id` de la acción o null. Es lo que usan las dos
// Carteras para abrir el formulario.
export function accionDelPedido(search) {
  const valor = new URLSearchParams(search || '').get(PARAMETRO)
  return ACCIONES_REGISTRAR.find(a => a.valor === valor)?.id || null
}

// ¿Esta caja de efectivo se puede convertir, y hacia dónde? Los pesos de una
// cuenta argentina se pasan a dólares; los dólares de su sub-cuenta, a pesos.
// Es la misma regla para el menú de la fila (positionActions) y para el
// selector de «Movimiento».
export function conversionDeLaCaja(p, broker) {
  if (!p?.is_cash || !broker) return null
  if (broker.currency === 'ARS') return 'ars_to_usd'
  if (broker.currency === 'USDT' && broker.parent_broker_id != null) return 'usd_to_ars'
  return null
}

// Las cajas que hoy se pueden convertir, con su dirección.
export function cajasParaConvertir(positions, brokers) {
  return (positions || []).flatMap(p => {
    const direction = conversionDeLaCaja(p, (brokers || []).find(b => b.name === p.broker))
    return direction ? [{ p, direction }] : []
  })
}
