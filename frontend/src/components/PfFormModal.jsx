// PfFormModal — alta de un plazo fijo.
// El banco viene de /pf/banks (con su TNA sugerida); el resto lo carga el user.
// Preview en vivo con computePf: tasa del período, interés, valor al
// vencimiento y equivalencia TNA↔TEA al plazo elegido.
import { useState, useEffect, useMemo } from 'react'
import { X, Landmark } from 'lucide-react'
import { api } from '../utils/api'
import { computePf } from '../utils/valuation'
import { useToast } from './Toast'

const today = () => new Date().toISOString().slice(0, 10)
const pct = (x) => (x * 100).toFixed(2) + '%'

export default function PfFormModal({ onClose, onSaved }) {
  const toast = useToast()
  const [banks, setBanks] = useState([])
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    banco: '', capital: '', moneda: 'ARS',
    tasa: '', rate_type: 'TNA',
    fecha_inicio: today(), plazo_dias: 30, renovacion_auto: false,
  })

  useEffect(() => {
    api.get('/pf/banks').then(d => setBanks(d || [])).catch(() => {})
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  function pickBank(name) {
    const b = banks.find(x => x.banco === name)
    setForm(f => ({
      ...f,
      banco: name,
      // Prefill de la TNA del banco (viene fracción → %), solo si el user no
      // tocó la tasa todavía.
      tasa: b && f.tasa === '' ? +(b.tna_clientes * 100).toFixed(2) : f.tasa,
      rate_type: b ? 'TNA' : f.rate_type,
    }))
  }

  const preview = useMemo(() => {
    const capital = +form.capital || 0
    const tasaFrac = (+form.tasa || 0) / 100
    const plazo = +form.plazo_dias || 0
    if (capital <= 0 || tasaFrac <= 0 || plazo <= 0) return null
    return computePf(
      { capital, tasa: tasaFrac, rate_type: form.rate_type, fecha_inicio: form.fecha_inicio, plazo_dias: plazo },
      form.fecha_inicio,  // asOf = inicio → preview del total del período
    )
  }, [form.capital, form.tasa, form.rate_type, form.plazo_dias, form.fecha_inicio])

  const sign = form.moneda === 'USD' ? 'US$' : '$'
  const money = (n) => sign + Math.round(n).toLocaleString('es-AR')

  async function save() {
    const capital = +form.capital, tasa = (+form.tasa) / 100, plazo = +form.plazo_dias
    if (!form.banco.trim()) return toast.push('Elegí el banco.', { type: 'warn' })
    if (!(capital > 0)) return toast.push('Poné el capital.', { type: 'warn' })
    if (!(tasa > 0)) return toast.push('Poné la tasa anual.', { type: 'warn' })
    if (!(plazo > 0)) return toast.push('Poné el plazo en días.', { type: 'warn' })
    setSaving(true)
    try {
      await api.post('/plazos-fijos', {
        banco: form.banco.trim(), capital, moneda: form.moneda, tasa,
        rate_type: form.rate_type, fecha_inicio: form.fecha_inicio,
        plazo_dias: plazo, renovacion_auto: form.renovacion_auto,
      })
      toast.push('Plazo fijo agregado.', { type: 'success' })
      onSaved && onSaved()
      onClose()
    } catch (e) {
      toast.push('Ocurrió un error: ' + e.message, { type: 'error' })
    } finally {
      setSaving(false)
    }
  }

  const inputClass = 'w-full bg-bg-2 border border-line-2 rounded-md px-3 py-2 text-sm text-ink-0 focus:outline-none focus:ring-2 focus:ring-rendi-accent/40 focus:border-rendi-accent/60 transition'

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-white dark:bg-bg-1 border border-line rounded-t-2xl sm:rounded w-full max-w-lg shadow-2xl max-h-[95vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-3 px-5 py-4 border-b border-line flex-shrink-0">
          <Landmark size={18} className="text-rendi-accent" aria-hidden="true" />
          <div className="flex-1 min-w-0">
            <h2 className="text-lg font-semibold text-ink-0 leading-tight">Agregar plazo fijo</h2>
            <p className="text-xs text-ink-2 mt-0.5">Cargá el banco, capital, tasa y plazo.</p>
          </div>
          <button onClick={onClose} className="-mr-2 p-2 text-ink-2 hover:text-ink-0" aria-label="Cerrar"><X size={16} /></button>
        </div>

        <div className="overflow-y-auto flex-1 p-5 space-y-3">
          <div>
            <label className="block text-xs text-ink-3 mb-1">Banco</label>
            <select className={inputClass} value={form.banco} onChange={e => pickBank(e.target.value)}>
              <option value="">Elegí un banco…</option>
              {banks.map(b => (
                <option key={b.banco} value={b.banco}>{b.banco} — {pct(b.tna_clientes)} TNA</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-ink-3 mb-1">Capital</label>
              <input type="number" inputMode="decimal" className={inputClass} value={form.capital} onChange={e => set('capital', e.target.value)} placeholder="1000000" />
            </div>
            <div>
              <label className="block text-xs text-ink-3 mb-1">Moneda</label>
              <select className={inputClass} value={form.moneda} onChange={e => set('moneda', e.target.value)}>
                <option value="ARS">ARS</option>
                <option value="USD">USD</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-ink-3 mb-1">Tasa anual (%)</label>
              <input type="number" step="0.01" inputMode="decimal" className={inputClass} value={form.tasa} onChange={e => set('tasa', e.target.value)} placeholder="19" />
            </div>
            <div>
              <label className="block text-xs text-ink-3 mb-1">Tipo de tasa</label>
              <div className="flex rounded-md overflow-hidden border border-line-2">
                {['TNA', 'TEA'].map(t => (
                  <button key={t} type="button" onClick={() => set('rate_type', t)}
                    className={`flex-1 py-2 text-sm transition ${form.rate_type === t ? 'bg-rendi-accent text-white' : 'bg-bg-2 text-ink-2 hover:text-ink-0'}`}>
                    {t}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-ink-3 mb-1">Fecha de inicio</label>
              <input type="date" className={inputClass} value={form.fecha_inicio} onChange={e => set('fecha_inicio', e.target.value)} />
            </div>
            <div>
              <label className="block text-xs text-ink-3 mb-1">Plazo (días)</label>
              <input type="number" inputMode="numeric" className={inputClass} value={form.plazo_dias} onChange={e => set('plazo_dias', e.target.value)} placeholder="30" />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-ink-1 cursor-pointer">
            <input type="checkbox" checked={form.renovacion_auto} onChange={e => set('renovacion_auto', e.target.checked)} />
            Renovación automática
          </label>

          {preview && (
            <div className="rounded-md border border-rendi-accent/30 bg-rendi-accent/[0.05] p-3 text-sm">
              <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">Estimación a {form.plazo_dias} días</div>
              <div className="grid grid-cols-2 gap-y-1.5">
                <span className="text-ink-3">Tasa del período</span><span className="text-right text-ink-0 font-medium tabular">{pct(preview.tasaPeriodo)}</span>
                <span className="text-ink-3">Interés</span><span className="text-right text-ink-0 font-medium tabular">{money(preview.interes)}</span>
                <span className="text-ink-3">Valor al vencimiento</span><span className="text-right text-ink-0 font-semibold tabular">{money(preview.valorVencimiento)}</span>
              </div>
              <div className="text-[11px] text-ink-3 mt-2 pt-2 border-t border-line/40">
                Equivale a TNA {pct(preview.tnaEquiv)} · TEA {pct(preview.teaEquiv)} (a {form.plazo_dias} días)
              </div>
            </div>
          )}
        </div>

        <div className="flex gap-2 px-5 py-4 border-t border-line flex-shrink-0">
          <button onClick={onClose} className="flex-1 py-2 rounded-md border border-line text-ink-1 text-sm hover:bg-bg-2 transition">Cancelar</button>
          <button onClick={save} disabled={saving} className="flex-1 py-2 rounded-md bg-rendi-accent text-white text-sm font-semibold hover:bg-rendi-accent/90 disabled:opacity-50 transition">
            {saving ? 'Guardando…' : 'Agregar'}
          </button>
        </div>
      </div>
    </div>
  )
}
