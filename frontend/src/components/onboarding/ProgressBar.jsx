// ProgressBar — barra de progreso del wizard de onboarding.
// ════════════════════════════════════════════════════════════════════════════
// Muestra los N steps como pills horizontales, con el actual destacado.
// Coherente con la estética del producto: mono uppercase + accent violet.

import { Check } from 'lucide-react'

export default function ProgressBar({ steps, currentIndex }) {
  return (
    <div className="w-full">
      {/* Step indicator mono */}
      <div className="text-[10px] font-mono uppercase tracking-caps text-data-violet mb-3 text-center">
        Paso {currentIndex + 1} de {steps.length}
      </div>

      {/* Pills */}
      <div className="flex items-center gap-1.5 w-full max-w-md mx-auto">
        {steps.map((step, i) => {
          const isDone = i < currentIndex
          const isCurrent = i === currentIndex
          return (
            <div key={step} className="flex-1 flex items-center gap-1.5">
              <div
                className={`h-1 flex-1 rounded-full transition-colors ${
                  isDone || isCurrent ? 'bg-data-violet' : 'bg-bg-2'
                }`}
                aria-label={`${step} ${isDone ? '(completado)' : isCurrent ? '(actual)' : '(pendiente)'}`}
              />
              {/* Check al pasar */}
              {isDone && i < steps.length - 1 && (
                <Check
                  size={10}
                  strokeWidth={2.5}
                  className="text-data-violet -ml-1"
                  aria-hidden="true"
                />
              )}
            </div>
          )
        })}
      </div>

      {/* Label del step actual */}
      <div className="text-center mt-3">
        <span className="text-xs text-ink-3 font-medium">{steps[currentIndex]}</span>
      </div>
    </div>
  )
}
