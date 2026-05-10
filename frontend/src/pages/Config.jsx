import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, Pencil, RefreshCw, Lock, Upload, History } from 'lucide-react'
import { api } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import PageHeader from '../components/PageHeader'
import ImportWizard from '../components/import/ImportWizard'

const DOLAR_REFRESH_MS = 600_000 // 10 min

export default function Config() {
  const { user } = useAuth()
  const [brokers, setBrokers] = useState([])
  const [dolar, setDolar] = useState(null)
  const [newBroker, setNewBroker] = useState({ name: '', currency: 'USDT' })
  const [editingBroker, setEditingBroker] = useState(null)
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' })
  const [pwState, setPwState] = useState({ loading: false, error: '', success: '' })
  const [showImport, setShowImport] = useState(false)

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
      // Backend devuelve token nuevo (con pca actualizado) — guardarlo para no perder sesión
      if (res.token) localStorage.setItem('rendi_token', res.token)
      setPwForm({ current: '', next: '', confirm: '' })
      setPwState({ loading: false, error: '', success: 'Contraseña actualizada correctamente.' })
    } catch (err) {
      setPwState({ loading: false, error: err.message, success: '' })
    }
  }

  const inputClass = 'w-full bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-2 text-slate-900 dark:text-slate-200 text-sm'
  const selectClass = 'bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-2 text-slate-900 dark:text-slate-200 text-sm'

  const fetchedAt = dolar?.fetched_at ? new Date(dolar.fetched_at) : null

  return (
    <div className="page-shell max-w-2xl space-y-6">
      <PageHeader title="Configuración" subtitle="Gestioná tus brokers, tipos de cambio y datos de cuenta." />

      {/* Tipos de cambio (auto) */}
      <div className="bg-white dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/50 shadow-sm dark:shadow-none rounded-xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-slate-800 dark:text-slate-200">Tipos de cambio</h2>
          <button
            type="button"
            onClick={loadDolar}
            className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 px-2 py-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700/40"
            title="Actualizar cotización"
          >
            <RefreshCw size={12} /> Actualizar
          </button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-slate-50 dark:bg-slate-700/40 rounded-lg px-4 py-3">
            <div className="text-xs text-slate-500 dark:text-slate-400">TC Blue (ARS/USD)</div>
            <div className="text-2xl font-bold text-slate-900 dark:text-slate-100">{dolar?.blue?.venta ?? '—'}</div>
            <div className="text-xs text-slate-400 dark:text-slate-500 mt-1">Compra {dolar?.blue?.compra ?? '—'}</div>
          </div>
          <div className="bg-slate-50 dark:bg-slate-700/40 rounded-lg px-4 py-3">
            <div className="text-xs text-slate-500 dark:text-slate-400">TC MEP (ARS/USD)</div>
            <div className="text-2xl font-bold text-slate-900 dark:text-slate-100">{dolar?.mep?.venta ?? '—'}</div>
            <div className="text-xs text-slate-400 dark:text-slate-500 mt-1">Compra {dolar?.mep?.compra ?? '—'}</div>
          </div>
        </div>
        <p className="text-xs text-slate-400 dark:text-slate-500 mt-3">
          Fuente: dolarapi.com · Actualización automática cada 10 minutos{fetchedAt ? ` · Última actualización ${fetchedAt.toLocaleTimeString()}` : ''}
        </p>
      </div>

      {/* Brokers */}
      <div className="bg-white dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/50 shadow-sm dark:shadow-none rounded-xl p-6">
        <h2 className="font-semibold text-slate-800 dark:text-slate-200 mb-4">Brokers</h2>

        {brokers.length > 0 && (
          <div className="space-y-2 mb-4">
            {brokers.map(b => (
              <div key={b.id}>
                {editingBroker?.id === b.id ? (
                  <form onSubmit={saveEditBroker} className="flex gap-2 items-center">
                    <input
                      value={editingBroker.name}
                      onChange={e => setEditingBroker(eb => ({ ...eb, name: e.target.value }))}
                      className="flex-1 bg-slate-50 dark:bg-slate-700 border border-slate-300 dark:border-slate-600 rounded-md px-3 py-1.5 text-sm text-slate-900 dark:text-slate-200"
                    />
                    <select
                      value={editingBroker.currency}
                      onChange={e => setEditingBroker(eb => ({ ...eb, currency: e.target.value }))}
                      className={selectClass}
                    >
                      <option value="USDT">USDT</option>
                      <option value="ARS">ARS</option>
                    </select>
                    <button type="submit" className="text-xs bg-blue-600 text-white px-3 py-1.5 rounded-md">OK</button>
                    <button type="button" onClick={() => setEditingBroker(null)} className="text-xs text-slate-400 px-2 py-1.5">✕</button>
                  </form>
                ) : (
                  <div className="flex items-center justify-between bg-slate-50 dark:bg-slate-700/40 rounded-lg px-3 py-2">
                    <div>
                      <span className="text-slate-800 dark:text-slate-200 text-sm font-medium">{b.name}</span>
                      <span className={`ml-2 text-xs px-1.5 py-0.5 rounded font-medium ${
                        b.currency === 'ARS'
                          ? 'bg-violet-500/20 text-violet-600 dark:text-violet-400'
                          : 'bg-blue-500/20 text-blue-600 dark:text-blue-400'
                      }`}>{b.currency}</span>
                    </div>
                    <div className="flex gap-2">
                      <button onClick={() => setEditingBroker({ ...b })} className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200">
                        <Pencil size={13} />
                      </button>
                      <button onClick={() => deleteBroker(b.id)} className="text-slate-400 hover:text-red-500">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <form onSubmit={addBroker} className="flex gap-2 items-end">
          <div className="flex-1">
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Nombre del broker</label>
            <input
              value={newBroker.name}
              onChange={e => setNewBroker(b => ({ ...b, name: e.target.value }))}
              placeholder="Ej.: Binance, Cocos, IOL..."
              className={inputClass}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Moneda</label>
            <select
              value={newBroker.currency}
              onChange={e => setNewBroker(b => ({ ...b, currency: e.target.value }))}
              className={selectClass}
            >
              <option value="USDT">USDT</option>
              <option value="ARS">ARS</option>
            </select>
          </div>
          <button
            type="submit"
            className="flex items-center gap-1 px-3 py-2 bg-blue-600/20 text-blue-600 dark:text-blue-400 hover:bg-blue-600/30 rounded-md text-sm font-medium transition-colors"
          >
            <Plus size={14} /> Agregar
          </button>
        </form>
        <p className="text-xs text-slate-400 dark:text-slate-500 mt-3">
          <span className="text-blue-600 dark:text-blue-400 font-medium">USDT</span> · precios en USD (Binance, exchanges crypto) ·
          <span className="text-violet-600 dark:text-violet-400 font-medium ml-1">ARS</span> · precios en pesos, convertidos a USD según el blue (Cocos, IOL y similares).
        </p>
      </div>

      {/* Importar datos */}
      <div className="bg-white dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/50 shadow-sm dark:shadow-none rounded-xl p-6">
        <h2 className="font-semibold text-slate-800 dark:text-slate-200 mb-1">Importar datos</h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
          Subí un CSV con tu historial de operaciones para reconstruir el portfolio sin cargar todo a mano. Soporta exports de cualquier broker — vas a poder mapear las columnas y previsualizar antes de confirmar.
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => setShowImport(true)}
            className="inline-flex items-center gap-1.5 text-sm bg-rendi-accent text-white hover:bg-rendi-accent/90 px-3 py-2 rounded-md font-semibold transition"
          >
            <Upload size={14} /> Importar CSV
          </button>
          <Link
            to="/imports"
            className="inline-flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-slate-100 px-3 py-2 rounded-md border border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600 transition"
          >
            <History size={14} /> Ver historial de importaciones
          </Link>
        </div>
      </div>

      {/* Cuenta */}
      <div className="bg-white dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/50 shadow-sm dark:shadow-none rounded-xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <Lock size={16} className="text-slate-400" />
          <h2 className="font-semibold text-slate-800 dark:text-slate-200">Cuenta</h2>
        </div>
        {user && (
          <div className="text-sm text-slate-500 dark:text-slate-400 mb-4">
            Sesión: <span className="text-slate-700 dark:text-slate-200 font-medium">{user.email || user.name}</span>
            {user.is_admin && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-rendi-accent/15 text-rendi-accent font-semibold uppercase tracking-wide">admin</span>}
          </div>
        )}
        <form onSubmit={changePassword} className="space-y-3">
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Contraseña actual</label>
            <input type="password" autoComplete="current-password" value={pwForm.current}
              onChange={e => setPwForm(f => ({ ...f, current: e.target.value }))}
              className={inputClass} required />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Nueva contraseña</label>
              <input type="password" autoComplete="new-password" value={pwForm.next}
                onChange={e => setPwForm(f => ({ ...f, next: e.target.value }))}
                className={inputClass} minLength={10} required />
            </div>
            <div>
              <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Confirmar</label>
              <input type="password" autoComplete="new-password" value={pwForm.confirm}
                onChange={e => setPwForm(f => ({ ...f, confirm: e.target.value }))}
                className={inputClass} minLength={10} required />
            </div>
          </div>
          {pwState.error && <p className="text-red-500 text-xs">{pwState.error}</p>}
          {pwState.success && <p className="text-emerald-600 dark:text-emerald-400 text-xs">{pwState.success}</p>}
          <p className="text-xs text-slate-400 dark:text-slate-500">Mínimo 10 caracteres. Al actualizarla, se cierran las sesiones activas en otros dispositivos.</p>
          <button type="submit" disabled={pwState.loading}
            className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-md">
            {pwState.loading ? 'Guardando...' : 'Cambiar contraseña'}
          </button>
        </form>
      </div>

      {showImport && (
        <ImportWizard
          onClose={() => setShowImport(false)}
          onConfirmed={() => { /* sin refresh — Config no muestra portfolio */ }}
        />
      )}
    </div>
  )
}
