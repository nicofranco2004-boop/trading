// GroupsBar — grupos de clientes del asesor: filtros GUARDADOS y dinámicos.
// ═══════════════════════════════════════════════════════════════════════════
// Idea de Nico: "un grupo con todos los que tengan Amazon / más de 20.000 /
// 30% en liquidez / 30% en acciones argentinas". No son listas congeladas: si
// mañana el cliente compra Amazon, entra solo. Se usan para filtrar el roster
// y de ahí operar/informar en lote sin tildar a nadie a mano.
import { useCallback, useEffect, useState } from 'react'
import { Filter, Plus, Trash2 } from 'lucide-react'
import Modal from '../Modal'
import { api } from '../../utils/api'
import { useToast } from '../Toast'

const inputCls = 'w-full text-sm bg-bg-2 border border-line rounded-sm px-3 py-2 text-ink-0 placeholder:text-ink-3 focus:border-rendi-accent/50 outline-none'

// Coma o punto (formato argentino).
function num(v) {
  let s = String(v == null ? '' : v).trim()
  if (!s) return null
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.')
  const n = parseFloat(s.replace(/[^\d.]/g, ''))
  return Number.isFinite(n) && n > 0 ? n : null
}

const EMPTY = { name: '', has_asset: '', aum_min: '', aum_max: '',
                cash_pct_min: '', klass: '', class_pct_min: '', losing: false }

export default function GroupsBar({ activeId, onPick }) {
  const toast = useToast()
  const [groups, setGroups] = useState([])
  const [classes, setClasses] = useState([])
  const [modal, setModal] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api.get('/advisor/groups')
      .then(d => { setGroups(d.groups || []); setClasses(d.classes || []) })
      .catch(() => setGroups([]))
  }, [])
  useEffect(() => { load() }, [load])

  const rulesOf = (f) => ({
    has_asset: f.has_asset.trim().toUpperCase() || undefined,
    aum_min: num(f.aum_min) || undefined,
    aum_max: num(f.aum_max) || undefined,
    cash_pct_min: num(f.cash_pct_min) || undefined,
    class: f.klass || undefined,
    class_pct_min: num(f.class_pct_min) || undefined,
    losing: f.losing || undefined,
  })

  async function doPreview(next) {
    const f = next || form
    const rules = rulesOf(f)
    if (!Object.values(rules).some(v => v !== undefined)) { setPreview(null); return }
    try {
      const r = await api.post('/advisor/groups/preview', { name: f.name || 'x', rules })
      setPreview(r)
    } catch { setPreview(null) }
  }

  async function save() {
    const rules = rulesOf(form)
    if (!form.name.trim()) { toast.push('Poné un nombre al grupo', { type: 'error' }); return }
    if (!Object.values(rules).some(v => v !== undefined)) {
      toast.push('Elegí al menos una condición', { type: 'error' }); return
    }
    setBusy(true)
    try {
      await api.post('/advisor/groups', { name: form.name.trim(), rules })
      toast.push('Grupo creado')
      setModal(false); setForm(EMPTY); setPreview(null)
      load()
    } catch (e) {
      toast.push(e?.message || 'No se pudo crear el grupo', { type: 'error' })
    } finally { setBusy(false) }
  }

  async function remove(g) {
    if (!window.confirm(`¿Borrar el grupo "${g.name}"? Tus clientes no se tocan.`)) return
    try {
      await api.delete(`/advisor/groups/${g.id}`)
      if (activeId === g.id) onPick?.(null)
      load()
    } catch { toast.push('No se pudo borrar', { type: 'error' }) }
  }

  const chip = (on) => `inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-full border transition-colors ${
    on ? 'border-rendi-accent bg-rendi-accent/10 text-rendi-accent' : 'border-line text-ink-2 hover:border-line/80'}`

  return (
    <>
      <div className="flex items-center gap-2 flex-wrap mb-3">
        <Filter size={14} className="text-ink-3" aria-hidden="true" />
        <button type="button" className={chip(!activeId)} onClick={() => onPick?.(null)}>
          Todos
        </button>
        {groups.map(g => (
          <span key={g.id} className="inline-flex items-center">
            <button type="button" className={chip(activeId === g.id)}
              title={g.description}
              onClick={() => onPick?.(activeId === g.id ? null : g)}>
              {g.name}
              <span className="text-[10px] opacity-70">{g.count ?? 0}</span>
            </button>
            {activeId === g.id && (
              <button type="button" onClick={() => remove(g)} aria-label={`Borrar grupo ${g.name}`}
                className="ml-1 text-ink-3 hover:text-rendi-neg p-1">
                <Trash2 size={12} />
              </button>
            )}
          </span>
        ))}
        <button type="button" onClick={() => { setForm(EMPTY); setPreview(null); setModal(true) }}
          className="inline-flex items-center gap-1 text-xs text-rendi-accent hover:underline px-1">
          <Plus size={13} /> Nuevo grupo
        </button>
      </div>

      {modal && (
        <Modal title="Nuevo grupo de clientes" onClose={() => setModal(false)}>
          <div className="space-y-3">
            <p className="text-xs text-ink-3">
              El grupo se arma solo con las condiciones que elijas: si mañana un cliente
              cumple, entra; si deja de cumplir, sale.
            </p>
            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder='Nombre. Ej: "Los de Amazon"' className={inputCls} maxLength={60} />

            <div className="pt-1 space-y-2">
              <label className="block text-xs text-ink-2">Tienen este activo</label>
              <input value={form.has_asset}
                onChange={e => { const v = { ...form, has_asset: e.target.value.toUpperCase() }; setForm(v); doPreview(v) }}
                placeholder="Ej: AMZN" className={inputCls} />

              <label className="block text-xs text-ink-2 pt-1">Tamaño de la cartera (US$)</label>
              <div className="flex gap-2">
                <input value={form.aum_min} placeholder="Más de…" className={inputCls}
                  onChange={e => { const v = { ...form, aum_min: e.target.value }; setForm(v); doPreview(v) }} />
                <input value={form.aum_max} placeholder="Menos de…" className={inputCls}
                  onChange={e => { const v = { ...form, aum_max: e.target.value }; setForm(v); doPreview(v) }} />
              </div>

              <label className="block text-xs text-ink-2 pt-1">Sin invertir (liquidez) — % o más</label>
              <input value={form.cash_pct_min} placeholder="Ej: 30" className={inputCls}
                onChange={e => { const v = { ...form, cash_pct_min: e.target.value }; setForm(v); doPreview(v) }} />

              <label className="block text-xs text-ink-2 pt-1">Concentración en un tipo de activo</label>
              <div className="flex gap-2">
                <select value={form.klass} className={inputCls}
                  onChange={e => { const v = { ...form, klass: e.target.value }; setForm(v); doPreview(v) }}>
                  <option value="">— elegir —</option>
                  {classes.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
                </select>
                <input value={form.class_pct_min} placeholder="% o más" className={inputCls}
                  onChange={e => { const v = { ...form, class_pct_min: e.target.value }; setForm(v); doPreview(v) }} />
              </div>

              <label className="flex items-center gap-2 text-xs text-ink-2 pt-1 cursor-pointer">
                <input type="checkbox" checked={form.losing}
                  onChange={e => { const v = { ...form, losing: e.target.checked }; setForm(v); doPreview(v) }} />
                Están perdiendo (valen menos de lo que aportaron)
              </label>
            </div>

            {preview && (
              <div className="rounded-sm border border-line bg-bg-2/50 px-3 py-2">
                <p className="text-xs text-ink-1">
                  {preview.clients.length === 0
                    ? 'Ningún cliente cumple estas condiciones por ahora.'
                    : `Entran ${preview.clients.length} cliente${preview.clients.length === 1 ? '' : 's'}: `}
                  <span className="text-ink-2">
                    {preview.clients.slice(0, 6).map(c => c.label).join(', ')}
                    {preview.clients.length > 6 ? ` +${preview.clients.length - 6}` : ''}
                  </span>
                </p>
              </div>
            )}

            <div className="flex gap-2 pt-1">
              <button type="button" onClick={save} disabled={busy}
                className="text-xs bg-rendi-accent text-white px-4 py-2 rounded-sm font-medium disabled:opacity-50">
                {busy ? 'Creando…' : 'Crear grupo'}
              </button>
              <button type="button" onClick={() => setModal(false)}
                className="text-xs text-ink-3 hover:text-ink-1 px-3 py-2">Cancelar</button>
            </div>
          </div>
        </Modal>
      )}
    </>
  )
}
