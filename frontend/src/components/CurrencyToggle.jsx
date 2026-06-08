import { useCurrency } from '../contexts/CurrencyContext'

/**
 * CurrencyToggle — switch entre USD y ARS para todo el display de números.
 *
 * Variant 'pill' (default): chip horizontal con ambas opciones visibles
 * Variant 'compact': solo muestra la moneda actual con click para toggle
 *
 * Props:
 *   size  'sm' (default) | 'lg' — 'lg' es la versión prominente para las
 *          barras de tabs (Cartera/Análisis) y Config.
 *   label string opcional — se muestra a la izquierda del pill (ej. "Ver en")
 *          para que el control sea inconfundible.
 *
 * Persiste preferencia en localStorage. El toggle no afecta data backend
 * (la API sigue devolviendo USD); las pages convierten al renderizar. El
 * state es global (CurrencyContext): cambiarlo en una pantalla lo cambia en
 * todas.
 */
export default function CurrencyToggle({ variant = 'pill', size = 'sm', label, className = '' }) {
  const { currency, setCurrency } = useCurrency()

  if (variant === 'compact') {
    return (
      <button
        onClick={() => setCurrency(currency === 'USD' ? 'ARS' : 'USD')}
        className={`inline-flex items-center gap-1 px-2 py-1 rounded-sm text-[10px] font-mono uppercase tracking-caps border border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3 press ${className}`}
        title={`Cambiar a ${currency === 'USD' ? 'ARS' : 'USD'}`}
        aria-label={`Moneda actual ${currency}. Tocá para cambiar.`}
      >
        {currency}
      </button>
    )
  }

  // 'pill' default
  const lg = size === 'lg'
  const btn = lg ? 'px-3.5 py-1.5 text-xs' : 'px-2.5 py-1 text-[10px]'

  return (
    <div className={`inline-flex items-center gap-2 ${className}`}>
      {label && (
        <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3 select-none">
          {label}
        </span>
      )}
      <div
        className={`inline-flex items-center rounded-md border border-line bg-bg-2 ${lg ? 'p-1' : 'p-0.5'}`}
        role="group"
        aria-label="Moneda de visualización"
      >
        {['USD', 'ARS'].map(c => (
          <button
            key={c}
            onClick={() => setCurrency(c)}
            aria-pressed={currency === c}
            className={`${btn} font-mono uppercase tracking-caps rounded-sm press ${
              currency === c
                ? 'bg-data-violet/15 text-data-violet'
                : 'text-ink-3 hover:text-ink-1'
            }`}
          >
            {c}
          </button>
        ))}
      </div>
    </div>
  )
}
