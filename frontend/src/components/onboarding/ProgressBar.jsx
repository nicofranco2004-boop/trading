// ProgressBar — el avance de la bienvenida (pages/Onboarding.jsx), discreto.
// ════════════════════════════════════════════════════════════════════════════
// Una fila: a la izquierda el tramo en que está («Configurá tu Rendi», «Últimos
// detalles») en sans violeta, a la derecha «2 de 3» con números tabulares, y
// abajo una pastilla fina por paso, llenas hasta el actual. Sin mayúsculas ni
// mono (frontend/CLAUDE.md, R1/R2). Cada pastilla dice su estado a un lector de
// pantalla; el conjunto lleva el nombre del tramo.

export default function ProgressBar({ steps, currentIndex, titulo }) {
  const total = steps.length
  return (
    <div className="w-full" role="group" aria-label={titulo || 'Avance'}>
      <div className="flex items-baseline justify-between gap-3 mb-1.5">
        <span className="text-[12.5px] font-medium text-data-violet truncate">{titulo || steps[currentIndex]}</span>
        <span className="text-[12px] text-ink-3 tabular flex-shrink-0">{currentIndex + 1} de {total}</span>
      </div>
      <div className="flex items-center gap-1.5 w-full">
        {steps.map((step, i) => {
          const hecho = i < currentIndex
          const actual = i === currentIndex
          return (
            <div
              key={step}
              className={`h-1 flex-1 rounded-full transition-colors duration-500 ${hecho || actual ? 'bg-data-violet' : 'bg-line-2'}`}
              aria-label={`${step} ${hecho ? '(listo)' : actual ? '(ahora)' : '(después)'}`}
            />
          )
        })}
      </div>
    </div>
  )
}
