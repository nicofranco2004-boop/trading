// MisAlertas — la pestaña «Mis alertas» de /alertas.
// ═══════════════════════════════════════════════════════════════════════════
// Todo lo que ya armaste, una fila por cosa: el resumen del mercado (si está
// prendido) y cada aviso de precio. Cada fila dice UNA frase («GGAL sube a
// $ 8.000») y UNA línea de estado («Está en $ 7.350 · le falta 8,8 %»), con el
// interruptor para pausarla. Tocar la fila abre el formulario para cambiarla o
// borrarla. Las frases salen de alertasTexto.js, las mismas que la
// confirmación del formulario.
//
// Las pausadas y las cumplidas (una de «una sola vez» que ya avisó: el motor la
// apaga sola) van al final, más tenues, con el interruptor para reactivarlas.
//
// Sistema visual: generación nueva — filas sobre el fondo, rótulos sans
// sentence-case, números con `tabular`.
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Sunrise, Briefcase, Bell } from 'lucide-react'
import AssetLogo from '../AssetLogo'
import { frase, estado, fechaCorta, horaArgentina, diaArgentina } from './alertasTexto'

export default function MisAlertas({ items, events, precios, resumen, hoy, onEditar, onPausar, onIrACrear, cargando }) {
  const [verHistorial, setVerHistorial] = useState(false)
  // Activas primero, después pausadas y cumplidas; dentro, como vinieron (las
  // más nuevas arriba).
  const ordenadas = [...items].sort((a, b) => Number(b.active) - Number(a.active))
  const vacio = !cargando && ordenadas.length === 0 && !resumen.prendido

  if (cargando && ordenadas.length === 0) {
    return <p className="py-10 text-center text-sm text-ink-2">Cargando…</p>
  }

  if (vacio) {
    return (
      <div className="py-12 text-center space-y-3">
        <Bell size={24} strokeWidth={1.5} className="text-ink-2 mx-auto" aria-hidden="true" />
        <p className="text-sm text-ink-1">Todavía no armaste ninguna alerta.</p>
        <button type="button" onClick={onIrACrear} className="text-sm font-medium text-data-violet hover:underline">
          Crear la primera
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <ul className="divide-y divide-line">
        {resumen.prendido && (
          <Fila
            icono={<Circulo><Sunrise size={18} strokeWidth={1.75} className="text-rendi-warn" /></Circulo>}
            titulo={<span className="font-semibold">Resumen del mercado</span>}
            detalle={<>Cada día hábil a las 11:00 · <Link to="/resumen" className="text-data-violet hover:underline">leer el de hoy</Link></>}
            prendida
            etiquetaInterruptor="Apagar el resumen del mercado"
            onInterruptor={() => resumen.cambiar(false)}
          />
        )}
        {ordenadas.map(a => {
          const { quien, que } = frase(a)
          const est = estado(a, a.symbol ? precios[a.symbol.toUpperCase()] : null, events, hoy)
          const cartera = a.scope === 'holdings'
          return (
            <Fila key={a.id}
              icono={cartera
                ? <Circulo><Briefcase size={18} strokeWidth={1.75} className="text-ink-1" /></Circulo>
                : <AssetLogo asset={a.symbol} size={40} />}
              titulo={<><span className="font-semibold">{quien}</span>{cartera ? ': ' : ' '}{que}</>}
              detalle={est.tono === 'aviso'
                ? <span className="inline-flex items-center gap-1.5"><span className="w-1.5 h-1.5 rounded-full bg-rendi-warn" aria-hidden="true" />{est.texto}</span>
                : est.texto}
              prendida={a.active}
              tenue={!a.active}
              onAbrir={() => onEditar(a)}
              etiquetaInterruptor={`${a.active ? 'Pausar' : 'Reactivar'} el aviso de ${quien}`}
              onInterruptor={() => onPausar(a)}
            />
          )
        })}
      </ul>

      <div className="space-y-3">
        <p className="text-[13px] text-ink-2">
          {ordenadas.length > 0 && 'Tocá un aviso para cambiarlo o borrarlo. '}
          {events.length > 0 && (
            <button type="button" onClick={() => setVerHistorial(v => !v)} aria-expanded={verHistorial}
              className="text-data-violet hover:underline">
              {verHistorial ? 'Ocultar avisos anteriores' : 'Ver avisos anteriores'}
            </button>
          )}
        </p>
        {verHistorial && (
          <ul className="divide-y divide-line rounded-xl border border-line bg-bg-1">
            {events.map(ev => (
              <li key={ev.id} className="flex items-baseline gap-3 px-4 py-2.5">
                <span className="flex-1 min-w-0 text-sm text-ink-1 tabular">{ev.message}</span>
                <span className="flex-shrink-0 text-xs text-ink-2 tabular">
                  {diaArgentina(ev.fired_at) === hoy ? `Hoy ${horaArgentina(ev.fired_at)}` : fechaCorta(ev.fired_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function Circulo({ children }) {
  return (
    <span className="w-10 h-10 rounded-full bg-bg-2 flex items-center justify-center flex-shrink-0" aria-hidden="true">
      {children}
    </span>
  )
}

function Fila({ icono, titulo, detalle, prendida, tenue, onAbrir, etiquetaInterruptor, onInterruptor }) {
  const cuerpo = (
    <>
      {icono}
      <span className="flex-1 min-w-0">
        <span className="block text-[15px] text-ink-0 tabular">{titulo}</span>
        <span className="block text-[13px] text-ink-2 tabular">{detalle}</span>
      </span>
    </>
  )
  return (
    <li className={`flex items-center gap-3.5 py-3.5 ${tenue ? 'opacity-60' : ''}`}>
      {onAbrir ? (
        <button type="button" onClick={onAbrir} className="flex-1 min-w-0 flex items-center gap-3.5 text-left rounded-lg hover:bg-bg-2/60 -mx-2 px-2 py-1 transition-colors">
          {cuerpo}
        </button>
      ) : (
        <div className="flex-1 min-w-0 flex items-center gap-3.5">{cuerpo}</div>
      )}
      <button type="button" role="switch" aria-checked={!!prendida} aria-label={etiquetaInterruptor} onClick={onInterruptor}
        className="w-11 h-11 flex items-center justify-center flex-shrink-0">
        <span className={`relative block w-9 h-[22px] rounded-full transition-colors ${prendida ? 'bg-data-violet' : 'bg-bg-3'}`}>
          <span className={`absolute top-[3px] w-4 h-4 rounded-full bg-white transition-all ${prendida ? 'left-[17px]' : 'left-[3px]'}`} />
        </span>
      </button>
    </li>
  )
}
