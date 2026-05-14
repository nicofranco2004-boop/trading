// Config — settings como tablero operativo (V2 audit pattern).
// ════════════════════════════════════════════════════════════════════════════
// Estructura:
//   1. PageHeader operativo (eyebrow "Configuración / Workspace" + título corto)
//   2. KPI strip de FX rates (4 cells: Blue / MEP / CCL / Cripto) con dot live
//   3. Status row "FUENTE · dolarapi.com · SYNC HH:MM"
//   4. Grid 2 col: Brokers conectados (tabla densa) | Datos del workspace (key-value)
//   5. Grid 2 col: Cambiar contraseña | Datos / Importaciones (Sistema)

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, Pencil, RefreshCw, Lock, Upload, History, KeyRound } from 'lucide-react'
import { api } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import Pill from '../components/Pill'
import Eyebrow from '../components/Eyebrow'
import ImportWizard from '../components/import/ImportWizard'

const DOLAR_REFRESH_MS = 600_000 // 10 min

// ─── Helpers ─────────────────────────────────────────────────────────────────

function fmtArs(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString('es-AR', { maximumFractionDigits: 1 })
}

function fmtTime(d) {
  if (!d) return '—'
  return d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })
}

function memberSince(createdAt) {
  if (!createdAt) return '—'
  try {
    const d = new Date(createdAt)
    if (isNaN(d.getTime())) return '—'
    const months = Math.max(1, Math.round((Date.now() - d.getTime()) / (1000 * 60 * 60 * 24 * 30)))
    return `${d.toLocaleDateString('es-AR', { day: '2-digit', month: 'short', year: 'numeric' })} · ${months} ${months === 1 ? 'mes' : 'meses'}`
  } catch {
    return '—'
  }
}

// ─── FX KPI cell ─────────────────────────────────────────────────────────────

function FxCell({ first, label, value, compra, venta, source, accent }) {
  return (
    <div className={`px-4 py-3 flex-1 min-w-[160px] ${first ? '' : 'border-l border-line/50'}`}>
      <div className="text-[10px] font-mono uppercase tracking-label text-ink-3 leading-none flex items-center gap-1.5">
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${accent === 'cyan' ? 'bg-data-cyan' : 'bg-rendi-pos'}`} aria-hidden="true" />
        {label}
      </div>
      <div className="mt-2 font-medium tabular num leading-none text-2xl tracking-tight text-ink-0">
        {value != null ? fmtArs(value) : '—'}
      </div>
      <div className="text-[10px] font-mono text-ink-3 mt-1.5 leading-none truncate uppercase tracking-caps">
        {compra != null && venta != null ? `compra ${fmtArs(compra)} · venta ${fmtArs(venta)}` : (source || '—')}
      </div>
    </div>
  )
}

// ─── Workspace key-value row ─────────────────────────────────────────────────

function MetaRow({ label, children, last }) {
  return (
    <div className={`flex items-baseline gap-3 px-4 py-2.5 ${last ? '' : 'border-b border-line/40'}`}>
      <span className="text-[10px] font-mono uppercase tracking-label text-ink-3 min-w-[120px]">{label}</span>
      <span className="text-sm text-ink-1 flex-1 truncate">{children}</span>
    </div>
  )
}

// ─── Currency tone helper ────────────────────────────────────────────────────

function currencyTone(c) {
  switch (c) {
    case 'ARS':  return 'info'   // azul violáceo
    case 'USD':  return 'signal' // verde
    case 'USDT': return 'info'   // cyan-ish via info
    default:     return 'default'
  }
}

// ─── Página ──────────────────────────────────────────────────────────────────

export default function Config() {
  const { user } = useAuth()
  const [brokers, setBrokers] = useState([])
  const [dolar, setDolar] = useState(null)
  const [newBroker, setNewBroker] = useState({ name: '', currency: 'USDT' })
  const [editingBroker, setEditingBroker] = useState(null)
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' })
  const [pwState, setPwState] = useState({ loading: false, error: '', success: '' })
  const [showImport, setShowImport] = useState(false)
  const [showAddBroker, setShowAddBroker] = useState(false)

  useEffect(() => {
    loadDolar()
    loadBrokers()
    const id = setInterval(loadDolar, DOLAR_REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  async function loadDolar() {
    try { setDolar(await api.get('/dolar')) } catch {}
  }

  async function loadBrokers() {
    setBrokers(await api.get('/brokers'))
  }

  async function addBroker(e) {
    e.preventDefault()
    if (!newBroker.name.trim()) return
    await api.post('/brokers', { name: newBroker.name.trim(), currency: newBroker.currency })
    setNewBroker({ name: '', currency: 'USDT' })
    setShowAddBroker(false)
    loadBrokers()
  }

  async function saveEditBroker(e) {
    e.preventDefault()
    await api.put(`/brokers/${editingBroker.id}`, { name: editingBroker.name, currency: editingBroker.currency })
    setEditingBroker(null)
    loadBrokers()
  }

  async function deleteBroker(id) {
    if (!confirm('¿Eliminar este broker? Las posiciones asociadas quedarán huérfanas y deberás reasignarlas manualmente.')) return
    await api.delete(`/brokers/${id}`)
    loadBrokers()
  }

  async function changePassword(e) {
    e.preventDefault()
    setPwState({ loading: true, error: '', success: '' })
    if (pwForm.next.length < 10) {
      setPwState({ loading: false, error: 'La nueva contraseña debe tener al menos 10 caracteres.', success: '' })
      return
    }
    if (pwForm.next !== pwForm.confirm) {
      setPwState({ loading: false, error: 'Las contraseñas no coinciden.', success: '' })
      return
    }
    try {
      const res = await api.post('/auth/change-password', {
        current_password: pwForm.current,
        new_password: pwForm.next,
      })
      if (res.token) localStorage.setItem('rendi_token', res.token)
      setPwForm({ current: '', next: '', confirm: '' })
      setPwState({ loading: false, error: '', success: 'Contraseña actualizada correctamente.' })
    } catch (err) {
      setPwState({ loading: false, error: err.message, success: '' })
    }
  }

  const fetchedAt = dolar?.fetched_at ? new Date(dolar.fetched_at) : null
  const labelClass = 'block text-[10px] font-mono uppercase tracking-label text-ink-3 mb-1'
  const inputClass = 'w-full bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2 font-mono'
  const selectClass = 'bg-bg-2 border border-line rounded-sm px-2.5 py-1.5 text-sm text-ink-0 focus:outline-none focus:border-ink-2 font-mono'

  return (
    <div className="page-shell-wide">
      <PageHeader
        eyebrow="Configuración / Workspace"
        title="Settings"
        meta={fetchedAt ? `FX sync · ${fmtTime(fetchedAt)}` : null}
      />

      {/* ── KPI strip · FX rates ─────────────────────────────────────────── */}
      <div className="border border-line rounded bg-bg-1 flex flex-wrap mb-2">
        <FxCell
          first
          label="TC Blue · ARS/USD"
          value={dolar?.blue?.venta}
          compra={dolar?.blue?.compra}
          venta={dolar?.blue?.venta}
        />
        <FxCell
          label="TC MEP · ARS/USD"
          value={dolar?.mep?.venta}
          compra={dolar?.mep?.compra}
          venta={dolar?.mep?.venta}
        />
        <FxCell
          label="TC CCL · ARS/USD"
          value={dolar?.ccl?.venta}
          compra={dolar?.ccl?.compra}
          venta={dolar?.ccl?.venta}
        />
        <FxCell
          label="TC Cripto · ARS/USDT"
          value={dolar?.cripto?.venta}
          compra={dolar?.cripto?.compra}
          venta={dolar?.cripto?.venta}
          source="crypto · Binance"
          accent="cyan"
        />
      </div>

      <div className="flex items-center gap-3 mb-6 text-[10px] font-mono uppercase tracking-caps text-ink-3">
        <span>Fuente · dolarapi.com</span>
        <span>·</span>
        <span>refresh cada 10min</span>
        <span>·</span>
        <span>última sync <span className="text-ink-2">{fmtTime(fetchedAt)}</span></span>
        <button
          type="button"
          onClick={loadDolar}
          className="ml-auto inline-flex items-center gap-1 text-data-cyan hover:text-ink-0 transition-colors"
          title="Actualizar cotización"
        >
          <RefreshCw size={11} strokeWidth={1.75} />
          Forzar actualización
        </button>
      </div>

      {/* ── Grid: Brokers | Workspace info ───────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-4 mb-4">
        {/* Brokers conectados */}
        <Panel padding="none">
          <header className="flex items-center justify-between px-4 py-2.5 border-b border-line">
            <div className="flex items-center gap-2">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-rendi-pos" aria-hidden="true" />
              <Eyebrow>Brokers conectados</Eyebrow>
              <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3 ml-1">
                / {brokers.length} {brokers.length === 1 ? 'activo' : 'activos'}
              </span>
            </div>
            <button
              onClick={() => setShowAddBroker(true)}
              className="inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-caps bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-2 py-1 rounded-sm transition-colors"
            >
              <Plus size={10} strokeWidth={2.25} /> Conectar
            </button>
          </header>

          {brokers.length === 0 ? (
            <div className="p-6 text-center text-ink-3 text-sm">
              No tenés brokers configurados. Conectá uno para empezar a registrar posiciones.
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-line/60 text-[10px] font-mono uppercase tracking-label text-ink-3">
                  <th className="text-left px-4 py-2 font-medium">Broker</th>
                  <th className="text-left px-3 py-2 font-medium">Moneda</th>
                  <th className="text-left px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 w-[60px]"></th>
                </tr>
              </thead>
              <tbody>
                {brokers.map(b => (
                  <tr key={b.id} className="border-b border-line/30 hover:bg-bg-2/40 transition-colors">
                    {editingBroker?.id === b.id ? (
                      <td colSpan={4} className="px-4 py-3 bg-bg-2/40">
                        <form onSubmit={saveEditBroker} className="flex flex-wrap items-end gap-2">
                          <div className="flex-1 min-w-[140px]">
                            <label className={labelClass}>Nombre</label>
                            <input
                              value={editingBroker.name}
                              onChange={e => setEditingBroker(eb => ({ ...eb, name: e.target.value }))}
                              className={inputClass}
                              autoFocus
                            />
                          </div>
                          <div>
                            <label className={labelClass}>Moneda</label>
                            <select
                              value={editingBroker.currency}
                              onChange={e => setEditingBroker(eb => ({ ...eb, currency: e.target.value }))}
                              className={selectClass}
                            >
                              <option value="USDT">USDT</option>
                              <option value="USD">USD</option>
                              <option value="ARS">ARS</option>
                            </select>
                          </div>
                          <div className="flex gap-1">
                            <button type="submit" className="text-[10px] font-mono uppercase tracking-caps bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 px-2 py-1.5 rounded-sm transition-colors">
                              Guardar
                            </button>
                            <button type="button" onClick={() => setEditingBroker(null)} className="text-[10px] font-mono uppercase tracking-caps text-ink-3 hover:text-ink-0 px-2 py-1.5 transition-colors">
                              Cancelar
                            </button>
                          </div>
                        </form>
                      </td>
                    ) : (
                      <>
                        <td className="px-4 py-2.5">
                          <div className="text-sm font-medium text-ink-0">{b.name}</div>
                        </td>
                        <td className="px-3 py-2.5">
                          <Pill tone={currencyTone(b.currency)}>{b.currency}</Pill>
                        </td>
                        <td className="px-3 py-2.5">
                          <Pill tone="signal" dot>Conectado</Pill>
                        </td>
                        <td className="px-3 py-2.5">
                          <div className="flex gap-2 justify-end">
                            <button onClick={() => setEditingBroker({ ...b })} className="text-ink-3 hover:text-ink-0 transition-colors" title="Editar broker" aria-label={`Editar broker ${b.name}`}>
                              <Pencil size={13} strokeWidth={1.75} aria-hidden="true" />
                            </button>
                            <button onClick={() => deleteBroker(b.id)} className="text-ink-3 hover:text-rendi-neg transition-colors" title="Eliminar broker" aria-label={`Eliminar broker ${b.name}`}>
                              <Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />
                            </button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                ))}
                {showAddBroker && (
                  <tr className="border-b border-line/30 bg-bg-2/40">
                    <td colSpan={4} className="px-4 py-3">
                      <form onSubmit={addBroker} className="flex flex-wrap items-end gap-2">
                        <div className="flex-1 min-w-[180px]">
                          <label className={labelClass}>Nombre del broker</label>
                          <input
                            value={newBroker.name}
                            onChange={e => setNewBroker(b => ({ ...b, name: e.target.value }))}
                            placeholder="Ej.: Binance, Cocos, IOL…"
                            className={inputClass}
                            autoFocus
                          />
                        </div>
                        <div>
                          <label className={labelClass}>Moneda</label>
                          <select
                            value={newBroker.currency}
                            onChange={e => setNewBroker(b => ({ ...b, currency: e.target.value }))}
                            className={selectClass}
                          >
                            <option value="USDT">USDT</option>
                            <option value="USD">USD</option>
                            <option value="ARS">ARS</option>
                          </select>
                        </div>
                        <div className="flex gap-1">
                          <button type="submit" className="text-[10px] font-mono uppercase tracking-caps bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 px-2.5 py-1.5 rounded-sm transition-colors">
                            <Plus size={10} strokeWidth={2.25} className="inline mr-1" /> Agregar
                          </button>
                          <button type="button" onClick={() => setShowAddBroker(false)} className="text-[10px] font-mono uppercase tracking-caps text-ink-3 hover:text-ink-0 px-2 py-1.5 transition-colors">
                            Cancelar
                          </button>
                        </div>
                      </form>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}

          <div className="px-4 py-2.5 border-t border-line flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-mono uppercase tracking-caps text-ink-3">
            <span><b className="text-data-cyan">USDT</b> · exchanges crypto (Binance)</span>
            <span><b className="text-ink-2">USD</b> · brokers en dólares (IBKR, Schwab)</span>
            <span><b className="text-ink-2">ARS</b> · brokers en pesos · convertidos al blue (Cocos, IOL)</span>
          </div>
        </Panel>

        {/* Workspace info */}
        <Panel padding="none">
          <header className="flex items-center gap-2 px-4 py-2.5 border-b border-line">
            <span
              className="inline-block w-1.5 h-1.5 rounded-full bg-data-cyan"
              style={{ boxShadow: '0 0 6px rgba(70,198,224,0.6)' }}
              aria-hidden="true"
            />
            <Eyebrow>Datos del workspace</Eyebrow>
          </header>
          <div>
            <MetaRow label="Usuario">
              <span className="font-medium text-ink-0">{user?.email || user?.name || '—'}</span>
              {user?.is_admin && (
                <Pill tone="info" className="ml-2">Admin</Pill>
              )}
            </MetaRow>
            <MetaRow label="Workspace">
              <span className="font-medium text-ink-0">
                {user?.email ? user.email.split('@')[0] : (user?.name || '—')}
              </span>
              <span className="text-[10px] font-mono text-ink-3 ml-2">· personal</span>
            </MetaRow>
            <MetaRow label="Brokers">
              <span className="font-mono tabular">
                {brokers.length} {brokers.length === 1 ? 'conectado' : 'conectados'}
              </span>
            </MetaRow>
            <MetaRow label="Plan">
              <Pill tone="signal">Free</Pill>
            </MetaRow>
            <MetaRow label="Miembro desde">
              <span className="font-mono tabular text-xs">{memberSince(user?.created_at)}</span>
            </MetaRow>
            <MetaRow label="ID instancia" last>
              <span className="font-mono tabular text-[11px] text-ink-3">
                rnd-{user?.id || '—'}
              </span>
            </MetaRow>
          </div>
        </Panel>
      </div>

      {/* ── Grid: Datos / Importaciones | Cambiar contraseña ─────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Datos / Importaciones */}
        <Panel padding="none">
          <header className="flex items-center gap-2 px-4 py-2.5 border-b border-line">
            <span
              className="inline-block w-1.5 h-1.5 rounded-full bg-data-cyan"
              style={{ boxShadow: '0 0 6px rgba(70,198,224,0.6)' }}
              aria-hidden="true"
            />
            <Eyebrow>Datos / Importaciones</Eyebrow>
          </header>
          <div className="p-4 space-y-3">
            <p className="text-xs text-ink-2 leading-relaxed">
              Subí un CSV con tu historial de operaciones para reconstruir el portfolio sin cargar todo a mano. Soporta exports de cualquier broker — vas a poder mapear las columnas y previsualizar antes de confirmar.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setShowImport(true)}
                className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-2.5 py-1.5 rounded-sm transition-colors"
              >
                <Upload size={12} strokeWidth={2} /> Importar CSV
              </button>
              <Link
                to="/imports"
                className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps text-ink-2 hover:text-ink-0 border border-line bg-bg-2 hover:bg-bg-3 px-2.5 py-1.5 rounded-sm transition-colors"
              >
                <History size={12} strokeWidth={1.75} /> Ver historial
              </Link>
            </div>
          </div>
        </Panel>

        {/* Cambiar contraseña */}
        <Panel padding="none">
          <header className="flex items-center gap-2 px-4 py-2.5 border-b border-line">
            <span
              className="inline-block w-1.5 h-1.5 rounded-full bg-data-cyan"
              style={{ boxShadow: '0 0 6px rgba(70,198,224,0.6)' }}
              aria-hidden="true"
            />
            <Eyebrow>Cambiar contraseña</Eyebrow>
            <KeyRound size={11} strokeWidth={1.75} className="text-ink-3" aria-hidden="true" />
          </header>
          <form onSubmit={changePassword} className="p-4 space-y-3">
            <div>
              <label className={labelClass}>Contraseña actual</label>
              <input
                type="password"
                autoComplete="current-password"
                value={pwForm.current}
                onChange={e => setPwForm(f => ({ ...f, current: e.target.value }))}
                className={inputClass}
                placeholder="••••••••••"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelClass}>Nueva</label>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={pwForm.next}
                  onChange={e => setPwForm(f => ({ ...f, next: e.target.value }))}
                  className={inputClass}
                  minLength={10}
                  required
                />
              </div>
              <div>
                <label className={labelClass}>Confirmar</label>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={pwForm.confirm}
                  onChange={e => setPwForm(f => ({ ...f, confirm: e.target.value }))}
                  className={inputClass}
                  minLength={10}
                  required
                />
              </div>
            </div>
            <p className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
              Mínimo 10 caracteres · al actualizar se cierran las sesiones activas en otros dispositivos.
            </p>
            {pwState.error && (
              <p className="text-[11px] font-mono text-rendi-neg">{pwState.error}</p>
            )}
            {pwState.success && (
              <p className="text-[11px] font-mono text-rendi-pos">{pwState.success}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => { setPwForm({ current: '', next: '', confirm: '' }); setPwState({ loading: false, error: '', success: '' }) }}
                className="text-[11px] font-mono uppercase tracking-caps text-ink-3 hover:text-ink-0 px-3 py-1.5 transition-colors"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={pwState.loading}
                className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-3 py-1.5 rounded-sm transition-colors disabled:opacity-50"
              >
                <Lock size={11} strokeWidth={1.75} />
                {pwState.loading ? 'Guardando…' : 'Cambiar contraseña'}
              </button>
            </div>
          </form>
        </Panel>
      </div>

      {showImport && (
        <ImportWizard
          onClose={() => setShowImport(false)}
          onConfirmed={() => { /* Config no muestra portfolio — no refresh */ }}
        />
      )}
    </div>
  )
}
