// AvisameTecnico — el botón «Avisame» chico de una señal técnica.
// ═══════════════════════════════════════════════════════════════════════════
// Va en cada tarjeta de la ficha técnica (LecturaTecnica) y lo puede usar
// cualquier otra pantalla que muestre una señal (la Radiografía de la Cartera):
//
//   const avisos = useAvisosTecnicos()          // UNA vez por pantalla
//   <BotonAvisame asset="AAPL" accionLocal={false} moneda="usd"
//     senal="media200" direction="below" avisos={avisos} />
//
//   · asset: el activo como lo pide la ficha técnica ('AAPL', 'GGAL', 'BTC').
//   · accionLocal: la misma marca que se le pasa a GET /api/tecnico (acción
//     argentina → su precio de BYMA ÷ MEP, no el ADR).
//   · moneda: 'usd' | 'ars', la vista que se está mirando.
//   · senal: una de SENALES_TECNICAS (alertasTexto.js); direction: 'above' |
//     'below' | 'either' (sólo para los cruces de un promedio).
//   · avisos: lo que devuelve useAvisosTecnicos(); con eso el botón sabe si ya
//     hay una alerta igual y en vez de «Avisame» dice «Te avisamos».
//
// Tocarlo abre el formulario de siempre (AlertaForm) ya armado con esa señal:
// ahí se ve la confirmación en palabras, por dónde avisa y cuántas veces, y se
// pide el permiso de notificaciones en el mismo toque. La alerta la evalúa el
// servidor una vez por día con el cierre (alerts_engine.evaluar_tecnicas); la
// de tu línea o tu canal, también durante la rueda (_evaluar_en_la_rueda).
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, Check } from 'lucide-react'
import AlertaForm from './AlertaForm'
import { usePlanFeatures } from '../../hooks/usePlanFeatures'
import { useToast } from '../Toast'
import { api } from '../../utils/api'
import { track } from '../../utils/track'
import { conSentido, SENALES_TECNICAS, alertaDeLinea } from './alertasTexto'
import { tendenciaDe } from '../../utils/tecnico'

/** La alerta técnica que se arma desde una señal (lo que se manda al formulario). */
export function prefillTecnico({ asset, accionLocal = false, moneda = 'usd', senal, direction }) {
  return {
    kind: 'tecnica', fijo: true, symbol: String(asset || '').toUpperCase(), senal,
    direction: conSentido(senal) ? (direction || 'either') : 'either',
    currency: moneda === 'ars' ? 'ARS' : 'USD', accionLocal: !!accionLocal,
  }
}

/** ¿Ya hay una alerta técnica activa que avise esto? La misma señal, activo y
 *  moneda, y que cubra el lado: una de «los dos lados» cubre cualquiera; una de
 *  «para arriba» no avisa cuando queda abajo. */
export function alertaExistente(items = [], p) {
  return items.find(a => a.kind === 'tecnica' && a.active
    && String(a.symbol || '').toUpperCase() === p.symbol && a.senal === p.senal
    && String(a.currency || 'USD').toUpperCase() === p.currency
    && !!a.accion_local === p.accionLocal
    && (!conSentido(p.senal) || a.direction === 'either' || a.direction === p.direction)) || null
}

/** Las alertas de la cuenta, una sola vez por pantalla (no una por botón). */
export function useAvisosTecnicos() {
  const [items, setItems] = useState(null)
  const recargar = useCallback(() => {
    api.get('/alerts').then(r => setItems(r?.items || [])).catch(() => setItems([]))
  }, [])
  useEffect(() => { recargar() }, [recargar])
  return { items: items || [], cargado: items !== null, recargar }
}

/** `soloIcono`: la campanita sola, como botón redondo (los renglones de «Lo que
 *  cambió esta semana» del Panorama); el texto va en el globo y para el lector
 *  de pantalla. */
export function BotonAvisame({ avisos, className = '', soloIcono = false, ...datos }) {
  const plan = usePlanFeatures()
  const toast = useToast()
  const [abierto, setAbierto] = useState(false)
  const prefill = prefillTecnico(datos)
  const ya = alertaExistente(avisos?.items, prefill)

  const queAvisa = `Avisame cuando ${(SENALES_TECNICAS.find(x => x.id === prefill.senal)?.texto || '').replace(/^./, c => c.toLowerCase())}`
  const redondo = 'inline-flex items-center justify-center w-[34px] h-[34px] rounded-full border border-line bg-bg-2/60'

  if (ya) {
    if (soloIcono) {
      return (
        <Link to="/alertas?tab=mis" title="Ya te avisamos: ver tus alertas" aria-label="Ya te avisamos: ver tus alertas"
          className={`${redondo} text-rendi-pos hover:border-rendi-pos/40 ${className}`}>
          <Check size={14} strokeWidth={2.25} aria-hidden="true" />
        </Link>
      )
    }
    return (
      <Link to="/alertas?tab=mis" className={`inline-flex items-center gap-1 min-h-8 text-[12px] text-rendi-pos hover:underline ${className}`}>
        <Check size={13} strokeWidth={2.25} aria-hidden="true" /> Te avisamos
      </Link>
    )
  }

  async function crear(payload) {
    const res = await api.post('/alerts', payload)   // throws en 403 (tope del plan)
    track('alerta_creada', { tipo: 'tecnica', senal: payload.senal })
    return res
  }

  function creada(res, payload, pedidoPush) {
    toast.push('Listo: te avisamos cuando pase.', { type: 'success' })
    pedidoPush?.catch((ex) => {
      if (ex?.motivo === 'bloqueadas') return
      toast.push(payload.channel === 'push'
        ? 'Las notificaciones no se activaron, así que todavía no te va a llegar. Activalas desde Más → Notificaciones.'
        : 'Las notificaciones no se activaron: por ahora te llega por mail.', { type: 'warn', duration: 7000 })
    })
    avisos?.recargar?.()
  }

  return (
    <>
      {soloIcono ? (
        <button type="button" onClick={() => setAbierto(true)} title={queAvisa} aria-label={queAvisa}
          className={`${redondo} text-ink-1 hover:text-ink-0 hover:border-rendi-accent/40 transition ${className}`}>
          <Bell size={14} strokeWidth={2} aria-hidden="true" />
        </button>
      ) : (
        <button type="button" onClick={() => setAbierto(true)} title={queAvisa}
          className={`inline-flex items-center gap-1 min-h-8 px-2 -mx-2 rounded text-[12px] text-data-violet hover:bg-data-violet/10 ${className}`}>
          <Bell size={13} strokeWidth={2} aria-hidden="true" /> Avisame
        </button>
      )}
      {abierto && (
        <AlertaForm plan={plan} prefill={prefill} onClose={() => setAbierto(false)}
          crear={crear} onCreada={creada} />
      )}
    </>
  )
}

// El aviso activo de tu línea del gráfico vive en alertasTexto (lo usa también
// el formulario); se re-exporta para quien ya lo pedía de acá.
export { alertaDeLinea }

/**
 * «Avisame si el precio la toca», en el cartel de tu línea elegida (Nico,
 * 28/10), y «Avisame si sale del canal» en el de tu canal (29/10). Abre el
 * formulario de siempre ya armado con esa línea (el canal pregunta por qué
 * borde y cuándo cuenta); si ya hay un aviso, dice «Te avisamos» y deja dejar
 * de avisar.
 */
export function BotonAvisameLinea({ avisos, asset, accionLocal = false, moneda = 'usd', dibujo, tipoLinea }) {
  const plan = usePlanFeatures()
  const toast = useToast()
  const [abierto, setAbierto] = useState(false)
  const ya = alertaDeLinea(avisos?.items, { asset, moneda, dibujo })
  const canal = tipoLinea === 'canal'
  if (ya) {
    return (
      <span className="inline-flex items-center gap-2">
        <Link to="/alertas?tab=mis" className="inline-flex items-center gap-1 min-h-10 sm:min-h-8 text-[12.5px] text-rendi-pos hover:underline">
          <Check size={14} strokeWidth={2.25} aria-hidden="true" /> {canal ? 'Te avisamos si sale' : 'Te avisamos si la toca'}
        </Link>
        <button type="button" onClick={async () => {
          try { await api.patch(`/alerts/${ya.id}`, { active: false }); avisos?.recargar?.() }
          catch { toast.push('No se pudo desactivar el aviso. Probá de nuevo.', { type: 'warn' }) }
        }} className="min-h-10 sm:min-h-8 px-2 rounded text-[12.5px] text-ink-2 hover:text-ink-0 underline-offset-2 hover:underline">
          Dejar de avisar
        </button>
      </span>
    )
  }
  const prefill = {
    kind: 'tecnica', fijo: true, symbol: String(asset || '').toUpperCase(), senal: 'linea', direction: 'either',
    currency: moneda === 'ars' ? 'ARS' : 'USD', accionLocal: !!accionLocal, dibujo, tipoLinea,
    ...(canal ? { modo: 'toque' } : {}),
  }
  return (
    <>
      <button type="button" onClick={() => setAbierto(true)}
        className="inline-flex items-center gap-1.5 min-h-10 sm:min-h-8 px-3 rounded-lg border border-data-violet/50 bg-data-violet/10 text-ink-0 font-medium">
        <Bell size={14} aria-hidden="true" /> {canal ? 'Avisame si sale del canal' : 'Avisame si la toca'}
      </button>
      {abierto && (
        <AlertaForm plan={plan} prefill={prefill} onClose={() => setAbierto(false)}
          crear={async (payload) => {
            const res = await api.post('/alerts', payload)
            track('alerta_creada', { tipo: 'tecnica', senal: 'linea' })
            return res
          }}
          onCreada={(res, payload, pedidoPush) => {
            toast.push(canal ? 'Listo: te avisamos si el precio sale de tu canal.' : 'Listo: te avisamos si el precio toca tu línea.', { type: 'success' })
            pedidoPush?.catch((ex) => {
              if (ex?.motivo === 'bloqueadas') return
              toast.push('Las notificaciones no se activaron: por ahora te llega por mail.', { type: 'warn', duration: 7000 })
            })
            avisos?.recargar?.()
          }} />
      )}
    </>
  )
}

/**
 * Qué señal ofrece el «Avisame» de cada tarjeta de la ficha (ids de
 * `tarjetas()` en utils/tecnico.js), según cómo está hoy: si el precio está
 * arriba de su promedio, lo que sirve saber es cuándo queda abajo, y al revés.
 * null = esa tarjeta no lleva botón.
 */
export function senalDeTarjeta(id, l) {
  const lado = (d) => (d == null ? 'either' : d >= 0 ? 'below' : 'above')
  // La de fondo, con la tendencia que manda el servidor (P6): una sola regla.
  if (id === 'fondo') {
    const t = tendenciaDe(l)
    return { senal: 'media200', direction: !t ? 'either' : t === 'alcista' ? 'below' : 'above' }
  }
  if (id === 'corto') return { senal: 'media50', direction: lado(l?.dist_media50) }
  if (id === 'rsi') {
    // Lo próximo que puede pasar: abajo de 30, que vuelva a pasarlo; arriba de
    // 70, que vuelva a bajar; con fuerza, que pase 70; sin fuerza, que baje de 30.
    const r = l?.rsi
    if (r == null) return { senal: 'rsi_bajo_30' }
    return { senal: r < 30 ? 'rsi_sube_30' : r >= 70 ? 'rsi_baja_70' : r > 50 ? 'rsi_sobre_70' : 'rsi_bajo_30' }
  }
  if (id === 'maximo') return { senal: 'maximo_12m' }
  return null
}

/**
 * Qué aviso ofrece la campanita de un cambio de la semana (`tipo` y `sentido`
 * de GET /api/tus-senales): que vuelva a cambiar. Cruzó para arriba su promedio
 * → avisar si lo vuelve a cruzar para abajo; el impulso bajó de 30 → si vuelve
 * a superarlo; superó 70 → si vuelve a quedar debajo; empezó a marcar máximos →
 * la próxima vez que marque uno. La fuerza de la tendencia (ADX) no tiene
 * alerta: null, sin campanita.
 */
export function senalDelCambio(s) {
  const vuelta = s?.sentido === 'arriba' ? 'below' : s?.sentido === 'abajo' ? 'above' : 'either'
  if (s?.tipo === 'media200' || s?.tipo === 'media50') return { senal: s.tipo, direction: vuelta }
  if (s?.tipo === 'rsi_bajo_30') return { senal: 'rsi_sube_30' }
  if (s?.tipo === 'rsi_sobre_70') return { senal: 'rsi_baja_70' }
  if (s?.tipo === 'maximo_12m') return { senal: 'maximo_12m' }
  return null
}
