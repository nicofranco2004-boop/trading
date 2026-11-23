// «Días que no cierran» — el panel del vigía de días en /admin.
//
// Lista las cuentas con plan vigente que vencen más tarde de lo que explica su
// historial de cobros (la regla vive en backend/billing/vigia_dias.py). En cada
// una, dos salidas, las dos con vista previa del servidor antes de escribir:
//   · «Corregir al dd/mm»: acorta el vencimiento a lo que dice el historial.
//   · «Dejar como está»: no mueve la fecha, deja constancia y la cuenta deja de
//     salir (en el panel y en el mail de cada noche).
// El motivo es obligatorio: queda escrito en el historial de la cuenta.
import { useState } from 'react'
import { AlertTriangle, RefreshCw, Check } from 'lucide-react'
import { api } from '../../utils/api'
import { confirmar } from '../../utils/confirmar'

export const MOTIVOS_VIGIA = {
  cobro_repetido: 'Un aviso de Rebill se contó como cobro más de una vez',
  sin_explicacion: 'Tiene más días de los que explica su historial',
  sin_registro: 'Tiene plan vigente sin ningún renglón en su historial',
}

const MOTIVO_POR_DEFECTO = {
  cobro_repetido: 'Avisos de Rebill que no eran cobros',
  sin_explicacion: 'Días de más sin cobro que los explique',
  sin_registro: 'Plan sin cobro registrado',
}

export function dia(iso) {
  const s = String(iso || '').slice(0, 10)
  return s.length === 10 ? `${s.slice(8, 10)}/${s.slice(5, 7)}/${s.slice(0, 4)}` : '—'
}

export function FilaHallazgo({ h, motivo, onMotivo, onCorregir, onDejar, ocupado }) {
  return (
    <li className="py-3 border-t border-line/60 first:border-t-0 space-y-2">
      <div className="text-sm text-ink-0">
        <b>{h.name || h.email}</b> <span className="text-ink-3 text-xs">· {h.email} · id <span className="tabular">{h.id}</span></span>
      </div>
      <div className="text-xs text-ink-2">
        Plan {h.plan} · vence <span className="tabular">{dia(h.vence)}</span>
        {h.deberia_vencer && <> · según lo que pagó, <span className="tabular">{dia(h.deberia_vencer)}</span></>}
        {' · '}<b className="text-rendi-warn"><span className="tabular">{h.dias_de_mas}</span> días de más</b>
      </div>
      <div className="text-xs text-ink-3">{MOTIVOS_VIGIA[h.motivo] || h.motivo}</div>
      {h.repetidos?.length > 0 && (
        <ul className="text-xs text-ink-3 list-disc pl-5">
          {h.repetidos.map((r, i) => (
            <li key={i}>
              <span className="tabular">{dia(r.fecha)}</span>: +<span className="tabular">{r.dias}</span> días,
              {' '}<span className="tabular">{r.dias_despues_del_anterior}</span> días después del cobro anterior
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-2 flex-wrap">
        <input
          value={motivo} onChange={e => onMotivo(e.target.value)} disabled={ocupado}
          aria-label="Motivo (queda en el historial)"
          className="flex-1 min-w-[12rem] rounded border border-line bg-bg-1 px-2 py-1 text-xs text-ink-0"
        />
        {h.deberia_vencer && (
          <button onClick={onCorregir} disabled={ocupado}
            className="text-xs px-3 py-1.5 rounded bg-rendi-warn/15 text-rendi-warn hover:bg-rendi-warn/25 disabled:opacity-50">
            Corregir al <span className="tabular">{dia(h.deberia_vencer)}</span>
          </button>
        )}
        <button onClick={onDejar} disabled={ocupado}
          className="text-xs px-3 py-1.5 rounded bg-bg-2 text-ink-2 hover:text-ink-0 disabled:opacity-50">
          Dejar como está
        </button>
      </div>
    </li>
  )
}

export default function VigiaDiasPanel({ toast }) {
  const [res, setRes] = useState(null)
  const [cargando, setCargando] = useState(false)
  const [ocupado, setOcupado] = useState(null)   // id de la cuenta en curso
  const [motivos, setMotivos] = useState({})

  async function cargar() {
    setCargando(true)
    try {
      setRes(await api.get('/admin/billing/vigia-dias'))
    } catch (e) {
      toast.push('No se pudo revisar: ' + (e.message || 'error'), { type: 'error' })
    } finally {
      setCargando(false)
    }
  }

  const motivoDe = (h) => motivos[h.id] ?? MOTIVO_POR_DEFECTO[h.motivo] ?? ''

  async function aplicar(h, fecha) {
    const motivo = motivoDe(h).trim()
    if (motivo.length < 5) {
      toast.push('Escribí el motivo: queda en el historial de la cuenta.', { type: 'error' })
      return
    }
    setOcupado(h.id)
    try {
      const cuerpo = { user_id: h.id, fecha, motivo }
      const p = await api.post('/admin/billing/corregir-vencimiento', { ...cuerpo, confirm: false })
      const pregunta = fecha
        ? `¿Corregir el vencimiento de ${h.email}?\n\n` +
          `Pasa del ${dia(p.antes)} al ${dia(p.despues)} (${Math.abs(Math.round(p.dias))} días menos). ` +
          (p.pierde_el_plan_ahora
            ? 'Esa fecha ya pasó: pierde el plan en el momento. '
            : 'Hasta esa fecha no nota nada. ') +
          'No se le manda ningún mail.'
        : `¿Dejar el vencimiento de ${h.email} como está?\n\n` +
          `Sigue venciendo el ${dia(p.antes)}. Queda anotado y deja de aparecer acá y en el mail de cada noche.`
      if (!await confirmar(pregunta, { si: fecha ? 'Corregir' : 'Dejar como está' })) return
      // `antes_visto`: lo que dijo el cartel. Si entró un cobro mientras se
      // leía, el servidor no escribe (409) y la lista se vuelve a cargar.
      await api.post('/admin/billing/corregir-vencimiento', { ...cuerpo, confirm: true, antes_visto: p.antes })
      toast.push(fecha ? `Listo: ${h.email} vence el ${dia(p.despues)}.` : `Listo: ${h.email} queda como está.`)
      await cargar()
    } catch (e) {
      toast.push(e.message || 'No se pudo corregir.', { type: 'error' })
    } finally {
      setOcupado(null)
    }
  }

  const hallazgos = res?.hallazgos || []
  return (
    <div className="bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <AlertTriangle size={16} className="text-rendi-warn" />
          <h2 className="font-semibold text-ink-0">Días que no cierran con lo pagado</h2>
        </div>
        <button onClick={cargar} disabled={cargando || ocupado !== null}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50">
          <RefreshCw size={12} className={cargando ? 'animate-spin' : ''} /> {res ? 'Revisar de nuevo' : 'Revisar'}
        </button>
      </div>
      <p className="text-xs text-ink-3 leading-relaxed">
        Compara, cuenta por cuenta, hasta cuándo tiene plan con lo que explican sus cobros. Corre solo todas las
        noches y, si encuentra algo, te manda un mail hasta que cada cuenta se corrija o se deje como está.
      </p>
      {res && hallazgos.length === 0 && (
        <p className="text-xs text-ink-2 flex items-center gap-1.5">
          <Check size={12} className="text-rendi-pos" />
          Las <span className="tabular">{res.revisadas}</span> cuentas con plan vigente cierran con lo que pagaron.
        </p>
      )}
      {hallazgos.length > 0 && (
        <ul>
          {hallazgos.map(h => (
            <FilaHallazgo key={h.id} h={h} motivo={motivoDe(h)} ocupado={ocupado !== null}
              onMotivo={v => setMotivos(m => ({ ...m, [h.id]: v }))}
              onCorregir={() => aplicar(h, String(h.deberia_vencer).slice(0, 10))}
              onDejar={() => aplicar(h, null)} />
          ))}
        </ul>
      )}
    </div>
  )
}
