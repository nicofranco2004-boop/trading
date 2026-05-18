// Config — settings como tablero operativo (V2 audit pattern).
// ════════════════════════════════════════════════════════════════════════════
// Estructura:
//   1. PageHeader operativo (eyebrow "Configuración / Workspace" + título corto)
//   2. KPI strip de FX rates (4 cells: Blue / MEP / CCL / Cripto) con dot live
//   3. Status row "FUENTE · dolarapi.com · SYNC HH:MM"
//   4. Grid 2 col: Brokers conectados (tabla densa) | Datos del workspace (key-value)
//   5. Grid 2 col: Cambiar contraseña | Datos / Importaciones (Sistema)

import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Plus, Trash2, Pencil, RefreshCw, Lock, Upload, History, KeyRound, Sparkles, Check, Zap } from 'lucide-react'
import { api } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import { track } from '../utils/track'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import Pill from '../components/Pill'
import ImportWizard from '../components/import/ImportWizard'
import UpgradeModal from '../components/plan/UpgradeModal'
import { usePlanFeatures, refreshPlanFeatures } from '../hooks/usePlanFeatures'

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

function FxCell({ first, label, sub, value, compra, venta }) {
  return (
    <div className={`px-4 py-3 flex-1 min-w-[160px] ${first ? '' : 'border-l border-line/50'}`}>
      <div className="text-xs text-ink-3 leading-none flex items-baseline gap-1.5">
        <span className="text-ink-2">{label}</span>
        {sub && <span className="text-[10px] text-ink-3">{sub}</span>}
      </div>
      <div className="mt-2 font-medium tabular num leading-none text-2xl tracking-tight text-ink-0">
        {value != null ? fmtArs(value) : '—'}
      </div>
      <div className="text-[11px] text-ink-3 mt-1.5 leading-none truncate">
        {compra != null && venta != null
          ? <>Compra <span className="font-mono tabular">{fmtArs(compra)}</span> · Venta <span className="font-mono tabular">{fmtArs(venta)}</span></>
          : '—'}
      </div>
    </div>
  )
}

// ─── Workspace key-value row ─────────────────────────────────────────────────

function MetaRow({ label, children, last }) {
  return (
    <div className={`flex items-baseline gap-3 px-4 py-2.5 ${last ? '' : 'border-b border-line/30'}`}>
      <span className="text-xs text-ink-3 min-w-[140px]">{label}</span>
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

const FIRST_IMPORT_FLAG = 'rendi_first_import_done'

export default function Config() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [brokers, setBrokers] = useState([])
  const [dolar, setDolar] = useState(null)
  const [newBroker, setNewBroker] = useState({ name: '', currency: 'USDT' })
  const [editingBroker, setEditingBroker] = useState(null)
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' })
  const [pwState, setPwState] = useState({ loading: false, error: '', success: '' })
  const [showImport, setShowImport] = useState(false)
  const [importJustConfirmed, setImportJustConfirmed] = useState(false)
  const [showAddBroker, setShowAddBroker] = useState(false)
  const [aiUsage, setAiUsage] = useState(null)
  // Upgrade modal cuando el backend devuelve 403 al intentar agregar broker
  const [brokerUpgrade, setBrokerUpgrade] = useState(null)
  const plan = usePlanFeatures()

  useEffect(() => {
    loadDolar()
    loadBrokers()
    loadAiUsage()
    const id = setInterval(loadDolar, DOLAR_REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  async function loadAiUsage() {
    try { setAiUsage(await api.get('/ai/usage')) } catch {}
  }

  async function loadDolar() {
    try { setDolar(await api.get('/dolar')) } catch {}
  }

  async function loadBrokers() {
    setBrokers(await api.get('/brokers'))
  }

  async function addBroker(e) {
    e.preventDefault()
    if (!newBroker.name.trim()) return
    try {
      await api.post('/brokers', { name: newBroker.name.trim(), currency: newBroker.currency })
      setNewBroker({ name: '', currency: 'USDT' })
      setShowAddBroker(false)
      loadBrokers()
      refreshPlanFeatures()  // brokers_current cambió
    } catch (ex) {
      // Gate Free: backend devuelve 403 con upgrade payload cuando cap alcanzado
      if (ex?.status === 403 && ex?.payload?.detail?.upgrade) {
        const detail = ex.payload.detail
        track('feature_blocked_clicked', { feature: 'brokers.create', source: 'config_add_broker' })
        setBrokerUpgrade({
          message: detail.error || 'El plan Free permite 1 broker.',
          benefits: detail.upgrade?.benefits,
        })
        return
      }
      throw ex
    }
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
  const labelClass = 'block text-xs text-ink-3 mb-1'
  const inputClass = 'w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2'
  const selectClass = 'bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 focus:outline-none focus:border-ink-2'

  return (
    <div className="page-shell-wide">
      <PageHeader
        title="Configuración"
        subtitle="Gestioná tus brokers, tipos de cambio y datos de cuenta."
      />

      {/* ── Plan actual ──────────────────────────────────────────────────── */}
      <PlanHero tier={user?.tier || 'free'} usage={aiUsage} />

      {/* ── FX rates ─────────────────────────────────────────────────────── */}
      <section className="mb-6">
        <div className="flex items-baseline justify-between mb-2 gap-3 flex-wrap">
          <h2 className="text-sm font-medium text-ink-1">Tipos de cambio</h2>
          <span className="text-xs text-ink-3 inline-flex items-center gap-3">
            <span>dolarapi.com · sync {fmtTime(fetchedAt)}</span>
            <button
              type="button"
              onClick={loadDolar}
              className="inline-flex items-center gap-1 text-ink-3 hover:text-ink-0 transition-colors"
              title="Actualizar cotización"
            >
              <RefreshCw size={11} strokeWidth={1.75} />
              Actualizar
            </button>
          </span>
        </div>
        <div className="border border-line rounded bg-bg-1 flex flex-wrap">
          <FxCell
            first
            label="Blue"
            sub="ARS/USD"
            value={dolar?.blue?.venta}
            compra={dolar?.blue?.compra}
            venta={dolar?.blue?.venta}
          />
          <FxCell
            label="MEP"
            sub="ARS/USD"
            value={dolar?.mep?.venta}
            compra={dolar?.mep?.compra}
            venta={dolar?.mep?.venta}
          />
          <FxCell
            label="CCL"
            sub="ARS/USD"
            value={dolar?.ccl?.venta}
            compra={dolar?.ccl?.compra}
            venta={dolar?.ccl?.venta}
          />
          <FxCell
            label="Cripto"
            sub="ARS/USDT"
            value={dolar?.cripto?.venta}
            compra={dolar?.cripto?.compra}
            venta={dolar?.cripto?.venta}
          />
        </div>
      </section>

      {/* ── Grid: Brokers | Workspace info ───────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-4 mb-4">
        {/* Brokers conectados */}
        <Panel padding="none">
          <header className="flex items-center justify-between px-4 py-3 border-b border-line">
            <div>
              <h2 className="text-sm font-medium text-ink-0">Brokers</h2>
              <p className="text-xs text-ink-3 mt-0.5">
                {brokers.length} {brokers.length === 1 ? 'broker conectado' : 'brokers conectados'}
              </p>
            </div>
            <button
              onClick={() => setShowAddBroker(true)}
              className="inline-flex items-center gap-1.5 text-xs bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-3 py-1.5 rounded-sm transition-colors"
            >
              <Plus size={12} strokeWidth={2} /> Agregar broker
            </button>
          </header>

          {brokers.length === 0 ? (
            <div className="p-6 text-center text-ink-3 text-sm">
              No tenés brokers configurados. Conectá uno para empezar a registrar posiciones.
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-line/60 text-xs text-ink-3">
                  <th className="text-left px-4 py-2 font-medium">Broker</th>
                  <th className="text-left px-3 py-2 font-medium">Moneda</th>
                  <th className="text-left px-3 py-2 font-medium">Estado</th>
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
                          <div className="flex gap-2">
                            <button type="submit" className="text-xs bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 px-3 py-2 rounded-sm transition-colors">
                              Guardar
                            </button>
                            <button type="button" onClick={() => setEditingBroker(null)} className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors">
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
                        <div className="flex gap-2">
                          <button type="submit" className="inline-flex items-center gap-1.5 text-xs bg-rendi-pos/10 text-rendi-pos border border-rendi-pos/30 hover:bg-rendi-pos/15 px-3 py-2 rounded-sm transition-colors">
                            <Plus size={12} strokeWidth={2} /> Agregar
                          </button>
                          <button type="button" onClick={() => setShowAddBroker(false)} className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors">
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

          <div className="px-4 py-3 border-t border-line text-xs text-ink-3 leading-relaxed">
            <span className="text-data-cyan font-medium">USDT</span> exchanges crypto (Binance) ·{' '}
            <span className="text-ink-2 font-medium">USD</span> brokers en dólares (IBKR, Schwab) ·{' '}
            <span className="text-ink-2 font-medium">ARS</span> brokers en pesos, convertidos al blue (Cocos, IOL).
          </div>
        </Panel>

        {/* Workspace info */}
        <Panel padding="none">
          <header className="px-4 py-3 border-b border-line">
            <h2 className="text-sm font-medium text-ink-0">Cuenta</h2>
            <p className="text-xs text-ink-3 mt-0.5">Datos de tu workspace</p>
          </header>
          <div>
            <MetaRow label="Email">
              <span className="font-medium text-ink-0">{user?.email || user?.name || '—'}</span>
              {user?.is_admin && (
                <Pill tone="info" className="ml-2">Admin</Pill>
              )}
            </MetaRow>
            <MetaRow label="Workspace">
              <span className="text-ink-1">
                {user?.email ? user.email.split('@')[0] : (user?.name || '—')}
                <span className="text-ink-3 ml-1.5">· personal</span>
              </span>
            </MetaRow>
            <MetaRow label="Plan">
              <Pill tone="signal">Free</Pill>
            </MetaRow>
            <MetaRow label="Brokers">
              <span className="tabular">
                {brokers.length} {brokers.length === 1 ? 'conectado' : 'conectados'}
              </span>
            </MetaRow>
            <MetaRow label="Miembro desde" last>
              <span className="tabular text-xs">{memberSince(user?.created_at)}</span>
            </MetaRow>
          </div>
        </Panel>
      </div>

      {/* ── Grid: Datos / Importaciones | Cambiar contraseña ─────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Datos / Importaciones */}
        <Panel padding="none">
          <header className="px-4 py-3 border-b border-line">
            <h2 className="text-sm font-medium text-ink-0">Importar datos</h2>
            <p className="text-xs text-ink-3 mt-0.5">Subí un CSV con tu historial</p>
          </header>
          <div className="p-4 space-y-3">
            <p className="text-sm text-ink-2 leading-relaxed">
              Reconstruí el portfolio sin cargar todo a mano. Soporta exports de cualquier broker — vas a poder mapear las columnas y previsualizar antes de confirmar.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setShowImport(true)}
                className="inline-flex items-center gap-1.5 text-xs bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-3 py-1.5 rounded-sm transition-colors"
              >
                <Upload size={12} strokeWidth={2} /> Importar CSV
              </button>
              <Link
                to="/imports"
                className="inline-flex items-center gap-1.5 text-xs text-ink-2 hover:text-ink-0 border border-line bg-bg-2 hover:bg-bg-3 px-3 py-1.5 rounded-sm transition-colors"
              >
                <History size={12} strokeWidth={1.75} /> Ver historial
              </Link>
            </div>
          </div>
        </Panel>

        {/* Cambiar contraseña */}
        <Panel padding="none">
          <header className="flex items-center gap-2 px-4 py-3 border-b border-line">
            <KeyRound size={14} strokeWidth={1.75} className="text-ink-3" aria-hidden="true" />
            <div>
              <h2 className="text-sm font-medium text-ink-0">Contraseña</h2>
              <p className="text-xs text-ink-3 mt-0.5">Cambiala periódicamente</p>
            </div>
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
            <p className="text-xs text-ink-3">
              Mínimo 10 caracteres. Al actualizarla se cierran las sesiones activas en otros dispositivos.
            </p>
            {pwState.error && (
              <p className="text-xs text-rendi-neg">{pwState.error}</p>
            )}
            {pwState.success && (
              <p className="text-xs text-rendi-pos">{pwState.success}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => { setPwForm({ current: '', next: '', confirm: '' }); setPwState({ loading: false, error: '', success: '' }) }}
                className="text-xs text-ink-3 hover:text-ink-0 px-3 py-2 transition-colors"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={pwState.loading}
                className="inline-flex items-center gap-1.5 text-xs bg-rendi-pos/10 hover:bg-rendi-pos/15 text-rendi-pos border border-rendi-pos/30 px-3 py-2 rounded-sm transition-colors disabled:opacity-50"
              >
                <Lock size={12} strokeWidth={1.75} />
                {pwState.loading ? 'Guardando…' : 'Cambiar contraseña'}
              </button>
            </div>
          </form>
        </Panel>
      </div>

      {/* Modal de upgrade cuando intenta agregar broker n°2 en Free */}
      {brokerUpgrade && (
        <UpgradeModal
          title="Pasate a Rendi Pro para más brokers"
          message={brokerUpgrade.message}
          feature="brokers.create"
          source="config_add_broker"
          benefits={brokerUpgrade.benefits}
          onClose={() => setBrokerUpgrade(null)}
        />
      )}

      {showImport && (
        <ImportWizard
          onClose={() => {
            setShowImport(false)
            if (importJustConfirmed && !localStorage.getItem(FIRST_IMPORT_FLAG)) {
              localStorage.setItem(FIRST_IMPORT_FLAG, '1')
              setImportJustConfirmed(false)
              navigate('/bienvenida')
              return
            }
            setImportJustConfirmed(false)
          }}
          onConfirmed={() => { setImportJustConfirmed(true) }}
        />
      )}
    </div>
  )
}

// ─── PlanHero ────────────────────────────────────────────────────────────────
// Sección destacada al tope de Config con plan actual + uso semanal de IA
// + comparativa Free vs Pro + CTA upgrade (solo en Free). Tono violet para
// Pro, sutil para Free (que SIGUE el highlight es el botón de upgrade).

const PRO_FEATURES = [
  { label: '60 análisis IA por semana', sub: '10× más que Free (6/sem)' },
  { label: 'Respuestas con causalidad y comparaciones', sub: 'Free: solo descripción' },
  { label: 'Follow-ups: profundizá con preguntas libres', sub: 'No disponible en Free' },
  { label: 'AI Hub: exploración libre sobre tu portfolio', sub: 'Exclusivo Pro', comingSoon: true },
]

const FREE_FEATURES = [
  { label: '6 análisis IA por semana', value: 'free' },
  { label: 'Respuestas descriptivas', value: 'free' },
  { label: 'Dashboard, Insights, Reportes', value: 'free' },
  { label: 'Todas las pantallas de data y posiciones', value: 'free' },
]

function PlanHero({ tier, usage }) {
  if (tier === 'admin') return <PlanHeroAdmin usage={usage} />
  if (tier === 'pro') return <PlanHeroPro usage={usage} />
  return <PlanHeroFree usage={usage} />
}

function PlanHeroFree({ usage }) {
  const count = usage?.analyses_count ?? 0
  const limit = usage?.analyses_limit ?? 6
  const pct = limit > 0 ? Math.min(100, (count / limit) * 100) : 0
  const remaining = Math.max(0, limit - count)

  function onUpgradeClick() {
    track('plan_hero_upgrade_clicked', { source: 'config' })
    // TODO: cuando exista checkout, redirigir.
  }

  return (
    <section className="mb-6 border border-data-violet/30 bg-data-violet/[0.04] rounded p-5">
      <div className="grid grid-cols-1 lg:grid-cols-[1.3fr_1fr] gap-5">
        {/* Left: tier actual + headline + features Free */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="font-mono text-[10px] uppercase tracking-caps text-ink-3">Plan actual</span>
            <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm font-mono text-[9px] font-medium tracking-caps bg-bg-2 text-ink-2">
              FREE
            </span>
          </div>
          <h2 className="text-lg font-semibold text-ink-0 leading-snug mb-1">
            Estás en el plan gratuito de Rendi
          </h2>
          <p className="text-sm text-ink-2 leading-relaxed mb-3">
            Acceso completo a tu portfolio, brokers, monthly tracking, posiciones, drawdowns e Insights. Con la IA en modo descriptivo (resumen breve).
          </p>
          <div className="space-y-1.5">
            {FREE_FEATURES.map((f, i) => (
              <div key={i} className="flex items-start gap-2 text-xs text-ink-1">
                <Check size={11} strokeWidth={2} className="text-ink-3 mt-0.5 flex-shrink-0" />
                <span className="leading-snug">{f.label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: usage strip + CTA */}
        <div className="bg-bg-1 border border-line/60 rounded-sm p-4 flex flex-col">
          <div className="flex items-baseline justify-between mb-1">
            <span className="font-mono text-[10px] uppercase tracking-caps text-ink-3">Uso IA últimos 7 días</span>
            <span className="font-mono text-xs text-ink-1 tabular">{count} / {limit}</span>
          </div>
          <div className="h-1.5 bg-bg-2 rounded-full overflow-hidden mb-2">
            <div
              className={`h-full transition-all ${pct >= 100 ? 'bg-rendi-neg' : pct >= 80 ? 'bg-data-amber' : 'bg-data-violet'}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-[11px] text-ink-3 mb-4">
            {remaining > 0
              ? `${remaining} análisis ${remaining === 1 ? 'restante' : 'restantes'} · ventana móvil de 7 días`
              : (usage?.resets_on
                  ? `Próximo análisis disponible el ${usage.resets_on}`
                  : 'Llegaste al límite · esperá 7 días desde tu análisis más viejo'
                )}
          </p>

          {/* Pro pitch */}
          <div className="pt-3 border-t border-line/40 space-y-2 flex-1">
            <p className="text-xs text-ink-1 font-medium">Pasate a <span className="text-data-violet">Rendi Pro</span></p>
            <ul className="space-y-1.5">
              {PRO_FEATURES.map((f, i) => (
                <li key={i} className="flex items-start gap-2 text-[11px] text-ink-2">
                  <Sparkles size={10} strokeWidth={2} className="text-data-violet mt-0.5 flex-shrink-0" />
                  <div className="leading-snug">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span>{f.label}</span>
                      {f.comingSoon && (
                        <span className="font-mono text-[9px] uppercase tracking-caps px-1 py-px rounded-sm bg-data-amber/15 text-data-amber">
                          Próximamente
                        </span>
                      )}
                    </div>
                    {f.sub && <div className="text-[10px] text-ink-3">{f.sub}</div>}
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <button
            type="button"
            onClick={onUpgradeClick}
            className="mt-4 w-full inline-flex items-center justify-center gap-1.5 text-sm font-medium bg-data-violet/15 hover:bg-data-violet/25 text-data-violet border border-data-violet/40 rounded-sm py-2.5 transition-colors"
          >
            <Sparkles size={13} strokeWidth={1.75} />
            Conocer Rendi Pro
          </button>
          <p className="mt-1.5 text-[10px] text-ink-3 text-center">
            Pro está en desarrollo — te avisamos cuando esté listo.
          </p>
        </div>
      </div>
    </section>
  )
}

function PlanHeroPro({ usage }) {
  const count = usage?.analyses_count ?? 0
  const limit = usage?.analyses_limit ?? 60
  const pct = limit > 0 ? Math.min(100, (count / limit) * 100) : 0

  return (
    <section className="mb-6 border border-data-violet/40 bg-data-violet/[0.06] rounded p-5">
      <div className="grid grid-cols-1 lg:grid-cols-[1.3fr_1fr] gap-5">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <span className="font-mono text-[10px] uppercase tracking-caps text-ink-3">Plan actual</span>
            <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm font-mono text-[9px] font-medium tracking-caps bg-data-violet/15 text-data-violet">
              PRO
            </span>
            <span className="inline-flex items-center gap-1 text-[10px] text-rendi-pos font-mono uppercase tracking-caps">
              <span className="w-1.5 h-1.5 rounded-full bg-rendi-pos" /> Activo
            </span>
          </div>
          <h2 className="text-lg font-semibold text-ink-0 leading-snug mb-1">
            Tenés acceso completo a Rendi Pro
          </h2>
          <p className="text-sm text-ink-2 leading-relaxed mb-3">
            Análisis profundos, follow-ups, AI Hub y 10× más uso que Free. Gracias por bancar el producto.
          </p>
          <div className="space-y-1.5">
            {PRO_FEATURES.map((f, i) => (
              <div key={i} className="flex items-start gap-2 text-xs text-ink-1">
                {f.comingSoon
                  ? <Sparkles size={11} strokeWidth={2} className="text-data-amber mt-0.5 flex-shrink-0" />
                  : <Check size={11} strokeWidth={2} className="text-data-violet mt-0.5 flex-shrink-0" />
                }
                <span className="leading-snug flex items-center gap-1.5 flex-wrap">
                  <span className={f.comingSoon ? 'text-ink-2' : ''}>{f.label}</span>
                  {f.comingSoon && (
                    <span className="font-mono text-[9px] uppercase tracking-caps px-1 py-px rounded-sm bg-data-amber/15 text-data-amber">
                      Próximamente
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="bg-bg-1 border border-line/60 rounded-sm p-4 flex flex-col">
          <div className="flex items-baseline justify-between mb-1">
            <span className="font-mono text-[10px] uppercase tracking-caps text-ink-3">Uso IA últimos 7 días</span>
            <span className="font-mono text-xs text-ink-1 tabular">{count} / {limit}</span>
          </div>
          <div className="h-1.5 bg-bg-2 rounded-full overflow-hidden mb-2">
            <div className="h-full transition-all bg-data-violet" style={{ width: `${pct}%` }} />
          </div>
          <p className="text-[11px] text-ink-3">
            Ventana móvil de 7 días · seguís dentro del plan
          </p>
        </div>
      </div>
    </section>
  )
}

function PlanHeroAdmin({ usage }) {
  const count = usage?.analyses_count ?? 0
  return (
    <section className="mb-6 border border-rendi-pos/30 bg-rendi-pos/[0.04] rounded px-5 py-3.5 flex items-center gap-3 flex-wrap">
      <Zap size={14} strokeWidth={1.75} className="text-rendi-pos flex-shrink-0" />
      <span className="font-mono text-[10px] uppercase tracking-caps text-rendi-pos">Plan ADMIN</span>
      <span className="text-sm text-ink-1 flex-1 min-w-[200px]">
        Acceso interno sin tope. {count > 0 ? `Usaste ${count} análisis IA esta semana.` : 'Sin uso de IA esta semana.'}
      </span>
    </section>
  )
}
