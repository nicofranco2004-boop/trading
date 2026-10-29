// PreguntaMontos — "¿van los montos o sólo los porcentajes?"
// ═══════════════════════════════════════════════════════════════════════════
// La pregunta que se le hace al usuario antes de sacar sus números de la app:
// la imagen para compartir (ShareCardModal) y el reporte en PDF
// (BotonReporte). Una sola pregunta con un solo texto: cuánta plata tiene
// alguien no es algo que la app deba decidir por él, y la respuesta
// recomendada es la que no la muestra.

import { Eye, EyeOff } from 'lucide-react'

export default function PreguntaMontos({ onElegir, texto }) {
  return (
    <div className="space-y-3">
      <p className="text-[13px] text-ink-1 leading-relaxed">
        {texto || 'La imagen puede mostrar cuánta plata tenés en cada parte, o solo los porcentajes. Si la vas a subir a redes, te recomendamos ocultarlos.'}
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <button
          type="button"
          autoFocus
          onClick={() => onElegir(false)}
          className="inline-flex items-center justify-center gap-1.5 text-xs bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 px-3 py-2.5 rounded-sm transition-colors"
        >
          <EyeOff size={12} strokeWidth={1.75} />
          Solo porcentajes
        </button>
        <button
          type="button"
          onClick={() => onElegir(true)}
          className="inline-flex items-center justify-center gap-1.5 text-xs bg-bg-2 hover:bg-bg-3 text-ink-1 border border-line-2 px-3 py-2.5 rounded-sm transition-colors"
        >
          <Eye size={12} strokeWidth={1.75} />
          Mostrar montos
        </button>
      </div>
    </div>
  )
}
