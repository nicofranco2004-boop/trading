import { useCurrency } from '../contexts/CurrencyContext'

/**
 * CurrencyToggle — USD | ARS. Control del MISMO estado global que ya vive en
 * CurrencyContext (persistido en localStorage), así que da igual desde qué
 * pantalla lo toques: la preferencia es una sola y viaja con el usuario.
 *
 * Existía sólo como JSX inline en Cartera. Al querer el toggle también en el
 * Dashboard, se extrae acá para que no haya dos copias que se desincronicen
 * (mismos estilos, mismo aria, mismo comportamiento).
 *
 * ⚠️ Ponerlo SOLO en pantallas que respeten `currency` de punta a punta. Si una
 * pantalla ignora la preferencia, el toggle miente: cambia unos números y otros
 * no. Hoy lo respetan Cartera, Dashboard y el Diagnóstico de Métricas;
 * Comportamiento y Reportes todavía no.
 */
export default function CurrencyToggle({ className = '' }) {
  const { currency, setCurrency } = useCurrency()
  const isArs = currency === 'ARS'

  return (
    <div
      className={`inline-flex items-center rounded-full border border-line-2 bg-bg-2 p-0.5 ${className}`}
      role="group"
      aria-label="Moneda de visualización"
    >
      <button
        type="button"
        onClick={() => setCurrency('USD')}
        aria-pressed={!isArs}
        className={`px-3 py-1 rounded-full text-xs font-medium transition ${!isArs ? 'bg-data-violet/15 text-data-violet' : 'text-ink-2 hover:text-ink-0'}`}
        title="Mostrar los importes en dólares"
      >
        USD
      </button>
      <button
        type="button"
        onClick={() => setCurrency('ARS')}
        aria-pressed={isArs}
        className={`px-3 py-1 rounded-full text-xs font-medium transition ${isArs ? 'bg-data-violet/15 text-data-violet' : 'text-ink-2 hover:text-ink-0'}`}
        title="Mostrar los importes en pesos (al tipo de cambio activo)"
      >
        ARS
      </button>
    </div>
  )
}
