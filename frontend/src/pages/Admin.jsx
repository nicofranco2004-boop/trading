import { useEffect, useState } from 'react'
import { Shield, Users, Activity, Database, Trash2, RefreshCw, Check, Clock } from 'lucide-react'
import { api } from '../utils/api'
import StatCard from '../components/StatCard'
import { useAuth } from '../contexts/AuthContext'

export default function Admin() {
  const { user } = useAuth()
  const [stats, setStats] = useState(null)
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => { load() }, [])

  async function load() {
    setLoading(true)
    setError('')
    try {
      const [s, u] = await Promise.all([
        api.get('/admin/stats'),
        api.get('/admin/users'),
      ])
      setStats(s)
      setUsers(u)
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
      alert('Ocurrió un error: ' + e.message)
    }
  }

  async function deleteUser(u) {
    if (u.is_admin) return
    if (!confirm(`¿Eliminar la cuenta de ${u.email} junto a todos sus datos? Esta acción no se puede deshacer.`)) return
    try {
      await api.delete(`/admin/users/${u.id}`)
      load()
    } catch (e) {
      alert('Ocurrió un error: ' + e.message)
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
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">Panel de administración</h1>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 px-2 py-1 rounded-md hover:bg-slate-100 dark:hover:bg-slate-700/40"
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

          <div className="bg-white dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/50 shadow-sm dark:shadow-none rounded-xl p-5">
            <div className="flex items-center gap-2 mb-3">
              <Activity size={16} className="text-slate-400" />
              <h2 className="font-semibold text-slate-800 dark:text-slate-200">Estado del sistema</h2>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
              <Row label="Registro público">
                <span className={stats.registration_open ? 'text-emerald-500' : 'text-amber-500'}>
                  {stats.registration_open ? 'Habilitado · cualquier usuario puede registrarse' : 'Deshabilitado · solo el admin crea cuentas'}
                </span>
              </Row>
              <Row label="Snapshots almacenados"><Database size={12} className="inline text-slate-400" /> {stats.snapshots_total}</Row>
              <Row label="Tasa de actividad">
                {stats.users_total > 0 ? `${((stats.active_last_7d / stats.users_total) * 100).toFixed(0)}%` : '—'}
              </Row>
            </div>
          </div>
        </>
      )}

      <div className="bg-white dark:bg-slate-800/60 border border-slate-200/80 dark:border-slate-700/50 shadow-sm dark:shadow-none rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-200 dark:border-slate-700/50 flex items-center gap-2">
          <Users size={16} className="text-slate-400" />
          <h2 className="font-semibold text-slate-800 dark:text-slate-200">Usuarios ({users.length})</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700/50">
                {['ID', 'Email', 'Nombre', 'Registro', 'Último login', 'Pos', 'Ops', 'Mes', ''].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-xs text-slate-400 dark:text-slate-500 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-b border-slate-100 dark:border-slate-700/30 hover:bg-slate-50 dark:hover:bg-slate-700/20">
                  <td className="px-3 py-2 text-slate-500 dark:text-slate-400 font-mono text-xs">{u.id}</td>
                  <td className="px-3 py-2 font-medium text-slate-800 dark:text-slate-200">
                    {u.email}
                    {u.is_admin && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-rendi-accent/15 text-rendi-accent font-semibold uppercase tracking-wide">admin</span>}
                    {!u.approved && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-400 font-semibold uppercase tracking-wide"><Clock size={10} className="inline -mt-0.5" /> Pendiente</span>}
                  </td>
                  <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{u.name || '—'}</td>
                  <td className="px-3 py-2 text-slate-500 dark:text-slate-400 text-xs">{u.created_at?.slice(0, 16) || '—'}</td>
                  <td className="px-3 py-2 text-slate-500 dark:text-slate-400 text-xs">{u.last_login_at?.slice(0, 16) || '—'}</td>
                  <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{u.positions_count}</td>
                  <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{u.operations_count}</td>
                  <td className="px-3 py-2 text-slate-600 dark:text-slate-300">{u.monthly_count}</td>
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
                          className="text-slate-400 hover:text-red-500"
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
        <p className="text-xs text-slate-400 dark:text-slate-500 px-5 py-3 border-t border-slate-200 dark:border-slate-700/50">
          Eliminar una cuenta también borra sus posiciones, operaciones, snapshots y brokers. Las cuentas de administrador no se pueden eliminar desde este panel.
        </p>
      </div>
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div>
      <p className="text-xs text-slate-400 dark:text-slate-500 mb-0.5">{label}</p>
      <p className="text-slate-700 dark:text-slate-300">{children}</p>
    </div>
  )
}
