import { useCurrency } from '../contexts/CurrencyContext'

/**
 * CurrencyToggle — switch entre USD y ARS para todo el display de números.
 *
 * Variant 'pill' (default): chip horizontal con ambas opciones visibles
 * Variant 'compact': solo muestra la moneda actual con click para toggle
 *
 * Persiste preferencia en localStorage. El toggle no afecta data backend
 * (la API sigue devolviendo USD); las pages convierten al renderizar.
 */
export default function CurrencyToggle({ variant = 'pill', className = '' }) {
  const { currency, setCurrency } = useCurrency()

  if (variant === 'compact') {
    return (
      <button
        onClick={() => setCurrency(currency === 'USD' ? 'ARS' : 'USD')}
        className={`inline-flex items-center gap-1 px-2 py-1 rounded-sm text-[10px] font-mono uppercase tracking-caps border border-line bg-bg-2 text-ink-2 hover:text-ink-0 hover:bg-bg-3 transition-colors ${className}`}
        title={`Cambiar a ${currency === 'USD' ? 'ARS' : 'USD'}`}
      >
        {currency}
      </button>
    )
  }

  // 'pill' default
  return (
    <div className={`inline-flex items-center rounded-sm border border-line bg-bg-2 p-0.5 ${className}`}>
      {['USD', 'ARS'].map(c => (
        <button
          key={c}
          onClick={() => setCurrency(c)}
          className={`px-2.5 py-1 text-[10px] font-mono uppercase tracking-caps rounded-sm transition-colors ${
            currency === c
              ? 'bg-data-violet/15 text-data-violet'
              : 'text-ink-3 hover:text-ink-1'
          }`}
        >
          {c}
        </button>
      ))}
    </div>
  )
}
