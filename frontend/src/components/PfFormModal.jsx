// PfFormModal — alta de un plazo fijo, en 2 pasos:
//   1. Elegí el banco (lista buscable con logo + tasa, estilo FCI/tickers).
//   2. Datos del PF (capital, tasa prefilleada, plazo…) + preview en vivo.
// La tasa se prefilla con la TNA del banco elegido (cada vez que lo cambiás).
import { useState, useEffect, useMemo, useRef } from 'react'
import { X, ArrowLeft, Search, Landmark, Pencil } from 'lucide-react'
import { api } from '../utils/api'
import { computePf } from '../utils/valuation'
import { useToast } from './Toast'

const today = () => new Date().toISOString().slice(0, 10)
const pct = (x) => (x * 100).toFixed(2) + '%'

// Aritmética de fechas local (sin shift de timezone).
function addDays(dateStr, days) {
  if (!dateStr) return ''
  const [y, m, d] = dateStr.split('-').map(Number)
  const dt = new Date(y, (m || 1) - 1, (d || 1) + (+days || 0))
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
}
function daysBetween(aStr, bStr) {
  if (!aStr || !bStr) return 0
  const [ay, am, ad] = aStr.split('-').map(Number)
  const [by, bm, bd] = bStr.split('-').map(Number)
  return Math.round((new Date(by, bm - 1, bd) - new Date(ay, am - 1, ad)) / 86400000)
}

// Prettify del nombre del banco (la API los trae en mayúscula).
const SMALL = new Set(['de', 'la', 'del', 'y', 'el', 'los', 'las', 'en'])
const KEEP = new Set(['BBVA', 'ICBC', 'CMF', 'BIND', 'HSBC', 'BICE', 'BACS', 'S.A.', 'S.A.U.'])
function prettyBank(name) {
  return (name || '').split(/\s+/).map((w, i) => {
    if (KEEP.has(w)) return w
    const lo = w.toLowerCase()
    if (i > 0 && SMALL.has(lo)) return lo
    return lo.charAt(0).toUpperCase() + lo.slice(1)
  }).join(' ')
}

function BankLogo({ logo, name, size = 32 }) {
  const [err, setErr] = useState(false)
  const src = logo ? logo.replace(/^http:\/\//, 'https://') : null
  if (!src || err) {
    const initials = (name || '?').replace(/^BANCO\s+(DE\s+(LA\s+)?)?/i, '').trim().slice(0, 2).toUpperCase()
    return (
      <div style={{ width: size, height: size }} className="rounded-full bg-bg-3 border border-line flex items-center justify-center text-[10px] font-bold text-ink-2 flex-shrink-0">
        {initials || '?'}
      </div>
    )
  }
  return (
    <img src={src} alt="" onError={() => setErr(true)} style={{ width: size, height: size }}
      className="rounded-full bg-white object-contain border border-line flex-shrink-0" />
  )
}

// ── Paso 1: picker de banco (buscable, con logo + tasa) ──────────────────────
function BankPicker({ banks, onPick, onManual }) {
  const [query, setQuery] = useState('')
  const inputRef = useRef(null)
  useEffect(() => { inputRef.current?.focus() }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return banks
    return banks.filter(b => (b.banco || '').toLowerCase().includes(q))
  }, [query, banks])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-5 py-3 border-b border-line bg-bg-2/40 dark:bg-bg-2/30 flex-shrink-0">
        <div className="relative">
          <Search size={14} strokeWidth={1.75} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-3 pointer-events-none" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Buscar banco…"
            autoComplete="off"
            spellCheck="false"
            className="w-full bg-white dark:bg-bg-1 border border-line rounded-sm pl-9 pr-3 py-2 text-sm text-ink-0 placeholder-ink-3 focus:outline-none focus:border-rendi-accent/60 focus:ring-2 focus:ring-rendi-accent/20 transition"
          />
        </div>
        <p className="text-xs text-ink-3 font-mono mt-2">
          {filtered.length} de {banks.length} bancos · ordenados por tasa
        </p>
      </div>
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="p-8 text-center text-sm text-ink-2">
            Sin resultados para <span className="font-mono">"{query}"</span>
          </div>
        ) : (
          <ul className="divide-y divide-line/50 dark:divide-line/40">
            {filtered.map(b => (
              <li key={b.banco}>
                <button
                  onClick={() => onPick(b)}
                  className="w-full flex items-center gap-3 px-5 py-3 hover:bg-bg-2 dark:hover:bg-bg-2/40 transition-colors text-left focus:outline-none focus:bg-bg-2 dark:focus:bg-bg-2/40"
                >
                  <BankLogo logo={b.logo} name={b.banco} size={32} />
                  <div className="min-w-0 flex-1">
                    <p className="font-semibold text-ink-0 text-sm truncate">{prettyBank(b.banco)}</p>
                    <p className="text-xs text-ink-2">Tasa de hoy</p>
                  </div>
                  <span className="text-sm font-semibold text-rendi-pos tabular flex-shrink-0">{pct(b.tna_clientes)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {/* Opción de carga manual (banco que no está en la lista, o todo a mano) */}
      <div className="border-t border-line px-5 py-3 flex-shrink-0">
        <button
          onClick={onManual}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-md border border-dashed border-line hover:border-rendi-accent/40 hover:bg-bg-2 transition text-left"
        >
          <div className="flex-shrink-0 w-8 h-8 rounded-full bg-bg-3 border border-line flex items-center justify-center text-ink-2">
            <Pencil size={14} strokeWidth={1.75} aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink-0">Seguir sin banco de la lista</p>
            <p className="text-xs text-ink-3">Cargás el banco y la tasa a mano</p>
          </div>
        </button>
      </div>
    </div>
  )
}

export default function PfFormModal({ onClose, onSaved }) {
  const toast = useToast()
  const [banks, setBanks] = useState([])
  const [step, setStep] = useState('bank')   // 'bank' | 'form'
  const [manual, setManual] = useState(false)  // banco fuera de la lista / carga a mano
  const [plazoMode, setPlazoMode] = useState('dias')  // 'dias' | 'fecha'
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    banco: '', logo: null, capital: '', moneda: 'ARS',
    tasa: '', rate_type: 'TNA', fecha_inicio: today(), plazo_dias: 30, renovacion_auto: false,
    modalidad: 'vencimiento', pago_frecuencia_meses: 1,
  })

  useEffect(() => {
    api.get('/pf/banks').then(d => setBanks(d || [])).catch(() => {})
    function onKey(e) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  function pickBank(b) {
    // Prefill SIEMPRE con la TNA del banco elegido (fix del bug de antes, que
    // solo prefilleaba la primera vez). Si la cambiás a mano queda lo que pongas.
    setManual(false)
    setForm(f => ({ ...f, banco: b.banco, logo: b.logo, tasa: +(b.tna_clientes * 100).toFixed(2), rate_type: 'TNA' }))
    setStep('form')
  }

  function goManual() {
    // Sin banco de la lista: banco como texto, tasa vacía (todo a mano).
    setManual(true)
    setForm(f => ({ ...f, banco: '', logo: null, tasa: '' }))
    setStep('form')
  }

  const preview = useMemo(() => {
    const capital = +form.capital || 0
    const tasaFrac = (+form.tasa || 0) / 100
    const plazo = +form.plazo_dias || 0
    if (capital <= 0 || tasaFrac <= 0 || plazo <= 0) return null
    return computePf(
      {
        capital, tasa: tasaFrac, rate_type: form.rate_type,
        fecha_inicio: form.fecha_inicio, plazo_dias: plazo,
        modalidad: form.modalidad, pago_frecuencia_meses: form.pago_frecuencia_meses,
      },
      form.fecha_inicio,
    )
  }, [form.capital, form.tasa, form.rate_type, form.plazo_dias, form.fecha_inicio, form.modalidad, form.pago_frecuencia_meses])

  const sign = form.moneda === 'USD' ? 'US$' : '$'
  const money = (n) => sign + Math.round(n).toLocaleString('es-AR')
  const vencimiento = addDays(form.fecha_inicio, form.plazo_dias)

  async function save() {
    const capital = +form.capital, tasa = (+form.tasa) / 100, plazo = +form.plazo_dias
    if (!form.banco.trim()) { setStep('bank'); return toast.push('Elegí el banco.', { type: 'warn' }) }
    if (!(capital > 0)) return toast.push('Poné el capital.', { type: 'warn' })
    if (!(tasa > 0)) return toast.push('Poné la tasa anual.', { type: 'warn' })
    if (!(plazo > 0)) return toast.push('Poné el plazo en días.', { type: 'warn' })
    setSaving(true)
    try {
      await api.post('/plazos-fijos', {
        banco: form.banco.trim(), capital, moneda: form.moneda, tasa,
        rate_type: form.rate_type, fecha_inicio: form.fecha_inicio,
        plazo_dias: plazo, renovacion_auto: form.renovacion_auto,
        modalidad: form.modalidad,
        pago_frecuencia_meses: form.modalidad === 'periodico' ? +form.pago_frecuencia_meses : null,
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
      <div className="bg-white dark:bg-bg-1 border border-line rounded-t-2xl sm:rounded w-full max-w-lg shadow-2xl max-h-[92vh] sm:max-h-[85vh] flex flex-col" onClick={e => e.stopPropagation()}>
        <div className="flex items-start gap-3 px-5 py-4 border-b border-line flex-shrink-0">
          {step === 'form' ? (
            <button onClick={() => setStep('bank')} className="-ml-2 p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2 transition-colors" aria-label="Volver">
              <ArrowLeft size={16} strokeWidth={1.75} aria-hidden="true" />
            </button>
          ) : (
            <Landmark size={18} className="text-rendi-accent mt-1 flex-shrink-0" aria-hidden="true" />
          )}
          <div className="flex-1 min-w-0">
            <p className="eyebrow mb-1">Paso {step === 'bank' ? 1 : 2} de 2</p>
            <h2 className="text-lg font-semibold text-ink-0 leading-tight">
              {step === 'bank' ? 'Elegí el banco' : 'Datos del plazo fijo'}
            </h2>
            <p className="text-xs text-ink-2 mt-0.5">
              {step === 'bank' ? 'Buscá tu banco — te traemos su tasa de hoy.' : 'Capital, tasa y plazo.'}
            </p>
          </div>
          <button onClick={onClose} className="-mr-2 p-2 rounded-sm text-ink-2 hover:text-ink-0 hover:bg-bg-2 transition-colors" aria-label="Cerrar">
            <X size={16} strokeWidth={1.75} aria-hidden="true" />
          </button>
        </div>

        {step === 'bank' ? (
          <BankPicker banks={banks} onPick={pickBank} onManual={goManual} />
        ) : (
          <>
            <div className="overflow-y-auto flex-1 p-5 space-y-3">
              {/* banco: chip si vino de la lista, input si es carga manual */}
              {manual ? (
                <div>
                  <label className="block text-xs text-ink-3 mb-1">Banco / entidad</label>
                  <input
                    type="text"
                    className={inputClass}
                    value={form.banco}
                    onChange={e => set('banco', e.target.value)}
                    placeholder="Nombre del banco"
                    autoFocus
                  />
                </div>
              ) : (
                <div className="flex items-center gap-2.5 bg-bg-2 border border-line rounded-md px-3 py-2">
                  <BankLogo logo={form.logo} name={form.banco} size={28} />
                  <span className="text-sm font-medium text-ink-0 flex-1 truncate">{prettyBank(form.banco)}</span>
                  <button onClick={() => setStep('bank')} className="text-xs text-rendi-accent hover:underline flex-shrink-0">Cambiar</button>
                </div>
              )}

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
                  <div className="flex items-center justify-between mb-1 gap-2">
                    <label className="text-xs text-ink-3">{plazoMode === 'dias' ? 'Plazo (días)' : 'Vencimiento'}</label>
                    <div className="flex rounded-sm overflow-hidden border border-line-2">
                      {[['dias', 'Días'], ['fecha', 'Fecha']].map(([m, lbl]) => (
                        <button key={m} type="button" onClick={() => setPlazoMode(m)}
                          className={`px-1.5 py-0.5 text-[10px] transition ${plazoMode === m ? 'bg-rendi-accent text-white' : 'bg-bg-2 text-ink-3 hover:text-ink-1'}`}>
                          {lbl}
                        </button>
                      ))}
                    </div>
                  </div>
                  {plazoMode === 'dias' ? (
                    <input type="number" inputMode="numeric" className={inputClass} value={form.plazo_dias} onChange={e => set('plazo_dias', e.target.value)} placeholder="30" />
                  ) : (
                    <input type="date" className={inputClass} value={vencimiento} min={form.fecha_inicio}
                      onChange={e => set('plazo_dias', Math.max(0, daysBetween(form.fecha_inicio, e.target.value)))} />
                  )}
                </div>
              </div>
              <p className="text-[11px] text-ink-3 -mt-1.5 leading-relaxed">
                {plazoMode === 'dias' ? (
                  <>El plazo es cuántos días dejás el dinero hasta el vencimiento.{form.plazo_dias > 0 && form.fecha_inicio ? <> Vence el <span className="text-ink-1 font-medium">{vencimiento}</span>.</> : null}</>
                ) : (
                  form.plazo_dias > 0 ? <>Son <span className="text-ink-1 font-medium">{form.plazo_dias} días</span> desde el inicio.</> : 'Elegí la fecha de vencimiento.'
                )}
              </p>

              <label className="flex items-center gap-2 text-sm text-ink-1 cursor-pointer">
                <input type="checkbox" checked={form.renovacion_auto} onChange={e => set('renovacion_auto', e.target.checked)} />
                Renovación automática
              </label>

              {/* Modalidad de interés */}
              <div>
                <label className="block text-xs text-ink-3 mb-1">Modalidad de interés</label>
                <div className="flex rounded-md overflow-hidden border border-line-2">
                  {[['vencimiento', 'Al vencimiento'], ['periodico', 'Capitaliza periódico']].map(([m, lbl]) => (
                    <button key={m} type="button" onClick={() => set('modalidad', m)}
                      className={`flex-1 py-2 text-xs transition ${form.modalidad === m ? 'bg-rendi-accent text-white' : 'bg-bg-2 text-ink-2 hover:text-ink-0'}`}>
                      {lbl}
                    </button>
                  ))}
                </div>
                {form.modalidad === 'periodico' && (
                  <div className="mt-2">
                    <label className="block text-[11px] text-ink-3 mb-1">Cada cuánto capitaliza</label>
                    <div className="flex rounded-md overflow-hidden border border-line-2">
                      {[[1, 'Mensual'], [3, 'Trimestral'], [6, 'Semestral']].map(([m, lbl]) => (
                        <button key={m} type="button" onClick={() => set('pago_frecuencia_meses', m)}
                          className={`flex-1 py-1.5 text-[11px] transition ${+form.pago_frecuencia_meses === m ? 'bg-rendi-accent/80 text-white' : 'bg-bg-2 text-ink-3 hover:text-ink-1'}`}>
                          {lbl}
                        </button>
                      ))}
                    </div>
                    <p className="text-[11px] text-ink-3 mt-1">El interés se reinvierte cada período (compone).</p>
                  </div>
                )}
              </div>

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
                {saving ? 'Guardando…' : 'Agregar plazo fijo'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
