// Interruptores de /admin: prender o apagar para TODOS una función que se publica apagada.
//
// Los comparten el aviso nuevo de cambio de ratio y «Mover a otro broker». Cada uno lee
// GET /api/admin/<ruta> → { interruptor: { encendido, cambiado_at }, …lo suyo } y escribe
// POST /api/admin/<ruta>/interruptor { encendido } (backend: `_poner_interruptor`, el
// escritor único de la tabla `interruptores`). Lo propio de cada panel —la lista de cambios
// de ratio, las cuentas con pases sin deshacer— va en `children(e)`.
//
// Antes el del ratio tenía su propia copia del cargar/cambiar/botón y «Mover a otro broker»
// no tenía botón: el interruptor existía en el servidor y no había cómo prenderlo.
import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { api } from '../../utils/api'
import { confirmar } from '../../utils/confirmar'

/** La parte que se ve, sin estado (la prueban los render tests). */
export function VistaInterruptor({ titulo, e, busy, textos, onCambiar, children }) {
  const on = !!e?.interruptor?.encendido
  return (
    <div className="bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <AlertTriangle size={16} className="text-violet-500" />
          <h2 className="font-semibold text-ink-0">{titulo}</h2>
        </div>
        <button onClick={() => onCambiar(!on)} disabled={busy || !e}
          className={`text-xs px-3 py-1.5 rounded text-white disabled:opacity-50 ${on ? 'bg-rendi-neg hover:opacity-90' : 'bg-violet-600 hover:bg-violet-500'}`}>
          {busy ? 'Guardando…' : on ? textos.apagar : textos.prender}
        </button>
      </div>
      {!e ? <p className="text-xs text-ink-3">Cargando…</p> : (
        <>
          <p className={`text-sm font-medium ${on ? 'text-rendi-warn' : 'text-ink-1'}`}>
            {on ? textos.lineaPrendido : textos.lineaApagado}
            {e.interruptor?.cambiado_at && <span className="text-ink-3 font-normal"> · cambiado {e.interruptor.cambiado_at} (UTC)</span>}
          </p>
          {children ? children(e) : null}
        </>
      )}
    </div>
  )
}

export default function InterruptorAdmin({ toast, ruta, titulo, textos, children }) {
  const [e, setE] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let vivo = true
    api.get(`/admin/${ruta}`)
      .then((r) => { if (vivo) setE(r) })
      .catch((ex) => toast.push('Error: ' + ex.message, { type: 'error' }))
    return () => { vivo = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ruta])

  async function cambiar(encendido) {
    if (encendido && !await confirmar(textos.preguntaAlPrender)) return
    setBusy(true)
    try {
      const r = await api.post(`/admin/${ruta}/interruptor`, { encendido })
      setE((x) => ({ ...(x || {}), interruptor: r }))
      toast.push(r.encendido ? textos.avisoPrendido : textos.avisoApagado, { type: 'success' })
    } catch (ex) {
      toast.push('Error: ' + ex.message, { type: 'error' })
    } finally { setBusy(false) }
  }

  return <VistaInterruptor titulo={titulo} e={e} busy={busy} textos={textos} onCambiar={cambiar}>{children}</VistaInterruptor>
}

// ─── «Mover a otro broker» ──────────────────────────────────────────────────
// Se publica APAGADO. Apagado: nadie arma pases nuevos (la vista previa y el confirmar dan
// 403); los ya hechos se siguen viendo y deshaciendo. Para volver atrás una publicación,
// primero hay que deshacer los pases vivos (la lista de abajo; el servidor tiene
// POST /api/admin/mover-entre-brokers/deshacer-pases para hacerlo por cuenta).
export const TEXTOS_MOVER = {
  prender: 'Prender «Mover a otro broker»',
  apagar: 'Apagar «Mover a otro broker»',
  preguntaAlPrender: '¿Prender «Mover a otro broker» para todos? Desde ahora cada persona ve la opción en el menú de cada activo de Cartera.',
  lineaPrendido: 'PRENDIDO: todos ven «Mover a otro broker» en Cartera.',
  lineaApagado: 'Apagado: nadie puede armar un pase nuevo. Los que ya se hicieron se siguen viendo y se pueden deshacer.',
  avisoPrendido: '«Mover a otro broker» PRENDIDO',
  avisoApagado: '«Mover a otro broker» apagado',
}

export function lineaPasesVivos(cuentas) {
  if (!cuentas?.length) return 'Nadie tiene pases sin deshacer.'
  const total = cuentas.reduce((s, c) => s + (Number(c.pases) || 0), 0)
  const detalle = cuentas.map((c) => `cuenta ${c.user_id}: ${c.pases}`).join(' · ')
  return `${total} ${total === 1 ? 'pase' : 'pases'} sin deshacer (${detalle}). Antes de volver atrás una publicación, hay que deshacerlos.`
}

// ─── El bot de WhatsApp ─────────────────────────────────────────────────────
// Se publica APAGADO. Apagado: Configuración → WhatsApp dice «todavía no está disponible»
// y el timbre de Meta acepta los avisos sin contestarlos (a los números ya vinculados
// les dice «en mantenimiento»). Antes de prender: las variables WHATSAPP_* cargadas
// (el renglón de abajo dice si falta alguna) y el webhook dado de alta en Meta.
export const TEXTOS_WHATSAPP = {
  prender: 'Prender el bot de WhatsApp',
  apagar: 'Apagar el bot de WhatsApp',
  preguntaAlPrender: '¿Prender el bot de WhatsApp para todos los Pro? Desde ahora pueden vincular su número en Configuración → WhatsApp y Rendi les contesta por ahí.',
  lineaPrendido: 'PRENDIDO: los Pro pueden vincular su WhatsApp y Rendi contesta.',
  lineaApagado: 'Apagado: Configuración → WhatsApp dice «todavía no está disponible»; los avisos de Meta se descartan.',
  avisoPrendido: 'Bot de WhatsApp PRENDIDO',
  avisoApagado: 'Bot de WhatsApp apagado',
}

export function lineaBotWhatsapp(e) {
  const faltan = []
  if (!e?.configurado) faltan.push('WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID')
  if (!e?.firma) faltan.push('WHATSAPP_APP_SECRET')
  if (!e?.numero_bot) faltan.push('WHATSAPP_NUMERO')
  // La palabra del webhook: sin ella Meta no deja guardar el webhook («No se pudo
  // validar la URL»). Se informa sólo si está, nunca cuál es.
  if (!e?.palabra) faltan.push('WHATSAPP_VERIFY_TOKEN')
  const config = faltan.length ? `Falta configurar: ${faltan.join(', ')}.` : `Número del bot: +${e.numero_bot}.`
  return `${config} ${e?.cuentas_vinculadas ?? 0} ${e?.cuentas_vinculadas === 1 ? 'cuenta vinculada' : 'cuentas vinculadas'} · ${e?.mensajes_hoy ?? 0} ${e?.mensajes_hoy === 1 ? 'mensaje recibido hoy' : 'mensajes recibidos hoy'}.`
}

export function BotWhatsappPanel({ toast }) {
  return (
    <InterruptorAdmin toast={toast} ruta="whatsapp" titulo="Bot de WhatsApp" textos={TEXTOS_WHATSAPP}>
      {(e) => <p className="text-xs text-ink-3">{lineaBotWhatsapp(e)}</p>}
    </InterruptorAdmin>
  )
}

export function MoverEntreBrokersPanel({ toast }) {
  return (
    <InterruptorAdmin toast={toast} ruta="mover-entre-brokers" titulo="Mover a otro broker" textos={TEXTOS_MOVER}>
      {(e) => <p className="text-xs text-ink-3">{lineaPasesVivos(e.cuentas_con_pases)}</p>}
    </InterruptorAdmin>
  )
}
