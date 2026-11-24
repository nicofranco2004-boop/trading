// VistaPreviaDelPase — lo que se DIBUJA de «Mover a otro broker». Sólo dibuja.
// ═══════════════════════════════════════════════════════════════════════════
// Sin estado, sin efectos y sin pedidos: recibe la vista previa que armó el
// servidor (POST /api/positions/traspaso/vista-previa) y la escribe. Así se puede
// probar entera con `renderToStaticMarkup`, que no corre efectos: el contenedor
// (MoverDeBrokerModal) maneja el formulario y los pedidos.
//
// Con el ojito («Ocultar saldos», `hidden`) se tapan los montos; las cantidades,
// las fechas y el precio unitario quedan a la vista, como en la Cartera.

import { taparMontos } from '../../utils/ocultarSaldos'
import { lineaDeLote, lineaDelValor, lineaDelPuente, lineaDelGasto, formateadorDeMontos } from '../../utils/moverDeBroker'

/** El valor del `<select>` que no es un broker: cierra el modal y abre el alta. */
export const CREAR_BROKER = '__crear_broker__'

export default function VistaPreviaDelPase({ plan = null, hidden = false, error = null, opcion = null }) {
  const fmt = formateadorDeMontos(hidden)
  const tapar = (t) => (hidden ? taparMontos(t) : t)
  const A = plan?.origen?.cuenta || opcion?.cuenta || ''
  const B = plan?.destino?.cuenta || ''
  const [costaron, queda, noEsVenta] = lineaDelPuente(plan, A, B, fmt)
  const gasto = lineaDelGasto(plan, A, fmt)
  return (
    <div className="space-y-3">
      {plan && (
        <div className="rounded-xl border border-line bg-bg-2/40 px-3 py-3 space-y-2.5 text-[13px] leading-relaxed text-ink-1">
          <div>
            <p className="font-medium text-ink-0">Se mueven estos lotes (primero los más viejos):</p>
            <ul className="mt-1 space-y-0.5">
              {(plan.lotes || []).map((l, i) => (
                <li key={l.lote_id ?? i} className="tabular text-ink-2">{lineaDeLote(l, plan.asset, fmt)}</li>
              ))}
            </ul>
          </div>
          <p className="tabular">{lineaDelValor(plan, fmt)}</p>
          <div className="space-y-1">
            <p className="tabular">{costaron}</p>
            <p className="tabular">{queda}</p>
            <p className="text-ink-3">{noEsVenta}</p>
          </div>
          {gasto && <p className="tabular">{gasto}</p>}
          {(plan.avisos || []).length > 0 && (
            <ul className="space-y-1">
              {plan.avisos.map((a, i) => (
                <li key={i} className="text-rendi-warn tabular">{tapar(a)}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {error && (
        <p role="alert" className="text-[13px] leading-relaxed text-rendi-neg whitespace-pre-line">{tapar(error)}</p>
      )}
    </div>
  )
}

/**
 * «¿A qué broker?»: las cuentas que ofrece `destinosPosibles` y, al final, crear
 * uno nuevo (el contenedor reconoce `CREAR_BROKER`).
 */
export function SelectorDeDestino({ destinos = [], valor = '', onCambio }) {
  return (
    <select
      value={valor}
      onChange={(e) => onCambio?.(e.target.value)}
      aria-label="¿A qué broker?"
      className="w-full bg-bg-2 border border-line rounded-lg px-3 py-2 text-base sm:text-sm text-ink-0 focus:outline-none focus:border-ink-2"
    >
      {!valor && <option value="" disabled>Elegí un broker</option>}
      {destinos.map((b) => (
        <option key={b.id ?? b.name} value={b.name}>{b.name}</option>
      ))}
      <option value={CREAR_BROKER}>+ Crear un broker nuevo</option>
    </select>
  )
}
