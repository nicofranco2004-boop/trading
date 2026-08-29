// shared — el vocabulario común de la pantalla Operaciones.
// ═══════════════════════════════════════════════════════════════════════════
// Hasta la Fase 3 esto vivía duplicado entre pages/Operations.jsx (tabla) y
// pages/OperationsMobile.jsx (feed), que era un fork por viewport. Al matarlo,
// TODO lo que no es JSX vino acá: los dos renderers importan de un solo lugar.
//
// Nada de esto toca React ni hace fetch. Son datos y funciones puras.

import {
  ArrowUpRight, ArrowDownRight, ArrowDownToLine, ArrowUpFromLine,
  Coins, Receipt, SlidersHorizontal,
} from 'lucide-react'

// ─── Tipos de movimiento ───────────────────────────────────────────────────
// UN solo mapa. Antes eran dos (`TYPE_META` desktop / `MOVE_TYPE_META` mobile)
// y NO eran el mismo objeto con otro nombre: tenían campos distintos que
// cubren EJES distintos, y colapsarlos habría cambiado los dos renders.
//
//   · `color` → el badge del TIPO en la tabla desktop.
//   · `tone`  → el color del MONTO (y, en el feed, el chip del ícono).
//
// En el desktop el color del monto no salía de acá sino de dos listas sueltas
// (`isPositive` / `isNegative`); `tone` las reemplaza y da exactamente el mismo
// resultado en las 7 claves que ya existían. Por eso están los dos campos: con
// uno solo, el retiro perdía su badge `warn` y compra/venta sus data-blue /
// data-violet.
//
// IMPUESTO existía SÓLO en mobile. El desktop lo pintaba con el fallback: la
// etiqueta cruda "IMPUESTO" en gris, con ícono `Repeat`, pese a ser borrable.
// Al compartir el mapa, el desktop lo gana.
export const TYPE_META = {
  BUY:      { label: 'Compra',     Icon: ArrowUpRight,     color: 'text-data-blue',    tone: null },
  SELL:     { label: 'Venta',      Icon: ArrowDownRight,   color: 'text-data-violet',  tone: null },
  DEPOSIT:  { label: 'Depósito',   Icon: ArrowDownToLine,  color: 'text-rendi-pos',    tone: 'pos' },
  WITHDRAW: { label: 'Retiro',     Icon: ArrowUpFromLine,  color: 'text-rendi-warn',   tone: 'neg' },
  DIVIDEND: { label: 'Dividendo',  Icon: Coins,            color: 'text-rendi-pos',    tone: 'pos' },
  INTEREST: { label: 'Interés',    Icon: Coins,            color: 'text-rendi-pos',    tone: 'pos' },
  FEE:      { label: 'Comisión',   Icon: Receipt,          color: 'text-ink-3',        tone: 'neg' },
  IMPUESTO: { label: 'Impuesto',   Icon: Receipt,          color: 'text-ink-3',        tone: 'neg' },
}

// Clase del MONTO a partir del `tone`. Es lo que el desktop calculaba con
// `isPositive`/`isNegative` y el feed con su propio ternario.
export function amountClassFor(type) {
  const tone = TYPE_META[type]?.tone
  return tone === 'pos' ? 'text-rendi-pos' : tone === 'neg' ? 'text-rendi-neg' : 'text-ink-1'
}

// Cash-flows + trades (compras/ventas rutean al motor de cascada del backend,
// que bloquea con mensaje claro lo que aún no soporta: manuales en pesos, bonos,
// compras ya vendidas, activos con data manual mezclada).
// Estaba duplicada byte a byte en los dos archivos.
export const DELETABLE_MOVEMENT_TYPES = ['DEPOSIT', 'WITHDRAW', 'DIVIDEND', 'INTEREST', 'FEE', 'IMPUESTO', 'BUY', 'SELL']

export const MOVEMENT_TYPES = [
  { id: 'all',      label: 'Todos',        icon: SlidersHorizontal },
  { id: 'BUY',      label: 'Compras',      icon: ArrowUpRight,      tone: 'pos' },
  { id: 'SELL',     label: 'Ventas',       icon: ArrowDownRight,    tone: 'neg' },
  { id: 'DEPOSIT',  label: 'Depósitos',    icon: ArrowDownToLine,   tone: 'pos' },
  { id: 'WITHDRAW', label: 'Retiros',      icon: ArrowUpFromLine,   tone: 'neg' },
  { id: 'DIVIDEND', label: 'Dividendos',   icon: Coins,             tone: 'pos' },
  { id: 'INTEREST', label: 'Intereses',    icon: Coins,             tone: 'pos' },
  { id: 'FEE',      label: 'Comisiones',   icon: Receipt,           tone: 'neg' },
]

// ─── Etiquetas ─────────────────────────────────────────────────────────────

export const MESES_ES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']

export function prettyOpType(raw) {
  if (!raw) return '—'
  const s = String(raw).trim()
  if (s.startsWith('CONVERSION IMPORT ARS→USDT') || s.startsWith('CONVERSION IMPORT ARS→USD')) return 'Conversión ARS→USD'
  if (s.startsWith('CONVERSION IMPORT USDT→ARS') || s.startsWith('CONVERSION IMPORT USD→ARS')) return 'Conversión USD→ARS'
  return s
}

export function prettyMonth(ym) {
  if (!ym || ym.length < 7) return ym || 'Sin fecha'
  const [y, m] = ym.split('-')
  const idx = parseInt(m, 10) - 1
  return idx >= 0 && idx < 12 ? `${MESES_ES[idx]} ${y}` : ym
}

export function formatDateLabel(date) {
  if (!date || date === 'sin-fecha') return 'Sin fecha'
  // Esperamos YYYY-MM-DD
  const d = new Date(date + 'T00:00:00')
  if (isNaN(d)) return date
  const today = new Date()
  const sameDay = d.toDateString() === today.toDateString()
  if (sameDay) return 'Hoy'
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) return 'Ayer'
  return `${d.getDate()} ${MESES_ES[d.getMonth()]} ${d.getFullYear()}`
}

// OJO: NO es la misma regla que usa la columna "Cant." de la tabla desktop, que
// formatea inline con `toLocaleString('es-AR', { maximumFractionDigits: 4 })`.
// Difieren en locale, en el redondeo arriba de 1000 y en el piso de 4 decimales.
// Vive acá porque el feed la usa, no para que la tabla la adopte: cambiarla
// movería números en pantalla.
export function formatQty(q) {
  if (q == null || isNaN(q)) return '—'
  if (Math.abs(q) >= 1000) return Math.round(q).toLocaleString('en-US')
  if (Math.abs(q) >= 1) return q.toFixed(2).replace(/\.00$/, '')
  return q.toFixed(4)
}

// ─── P&L de un movimiento ──────────────────────────────────────────────────
// Solo las ventas (SELL, vía operations) traen `pnl_usd` stampeado; el resto de
// los tipos (BUY/DEPOSIT/WITHDRAW/DIVIDEND/INTEREST/FEE) no aportan P&L
// realizado y suman 0. Los dividendos/intereses importados NO traen pnl_usd (su
// monto vive en amount_usd como ingreso), así que acá cuentan 0 — el P&L
// realizado refleja estrictamente trades cerrados.
export function movPnl(m) {
  return typeof m.pnl_usd === 'number' ? m.pnl_usd : 0
}

// ─── Eje temporal ──────────────────────────────────────────────────────────
// UNA sola lista mutuamente excluyente. Antes eran dos ejes que no se
// solapaban: el desktop tenía años ('2026', '2025', …) y el feed ventanas
// relativas ('30d', '90d', '1y'). Sumarlos habría permitido combinaciones
// imposibles (año 2024 + últimos 30 días = vacío garantizado).
export const PERIOD_FIJOS = [
  { id: 'all',  label: 'Todo' },
  { id: '30d',  label: 'Último mes' },
  { id: '90d',  label: 'Últimos 3M' },
  { id: '365d', label: 'Último año' },
]

/** Las opciones fijas + un año por cada año presente en los datos, desc. */
export function buildPeriodOptions(rows) {
  const años = [...new Set((rows || []).map(r => (r.date || '').slice(0, 4)).filter(Boolean))]
    .sort().reverse()
  return [...PERIOD_FIJOS, ...años.map(y => ({ id: y, label: y }))]
}

/**
 * UN predicado: si el id termina en 'd' es ventana relativa, si son 4 dígitos
 * es un año.
 *
 * Las dos ramas tratan distinto a las filas SIN fecha, y es a propósito: cada
 * una conserva la semántica que ya tenía su dueño. Ventana relativa → pasan
 * (era el `if (cutoff && o.date)` del feed). Año → no pasan (era el
 * `!(o.date || '').startsWith(year)` de la tabla).
 */
export function enPeriodo(dateStr, period) {
  if (!period || period === 'all') return true
  if (/^\d+d$/.test(period)) {
    if (!dateStr) return true
    const t = new Date(dateStr).getTime()
    if (!isFinite(t)) return true
    return t >= Date.now() - parseInt(period, 10) * 86400000
  }
  if (/^\d{4}$/.test(period)) return (dateStr || '').startsWith(period)
  return true
}

// ─── Agrupación ────────────────────────────────────────────────────────────

export const GROUP_OPTIONS = [
  { id: 'asset', label: 'Activo' },
  { id: 'month', label: 'Mes' },
  { id: 'none',  label: 'Ninguno' },
]

// Clave del grupo de las filas sin fecha. Antes era la string 'Sin fecha' (mes)
// o 'sin-fecha' (día), y las dos ORDENABAN MAL: el sort es `localeCompare`
// descendente sobre la clave, y 's'/'S' > '2', así que el grupo sin fecha
// quedaba ARRIBA de todo. Ahora se lo saca del orden y se lo manda al final.
export const SIN_FECHA = '__sin_fecha__'

/**
 * Agrupa filas (YA filtradas) por día, mes o activo.
 * Devuelve { key, label, rows, count, pnl, brokers } ordenados.
 *
 * `pnl` es la suma CRUDA en USD y se usa sólo para ORDENAR. Lo que se muestra
 * lo recalcula cada renderer con `histMoney.sumConvertedAt(group.rows, …)`
 * (convert-then-sum), que es lo único que garantiza `total === Σ filas`.
 */
export function buildGroups(rows, groupBy) {
  const map = new Map()
  for (const m of rows) {
    let key, label
    if (groupBy === 'day') {
      key = m.date || SIN_FECHA
      label = key === SIN_FECHA ? 'Sin fecha' : formatDateLabel(key)
    } else if (groupBy === 'month') {
      key = (m.date || '').slice(0, 7) || SIN_FECHA
      label = key === SIN_FECHA ? 'Sin fecha' : prettyMonth(key)
    } else {
      // 'asset' — ops sin activo (depósitos/retiros/conversiones) caen en un
      // grupo "Sin activo" para no perderlas.
      key = (m.asset || '').trim() || '__no_asset__'
      label = key === '__no_asset__' ? 'Sin activo' : key
    }
    if (!map.has(key)) map.set(key, { key, label, rows: [], pnl: 0, brokers: new Set() })
    const g = map.get(key)
    g.rows.push(m)
    g.pnl += movPnl(m)
    if (m.broker) g.brokers.add(m.broker)
  }
  const groups = [...map.values()].map(g => ({
    key: g.key,
    label: g.label,
    rows: g.rows.slice().sort((a, b) => (b.date || '').localeCompare(a.date || '')),
    count: g.rows.length,
    pnl: g.pnl,
    brokers: [...g.brokers],
  }))
  // Por fecha (día o mes) → cronológico desc, con el grupo sin fecha SIEMPRE al
  // final. Por activo → P&L realizado desc (lo más relevante arriba), con
  // desempate por # de movimientos y luego alfabético.
  if (groupBy === 'day' || groupBy === 'month') {
    groups.sort((a, b) => {
      if (a.key === SIN_FECHA) return 1
      if (b.key === SIN_FECHA) return -1
      return b.key.localeCompare(a.key)
    })
  } else {
    groups.sort((a, b) => (b.pnl - a.pnl) || (b.count - a.count) || a.label.localeCompare(b.label))
  }
  return groups
}
