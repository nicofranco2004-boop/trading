import { useCurrency } from '../contexts/CurrencyContext'

// CurrencyRail — selector de moneda de valuación en formato "riel" segmentado
// (3 opciones a lo ancho): USD MEP · USD CCL · Pesos. Reemplaza al toggle
// USD/ARS + al toggle MEP/CCL, unificándolos en un solo control prominente.
//
// Cada opción muestra su cotización actual debajo del label (USD MEP → $1.424,
// USD CCL → $1.432; Pesos → "ARS"), tomada del /dolar que ya publica el
// CurrencyContext. Mapea los DOS ejes de preferencia a una sola selección:
//   - USD MEP → currency=USD, valuationDollar=mep   (dólar local, default)
//   - USD CCL → currency=USD, valuationDollar=ccl   (dólar implícito del CEDEAR)
//   - Pesos   → currency=ARS                          (todo en ARS)
//
// Al elegir "Pesos" NO se pisa valuationDollar: se conserva para que al volver
// a USD el user recupere su elección MEP/CCL (round-trip). State global
// (localStorage, per-device) → cambiarlo acá lo cambia en toda la app.

// Formatea una cotización ARS/USD para el subtítulo ("$1.424"). Devuelve null
// si todavía no llegó el /dolar (el caller deja el espacio con un &nbsp).
function fmtRate(v) {
  const n = Number(v)
  if (v == null || !Number.isFinite(n) || n <= 0) return null
  return '$' + n.toLocaleString('es-AR', { maximumFractionDigits: 0 })
}

const OPTS = [
  { key: 'mep', label: 'USD MEP' },
  { key: 'ccl', label: 'USD CCL' },
  { key: 'ars', label: 'Pesos' },
]

export default function CurrencyRail({ className = '' }) {
  const { currency, valuationDollar, setCurrency, setValuationDollar, dolar } = useCurrency()
  const active = currency === 'ARS' ? 'ars' : (valuationDollar === 'ccl' ? 'ccl' : 'mep')

  const subFor = {
    mep: fmtRate(dolar?.mep?.venta),
    ccl: fmtRate(dolar?.ccl?.venta),
    ars: 'ARS',
  }

  function pick(key) {
    if (key === 'ars') {
      setCurrency('ARS')
    } else {
      setCurrency('USD')
      setValuationDollar(key)
    }
  }

  return (
    <div
      role="group"
      aria-label="Moneda de valuación"
      className={`flex w-full items-stretch gap-1 rounded-full border border-line bg-bg-0 p-1.5 ${className}`}
    >
      {OPTS.map(o => {
        const on = active === o.key
        const sub = subFor[o.key]
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
              {sub || ' '}
            </span>
          </button>
        )
      })}
    </div>
  )
}
