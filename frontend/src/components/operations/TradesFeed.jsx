// TradesFeed — el feed cronológico de trades (rama angosta de /operaciones).
// ═══════════════════════════════════════════════════════════════════════════
// Salió tal cual de pages/OperationsMobile.jsx cuando se mató el fork por
// viewport. Feed apilado con la fecha como header de grupo, una fila por trade
// con badge de tipo y P&L a la derecha.
//
// Dos cosas cambiaron respecto del original, y las dos son el punto del refactor:
//   · Los grupos ya no se arman acá: llegan de `buildGroups(…, 'day')`, que es
//     el mismo motor que agrupa la tabla. Eso es lo que manda el grupo "Sin
//     fecha" al FINAL en vez de arriba de todo.
//   · `histMoney` llega por PROP. Antes DayGroup y OperationRow llamaban
//     `useHistoricalMoney()` cada uno: con 400 trades eso construía el índice FX
//     ~800 veces en un solo render.
//
// El `sticky top-[88px]` del header NO vive acá: está calibrado a la altura del
// MobileTopBar y se queda en la página.

import { TrendingUp, TrendingDown, Calendar, Trash2 } from 'lucide-react'
import AssetLogo from '../AssetLogo'
import { pctSigned, colorClass } from '../../utils/format'
import { fmtConvertedCompactRaw } from '../../contexts/CurrencyContext'
import { formatQty } from './shared'

export default function TradesFeed({ groups, histMoney, onDelete }) {
  return (
    <ul>
      {groups.map(g => (
        <DayGroup key={g.key} group={g} histMoney={histMoney} onDelete={onDelete} />
      ))}
    </ul>
  )
}

function DayGroup({ group, histMoney, onDelete }) {
  // El subtotal del DÍA se arma convirtiendo CADA op con SU FX y sumando eso
  // (convert-then-sum) — así coincide con las filas que despliega.
  // Antes tomaba el `fx_to_usd` de la PRIMERA op con fx>0 y lo aplicaba a todo
  // el subtotal: si el día mezclaba una op USD (fx=1) con una ARS, el subtotal
  // quedaba mal. Mismo criterio que los headers de grupo de la tabla.
  const ops = group.rows
  const subtotalDisp = histMoney.sumConvertedAt(ops, o => (o.pnl_usd || 0))
  return (
    <li className="border-t border-line/30">
      <div className="flex items-baseline justify-between px-4 py-2 bg-bg-1/50">
        <div className="flex items-center gap-1.5">
          <Calendar size={11} strokeWidth={1.75} className="text-ink-3" />
          <span className="text-[12.5px] text-ink-2 font-medium">
            {group.label}
          </span>
          <span className="text-[10px] tabular text-ink-3">
            · {ops.length} {ops.length === 1 ? 'op' : 'ops'}
          </span>
        </div>
        <span className={`text-[11px] tabular ${colorClass(subtotalDisp)}`}>
          {fmtConvertedCompactRaw(subtotalDisp, histMoney.currency, { signed: true })}
        </span>
      </div>
      <ul>
        {ops.map(op => (
          <OperationRow key={op.id} op={op} histMoney={histMoney} onDelete={onDelete} />
        ))}
      </ul>
    </li>
  )
}

function OperationRow({ op, histMoney, onDelete }) {
  const isWin = op.pnl_usd != null && op.pnl_usd > 0
  const isLoss = op.pnl_usd != null && op.pnl_usd < 0
  const type = (op.op_type || '').toLowerCase()
  const isBuy = type.includes('compra') || type === 'buy'

  return (
    <li className="flex items-center gap-3 px-4 py-2.5 border-t border-line/20 first:border-t-0">
      <AssetLogo asset={op.asset} size={28} />

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-sm font-semibold text-ink-0 leading-none truncate">
            {op.asset}
          </span>
          <span className="text-[12.5px] text-ink-2 leading-none font-medium">
            {op.broker}
          </span>
        </div>
        <div className="flex items-center gap-2 mt-1.5">
          <span className={`inline-flex items-center text-[9px] px-1 py-0.5 rounded-sm ${
            isBuy
              ? 'bg-data-blue/10 text-data-blue border border-data-blue/30'
              : 'bg-data-violet/10 text-data-violet border border-data-violet/30'
          }`}>
            {isBuy ? 'Compra' : (op.op_type || 'Venta')}
          </span>
          {op.quantity != null && (
            <span className="text-[10px] tabular text-ink-3 truncate">
              {formatQty(op.quantity)} u.
            </span>
          )}
        </div>
      </div>

      <div className="flex-shrink-0 text-right">
        {op.pnl_usd != null && (
          <div className={`text-sm font-medium tabular leading-none flex items-center justify-end gap-1 ${colorClass(op.pnl_usd)}`}>
            {isWin ? <TrendingUp size={11} strokeWidth={1.75} /> : isLoss ? <TrendingDown size={11} strokeWidth={1.75} /> : null}
            {histMoney.fmtMoneyCompactAt(op.pnl_usd, {
              stampedFx: op.fx_to_usd,
              rowCurrency: op.currency,
              dateIso: op.date,
              signed: true,
            })}
          </div>
        )}
        {op.pnl_pct != null && (
          <div className={`text-[10px] tabular leading-none mt-1.5 ${colorClass(op.pnl_pct)}`}>
            {pctSigned(op.pnl_pct / 100)}
          </div>
        )}
      </div>

      {onDelete && (
        <button
          type="button"
          onClick={() => onDelete(op)}
          aria-label="Eliminar operación"
          className="flex-shrink-0 -mr-1 p-1.5 text-ink-3 hover:text-rendi-neg transition-colors"
        >
          <Trash2 size={15} strokeWidth={1.75} />
        </button>
      )}
    </li>
  )
}
