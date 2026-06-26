// RentaFijaSections — zona "Renta Fija" en Cartera. Agrupa los bonos / letras /
// FCI de TODOS los brokers en secciones por (categoría, moneda) — Bonos USD, Bonos
// ARS, Letras, FCI ARS/USD — y permite ELIMINAR una sección entera (borrado
// reversible) sin tocar el broker ni la renta variable, y RESTAURARLA.
//
// Las posiciones siguen viviendo en su broker (la valuación depende de eso): esto
// es solo agrupación de presentación. Cada fila se valúa con `valuePos` del padre
// (misma lógica que las tablas por broker → sin divergencia).
import { useState, useEffect, Fragment } from 'react'
import { Layers, Trash2, RotateCcw, ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../utils/api'
import { useToast } from './Toast'
import { positionSection, sectionKey, sectionLabel, sortSectionKeys } from '../utils/sections'

export default function RentaFijaSections({ positions = [], valuePos, brokers = [], displayCurrency = 'USD', tcBlue = 1, onChanged }) {
  const toast = useToast()
  const [archived, setArchived] = useState([])
  const [busy, setBusy] = useState(null)
  const [open, setOpen] = useState({})   // colapsado por sección

  async function loadArchived() {
    try { setArchived((await api.get('/sections/archived'))?.archived || []) }
    catch { /* noop */ }
  }
  useEffect(() => { loadArchived() }, [positions])

  // Agrupar las posiciones de renta fija por sección.
  const groups = {}
  for (const p of positions) {
    if (p.is_cash) continue
    const sec = positionSection(p.asset_type, p.asset, p.currency)
    if (!sec) continue
    const key = sectionKey(sec.category, sec.currency)
    if (!groups[key]) groups[key] = { category: sec.category, currency: sec.currency, rows: [] }
    groups[key].rows.push(p)
  }
  const keys = sortSectionKeys(Object.keys(groups))

  if (keys.length === 0 && archived.length === 0) return null

  const fmtMoney = (usd) => {
    const n = displayCurrency === 'ARS' ? usd * tcBlue : usd
    const sym = displayCurrency === 'ARS' ? '$' : 'US$'
    return sym + Math.round(n).toLocaleString('es-AR')
  }
  const pct = (x) => (x >= 0 ? '+' : '') + (x * 100).toFixed(1) + '%'

  async function wipeSection(key, label, count) {
    if (!confirm(`¿Eliminar la sección "${label}" (${count} ${count === 1 ? 'posición' : 'posiciones'})?\n\nSe puede restaurar después. No toca el broker ni el resto de tus tenencias.`)) return
    setBusy(key)
    try {
      await api.post('/sections/archive', { section: key })
      toast.push(`"${label}" eliminada. Podés restaurarla.`, { type: 'success' })
      onChanged && onChanged()
      loadArchived()
    } catch (e) {
      toast.push('No se pudo eliminar: ' + e.message, { type: 'error' })
    } finally { setBusy(null) }
  }

  async function restore(a) {
    setBusy('r' + a.id)
    try {
      await api.post('/sections/restore', { archive_id: a.id })
      toast.push(`"${a.label}" restaurada.`, { type: 'success' })
      onChanged && onChanged()
      loadArchived()
    } catch (e) {
      toast.push('No se pudo restaurar: ' + e.message, { type: 'error' })
    } finally { setBusy(null) }
  }

  return (
    <div className="mt-6">
      <div className="flex items-center gap-2 px-4 sm:px-5 py-3 border-b border-line">
        <Layers size={15} className="text-ink-2" strokeWidth={1.5} />
        <h3 className="text-lg font-semibold leading-tight text-ink-0">Renta Fija</h3>
        <span className="text-ink-3 text-xs">· {keys.length} {keys.length === 1 ? 'sección' : 'secciones'}</span>
      </div>

      {keys.map(key => {
        const g = groups[key]
        const label = sectionLabel(g.category, g.currency)
        const isOpen = open[key] !== false   // default abierto
        let secValue = 0, secInv = 0
        const valued = g.rows.map(p => {
          const v = valuePos ? valuePos(p) : { valueUsd: 0, investedUsd: 0, pnlUsd: 0, pnlPct: 0 }
          secValue += v.valueUsd || 0
          secInv += v.investedUsd || 0
          return { p, v }
        })
        const secPnl = secValue - secInv
        const secPct = secInv > 0 ? secPnl / secInv : 0
        return (
          <div key={key} className="mt-3 bg-white dark:bg-bg-2/40 border border-line rounded-md overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-line/60 bg-bg-2/40">
              <button onClick={() => setOpen(o => ({ ...o, [key]: !isOpen }))}
                className="flex items-center gap-2 text-sm font-medium text-ink-0">
                {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                {label} <span className="text-ink-3 text-xs">· {g.rows.length}</span>
              </button>
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <div className="text-ink-0 font-semibold tabular text-sm">{fmtMoney(secValue)}</div>
                  <div className={`text-[11px] tabular ${secPnl >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>{pct(secPct)}</div>
                </div>
                <button onClick={() => wipeSection(key, label, g.rows.length)} disabled={busy === key}
                  className="text-ink-3 hover:text-red-500 transition disabled:opacity-40"
                  title={`Eliminar la sección ${label} (reversible)`}>
                  <Trash2 size={15} />
                </button>
              </div>
            </div>
            {isOpen && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-line/50">
                      {['Activo', 'Broker', 'Cantidad', 'Valor', 'P&L'].map(h => (
                        <th key={h} className="px-3 py-2 text-left text-xs text-ink-3 font-medium whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {valued.map(({ p, v }) => (
                      <tr key={p.id} className="border-b border-line/40 hover:bg-bg-2/40">
                        <td className="px-3 py-2 font-medium text-ink-0">{p.asset}</td>
                        <td className="px-3 py-2 text-[11px] text-ink-3">{p.broker}</td>
                        <td className="px-3 py-2 text-ink-1 tabular">{(p.quantity || 0).toLocaleString('es-AR')}</td>
                        <td className="px-3 py-2 text-ink-0 tabular">{v.valueUsd != null ? fmtMoney(v.valueUsd) : '—'}</td>
                        <td className={`px-3 py-2 tabular text-[12px] ${(v.pnlPct || 0) >= 0 ? 'text-rendi-pos' : 'text-rendi-neg'}`}>
                          {v.valueUsd != null ? pct(v.pnlPct || 0) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })}

      {archived.length > 0 && (
        <div className="mt-3 text-xs text-ink-3">
          <div className="mb-1.5 label-mono">Secciones eliminadas</div>
          <div className="flex flex-col gap-1.5">
            {archived.map(a => (
              <div key={a.id} className="flex items-center justify-between bg-bg-2/30 border border-line/60 rounded px-3 py-1.5">
                <span className="text-ink-2">{a.label} <span className="text-ink-3">· {a.count} {a.count === 1 ? 'posición' : 'posiciones'}</span></span>
                <button onClick={() => restore(a)} disabled={busy === 'r' + a.id}
                  className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded bg-bg-2 hover:bg-bg-3 border border-line text-ink-1 transition disabled:opacity-40">
                  <RotateCcw size={11} /> Restaurar
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
