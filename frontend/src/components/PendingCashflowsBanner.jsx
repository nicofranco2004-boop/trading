// PendingCashflowsBanner — inbox de cobranzas de bonos pendientes de confirmar.
// ════════════════════════════════════════════════════════════════════════════
// Phase 3E (Nivel 2 de automatización). Se renderea arriba de /posiciones
// cuando el detector encuentra fechas de pago del cronograma de algún bono
// que ya pasaron pero el user no registró ni saltó.
//
// Cada item tiene 2 acciones:
//   • Confirmar → abre BondCashflowModal pre-llenado con la fecha y monto
//     teórico. El user revisa, ajusta y registra. (Reusa BondCashflowModal
//     ya existente — no duplicamos UI.)
//   • Saltar → POST /api/bonds/cashflow/skip → el pago no aparece más.
//
// Diseño: colapsable. Por default muestra el primer pendiente + count;
// click expande la lista entera. Para que no inunde la pantalla si el user
// tiene 20 bonos.

import { useState } from 'react'
import { Bell, ChevronDown, ChevronUp, Check, X as XIcon, Coins, Layers as LayersIcon } from 'lucide-react'
import AssetLogo from './AssetLogo'

const fmt = (n, dec = 2) => n.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })

export default function PendingCashflowsBanner({
  pending,           // resultado de detectPendingCashflows
  onConfirm,         // (item) => void — abre el modal pre-llenado
  onSkip,            // (item, reason?) => void — POST /skip
  brokers,           // para mostrar la currency del broker en el subtítulo
}) {
  const [expanded, setExpanded] = useState(false)

  if (!pending || pending.length === 0) return null

  const n = pending.length
  const visible = expanded ? pending : pending.slice(0, 1)

  return (
    <div className="bg-rendi-accent/[0.08] border border-rendi-accent/40 rounded mb-6 overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 hover:bg-rendi-accent/[0.04] transition"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-sm bg-rendi-accent/20 text-rendi-accent flex items-center justify-center flex-shrink-0">
            <Bell size={15} strokeWidth={1.75} />
          </div>
          <div className="min-w-0 text-left">
            <p className="text-sm font-semibold text-ink-0">
              {n} {n === 1 ? 'cobranza pendiente' : 'cobranzas pendientes'} de confirmar
            </p>
            <p className="text-[11px] text-ink-2 font-mono leading-snug">
              Pagos del cronograma de tus bonos que ya pasaron sin registrar. Confirmá o saltá cada uno.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1 text-xs text-ink-2 flex-shrink-0">
          {expanded ? 'Ocultar' : 'Ver detalle'}
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </button>

      {/* Lista de pendientes */}
      <div className="border-t border-rendi-accent/30 divide-y divide-rendi-accent/15">
        {visible.map(item => (
          <PendingItem
            key={item.key}
            item={item}
            broker={brokers?.find(b => b.name === item.broker)}
            onConfirm={() => onConfirm(item)}
            onSkip={() => onSkip(item)}
          />
        ))}
        {!expanded && n > 1 && (
          <button
            onClick={() => setExpanded(true)}
            className="w-full px-4 py-2 text-[11px] text-rendi-accent font-mono hover:bg-rendi-accent/[0.08] transition"
          >
            + Ver los otros {n - 1} {n - 1 === 1 ? 'pago pendiente' : 'pagos pendientes'}
          </button>
        )}
      </div>
    </div>
  )
}

function PendingItem({ item, broker, onConfirm, onSkip }) {
  const KindIcon = item.kind === 'amortizacion'
    ? LayersIcon
    : item.kind === 'cupon'
      ? Coins
      : Coins
  const kindLabel = item.kind === 'amortizacion'
    ? 'Amortización'
    : item.kind === 'cupon'
      ? 'Cupón'
      : 'Cupón + amort'
  const kindColor = item.kind === 'amortizacion'
    ? 'text-rendi-accent'
    : 'text-rendi-pos'

  return (
    <div className="px-4 py-3 flex items-center gap-3">
      <AssetLogo asset={item.asset} size={28} />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-ink-0 flex items-center gap-2 flex-wrap">
          {item.asset}
          <span className="text-[10px] font-mono text-ink-2 normal-case">
            · {item.broker}
          </span>
          <span className={`text-[12.5px] tracking-[0.12em] px-1.5 py-0.5 rounded-sm bg-bg-3 border border-line ${kindColor} flex items-center gap-1 font-medium`}>
            <KindIcon size={9} strokeWidth={1.75} />
            {kindLabel}
          </span>
        </p>
        <p className="text-[11px] text-ink-2 font-mono">
          Fecha esperada {item.date} · hace {item.daysAgo} {item.daysAgo === 1 ? 'día' : 'días'}
        </p>
        <p className="text-xs text-ink-1 font-mono mt-0.5">
          Estimado: <span className="font-semibold text-rendi-pos tabular">{item.currency} {fmt(item.total)}</span>
          {item.kind === 'mixto' && (
            <span className="text-[10px] text-ink-3 ml-1">
              ({item.currency} {fmt(item.coupon, 3)} cupón + {item.currency} {fmt(item.amort, 2)} amort)
            </span>
          )}
        </p>
      </div>
      <div className="flex flex-col sm:flex-row gap-1.5 flex-shrink-0">
        <button
          onClick={onConfirm}
          className="inline-flex items-center justify-center gap-1 text-xs bg-rendi-pos/15 hover:bg-rendi-pos/25 text-rendi-pos border border-rendi-pos/30 rounded-sm px-2.5 py-1.5 transition"
          title="Abrir modal pre-llenado con esta fecha y monto. Podés ajustar antes de guardar."
        >
          <Check size={12} strokeWidth={1.75} /> Confirmar
        </button>
        <button
          onClick={onSkip}
          className="inline-flex items-center justify-center gap-1 text-xs bg-bg-2 hover:bg-bg-3 text-ink-2 border border-line rounded-sm px-2.5 py-1.5 transition"
          title="No registrar este pago (default, bono vendido antes, etc.). No volverá a aparecer."
        >
          <XIcon size={12} strokeWidth={1.75} /> Saltar
        </button>
      </div>
    </div>
  )
}
