// TradesTable — la tabla densa de trades cerrados (rama ancha de /operaciones).
// ═══════════════════════════════════════════════════════════════════════════
// Salió tal cual de pages/Operations.jsx cuando se mató el fork por viewport.
// NO tiene estado de datos: no fetchea, no lee localStorage y recibe `histMoney`
// por prop (nunca llama al hook adentro — instanciarlo por fila reconstruye el
// índice FX una vez por fila).
//
// Ni una clase de Tailwind cambió respecto del original: el refactor es puro.

import { Fragment } from 'react'
import {
  Plus, Pencil, Trash2, ArrowUpRight, ArrowDownRight,
  ChevronLeft, ChevronRight, ChevronDown, ChevronUp,
} from 'lucide-react'
import { usd, pctSigned, colorClass } from '../../utils/format'
import { fmtConvertedRaw } from '../../contexts/CurrencyContext'
import EmptyState from '../EmptyState'
import InlineAIButton from '../ai/InlineAIButton'
import Panel from '../Panel'
import { prettyOpType, movPnl } from './shared'

export const PAGE_SIZE = 50

export default function TradesTable({
  ops, filteredOps, pagedOps, groups, grouped, groupBy,
  histMoney, expandedGroups, onToggleGroup,
  onEdit, onDelete, onDeleteGroup, busyDel,
  onAdd, page, totalPages, onPage,
}) {
  return (
    <Panel padding="none">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-line text-[12.5px] text-ink-2 font-medium">
              <th className="text-left px-4 py-2.5 font-medium">Fecha</th>
              <th className="text-left px-3 py-2.5 font-medium">Broker</th>
              <th className="text-left px-3 py-2.5 font-medium">Activo</th>
              <th className="text-left px-3 py-2.5 font-medium">Tipo</th>
              <th className="text-right px-3 py-2.5 font-medium">P. Entrada</th>
              <th className="text-right px-3 py-2.5 font-medium">P. Salida</th>
              <th className="text-right px-3 py-2.5 font-medium">Cant.</th>
              <th className="text-right px-3 py-2.5 font-medium">P&L USD</th>
              <th className="text-right px-3 py-2.5 font-medium">P&L %</th>
              <th className="px-3 py-2.5 w-[60px]"></th>
              <th className="px-3 py-2.5 w-[28px] text-center font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {ops.length === 0 && (
              <tr><td colSpan={11}>
                <EmptyState
                  icon={<ArrowUpRight size={20} />}
                  title="Aún no hay operaciones registradas"
                  description="Las ventas realizadas desde Posiciones quedan registradas automáticamente con su P&L realizado. También podés agregar operaciones manualmente."
                  action={
                    <button onClick={onAdd} className="inline-flex items-center gap-1.5 text-xs bg-data-violet/10 text-data-violet hover:bg-data-violet/15 border border-data-violet/30 px-3 py-1.5 rounded-sm transition-colors font-medium">
                      <Plus size={12} strokeWidth={2} /> Agregar manualmente
                    </button>
                  }
                />
              </td></tr>
            )}
            {ops.length > 0 && filteredOps.length === 0 && (
              <tr><td colSpan={11}>
                <EmptyState title="Sin resultados para los filtros aplicados" description="Ajustá los filtros para ampliar la búsqueda." dense />
              </td></tr>
            )}
            {/* Modo lista plana ('none') — la tabla de siempre, paginada. */}
            {!grouped && pagedOps.map(op => (
              <TradeRow key={op.id} op={op} histMoney={histMoney} onEdit={onEdit} onDelete={onDelete} deleting={!!busyDel[`op-${op.id}`]} />
            ))}
            {/* Modo agrupado (por activo / mes) — fila-resumen expandible. */}
            {grouped && groups.map(g => {
              const isOpen = expandedGroups.has(g.key)
              return (
                <Fragment key={g.key}>
                  <TradeGroupRow
                    group={g}
                    groupBy={groupBy}
                    isOpen={isOpen}
                    onToggle={() => onToggleGroup(g.key)}
                    histMoney={histMoney}
                    onDeleteGroup={groupBy === 'asset' ? onDeleteGroup : null}
                    deleting={!!busyDel[`grp-${g.key}`]}
                  />
                  {isOpen && g.rows.map(op => (
                    <TradeRow key={op.id} op={op} histMoney={histMoney} onEdit={onEdit} onDelete={onDelete} indent deleting={!!busyDel[`op-${op.id}`]} />
                  ))}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Paginación — oculta en modo agrupado (mismo criterio que MovementsTable). */}
      {!grouped && filteredOps.length > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-3 px-4 py-2.5 border-t border-line text-[12.5px] text-ink-3 font-medium">
          <span className="tabular">
            {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filteredOps.length)} de {filteredOps.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => onPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-sm border border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              aria-label="Página anterior"
            >
              <ChevronLeft size={11} strokeWidth={2} aria-hidden="true" /> Anterior
            </button>
            <span className="px-3 tabular text-ink-2">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => onPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-sm border border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              aria-label="Página siguiente"
            >
              Siguiente <ChevronRight size={11} strokeWidth={2} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}
    </Panel>
  )
}

// Fila de un trade cerrado. Se usa tanto en la lista plana (modo 'none') como en
// el detalle de un grupo (modo agrupado), donde va atenuada/indentada con "└" —
// mismo recurso visual que MovementRow. Mantiene las acciones por-trade
// (analizar/editar/eliminar) en todos los modos.
function TradeRow({ op, histMoney, onEdit, onDelete, indent = false, deleting = false }) {
  const isWin = op.pnl_usd != null && op.pnl_usd > 0
  const isLoss = op.pnl_usd != null && op.pnl_usd < 0
  const ArrowIcon = isWin ? ArrowUpRight : isLoss ? ArrowDownRight : null
  const arrowColor = isWin ? 'text-rendi-pos' : isLoss ? 'text-rendi-neg' : 'text-ink-3'
  return (
    <tr className={`border-b border-line/30 hover:bg-bg-2/40 transition-colors ${indent ? 'bg-bg-2/15' : ''}`}>
      <td className={`px-4 py-2 text-xs font-mono tabular text-ink-2 ${indent ? 'pl-6 opacity-75' : ''}`}>
        {indent && <span className="text-ink-3 font-mono select-none mr-1" title="Detalle">└</span>}
        {op.date}
      </td>
      <td className={`px-3 py-2 text-xs text-ink-2 ${indent ? 'opacity-75' : ''}`}>{op.broker}</td>
      <td className={`px-3 py-2 text-sm font-medium text-ink-0 ${indent ? 'opacity-75' : ''}`}>{op.asset}</td>
      <td className={`px-3 py-2 text-[12.5px] text-ink-3 ${indent ? 'opacity-75' : ''} font-medium`}>{prettyOpType(op.op_type)}</td>
      <td className={`px-3 py-2 text-xs font-mono tabular text-right text-ink-2 ${indent ? 'opacity-75' : ''}`}>{op.entry_price != null ? usd(op.entry_price) : '—'}</td>
      <td className={`px-3 py-2 text-xs font-mono tabular text-right text-ink-2 ${indent ? 'opacity-75' : ''}`}>{op.exit_price != null ? usd(op.exit_price) : '—'}</td>
      <td className={`px-3 py-2 text-xs font-mono tabular text-right text-ink-2 ${indent ? 'opacity-75' : ''}`}>{op.quantity ?? '—'}</td>
      <td className={`px-3 py-2 text-sm font-mono tabular text-right font-medium ${colorClass(op.pnl_usd)} ${indent ? 'opacity-75' : ''}`}>
        {op.pnl_usd == null
          ? '—'
          : histMoney.fmtMoneyAt(op.pnl_usd, {
              stampedFx: op.fx_to_usd,
              rowCurrency: op.currency,
              dateIso: op.date,
              signed: true,
              decimals: 2,
            })}
      </td>
      <td className={`px-3 py-2 text-xs font-mono tabular text-right ${colorClass(op.pnl_pct)} ${indent ? 'opacity-75' : ''}`}>
        {op.pnl_pct != null ? pctSigned(op.pnl_pct / 100) : '—'}
      </td>
      <td className="px-3 py-2">
        <div className="flex gap-1 justify-end items-center">
          {op.pnl_usd != null && (
            <InlineAIButton
              topic="operations.trade"
              params={{ operation_id: op.id }}
              subtitle={`${op.asset} · ${op.date}`}
              ariaLabel={`Analizar trade de ${op.asset}`}
            />
          )}
          <button onClick={() => onEdit(op)} className="text-ink-3 hover:text-ink-0 transition-colors p-1" title="Editar" aria-label={`Editar operación ${op.asset}`}>
            <Pencil size={13} strokeWidth={1.75} aria-hidden="true" />
          </button>
          {/* onDelete(op) con el OBJETO — antes acá era onDelete(op.id) y en el
              feed onDelete(op). Firma única desde la Fase 3. */}
          <button onClick={() => onDelete(op)} disabled={deleting} className="text-ink-3 hover:text-rendi-neg transition-colors p-1 disabled:opacity-40 disabled:pointer-events-none" title="Eliminar" aria-label={`Eliminar operación ${op.asset}`}>
            <Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>
      </td>
      <td className="pr-4 pl-1 py-2 align-middle text-right">
        {ArrowIcon
          ? <ArrowIcon size={16} strokeWidth={2.25} className={`inline-block ${arrowColor}`} aria-label={isWin ? 'Ganancia' : 'Pérdida'} />
          : <span className="text-ink-3 text-xs">—</span>}
      </td>
    </tr>
  )
}

// Fila-resumen de un grupo de trades (modo agrupado por activo o por mes).
// Click → toggle del detalle. Muestra: etiqueta (ticker o mes) · broker(s) ·
// # de trades · P&L total con flecha ↗/↘.
//
// ⚠️ CONVERT-THEN-SUM (money-critical): el total se arma convirtiendo CADA fila
// con SU FX histórico y sumando eso — NO sumando los USD y convirtiendo al FX de
// hoy. Antes usaba `fmtPnl` (= tcValuacion actual, que además es el MEP), mientras las
// filas usan el FX de su fecha: un grupo de UN trade mostraba dos números
// distintos (reporte real: header +$147.007 vs su única fila +$135.444, mismo
// pnl_usd × dos dólares). El invariante que garantiza esto es `total === Σ filas`.
function TradeGroupRow({ group, groupBy, isOpen, onToggle, histMoney, onDeleteGroup, deleting }) {
  const { label, count, brokers } = group
  // Signo, color y flecha salen del MISMO número que se imprime. Derivarlos del
  // USD crudo podía contradecir lo mostrado: un grupo con +100 USD de 2021 (fx 190)
  // y −90 USD de 2026 (fx 1500) suma +10 USD (flecha verde) pero −$116.000 en
  // pesos. En modo USD `pnlDisp === pnl`, así que no cambia nada.
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
      className="border-b border-line/40 bg-bg-2/40 hover:bg-bg-2/60 cursor-pointer transition-colors"
      onClick={onToggle}
    >
      {/* Etiqueta del grupo + chevron — ocupa Fecha */}
      <td className="px-4 py-2.5">
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
      {/* Broker(s) — solo tiene sentido en agrupado por activo */}
      <td className="px-3 py-2.5 text-ink-3 text-xs">
        {groupBy === 'asset' ? brokersLabel : '—'}
      </td>
      {/* # trades — ocupa Activo … Cant. */}
      <td className="px-3 py-2.5 text-ink-2" colSpan={5}>
        <span className="text-[12.5px] font-medium">
          {count} {count === 1 ? 'trade' : 'trades'}
        </span>
      </td>
      {/* P&L total con flecha — bajo "P&L USD" */}
      <td className={`px-3 py-2.5 text-right font-mono font-semibold tabular ${colorClass(hasPnl ? pnl : null)}`}>
        <span className="inline-flex items-center gap-1 justify-end">
          {Arrow && <Arrow size={13} strokeWidth={2.25} aria-hidden="true" />}
          {hasPnl ? fmtConvertedRaw(pnlDisp, histMoney.currency, { signed: true, decimals: 2 }) : '—'}
        </span>
      </td>
      {/* Resto (P&L % · acciones) — hint del P&L + tacho para borrar el activo entero */}
      <td className="px-3 py-2.5 text-right" colSpan={3}>
        <div className="inline-flex items-center gap-2 justify-end">
          {hasPnl && <span className="text-ink-3 text-[12px] font-medium">P&L total</span>}
          {onDeleteGroup && (
            <button
              type="button"
              disabled={deleting}
              onClick={(e) => { e.stopPropagation(); onDeleteGroup(group) }}
              aria-label={`Borrar todo el historial de ${label}`}
              title={`Borrar todo el historial de ${label}`}
              className="p-1 text-ink-3 hover:text-rendi-neg transition-colors disabled:opacity-40 disabled:pointer-events-none"
            >
              <Trash2 size={14} strokeWidth={1.75} />
            </button>
          )}
        </div>
      </td>
    </tr>
  )
}
