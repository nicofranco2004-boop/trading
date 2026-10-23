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
// servidor una vez por día con el cierre (alerts_engine.evaluar_tecnicas).
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bell, Check } from 'lucide-react'
import AlertaForm from './AlertaForm'
import { usePlanFeatures } from '../../hooks/usePlanFeatures'
import { useToast } from '../Toast'
import { api } from '../../utils/api'
import { track } from '../../utils/track'
import { conSentido, SENALES_TECNICAS } from './alertasTexto'

/** La alerta técnica que se arma desde una señal (lo que se manda al formulario). */
export function prefillTecnico({ asset, accionLocal = false, moneda = 'usd', senal, direction }) {
  return {
    kind: 'tecnica', fijo: true, symbol: String(asset || '').toUpperCase(), senal,
    direction: conSentido(senal) ? (direction || 'either') : 'either',
    currency: moneda === 'ars' ? 'ARS' : 'USD', accionLocal: !!accionLocal,
  }
}

/** ¿Ya hay una alerta técnica activa para esta señal, este activo y esta moneda? */
export function alertaExistente(items = [], p) {
  return items.find(a => a.kind === 'tecnica' && a.active
    && String(a.symbol || '').toUpperCase() === p.symbol && a.senal === p.senal
    && String(a.currency || 'USD').toUpperCase() === p.currency
    && !!a.accion_local === p.accionLocal) || null
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

export function BotonAvisame({ avisos, className = '', ...datos }) {
  const plan = usePlanFeatures()
  const toast = useToast()
  const [abierto, setAbierto] = useState(false)
  const prefill = prefillTecnico(datos)
  const ya = alertaExistente(avisos?.items, prefill)

  if (ya) {
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
      <button type="button" onClick={() => setAbierto(true)}
        title={`Avisame cuando ${(SENALES_TECNICAS.find(x => x.id === prefill.senal)?.texto || '').replace(/^./, c => c.toLowerCase())}`}
        className={`inline-flex items-center gap-1 min-h-8 px-2 -mx-2 rounded text-[12px] text-data-violet hover:bg-data-violet/10 ${className}`}>
        <Bell size={13} strokeWidth={2} aria-hidden="true" /> Avisame
      </button>
      {abierto && (
        <AlertaForm plan={plan} prefill={prefill} onClose={() => setAbierto(false)}
          crear={crear} onCreada={creada} />
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
  if (id === 'fondo') return { senal: 'media200', direction: lado(l?.dist_media200) }
  if (id === 'corto') return { senal: 'media50', direction: lado(l?.dist_media50) }
  if (id === 'rsi') {
    const r = l?.rsi
    return { senal: r != null && r < 30 ? 'rsi_sube_30' : r != null && r > 50 ? 'rsi_sobre_70' : 'rsi_bajo_30' }
  }
  if (id === 'maximo') return { senal: 'maximo_12m' }
  return null
}
