// ClientMoveAlert — "avisame si la cartera de cualquiera de mis clientes se
// mueve X%". Es la alerta de variación % que ya tienen los usuarios, pero un
// nivel arriba: en vez de un ACTIVO, mira la CARTERA COMPLETA de cada cliente.
import { useState } from 'react'
import { TrendingUp, TrendingDown, Users } from 'lucide-react'
import Panel from '../Panel'
import { api } from '../../utils/api'
import { useToast } from '../Toast'

// Coma o punto: en Argentina se tipea "0,5" (mismo helper que las alertas).
function parseNum(v) {
  let s = String(v == null ? '' : v).trim().replace(/\s/g, '')
  if (!s) return NaN
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.')
  return parseFloat(s)
}

export default function ClientMoveAlert({ config, onSaved }) {
  const toast = useToast()
  const [up, setUp] = useState(config?.up_pct != null ? String(config.up_pct) : '')
  const [down, setDown] = useState(config?.down_pct != null ? String(config.down_pct) : '')
  const [channel, setChannel] = useState(config?.channel || 'both')
  const [busy, setBusy] = useState(false)
  const active = !!config?.active

  async function save(nextActive) {
    const u = parseNum(up), d = parseNum(down)
    if (nextActive && !(u > 0) && !(d > 0)) {
      toast.push('Poné al menos un umbral: sube y/o baja X%', { type: 'error' })
      return
    }
    setBusy(true)
    try {
      const r = await api.patch('/advisor/alerts', {
        up_pct: u > 0 ? u : 0, down_pct: d > 0 ? d : 0,
        channel, active: nextActive,
      })
      onSaved?.(r.config)
      toast.push(nextActive ? 'Alerta activada' : 'Alerta pausada')
    } catch (e) {
      toast.push(e?.message || 'No se pudo guardar', { type: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const seg = (on) => `inline-flex items-center gap-1 text-xs px-3 py-1.5 rounded-sm border transition-colors ${
    on ? 'border-rendi-accent bg-rendi-accent/10 text-rendi-accent' : 'border-line text-ink-2 hover:border-line/80'}`

  return (
    <Panel padding="none">
      <header className="px-4 py-3 border-b border-line flex items-center justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <Users size={17} strokeWidth={1.75} className="text-ink-3 mt-0.5" aria-hidden="true" />
          <div>
            <h2 className="text-sm font-medium text-ink-0">Movimiento en la cartera de un cliente</h2>
            <p className="text-xs text-ink-3 mt-0.5">
              Te avisamos cuando la cartera de <span className="font-medium">cualquiera</span> de tus
              clientes se mueve más de lo que definas en el día
            </p>
          </div>
        </div>
        <span className={`text-[10px] font-medium rounded px-2 py-0.5 flex-shrink-0 ${
          active ? 'bg-rendi-pos/10 text-rendi-pos' : 'bg-bg-2 text-ink-3'}`}>
          {active ? 'Activa' : 'Apagada'}
        </span>
      </header>

      <div className="px-4 py-3.5 space-y-3">
        <p className="text-[11px] text-ink-3">Completá uno o los dos (podés poner valores distintos)</p>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-xs text-ink-2 w-28 flex-shrink-0">
            <TrendingUp size={13} /> Sube más de
          </span>
          <input value={up} onChange={e => setUp(e.target.value)} type="text" inputMode="decimal"
            placeholder="—" className="flex-1 text-sm bg-bg-2 border border-line rounded-sm px-3 py-2 text-ink-0 placeholder:text-ink-3 focus:border-rendi-accent/50 outline-none" />
          <span className="text-xs text-ink-3 w-6">%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 text-xs text-ink-2 w-28 flex-shrink-0">
            <TrendingDown size={13} /> Baja más de
          </span>
          <input value={down} onChange={e => setDown(e.target.value)} type="text" inputMode="decimal"
            placeholder="—" className="flex-1 text-sm bg-bg-2 border border-line rounded-sm px-3 py-2 text-ink-0 placeholder:text-ink-3 focus:border-rendi-accent/50 outline-none" />
          <span className="text-xs text-ink-3 w-6">%</span>
        </div>

        <div className="flex gap-2 flex-wrap pt-1">
          <button type="button" className={seg(channel === 'both')} onClick={() => setChannel('both')}>Push + Email</button>
          <button type="button" className={seg(channel === 'push')} onClick={() => setChannel('push')}>Push</button>
          <button type="button" className={seg(channel === 'email')} onClick={() => setChannel('email')}>Email</button>
        </div>
        <p className="text-[11px] text-ink-3 -mt-1">
          Un aviso por cliente por día, solo con el mercado abierto — no te llena la casilla.
        </p>

        <div className="flex gap-2 pt-1">
          <button type="button" disabled={busy} onClick={() => save(!active)}
            className={`text-xs px-4 py-2 rounded-sm font-medium disabled:opacity-50 ${
              active ? 'border border-line text-ink-2 hover:text-ink-0'
                     : 'bg-rendi-accent text-white'}`}>
            {busy ? 'Guardando…' : active ? 'Pausar' : 'Activar alerta'}
          </button>
          {active && (
            <button type="button" disabled={busy} onClick={() => save(true)}
              className="text-xs text-rendi-accent hover:underline px-2 py-2">
              Guardar cambios
            </button>
          )}
        </div>
      </div>
    </Panel>
  )
}
