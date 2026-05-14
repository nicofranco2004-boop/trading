// BondCashflowModal — registrar un cupón cobrado o amortización recibida.
// ════════════════════════════════════════════════════════════════════════════
// Flow:
//   1. Usuario hace click en "Registrar cupón" o "Registrar amortización"
//      desde el ActionMenu de una posición de bono.
//   2. El modal abre PRE-LLENADO con la estimación del próximo pago según
//      el cronograma del bono (Fase 3D / Nivel 1 de automatización):
//        - Fecha: la fecha del próximo pago del schedule.
//        - Monto: qty × payment_per_100 / 100 — el monto teórico.
//        - Notas: "Estimado por cronograma — ajustá comisiones/retenciones."
//   3. Usuario revisa, ajusta si difiere y guarda.
//   4. Submit → POST /api/bonds/cashflow → backend:
//      a. INSERT operation con currency + fx_to_usd stampados.
//      b. Acreditar cash del broker por monto neto (amount − commissions).
//      c. Si flow_type='amortization': reducir FIFO quantity + invested de
//         los lotes (cost basis amortizante, Phase 3D).
//      Todo atómico.
//   5. Recarga positions para reflejar el cash + qty actualizados.
//
// El monto se carga en la moneda del broker (USDT/USD/ARS). Si el bono paga
// en USD pero el broker es ARS, el user carga el equivalente en pesos que
// efectivamente recibió.

import { useState, useEffect, useMemo } from 'react'
import { X, ArrowDownCircle, Layers as LayersIcon } from 'lucide-react'
import { api } from '../utils/api'
import { useToast } from './Toast'
import AssetLogo from './AssetLogo'
import { getBondMeta, formatBondType } from '../utils/bondMeta'
import { nextPaymentForPosition } from '../utils/bondSchedule'

const today = () => new Date().toISOString().slice(0, 10)

export default function BondCashflowModal({
  flowType,     // 'coupon' | 'amortization'
  broker,       // string — nombre del broker
  brokerCurrency, // 'USDT' | 'USD' | 'ARS'
  asset,        // string — ticker del bono
  position,     // Optional: la posición completa (con quantity) para pre-fill
  onClose,
  onSuccess,
}) {
  const bondMeta = getBondMeta(asset)
  const isCoupon = flowType === 'coupon'

  // ── Phase 3D / Nivel 1 — Pre-fill desde el cronograma ────────────────────
  // Si tenemos position.quantity, calculamos el próximo pago teórico y
  // pre-llenamos fecha + monto. Para bonos USD en broker ARS, el monto teórico
  // está en USD (moneda del bono); el user igualmente puede sobrescribirlo
  // con el monto ARS que efectivamente recibió.
  const estimate = useMemo(() => {
    if (!position?.quantity) return null
    const next = nextPaymentForPosition(asset, position.quantity, today())
    if (!next) return null
    // Para amortization vs coupon: filtramos el monto al sub-flujo correspondiente.
    if (flowType === 'coupon' && next.coupon > 0) {
      return { date: next.date, amount: next.coupon, kind: 'coupon-only' }
    }
    if (flowType === 'amortization' && next.amort > 0) {
      return { date: next.date, amount: next.amort, kind: 'amort-only' }
    }
    // Caso edge: el próximo pago es del tipo opuesto (ej: user abrió "cupón"
    // pero el próximo flujo es sólo amort). Devolvemos null para no confundir.
    return null
  }, [asset, flowType, position?.quantity])

  const [date, setDate] = useState(estimate?.date || today())
  const [amount, setAmount] = useState(estimate?.amount?.toFixed(2) || '')
  const [commissions, setCommissions] = useState('')
  const [notes, setNotes] = useState(
    estimate ? 'Estimado por cronograma — ajustá monto si difiere por retenciones/comisiones' : ''
  )
  // Phase 3F (audit final / hallazgos N1, N4): el toggle decrement_quantity
  // sólo aplica si:
  //   • flow_type === 'amortization' (cupones no decrementan VN)
  //   • el bono ES amortizante (tiene amortSchedule o amortStart)
  //   • broker.currency === bond.currency (sin cross-currency)
  // En cualquier otro caso, el toggle está disabled + default OFF.
  const isAmortizingBond = !!(bondMeta?.amortSchedule || bondMeta?.amortStart)
  const decrementApplies = flowType === 'amortization' && isAmortizingBond
  const moneyLabel = brokerCurrency === 'ARS' ? 'ARS' : (brokerCurrency === 'USD' ? 'USD' : 'USDT')
  const crossCurrency = bondMeta && bondMeta.currency !== 'ARS' && brokerCurrency === 'ARS'
  const decrementSafeDefault = decrementApplies && !crossCurrency
  const [decrementQty, setDecrementQty] = useState(decrementSafeDefault)
  const [saving, setSaving] = useState(false)
  const toast = useToast()

  // Si cambia la estimación (caso re-render por props), re-aplicar valores.
  useEffect(() => {
    if (estimate && !amount) {
      setDate(estimate.date)
      setAmount(estimate.amount.toFixed(2))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estimate])

  const title = isCoupon ? 'Registrar cupón cobrado' : 'Registrar amortización'
  const Icon = isCoupon ? ArrowDownCircle : LayersIcon

  async function submit(e) {
    e.preventDefault()
    const amt = +amount
    if (!amt || amt <= 0) {
      toast.push('Ingresá un monto válido.', { type: 'warn' })
      return
    }
    setSaving(true)
    try {
      // Phase 3F: si el user marcó decrement_quantity Y tenemos estimate del
      // schedule, mandamos `face_amortized` explícito (en VN) además del
      // `amount` (en moneda del broker). Esto soluciona el bug N1: en
      // cross-currency, amount está en pesos pero la qty está en VN; sin
      // face_amortized, el backend trata pesos como face y borra la posición.
      const willDecrement = decrementApplies && decrementQty
      const faceAmortized = willDecrement && estimate?.amount && position?.quantity
        ? (estimate.amount * position.quantity / 100)  // pmt.amort (per 100) × qty / 100 = VN
        : undefined
      const payload = {
        broker,
        asset: asset.toUpperCase(),
        flow_type: flowType,
        amount: amt,
        date,
        commissions: +commissions || 0,
        notes: notes.trim() || null,
        decrement_quantity: willDecrement,
        ...(faceAmortized != null ? { face_amortized: faceAmortized } : {}),
      }
      const res = await api.post('/bonds/cashflow', payload)
      let msg = `${isCoupon ? 'Cupón' : 'Amortización'} de ${asset} registrado · ${moneyLabel} ${amt}`
      if (res.qty_decremented > 0) {
        msg += ` · ${res.qty_decremented.toFixed(2)} VN amortizados`
      } else if (res.cross_currency_skipped) {
        // El sanity check disparó — informar al user que su qty NO se tocó.
        msg += ' · qty intacta (cross-currency: pasá face_amortized para decrementar)'
        toast.push(msg, { type: 'warn' })
        onSuccess?.()
        onClose()
        setSaving(false)
        return
      }
      toast.push(msg, { type: 'success' })
      onSuccess?.()
      onClose()
    } catch (err) {
      toast.push(`Error: ${err.message || 'No se pudo registrar el cashflow'}`, { type: 'error' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white dark:bg-bg-1 border border-line rounded-t-2xl sm:rounded w-full max-w-md shadow-2xl flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-line">
          <div className="flex items-center gap-3 min-w-0">
            <div className={`w-9 h-9 rounded-sm flex items-center justify-center flex-shrink-0 ${
              isCoupon ? 'bg-rendi-pos/15 text-rendi-pos' : 'bg-rendi-accent/15 text-rendi-accent'
            }`}>
              <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
            </div>
            <div className="min-w-0">
              <p className="eyebrow mb-0.5">{broker}</p>
              <h2 className="text-base font-semibold text-ink-0 leading-tight">{title}</h2>
            </div>
          </div>
          <button
            onClick={onClose}
            className="flex-shrink-0 -mr-2 p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2 transition-colors"
            aria-label="Cerrar"
          >
            <X size={16} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>

        {/* Asset display */}
        <div className="px-5 py-3 border-b border-line bg-bg-2/40 dark:bg-bg-2/30 flex items-center gap-3">
          <AssetLogo asset={asset} size={32} />
          <div className="min-w-0">
            <p className="font-semibold text-ink-0 text-sm tabular">{asset}</p>
            {bondMeta && (
              <p className="text-[11px] text-ink-2 font-mono">
                {bondMeta.issuer} · {bondMeta.maturity ? `vence ${bondMeta.maturity}` : 'ETF'}
              </p>
            )}
          </div>
        </div>

        {/* Pre-fill banner (Phase 3D / Nivel 1) */}
        {estimate && (
          <div className="mx-5 mt-4 px-3 py-2 rounded-sm bg-rendi-accent/[0.08] border border-rendi-accent/30 text-[11px] text-ink-1 leading-snug">
            <p className="font-mono">
              💡 Pre-llenado según cronograma: <strong>{estimate.date}</strong> · estimado{' '}
              <strong>
                {bondMeta?.currency} {estimate.amount.toFixed(2)} por {position?.quantity || '?'} VN
              </strong>
              {crossCurrency && (
                <span className="block text-rendi-warn mt-0.5">
                  ⚠ Monto en {bondMeta.currency} — convertí al equivalente {moneyLabel} que recibiste de tu broker
                </span>
              )}
            </p>
          </div>
        )}

        {/* Form */}
        <form onSubmit={submit} className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-ink-2 mb-1">Fecha</label>
              <input
                type="date"
                value={date}
                onChange={e => setDate(e.target.value)}
                className="w-full bg-bg-2 dark:bg-bg-2 border border-line rounded-md px-3 py-2 text-sm text-ink-0 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60"
                required
              />
            </div>
            <div>
              <label className="block text-xs text-ink-2 mb-1">Monto bruto ({moneyLabel})</label>
              <input
                type="number"
                step="any"
                inputMode="decimal"
                value={amount}
                onChange={e => setAmount(e.target.value)}
                placeholder="0.00"
                className="w-full bg-bg-2 dark:bg-bg-2 border border-line rounded-md px-3 py-2 text-sm text-ink-0 tabular focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60"
                autoFocus
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-xs text-ink-2 mb-1">Comisiones / retenciones ({moneyLabel}) — opcional</label>
            <input
              type="number"
              step="any"
              inputMode="decimal"
              value={commissions}
              onChange={e => setCommissions(e.target.value)}
              placeholder="0.00"
              className="w-full bg-bg-2 dark:bg-bg-2 border border-line rounded-md px-3 py-2 text-sm text-ink-0 tabular focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60"
            />
            <p className="text-[10px] text-ink-3 mt-1">
              Se descuentan del monto neto que se acredita al cash.
            </p>
          </div>

          {/* Decrement quantity toggle — sólo para amortización en bonos
              amortizantes (no bullet). Phase 3F: disabled si el bono NO
              amortiza (N4) o si hay cross-currency mismatch (N1) — en
              ambos casos el decrement automático rompería los datos. */}
          {flowType === 'amortization' && (
            <div className={`px-3 py-2.5 rounded-sm border ${decrementApplies ? 'bg-bg-3 border-line' : 'bg-bg-2/30 border-line/40'}`}>
              <label className={`flex items-start gap-2 ${decrementApplies ? 'cursor-pointer' : 'cursor-not-allowed'}`}>
                <input
                  type="checkbox"
                  checked={decrementQty}
                  disabled={!decrementApplies}
                  onChange={e => setDecrementQty(e.target.checked)}
                  className="mt-0.5"
                />
                <div className="text-xs leading-snug flex-1">
                  <span className={`font-medium ${decrementApplies ? 'text-ink-0' : 'text-ink-3'}`}>
                    Reducir cantidad de la posición
                  </span>
                  {!isAmortizingBond && (
                    <p className="text-[10px] text-rendi-warn mt-0.5">
                      ⚠ {bondMeta?.issuer ? `${formatBondType(bondMeta.type)} ${bondMeta.issuer}` : 'Este bono'} es bullet
                      (no amortiza progresivamente — devuelve face al vencimiento). El decrement no aplica
                      antes del maturity.
                    </p>
                  )}
                  {isAmortizingBond && crossCurrency && (
                    <p className="text-[10px] text-rendi-warn mt-0.5">
                      ⚠ Cross-currency ({bondMeta.currency} bono en broker {brokerCurrency}): el sistema necesita
                      saber cuántos VN se amortizaron, no podemos inferirlo del monto en {brokerCurrency}.
                      Si confirmás con esto activo, la cobranza se registra pero la qty queda intacta
                      (backend abort el decrement por sanity check).
                    </p>
                  )}
                  {decrementApplies && (
                    <p className="text-[10px] text-ink-2 mt-0.5">
                      Una amortización devuelve capital → tu VN remanente decrece. Si está activo,
                      el sistema reduce automáticamente la quantity y el cost basis del lote (FIFO).
                      Desactivá si querés trackear sólo el cash sin tocar la posición.
                    </p>
                  )}
                </div>
              </label>
            </div>
          )}

          {/* Net amount preview */}
          {amount && (
            <div className="px-3 py-2 rounded-sm bg-bg-3 border border-line text-xs text-ink-1">
              <span className="font-mono">Neto al cash {broker}: </span>
              <span className="font-semibold text-rendi-pos tabular">
                +{moneyLabel} {(((+amount || 0) - (+commissions || 0))).toFixed(2)}
              </span>
            </div>
          )}

          <div>
            <label className="block text-xs text-ink-2 mb-1">Notas — opcional</label>
            <input
              type="text"
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="Ej.: Cupón nominal USD 28, recibí 27.500 después de retención"
              className="w-full bg-bg-2 dark:bg-bg-2 border border-line rounded-md px-3 py-2 text-sm text-ink-0 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60"
            />
          </div>

          {/* Footer buttons */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-ink-2 hover:text-ink-0"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={saving || !amount}
              className="px-4 py-2 text-sm bg-rendi-accent hover:bg-rendi-accent/90 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded-md font-semibold transition"
            >
              {saving ? 'Registrando…' : (isCoupon ? 'Registrar cupón' : 'Registrar amortización')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
