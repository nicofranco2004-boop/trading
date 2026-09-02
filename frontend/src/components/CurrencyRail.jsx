import { useCurrencyChoice } from '../hooks/useCurrencyChoice'

// CurrencyRail — selector de moneda de valuación en formato "riel" segmentado
// (3 opciones a lo ancho): USD MEP · USD CCL · Pesos. Reemplaza al toggle
// USD/ARS + al toggle MEP/CCL, unificándolos en un solo control prominente.
//
// Cada opción muestra su cotización actual debajo del label (USD MEP → $1.424,
// USD CCL → $1.432; Pesos → "ARS"), tomada del /dolar que ya publica el
// CurrencyContext. El mapeo a los dos ejes del contexto (currency +
// valuationDollar) vive en `hooks/useCurrencyChoice` — compartido con el
// CurrencySwitcher global del shell, para que el mismo click haga lo mismo
// desde cualquiera de los dos controles.
//
// Esta es la versión ANCHA, para la página de Configuración (donde hay lugar
// para explicar y mostrar las tres cotizaciones a la vez). El control de todos
// los días es el CurrencySwitcher, fijo en la sidebar / barra superior.

export default function CurrencyRail({ className = '' }) {
  const { options, active, rates, pick } = useCurrencyChoice()

  return (
    <div
      role="group"
      aria-label="Moneda de valuación"
      className={`flex w-full items-stretch gap-1 rounded-full border border-line bg-bg-0 p-1.5 ${className}`}
    >
      {options.map(o => {
        const on = active === o.key
        const sub = rates[o.key]
        return (
          <button
            key={o.key}
            type="button"
            onClick={() => pick(o.key)}
            aria-pressed={on}
            className={`flex-1 rounded-full px-3 py-2.5 text-center transition-colors press ${
              on
                ? 'bg-data-violet/15 text-data-violet ring-1 ring-inset ring-data-violet/40'
                : 'text-ink-2 hover:text-ink-0'
            }`}
          >
            <span className="block text-[15px] font-medium leading-tight">{o.label}</span>
            <span className={`block mt-0.5 text-[11px] leading-tight tabular-nums ${on ? 'text-data-violet/70' : 'text-ink-3'}`}>
              {sub || ' '}
            </span>
          </button>
        )
      })}
    </div>
  )
}
