// MovementsTable — la tabla de movimientos (rama ancha del tab "Todos").
// ═══════════════════════════════════════════════════════════════════════════
// Salió tal cual de pages/Operations.jsx. Sin estado de datos, sin fetch, y
// `histMoney` por prop: antes MovementRow llamaba `useHistoricalMoney()` una vez
// POR FILA.
//
// Ni una clase de Tailwind cambió. Lo único distinto en el render es que
// IMPUESTO ya no cae al fallback gris con la etiqueta cruda: ahora está en el
// TYPE_META compartido (venía sólo del lado mobile).

import { Fragment } from 'react'
import {
  Trash2, RotateCcw, ArrowUpRight, ArrowDownRight,
  ChevronLeft, ChevronRight, ChevronDown, ChevronUp, Repeat,
} from 'lucide-react'
import { colorClass } from '../../utils/format'
import { fmtConvertedRaw } from '../../contexts/CurrencyContext'
import EmptyState from '../EmptyState'
import { TYPE_META, DELETABLE_MOVEMENT_TYPES, amountClassFor, movPnl } from './shared'

export const MOV_PAGE_SIZE = 50

export default function MovementsTable({
  movements, filtered, pageRows, groups, grouped, groupBy,
  histMoney, currency, expandedGroups, onToggleGroup,
  onDelete, onDeleteGroup, deletingId, busyGroup,
  page, totalPages, onPage,
}) {
  return (
    <>
      {filtered.length === 0 ? (
        <EmptyState
          icon={<Repeat size={18} />}
          title="No hay movimientos"
          description="No se encontraron movimientos con los filtros aplicados."
        />
      ) : (
        <div className="border border-line rounded-xl overflow-x-auto bg-bg-1">
          <table className="w-full text-sm">
            <thead className="bg-bg-2 text-ink-3 text-[12px] font-medium">
              <tr>
                <th className="text-left px-3 py-2">Fecha</th>
                <th className="text-left px-3 py-2">Tipo</th>
                <th className="text-left px-3 py-2">Broker</th>
                <th className="text-left px-3 py-2">Activo</th>
                <th className="text-right px-3 py-2">Cant.</th>
                <th className="text-right px-3 py-2">Precio</th>
                <th className="text-right px-3 py-2">Monto {currency}</th>
                <th className="text-left px-3 py-2">Notas</th>
                <th className="px-3 py-2 w-8" aria-label="Acciones"></th>
              </tr>
            </thead>
            <tbody>
              {!grouped && pageRows.map(m => (
                <MovementRow key={m.id} m={m} histMoney={histMoney} onDelete={onDelete} deleting={deletingId === m.id} />
              ))}
              {grouped && groups.map(g => {
                const isOpen = expandedGroups.has(g.key)
                return (
                  <Fragment key={g.key}>
                    <MovementGroupRow
                      group={g}
                      groupBy={groupBy}
                      isOpen={isOpen}
                      onToggle={() => onToggleGroup(g.key)}
                      histMoney={histMoney}
                      onDeleteGroup={groupBy === 'asset' ? onDeleteGroup : null}
                      deleting={!!busyGroup[g.key]}
                    />
                    {isOpen && g.rows.map(m => (
                      <MovementRow key={m.id} m={m} histMoney={histMoney} indent onDelete={onDelete} deleting={deletingId === m.id} />
                    ))}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination — solo en modo lista plana (ver DECISIÓN PAGINACIÓN). */}
      {!grouped && totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 text-xs text-ink-3">
          <span className="font-mono tabular">Página {page + 1} de {totalPages}</span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => onPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="p-1.5 rounded-sm border border-line bg-bg-2 hover:bg-bg-3 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={12} />
            </button>
            <button
              onClick={() => onPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="p-1.5 rounded-sm border border-line bg-bg-2 hover:bg-bg-3 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronRight size={12} />
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// indent: cuando la fila es detalle de un grupo (modo agrupado), la atenuamos
// e indentamos la primera celda con un marquito "└" — mismo recurso visual que
// los lotes en Positions.
function MovementRow({ m, histMoney, indent = false, onDelete, deleting = false }) {
  // Phase C (audit fix H1): cada movimiento usa SU PROPIO FX histórico para
  // la conversión a ARS. m.fx_to_usd (si stampeado) > lookup por m.date >
  // tcValuacion actual. Esto evita que un retiro de $1000 USD en 2024 (blue era
  // 1100) se muestre hoy como $1.466.000 ARS (al blue actual ~1466) cuando
  // en realidad fueron ~$1.100.000 ARS al tipo de cambio del momento.
  //
  // decimals:2 para que la columna sea coherente: el header del grupo muestra
  // centavos, así que las filas que despliega tienen que mostrarlos también
  // (si no, el total "no cierra" con la suma visible de sus filas).
  const fmtUsd = (v) => histMoney.fmtMoneyAt(v, {
    stampedFx: m.fx_to_usd,
    rowCurrency: m.currency,
    dateIso: m.date,
    signed: false,
    decimals: 2,
  })
  const meta = TYPE_META[m.type] || { label: m.type, Icon: Repeat, color: 'text-ink-3', tone: null }
  const { Icon } = meta
  const amountClass = TYPE_META[m.type] ? amountClassFor(m.type) : 'text-ink-1'
  return (
    <tr className={`border-t border-line/60 hover:bg-bg-2/40 ${indent ? 'bg-bg-2/15' : ''}`}>
      <td className={`px-3 py-2 text-ink-2 tabular text-xs ${indent ? 'pl-6 opacity-75' : ''}`}>
        {indent && <span className="text-ink-3 font-mono select-none mr-1" title="Detalle">└</span>}
        {m.date || '—'}
        {m.approx_date && <span className="ml-1 text-[9px] text-ink-3" title="Fecha aproximada (agregado mensual)">~</span>}
      </td>
      <td className="px-3 py-2">
        <span className={`inline-flex items-center gap-1 text-xs ${meta.color}`}>
          <Icon size={11} strokeWidth={2} aria-hidden="true" />
          {meta.label}
        </span>
      </td>
      <td className="px-3 py-2 text-ink-3 text-xs">{m.broker || '—'}</td>
      <td className="px-3 py-2 font-medium text-ink-0 text-xs">{m.asset || '—'}</td>
      <td className="px-3 py-2 text-right font-mono text-ink-2 tabular text-xs">
        {m.quantity != null ? Number(m.quantity).toLocaleString('es-AR', { maximumFractionDigits: 4 }) : '—'}
      </td>
      <td className="px-3 py-2 text-right font-mono text-ink-2 tabular text-xs">
        {m.unit_price != null ? Number(m.unit_price).toLocaleString('es-AR', { maximumFractionDigits: 2 }) : '—'}
      </td>
      <td className={`px-3 py-2 text-right font-mono font-medium tabular ${amountClass}`}>
        {fmtUsd(m.amount_usd || 0)}
      </td>
      <td className="px-3 py-2 text-ink-3 text-xs max-w-xs truncate" title={m.notes}>
        {m.notes || (m.source === 'monthly' ? 'Agregado mensual' : m.source === 'import' ? 'Desde import CSV' : '')}
      </td>
      <td className="px-2 py-2 text-right">
        {onDelete && DELETABLE_MOVEMENT_TYPES.includes(m.type) && (
          <button
            type="button"
            onClick={() => onDelete(m)}
            disabled={deleting}
            title={m.transfer_out ? `Reabrir ${m.asset || 'la posición'}` : 'Borrar movimiento'}
            aria-label={m.transfer_out ? `Reabrir ${m.asset || 'la posición'}` : 'Borrar movimiento'}
            className={`p-1 rounded-sm text-ink-3 disabled:opacity-40 disabled:cursor-wait ${
              m.transfer_out ? 'hover:text-rendi-pos hover:bg-rendi-pos/10'
                             : 'hover:text-rendi-neg hover:bg-rendi-neg/10'}`}
          >
            {/* Un cierre a costo NO se "borra": se DESHACE y la posición vuelve. El
                ícono de deshacer evita que el tacho asuste (borrar ≠ recuperar). */}
            {m.transfer_out
              ? <RotateCcw size={13} strokeWidth={1.75} aria-hidden="true" />
              : <Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />}
          </button>
        )}
      </td>
    </tr>
  )
}

// Fila-resumen de un grupo (modo agrupado por activo o por mes). Click → toggle
// del despliegue de sus movimientos. Muestra: etiqueta del grupo (ticker o mes)
// · broker(s) · # de movimientos · P&L realizado total con flecha ↗/↘.
//
// ⚠️ CONVERT-THEN-SUM, igual que TradeGroupRow (ver el comentario largo allá):
// cada fila se convierte con SU FX histórico y recién ahí se suma, para que el
// total coincida con las filas que despliega.
function MovementGroupRow({ group, groupBy, isOpen, onToggle, histMoney, onDeleteGroup, deleting }) {
  const { label, count, brokers } = group
  // El tacho de "borrar todo el historial" solo aplica a un ACTIVO de verdad: no a
  // "Sin activo" (depósitos/retiros sueltos) ni a los grupos de puro efectivo, que no
  // tienen compras ni ventas que borrar.
  const canDeleteGroup = !!onDeleteGroup && group.key !== '__no_asset__'
    && group.rows.some(r => r.type === 'BUY' || r.type === 'SELL')
  // Ver TradeGroupRow: signo/color/flecha sobre el número que se muestra.
  const pnl = histMoney.sumConvertedAt(group.rows, r => movPnl(r))
  const pnlDisp = pnl
  const Chevron = isOpen ? ChevronUp : ChevronDown
  const hasPnl = pnl !== 0
  const Arrow = pnl > 0 ? ArrowUpRight : pnl < 0 ? ArrowDownRight : null
  const brokersLabel = brokers.length === 0
    ? '—'
    : brokers.length <= 2
    ? brokers.join(' · ')
    : `${brokers.length} brokers`
  return (
    <tr
      className="border-t border-line/60 bg-bg-2/40 hover:bg-bg-2/60 cursor-pointer transition-colors"
      onClick={onToggle}
    >
      {/* Etiqueta del grupo + chevron — ocupa Fecha + Tipo */}
      <td className="px-3 py-2.5" colSpan={2}>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onToggle() }}
          className="inline-flex items-center gap-1.5 text-ink-0 font-semibold text-sm"
          aria-expanded={isOpen}
        >
          <Chevron size={13} strokeWidth={2} className="text-ink-3" aria-hidden="true" />
          {label}
        </button>
      </td>
      {/* Broker(s) */}
      <td className="px-3 py-2.5 text-ink-3 text-xs">
        {groupBy === 'asset' ? brokersLabel : '—'}
      </td>
      {/* # movimientos — bajo "Activo" */}
      <td className="px-3 py-2.5 text-ink-2 text-xs" colSpan={3}>
        <span className="text-[12.5px] font-medium">
          {count} {count === 1 ? 'movimiento' : 'movimientos'}
        </span>
      </td>
      {/* P&L realizado total con flecha — bajo "Monto" */}
      <td className={`px-3 py-2.5 text-right font-mono font-semibold tabular ${colorClass(hasPnl ? pnl : null)}`}>
        <span className="inline-flex items-center gap-1 justify-end">
          {Arrow && <Arrow size={13} strokeWidth={2.25} aria-hidden="true" />}
          {hasPnl ? fmtConvertedRaw(pnlDisp, histMoney.currency, { signed: true, decimals: 2 }) : '—'}
        </span>
      </td>
      {/* Notas — hint del P&L + tacho del activo entero */}
      <td className="px-3 py-2.5 text-ink-3 text-[12px] font-medium">
        <div className="inline-flex items-center gap-2 justify-end w-full">
          {hasPnl ? 'P&L realizado' : ''}
          {canDeleteGroup && (
            <button
              type="button"
              disabled={deleting}
              onClick={(e) => { e.stopPropagation(); onDeleteGroup(group) }}
              aria-label={`Borrar todo el historial de ${label}`}
              title={`Borrar todo el historial de ${label}`}
              className="p-1 text-ink-3 hover:text-rendi-neg transition-colors disabled:opacity-40 disabled:pointer-events-none"
            >
              <Trash2 size={14} strokeWidth={1.75} aria-hidden="true" />
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}
