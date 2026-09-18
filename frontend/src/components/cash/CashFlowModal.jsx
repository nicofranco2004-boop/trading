// CashFlowModal — depósito / retiro de efectivo en un broker.
// ═══════════════════════════════════════════════════════════════════════════
// UNA sola definición para las dos anchuras. Antes vivía escrita dos veces —
// inline en Positions.jsx (escritorio) y otra vez inline en PositionsMobile.jsx
// (celular)— y las dos copias se separaron: la del celular NUNCA tuvo el campo
// de FECHA.
//
// Eso no era un detalle de layout. Sin fecha, `POST /cash/flow` sale sin `date`
// y el backend bookea el movimiento en el MES DE HOY (main.py: `if data.date:`
// … si no, `datetime.utcnow()`). O sea: un depósito de marzo cargado desde el
// teléfono entraba como aporte de hoy, y el capital aportado —que es el
// DENOMINADOR del rendimiento— quedaba corrido de mes. La pantalla no decía
// nada; simplemente el número salía distinto según el aparato desde el que se
// cargó. Misma familia que el `tc_blue` que el celular tampoco mandaba.
//
// Al unificar, el celular gana además la línea que dice a qué dólar se va a
// dolarizar un aporte en pesos (el de la FECHA elegida, no el de hoy).
//
// El wrapper `Modal` ya resuelve la anchura: en escritorio dibuja el modal
// centrado y en celular delega en BottomSheet. Por eso este componente no
// mira `useIsMobile()` — no tiene por qué.

import Modal from '../Modal'
import DateInput from '../DateInput'
import { usd, ars, parseNum } from '../../utils/format'
import { hoyISO } from '../../utils/fecha'

const inputClass = 'w-full bg-bg-2 border border-line-2 rounded px-3 py-2 text-sm text-ink-0 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60 transition'

export default function CashFlowModal({ form, setForm, tcValuacion, fxHist, onClose, onConfirm, saving = false }) {
  const esDeposito = form.direction === 'deposit'
  const monto = parseNum(form.amount) || 0

  return (
    <Modal
      title={`${esDeposito ? 'Depositar en' : 'Retirar de'} ${form.broker}`}
      onClose={onClose}
    >
      <div className="space-y-4">
        <p className="text-sm text-ink-2 leading-snug">
          {esDeposito
            ? 'Ingresá el monto a depositar. Se acreditará al cash del broker y se registrará como aporte del mes de la fecha que elijas.'
            : 'Ingresá el monto a retirar. Se debitará del cash del broker y se registrará como retiro del mes de la fecha que elijas.'}
        </p>

        {!esDeposito && (
          <p className="text-xs text-ink-3">
            Disponible: <span className="font-medium text-ink-2">
              {form.currency === 'ARS' ? ars(form.available) : `$${usd(form.available)}`} {form.currency}
            </span>
          </p>
        )}

        <div>
          <label className="block text-xs text-ink-3 mb-1">Fecha</label>
          <DateInput
            value={form.date || ''}
            max={hoyISO()}
            onChange={v => setForm(f => ({ ...f, date: v || f.date }))}
          />
        </div>

        <div>
          <label className="block text-xs text-ink-3 mb-1">
            Monto ({form.currency})
          </label>
          <input
            type="text"
            inputMode="decimal"
            value={form.amount}
            onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
            className={inputClass}
            placeholder="0"
          />
        </div>

        {form.currency === 'ARS' && (() => {
          // El dólar que se va a aplicar es el de la FECHA elegida, no el de hoy.
          // Mostrarlo evita la caja negra: si el aporte se dolariza a un TC que no
          // es el de ese día, el capital aportado (denominador del rendimiento)
          // queda mal y no hay nada en pantalla que lo delate.
          const hoy = hoyISO()
          const fecha = form.date || hoy
          const esHoy = fecha >= hoy
          const tc = esHoy ? tcValuacion : (fxHist?.getMepOrFallback?.(fecha) || tcValuacion)
          return (
            <p className="text-xs text-ink-3 leading-relaxed">
              Equivalente en USD al dólar {esHoy ? 'de hoy' : `del ${fecha.split('-').reverse().join('/')}`} ({Math.round(tc)}):
              <span className="font-medium text-ink-2 ml-1">${usd(monto / (tc || 1))}</span>
              {' '}· es el valor que va a contar como {esDeposito ? 'capital aportado' : 'retiro'}.
            </p>
          )
        })()}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-ink-3 hover:text-ink-0"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={saving || !(monto > 0)}
            className={`px-4 py-2 text-sm rounded font-medium text-white disabled:opacity-40 disabled:cursor-not-allowed transition ${
              esDeposito
                ? 'bg-rendi-pos hover:bg-rendi-pos/90'
                : 'bg-data-amber hover:bg-data-amber/90'
            }`}
          >
            {saving ? 'Guardando…' : `Confirmar ${esDeposito ? 'depósito' : 'retiro'}`}
          </button>
        </div>
      </div>
    </Modal>
  )
}
