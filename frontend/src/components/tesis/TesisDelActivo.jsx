// TesisDelActivo — «por qué lo compraste», con la tendencia de ese día y la de
// hoy, y «Recordarme revisarla». El MISMO componente en Movimientos (la
// posición abierta) y en la ficha del activo; los datos llegan de `useTesis()`
// (hooks/useDiario.js), que lo llama la pantalla una vez.
//
// La tesis es por ACTIVO y con historia por día (backend/tesis.py). Acá se ve
// y se edita la vigente (la última); las ventas viejas muestran la que tenían.
//
// Describe, no aconseja: dice cómo estaba el precio contra su promedio de 200
// días el día que la escribiste y hoy. Nunca «vendé» ni «mantené».

import { useState } from 'react'
import { BellRing, Pencil, Trash2 } from 'lucide-react'
import { api } from '../../utils/api'
import DateInput from '../DateInput'
import { tesisVigente } from '../../utils/diarioOperaciones'
import { fechaCorta } from '../operations/DiarioCeldas'
import { confirmar } from '../../utils/confirmar'

const MAX = 1000

function comoEstaba(t) {
  if (!t?.tendencia) return null
  return { arriba: t.tendencia === 'alcista', palabra: t.tendencia, dist: t.dist, fecha: t.fecha }
}

const pct1 = (x) => `${Math.abs(x).toLocaleString('es-AR', { maximumFractionDigits: 1 })} %`

/** «Cuando la escribiste estaba alcista. Al cierre del 28/10/26 estaba 8,1 % abajo de su
 *  promedio de 200 días: bajista.» La de ahora es la del último cierre, con su fecha
 *  (auditoría D5, 29/10: decía «Hoy» al lado del precio en vivo de la ficha). */
export function lineaDeTendencias(antes, hoy) {
  const a = comoEstaba(antes), h = comoEstaba(hoy)
  const partes = []
  if (a) partes.push(`Cuando la escribiste el precio estaba ${a.arriba ? 'arriba' : 'abajo'} de su promedio de 200 días (${a.palabra}).`)
  if (h) {
    const d = h.dist != null ? `${pct1(h.dist)} ` : ''
    const cuando = h.fecha ? `Al cierre del ${fechaCorta(h.fecha)}` : 'En el último cierre'
    partes.push(`${cuando} estaba ${d}${h.arriba ? 'arriba' : 'abajo'} de su promedio de 200 días: ${h.palabra}.`)
  }
  if (!a && !h) partes.push('Sin lectura de tendencia: no hay precios guardados de este activo (pasa con bonos y fondos).')
  return partes.join(' ')
}

export default function TesisDelActivo({ asset, local = false, tesis, desde = null, className = '' }) {
  const vigente = tesisVigente(tesis?.items, asset)
  const [editando, setEditando] = useState(false)
  const [texto, setTexto] = useState('')
  const [guardando, setGuardando] = useState(false)
  const [error, setError] = useState(null)
  const [eligiendoFecha, setEligiendoFecha] = useState(false)
  const [fecha, setFecha] = useState('')

  if (!tesis || tesis.estado === 'cargando') {
    return <div className={`text-[12.5px] text-ink-3 ${className}`}>Cargando tu tesis…</div>
  }
  if (tesis.estado === 'error') return null

  const escribir = !vigente || editando

  async function guardar() {
    setGuardando(true); setError(null)
    try {
      await api.put('/tesis', { asset, texto, local })
      await tesis.recargar()
      setEditando(false)
    } catch (ex) {
      setError(ex?.message || 'No pudimos guardar tu tesis.')
    } finally { setGuardando(false) }
  }

  async function borrar() {
    // La tesis tiene historia por día: si hay una más vieja, vuelve a ser la
    // vigente. Que no sea una sorpresa.
    const anterior = tesisVigente((tesis.items || []).filter(t => t.id !== vigente.id), asset)
    const ok = await confirmar(
      `¿Borrar tu tesis de ${asset}?\n\nSe borra este texto y, si tenía, el recordatorio.`
        + (anterior ? ` Vuelve a verse la que escribiste el ${fechaCorta(anterior.escrita_el)}.` : ''),
      { si: 'Borrar', peligro: true })
    if (!ok) return
    setError(null)
    try {
      await api.delete(`/tesis/${vigente.id}`)
      await tesis.recargar()
    } catch (ex) { setError(ex?.message || 'No pudimos borrarla.') }
  }

  async function recordar(tipo, f = null) {
    setGuardando(true); setError(null)
    try {
      await api.put(`/tesis/${vigente.id}/recordatorio`, { tipo, fecha: f })
      await tesis.recargar()
      setEligiendoFecha(false)
    } catch (ex) {
      setError(ex?.message || 'No pudimos guardar el recordatorio.')
    } finally { setGuardando(false) }
  }

  async function sinRecordatorio() {
    setError(null)
    try {
      await api.delete(`/tesis/${vigente.id}/recordatorio`)
      await tesis.recargar()
    } catch (ex) { setError(ex?.message || 'No pudimos sacar el recordatorio.') }
  }

  const rec = vigente?.recordatorio
  const chip = 'inline-flex items-center rounded-full border border-line bg-bg-2 px-3 py-1.5 text-[13px] text-ink-0 hover:bg-bg-3 transition-colors disabled:opacity-40'

  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="text-base font-semibold text-ink-0">{asset}</span>
        {desde && <span className="text-[12.5px] text-ink-2">{desde}</span>}
      </div>

      {escribir ? (
        <div className="flex flex-col gap-2">
          <label htmlFor={`tesis-${asset}`} className="text-[12.5px] text-ink-2 font-medium">¿Por qué lo compraste?</label>
          <textarea
            id={`tesis-${asset}`}
            value={texto}
            onChange={e => setTexto(e.target.value.slice(0, MAX))}
            rows={3}
            placeholder="Por ejemplo: «El recambio de celulares por la IA va a empujar las ventas en 2026»."
            className="w-full bg-bg-2 border border-line rounded px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2"
          />
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <span className="text-[12px] text-ink-3">Se guarda con la fecha de hoy y cómo está la tendencia hoy.</span>
            <div className="flex gap-2">
              {vigente && (
                <button type="button" onClick={() => { setEditando(false); setError(null) }}
                  className="text-[13px] text-ink-2 hover:text-ink-0 px-2 py-1">Cancelar</button>
              )}
              <button type="button" onClick={guardar} disabled={guardando || !texto.trim()}
                className="inline-flex items-center text-[13px] bg-data-violet/10 text-data-violet hover:bg-data-violet/15 border border-data-violet/30 px-3 py-1.5 rounded transition-colors font-medium disabled:opacity-40">
                {guardando ? 'Guardando…' : 'Guardar'}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <>
          <blockquote className="bg-bg-2 border border-line rounded-lg px-3 py-2.5 text-sm leading-relaxed text-ink-0 whitespace-pre-line break-words">
            «{vigente.texto}»
          </blockquote>
          <div className="text-[12.5px] text-ink-3">Escrita el {fechaCorta(vigente.escrita_el)}</div>
          <p className="text-[13px] leading-relaxed text-ink-1">
            {lineaDeTendencias(vigente.tendencia, tesis.hoy?.[asset])}
          </p>
          <div className="flex gap-3">
            <button type="button" onClick={() => { setTexto(vigente.texto); setEditando(true); setError(null) }}
              className="inline-flex items-center gap-1 text-[12.5px] text-ink-2 hover:text-ink-0">
              <Pencil size={12} strokeWidth={1.75} aria-hidden="true" /> Cambiarla
            </button>
            <button type="button" onClick={borrar}
              className="inline-flex items-center gap-1 text-[12.5px] text-ink-2 hover:text-rendi-neg">
              <Trash2 size={12} strokeWidth={1.75} aria-hidden="true" /> Borrar
            </button>
          </div>

          <div className="flex flex-col gap-2 pt-1">
            <div className="text-[12.5px] text-ink-2 font-medium">Recordarme revisarla</div>
            {rec && !rec.avisado_at ? (
              <div className="flex items-start gap-2 text-[13px] text-ink-1">
                <BellRing size={13} strokeWidth={1.75} className="text-data-violet mt-1 shrink-0" aria-hidden="true" />
                <span>
                  Te avisamos el {fechaCorta(rec.fecha)} por mail y notificación{rec.tipo === 'balance' ? ', el día después del balance' : ''}.{' '}
                  <button type="button" onClick={sinRecordatorio} className="text-[12.5px] text-ink-3 hover:text-ink-0 underline">Quitar</button>
                </span>
              </div>
            ) : (
              <>
                {rec?.avisado_at && (
                  <div className="text-[12.5px] text-ink-3">Te lo recordamos el {fechaCorta(rec.fecha)}.</div>
                )}
                <div className="flex flex-wrap gap-1.5">
                  <button type="button" className={chip} disabled={guardando} onClick={() => recordar('3m')}>En 3 meses</button>
                  <button type="button" className={chip} disabled={guardando} onClick={() => setEligiendoFecha(v => !v)}>Una fecha</button>
                  <button type="button" className={chip} disabled={guardando} onClick={() => recordar('balance')}>Después del próximo balance</button>
                </div>
                {eligiendoFecha && (
                  <div className="flex items-center gap-2">
                    <DateInput value={fecha} onChange={setFecha} className="max-w-[11rem]" />
                    <button type="button" disabled={!fecha || guardando} onClick={() => recordar('fecha', fecha)}
                      className="text-[13px] text-data-violet font-medium disabled:opacity-40">Listo</button>
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}
      {error && <div role="alert" className="text-[12.5px] text-rendi-neg">{error}</div>}
    </div>
  )
}
