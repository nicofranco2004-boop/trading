import { useEffect, useState } from 'react'
import { Shield, Users, Activity, Database, Trash2, RefreshCw, Check, Clock, Sparkles, TrendingUp, RotateCcw, AlertTriangle, Mail, Send } from 'lucide-react'
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

  async function restoreTier(u) {
    if (!confirm(`¿Restaurar el plan de ${u.email}? Usa el crédito que ya pagó (vigente), no recobra ni mueve fechas.`)) return
    try {
      const res = await api.post('/admin/billing/restore-tier?email=' + encodeURIComponent(u.email))
      if (res?.ok && res?.changed) {
        toast.push(`Plan restaurado a ${res.after_tier} para ${u.email}.`, { type: 'success' })
      } else if (res?.ok) {
        toast.push(res.detail || 'Sin cambios: el tier ya estaba alineado.', { type: 'info' })
      } else {
        toast.push(res?.detail || 'No se pudo restaurar el plan.', { type: 'warn' })
      }
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

  const affected = users.filter(u => u.billing_affected)

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

      {/* ── Re-engagement: mail a usuarios que no importaron su historial ── */}
      <ReengagementPanel toast={toast} />

      {/* ── Alerta de billing: pagaron pero figuran en Free ──────────────── */}
      {affected.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/40 rounded-xl p-4 flex items-start gap-3">
          <AlertTriangle size={18} className="text-amber-500 flex-shrink-0 mt-0.5" />
          <div className="text-sm min-w-0">
            <p className="font-medium text-amber-800 dark:text-amber-300">
              {affected.length} usuario{affected.length > 1 ? 's' : ''} con crédito activo figura{affected.length > 1 ? 'n' : ''} en Free
            </p>
            <p className="text-amber-700/80 dark:text-amber-400/70 text-xs mt-0.5 leading-relaxed">
              Pagaron pero el tier quedó en free (clobber del cron de downgrade). Restauralos con el botón “Restaurar” en la tabla de abajo —
              usa el crédito que ya pagaron, no recobra ni mueve fechas.
            </p>
          </div>
        </div>
      )}

      <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-line/50 flex items-center gap-2">
          <Users size={16} className="text-ink-3" />
          <h2 className="font-semibold text-ink-0">Usuarios ({users.length})</h2>
          {affected.length > 0 && (
            <span className="ml-1 inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-400 font-semibold uppercase tracking-wide">
              <AlertTriangle size={10} /> {affected.length} a restaurar
            </span>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line/50">
                {['ID', 'Email', 'Nombre', 'Plan', 'Registro', 'Último login', 'Pos', 'Ops', 'Mes', ''].map(h => (
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
                  <td className="px-3 py-2"><PlanBadge plan={u.plan} affected={u.billing_affected} creditActive={u.credit_active} /></td>
                  <td className="px-3 py-2 text-ink-3 text-xs">{u.created_at?.slice(0, 16) || '—'}</td>
                  <td className="px-3 py-2 text-ink-3 text-xs">{u.last_login_at?.slice(0, 16) || '—'}</td>
                  <td className="px-3 py-2 text-ink-2">{u.positions_count}</td>
                  <td className="px-3 py-2 text-ink-2">{u.operations_count}</td>
                  <td className="px-3 py-2 text-ink-2">{u.monthly_count}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      {u.billing_affected && (
                        <button
                          onClick={() => restoreTier(u)}
                          className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-amber-500/15 text-amber-700 dark:text-amber-400 hover:bg-amber-500/25"
                          title="Restaurar plan desde el crédito activo (no recobra)"
                        >
                          <RotateCcw size={12} /> Restaurar
                        </button>
                      )}
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

// ─── ReengagementPanel — mail a usuarios que se registraron pero no importaron ─
// Preview (confirm:false) → muestra la lista exacta de destinatarios sin mandar
// nada. Recién al apretar "Enviar" (confirm:true) el backend mailea por Resend,
// stampea reengagement_email_sent_at y saltea a quien ya recibió. Idempotente:
// re-correr no duplica; los fallidos se reintentan en la próxima corrida.
function ReengagementPanel({ toast }) {
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)

  async function loadPreview() {
    setLoading(true); setResult(null)
    try {
      setPreview(await api.post('/admin/email/re-engagement', { confirm: false }))
    } catch (e) {
      toast.push('Error al previsualizar: ' + e.message, { type: 'error' })
    } finally { setLoading(false) }
  }

  async function send() {
    const pending = (preview?.recipients || []).filter(r => !r.already_sent_at).length
    if (pending === 0) return
    if (!confirm(`¿Mandar el mail de re-engagement a ${pending} usuario${pending > 1 ? 's' : ''}? Los que ya lo recibieron se saltean.`)) return
    setSending(true)
    try {
      const r = await api.post('/admin/email/re-engagement', { confirm: true })
      setResult(r)
      toast.push(
        `Enviados ${r.sent_count} · fallados ${r.failed_count} · salteados ${r.skipped_count}`,
        { type: r.failed_count ? 'warn' : 'success' }
      )
      await loadPreview()
    } catch (e) {
      toast.push('Error al enviar: ' + e.message, { type: 'error' })
    } finally { setSending(false) }
  }

  const recipients = preview?.recipients || []
  const pending = recipients.filter(r => !r.already_sent_at)

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Mail size={16} className="text-data-violet" />
          <h2 className="font-semibold text-ink-0">Re-engagement · importá tu historial</h2>
        </div>
        <button
          onClick={loadPreview}
          disabled={loading}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> {preview ? 'Recalcular' : 'Ver destinatarios'}
        </button>
      </div>

      <p className="text-xs text-ink-3 leading-relaxed">
        Usuarios verificados con ≤1 operación cargada (se registraron pero no importaron su historial). El mail es el
        tono “lite”, sin presión. Los que ya lo recibieron quedan excluidos automáticamente — podés re-correrlo sin
        miedo a duplicar.
      </p>

      {preview && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <ConvCell label="Candidatos" value={preview.total_candidates} hint="≤1 operación" />
            <ConvCell label="A enviar ahora" value={pending.length} hint="nunca recibieron" />
            <ConvCell label="Ya recibieron" value={preview.already_sent} hint="se saltean" />
          </div>

          {recipients.length > 0 ? (
            <div className="max-h-64 overflow-y-auto border border-line/40 rounded-sm bg-bg-1/40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line/40 text-ink-3 sticky top-0 bg-bg-2/80 backdrop-blur">
                    <th className="text-left px-2 py-1">Email</th>
                    <th className="text-left px-2 py-1">Nombre</th>
                    <th className="text-right px-2 py-1">Actividad</th>
                    <th className="text-left px-2 py-1">Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {recipients.map(r => (
                    <tr key={r.id} className="border-b border-line/20">
                      <td className="px-2 py-1 text-ink-1">{r.email}</td>
                      <td className="px-2 py-1 text-ink-2">{r.name || '—'}</td>
                      <td className="px-2 py-1 text-right tabular text-ink-2">{r.activity}</td>
                      <td className="px-2 py-1">
                        {r.already_sent_at
                          ? <span className="text-emerald-600 dark:text-emerald-400">enviado</span>
                          : <span className="text-ink-3">pendiente</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-sm text-ink-3">No hay usuarios que cumplan el criterio. 🎉</p>
          )}

          <div className="flex items-center justify-between gap-3 pt-1 border-t border-line/30 flex-wrap">
            <p className="text-[11px] text-ink-3 max-w-md">
              Envía vía Resend. Los que fallan no se marcan como enviados → se reintentan solos la próxima vez.
            </p>
            <button
              onClick={send}
              disabled={sending || pending.length === 0}
              className="flex items-center gap-1.5 text-sm px-3.5 py-2 rounded-md bg-data-violet text-white font-medium hover:bg-data-violet/90 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Send size={14} /> {sending ? 'Enviando…' : `Enviar a ${pending.length}`}
            </button>
          </div>

          {result && (
            <div className="text-xs text-ink-2 bg-bg-1/40 border border-line/40 rounded-sm px-3 py-2">
              Resultado: <b className="text-emerald-600 dark:text-emerald-400">{result.sent_count} enviados</b>
              {result.failed_count > 0 && <> · <b className="text-red-500">{result.failed_count} fallados</b></>}
              {result.skipped_count > 0 && <> · {result.skipped_count} salteados</>}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// Badge de plan en la tabla de usuarios. `affected` = pagó pero quedó en free
// (mostramos "afectado" en ámbar). Caso contrario, color por plan.
function PlanBadge({ plan, affected, creditActive }) {
  if (affected) {
    return (
      <span
        className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-400 font-semibold uppercase tracking-wide"
        title="Tiene crédito vigente pero el tier quedó en free — restaurable"
      >
        <AlertTriangle size={10} /> afectado
      </span>
    )
  }
  const styles = {
    admin: 'bg-rendi-accent/15 text-rendi-accent',
    plus: 'bg-data-violet/15 text-data-violet',
    pro: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-400',
    free: 'bg-bg-2 text-ink-3 dark:bg-bg-2/60',
  }
  const cls = styles[plan] || styles.free
  return (
    <span className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase tracking-wide ${cls}`}>
      {plan || 'free'}
      {creditActive && plan !== 'free' && plan !== 'admin' && (
        <span className="ml-1 normal-case font-normal opacity-70" title="Crédito vigente">· crédito</span>
      )}
    </span>
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
        <span className="text-[11px] font-mono uppercase tracking-caps text-ink-2">
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
      <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 leading-none">{label}</div>
      <div className="mt-1.5 text-xl font-medium tabular num leading-none text-ink-0">{value}</div>
      <div className="text-[10px] text-ink-3 mt-1 truncate">{hint}</div>
    </div>
  )
}
