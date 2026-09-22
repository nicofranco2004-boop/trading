// positionActions — QUÉ acciones ofrece una fila de la cartera, en UN solo lugar.
// ═══════════════════════════════════════════════════════════════════════════
// El menú de los tres puntitos existía escrito DOS veces: `buildPositionMenu`
// en Positions.jsx (escritorio) y un array armado a mano dentro de PositionRow
// en PositionsMobile.jsx (celular). Las dos copias se separaron sin que nada
// lo avisara:
//
//   escritorio          Agregar compra · Registrar venta · Crear alerta ·
//                       Editar posición · Eliminar
//   celular (antes)     Analizar · Vender · Editar · Eliminar
//
// O sea: desde el teléfono no había forma de agregar una compra sobre una
// posición existente ni de crear una alerta, y las dos acciones que sí estaban
// se llamaban distinto que en la compu. Lo mismo en efectivo: "Comprar USD"
// (pesos) y "Vender USD a ARS" (sub-broker en dólares) sólo existían en la
// pantalla grande, y en bonos faltaban cupón y amortización enteros.
//
// Esta función devuelve DESCRIPTORES NEUTROS — sin JSX, sin clases de Tailwind,
// sin decidir si el menú es un popover o un bottom sheet. Cada pantalla los
// dibuja como le corresponde:
//
//   { id, label, icon: <componente lucide>, tone, danger?, onClick }
//   { divider: true }
//
// `tone` ('pos' | 'neg' | 'warn' | 'accent' | undefined) es la intención, no el
// color: el popover del escritorio lo usa sólo para el rojo de Eliminar y el
// sheet del celular lo usa para pintar el renglón entero.
//
// Un handler que no se pasa hace desaparecer su ítem. Así una pantalla que
// todavía no tiene, por ejemplo, el modal de conversión no muestra la opción
// muerta — pero tampoco puede "olvidarse" de un ítem sin que se note al leer
// las props que le pasa.

import {
  ShoppingCart, DollarSign, Bell, Pencil, Trash2, Coins, Sparkles,
  ArrowDownCircle, ArrowUpCircle, ChevronUp, Layers as LayersIcon,
} from 'lucide-react'
import { filaSinUnaPata } from './filaFusionada'

/**
 * @param {object}  p          La fila (posición, lote, agregado o efectivo).
 * @param {object}  handlers   Callbacks; el que falte esconde su ítem.
 * @param {object}  opts       { broker, isAgg, isBond, lotCount, expanded }
 * @returns {Array} descriptores (ver arriba), con `{divider:true}` intercalados.
 */
export function buildPositionActions(p, handlers = {}, opts = {}) {
  const {
    onAnalyze, onBuy, onSell, onAlert, onEdit, onEditGroup, onDelete,
    onCashFlow, onConvert, onBondCashflow, onToggleLots,
  } = handlers
  const { broker, isAgg = false, isBond = false, lotCount = 0, expanded = false } = opts

  // "Analizar" (la IA de la fila) va primero donde exista. El escritorio no lo
  // pasa: tiene su propio botón ✦ al lado de la fila.
  const analizar = onAnalyze && {
    id: 'ai', label: 'Analizar', icon: Sparkles, tone: 'accent',
    onClick: () => onAnalyze(p),
  }

  // ── Fila AGREGADA (varios lotes del mismo ticker) ──────────────────────
  // Editar/Eliminar son POR LOTE: el agregado es sintético, no hay un id que
  // editar y promediar rompería el costo FIFO y las fechas de compra.
  if (isAgg) {
    const verLotes = onToggleLots && {
      id: 'lots',
      label: expanded ? `Ocultar lotes${lotCount ? ` (${lotCount})` : ''}` : `Ver lotes${lotCount ? ` (${lotCount})` : ''}`,
      icon: expanded ? ChevronUp : LayersIcon,
      tone: 'accent',
      onClick: () => onToggleLots(p),
    }
    const editarPosicion = onEditGroup && {
      id: 'edit-group', label: 'Editar posición', icon: Pencil, tone: 'accent',
      onClick: () => onEditGroup(p),
    }

    // La fila que fusiona las DOS patas de la cuenta (comprada en pesos y en
    // dólares) no tiene UN broker al que mandar una escritura: "Ver lotes" va
    // primero porque ahí cada lote es su posición real.
    if (filaSinUnaPata(p)) {
      return compact([
        analizar,
        verLotes,
        { divider: true },
        editarPosicion,
        { divider: true },
        onBuy  && { id: 'buy',  label: 'Agregar compra',  icon: ShoppingCart, tone: 'accent', onClick: () => onBuy(p) },
        onSell && { id: 'sell', label: 'Registrar venta', icon: DollarSign,   tone: 'neg',    onClick: () => onSell(p) },
        onAlert && { id: 'alert', label: 'Crear alerta',  icon: Bell,         onClick: () => onAlert(p) },
      ])
    }

    return compact([
      analizar,
      onBuy  && { id: 'buy',  label: 'Agregar compra',  icon: ShoppingCart, tone: 'accent', onClick: () => onBuy(p) },
      onSell && { id: 'sell', label: 'Registrar venta', icon: DollarSign,   tone: 'neg',    onClick: () => onSell(p) },
      onAlert && { id: 'alert', label: 'Crear alerta',  icon: Bell,         onClick: () => onAlert(p) },
      { divider: true },
      verLotes,
      editarPosicion,
    ])
  }

  // ── Efectivo ───────────────────────────────────────────────────────────
  if (p.is_cash) {
    const esCashArs = broker?.currency === 'ARS'
    const esCashUsdSubBroker = broker?.currency === 'USDT' && broker?.parent_broker_id != null
    return compact([
      onCashFlow && { id: 'deposit',  label: 'Depositar', icon: ArrowDownCircle, tone: 'pos',  onClick: () => onCashFlow(p, 'deposit') },
      onCashFlow && { id: 'withdraw', label: 'Retirar',   icon: ArrowUpCircle,   tone: 'warn', onClick: () => onCashFlow(p, 'withdraw') },
      esCashArs && onConvert && {
        id: 'to-usd', label: 'Comprar USD', icon: DollarSign, tone: 'accent',
        onClick: () => onConvert(p, 'ars_to_usd'),
      },
      esCashUsdSubBroker && onConvert && {
        id: 'to-ars', label: 'Vender USD a ARS', icon: DollarSign, tone: 'accent',
        onClick: () => onConvert(p, 'usd_to_ars'),
      },
      { divider: true },
      onEdit   && { id: 'edit',   label: 'Editar posición', icon: Pencil, tone: 'accent', onClick: () => onEdit(p) },
      onDelete && { id: 'delete', label: 'Eliminar',        icon: Trash2, tone: 'neg', danger: true, onClick: () => onDelete(p) },
    ])
  }

  // ── Bonos ──────────────────────────────────────────────────────────────
  // Cupón y amortización son los eventos que generan cash recibido del bono:
  // van arriba porque son las acciones más frecuentes en renta fija.
  const cabeceraBono = (isBond && onBondCashflow) ? [
    { id: 'coupon', label: 'Registrar cupón',        icon: Coins,      tone: 'pos',    onClick: () => onBondCashflow(p, 'coupon') },
    { id: 'amort',  label: 'Registrar amortización', icon: LayersIcon, tone: 'accent', onClick: () => onBondCashflow(p, 'amortization') },
    { divider: true },
  ] : []

  // ── Posición normal ────────────────────────────────────────────────────
  return compact([
    analizar,
    ...cabeceraBono,
    onBuy   && { id: 'buy',   label: 'Agregar compra',  icon: ShoppingCart, tone: 'accent', onClick: () => onBuy(p) },
    onSell  && { id: 'sell',  label: 'Registrar venta', icon: DollarSign,   tone: 'neg',    onClick: () => onSell(p) },
    onAlert && { id: 'alert', label: 'Crear alerta',    icon: Bell,         onClick: () => onAlert(p) },
    { divider: true },
    onEdit   && { id: 'edit',   label: 'Editar posición', icon: Pencil, tone: 'accent', onClick: () => onEdit(p) },
    onDelete && { id: 'delete', label: 'Eliminar',        icon: Trash2, tone: 'neg', danger: true, onClick: () => onDelete(p) },
  ])
}

// Saca los falsy y además los separadores que quedaron sueltos: si los ítems de
// un bloque no existen, su línea divisoria tampoco tiene que dibujarse (ni al
// principio, ni al final, ni dos seguidas).
function compact(items) {
  const vivos = items.filter(Boolean)
  const out = []
  for (const it of vivos) {
    if (it.divider) {
      if (out.length === 0) continue
      if (out[out.length - 1].divider) continue
    }
    out.push(it)
  }
  while (out.length && out[out.length - 1].divider) out.pop()
  return out
}
