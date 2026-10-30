// ResumenMervalle — «✦ Analizar con Mervall-E» en la ficha del activo: el
// resumen a pedido y compartido, y las preguntas para seguir en el chat.
// ════════════════════════════════════════════════════════════════════════════
// Mockup aprobado por Nico (30/10): UN solo botón de Mervall-E en la ficha, en
// la tarjeta «La lectura de hoy» (LecturaDeHoy.jsx). Al tocarlo se abre ahí
// mismo, abajo de los casilleros, el párrafo que cuenta cómo viene el precio y
// debajo tres preguntas para seguir en el chat con ese activo ya cargado.
//
// El párrafo lo escribe la IA UNA vez por activo y por día de velas, y lo ven
// todos (backend/ai/resumen_tecnico.py); no descuenta cupo:
//   · si ya existe, viene con GET /api/tecnico (`resumen.estado = 'listo'`) y el
//     panel se muestra abierto, sin pedir nada;
//   · si no ('no_hay' o 'generando'), el botón hace POST
//     /api/tecnico/{activo}/resumen: el primero lo genera, el que toca mientras
//     tanto espera al primero;
//   · null: no se ofrece (sin IA, precios viejos, sin datos): no hay botón.
//
// Las preguntas para seguir son análisis del botón ✦ (`useVoz().analizar`, como
// el ✦ de cualquier tarjeta): la pregunta la escribe el SERVIDOR
// (ai/preguntas.py, `tecnico.*`) y la respuesta llega en el chat con la lectura
// técnica de este activo (ai/lectura_tecnica_chat.py). Cada una descuenta una
// del cupo de análisis del plan, como cualquier ✦.
//
// Tres piezas que comparten el estado: `useResumenMervalle` (en LecturaTecnica,
// antes de sus `return` tempranos), `BotonMervalle` (en la cabecera de la
// tarjeta) y `PanelMervalle` (abajo). Las cuentas y los datos los arma el
// servidor: de acá no viaja nada tuyo.

import { useEffect, useState } from 'react'
import { MessageCircle, Sparkles } from 'lucide-react'
import { api } from '../../utils/api'
import { useVoz } from '../../contexts/VozContext'

const AVISOS = {
  tope: 'Por hoy Mervall-E ya escribió todos los análisis que tenía previstos. Mañana vuelve a estar.',
  tope_persona: 'Hoy ya pediste varios análisis. Mañana podés pedir más.',
  generando: 'Otra persona lo pidió recién y se está terminando de escribir. Probá de nuevo en unos segundos.',
  no_disponible: 'Para este activo no hay análisis por ahora.',
  error: 'Esta vez no se pudo escribir el análisis.',
}

function fechaCorta(iso) {
  if (!iso) return ''
  const [, m, d] = iso.split('-')
  return `${d}/${m}`
}

/** El estado del botón y del panel. `resumen` = el de GET /api/tecnico. */
export function useResumenMervalle({ asset, moneda, local = false, resumen, alTenerlo }) {
  // Lo pidió (o lo abrió) y lo cerró, por separado: si ya está escrito, el panel
  // arranca abierto (no cuesta nada y es de todos) hasta que la persona lo cierra.
  const [abierto, setAbierto] = useState(false)
  const [cerrado, setCerrado] = useState(false)
  const [escribiendo, setEscribiendo] = useState(false)
  const [aviso, setAviso] = useState(null)
  // Otra moneda (otra serie, otro resumen) u otro activo: de cero.
  useEffect(() => { setAbierto(false); setCerrado(false); setEscribiendo(false); setAviso(null) }, [asset, moneda])

  const listo = resumen?.estado === 'listo'
  const visible = !!resumen && !cerrado && (listo || abierto)
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
  const tocar = () => {
    if (visible) { setCerrado(true); setAbierto(false); return }
    setCerrado(false)
    setAbierto(true)
    if (!listo && !escribiendo) pedir()
  }
  return { ofrecido: !!resumen, listo, escribiendo, aviso, resumen, asset, moneda, local, visible, tocar, reintentar: pedir }
}

/** El botón de la cabecera de «La lectura de hoy». */
export function BotonMervalle({ r, ancho = false }) {
  if (!r?.ofrecido) return null
  return (
    <button type="button" onClick={r.tocar} aria-expanded={r.visible} aria-busy={r.escribiendo || undefined}
      className={`inline-flex items-center justify-center gap-1.5 min-h-10 sm:min-h-8 px-3 rounded-lg text-xs font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 transition-colors press ${ancho ? 'w-full sm:w-auto' : ''}`}>
      <Sparkles size={13} strokeWidth={1.75} aria-hidden="true" className={r.escribiendo ? 'animate-pulse' : ''} />
      {r.escribiendo ? 'Mervall-E está escribiendo…' : 'Analizar con Mervall-E'}
    </button>
  )
}

// Las preguntas para seguir: el `screen` de cada una vive en el servidor
// (ai/registry.py + ai/preguntas.py); acá sólo el rótulo del botoncito.
function preguntas(direccion) {
  const mov = direccion === 'suba' ? 'esta suba' : direccion === 'bajada' ? 'esta bajada' : 'este movimiento'
  return [
    { screen: 'tecnico.tendencia', rotulo: '¿Está en tendencia?' },
    { screen: 'tecnico.fuerza', rotulo: `¿Tiene fuerza ${mov}?` },
    { screen: 'tecnico.que_se_mira', rotulo: '¿Qué se mira de acá en adelante?' },
  ]
}

/** Lo que se abre abajo de los casilleros: el párrafo y las preguntas para seguir.
 *  `direccion`: 'suba' | 'bajada' del movimiento de ahora (el Fibonacci en curso). */
export function PanelMervalle({ r, direccion = null }) {
  const { analizar, setOpen } = useVoz()
  if (!r?.visible) return null
  const { resumen, aviso } = r
  const reintento = aviso === 'error' || aviso === 'generando'
  const params = { asset: r.asset, moneda: r.moneda, local: r.local ? '1' : '' }
  return (
    <div className="border-t border-line/60 bg-data-violet/5 px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 mb-1.5">
        <div className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-data-violet">
          <Sparkles size={13} strokeWidth={1.75} aria-hidden="true" />
          Mervall-E
        </div>
        {resumen?.fecha && <div className="text-[11.5px] text-ink-2 tabular">Con los precios al cierre del {fechaCorta(resumen.fecha)}</div>}
      </div>
      {r.listo ? (
        <p className="text-[13.5px] text-ink-0 leading-relaxed">{resumen.texto}</p>
      ) : (
        <p role="status" className="text-[13px] text-ink-1">
          {r.escribiendo ? 'Mervall-E está escribiendo cómo viene el precio…' : aviso ? AVISOS[aviso] : ''}
          {reintento && !r.escribiendo && (
            <button type="button" onClick={r.reintentar}
              className="ml-2 min-h-10 sm:min-h-0 font-medium text-data-violet hover:underline">Probar de nuevo</button>
          )}
        </p>
      )}
      {r.listo && (
        <>
          <p className="text-[12px] text-ink-2 mt-3 mb-1.5">Seguir con Mervall-E:</p>
          <div className="flex flex-wrap gap-1.5">
            {preguntas(direccion).map(p => (
              <button key={p.screen} type="button" onClick={() => analizar({ screen: p.screen, params })}
                className="inline-flex items-center min-h-10 sm:min-h-8 px-3 rounded-full text-[12px] text-data-violet bg-data-violet/10 hover:bg-data-violet/15 border border-data-violet/30 transition-colors press">
                {p.rotulo}
              </button>
            ))}
            <button type="button" onClick={() => setOpen(true)}
              className="inline-flex items-center gap-1 min-h-10 sm:min-h-8 px-3 rounded-full text-[12px] text-data-violet border border-dashed border-data-violet/40 hover:bg-data-violet/10 transition-colors press">
              <MessageCircle size={12} strokeWidth={1.75} aria-hidden="true" />
              Preguntar otra cosa
            </button>
          </div>
        </>
      )}
      <p className="text-[11.5px] text-ink-2 mt-2.5">
        Lo escribió la IA con los datos del gráfico; puede equivocarse. No es una recomendación para comprar ni vender.
      </p>
    </div>
  )
}
