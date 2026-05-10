// Skeleton — placeholder animado que mantiene el shape del contenido real
// mientras carga. Es la convención fintech moderna (Stripe, Linear, Robinhood)
// en lugar de mostrar 'Cargando…' que rompe la sensación de continuidad.
//
// Uso:
//   <Skeleton className="h-12 w-48" />            ← una línea
//   <Skeleton className="h-2 w-full rounded-full" /> ← progress bar
//
// Para layouts más complejos, componer múltiples Skeletons con la misma
// estructura que el componente final.

export default function Skeleton({ className = '', ...rest }) {
  return (
    <div
      className={`animate-pulse bg-slate-200 dark:bg-bg-2 rounded motion-reduce:animate-none ${className}`}
      aria-hidden="true"
      {...rest}
    />
  )
}

// Skeleton compuesto que imita el layout del Dashboard mientras carga.
// Mantiene exactamente el shape: hero + insight line + KPI strip + chart.
export function DashboardSkeleton() {
  return (
    <div className="page-shell" aria-busy="true" aria-live="polite">
      {/* PageHeader */}
      <div className="mb-8">
        <Skeleton className="h-3 w-24 mb-2" />
        <Skeleton className="h-7 w-40" />
      </div>
      {/* Hero */}
      <div className="mb-6">
        <Skeleton className="h-3 w-28 mb-3" />
        <Skeleton className="h-16 w-72 mb-4" />
        <Skeleton className="h-4 w-96" />
      </div>
      {/* Insight line */}
      <Skeleton className="h-10 w-full mb-8" />
      {/* KPI strip */}
      <div className="bg-bg-1 border border-line rounded mb-8 p-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          {[0, 1, 2, 3].map(i => (
            <div key={i} className="space-y-2">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="h-7 w-24" />
              <Skeleton className="h-3 w-32" />
            </div>
          ))}
        </div>
      </div>
      {/* Chart */}
      <div className="bg-bg-1 border border-line rounded p-5 mb-8">
        <Skeleton className="h-5 w-32 mb-2" />
        <Skeleton className="h-4 w-64 mb-6" />
        <Skeleton className="h-64 w-full" />
      </div>
    </div>
  )
}
