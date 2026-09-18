// CashMenuModal — el paso previo al depósito/retiro: ¿en qué broker y qué
// movimiento?
// ═══════════════════════════════════════════════════════════════════════════
// En escritorio este paso existió siempre (botón "Cash" del header). En el
// celular NO: el ítem "Cash · depósito / retiro" del sheet de acciones saltaba
// derecho a `brokers[0]` con `direction: 'deposit'` clavado. El usuario que
// tenía tres brokers y quería registrar un retiro en el tercero no tenía cómo
// llegar — el modal se abría ya decidido por él, y decidido mal.
//
// Igual que CashFlowModal: una sola definición, `Modal` resuelve la anchura.

import Modal from '../Modal'
import { ArrowDownCircle, ArrowUpCircle } from 'lucide-react'
import { brokerCurrencyLabel } from '../../utils/valuation'

const inputClass = 'w-full bg-bg-2 border border-line-2 rounded px-3 py-2 text-sm text-ink-0 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60 transition'

export default function CashMenuModal({ form, setForm, brokers, onClose, onContinue }) {
  return (
    <Modal title="Movimiento de cash" onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-ink-2 leading-relaxed">
          Registrá un depósito (plata que entra al broker) o un retiro (plata que sale).
        </p>

        {/* Selector broker */}
        <div>
          <label className="block text-xs text-ink-3 mb-1.5">Broker</label>
          <select
            value={form.broker}
            onChange={e => setForm(f => ({ ...f, broker: e.target.value }))}
            className={inputClass}
          >
            {brokers.map(b => (
              <option key={b.id} value={b.name}>{b.name} ({brokerCurrencyLabel(b, brokers)})</option>
            ))}
          </select>
        </div>

        {/* Selector dirección */}
        <div>
          <label className="block text-xs text-ink-3 mb-1.5">¿Qué movimiento?</label>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setForm(f => ({ ...f, direction: 'deposit' }))}
              aria-pressed={form.direction === 'deposit'}
              className={`p-3 border rounded text-left transition-all ${
                form.direction === 'deposit'
                  ? 'border-rendi-pos/50 bg-rendi-pos/10'
                  : 'border-line hover:border-line-3'
              }`}
            >
              <div className="flex items-center gap-2 mb-0.5">
                <ArrowDownCircle size={14} strokeWidth={2} className="text-rendi-pos" />
                <span className="text-sm font-medium text-ink-0">Depósito</span>
              </div>
              <div className="text-[11px] text-ink-3 leading-relaxed">
                Metés plata al broker
              </div>
            </button>
            <button
              type="button"
              onClick={() => setForm(f => ({ ...f, direction: 'withdraw' }))}
              aria-pressed={form.direction === 'withdraw'}
              className={`p-3 border rounded text-left transition-all ${
                form.direction === 'withdraw'
                  ? 'border-data-amber/50 bg-data-amber/10'
                  : 'border-line hover:border-line-3'
              }`}
            >
              <div className="flex items-center gap-2 mb-0.5">
                <ArrowUpCircle size={14} strokeWidth={2} className="text-data-amber" />
                <span className="text-sm font-medium text-ink-0">Retiro</span>
              </div>
              <div className="text-[11px] text-ink-3 leading-relaxed">
                Sacás plata del broker
              </div>
            </button>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-line/40">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onContinue}
            disabled={!form.broker}
            className="inline-flex items-center gap-1.5 text-xs bg-data-violet hover:bg-data-violet/90 disabled:bg-data-violet/40 disabled:cursor-not-allowed text-white px-4 py-2 rounded-sm transition-colors"
          >
            Continuar →
          </button>
        </div>
      </div>
    </Modal>
  )
}
