// El micrófono — hablarle a Rendi en vez de escribirle.
// ═══════════════════════════════════════════════════════════════════════════
// UNO solo para las dos pantallas: el acompañante flotante y el chat grande de
// /ai. La conversación ya es una sola (ver VozContext); el micrófono también.
//
// 🔴 LO DICTADO NO SE MANDA SOLO. Esto termina llamando a `onTexto` y ahí se
// acaba su trabajo: quien lo usa pone el texto EN EL CUADRO, editable, y el
// usuario decide si lo manda. Un número mal escuchado en "compré a sesenta y
// cinco mil" se carga en la cartera y queda; un toque de más es barato al lado.
//
// POR QUÉ ES UN HOOK QUE DEVUELVE PEDAZOS Y NO UN COMPONENTE: las dos piezas
// van en lugares distintos del pie —el cartel de error ARRIBA, el botón
// ADENTRO, al lado del cuadro— pero comparten un solo estado. Un componente
// solo no puede dibujarse en dos lados, y partirlo en dos componentes obliga a
// cada pantalla a cablear el estado por su cuenta: dos cableados que después
// se desincronizan, que es exactamente lo que acabamos de arreglar en el chat.
//
// Tipografía y radios: contrato visual del frontend — sans, `tabular` en los
// números, `rounded-xl` de superficie.

import { Mic, Square, Loader2, RotateCcw } from 'lucide-react'
import { useDictado, MAX_SEGUNDOS, sePuedeGrabar } from '../../hooks/useDictado'

const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

/**
 * @param onTexto         (texto) => void — lo dictado, para PONER EN EL CUADRO.
 * @param onAntesDeGrabar () => void — callar a Rendi antes de abrir el micrófono.
 * @param deshabilitado   mientras hay una consulta en vuelo.
 * @param compacto        true en la isla (30px), false en el chat grande (34px).
 * @returns { boton, aviso, grabando } — `grabando` sirve para esconder el
 *          cuadro de escribir mientras el panel lo reemplaza.
 */
export function useMicrofono({ onTexto, onAntesDeGrabar, deshabilitado, compacto = true } = {}) {
  const d = useDictado({ onTexto, onAntesDeGrabar })
  // Sin soporte no se dibuja NADA: un botón que al tocarlo sólo sabe decir "tu
  // navegador no puede" es peor que no estar.
  const hay = sePuedeGrabar()
  const grabando = hay && (d.estado === 'escuchando' || d.estado === 'pidiendo')

  return {
    grabando,
    aviso: !hay ? null : (d.sugerida
      ? <Sugerida s={d.sugerida} onAceptar={d.aceptarSugerida} onDescartar={d.descartarSugerida} />
      : <Aviso error={d.error} onCerrar={d.limpiarError} />),
    boton: !hay ? null
      : grabando ? <PanelGrabando d={d} />
      : <Boton d={d} deshabilitado={deshabilitado} compacto={compacto} />,
  }
}


function Boton({ d, deshabilitado, compacto }) {
  const lado = compacto ? 'w-[30px] h-[30px]' : 'w-[34px] h-[34px]'
  const ocupado = d.estado === 'transcribiendo'
  return (
    <button
      type="button"
      onClick={d.grabar}
      disabled={deshabilitado || ocupado}
      aria-label={ocupado ? 'Pasando a texto…' : 'Hablarle a Rendi'}
      title={ocupado ? 'Pasando a texto…' : 'Hablarle a Rendi'}
      className={`${lado} rounded-full grid place-items-center flex-none border transition-colors
                  border-data-violet/40 bg-data-violet/[0.12] text-data-violet
                  hover:bg-data-violet/20 hover:border-data-violet/60
                  disabled:border-line-2 disabled:bg-transparent disabled:text-ink-3`}
    >
      {ocupado
        ? <Loader2 size={compacto ? 14 : 16} className="animate-spin" aria-hidden="true" />
        : <Mic size={compacto ? 14 : 16} strokeWidth={2} aria-hidden="true" />}
    </button>
  )
}


/** El pie mientras graba. REEMPLAZA al cuadro de escribir, no lo acompaña. */
function PanelGrabando({ d }) {
  const pidiendo = d.estado === 'pidiendo'
  return (
    <div className="flex-1 min-w-0 rounded-xl border border-data-violet/40 bg-data-violet/[0.08] px-3 py-2.5">
      <div className="flex items-center gap-2.5">
        <span className={`w-2 h-2 rounded-full flex-none ${pidiendo ? 'bg-ink-3' : 'bg-rendi-neg animate-pulse'}`}
              aria-hidden="true" />
        <span className="text-[12.5px] font-semibold text-ink-0">
          {pidiendo ? 'Dale permiso al micrófono…' : 'Te escucho…'}
        </span>
        {!pidiendo && (
          <span className="ml-auto flex items-baseline gap-1">
            <span className="tabular text-[12px] text-ink-1">{mmss(d.segundos)}</span>
            <span className="tabular text-[11px] text-ink-3">/ {mmss(MAX_SEGUNDOS)}</span>
          </span>
        )}
      </div>

      {/* EL MEDIDOR. Es lo único que prueba que el micrófono está tomando: el
          contador corre igual con el micrófono mudo, y sin esto el usuario se
          entera de que no lo escuchó recién cuando vuelve el texto vacío. */}
      {!pidiendo && (
        <>
          <div className="flex items-center gap-[2.5px] h-[22px] my-2" aria-hidden="true">
            {d.niveles.map((n, i) => (
              <i key={i}
                 className={`block w-[3px] rounded-full transition-[height] duration-75
                             ${n > 0.12 ? 'bg-data-violet' : 'bg-line-3'}`}
                 style={{ height: `${Math.max(3, Math.round(n * 22))}px` }} />
            ))}
          </div>
          <span className="block h-[3px] rounded-full bg-bg-3 overflow-hidden" aria-hidden="true">
            <i className="block h-full rounded-full bg-data-violet transition-[width] duration-1000 ease-linear"
               style={{ width: `${Math.min(100, (d.segundos / MAX_SEGUNDOS) * 100)}%` }} />
          </span>
        </>
      )}

      <div className="flex items-center gap-2 mt-2.5">
        <button
          type="button"
          onClick={d.terminar}
          disabled={pidiendo}
          className="flex-1 h-9 rounded-full inline-flex items-center justify-center gap-1.5
                     bg-data-violet text-bg-0 text-[12.5px] font-semibold
                     disabled:opacity-50 disabled:cursor-default transition-opacity"
        >
          <Square size={13} fill="currentColor" aria-hidden="true" /> Listo
        </button>
        <button
          type="button"
          onClick={d.cancelar}
          className="h-9 px-3.5 rounded-full border border-line-2 text-[12.5px] text-ink-2
                     hover:text-ink-0 hover:border-ink-3 transition-colors"
        >
          Cancelar
        </button>
      </div>
    </div>
  )
}


/**
 * Free y Plus: "entendí que preguntabas X".
 *
 * Esos planes sólo pueden mandar 12 preguntas EXACTAS, y lo dictado nunca
 * coincide letra por letra. MEDIDO: un Free dictó la pregunta exacta de un
 * chip, salió "porfolio" en vez de "portfolio" y el chat se lo rechazó con
 * "el chat libre es solo Pro". Le mostrábamos un micrófono, hablaba, y le
 * rebotaba.
 *
 * Acá elige entre opciones NUESTRAS: al confirmar viaja la pregunta de la
 * lista letra por letra, así que el candado sigue cerrado. Lo que dijo se
 * muestra arriba, chiquito, para que entienda por qué le ofrecemos ésa.
 */
function Sugerida({ s, onAceptar, onDescartar }) {
  return (
    <div className="rounded-xl border border-data-violet/35 bg-data-violet/[0.07] px-3 py-2.5">
      <p className="m-0 text-[11px] text-ink-3">Dijiste: «{s.dicho}»</p>
      <p className="m-0 mt-1.5 text-[11.5px] text-ink-2">Entendí que preguntabas:</p>
      <p className="m-0 mt-0.5 text-[13px] font-semibold leading-snug text-ink-0">{s.pregunta}</p>
      <div className="flex items-center gap-2 mt-2.5">
        <button
          type="button"
          onClick={onAceptar}
          className="rounded-full bg-data-violet text-bg-0 text-[12px] font-semibold px-3.5 py-1.5"
        >
          Sí, esa
        </button>
        <button
          type="button"
          onClick={onDescartar}
          className="rounded-full border border-line-2 text-[12px] text-ink-2 px-3.5 py-1.5
                     hover:text-ink-0 hover:border-ink-3 transition-colors"
        >
          No, otra cosa
        </button>
      </div>
    </div>
  )
}


/**
 * El aviso cuando algo sale mal. Dice QUÉ HACER AHORA y no sólo qué falló, y
 * no es un callejón: siempre queda escribir, que es a lo que el usuario vino.
 */
function Aviso({ error, onCerrar }) {
  if (!error) return null
  return (
    <div className="rounded-xl border border-rendi-warn/30 bg-rendi-warn/[0.07] px-3 py-2">
      <p className="m-0 text-[12.5px] font-semibold text-ink-0">{error.titulo}</p>
      <p className="m-0 mt-0.5 text-[12px] leading-snug text-ink-2">{error.texto}</p>
      <button
        type="button"
        onClick={onCerrar}
        className="mt-1.5 inline-flex items-center gap-1.5 text-[12px] font-semibold
                   text-data-violet hover:underline underline-offset-2"
      >
        <RotateCcw size={12} aria-hidden="true" /> Escribirla a mano
      </button>
    </div>
  )
}
