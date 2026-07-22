// PendingCashflowsBanner — inbox de cobros de bonos pendientes de confirmar.
// ════════════════════════════════════════════════════════════════════════════
// v2 (mockup bonos-v2): cards estilo Novedades con el monto grande y
// CONFIRMACIÓN DIRECTA en un click cuando es seguro:
//   • Confirmar (directo) → SOLO cupones en la MISMA moneda que el broker:
//     registra el monto teórico del cronograma sin abrir modal.
//   • Revisar → abre BondCashflowModal pre-llenado (amortizaciones — que
//     pueden decrementar VN —, pagos mixtos, cross-currency, o cuando el
//     monto real difiere).
//   • Saltar → POST /bonds/cashflow/skip → no aparece más.

import { useState } from 'react'
import { ChevronDown, ChevronUp, Check, X as XIcon, Loader2, CircleDollarSign } from 'lucide-react'
import AssetLogo from './AssetLogo'

const fmt = (n, dec = 2) => n.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })

// ¿El monto teórico (en moneda del BONO) se puede acreditar tal cual al broker?
function sameCurrency(brokerCcy, bondCcy) {
  if (bondCcy === 'ARS') return brokerCcy === 'ARS'
  return brokerCcy === 'USD' || brokerCcy === 'USDT'
}

export default function PendingCashflowsBanner({
  pending,           // resultado de detectPendingCashflows
  onConfirm,         // (item) => void — abre el modal pre-llenado ("Revisar")
  onConfirmDirect,   // (item) => void — registra directo el monto teórico
  confirmingKey,     // key del item que se está registrando (spinner)
  onSkip,            // (item) => void — POST /skip
  brokers,
}) {
  const [expanded, setExpanded] = useState(false)

  if (!pending || pending.length === 0) return null

  const n = pending.length
  const visible = expanded ? pending : pending.slice(0, 2)

  return (
    <div className="bg-bg-1 border border-line rounded-xl mb-6 overflow-hidden">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 hover:bg-bg-2/40 transition"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-data-cyan/10 text-data-cyan grid place-items-center flex-shrink-0">
            <CircleDollarSign size={16} strokeWidth={1.75} />
          </div>
          <div className="min-w-0 text-left">
            <p className="text-sm font-semibold text-ink-0">
              {n === 1 ? 'Tenés 1 cobro para confirmar' : `Tenés ${n} cobros para confirmar`}
            </p>
            <p className="text-[11.5px] text-ink-3 leading-snug">
              Fechas del cronograma que ya pasaron — confirmá y se acreditan al cash del broker
            </p>
          </div>
        </div>
        {n > 2 && (
          <div className="flex items-center gap-1 text-xs text-ink-2 flex-shrink-0">
            {expanded ? 'Ocultar' : 'Ver todos'}
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </div>
        )}
      </button>

      <div className="border-t border-line/60 divide-y divide-line/40">
        {visible.map(item => (
          <PendingItem
            key={item.key}
            item={item}
            broker={brokers?.find(b => b.name === item.broker)}
            confirming={confirmingKey === item.key}
            onConfirm={() => onConfirm(item)}
            onConfirmDirect={onConfirmDirect ? () => onConfirmDirect(item) : null}
            onSkip={() => onSkip(item)}
          />
        ))}
        {!expanded && n > 2 && (
          <button
            onClick={() => setExpanded(true)}
            className="w-full px-4 py-2 text-[11.5px] font-medium text-data-cyan hover:bg-data-cyan/[0.06] transition"
          >
            + Ver los otros {n - 2} {n - 2 === 1 ? 'cobro pendiente' : 'cobros pendientes'}
          </button>
        )}
      </div>
    </div>
  )
}

function PendingItem({ item, broker, confirming, onConfirm, onConfirmDirect, onSkip }) {
  const kindLabel = item.kind === 'amortizacion'
    ? 'Amortización'
    : item.kind === 'cupon' ? 'Cupón' : 'Cupón + amortización'

  // Directo solo para cupones same-currency: el teórico está en la moneda del
  // bono; si el broker acredita en otra (bono USD en Cocos ARS) o hay VN en
  // juego (amort), el flujo pasa por el modal para revisar montos.
  const directOk = !!onConfirmDirect && item.kind === 'cupon' && sameCurrency(broker?.currency, item.currency)

  return (
    <div className="px-4 py-3 flex items-center gap-3 flex-wrap">
      <AssetLogo asset={item.asset} size={30} />
      <div className="min-w-0 flex-1">
        <p className="text-[13.5px] font-semibold text-ink-0 flex items-center gap-2 flex-wrap">
          {item.asset} · {kindLabel}
          <span className="text-[10.5px] font-semibold text-rendi-warn bg-rendi-warn/10 rounded-full px-2 py-0.5">
            venció hace {item.daysAgo} {item.daysAgo === 1 ? 'día' : 'días'}
          </span>
        </p>
        <p className="text-[11px] text-ink-3">
          {item.broker} · fecha esperada {item.date}
          {item.kind === 'mixto' && (
            <span> · {item.currency} {fmt(item.coupon, 2)} cupón + {item.currency} {fmt(item.amort, 2)} amort</span>
          )}
        </p>
      </div>
      <div className="text-right mr-1">
        <div className="text-[15px] font-bold text-rendi-pos tabular">+{item.currency} {fmt(item.total)}</div>
        <div className="text-[10px] text-ink-3">estimado por tus {item.position?.quantity || '?'} nominales</div>
      </div>
      <div className="flex gap-1.5 flex-shrink-0">
        {directOk ? (
          <>
            <button
              onClick={onConfirmDirect}
              disabled={confirming}
              className="inline-flex items-center justify-center gap-1.5 text-xs font-semibold bg-rendi-pos text-[#04120a] hover:opacity-90 rounded-lg px-3 py-2 transition disabled:opacity-50"
              title="Registrar directo con el monto teórico del cronograma. Se acredita al cash del broker."
            >
              {confirming ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} strokeWidth={2.5} />} Confirmar
            </button>
            <button
              onClick={onConfirm}
              className="text-xs font-medium text-ink-1 border border-line hover:border-ink-3 rounded-lg px-3 py-2 transition"
              title="Abrir el modal para ajustar monto, fecha o comisiones antes de registrar."
            >
              Ajustar
            </button>
          </>
        ) : (
          <button
            onClick={onConfirm}
            className="inline-flex items-center justify-center gap-1.5 text-xs font-semibold bg-rendi-pos/15 hover:bg-rendi-pos/25 text-rendi-pos border border-rendi-pos/30 rounded-lg px-3 py-2 transition"
            title={item.kind === 'cupon'
              ? `El bono paga en ${item.currency} pero el broker acredita en ${broker?.currency || '?'} — revisá el monto convertido antes de registrar.`
              : 'Las amortizaciones pueden reducir tus nominales — revisá antes de registrar.'}
          >
            <Check size={12} strokeWidth={2} /> Revisar y confirmar
          </button>
        )}
        <button
          onClick={onSkip}
          className="text-xs text-ink-3 hover:text-ink-1 rounded-lg px-2.5 py-2 transition"
          title="No registrar este pago (default, bono vendido antes, etc.). No volverá a aparecer."
        >
          <XIcon size={13} strokeWidth={1.75} />
        </button>
      </div>
    </div>
  )
}
