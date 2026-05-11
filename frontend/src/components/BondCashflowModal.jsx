// BondCashflowModal — registrar un cupón cobrado o amortización recibida.
// ════════════════════════════════════════════════════════════════════════════
// Flow:
//   1. Usuario hace click en "Registrar cupón" o "Registrar amortización"
//      desde el ActionMenu de una posición de bono.
//   2. Se abre este modal con el broker y asset pre-seleccionados.
//   3. Usuario ingresa fecha + monto + (opcional) comisiones + notas.
//   4. Submit → POST /api/bonds/cashflow → backend:
//      a. INSERT operation (op_type 'Cupón' o 'Amortización')
//      b. Acreditar cash del broker por monto neto (amount - commissions)
//      Todo atómico.
//   5. Recarga positions para reflejar el cash actualizado.
//
// El monto se carga en la moneda del broker (USDT/USD/ARS). Si el bono paga
// en USD pero el broker es ARS, el user carga el equivalente en pesos que
// efectivamente recibió.

import { useState } from 'react'
import { X, ArrowDownCircle, Layers as LayersIcon } from 'lucide-react'
import { api } from '../utils/api'
import { useToast } from './Toast'
import AssetLogo from './AssetLogo'
import { getBondMeta } from '../utils/bondMeta'

const today = () => new Date().toISOString().slice(0, 10)

export default function BondCashflowModal({
  flowType,     // 'coupon' | 'amortization'
  broker,       // string — nombre del broker
  brokerCurrency, // 'USDT' | 'USD' | 'ARS'
  asset,        // string — ticker del bono
  onClose,
  onSuccess,
}) {
  const [date, setDate] = useState(today())
  const [amount, setAmount] = useState('')
  const [commissions, setCommissions] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const toast = useToast()
  const bondMeta = getBondMeta(asset)

  const isCoupon = flowType === 'coupon'
  const title = isCoupon ? 'Registrar cupón cobrado' : 'Registrar amortización'
  const Icon = isCoupon ? ArrowDownCircle : LayersIcon
  const moneyLabel = brokerCurrency === 'ARS' ? 'ARS' : (brokerCurrency === 'USD' ? 'USD' : 'USDT')

  async function submit(e) {
    e.preventDefault()
    const amt = +amount
    if (!amt || amt <= 0) {
      toast.push('Ingresá un monto válido.', { type: 'warn' })
      return
    }
    setSaving(true)
    try {
      await api.post('/bonds/cashflow', {
        broker,
        asset: asset.toUpperCase(),
        flow_type: flowType,
        amount: amt,
        date,
        commissions: +commissions || 0,
        notes: notes.trim() || null,
      })
      toast.push(
        `${isCoupon ? 'Cupón' : 'Amortización'} de ${asset} registrado · ${moneyLabel} ${amt}`,
        { type: 'success' }
      )
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
        className="bg-white dark:bg-bg-1 border border-slate-200 dark:border-line rounded-t-2xl sm:rounded w-full max-w-md shadow-2xl flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-slate-200 dark:border-line">
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
        <div className="px-5 py-3 border-b border-slate-200 dark:border-line bg-slate-50/40 dark:bg-bg-2/30 flex items-center gap-3">
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

        {/* Form */}
        <form onSubmit={submit} className="p-5 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-ink-2 mb-1">Fecha</label>
              <input
                type="date"
                value={date}
                onChange={e => setDate(e.target.value)}
                className="w-full bg-slate-50 dark:bg-bg-2 border border-slate-300 dark:border-line rounded-md px-3 py-2 text-sm text-ink-0 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60"
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
                className="w-full bg-slate-50 dark:bg-bg-2 border border-slate-300 dark:border-line rounded-md px-3 py-2 text-sm text-ink-0 tabular focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60"
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
              className="w-full bg-slate-50 dark:bg-bg-2 border border-slate-300 dark:border-line rounded-md px-3 py-2 text-sm text-ink-0 tabular focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60"
            />
            <p className="text-[10px] text-ink-3 mt-1">
              Se descuentan del monto neto que se acredita al cash.
            </p>
          </div>

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
              className="w-full bg-slate-50 dark:bg-bg-2 border border-slate-300 dark:border-line rounded-md px-3 py-2 text-sm text-ink-0 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60"
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
