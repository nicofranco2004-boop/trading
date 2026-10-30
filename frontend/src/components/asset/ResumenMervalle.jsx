// ResumenMervalle — el resumen de Mervall-E en la ficha del activo, a pedido y
// compartido entre todos.
// ════════════════════════════════════════════════════════════════════════════
// Un párrafo que cuenta cómo viene el precio «como si te lo explicara un
// amigo». Lo escribe la IA UNA vez por activo y por día de velas, y lo ven
// todos (backend/ai/resumen_tecnico.py):
//   · si ya existe, viene con GET /api/tecnico (`resumen.estado = 'listo'`) y se
//     muestra solo;
//   · si no ('no_hay' o 'generando'), un botón. Tocarlo hace POST
//     /api/tecnico/{activo}/resumen: el primero lo genera, el que toca mientras
//     tanto espera al primero;
//   · null: no se ofrece (sin IA, precios viejos, sin datos).
// Mientras se escribe, el resto de la ficha se ve igual; si falla, se dice y se
// puede reintentar. Las cuentas y los datos los arma el servidor: de acá no
// viaja nada tuyo.

import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { api } from '../../utils/api'

const AVISOS = {
  tope: 'Por hoy Mervall-E ya escribió todos los resúmenes que tenía previstos. Mañana vuelve a estar.',
  tope_persona: 'Hoy ya pediste varios resúmenes. Mañana podés pedir más.',
  generando: 'Otra persona lo pidió recién y se está terminando de escribir. Probá de nuevo en unos segundos.',
  no_disponible: 'Para este activo no hay resumen por ahora.',
  error: 'Esta vez no se pudo escribir el resumen.',
}

function fechaCorta(iso) {
  if (!iso) return ''
  const [, m, d] = iso.split('-')
  return `${d}/${m}`
}

export default function ResumenMervalle({ asset, moneda, local = false, resumen, alTenerlo }) {
  const [escribiendo, setEscribiendo] = useState(false)
  const [aviso, setAviso] = useState(null)
  if (!resumen) return null

  const pedir = async () => {
    setEscribiendo(true)
    setAviso(null)
    try {
      const r = await api.post(
        `/tecnico/${encodeURIComponent(asset)}/resumen?moneda=${moneda}${local ? '&local=1' : ''}`)
      if (r?.estado === 'listo') alTenerlo?.(r)
      else setAviso(r?.estado in AVISOS ? r.estado : 'error')
    } catch {
      setAviso('error')
    } finally {
      setEscribiendo(false)
    }
  }

  if (resumen.estado === 'listo') {
    return (
      <div className="rounded-xl border border-data-violet/30 bg-data-violet/5 px-3.5 py-3 mt-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 mb-1.5">
          <div className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-data-violet">
            <Sparkles size={13} strokeWidth={1.75} aria-hidden="true" />
            Resumen de Mervall-E
          </div>
          <div className="text-[11.5px] text-ink-2 tabular">Con los precios al cierre del {fechaCorta(resumen.fecha)}</div>
        </div>
        <p className="text-[13.5px] text-ink-0 leading-relaxed">{resumen.texto}</p>
        <p className="text-[11.5px] text-ink-2 mt-2">
          Lo escribió la IA con los datos del gráfico; puede equivocarse. No es una recomendación para comprar ni vender.
        </p>
      </div>
    )
  }

  const reintento = aviso === 'error' || aviso === 'generando'
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {(!aviso || reintento) && (
        <button type="button" onClick={pedir} disabled={escribiendo} aria-busy={escribiendo || undefined}
          className="inline-flex items-center gap-1.5 min-h-10 sm:min-h-8 px-3 rounded-lg text-xs font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 transition-colors press disabled:opacity-60 disabled:cursor-wait">
          <Sparkles size={13} strokeWidth={1.75} aria-hidden="true" className={escribiendo ? 'animate-pulse' : ''} />
          {escribiendo ? 'Mervall-E está escribiendo…' : reintento ? 'Probar de nuevo' : 'Resumen de Mervall-E'}
        </button>
      )}
      <span role="status" className="text-[12px] text-ink-2">
        {aviso ? AVISOS[aviso] : !escribiendo && 'Te cuenta en palabras cómo viene el precio. No es una recomendación.'}
      </span>
    </div>
  )
}
