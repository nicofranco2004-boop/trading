// MovementsFeed — el feed de movimientos por día (rama angosta del tab "Todos").
// ═══════════════════════════════════════════════════════════════════════════
// Salió de pages/OperationsMobile.jsx. Como TradesFeed: los grupos llegan de
// `buildGroups(…, 'day')` (por eso "Sin fecha" cae al final, no arriba) y
// `histMoney` viene por prop.
//
// LO QUE GANÓ AL COMPARTIR EL VOCABULARIO CON LA TABLA:
//   · `transfer_out`. Estas filas son el cierre sintético que genera una foto de
//     tenencia; borrarlas REABRE la posición. Acá antes decía "Borrar
//     movimiento" — un texto que afirma lo contrario de lo que hace. Ahora usa
//     el mismo ícono RotateCcw y el mismo "Reabrir {asset}" que la tabla.
//   · El TYPE_META único: compra y venta pasan a los íconos de la tabla
//     (ArrowUpRight / ArrowDownRight en vez de TrendingUp / TrendingDown).

import { Trash2, RotateCcw, Repeat } from 'lucide-react'
import { TYPE_META, DELETABLE_MOVEMENT_TYPES, amountClassFor } from './shared'

export default function MovementsFeed({ groups, histMoney, onDelete, deletingId }) {
  return (
    <ul className="pt-1">
      {groups.map(g => (
        <li key={g.key}>
          <div className="px-4 py-1.5 text-[12px] text-ink-3 border-b border-line/30 bg-bg-1/50 font-medium">
            {g.label}
          </div>
          <ul>
            {g.rows.map(m => (
              <MovementRowMobile
                key={m.id}
                m={m}
                histMoney={histMoney}
                onDelete={onDelete}
                deleting={deletingId === m.id}
              />
            ))}
          </ul>
        </li>
      ))}
    </ul>
  )
}

function MovementRowMobile({ m, histMoney, onDelete, deleting }) {
  const meta = TYPE_META[m.type] || { label: m.type, Icon: Repeat, tone: null }
  const { Icon } = meta
  const canDelete = DELETABLE_MOVEMENT_TYPES.includes(m.type)
  const amountClass = TYPE_META[m.type] ? amountClassFor(m.type) : 'text-ink-1'
  return (
    <li className="flex items-center gap-3 px-4 py-2.5 border-t border-line/20 first:border-t-0">
      <span className={`flex-shrink-0 w-7 h-7 rounded-sm bg-bg-2 flex items-center justify-center ${amountClass}`}>
        <Icon size={14} strokeWidth={1.75} aria-hidden="true" />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-ink-0 leading-none">{meta.label}</div>
        <div className="text-[12.5px] text-ink-3 leading-none mt-1.5 truncate font-medium">
          {m.broker || '—'}{m.asset ? ` · ${m.asset}` : ''}
        </div>
      </div>
      <div className={`flex-shrink-0 text-right text-sm font-medium tabular ${amountClass}`}>
        {histMoney.fmtMoneyAt(m.amount_usd || 0, {
          stampedFx: m.fx_to_usd,
          rowCurrency: m.currency,
          dateIso: m.date,
          signed: false,
          decimals: 2,
        })}
      </div>
      {canDelete && (
        <button
          type="button"
          onClick={() => onDelete(m)}
          disabled={deleting}
          aria-label={m.transfer_out ? `Reabrir ${m.asset || 'la posición'}` : 'Borrar movimiento'}
          title={m.transfer_out ? `Reabrir ${m.asset || 'la posición'}` : 'Borrar movimiento'}
          className={`flex-shrink-0 p-1.5 -mr-1 rounded-sm text-ink-3 disabled:opacity-40 ${
            m.transfer_out ? 'active:text-rendi-pos active:bg-rendi-pos/10'
                           : 'active:text-rendi-neg active:bg-rendi-neg/10'}`}
        >
          {m.transfer_out
            ? <RotateCcw size={15} strokeWidth={1.75} aria-hidden="true" />
            : <Trash2 size={15} strokeWidth={1.75} aria-hidden="true" />}
        </button>
      )}
    </li>
  )
}
