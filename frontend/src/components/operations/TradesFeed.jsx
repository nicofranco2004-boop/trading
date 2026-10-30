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
// El `sticky` del header NO vive acá: se pega debajo de la barra de arriba
// (--alto-barra-celular, que anota MobileTopBar) y se queda en la página.

import { TrendingUp, TrendingDown, Calendar, Trash2 } from 'lucide-react'
import AssetLogo from '../AssetLogo'
import { pctSigned, colorClass } from '../../utils/format'
import { fmtConvertedCompactRaw } from '../../contexts/CurrencyContext'
import { formatQty, pctEnMoneda } from './shared'
import { esCobro } from '../../utils/tradeStats'

// `nuevas`: ids de las operaciones recién cargadas (Operations): esa tarjeta
// destella al aparecer. Acá los grupos son por día y están siempre abiertos,
// así que la nueva siempre queda a la vista.
// `borrando(clave)`: ¿ese borrado está viajando? Apaga el tacho (Operations).
export default function TradesFeed({ groups, histMoney, onDelete, borrando = () => false, nuevas = new Set() }) {
  return (
    <ul>
      {groups.map(g => (
        <DayGroup key={g.key} group={g} histMoney={histMoney} onDelete={onDelete} borrando={borrando} nuevas={nuevas} />
      ))}
    </ul>
  )
}

function DayGroup({ group, histMoney, onDelete, borrando, nuevas }) {
  // El subtotal del DÍA se arma convirtiendo CADA op con SU FX y sumando eso
  // (convert-then-sum) — así coincide con las filas que despliega.
  // Antes tomaba el `fx_to_usd` de la PRIMERA op con fx>0 y lo aplicaba a todo
  // el subtotal: si el día mezclaba una op USD (fx=1) con una ARS, el subtotal
  // quedaba mal. Mismo criterio que los headers de grupo de la tabla.
  const ops = group.rows
  const subtotalDisp = histMoney.sumPnlAt(ops)
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
          {histMoney.fmtMontoCorto(subtotalDisp, { signed: true })}
        </span>
      </div>
      <ul>
        {ops.map(op => (
          <OperationRow key={op.id} op={op} nueva={nuevas.has(op.id)} histMoney={histMoney} onDelete={onDelete} deleting={borrando(`op-${op.id}`)} />
        ))}
      </ul>
    </li>
  )
}

function OperationRow({ op, nueva = false, histMoney, onDelete, deleting = false }) {
  // Color, flecha y signo salen del MISMO número que se imprime (en Pesos puede tener
  // otro signo que el resultado en dólares: ganó en pesos y perdió en dólares).
  const pnlVisto = op.pnl_usd == null ? null : histMoney.pnlAt(op)
  const isWin = pnlVisto != null && pnlVisto > 0
  // El % en la moneda de la app (pesos o dólares), no en la de la venta.
  const { pct } = pctEnMoneda(op, histMoney.currency)
  const isLoss = pnlVisto != null && pnlVisto < 0
  const type = (op.op_type || '').toLowerCase()
  const isBuy = type.includes('compra') || type === 'buy'

  return (
    <li className={`flex items-center gap-3 px-4 py-2.5 border-t border-line/20 first:border-t-0 ${nueva ? 'destello-nueva' : ''}`}>
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
          {op.quantity != null && !esCobro(op.op_type) && (
            <span className="text-[10px] tabular text-ink-3 truncate">
              {formatQty(op.quantity)} u.
            </span>
          )}
        </div>
      </div>

      <div className="flex-shrink-0 text-right">
        {op.pnl_usd != null && (
          <div className={`text-sm font-medium tabular leading-none flex items-center justify-end gap-1 ${colorClass(pnlVisto)}`}>
            {isWin ? <TrendingUp size={11} strokeWidth={1.75} /> : isLoss ? <TrendingDown size={11} strokeWidth={1.75} /> : null}
            {histMoney.fmtPnlCompactAt(op, { signed: true })}
          </div>
        )}
        {pct != null && (
          <div className={`text-[10px] tabular leading-none mt-1.5 ${colorClass(pct)}`}>
            {pctSigned(pct / 100)}
          </div>
        )}
      </div>

      {onDelete && (
        <button
          type="button"
          onClick={() => onDelete(op)}
          disabled={deleting}
          aria-label="Eliminar operación"
          className="flex-shrink-0 -mr-1 p-1.5 text-ink-3 hover:text-rendi-neg transition-colors disabled:opacity-40 disabled:pointer-events-none"
        >
          <Trash2 size={15} strokeWidth={1.75} />
        </button>
      )}
    </li>
  )
}
