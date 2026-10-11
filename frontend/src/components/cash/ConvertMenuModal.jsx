// ConvertMenuModal — el paso previo a la conversión: ¿de qué cuenta?
// ═══════════════════════════════════════════════════════════════════════════
// "Comprar USD" y "Vender USD a ARS" sólo se alcanzaban desde los tres puntitos
// de la fila de efectivo: había que saber que estaban ahí. La opción
// «Movimiento» del botón Registrar (utils/registrar.js) llega sin una fila
// elegida, así que primero pregunta cuál.
//
// `cajas` viene de `cajasParaConvertir` (la misma regla que el menú de la
// fila). Al elegir una se sigue por el ConvertModal de siempre.
//
// Igual que CashMenuModal: una sola definición, `Modal` resuelve la anchura.

import Modal from '../Modal'
import { brokerLegLabel } from '../../utils/brokerAccounts'
import { ars, usd } from '../../utils/format'

export default function ConvertMenuModal({ cajas, brokers, onPick, onClose }) {
  return (
    <Modal title="Movimiento entre pesos y dólares" onClose={onClose}>
      <div className="space-y-2">
        {cajas.length === 0 ? (
          <p className="text-sm text-ink-2 leading-relaxed">
            Este movimiento pasa pesos a dólares (o dólares a pesos) adentro de una
            cuenta argentina. Para usarlo necesitás efectivo cargado en una cuenta
            en pesos: si la plata ya está en tu broker, primero registrá el depósito.
          </p>
        ) : (
          <>
            <p className="text-xs text-ink-3 leading-relaxed mb-2">
              Elegí de qué efectivo sale. Rendi descuenta una moneda y acredita la
              otra en la misma cuenta, al tipo de cambio que le indiques.
            </p>
            <ul className="space-y-1.5">
              {cajas.map(({ p, direction }) => {
                const aDolares = direction === 'ars_to_usd'
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => onPick(p, direction)}
                      className="w-full p-3 border border-line hover:border-data-violet hover:bg-data-violet/[0.04] rounded text-left transition-all group flex items-center gap-3"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5">
                          <span className="text-sm font-semibold text-ink-0">{brokerLegLabel(p.broker, brokers)}</span>
                          <span className={`text-[12.5px] px-1.5 py-0.5 rounded border font-medium ${aDolares ? 'bg-rendi-warn/10 text-rendi-warn border-rendi-warn/30' : 'bg-data-cyan/10 text-data-cyan border-data-cyan/30'}`}>
                            {aDolares ? '$' : 'US$'}
                          </span>
                        </div>
                        <div className="text-xs text-ink-3 leading-relaxed">
                          {aDolares ? 'Comprar dólares con pesos' : 'Vender dólares a pesos'} · disponible{' '}
                          <span className="tabular">{aDolares ? `ARS ${ars(p.invested || 0)}` : `USD ${usd(p.invested || 0)}`}</span>
                        </div>
                      </div>
                      <span className="text-xs font-medium text-data-violet group-hover:translate-x-0.5 transition-transform">
                        Convertir →
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </>
        )}
        <div className="flex justify-end pt-3 mt-2 border-t border-line/40">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors"
          >
            {cajas.length === 0 ? 'Cerrar' : 'Cancelar'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
