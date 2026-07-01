import { useEffect, useState } from 'react'
import { Shield, Users, Activity, Database, Trash2, RefreshCw, Check, Clock, Sparkles, TrendingUp, RotateCcw, AlertTriangle, Mail, Send, Gift } from 'lucide-react'
import { api } from '../utils/api'
import StatCard from '../components/StatCard'
import { PageSkeleton } from '../components/Skeleton'
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

  async function grantPro(u) {
    const days = 30
    if (!confirm(`¿Dar Pro por ${days} días a ${u.email}? Es de cortesía (gratis) y se vence solo — vuelve a Free en ${days} días.`)) return
    const url = `/admin/billing/grant-comp?email=${encodeURIComponent(u.email)}&plan=pro&days=${days}`
    try {
      let res = await api.post(url)
      if (res?.ok === false && res?.reason === 'credit_already_active') {
        const until = (res.credit_active_until || '').slice(0, 10)
        if (!confirm(`${u.email} ya tiene plan activo hasta ${until}. ¿Sumar ${days} días más?`)) return
        res = await api.post(url + '&force=true')
      }
      if (res?.ok) {
        toast.push(res.detail || `Pro otorgado a ${u.email}.`, { type: 'success' })
      } else {
        toast.push(res?.detail || 'No se pudo otorgar el plan.', { type: 'warn' })
      }
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

  if (loading) return <PageSkeleton />

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

          {/* ── Embudo de activación ─────────────────────────────────────── */}
          {stats.activation && (
            <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 shadow-sm dark:shadow-none rounded-xl p-5">
              <div className="flex items-center gap-2 mb-1">
                <Activity size={16} className="text-ink-3" />
                <h2 className="font-semibold text-ink-0">Embudo de activación</h2>
              </div>
              <p className="text-xs text-ink-3 mb-4">
                Usuarios reales (verificados, sin admins ni cuentas de test). Muestra en qué escalón se cae la gente camino al “aha”.
              </p>
              {(() => {
                const a = stats.activation
                const base = a.verified_real || 0
                const steps = [
                  { label: 'Verificó email', n: a.verified_real },
                  { label: 'Creó un broker', n: a.with_broker },
                  { label: 'Cargó una posición', n: a.with_position },
                  { label: 'Cargó ≥1 operación', n: a.with_operation },
                  { label: 'Cargó ≥2 operaciones', n: a.with_2plus_operations },
                ]
                return (
                  <div className="space-y-2">
                    {steps.map((s, i) => {
                      const pct = base > 0 ? Math.round((s.n / base) * 100) : 0
                      const prev = i > 0 ? steps[i - 1].n : s.n
                      const drop = prev > 0 ? Math.round(((prev - s.n) / prev) * 100) : 0
                      return (
                        <div key={s.label} className="flex items-center gap-3">
                          <div className="w-36 sm:w-44 text-sm text-ink-1 flex-shrink-0">{s.label}</div>
                          <div className="flex-1 h-6 bg-bg-1 dark:bg-bg-1/60 rounded overflow-hidden min-w-0">
                            <div className="h-full bg-data-violet/70 rounded" style={{ width: `${pct}%` }} />
                          </div>
                          <div className="w-24 text-right text-sm tabular flex-shrink-0">
                            <span className="text-ink-0 font-medium">{s.n}</span>
                            <span className="text-ink-3"> · {pct}%</span>
                          </div>
                          <div className="w-14 text-right text-xs tabular text-rendi-neg flex-shrink-0">
                            {i > 0 && drop > 0 ? `−${drop}%` : ''}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )
              })()}
            </div>
          )}
        </>
      )}

      {/* ── Conversión Pro (paywall analytics) ─────────────────────────── */}
      <ConversionPanel data={conversion} />

      {/* ── Re-engagement: mail a usuarios que no importaron su historial ── */}
      <ReengagementPanel toast={toast} />

      {/* ── Campaña regalo Pro: avisar que les regalamos un mes + cargá historial ── */}
      <GiftPlanPanel toast={toast} />

      {/* ── Backup manual (S3) — hacelo ANTES de cualquier recompute/repair ── */}
      <BackupPanel toast={toast} />

      {/* ── Backfill: recomputar posiciones de cuentas ya importadas (FIFO + amort) ── */}
      <BackfillPanel toast={toast} />

      <MtmBackfillPanel toast={toast} />

      <CurrencyBackfillPanel toast={toast} />

      <RepairUserPanel toast={toast} />

      <MassRepairPanel toast={toast} />

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
                  <td className="px-3 py-2"><PlanBadge plan={u.plan} affected={u.billing_affected} creditActive={u.credit_active} daysRemaining={u.days_remaining} /></td>
                  <td className="px-3 py-2 text-ink-3 text-xs">{u.created_at?.slice(0, 16) || '—'}</td>
                  <td className="px-3 py-2 text-ink-3 text-xs">{u.last_login_at?.slice(0, 16) || '—'}</td>
                  <td className="px-3 py-2 text-ink-2">{u.positions_count}</td>
                  <td className="px-3 py-2 text-ink-2">{u.operations_count}</td>
                  <td className="px-3 py-2 text-ink-2">{u.monthly_count}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      {!u.is_admin && (
                        <button
                          onClick={() => grantPro(u)}
                          className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-data-violet/15 text-data-violet hover:bg-data-violet/25"
                          title="Dar Pro gratis por 30 días (cortesía, se vence solo)"
                        >
                          <Gift size={12} /> Pro 1 mes
                        </button>
                      )}
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
  const [resend, setResend] = useState(false)

  async function loadPreview() {
    setLoading(true); setResult(null)
    try {
      setPreview(await api.post('/admin/email/re-engagement', { confirm: false }))
    } catch (e) {
      toast.push('Error al previsualizar: ' + e.message, { type: 'error' })
    } finally { setLoading(false) }
  }

  async function send() {
    const all = preview?.recipients || []
    const n = resend ? all.length : all.filter(r => !r.already_sent_at).length
    if (n === 0) return
    const msg = resend
      ? `¿Reenviar el mail a los ${n} destinatarios? Incluye a los que ya lo recibieron (re-test).`
      : `¿Mandar el mail de re-engagement a ${n} usuario${n > 1 ? 's' : ''}? Los que ya lo recibieron se saltean.`
    if (!confirm(msg)) return
    setSending(true)
    try {
      const r = await api.post('/admin/email/re-engagement', { confirm: true, resend })
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
  const toSend = resend ? recipients : pending

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
            <p className="text-sm text-ink-3">No hay usuarios que cumplan el criterio.</p>
          )}

          <div className="flex items-center justify-between gap-3 pt-1 border-t border-line/30 flex-wrap">
            <div className="space-y-1.5">
              <p className="text-[11px] text-ink-3 max-w-md">
                Envía vía Resend. Los que fallan no se marcan como enviados → se reintentan solos la próxima vez.
              </p>
              <label className="flex items-center gap-1.5 text-[11px] text-ink-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={resend}
                  onChange={e => setResend(e.target.checked)}
                  className="accent-data-violet"
                />
                Reenviar a los que ya recibieron (para re-testear el email)
              </label>
            </div>
            <button
              onClick={send}
              disabled={sending || toSend.length === 0}
              className="flex items-center gap-1.5 text-sm px-3.5 py-2 rounded-md bg-data-violet text-white font-medium hover:bg-data-violet/90 disabled:opacity-40 disabled:cursor-not-allowed press"
            >
              <Send size={14} /> {sending ? 'Enviando…' : `Enviar a ${toSend.length}`}
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

// ─── BackupPanel — backup manual de la base a S3 (antes de recompute/repair) ──
function BackupPanel({ toast }) {
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  async function backup() {
    setBusy(true); setResult(null)
    try {
      const r = await api.post('/admin/backup-trigger')
      setResult(r)
      toast.push(r.ok ? 'Backup subido a S3 ✓' : 'Backup terminó con errores — revisá', { type: r.ok ? 'success' : 'warn' })
    } catch (e) {
      toast.push('Error en el backup: ' + (e.message || ''), { type: 'error' })
    } finally { setBusy(false) }
  }

  const st = result?.stats || {}
  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-start gap-2">
          <Database size={16} className="text-rendi-accent mt-0.5 flex-shrink-0" />
          <div>
            <h2 className="font-semibold text-ink-0">Backup ahora</h2>
            <p className="text-xs text-ink-3 leading-relaxed mt-0.5">
              Sube una copia de la base a S3 (el mismo backup que el cron diario). <b>Hacelo antes de
              Aplicar</b> cualquier Recompute o Reparar snapshots.
            </p>
          </div>
        </div>
        <button onClick={backup} disabled={busy}
          className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-md bg-rendi-accent/15 text-rendi-accent hover:bg-rendi-accent/25 disabled:opacity-50 flex-shrink-0">
          {busy ? <RefreshCw size={14} className="animate-spin" /> : <Database size={14} />}
          {busy ? 'Haciendo backup…' : 'Hacer backup'}
        </button>
      </div>
      {result && (
        <div className={`mt-3 text-xs px-3 py-2 rounded-md border ${result.ok ? 'bg-rendi-pos/10 border-rendi-pos/30 text-rendi-pos' : 'bg-rendi-warn/10 border-rendi-warn/30 text-rendi-warn'}`}>
          {result.ok ? '✅ Backup subido a S3' : '⚠ Backup con errores'}
          {(st.s3_key || st.key) && <span className="text-ink-2"> · {st.s3_key || st.key}</span>}
          {st.size_bytes && <span className="text-ink-2"> · {(st.size_bytes / 1e6).toFixed(1)} MB</span>}
          {st.errors?.length > 0 && <span className="text-ink-2"> · {st.errors.length} error(es)</span>}
        </div>
      )}
    </div>
  )
}

// ─── GiftPlanPanel — mail "te regalamos un mes de Pro, cargá tu historial" ────
// Para usuarios con ≤1 operación a los que YA se les regaló un mes de Pro (vía
// grant-comp). Preview (confirm:false) muestra la lista + su tier/regalo sin
// mandar nada; "Enviar" (confirm:true) mailea por Resend, stampea
// gift_plan_email_sent_at y saltea a quien ya recibió. Idempotente.
//   • only_gifted: solo a quienes tienen un comp Pro/Plus activo (no promete un
//     regalo a quien no lo recibió). Default ON por seguridad.
function GiftPlanPanel({ toast }) {
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState(null)
  const [resend, setResend] = useState(false)
  const [onlyGifted, setOnlyGifted] = useState(true)

  async function loadPreview() {
    setLoading(true); setResult(null)
    try {
      setPreview(await api.post('/admin/email/gift-plan', { confirm: false, only_gifted: onlyGifted }))
    } catch (e) {
      toast.push('Error al previsualizar: ' + e.message, { type: 'error' })
    } finally { setLoading(false) }
  }

  async function send() {
    const all = preview?.recipients || []
    const n = resend ? all.length : all.filter(r => !r.already_sent_at).length
    if (n === 0) return
    const msg = resend
      ? `¿Reenviar el mail de regalo Pro a los ${n} destinatarios? Incluye a los que ya lo recibieron.`
      : `¿Mandar el mail "te regalamos un mes de Pro" a ${n} usuario${n > 1 ? 's' : ''}? Los que ya lo recibieron se saltean.`
    if (!confirm(msg)) return
    setSending(true)
    try {
      const r = await api.post('/admin/email/gift-plan', { confirm: true, resend, only_gifted: onlyGifted })
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
  const toSend = resend ? recipients : pending

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Mail size={16} className="text-emerald-500" />
          <h2 className="font-semibold text-ink-0">Regalo Pro · cargá tu historial</h2>
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
        Usuarios con ≤1 operación a los que les regalaste un mes de Pro. El mail les avisa del regalo y los empuja a
        importar su historial para aprovecharlo. Con <b>“solo con regalo activo”</b> se manda únicamente a quienes
        tienen un comp Pro/Plus vigente (no promete un regalo a quien no lo tiene). Los que ya lo recibieron se saltean.
      </p>

      <label className="flex items-center gap-1.5 text-[11px] text-ink-3 cursor-pointer select-none">
        <input type="checkbox" checked={onlyGifted} onChange={e => setOnlyGifted(e.target.checked)} className="accent-emerald-500" />
        Solo a quienes tienen el regalo (Pro/Plus) activo
      </label>

      {preview && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <ConvCell label="Candidatos" value={preview.total_candidates} hint="≤1 operación" />
            <ConvCell label="Con regalo activo" value={preview.with_gift} hint="comp Pro/Plus vigente" />
            <ConvCell label="A enviar ahora" value={pending.length} hint="nunca recibieron" />
          </div>

          {recipients.length > 0 ? (
            <div className="max-h-64 overflow-y-auto border border-line/40 rounded-sm bg-bg-1/40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line/40 text-ink-3 sticky top-0 bg-bg-2/80 backdrop-blur">
                    <th className="text-left px-2 py-1">Email</th>
                    <th className="text-left px-2 py-1">Nombre</th>
                    <th className="text-right px-2 py-1">Actividad</th>
                    <th className="text-left px-2 py-1">Plan</th>
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
                        {r.has_gift
                          ? <span className="text-emerald-600 dark:text-emerald-400 uppercase font-semibold">{r.tier}</span>
                          : <span className="text-amber-600 dark:text-amber-400" title="Sin comp activo — no recibió el regalo">{r.tier || 'free'} ⚠</span>}
                      </td>
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
            <p className="text-sm text-ink-3">No hay usuarios que cumplan el criterio.</p>
          )}

          <div className="flex items-center justify-between gap-3 pt-1 border-t border-line/30 flex-wrap">
            <div className="space-y-1.5">
              <p className="text-[11px] text-ink-3 max-w-md">
                Envía vía Resend. Los que fallan no se marcan como enviados → se reintentan solos la próxima vez.
              </p>
              <label className="flex items-center gap-1.5 text-[11px] text-ink-3 cursor-pointer select-none">
                <input type="checkbox" checked={resend} onChange={e => setResend(e.target.checked)} className="accent-emerald-500" />
                Reenviar a los que ya recibieron (para re-testear el email)
              </label>
            </div>
            <button
              onClick={send}
              disabled={sending || toSend.length === 0}
              className="flex items-center gap-1.5 text-sm px-3.5 py-2 rounded-md bg-emerald-500 text-white font-medium hover:bg-emerald-500/90 disabled:opacity-40 disabled:cursor-not-allowed press"
            >
              <Send size={14} /> {sending ? 'Enviando…' : `Enviar a ${toSend.length}`}
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
function PlanBadge({ plan, affected, creditActive, daysRemaining }) {
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
  const showDays = creditActive && plan !== 'free' && plan !== 'admin' && daysRemaining != null
  const lowDays = showDays && daysRemaining <= 5
  return (
    <span className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded font-semibold uppercase tracking-wide ${cls}`}>
      {plan || 'free'}
      {showDays ? (
        <span
          className={`ml-1 normal-case font-medium ${lowDays ? 'text-amber-700 dark:text-amber-400' : 'opacity-70'}`}
          title={`Le ${daysRemaining === 1 ? 'queda' : 'quedan'} ${daysRemaining} ${daysRemaining === 1 ? 'día' : 'días'} de crédito antes de volver a Free`}
        >
          · {daysRemaining}d
        </span>
      ) : creditActive && plan !== 'free' && plan !== 'admin' && (
        <span className="ml-1 normal-case font-normal opacity-70" title="Crédito vigente">· crédito</span>
      )}
    </span>
  )
}

// ─── ConversionPanel — analytics del paywall Free → Pro ──────────────────────
// Aggregates de plan_events (Fase 3). Vacío si no hay events todavía.
// ─── BackfillPanel — recomputar posiciones de cuentas ya importadas ──────────
// Aplica a cuentas viejas los fixes de FIFO (currency-aware + neteo dólar-MEP) y
// la amortización de bonos, sin que el usuario re-importe. Simular (sobre copia,
// no toca nada) → revisar → Aplicar.
function BackfillPanel({ toast }) {
  const CHUNK = 25  // usuarios por request (clonar+recomputar a todos juntos timeout-eaba)
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [progress, setProgress] = useState(null)  // {done, total}
  const [costMode, setCostMode] = useState(false)  // false = solo seguro (cantidad); true = solo costo (sin tocar cantidades)

  // Procesa TODOS los usuarios por tandas de CHUNK, acumulando el resultado.
  async function runChunks(doApply) {
    let offset = 0, total = 1
    const safeOnly = costMode ? 'false' : 'true'
    const costOnly = costMode ? 'true' : 'false'
    const agg = { users_changed: 0, positions_changed: 0, cost_positions_changed: 0,
                  changes: [], cost_changes: [], errors: [], total_users: 0, cost_mode: costMode }
    do {
      const r = await api.post(`/admin/backfill-recompute?safe_only=${safeOnly}&cost_only=${costOnly}&apply=${doApply}&offset=${offset}&limit=${CHUNK}`)
      total = r.total_all_users || 0
      agg.users_changed += r.users_changed || 0
      agg.positions_changed += r.positions_changed || 0
      agg.cost_positions_changed += r.cost_positions_changed || 0
      agg.total_users = total
      if (agg.changes.length < 2000) agg.changes.push(...(r.changes || []))
      else agg.truncated = true
      if (agg.cost_changes.length < 2000) agg.cost_changes.push(...(r.cost_changes || []))
      if (r.errors?.length) agg.errors.push(...r.errors)
      offset += CHUNK
      setProgress({ done: Math.min(offset, total), total })
    } while (offset < total)
    return agg
  }

  async function simulate() {
    setLoading(true); setPreview(null); setProgress({ done: 0, total: 0 })
    try {
      setPreview(await runChunks(false))
    } catch (e) {
      toast.push('Error al simular: ' + e.message, { type: 'error' })
    } finally { setLoading(false); setProgress(null) }
  }

  async function apply() {
    if (!preview) return
    const detail = costMode
      ? `${preview.cost_positions_changed || 0} bonos a corregir (per-100→per-1), SIN tocar cantidades ni comisiones`
      : `${preview.positions_changed} cambios seguros de cantidad`
    if (!confirm(`¿Aplicar a ${preview.users_changed} cuenta${preview.users_changed === 1 ? '' : 's'} ` +
                 `(${detail})? Hacé un backup antes. Solo es reversible desde backup.`)) return
    setApplying(true); setProgress({ done: 0, total: 0 })
    try {
      const r = await runChunks(true)
      toast.push(`Aplicado: ${r.users_changed} cuentas · ${costMode ? `${r.cost_positions_changed} de costo` : `${r.positions_changed} seguros`}`, { type: 'success' })
      await simulate()  // re-simular → debería dar 0 cambios (idempotente)
    } catch (e) {
      toast.push('Error al aplicar: ' + e.message, { type: 'error' })
    } finally { setApplying(false); setProgress(null) }
  }

  const changes = preview?.changes || []

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <RotateCcw size={16} className="text-data-violet" />
          <h2 className="font-semibold text-ink-0">Recomputar posiciones — {costMode ? 'solo bonos (per-100→per-1)' : 'solo cambios seguros'}</h2>
        </div>
        <button
          onClick={simulate}
          disabled={loading || applying}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> {preview ? 'Volver a simular' : 'Simular corrección'}
        </button>
      </div>

      <label className="flex items-start gap-2 text-xs text-ink-2 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={costMode}
          onChange={e => { setCostMode(e.target.checked); setPreview(null) }}
          disabled={loading || applying}
          className="mt-0.5 accent-data-violet"
        />
        <span>
          <b>Modo solo bonos</b> — corrige la unidad de los bonos <b>per-100→per-1</b> sobre las posiciones
          <b>actuales</b>, <b>sin recomputar cantidades</b> (no re-corre el FIFO) y <b>sin tocar comisiones</b>
          (esa normalización es muy amplia/aproximada, se trabaja aparte). El "Simular" muestra solo el ÷100 de bonos; revisalo y hacé backup antes de aplicar.
        </span>
      </label>

      <p className="text-xs text-ink-3 leading-relaxed">
        Aplica a las cuentas <b>ya importadas</b> SOLO los cambios <b>inequívocos</b>: fantasmas dólar-MEP de acciones que
        van a <b>cero</b>, <b>letras vencidas</b>, <b>bonos 100% amortizados</b> y <b>amortizaciones limpias</b> (× su
        factor exacto). Todo lo dudoso de bonos-conducto (inflaciones, reducciones raras) se <b>omite</b> — así no rompe
        nada. <b>Simular</b> corre sobre una copia (no toca nada) y te muestra qué cambiaría; recién <b>Aplicar</b> modifica.
        Idempotente, no toca el cash. Hacé un backup antes de aplicar.
      </p>

      {progress && progress.total > 0 && (loading || applying) && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-ink-3">
            <span>{applying ? 'Aplicando…' : 'Simulando…'}</span>
            <span className="tabular">{progress.done} / {progress.total} cuentas</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-bg-2 dark:bg-bg-2/40 overflow-hidden">
            <div
              className="h-full bg-data-violet transition-all"
              style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }}
            />
          </div>
        </div>
      )}

      {preview && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <ConvCell label="Cuentas a corregir" value={preview.users_changed} hint={`de ${preview.total_users}`} />
            {costMode
              ? <ConvCell label="Cambios de costo" value={preview.cost_positions_changed || 0} hint="invested / comisión" />
              : <ConvCell label="Cambios seguros" value={preview.positions_changed} hint="solo lo inequívoco" />}
          </div>

          {!costMode && (changes.length > 0 ? (
            <div className="max-h-64 overflow-y-auto border border-line/40 rounded-sm bg-bg-1/40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line/40 text-ink-3 sticky top-0 bg-bg-2/80 backdrop-blur">
                    <th className="text-left px-2 py-1">Usuario</th>
                    <th className="text-left px-2 py-1">Broker</th>
                    <th className="text-left px-2 py-1">Activo</th>
                    <th className="text-left px-2 py-1">Tipo</th>
                    <th className="text-right px-2 py-1">Antes</th>
                    <th className="text-right px-2 py-1">Después</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((c, i) => (
                    <tr key={i} className="border-b border-line/20">
                      <td className="px-2 py-1 text-ink-2">#{c.uid}</td>
                      <td className="px-2 py-1 text-ink-2">{c.broker}</td>
                      <td className="px-2 py-1 text-ink-1">{c.asset}</td>
                      <td className="px-2 py-1 text-ink-3">{c.kind || c.tag}</td>
                      <td className="px-2 py-1 text-right tabular text-ink-2">{c.before?.toLocaleString()}</td>
                      <td className={`px-2 py-1 text-right tabular ${c.after === 0 ? 'text-rose-500' : 'text-ink-1'}`}>
                        {c.after?.toLocaleString()} {c.after === 0 && '· eliminada'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.truncated && <p className="text-[11px] text-ink-3 px-2 py-1">… lista truncada; los totales de arriba son completos.</p>}
            </div>
          ) : (
            <p className="text-xs text-ink-3">No hay cambios pendientes — las cuentas ya están al día. ✅</p>
          ))}

          {costMode && (preview.cost_changes?.length > 0 ? (
            <div className="max-h-64 overflow-y-auto border border-line/40 rounded-sm bg-bg-1/40">
              <div className="text-[11px] font-medium text-ink-2 px-2 py-1 bg-bg-2/70 sticky top-0">Bonos a corregir (per-100→per-1)</div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line/40 text-ink-3">
                    <th className="text-left px-2 py-1">Usuario</th>
                    <th className="text-left px-2 py-1">Broker</th>
                    <th className="text-left px-2 py-1">Activo</th>
                    <th className="text-right px-2 py-1">Invertido antes</th>
                    <th className="text-right px-2 py-1">Invertido después</th>
                    <th className="text-right px-2 py-1">Comisión</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.cost_changes.map((c, i) => (
                    <tr key={i} className="border-b border-line/20">
                      <td className="px-2 py-1 text-ink-2">#{c.uid}</td>
                      <td className="px-2 py-1 text-ink-2">{c.broker}</td>
                      <td className="px-2 py-1 text-ink-1">{c.asset}</td>
                      <td className="px-2 py-1 text-right tabular text-ink-2">{c.invested_before?.toLocaleString()}</td>
                      <td className="px-2 py-1 text-right tabular text-ink-1">{c.invested_after?.toLocaleString()}</td>
                      <td className="px-2 py-1 text-right tabular text-ink-3">
                        {c.comm_before !== c.comm_after ? `${c.comm_before?.toLocaleString()} → ${c.comm_after?.toLocaleString()}` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-ink-3">No hay cambios de costo pendientes — los costos ya están al día. ✅</p>
          ))}

          {preview.errors?.length > 0 && (
            <p className="text-xs text-rose-500">{preview.errors.length} cuenta(s) con error (se saltean): {preview.errors.slice(0, 5).map(e => `#${e.uid}`).join(', ')}</p>
          )}

          {preview.users_changed > 0 && (
            <button
              onClick={apply}
              disabled={applying || loading}
              className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-md bg-data-violet text-white hover:bg-data-violet/90 disabled:opacity-50"
            >
              <Check size={14} className={applying ? 'animate-pulse' : ''} />
              {applying ? 'Aplicando…' : `Aplicar a ${preview.users_changed} cuenta${preview.users_changed === 1 ? '' : 's'}`}
            </button>
          )}
        </>
      )}
    </div>
  )
}


// ─── MtmBackfillPanel — valuación histórica a mercado (arregla chart + CAGR) ──
// Rellena monthly_entries.capital_final + snapshots de meses cerrados con el valor
// de MERCADO histórico → la curva de Evolución deja de estar plana y el CAGR refleja
// el retorno real. Simular (sobre copia) → revisar → Aplicar.
function MtmBackfillPanel({ toast }) {
  const CHUNK = 6  // usuarios por request — el fetch de precios históricos es lento
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [progress, setProgress] = useState(null)

  const sleep = (ms) => new Promise(r => setTimeout(r, ms))

  function absorb(agg, r) {
    agg.users_changed += r.users_changed || 0
    agg.skipped += r.skipped || 0
    agg.total_users = r.total_all_users || agg.total_users
    if (agg.changes.length < 2000) agg.changes.push(...(r.changes || []))
    else agg.truncated = true
    if (r.errors?.length) agg.errors.push(...r.errors)
  }

  // Corre TODAS las tandas resiliente: si una tanda falla (timeout de Yahoo /
  // 502 transitorio), NO aborta — la registra y sigue. Después hace una 2da
  // pasada SOLO sobre las que fallaron: para entonces el cache de precios del
  // backend ya quedó caliente del primer barrido, así que suelen completar.
  async function runChunks(doApply) {
    const agg = { users_changed: 0, changes: [], errors: [], total_users: 0, skipped: 0, failed_chunks: 0 }
    let offset = 0, total = 1, done = 0
    const fetchChunk = (off) => api.post(`/admin/backfill-mtm?apply=${doApply}&offset=${off}&limit=${CHUNK}`)
    const failedOffsets = []

    // 1ra pasada
    do {
      try {
        const r = await fetchChunk(offset)
        total = r.total_all_users || total
        absorb(agg, r)
      } catch (e) {
        failedOffsets.push(offset)
        if (total <= 1) throw e  // nunca supimos el total (1ra tanda cayó) → no se puede seguir
      }
      offset += CHUNK
      done = Math.min(offset, total)
      setProgress({ done, total, phase: 'run' })
    } while (offset < total)

    // 2da pasada — reintenta las tandas lentas con el cache ya caliente.
    if (failedOffsets.length) {
      setProgress({ done, total, phase: 'retry' })
      await sleep(2500)  // darle aire a Yahoo antes de reintentar
      const stillFailed = []
      for (const off of failedOffsets) {
        try { absorb(agg, await fetchChunk(off)) }
        catch (e) { stillFailed.push(off) }
      }
      agg.failed_chunks = stillFailed.length
    }
    return agg
  }

  function reportFailures(agg, verb) {
    if (!agg.failed_chunks) return
    toast.push(
      `${verb}, pero ${agg.failed_chunks} tanda${agg.failed_chunks === 1 ? '' : 's'} (~${agg.failed_chunks * CHUNK} cuentas) ` +
      `no respondieron a tiempo. Volvé a tocar el botón para completarlas — el cache ya quedó caliente.`,
      { type: 'warn', duration: 9000 })
  }

  async function simulate() {
    setLoading(true); setPreview(null); setProgress({ done: 0, total: 0, phase: 'run' })
    try { const agg = await runChunks(false); setPreview(agg); reportFailures(agg, 'Simulado') }
    catch (e) { toast.push('Error al simular: ' + e.message, { type: 'error' }) }
    finally { setLoading(false); setProgress(null) }
  }

  async function apply() {
    if (!preview) return
    if (!confirm(`¿Aplicar la valuación histórica a mercado en ${preview.users_changed} cuenta${preview.users_changed === 1 ? '' : 's'}? ` +
                 `Hacé un backup antes. Solo es reversible desde backup.`)) return
    setApplying(true); setProgress({ done: 0, total: 0, phase: 'run' })
    try {
      const r = await runChunks(true)
      if (r.failed_chunks) reportFailures(r, 'Aplicado parcial')
      else toast.push(`Aplicado: ${r.users_changed} cuenta${r.users_changed === 1 ? '' : 's'} con historia a mercado`, { type: 'success' })
      await simulate()  // re-simular → debería dar 0 (idempotente)
    } catch (e) { toast.push('Error al aplicar: ' + e.message, { type: 'error' }) }
    finally { setApplying(false); setProgress(null) }
  }

  const changes = preview?.changes || []

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-data-violet" />
          <h2 className="font-semibold text-ink-0">Valuación histórica a mercado — chart + CAGR</h2>
        </div>
        <button onClick={simulate} disabled={loading || applying}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> {preview ? 'Volver a simular' : 'Simular'}
        </button>
      </div>

      <p className="text-xs text-ink-3 leading-relaxed">
        Rellena la historia de las cuentas <b>importadas</b> con el valor de <b>mercado</b> de cada mes (reconstruye qué
        tenías y lo valúa al precio de cierre histórico). Arregla el chart de <b>Evolución</b> (la curva deja de estar
        plana y de "saltar" al final) y el <b>CAGR</b>. <b>Simular</b> corre sobre una copia (no toca nada) y muestra
        qué cambiaría; recién <b>Aplicar</b> modifica. Idempotente, degrada al costo si falta un precio (<b>nunca infla</b>),
        no toca posiciones ni cash, saltea cuentas sin import. Hacé un backup antes.
      </p>

      {progress && progress.total > 0 && (loading || applying) && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-ink-3">
            <span>{progress.phase === 'retry' ? 'Reintentando tandas lentas…' : (applying ? 'Aplicando…' : 'Simulando…')}</span>
            <span className="tabular">{progress.done} / {progress.total} cuentas</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-bg-2 dark:bg-bg-2/40 overflow-hidden">
            <div className={`h-full transition-all ${progress.phase === 'retry' ? 'bg-amber-500 animate-pulse' : 'bg-data-violet'}`} style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }} />
          </div>
        </div>
      )}

      {preview && (
        <>
          {preview.failed_chunks > 0 && (
            <div className="text-xs px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30 text-amber-700 dark:text-amber-400">
              ⚠ {preview.failed_chunks} tanda{preview.failed_chunks === 1 ? '' : 's'} (~{preview.failed_chunks * CHUNK} cuentas) no respondieron a tiempo
              (Yahoo lento). Volvé a tocar <b>Simular</b> para completarlas — el cache ya quedó caliente y va a andar.
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <ConvCell label="Cuentas con historia a mercado" value={preview.users_changed} hint={`de ${preview.total_users}`} />
            <ConvCell label="Sin import (salteadas)" value={preview.skipped} hint="cuentas manuales" />
          </div>

          {changes.length > 0 ? (
            <div className="max-h-64 overflow-y-auto border border-line/40 rounded-sm bg-bg-1/40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line/40 text-ink-3 sticky top-0 bg-bg-2/80 backdrop-blur">
                    <th className="text-left px-2 py-1">Usuario</th>
                    <th className="text-right px-2 py-1">Meses</th>
                    <th className="text-left px-2 py-1">Primer mes (antes→después)</th>
                    <th className="text-left px-2 py-1">Último mes (antes→después)</th>
                    <th className="text-right px-2 py-1">Al costo</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((c, i) => (
                    <tr key={i} className="border-b border-line/20">
                      <td className="px-2 py-1 text-ink-2">#{c.uid}</td>
                      <td className="px-2 py-1 text-right tabular text-ink-2">{c.months_changed}</td>
                      <td className="px-2 py-1 text-ink-1 tabular">{c.first_ym}: {Math.round(c.first_before).toLocaleString()}→{Math.round(c.first_after).toLocaleString()}</td>
                      <td className="px-2 py-1 text-ink-1 tabular">{c.last_ym}: {Math.round(c.last_before).toLocaleString()}→{Math.round(c.last_after).toLocaleString()}</td>
                      <td className="px-2 py-1 text-right tabular text-ink-3">{c.cost_fallbacks}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.truncated && <p className="text-[11px] text-ink-3 px-2 py-1">… lista truncada; los totales de arriba son completos.</p>}
            </div>
          ) : (
            <p className="text-xs text-ink-3">No hay cambios — la historia ya está a mercado, o no hay cuentas importadas reconstruibles. ✅</p>
          )}

          {preview.errors?.length > 0 && (
            <p className="text-xs text-rose-500">{preview.errors.length} cuenta(s) con error (se saltean): {preview.errors.slice(0, 5).map(e => `#${e.uid}`).join(', ')}</p>
          )}

          {preview.users_changed > 0 && (
            <button onClick={apply} disabled={applying || loading}
              className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-md bg-data-violet text-white hover:bg-data-violet/90 disabled:opacity-50">
              <Check size={14} className={applying ? 'animate-pulse' : ''} />
              {applying ? 'Aplicando…' : `Aplicar a ${preview.users_changed} cuenta${preview.users_changed === 1 ? '' : 's'}`}
            </button>
          )}
        </>
      )}
    </div>
  )
}

// ─── CurrencyBackfillPanel — corregir moneda de cuentas con capital negativo gigante ──
// Corrige in-place las filas de import_normalized_tx envenenadas (pesos contados como
// dólares ×~tc_blue: FCI money-market, seed sintético, conductos dólar-MEP) y re-rebuildea.
// Solo toca cuentas con capital negativo < -50k (gate anti-falso-positivo). Simular → revisar
// (¡mirar los fondos FCI tocados!) → Aplicar.
function CurrencyBackfillPanel({ toast }) {
  const CHUNK = 12  // re-rebuild FIFO por cuenta; tanda moderada
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [progress, setProgress] = useState(null)

  function emptyAgg() {
    return { users_changed: 0, changes: [], errors: [], total_users: 0, skipped: 0, fci_funds: {} }
  }
  function absorb(agg, r) {
    agg.users_changed += r.users_changed || 0
    agg.skipped += r.skipped || 0
    agg.total_users = r.total_all_users || agg.total_users
    if (agg.changes.length < 2000) agg.changes.push(...(r.changes || []))
    else agg.truncated = true
    if (r.errors?.length) agg.errors.push(...r.errors)
    for (const [sym, f] of Object.entries(r.fci_funds_touched || {})) {
      const g = agg.fci_funds[sym] || { count: 0, vcp_min: f.vcp_min, vcp_max: f.vcp_max, max_amt: 0 }
      g.count += f.count || 0
      g.vcp_min = Math.min(g.vcp_min, f.vcp_min)
      g.vcp_max = Math.max(g.vcp_max, f.vcp_max)
      g.max_amt = Math.max(g.max_amt, f.max_amt || 0)
      agg.fci_funds[sym] = g
    }
  }

  async function runChunks(doApply) {
    const agg = emptyAgg()
    let offset = 0, total = 1
    do {
      const r = await api.post(`/admin/backfill-currency?apply=${doApply}&offset=${offset}&limit=${CHUNK}`)
      total = r.total_all_users || total
      absorb(agg, r)
      offset += CHUNK
      setProgress({ done: Math.min(offset, total), total })
    } while (offset < total)
    return agg
  }

  async function simulate() {
    setLoading(true); setPreview(null); setProgress({ done: 0, total: 0 })
    try { setPreview(await runChunks(false)) }
    catch (e) { toast.push('Error al simular: ' + e.message, { type: 'error' }) }
    finally { setLoading(false); setProgress(null) }
  }

  async function apply() {
    if (!preview) return
    if (!confirm(`¿Aplicar la corrección de moneda en ${preview.users_changed} cuenta${preview.users_changed === 1 ? '' : 's'}? ` +
                 `Antes: (1) revisá que los fondos FCI tocados sean todos money-market, (2) hacé un backup. ` +
                 `Solo reversible desde backup.`)) return
    setApplying(true); setProgress({ done: 0, total: 0 })
    try {
      const r = await runChunks(true)
      toast.push(`Aplicado: ${r.users_changed} cuenta${r.users_changed === 1 ? '' : 's'} corregidas`, { type: 'success' })
      await simulate()  // re-simular → debería dar 0 (idempotente)
    } catch (e) { toast.push('Error al aplicar: ' + e.message, { type: 'error' }) }
    finally { setApplying(false); setProgress(null) }
  }

  const changes = preview?.changes || []
  const fciFunds = Object.entries(preview?.fci_funds || {}).sort((a, b) => b[1].max_amt - a[1].max_amt)
  const fmt = (n) => Math.round(n || 0).toLocaleString()

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <AlertTriangle size={16} className="text-amber-500" />
          <h2 className="font-semibold text-ink-0">Corregir moneda — capital negativo gigante</h2>
        </div>
        <button onClick={simulate} disabled={loading || applying}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> {preview ? 'Volver a simular' : 'Simular'}
        </button>
      </div>

      <p className="text-xs text-ink-3 leading-relaxed">
        Corrige las cuentas con <b>capital negativo de millones</b>: pesos que se contaron como dólares (×~1400)
        por FCI money-market mal-etiquetados, retiros sintéticos del seed, y conductos dólar-MEP con bono. Corrige
        las filas guardadas + re-rebuildea. <b>Solo toca cuentas con capital &lt; −50k</b> (una cuenta sana no se
        toca). <b>Simular</b> corre sobre una copia (no toca nada). ⚠️ <b>Antes de aplicar</b>: revisá abajo que los
        <b> fondos FCI tocados</b> sean todos money-market (RFPESOS/DOLINKA/…) — si hay un fondo raro, avisá. Hacé un backup.
      </p>

      {progress && progress.total > 0 && (loading || applying) && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-ink-3">
            <span>{applying ? 'Aplicando…' : 'Simulando…'}</span>
            <span className="tabular">{progress.done} / {progress.total} cuentas</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-bg-2 dark:bg-bg-2/40 overflow-hidden">
            <div className="h-full transition-all bg-amber-500" style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }} />
          </div>
        </div>
      )}

      {preview && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <ConvCell label="Cuentas a corregir" value={preview.users_changed} hint={`de ${preview.total_users} · resto sano/salteado`} />
            <ConvCell label="Fondos FCI tocados" value={fciFunds.length} hint="verificar que sean money-market" />
          </div>

          {/* ⭐ verificación humana del blocker: qué fondos toca la regla FCI */}
          {fciFunds.length > 0 && (
            <div className="border border-amber-500/30 rounded-md bg-amber-500/5 p-3 space-y-1.5">
              <p className="text-[11px] font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wide">
                ⚠️ Fondos FCI convertidos a ARS — ¿son TODOS money-market peso?
              </p>
              <div className="max-h-40 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead><tr className="text-ink-3">
                    <th className="text-left px-1 py-0.5">Fondo</th><th className="text-right px-1">Filas</th>
                    <th className="text-right px-1">VCP</th><th className="text-right px-1">Monto máx</th>
                  </tr></thead>
                  <tbody>
                    {fciFunds.map(([sym, f], i) => (
                      <tr key={i} className="border-t border-line/20">
                        <td className="px-1 py-0.5 text-ink-1 font-medium">{sym}</td>
                        <td className="px-1 text-right tabular text-ink-2">{f.count}</td>
                        <td className="px-1 text-right tabular text-ink-2">{fmt(f.vcp_min)}–{fmt(f.vcp_max)}</td>
                        <td className="px-1 text-right tabular text-ink-2">{fmt(f.max_amt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {changes.length > 0 ? (
            <div className="max-h-64 overflow-y-auto border border-line/40 rounded-sm bg-bg-1/40">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line/40 text-ink-3 sticky top-0 bg-bg-2/80 backdrop-blur">
                    <th className="text-left px-2 py-1">Usuario</th>
                    <th className="text-left px-2 py-1">Correcciones</th>
                    <th className="text-left px-2 py-1">Peor capital (antes→después)</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((c, i) => (
                    <tr key={i} className="border-b border-line/20">
                      <td className="px-2 py-1 text-ink-2">#{c.uid}</td>
                      <td className="px-2 py-1 text-ink-2 tabular">
                        {[c.corrections.fci && `${c.corrections.fci} FCI`, c.corrections.seed && `${c.corrections.seed} seed`,
                          c.corrections.conduit && `${c.corrections.conduit} cond.`].filter(Boolean).join(' · ')}
                      </td>
                      <td className="px-2 py-1 text-ink-1 tabular">
                        {fmt(c.worst_before)} → <span className="text-emerald-600 dark:text-emerald-400">{fmt(c.worst_after)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {preview.truncated && <p className="text-[11px] text-ink-3 px-2 py-1">… lista truncada; los totales de arriba son completos.</p>}
            </div>
          ) : (
            <p className="text-xs text-ink-3">No hay cuentas para corregir — ninguna con capital negativo gigante afectada. ✅</p>
          )}

          {preview.errors?.length > 0 && (
            <p className="text-xs text-rose-500">{preview.errors.length} cuenta(s) con error (se saltean): {preview.errors.slice(0, 5).map(e => `#${e.uid}`).join(', ')}</p>
          )}

          {preview.users_changed > 0 && (
            <button onClick={apply} disabled={applying || loading}
              className="flex items-center gap-1.5 text-sm px-4 py-2 rounded-md bg-amber-500 text-white hover:bg-amber-500/90 disabled:opacity-50">
              <Check size={14} className={applying ? 'animate-pulse' : ''} />
              {applying ? 'Aplicando…' : `Aplicar a ${preview.users_changed} cuenta${preview.users_changed === 1 ? '' : 's'}`}
            </button>
          )}
        </>
      )}
    </div>
  )
}

// ─── RepairUserPanel — reparar histórico de un usuario (snapshots contaminados) ──
function RepairUserPanel({ toast }) {
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  async function repair() {
    const e = email.trim()
    if (!e) return
    if (!confirm(`¿Reparar el histórico de ${e}? Borra y regenera sus snapshots (no toca posiciones ni cash).`)) return
    setBusy(true); setResult(null)
    try {
      const r = await api.post('/admin/repair-user-history', { email: e })
      setResult(r)
      toast.push(`Histórico reparado: ${r.snapshots_before} → ${r.snapshots_after} snapshots`, { type: 'success' })
    } catch (ex) {
      toast.push('Error: ' + (ex.message || 'no se pudo reparar'), { type: 'error' })
    } finally { setBusy(false) }
  }

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <RotateCcw size={16} className="text-rendi-warn" />
        <h2 className="font-semibold text-ink-0">Reparar histórico de un usuario</h2>
      </div>
      <p className="text-xs text-ink-3 leading-relaxed">
        Para una cuenta cuyos <b>% de 30 días / anual / mes están rotos</b> (ej: +5941%) por snapshots viejos
        contaminados de un ciclo import → revertir → reimportar. Recalcula sus monthly_entries (mata el drift),
        borra los snapshots contaminados y los regenera limpios. <b>No toca posiciones ni cash.</b> Para la
        curva a valor de mercado, después corré "Valuación histórica" (MTM).
      </p>
      <div className="flex items-center gap-2">
        <input
          type="email" value={email} onChange={(ev) => setEmail(ev.target.value)}
          placeholder="email del usuario" disabled={busy}
          className="flex-1 text-sm px-3 py-2 rounded-md bg-bg-2 dark:bg-bg-1 border border-line/60 text-ink-0 placeholder:text-ink-3"
        />
        <button
          onClick={repair} disabled={busy || !email.trim()}
          className="flex items-center gap-1 text-xs px-3 py-2 rounded-md bg-rendi-warn/15 text-rendi-warn hover:bg-rendi-warn/25 disabled:opacity-50 flex-shrink-0"
        >
          <RotateCcw size={13} className={busy ? 'animate-spin' : ''} /> Reparar
        </button>
      </div>
      {result && (
        <div className="text-xs text-ink-2 bg-bg-1/40 border border-line/40 rounded-md px-3 py-2">
          ✅ <b>{result.email}</b>: snapshots {result.snapshots_before} → {result.snapshots_after}
          {result.corrupt_removed > 0 && ` · ${result.corrupt_removed} corruptos eliminados`}
          {result.netdep_updated > 0 && ` · ${result.netdep_updated} net_deposited corregidos`}
        </div>
      )}
    </div>
  )
}

// ─── MassRepairPanel — reparar snapshots contaminados de TODOS los usuarios ──
function MassRepairPanel({ toast }) {
  const CHUNK = 50
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [progress, setProgress] = useState(null)

  async function runChunks(doApply) {
    let offset = 0, total = 1
    const agg = { users_changed: 0, snapshots_removed: 0, errors: [], total_users: 0 }
    do {
      const r = await api.post(`/admin/repair-snapshots-all?apply=${doApply}&offset=${offset}&limit=${CHUNK}`)
      total = r.total_all_users || 0
      agg.users_changed += r.users_changed || 0
      agg.snapshots_removed += r.snapshots_removed || 0
      agg.total_users = total
      if (r.errors?.length) agg.errors.push(...r.errors)
      offset += CHUNK
      setProgress({ done: Math.min(offset, total), total })
    } while (offset < total)
    return agg
  }

  async function simulate() {
    setLoading(true); setPreview(null); setProgress({ done: 0, total: 0 })
    try { setPreview(await runChunks(false)) }
    catch (e) { toast.push('Error al simular: ' + e.message, { type: 'error' }) }
    finally { setLoading(false); setProgress(null) }
  }

  async function apply() {
    if (!preview) return
    if (!confirm(`¿Reparar snapshots de ${preview.users_changed} cuenta${preview.users_changed === 1 ? '' : 's'}? ` +
                 `Borra solo los contaminados (los diarios legítimos quedan). Hacé un backup antes.`)) return
    setApplying(true); setProgress({ done: 0, total: 0 })
    try {
      const r = await runChunks(true)
      toast.push(`Reparado: ${r.users_changed} cuentas · ${r.snapshots_removed} snapshots contaminados eliminados`, { type: 'success' })
      await simulate()  // re-simular → debería dar 0 (idempotente)
    } catch (e) { toast.push('Error al aplicar: ' + e.message, { type: 'error' }) }
    finally { setApplying(false); setProgress(null) }
  }

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <RotateCcw size={16} className="text-rendi-warn" />
          <h2 className="font-semibold text-ink-0">Reparar snapshots de TODOS los usuarios</h2>
        </div>
        <button onClick={simulate} disabled={loading || applying}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> {preview ? 'Volver a simular' : 'Simular'}
        </button>
      </div>
      <p className="text-xs text-ink-3 leading-relaxed">
        El mismo repair que el de un usuario pero a <b>escala</b> — para que los % rotos (30d / anual / mes) se
        arreglen para todos sin que nadie tenga que escribir. Recalcula monthly, regenera los snapshots de fin de
        mes y borra <b>solo los contaminados</b> (V-shapes + outliers de trayectoria); los diarios legítimos
        quedan. <b>Simular</b> corre sobre una copia (no toca nada); recién <b>Aplicar</b> modifica. Para la curva
        a valor de mercado, después corré "Valuación histórica" (MTM). Hacé un backup antes.
      </p>
      {progress && progress.total > 0 && (loading || applying) && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-ink-3">
            <span>{applying ? 'Aplicando…' : 'Simulando…'}</span>
            <span className="tabular">{progress.done} / {progress.total} cuentas</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-bg-2 dark:bg-bg-2/40 overflow-hidden">
            <div className="h-full bg-rendi-warn transition-all" style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }} />
          </div>
        </div>
      )}
      {preview && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <ConvCell label="Cuentas a reparar" value={preview.users_changed} hint={`de ${preview.total_users}`} />
            <ConvCell label="Snapshots contaminados" value={preview.snapshots_removed} hint="se eliminan" />
          </div>
          {preview.errors?.length > 0 && (
            <div className="text-xs text-rendi-neg">{preview.errors.length} errores (ver logs del server)</div>
          )}
          <button onClick={apply} disabled={applying || loading || !preview.users_changed}
            className="w-full text-sm px-3 py-2 rounded-md bg-rendi-warn/15 text-rendi-warn hover:bg-rendi-warn/25 disabled:opacity-50">
            {applying ? 'Aplicando…' : `Aplicar a ${preview.users_changed} cuenta${preview.users_changed === 1 ? '' : 's'}`}
          </button>
        </>
      )}
    </div>
  )
}

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
