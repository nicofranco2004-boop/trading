import { useEffect, useState } from 'react'
import { Shield, Users, Activity, Database, Trash2, RefreshCw, Check, Clock, Sparkles, TrendingUp } from 'lucide-react'
import { api } from '../utils/api'
import StatCard from '../components/StatCard'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../components/Toast'

export default function Admin() {
  const { user } = useAuth()
  const [stats, setStats] = useState(null)
  const [users, setUsers] = useState([])
  const [conversion, setConversion] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const toast = useToast()

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError('')
    try {
      const [s, u, c] = await Promise.all([
        api.get('/admin/stats'),
        api.get('/admin/users'),
        api.get('/admin/plan/conversion').catch(() => null),  // optional, no romper si falla
      ])
      setStats(s)
      setUsers(u)
      setConversion(c)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function approveUser(u) {
    if (!confirm(`¿Aprobar a ${u.email}? Una vez aprobado podrá iniciar sesión.`)) return
    try {
      await api.post(`/admin/users/${u.id}/approve`)
      load()
    } catch (e) {
      toast.push('Ocurrió un error: ' + e.message, { type: 'error' })
    }
  }

  async function deleteUser(u) {
    if (u.is_admin) return
    if (!confirm(`¿Eliminar la cuenta de ${u.email} junto a todos sus datos? Esta acción no se puede deshacer.`)) return
    try {
      await api.delete(`/admin/users/${u.id}`)
      load()
    } catch (e) {
      toast.push('Ocurrió un error: ' + e.message, { type: 'error' })
    }
  }

  if (!user?.is_admin) {
    return (
      <div className="page-shell max-w-3xl">
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-xl p-6 text-center">
          <Shield className="mx-auto text-red-500 mb-2" size={28} />
          <p className="text-red-700 dark:text-red-300 font-medium">Acceso restringido</p>
          <p className="text-xs text-red-600/70 dark:text-red-400/70 mt-1">Esta sección está reservada para administradores.</p>
        </div>
      </div>
    )
  }

  if (loading) return <div className="page-shell text-center text-ink-3" aria-live="polite">Cargando…</div>

  return (
    <div className="page-shell space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Shield size={22} className="text-rendi-accent" />
          <h1 className="text-xl font-bold text-ink-0">Panel de administración</h1>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1 text-xs text-ink-3 hover:text-ink-0 dark:hover:text-ink-0 px-2 py-1 rounded-md hover:bg-bg-2 dark:hover:bg-bg-2/40"
        >
          <RefreshCw size={12} /> Actualizar
        </button>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900/50 rounded-xl p-4 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}

      {stats && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <StatCard label="Usuarios totales" value={stats.users_total} sub={`${stats.users_admin} admin · ${stats.users_last_7d} nuevos en 7 días`} />
            <StatCard label="Pendientes de aprobación" value={stats.users_pending ?? 0} sub={stats.users_pending > 0 ? 'Requieren acción' : 'Sin solicitudes pendientes'} />
            <StatCard label="Activos (7 días)" value={stats.active_last_7d} sub="Inicio de sesión en los últimos 7 días" />
            <StatCard label="Posiciones" value={stats.positions_total} sub={`${stats.brokers_total} brokers configurados`} />
            <StatCard label="Operaciones" value={stats.operations_total} sub={`${stats.monthly_total} registros mensuales`} />
          </div>

          <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Activity size={16} className="text-ink-3" />
              <h2 className="font-semibold text-ink-0">Estado del sistema</h2>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
              <Row label="Registro público">
                <span className={stats.registration_open ? 'text-emerald-500' : 'text-amber-500'}>
                  {stats.registration_open ? 'Habilitado · cualquier usuario puede registrarse' : 'Deshabilitado · solo el admin crea cuentas'}
                </span>
              </Row>
              <Row label="Snapshots almacenados"><Database size={12} className="inline text-ink-3" /> {stats.snapshots_total}</Row>
              <Row label="Tasa de actividad">
                {stats.users_total > 0 ? `${((stats.active_last_7d / stats.users_total) * 100).toFixed(0)}%` : '—'}
              </Row>
            </div>
          </div>
        </>
      )}

      {/* ── Conversión Pro (paywall analytics) ─────────────────────────── */}
      <ConversionPanel data={conversion} />

      <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-line/50 flex items-center gap-2">
          <Users size={16} className="text-ink-3" />
          <h2 className="font-semibold text-ink-0">Usuarios ({users.length})</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line/50">
                {['ID', 'Email', 'Nombre', 'Registro', 'Último login', 'Pos', 'Ops', 'Mes', ''].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-xs text-ink-3 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-b border-line/50 dark:border-line/30 hover:bg-bg-2 dark:hover:bg-bg-2/20">
                  <td className="px-3 py-2 text-ink-3 font-mono text-xs">{u.id}</td>
                  <td className="px-3 py-2 font-medium text-ink-0">
                    {u.email}
                    {u.is_admin && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-rendi-accent/15 text-rendi-accent font-semibold uppercase tracking-wide">admin</span>}
                    {!u.approved && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-400 font-semibold uppercase tracking-wide"><Clock size={10} className="inline -mt-0.5" /> Pendiente</span>}
                  </td>
                  <td className="px-3 py-2 text-ink-2">{u.name || '—'}</td>
                  <td className="px-3 py-2 text-ink-3 text-xs">{u.created_at?.slice(0, 16) || '—'}</td>
                  <td className="px-3 py-2 text-ink-3 text-xs">{u.last_login_at?.slice(0, 16) || '—'}</td>
                  <td className="px-3 py-2 text-ink-2">{u.positions_count}</td>
                  <td className="px-3 py-2 text-ink-2">{u.operations_count}</td>
                  <td className="px-3 py-2 text-ink-2">{u.monthly_count}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      {!u.approved && !u.is_admin && (
                        <button
                          onClick={() => approveUser(u)}
                          className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-500/25"
                          title="Aprobar usuario"
                        >
                          <Check size={12} /> Aprobar
                        </button>
                      )}
                      {!u.is_admin && (
                        <button
                          onClick={() => deleteUser(u)}
                          className="text-ink-3 hover:text-red-500"
                          title="Eliminar usuario y todos sus datos"
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-ink-3 px-5 py-3 border-t border-line/50">
          Eliminar una cuenta también borra sus posiciones, operaciones, snapshots y brokers. Las cuentas de administrador no se pueden eliminar desde este panel.
        </p>
      </div>
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div>
      <p className="text-xs text-ink-3 mb-0.5">{label}</p>
      <p className="text-ink-1">{children}</p>
    </div>
  )
}

// ─── ConversionPanel — analytics del paywall Free → Pro ──────────────────────
// Aggregates de plan_events (Fase 3). Vacío si no hay events todavía.
function ConversionPanel({ data }) {
  if (!data) {
    return (
      <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles size={16} className="text-data-violet" />
          <h2 className="font-semibold text-ink-0">Conversión Pro</h2>
        </div>
        <p className="text-sm text-ink-3">Sin data — todavía no hay events registrados.</p>
      </div>
    )
  }

  const totalBlocked = data.totals?.feature_blocked_clicked || 0
  const totalCta = data.totals?.upgrade_modal_cta_clicked || 0
  const totalHero = data.totals?.plan_hero_upgrade_clicked || 0
  const totalPromo = data.totals?.upgrade_promo_clicked || 0
  const totalEvents = Object.values(data.totals || {}).reduce((s, n) => s + n, 0)

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-data-violet" />
          <h2 className="font-semibold text-ink-0">Conversión Pro</h2>
        </div>
        <span className="text-[10px] font-mono uppercase tracking-caps text-ink-3">
          {totalEvents} eventos totales · {data.last_30d_total} en 30 días
        </span>
      </div>

      {/* KPI strip de paywall events */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <ConvCell label="Bloqueos clicked"      value={totalBlocked} hint="LockedSection CTAs" />
        <ConvCell label="Upgrade modal CTA"     value={totalCta}     hint="Modal de upgrade" />
        <ConvCell label="Plan hero CTA"         value={totalHero}    hint="Banner en Config" />
        <ConvCell label="Drawer 429 CTA"        value={totalPromo}   hint="Cap semanal IA" />
      </div>

      {/* Por feature — qué bloqueo convierte más */}
      {data.by_feature?.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp size={13} className="text-ink-3" />
            <h3 className="text-sm font-medium text-ink-0">Por feature</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line/50 text-xs text-ink-3 font-medium">
                  <th className="text-left px-2 py-1.5">Feature</th>
                  <th className="text-right px-2 py-1.5">Clicks</th>
                  <th className="text-right px-2 py-1.5">Users únicos</th>
                </tr>
              </thead>
              <tbody>
                {data.by_feature.map(f => (
                  <tr key={f.feature_id} className="border-b border-line/30 hover:bg-bg-2/30">
                    <td className="px-2 py-1.5 font-mono text-xs text-ink-1">{f.feature_id}</td>
                    <td className="px-2 py-1.5 text-right tabular text-ink-0 font-medium">{f.clicks}</td>
                    <td className="px-2 py-1.5 text-right tabular text-ink-2">{f.users}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Por source — qué pantalla genera más intent */}
      {data.by_source?.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <Activity size={13} className="text-ink-3" />
            <h3 className="text-sm font-medium text-ink-0">Por pantalla</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line/50 text-xs text-ink-3 font-medium">
                  <th className="text-left px-2 py-1.5">Source</th>
                  <th className="text-right px-2 py-1.5">Clicks</th>
                  <th className="text-right px-2 py-1.5">Users únicos</th>
                </tr>
              </thead>
              <tbody>
                {data.by_source.map(s => (
                  <tr key={s.source} className="border-b border-line/30 hover:bg-bg-2/30">
                    <td className="px-2 py-1.5 font-mono text-xs text-ink-1">{s.source}</td>
                    <td className="px-2 py-1.5 text-right tabular text-ink-0 font-medium">{s.clicks}</td>
                    <td className="px-2 py-1.5 text-right tabular text-ink-2">{s.users}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent feed — debug útil para validar que los events llegan */}
      {data.recent?.length > 0 && (
        <details className="group">
          <summary className="cursor-pointer text-xs text-ink-3 hover:text-ink-0 select-none">
            Ver últimos {data.recent.length} eventos (debug)
          </summary>
          <div className="mt-2 max-h-64 overflow-y-auto border border-line/40 rounded-sm bg-bg-1/40">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-line/40 text-ink-3 sticky top-0 bg-bg-2/80 backdrop-blur">
                  <th className="text-left px-2 py-1">Fecha</th>
                  <th className="text-left px-2 py-1">User</th>
                  <th className="text-left px-2 py-1">Tier</th>
                  <th className="text-left px-2 py-1">Event</th>
                  <th className="text-left px-2 py-1">Feature</th>
                  <th className="text-left px-2 py-1">Source</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.map((e, i) => (
                  <tr key={i} className="border-b border-line/20">
                    <td className="px-2 py-1 text-ink-3">{e.created_at?.slice(5, 16)}</td>
                    <td className="px-2 py-1 text-ink-2">{e.user_id}</td>
                    <td className="px-2 py-1 text-ink-2">{e.tier}</td>
                    <td className="px-2 py-1 text-ink-1">{e.event_name?.replace('_clicked', '')}</td>
                    <td className="px-2 py-1 text-ink-2">{e.feature_id || '—'}</td>
                    <td className="px-2 py-1 text-ink-3">{e.source || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      <p className="text-[11px] text-ink-3 pt-1 border-t border-line/30">
        Telemetría auto-trackeada desde frontend → POST /api/plan/track. {data.distinct_free_users_with_intent} usuarios Free
        únicos han mostrado intent de upgrade.
      </p>
    </div>
  )
}

function ConvCell({ label, value, hint }) {
  return (
    <div className="border border-line/40 rounded-sm bg-bg-1/40 px-3 py-2.5">
      <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 leading-none">{label}</div>
      <div className="mt-1.5 text-xl font-medium tabular num leading-none text-ink-0">{value}</div>
      <div className="text-[10px] text-ink-3 mt-1 truncate">{hint}</div>
    </div>
  )
}
