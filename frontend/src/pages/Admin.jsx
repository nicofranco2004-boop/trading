import { useEffect, useMemo, useRef, useState } from 'react'
import { Shield, Users, Activity, Database, Trash2, RefreshCw, Check, Clock, Sparkles, TrendingUp, RotateCcw, AlertTriangle, Mail, Send, Gift, Search } from 'lucide-react'
import { api } from '../utils/api'
import { filtrarFilas, contarCaen, contarFrenadas } from '../utils/fxPanel'
import StatCard from '../components/StatCard'
import { PageSkeleton } from '../components/Skeleton'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../components/Toast'

// Nombre de cada plan, en un solo lugar. Estaba escrito inline en tres sitios
// del grant y ninguno contemplaba 'advisor', asi que el Plan Asesor se
// anunciaba como Plus (en los confirms) o como Pro (en el mail al usuario).
const PLAN_LABEL = { free: 'Free', plus: 'Plus', pro: 'Pro', advisor: 'Asesor', admin: 'Admin' }

export default function Admin() {
  const { user } = useAuth()
  const [stats, setStats] = useState(null)
  const [users, setUsers] = useState([])
  const [conversion, setConversion] = useState(null)
  const [trialFunnel, setTrialFunnel] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)   // null = sin búsqueda activa
  const [searching, setSearching] = useState(false)
  const searchSeq = useRef(0)   // guard anti-carrera: sólo la última búsqueda pisa el estado
  const toast = useToast()

  useEffect(() => { load() }, [])

  // Búsqueda server-side (debounced) — encontrar a alguien entre miles sin scrollear.
  // Query vacío = null → la tabla vuelve a mostrar la lista completa.
  useEffect(() => {
    const q = query.trim()
    if (!q) { setSearchResults(null); setSearching(false); return }
    setSearching(true)
    const t = setTimeout(async () => {
      const seq = ++searchSeq.current    // esta corrida gana sobre las anteriores en vuelo
      try {
        const res = await runSearch(q) || []
        if (seq === searchSeq.current) setSearchResults(res)   // ignorá si ya hay una más nueva
      } catch (e) {
        if (seq === searchSeq.current) { setSearchResults([]); toast.push('Error buscando: ' + e.message, { type: 'error' }) }
      } finally {
        if (seq === searchSeq.current) setSearching(false)
      }
    }, 300)
    return () => clearTimeout(t)
  }, [query])

  async function load() {
    setLoading(true)
    setError('')
    try {
      const [s, u, c, t] = await Promise.all([
        api.get('/admin/stats'),
        api.get('/admin/users'),
        api.get('/admin/plan/conversion').catch(() => null),  // optional, no romper si falla
        api.get('/admin/billing/trial-funnel?days=90').catch(() => null),
      ])
      setStats(s)
      setUsers(u)
      setConversion(c)
      setTrialFunnel(t)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const [giftPickerFor, setGiftPickerFor] = useState(null)   // userId con el picker de plan abierto

  const SEARCH_LIMIT = 100   // tope del backend; si vienen 100 avisamos que refine
  function runSearch(q) {
    return api.get(`/admin/users/search?q=${encodeURIComponent(q)}&limit=${SEARCH_LIMIT}`)
  }

  // Tras una acción (regalar/aprobar/borrar/restaurar): recargar la lista y, si hay
  // una búsqueda activa, re-correrla para reflejar el cambio en los resultados.
  async function refresh() {
    await load()
    const q = query.trim()
    if (q) {
      const seq = ++searchSeq.current
      try { const res = await runSearch(q) || []; if (seq === searchSeq.current) setSearchResults(res) } catch { /* noop */ }
    }
  }

  async function approveUser(u) {
    if (!confirm(`¿Aprobar a ${u.email}? Una vez aprobado podrá iniciar sesión.`)) return
    try {
      await api.post(`/admin/users/${u.id}/approve`)
      refresh()
    } catch (e) {
      toast.push('Ocurrió un error: ' + e.message, { type: 'error' })
    }
  }

  async function deleteUser(u) {
    if (u.is_admin) return
    if (!confirm(`¿Eliminar la cuenta de ${u.email} junto a todos sus datos? Esta acción no se puede deshacer.`)) return
    try {
      await api.delete(`/admin/users/${u.id}`)
      refresh()
    } catch (e) {
      toast.push('Ocurrió un error: ' + e.message, { type: 'error' })
    }
  }

  async function grantComp(u, plan) {
    setGiftPickerFor(null)
    const days = 30
    // ⚠️ Antes: `plan === 'pro' ? 'Pro' : 'Plus'`. El Plan Asesor se sumó al
    // picker pero no acá, así que caía en el else: al regalar ASESOR, los dos
    // confirms y el toast decían "Plus". Nico apretó "Asesor" y leyó "Extender
    // 30 días → Plus", que es exactamente lo que NO quería hacer, y canceló.
    const planLabel = PLAN_LABEL[plan] || plan
    const esAsesor = plan === 'advisor'
    if (!confirm(
      `¿Dar ${planLabel} por ${days} días a ${u.email}? Es de cortesía (gratis) y se vence solo.`
      + (esAsesor ? '\n\nEl Plan Asesor REEMPLAZA el plan de usuario que tenga y le habilita Clientes.' : '')
    )) return
    const url = `/admin/billing/grant-comp?email=${encodeURIComponent(u.email)}&plan=${plan}&days=${days}`
    try {
      let res = await api.post(url)
      if (res?.ok === false && res?.reason === 'credit_already_active') {
        // El caso más común es querer SUBIR de plan (Plus→Pro) a alguien con un
        // plan vigente. El mensaje viejo decía solo "¿Sumar 30 días más?" — no
        // mencionaba el cambio de plan, así que el admin lo cancelaba y el grant
        // "no hacía nada". Ahora distingue upgrade de extensión y muestra la
        // fecha resultante exacta (la calcula el backend en would_be_active_until).
        const cur = res.current_plan
        const hasta = (res.credit_active_until || '').slice(0, 10)
        const nuevoHasta = (res.would_be_active_until || '').slice(0, 10)
        // Tres casos distintos, y antes dos se contaban como el mismo:
        //  1. Mismo plan            → es una EXTENSIÓN.
        //  2. Otro plan             → es un REEMPLAZO (el que tenía se va).
        //  3. Sin plan ancla (null) → tiene tiempo activo pero NINGÚN plan
        //     colgado: es el estado normal de quien está en prueba gratis (ver
        //     project_free_trial). Caía en la rama 1 y afirmaba "ya tiene Plus
        //     activo" sobre un usuario que la tabla de al lado muestra en free.
        let msg
        if (!cur) {
          msg = `${u.email} tiene un período activo hasta ${hasta}, sin plan asociado`
              + ` (típico de una prueba gratis).\n\n`
              + `Darle ${planLabel} lo reemplaza: queda ${planLabel} hasta ${nuevoHasta}.`
        } else if (cur !== plan) {
          msg = `${u.email} tiene ${PLAN_LABEL[cur] || cur} activo (vence ${hasta}).\n\n`
              + `Al darle ${planLabel}, ${PLAN_LABEL[cur] || cur} SE VA y queda ${planLabel} hasta ${nuevoHasta}.`
        } else {
          msg = `${u.email} ya tiene ${planLabel} activo (vence ${hasta}).\n\n`
              + `Extender ${days} días → ${planLabel} hasta ${nuevoHasta}.`
        }
        // Al CAMBIAR de plan los días arrancan hoy (pedido de Nico: "30 exactos"),
        // así que si le quedaba MÁS que eso, el cambio le acorta el vencimiento.
        // Es la única forma de que le saque algo sin querer → se avisa fuerte y
        // decide él, con las dos fechas a la vista.
        if (nuevoHasta && hasta && nuevoHasta < hasta) {
          msg += `\n\n⚠️ OJO: hoy le queda hasta ${hasta} y le va a quedar hasta ${nuevoHasta}.`
               + ` Le estás ACORTANDO el acceso (los ${days} días del plan nuevo arrancan hoy).`
        }
        if (esAsesor) msg += '\n\nAdemás le habilita Clientes y su cuenta pasa a ser el libro.'
        if (!confirm(msg)) return
        res = await api.post(url + '&force=true')
      }
      if (res?.ok) {
        toast.push(res.detail || `${planLabel} otorgado a ${u.email}.`, { type: 'success' })
      } else {
        toast.push(res?.detail || 'No se pudo otorgar el plan.', { type: 'warn' })
      }
      refresh()
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
      refresh()
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
  const searchActive = query.trim().length > 0
  const displayed = searchActive ? (searchResults || []) : users

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
      <TrialFunnelPanel data={trialFunnel} />

      {/* ── Broadcast: mail custom que vos escribís a los usuarios ── */}
      <BroadcastPanel toast={toast} />

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

      <FciRefreshPanel toast={toast} />
      <MtmAuditPanel toast={toast} />
      <FxMigratePanel toast={toast} />

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
        <div className="px-5 py-3 border-b border-line/50 flex items-center gap-2 flex-wrap">
          <Users size={16} className="text-ink-3" />
          <h2 className="font-semibold text-ink-0">
            Usuarios ({searchActive ? `${displayed.length} resultado${displayed.length === 1 ? '' : 's'}` : users.length})
          </h2>
          {affected.length > 0 && !searchActive && (
            <span className="ml-1 inline-flex items-center gap-1 text-[12px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-400 font-semibold">
              <AlertTriangle size={10} /> {affected.length} a restaurar
            </span>
          )}
          <div className="relative ml-auto">
            <input
              type="search"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Buscar por email, nombre o id…"
              className="w-64 max-w-full text-sm pl-3 pr-8 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 border border-line/60 focus:border-rendi-accent/60 outline-none text-ink-1 placeholder:text-ink-3"
            />
            <span className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-3">
              {searching ? <RefreshCw size={13} className="animate-spin" /> : <Search size={13} />}
            </span>
          </div>
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
              {searchActive && displayed.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-3 py-6 text-center text-ink-3 text-xs">
                    {searching ? 'Buscando…' : `Sin resultados para "${query.trim()}".`}
                  </td>
                </tr>
              )}
              {displayed.map(u => (
                <tr key={u.id} className="border-b border-line/50 dark:border-line/30 hover:bg-bg-2 dark:hover:bg-bg-2/20">
                  <td className="px-3 py-2 text-ink-3 font-mono text-xs">{u.id}</td>
                  <td className="px-3 py-2 font-medium text-ink-0">
                    {u.email}
                    {u.is_admin && <span className="ml-2 text-[12px] px-1.5 py-0.5 rounded bg-rendi-accent/15 text-rendi-accent font-semibold">admin</span>}
                    {!u.approved && <span className="ml-2 text-[12px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-400 font-semibold"><Clock size={10} className="inline -mt-0.5" /> Pendiente</span>}
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
                        giftPickerFor === u.id ? (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => grantComp(u, 'plus')}
                              className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-md bg-data-violet/20 text-data-violet hover:bg-data-violet/35"
                            >Plus</button>
                            <button
                              onClick={() => grantComp(u, 'pro')}
                              className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-md bg-data-violet/20 text-data-violet hover:bg-data-violet/35"
                            >Pro</button>
                            <button
                              onClick={() => grantComp(u, 'advisor')}
                              className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-md bg-data-violet/20 text-data-violet hover:bg-data-violet/35"
                              title="Plan Asesor (multi-cliente) — activa /clientes para este user"
                            >Asesor</button>
                            <button
                              onClick={() => setGiftPickerFor(null)}
                              className="text-xs text-ink-3 hover:text-ink-0 px-1"
                            >✕</button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setGiftPickerFor(u.id)}
                            className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-data-violet/15 text-data-violet hover:bg-data-violet/25"
                            title="Dar plan de regalo por 30 días (cortesía, se vence solo)"
                          >
                            <Gift size={12} /> Regalar
                          </button>
                        )
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
              {searchActive && displayed.length >= SEARCH_LIMIT && (
                <tr>
                  <td colSpan={10} className="px-3 py-2 text-center text-ink-3 text-[11px]">
                    Mostrando los primeros {SEARCH_LIMIT}. Si no aparece, refiná la búsqueda (probá el email completo).
                  </td>
                </tr>
              )}
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

// ─── BroadcastPanel — mail CUSTOM que el admin escribe, a los usuarios ────────
// Escribís asunto + cuerpo (texto plano; {nombre} se reemplaza). "Enviar prueba"
// te lo manda a vos primero. "Ver destinatarios" (dry-run) lista a quién le caería
// según el targeting. "Enviar" (confirm:true) manda a todos vía Resend. OJO: sin
// protección de duplicado — apretá "Enviar" una sola vez.
function BroadcastPanel({ toast }) {
  const { user } = useAuth()
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [plan, setPlan] = useState('')            // '' = todos
  const [onlyVerified, setOnlyVerified] = useState(true)
  const [branded, setBranded] = useState(true)
  const [testTo, setTestTo] = useState('')
  const [preview, setPreview] = useState(null)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState(null)

  const base = () => ({ subject, body, only_verified: onlyVerified, plan: plan || null, branded })
  const ready = subject.trim() && body.trim()

  async function loadPreview() {
    if (!ready) { toast.push('Escribí asunto y cuerpo primero.', { type: 'warn' }); return }
    setLoading(true); setResult(null)
    try { setPreview(await api.post('/admin/email/broadcast', { ...base(), confirm: false })) }
    catch (e) { toast.push('Error al previsualizar: ' + e.message, { type: 'error' }) }
    finally { setLoading(false) }
  }

  async function sendTest() {
    const addr = (testTo.trim() || user?.email || '').trim()
    if (!ready) { toast.push('Escribí asunto y cuerpo primero.', { type: 'warn' }); return }
    if (!addr) { toast.push('Poné un email de prueba.', { type: 'warn' }); return }
    setTesting(true)
    try {
      const r = await api.post('/admin/email/broadcast', { ...base(), test_to: addr })
      toast.push(r.note || (r.sent ? `Prueba enviada a ${addr}` : 'No se envió'),
        { type: r.sent ? 'success' : 'warn' })
    } catch (e) { toast.push('Error: ' + e.message, { type: 'error' }) }
    finally { setTesting(false) }
  }

  async function send() {
    const n = preview?.total_recipients || 0
    if (n === 0) return
    if (!confirm(`¿Enviar este mail a ${n} usuario${n > 1 ? 's' : ''}?\n\nReintentar el MISMO mail no duplica (los ya-enviados se saltean). Cambiarle el texto lo manda de nuevo.`)) return
    setSending(true)
    try {
      const r = await api.post('/admin/email/broadcast', { ...base(), confirm: true })
      setResult(r); setPreview(null)
      toast.push(`Enviados ${r.sent_count}`
        + (r.failed_count ? ` · ${r.failed_count} fallados` : '')
        + (r.skipped_count ? ` · ${r.skipped_count} ya-enviados` : ''),
        { type: r.failed_count ? 'warn' : 'success' })
    } catch (e) { toast.push('Error al enviar: ' + e.message, { type: 'error' }) }
    finally { setSending(false) }
  }

  const recipients = preview?.recipients || []
  const inputCls = 'w-full text-sm px-3 py-2 rounded-md bg-bg-2 dark:bg-bg-2/40 border border-line/60 focus:border-data-violet/60 outline-none text-ink-1 placeholder:text-ink-3'

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <Send size={16} className="text-data-violet" />
        <h2 className="font-semibold text-ink-0">Email a usuarios · escribí el tuyo</h2>
      </div>

      <div className="space-y-3">
        <input value={subject} onChange={e => { setSubject(e.target.value); setPreview(null) }}
          placeholder="Asunto" className={inputCls} maxLength={200} />
        <textarea value={body} onChange={e => { setBody(e.target.value); setPreview(null) }}
          placeholder="Escribí el cuerpo del mail…&#10;&#10;Un párrafo por línea en blanco. Podés poner links (https://rendi.finance)."
          rows={7} className={inputCls + ' resize-y font-normal leading-relaxed'} maxLength={20000} />
        <p className="text-[11px] text-ink-3">
          <code className="px-1 rounded bg-bg-1/60">{'{nombre}'}</code> se reemplaza por el nombre de cada usuario (vacío si no tiene). El texto va como párrafos; los links se activan solos.
        </p>
      </div>

      <div className="flex items-center gap-3 flex-wrap text-[12px] text-ink-2 pt-1 border-t border-line/30">
        <label className="flex items-center gap-1.5">Plan:
          <select value={plan} onChange={e => { setPlan(e.target.value); setPreview(null) }}
            className="bg-bg-2 dark:bg-bg-2/40 border border-line/60 rounded px-2 py-1 text-ink-1">
            <option value="">Todos</option><option value="free">Free</option>
            <option value="plus">Plus</option><option value="pro">Pro</option>
          </select>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={onlyVerified} onChange={e => { setOnlyVerified(e.target.checked); setPreview(null) }} className="accent-data-violet" />
          Solo verificados
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={branded} onChange={e => setBranded(e.target.checked)} className="accent-data-violet" />
          Con diseño Rendi (header/footer)
        </label>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <input value={testTo} onChange={e => setTestTo(e.target.value)}
          placeholder={user?.email ? `Prueba a ${user.email}` : 'tu@email.com'}
          className={inputCls + ' flex-1 min-w-[180px]'} />
        <button onClick={sendTest} disabled={testing || !ready}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-1 hover:text-ink-0 border border-line/60 disabled:opacity-40">
          <Mail size={13} /> {testing ? 'Enviando…' : 'Enviar prueba a mí'}
        </button>
        <button onClick={loadPreview} disabled={loading || !ready}
          className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-1 hover:text-ink-0 border border-line/60 disabled:opacity-40">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Ver destinatarios
        </button>
      </div>

      {preview && (
        <div className="space-y-3 pt-1 border-t border-line/30">
          <p className="text-sm text-ink-1">
            Le caería a <b className="text-data-violet">{preview.total_recipients}</b> usuario{preview.total_recipients === 1 ? '' : 's'}
            {preview.plan ? ` (plan ${preview.plan})` : ''}{preview.only_verified ? ' · verificados' : ''}.
          </p>
          {recipients.length > 0 && (
            <div className="max-h-56 overflow-y-auto border border-line/40 rounded-sm bg-bg-1/40">
              <table className="w-full text-xs">
                <thead><tr className="border-b border-line/40 text-ink-3 sticky top-0 bg-bg-2/80 backdrop-blur">
                  <th className="text-left px-2 py-1">Email</th><th className="text-left px-2 py-1">Nombre</th><th className="text-left px-2 py-1">Plan</th>
                </tr></thead>
                <tbody>{recipients.map(r => (
                  <tr key={r.id} className="border-b border-line/20">
                    <td className="px-2 py-1 text-ink-1">{r.email}</td>
                    <td className="px-2 py-1 text-ink-2">{r.name || '—'}</td>
                    <td className="px-2 py-1 text-ink-3">{r.plan}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {preview.truncated && <p className="text-[11px] text-ink-3">Mostrando los primeros 500 · se envía a todos.</p>}
          <div className="flex justify-end">
            <button onClick={send} disabled={sending || preview.total_recipients === 0}
              className="flex items-center gap-1.5 text-sm px-3.5 py-2 rounded-md bg-data-violet text-white font-medium hover:bg-data-violet/90 disabled:opacity-40 press">
              <Send size={14} /> {sending ? 'Enviando…' : `Enviar a ${preview.total_recipients}`}
            </button>
          </div>
        </div>
      )}

      {result && (
        <div className="text-xs text-ink-2 bg-bg-1/40 border border-line/40 rounded-sm px-3 py-2">
          <b className="text-emerald-600 dark:text-emerald-400">{result.sent_count} enviados</b>
          {result.failed_count > 0 && <> · <b className="text-red-500">{result.failed_count} fallados</b></>}
          {result.skipped_count > 0 && <> · <b className="text-ink-3">{result.skipped_count} ya-enviados (dedup)</b></>}
        </div>
      )}
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
//   • El backend excluye SIEMPRE a los que están en su prueba gratis y los
//     reporta en excluded_in_trial: su crédito no tiene anchor, así que pasaban
//     por "comp activo" y recibían el mail en la mitad de la prueba.
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
        Los que están en su <b>prueba gratis</b> quedan siempre afuera: el mail les ofrecería de regalo lo que ya tienen,
        y la prueba trae su propia secuencia de avisos.
      </p>

      <label className="flex items-center gap-1.5 text-[11px] text-ink-3 cursor-pointer select-none">
        <input type="checkbox" checked={onlyGifted} onChange={e => setOnlyGifted(e.target.checked)} className="accent-emerald-500" />
        Solo a quienes tienen el regalo (Pro/Plus) activo
      </label>

      {preview && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <ConvCell label="Candidatos" value={preview.total_candidates} hint="≤1 operación" />
            <ConvCell label="Con regalo activo" value={preview.with_gift} hint="comp Pro/Plus vigente" />
            {/* Se muestra para que el número no se caiga en silencio: son los que
                quedaron afuera por estar en su prueba gratis. */}
            <ConvCell label="En prueba gratis" value={preview.excluded_in_trial ?? 0} hint="excluidos: ya lo tienen" />
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
                          ? <span className="text-emerald-600 dark:text-emerald-400 font-semibold">{r.tier}</span>
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
        className="inline-flex items-center gap-1 text-[12px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-400 font-semibold"
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
    // El Asesor se distingue del resto a propósito: no es un escalón más de la
    // escalera Free→Plus→Pro, es otro producto (multi-cliente).
    advisor: 'bg-data-violet/25 text-data-violet ring-1 ring-data-violet/40',
    free: 'bg-bg-2 text-ink-3 dark:bg-bg-2/60',
  }
  const cls = styles[plan] || styles.free
  const etiqueta = plan === 'advisor' ? 'asesor' : (plan || 'free')
  const showDays = creditActive && plan !== 'free' && plan !== 'admin' && daysRemaining != null
  const lowDays = showDays && daysRemaining <= 5
  return (
    <span className={`inline-flex items-center text-[12px] px-1.5 py-0.5 rounded font-semibold ${cls}`}>
      {etiqueta}
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

// ─── FciRefreshPanel — re-seedear el catálogo de FCI ────────────────────────
// El catálogo sale de una allowlist por nombre exacto (backend/pricing/fci.py) y
// se seedea con un cron diario. Cuando se suman fondos —pasa cada vez que un
// usuario reporta "falta el mío"— hay que esperar al cron o dispararlo a mano.
// El endpoint existía pero es POST-only: sin botón, en la práctica había que
// esperar 24h para que el usuario que reportó pudiera cargar su fondo.
function FciRefreshPanel({ toast }) {
  const [r, setR] = useState(null)
  const [busy, setBusy] = useState(false)

  async function refrescar() {
    setBusy(true)
    try {
      const out = await api.post('/admin/fci/refresh')
      setR(out)
      toast.push('Catálogo FCI actualizado', { type: 'success' })
    } catch (e) {
      toast.push('Error: ' + e.message, { type: 'error' })
    } finally { setBusy(false) }
  }

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <RefreshCw size={16} className="text-violet-500" />
          <h2 className="font-semibold text-ink-0">Catálogo FCI</h2>
        </div>
        <button onClick={refrescar} disabled={busy}
          className="text-xs px-3 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-50">
          {busy ? 'Actualizando…' : 'Re-seedear y refrescar precios'}
        </button>
      </div>
      <p className="text-xs text-ink-3 leading-relaxed">
        Vuelve a leer la allowlist de <code>pricing/fci.py</code> contra ArgentinaDatos y
        actualiza las cuotapartes. Corrélo después de sumar fondos nuevos — si no, hay que
        esperar al cron diario para que el usuario que los pidió pueda cargarlos.
      </p>
      {r && (
        <p className="text-xs text-emerald-500 tabular">
          {Object.entries(r).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' · ')}
        </p>
      )}
    </div>
  )
}


// ─── MtmAuditPanel — reconcilia la cadena a COSTO contra la de MERCADO ──────
// Existe porque después de portar el parche MtM a Insights, la MISMA cuenta
// mostraba dos números incompatibles: Dashboard "Anual +18,4% · 19 meses"
// (cadena a costo) contra Insights "Acumulado histórico −5,2%" (cadena a
// mercado), y el drawdown máximo pasó de −8,7% a −26,5%. No se puede decidir
// cuál está mal leyendo el código: hay que ver los meses.
// Va como BOTÓN y no como link al endpoint porque abrir la URL del backend a
// mano no lleva la sesión ("Token inválido") — mismo pozo que el cleanup.
function MtmAuditPanel({ toast }) {
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  // Segundo nivel: bajar la "Diferencia sin explicar" de un mes a la OPERACIÓN.
  const [mes, setMes] = useState('')
  const [gap, setGap] = useState(null)

  async function correr() {
    setBusy(true)
    try {
      setData(await api.get('/insights/mtm-audit'))
    } catch (e) {
      toast.push('Error: ' + e.message, { type: 'error' })
    } finally { setBusy(false) }
  }

  const pct = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)

  async function verMes(m) {
    setMes(m); setBusy(true); setGap(null)
    try {
      setGap(await api.get(`/insights/gap-month?mes=${m}`))
    } catch (e) { toast.push('Error: ' + e.message, { type: 'error' }) }
    finally { setBusy(false) }
  }

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Activity size={16} className="text-violet-500" />
          <h2 className="font-semibold text-ink-0">Costo vs Mercado — reconciliación mensual</h2>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <button
              onClick={() => { navigator.clipboard?.writeText(JSON.stringify(data, null, 1)); toast.push('JSON copiado') }}
              className="text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0">
              Copiar JSON
            </button>
          )}
          <button onClick={correr} disabled={busy}
            className="text-xs px-3 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-50">
            {busy ? 'Calculando…' : 'Reconciliar mi cuenta'}
          </button>
        </div>
      </div>
      <p className="text-xs text-ink-3 leading-relaxed">
        Compara, mes por mes, el retorno que sale de <b>monthly_entries</b> (a costo: los meses
        cerrados llevan <code>pnl_unrealized = 0</code>) contra el que sale de los <b>snapshots</b>
        {' '}(a mercado). Solo lee. Sirve para decidir cuál de las dos cadenas está mal cuando
        Dashboard e Insights se contradicen.
      </p>

      {data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Acumulado a COSTO" value={pct(data.acumulado_costo_pct)} />
            <StatCard label="Acumulado a MERCADO" value={pct(data.acumulado_mercado_pct)} />
            <StatCard label="Meses" value={`${data.meses}`} />
            <StatCard label="Meses con snapshot" value={`${data.snapshots_por_mes}`} />
          </div>
          {/* EL DATO QUE DECIDE: si las dos fuentes discrepan en los FLUJOS, el
              parche está mezclando fuentes (valores de una, flujos de la otra) y
              el desencuentro entra como retorno inventado. Si coinciden, la
              brecha de nivel es no-realizado genuino y la cadena de mercado es
              la que tiene razón. */}
          {data.veredicto && (
            <p className={`text-xs font-medium ${
              (data.meses_con_fuentes_distintas || []).length ? 'text-red-400' : 'text-emerald-500'}`}>
              {data.veredicto}
              {(data.meses_con_fuentes_distintas || []).length > 0 && (
                <span className="block font-normal text-ink-2 mt-1">
                  {data.meses_con_fuentes_distintas.map(x =>
                    `${x.mes}: ΔG ${x.delta_G} (${x.pct}% del capital) → ${x.delta_pp}pp`
                  ).join(' · ')}
                </span>
              )}
            </p>
          )}
          {/* ⚠️ LO MÁS IMPORTANTE DEL PANEL. `_backfill_snapshots_from_monthly`
              fabrica snapshots de fin de mes con total_value = capital_final (la
              cadena a COSTO) y total_invested = net_deposited acumulado. Para esos
              meses la columna "mercado" NO es mercado: es la contabilidad
              congelada en el momento del backfill. Se reconocen porque no tienen
              ni blue ni composición — el cron sí los escribe. */}
          {data.snapshots_sinteticos?.meses?.length > 0 && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 space-y-1">
              <p className="text-xs text-red-400 font-medium">
                {data.snapshots_sinteticos.meses.length} mes(es) con snapshot SINTÉTICO —
                su columna "mercado" no es mercado: {data.snapshots_sinteticos.meses.join(', ')}
              </p>
              <p className="text-[11px] text-ink-3">{data.snapshots_sinteticos.prediccion}</p>
              <p className="text-[11px] text-ink-2">
                Predicción verificada en <b>{data.snapshots_sinteticos.aciertos}</b> de los meses
                sintéticos con ΔG medible:{' '}
                {data.snapshots_sinteticos.verificacion.map(v =>
                  `${v.mes} ΔG ${v.delta_G} vs realizado ${v.realizado}${v.coincide ? ' ✓' : ' ✗'}`
                ).join(' · ')}
              </p>
            </div>
          )}
          {data.meses_sin_cobertura?.length > 0 && (
            <p className="text-xs text-amber-500">
              <b>{data.meses_sin_cobertura.length} mes(es) sin cobertura de snapshots</b> — quedan a
              costo: {data.meses_sin_cobertura.join(', ')}
            </p>
          )}
          {gap && (
            <div className="rounded-lg border border-violet-500/30 bg-violet-500/5 p-3 space-y-2">
              <p className="text-xs text-ink-1">
                <b>{gap.mes}</b> — flujos {gap.identidad.flujos} · realizado {gap.identidad.realizado_del_mes}
                {' '}· Δcosto {gap.identidad.delta_costo ?? '—'} · <b>ΔG {gap.identidad.delta_G ?? '—'}</b>
              </p>
              <p className="text-[11px] text-ink-3">{gap.identidad.lectura}</p>
              {/* Triangular el "realizado" del mes por sus tres caminos aísla el
                  eslabón roto: si la cadena no coincide con lo guardado,
                  capital_final no cierra con su propia fórmula; si lo guardado no
                  coincide con las operaciones, el cache quedó desincronizado. */}
              {gap.realizado_triangulado && (() => {
                const t = gap.realizado_triangulado
                const rompeCadena = Math.abs(t.cadena_vs_guardado) > 1
                const rompeOps = Math.abs(t.guardado_vs_operaciones) > 1
                return (
                  <div className="rounded-md border border-line/60 p-2 space-y-1">
                    <p className="text-[11px] text-ink-2">
                      Realizado del mes por tres caminos: cadena <b>{t.implicito_por_la_cadena}</b>
                      {' '}· guardado <b>{t.guardado_en_monthly}</b> · operaciones <b>{t.suma_de_operaciones}</b>
                    </p>
                    <p className={`text-[11px] font-medium ${rompeCadena || rompeOps ? 'text-red-400' : 'text-emerald-500'}`}>
                      {rompeCadena
                        ? `capital_final NO cierra con su fórmula: sobran ${t.cadena_vs_guardado}`
                        : rompeOps
                          ? `el realizado guardado no coincide con las operaciones: difieren ${t.guardado_vs_operaciones}`
                          : 'los tres coinciden'}
                    </p>
                  </div>
                )
              })()}
              {/* El color sigue al VEREDICTO, no a "cero sospechosas": un mes sin
                  operaciones, o con operaciones que no se pueden verificar, no es
                  verde — es "no sé". */}
              <p className={`text-xs font-medium ${
                gap.sospechosas ? 'text-red-400'
                  : gap.verificables > 0 ? 'text-emerald-500' : 'text-amber-500'}`}>
                {gap.veredicto}
              </p>
              {/* Si el P&L por operación está bien, lo que se movió fue la TENENCIA.
                  El diff de holdings entre los dos cierres nombra el activo, y el
                  blue estampado descarta (o no) al FX con un número. */}
              <p className="text-[11px] text-ink-2">
                Blue {gap.fx?.blue_ini ?? '—'} → {gap.fx?.blue_fin ?? '—'}
                {gap.fx?.variacion_pct != null && (
                  <b className={Math.abs(gap.fx.variacion_pct) < 2 ? ' text-ink-3' : ' text-amber-500'}>
                    {' '}({gap.fx.variacion_pct > 0 ? '+' : ''}{gap.fx.variacion_pct}%)
                  </b>
                )} — {gap.fx?.lectura}
              </p>
              {/* LA HIPÓTESIS FUERTE: futuros, dividendos e intereses suman P&L
                  realizado sin mover el costo de la tenencia. Si su total se
                  parece al ΔG del mes, la causa es ésa. */}
              {gap.pnl_sin_contrapartida_de_costo?.operaciones?.length > 0 && (
                <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 space-y-1">
                  <p className="text-[11px] text-amber-500 font-medium">
                    P&L sin contrapartida de costo: US$ {gap.pnl_sin_contrapartida_de_costo.total}
                    {gap.pnl_sin_contrapartida_de_costo.explica_del_delta_G_pct != null && (
                      <> — explica el <b>{gap.pnl_sin_contrapartida_de_costo.explica_del_delta_G_pct}%</b> del ΔG</>
                    )}
                  </p>
                  <p className="text-[10px] text-ink-3">{gap.pnl_sin_contrapartida_de_costo.lectura}</p>
                  <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-ink-2">
                    {gap.pnl_sin_contrapartida_de_costo.operaciones.map((o, i) => (
                      <span key={i} className="tabular">
                        {o.fecha} <b>{o.activo}</b> ({o.tipo}) {o.pnl_usd > 0 ? '+' : ''}{o.pnl_usd}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {gap.sin_composicion_guardada && (
                <p className="text-[11px] text-ink-3">
                  Sin composición guardada en alguno de los dos cierres — no se puede diffear la
                  tenencia de este mes (los snapshots viejos no guardaban <code>holdings_json</code>).
                </p>
              )}
              {gap.movimientos_de_tenencia?.length > 0 && (
                <div className="overflow-x-auto">
                  <p className="text-[11px] text-ink-2 font-medium mb-1">Qué se movió en la tenencia</p>
                  <table className="w-full text-[11px]">
                    <tbody>
                      {gap.movimientos_de_tenencia.filter(m => m.evento || Math.abs(m.delta) > 50).map(m => (
                        <tr key={m.activo} className="border-b border-line/30">
                          <td className="py-1 pr-2 font-medium">{m.activo}</td>
                          <td className="py-1 pr-2 text-right tabular text-ink-3">
                            {m.valor_ini ?? '—'} → {m.valor_fin ?? '—'}
                          </td>
                          <td className="py-1 pr-2 text-right tabular">{m.delta}</td>
                          <td className={`py-1 ${m.evento ? 'text-amber-500 font-medium' : 'text-ink-3'}`}>
                            {m.evento}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {gap.las_sin_verificar?.length > 0 && (
                <p className="text-[11px] text-ink-3">
                  <b>Sin verificar:</b>{' '}
                  {gap.las_sin_verificar.map(o => `${o.fecha} ${o.activo} (${o.tipo || '—'})`).join(' · ')}
                </p>
              )}
              {gap.las_sospechosas?.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="text-ink-3 text-left border-b border-line/60">
                        <th className="py-1 pr-2">Fecha</th><th className="py-1 pr-2">Activo</th>
                        <th className="py-1 pr-2 text-right">Precio</th>
                        <th className="py-1 pr-2 text-right">P&L US$</th>
                        <th className="py-1 pr-2 text-right">% guardado</th>
                        <th className="py-1 pr-2 text-right">% por precios</th>
                        <th className="py-1 text-right">Desvío</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gap.las_sospechosas.map(o => (
                        <tr key={o.id} className="border-b border-line/30">
                          <td className="py-1 pr-2 tabular">{o.fecha}</td>
                          <td className="py-1 pr-2">{o.activo} <span className="text-ink-3">({o.broker})</span></td>
                          <td className="py-1 pr-2 text-right tabular text-ink-3">{o.precio_entrada} → {o.precio_salida}</td>
                          <td className="py-1 pr-2 text-right tabular">{o.pnl_usd}</td>
                          <td className="py-1 pr-2 text-right tabular text-red-400">{o.pnl_pct_guardado}%</td>
                          <td className="py-1 pr-2 text-right tabular">{o.pnl_pct_por_precios}%</td>
                          <td className="py-1 text-right tabular text-red-400">{o.desvio_pp}pp</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-ink-3 text-left border-b border-line/60">
                  <th className="py-1.5 pr-3">Mes</th>
                  <th className="py-1.5 pr-3">Modo</th>
                  <th className="py-1.5 pr-3 text-right">Costo ci→cf</th>
                  <th className="py-1.5 pr-3 text-right">r costo</th>
                  <th className="py-1.5 pr-3 text-right">Mercado ci→cf</th>
                  <th className="py-1.5 pr-3 text-right">r mercado</th>
                  <th className="py-1.5 pr-3 text-right">Flujo</th>
                  <th className="py-1.5 pr-3 text-right" title="capital_final − total_invested: las 2 bases de COSTO, sin componente de mercado">ΔG</th>
                  <th className="py-1.5 text-right">Δ</th>
                </tr>
              </thead>
              <tbody>
                {(data.detalle || []).map(o => (
                  <tr key={o.mes} className="border-b border-line/30">
                    <td className="py-1.5 pr-3 tabular">
                      <button onClick={() => verMes(o.mes)}
                        className="underline decoration-dotted hover:text-violet-400"
                        title="Ver de qué operación sale la diferencia de este mes">
                        {o.mes}
                      </button>
                    </td>
                    <td className="py-1.5 pr-3 text-ink-3">{o.modo}</td>
                    <td className="py-1.5 pr-3 text-right tabular text-ink-3">{o.costo.ci} → {o.costo.cf}</td>
                    <td className="py-1.5 pr-3 text-right tabular">{pct(o.costo.r_pct)}</td>
                    <td className="py-1.5 pr-3 text-right tabular text-ink-3">{o.mercado.ci} → {o.mercado.cf}</td>
                    <td className="py-1.5 pr-3 text-right tabular">{pct(o.mercado.r_pct)}</td>
                    <td className="py-1.5 pr-3 text-right tabular text-ink-3">{o.net_flow}</td>
                    <td className={`py-1.5 pr-3 text-right tabular ${
                      o.delta_G_pct == null ? 'text-ink-3'
                        : Math.abs(o.delta_G_pct) > 2 ? 'text-red-400 font-medium' : 'text-ink-3'}`}>
                      {o.delta_G_pct == null ? '—' : `${o.delta_G_pct}%`}
                    </td>
                    <td className={`py-1.5 text-right tabular font-medium ${
                      o.delta_pp == null ? 'text-ink-3'
                        : o.delta_pp < -10 ? 'text-red-400'
                        : o.delta_pp > 10 ? 'text-emerald-500' : 'text-ink-2'}`}>
                      {o.delta_pp == null ? '—' : `${o.delta_pp > 0 ? '+' : ''}${o.delta_pp}pp`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}


// ─── FxMigratePanel — migrar cuentas al TC histórico (dólar de la fecha de cada op) ──
// Las cuentas viejas tienen TODO dolarizado al dólar del día en que importaron (medido:
// un usuario con 370 ventas de 10 años, todas al mismo 1415). El motor nuevo usa el TC
// de la fecha de cada operación, pero cada cuenta migra ENTERA (ventas + depósitos
// juntos) o no migra: por eso es cuenta por cuenta, con simulación previa.
function FxMigratePanel({ toast }) {
  const [cands, setCands] = useState(null)        // resultado de /candidates
  const [sel, setSel] = useState(new Set())       // user_ids seleccionados
  const [sims, setSims] = useState({})            // uid -> resultado del dry-run
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(null)    // 'sim' | 'apply' | null
  const [progress, setProgress] = useState(null)
  const [futuros, setFuturos] = useState(null)    // snapshots con fecha futura
  const [stale, setStale] = useState(false)      // el bundle del browser quedó viejo

  // El auto-update no recarga mientras estás trabajando (por diseño), así que se
  // puede simular 400 cuentas con código viejo y no enterarse. Acá el panel
  // compara su propio build contra el del server y avisa ANTES de que confíes en
  // un resultado calculado con reglas que ya cambiaron.
  useEffect(() => {
    let vivo = true
    fetch(`/version.json?t=${Date.now()}`, { cache: 'no-store', credentials: 'omit' })
      .then(r => (r.ok ? r.json() : null))
      .then(d => {
        const mio = (typeof __BUILD_ID__ !== 'undefined' && __BUILD_ID__) || null
        if (vivo && d?.version && mio && d.version !== mio) setStale(true)
      })
      .catch(() => {})
    return () => { vivo = false }
  }, [])

  const [aportado, setAportado] = useState(null)

  // Abre el desglose del aportado por año de UNA cuenta. Es la evidencia que la
  // simulación no da: si los DEPOSIT son de años viejos (TC bajo) y los WITHDRAW
  // de años recientes (TC alto), el salto es real — esa plata entró cuando el
  // dólar valía menos. Si depósitos y retiros son del MISMO año y el neto igual
  // explota, hay que mirar si son transferencias internas contadas como flujo.
  async function verAportado(userId) {
    setAportado({ user_id: userId, loading: true })
    try {
      setAportado(await api.get(`/admin/fx-aportado-breakdown?user_id=${userId}`))
    } catch (e) {
      toast.push('Error: ' + e.message, { type: 'error' })
      setAportado(null)
    }
  }

  async function cargar(preserveSims = false) {
    setLoading(true)
    try {
      const r = await api.get('/admin/fx-migrate-candidates')
      setCands(r)
      // La verificación de lo recién aplicado es el mecanismo de seguridad del
      // flujo: NO se borra al refrescar estados (solo con "Recargar" manual).
      if (!preserveSims) { setSims({}); setSel(new Set()) }
    } catch (e) { toast.push('Error al cargar: ' + e.message, { type: 'error' }) }
    finally { setLoading(false) }
  }

  const migrables = (cands?.cuentas || []).filter(c => c.fx_version === 'v1' && !c.bloqueada_por_escala)

  // ── Encontrar algo entre 497 filas ────────────────────────────────────────
  // Con la lista ordenada por cantidad de ventas, las cuentas que hay que mirar
  // (las que más le mueven el rendimiento al usuario) quedan desparramadas entre
  // las que no cambian nada. Buscador + orden por caída + filtros.
  const [buscar, setBuscar] = useState('')
  const [orden, setOrden] = useState('default')   // 'default' | 'caida'
  const [filtro, setFiltro] = useState('todas')   // 'todas' | 'caen' | 'frenadas' | 'sinsim'

  const filas = useMemo(
    () => filtrarFilas(cands?.cuentas, sims, { buscar, orden, filtro }),
    [cands, sims, buscar, orden, filtro])
  const nCaen = useMemo(() => contarCaen(cands?.cuentas, sims), [cands, sims])
  const nFrenadas = useMemo(() => contarFrenadas(cands?.cuentas, sims), [cands, sims])

  // Snapshots con fecha FUTURA: el backfill de fin de mes los escribía también
  // para el mes en curso, con el capital SIN ganancia no realizada. Como el
  // "último snapshot" se elige por fecha máxima, ese punto define el AUM del
  // asesor y la punta del gráfico hasta fin de mes. Ya no se generan; esto
  // limpia los que quedaron.
  async function limpiarFuturos(apply) {
    if (apply && !confirm(`¿Borrar ${futuros?.snapshots_futuros} snapshot(s) con fecha futura ` +
                          `de ${futuros?.cuentas} cuenta(s)? Un snapshot fechado en el futuro es ` +
                          `incorrecto por definición: lo reemplazan el diario del cron y el de ` +
                          `fin de mes cuando el mes cierre.`)) return
    setRunning('cleanup')
    try {
      const r = await api.post(`/admin/cleanup-future-snapshots?apply=${apply}`)
      setFuturos(r)
      if (apply) toast.push(`Limpiados ${r.snapshots_futuros} snapshots futuros`, { type: 'success' })
    } catch (e) { toast.push('Error: ' + e.message, { type: 'error' }) }
    finally { setRunning(null) }
  }

  // Semáforo de la verificación: rojo si CUALQUIER señal falla, no solo el cash.
  function nivelVerif(s) {
    if (!s?.ok || !s.verificacion) return null
    const v = s.verificacion
    const [ok, tot] = String(v.ventas_al_tc_de_su_fecha || '0/0').split('/').map(Number)
    if (!v.cash_intacto || (v.ventas_con_tc_distinto || []).length > 0 ||
        (s.rebuild?.errores || []).length > 0 || (tot > 0 && ok < tot) ||
        v.delta_pnl_implausible) return 'rojo'
    if (v.en_pares_salteados > 0 || v.sin_serie_fx > 0 ||
        (v.flujos_manuales_usd_no_migrables || 0) > 0) return 'ambar'
    return 'verde'
  }

  function toggle(uid) {
    const s = new Set(sel)
    s.has(uid) ? s.delete(uid) : s.add(uid)
    setSel(s)
  }

  async function correr(apply, force = false) {
    const ids = [...sel]
    if (!ids.length) return
    if (apply) {
      const sinSim = ids.filter(id => !sims[id]?.ok)
      const rojas = ids.filter(id => nivelVerif(sims[id]) === 'rojo')
      if (rojas.length) {
        // La simulación de estas cuentas FALLÓ su propia verificación: no se
        // aplican en tanda, punto. Se destildan y se sigue con el resto.
        toast.push(`${rojas.length} cuenta(s) con verificación en ROJO quedan fuera: ` +
                   rojas.map(id => '#' + id).join(', '), { type: 'error' })
        const limpio = ids.filter(id => !rojas.includes(id))
        setSel(new Set(limpio))
        if (!limpio.length) return
        ids.length = 0; ids.push(...limpio)
      }
      if (sinSim.length && !confirm(`${sinSim.length} cuenta(s) sin simulación previa. ¿Aplicar igual?`)) return
      const dPnl = ids.reduce((a, id) => a + (sims[id]?.delta?.pnl_ventas_usd || 0), 0)
      const dDep = ids.reduce((a, id) => a + ((sims[id]?.delta?.deposits_usd || 0) - (sims[id]?.delta?.withdrawals_usd || 0)), 0)
      if (!confirm(`¿Migrar ${ids.length} cuenta(s) al TC histórico?\n` +
                   `Δ P&L de ventas (simulado): US$ ${Math.round(dPnl).toLocaleString()}\n` +
                   `Δ Aportado neto (simulado): US$ ${Math.round(dDep).toLocaleString()}\n` +
                   `El % por operación NO cambia. Hacé un backup antes.`)) return
    }
    setRunning(apply ? 'apply' : 'sim')
    setProgress({ done: 0, total: ids.length })
    const out = { ...sims }

    // Simular = UNA sola copia de la base para todo el lote (el endpoint por
    // cuenta copia la base entera cada vez: 579 cuentas = 579 copias).
    if (!apply) {
      // En TANDAS: el batch copia la base una vez por request, así que mandar 497
      // cuentas en un solo pedido se pasa del timeout del proxy (~30s) y se pierde
      // todo. De a 25 cada request queda corto, y si una tanda falla se reporta
      // sola sin arrastrar a las demás.
      const CHUNK = 25
      let fallidas = 0
      for (let i = 0; i < ids.length; i += CHUNK) {
        const tanda = ids.slice(i, i + CHUNK)
        try {
          const r = await api.post('/admin/fx-migrate-batch', { user_ids: tanda })
          for (const [k, v] of Object.entries(r.resultados || {})) out[k] = v
        } catch (e) {
          fallidas += tanda.length
          for (const id of tanda) out[id] = { ok: false, motivo: 'no se pudo simular: ' + e.message }
        }
        setSims({ ...out })
        setProgress({ done: Math.min(i + CHUNK, ids.length), total: ids.length })
      }
      if (fallidas) toast.push(`${fallidas} cuenta(s) no se pudieron simular — reintentá esas`, { type: 'error' })
      setRunning(null); setProgress(null)
      return
    }

    for (let i = 0; i < ids.length; i++) {
      try {
        out[ids[i]] = await api.post(`/admin/fx-migrate-user?user_id=${ids[i]}&apply=${apply}${force ? '&force=true' : ''}`)
      } catch (e) {
        const msg = String(e.message || '')
        if (apply && msg.includes('ya está en v2')) {
          // El apply anterior llegó al server aunque la conexión se haya cortado
          // (timeout del proxy): "ya está en v2" en un RETRY significa ÉXITO.
          out[ids[i]] = { ok: true, applied: true, motivo: 'migrada (el intento anterior había llegado)' }
        } else {
          out[ids[i]] = { ok: false, motivo: msg + (apply
            ? ' — OJO: si fue un timeout, la migración puede haber terminado igual en el servidor; recargá y fijate si quedó v2.'
            : '') }
        }
      }
      setProgress({ done: i + 1, total: ids.length })
      setSims({ ...out })
    }
    setRunning(null); setProgress(null)
    if (apply) {
      const okN = ids.filter(id => out[id]?.ok && out[id]?.applied).length
      toast.push(`Migradas ${okN}/${ids.length} cuentas`, { type: okN === ids.length ? 'success' : 'error' })
      await cargar(true)   // refrescar estados v1/v2 SIN borrar la verificación
    }
  }

  const fmt = (n) => (n == null ? '—' : Math.round(n).toLocaleString())

  return (
    <div className="bg-white dark:bg-bg-2/60 border border-line/80 dark:border-line/50 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <RefreshCw size={16} className="text-violet-500" />
          <h2 className="font-semibold text-ink-0">Migración FX — TC de la fecha de cada operación</h2>
        </div>
        <button onClick={cargar} disabled={loading || !!running}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> {cands ? 'Recargar' : 'Cargar cuentas'}
        </button>
      </div>

      {stale && (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-500">
          <b>Tu navegador tiene una versión vieja de esta pantalla.</b> Los resultados que simules
          ahora pueden estar calculados con reglas que ya cambiaron.{' '}
          <button onClick={() => window.location.reload(true)} className="underline font-semibold">
            Recargar
          </button>
        </div>
      )}
      <p className="text-xs text-ink-3 leading-relaxed">
        Las cuentas viejas tienen el P&L y los depósitos dolarizados al <b>dólar del día en que importaron</b>
        (una venta de 2021 dividida por ~1450 en vez de ~190). Acá se migran al TC de la fecha de cada
        operación, <b>cuenta por cuenta y con las dos patas juntas</b> (ventas + depósitos), que es la única
        forma de que el rendimiento no quede a mitad de camino. Flujo: <b>Cargar → seleccionar → Simular</b>
        {' '}(corre sobre una copia, no toca nada) <b>→ revisar el antes/después → Aplicar</b>. El % por
        operación no cambia; el P&L en USD y el capital aportado sí. Las cuentas <b>bloqueadas por escala</b>
        {' '}(bug per-100) van por su reparación propia antes.
        <br />
        <b>Filas ARS</b> = todas las filas en pesos que se re-estampan (compras, ventas y depósitos). El
        <b> Δ Aportado</b> solo lo mueven los depósitos/retiros importados: si una cuenta tiene muchas filas
        pero Δ Aportado 0, su capital entró por carga manual (ver "flujos manuales no migrables" en Notas).
      </p>

      {progress && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-ink-3">
            <span>{running === 'apply' ? 'Aplicando…' : 'Simulando…'}</span>
            <span className="tabular">{progress.done} / {progress.total} cuentas</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-bg-2 dark:bg-bg-2/40 overflow-hidden">
            <div className="h-full transition-all bg-violet-500" style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }} />
          </div>
        </div>
      )}

      {cands && (
        <>
          <div className="grid grid-cols-3 gap-3">
            <StatCard label="Migrables (v1)" value={String(cands.v1_migrables)} />
            <StatCard label="Bloqueadas por escala" value={String(cands.v1_bloqueadas_por_escala)} />
            <StatCard label="Ya migradas (v2)" value={String(cands.v2_ya_migradas)} />
          </div>

          {/* Desglose del aportado por año — el "por qué" del salto. Se abre
              clickeando el #id de cualquier fila. */}
          {aportado && (
            <div className="rounded-lg border border-violet-500/40 bg-violet-500/5 p-3 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <b className="text-sm">De qué años viene el aportado de #{aportado.user_id}</b>
                <button onClick={() => setAportado(null)}
                  className="text-xs px-2 py-1 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0">Cerrar</button>
              </div>
              {aportado.loading ? <div className="text-xs text-ink-3">Calculando…</div> : (
                <>
                  <div className="text-xs text-ink-2">
                    Aportado neto US$ {Math.round(aportado.aportado_neto_v1 || 0).toLocaleString()}
                    {' → '}US$ {Math.round(aportado.aportado_neto_v2 || 0).toLocaleString()}
                    {aportado.factor != null ? ` (×${aportado.factor})` : ''}
                    {aportado.filas_sin_tc_en_serie ? ` · ${aportado.filas_sin_tc_en_serie} fila(s) sin TC en la serie` : ''}
                  </div>
                  {/* El seed del "Estado inicial" no se re-estampa: su monto está en
                      pesos de HOY y su fecha es `earliest − 1 día`. Se muestra aparte
                      para que se entienda por qué no figura en el desglose. */}
                  {(aportado.sinteticas?.filas || 0) > 0 && (
                    <div className="text-[11px] text-emerald-500/90">
                      + {aportado.sinteticas.filas} fila(s) del "Estado inicial"
                      ({Math.round(aportado.sinteticas.ars).toLocaleString()} pesos, desde{' '}
                      {(aportado.sinteticas.desde || '').slice(0, 10)}) — quedan al dólar de HOY,
                      no se re-estampan: el usuario tipeó ese monto en pesos de hoy y el wizard
                      lo fechó un día antes del primer movimiento.
                    </div>
                  )}
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs tabular">
                      <thead className="text-ink-3">
                        <tr className="border-b border-line/40 text-left">
                          <th className="py-1 pr-3">Año</th><th className="py-1 pr-3">Movimiento</th>
                          <th className="py-1 pr-3 text-right">Filas</th>
                          <th className="py-1 pr-3 text-right">Pesos</th>
                          <th className="py-1 pr-3 text-right">USD ahora</th>
                          <th className="py-1 pr-3 text-right">USD migrado</th>
                          <th className="py-1 pr-3 text-right">Dólar usado</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(aportado.por_anio || []).map((f, i) => (
                          <tr key={i} className="border-b border-line/20">
                            <td className="py-1 pr-3">{f.anio}</td>
                            <td className={`py-1 pr-3 ${f.op === 'DEPOSIT' ? 'text-emerald-500' : 'text-amber-500'}`}>
                              {f.op === 'DEPOSIT' ? 'Depósito' : 'Retiro'}
                            </td>
                            <td className="py-1 pr-3 text-right">{f.filas}</td>
                            <td className="py-1 pr-3 text-right">{Math.round(f.ars).toLocaleString()}</td>
                            <td className="py-1 pr-3 text-right">{Math.round(f.usd_v1).toLocaleString()}</td>
                            <td className="py-1 pr-3 text-right font-medium">{Math.round(f.usd_v2).toLocaleString()}</td>
                            <td className="py-1 pr-3 text-right text-ink-3">
                              {f.tc_implicito_v1 ?? '—'} → {f.tc_implicito_v2 ?? '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {/* Las filas crudas que mandan. Es lo que cierra el diagnóstico:
                      con el archivo, el broker y la fila original se ve si la fecha
                      la rompió el parser o si ya venía mal del export. */}
                  {(aportado.top_filas || []).length > 0 && (
                    <details className="text-xs" open>
                      <summary className="cursor-pointer text-ink-2 hover:text-ink-0 py-1">
                        Las filas más pesadas (de dónde salen)
                      </summary>
                      <div className="overflow-x-auto mt-1">
                        <table className="w-full text-[11px] tabular">
                          <thead className="text-ink-3">
                            <tr className="border-b border-line/40 text-left">
                              <th className="py-1 pr-3">Fecha</th><th className="py-1 pr-3">Mov.</th>
                              <th className="py-1 pr-3 text-right">Pesos</th>
                              <th className="py-1 pr-3 text-right">Dólar</th>
                              <th className="py-1 pr-3 text-right">USD migrado</th>
                              <th className="py-1 pr-3 text-right">USD hoy</th>
                              <th className="py-1 pr-3">Broker</th>
                              <th className="py-1 pr-3">Archivo</th>
                            </tr>
                          </thead>
                          <tbody>
                            {aportado.top_filas.map((f, i) => (
                              <tr key={i} className="border-b border-line/20 align-top">
                                <td className="py-1 pr-3 whitespace-nowrap">{(f.date || '').slice(0, 10)}</td>
                                <td className={`py-1 pr-3 ${f.op === 'DEPOSIT' ? 'text-emerald-500' : 'text-amber-500'}`}>
                                  {f.op === 'DEPOSIT' ? 'Dep.' : 'Ret.'}
                                </td>
                                <td className="py-1 pr-3 text-right">{Math.round(f.ars).toLocaleString()}</td>
                                <td className="py-1 pr-3 text-right text-ink-3">{f.tc ?? '—'}</td>
                                <td className="py-1 pr-3 text-right font-medium">{f.usd_v2 != null ? Math.round(f.usd_v2).toLocaleString() : '—'}</td>
                                <td className="py-1 pr-3 text-right text-ink-3">{Math.round(f.usd_hoy).toLocaleString()}</td>
                                <td className="py-1 pr-3">{f.broker || '—'}</td>
                                <td className="py-1 pr-3 max-w-[320px]">
                                  <div className="truncate">{f.archivo || f.parser || '—'}</div>
                                  {f.fila_original && (
                                    <div className="text-[10px] text-ink-3 truncate" title={f.fila_original}>
                                      {f.fila_original}
                                    </div>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        <p className="text-[10px] text-ink-3 mt-1">
                          Pasá el mouse por el archivo para ver la fila tal como vino en el export.
                        </p>
                      </div>
                    </details>
                  )}
                  <div className="text-[11px] text-ink-3 leading-relaxed">{aportado.como_leerlo}</div>
                </>
              )}
            </div>
          )}

          <div className="rounded-lg border border-line/60 dark:border-line/40 p-3 space-y-2">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <span className="text-xs text-ink-2 flex-1 min-w-[280px]">
                <b>Snapshots con fecha futura</b> — el backfill de fin de mes también escribía el
                mes EN CURSO: queda fechado en el futuro y con el capital SIN la ganancia no
                realizada. Como el "último snapshot" se elige por fecha máxima, ese punto define el
                AUM del asesor y la punta del gráfico hasta fin de mes. Ya no se generan; esto
                limpia los que quedaron.
              </span>
              <div className="flex items-center gap-2 shrink-0">
                <button onClick={() => limpiarFuturos(false)} disabled={!!running}
                  className="text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50">
                  {running === 'cleanup' ? 'Contando…' : 'Contar'}
                </button>
                {futuros?.snapshots_futuros > 0 && !futuros.applied && (
                  <button onClick={() => limpiarFuturos(true)} disabled={!!running}
                    className="text-xs px-3 py-1.5 rounded-md bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50">
                    Limpiar {futuros.snapshots_futuros}
                  </button>
                )}
              </div>
            </div>
            {futuros && (
              <p className={`text-xs ${futuros.snapshots_futuros && !futuros.applied ? 'text-amber-500' : 'text-emerald-500'}`}>
                {futuros.snapshots_futuros
                  ? (futuros.applied
                      ? `✓ ${futuros.snapshots_futuros} snapshot(s) futuro(s) borrado(s) de ${futuros.cuentas} cuenta(s)`
                      : `${futuros.snapshots_futuros} snapshot(s) futuro(s) en ${futuros.cuentas} cuenta(s) — apretá "Limpiar"`)
                  : '✓ Sin snapshots futuros'}
              </p>
            )}
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={() => setSel(new Set(migrables.slice(0, 10).map(c => c.user_id)))}
              disabled={!!running}
              className="text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50">
              Seleccionar 10 más chicas
            </button>
            <button onClick={() => setSel(new Set(migrables.filter(c => !sims[c.user_id]?.applied).slice(0, 50).map(c => c.user_id)))}
              disabled={!!running}
              className="text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50">
              Próximas 50
            </button>
            <button onClick={() => setSel(new Set(migrables.filter(c => !sims[c.user_id]?.applied).map(c => c.user_id)))}
              disabled={!!running}
              className="text-xs px-2.5 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0 disabled:opacity-50">
              Seleccionar todas ({migrables.filter(c => !sims[c.user_id]?.applied).length})
            </button>
            {(() => {
              // Destildar lo que la simulación marcó mal: rojas (verificación
              // fallida) + las que ni pudieron simular (bloqueadas, errores).
              const malas = [...sel].filter(id =>
                sims[id] && (!sims[id].ok || nivelVerif(sims[id]) === 'rojo'))
              return malas.length > 0 && (
                <button onClick={() => setSel(new Set([...sel].filter(id => !malas.includes(id))))}
                  disabled={!!running}
                  className="text-xs px-2.5 py-1.5 rounded-md bg-red-500/15 border border-red-500/30 text-red-400 hover:text-red-300 disabled:opacity-50">
                  Destildar las {malas.length} con problema
                </button>
              )
            })()}
            <div className="flex-1" />
            <button onClick={() => correr(false)} disabled={!sel.size || !!running}
              className="text-xs px-3 py-1.5 rounded-md bg-violet-600 text-white hover:bg-violet-500 disabled:opacity-50">
              Simular {sel.size ? `(${sel.size})` : ''}
            </button>
            <button onClick={() => correr(true)} disabled={!sel.size || !!running}
              className="text-xs px-3 py-1.5 rounded-md bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50">
              Aplicar {sel.size ? `(${sel.size})` : ''}
            </button>
            {/* FORZAR: para las cuentas que la verificación frenó y ya revisaste.
                El freno de Δ P&L tiene un umbral ABSOLUTO (>US$100k) que no escala
                con el tamaño: una cuenta con miles de ventas y un delta por venta
                sano (la calibración dice 0-378 en sanas, 2.888+ en corruptas) lo
                cruza igual. El motivo de cada frenada trae el "US$ x/venta" —
                mirá ESE número antes de forzar, no el total. */}
            <button
              onClick={() => {
                const n = sel.size
                if (!n) return
                if (!confirm(
                  `Forzar la migración de ${n} cuenta${n === 1 ? '' : 's'} SALTEANDO la verificación.\n\n` +
                  `Hacelo sólo si ya miraste el motivo de la frenada y entendés por qué.\n` +
                  `En el Δ P&L, el número que importa es el POR VENTA: las cuentas sanas ` +
                  `dan 0-378 y las corruptas 2.888 o más.\n\nEsto modifica la base.`)) return
                correr(true, true)
              }}
              disabled={!sel.size || !!running}
              title="Aplica igual aunque la verificación haya frenado la cuenta"
              className="text-xs px-3 py-1.5 rounded-md bg-amber-600/90 text-white hover:bg-amber-500 disabled:opacity-50">
              Forzar {sel.size ? `(${sel.size})` : ''}
            </button>
          </div>

          {/* Buscar / ordenar / filtrar: sin esto, las cuentas que hay que mirar
              quedan perdidas entre 497 filas ordenadas por cantidad de ventas. */}
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <div className="relative">
              <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-ink-3" />
              <input value={buscar} onChange={e => setBuscar(e.target.value)}
                placeholder="Buscar #id"
                className="pl-7 pr-2 py-1.5 rounded-md bg-bg-2 dark:bg-bg-2/40 border border-line/60 w-32" />
            </div>
            <button onClick={() => setOrden(orden === 'caida' ? 'default' : 'caida')}
              className={`px-2.5 py-1.5 rounded-md ${orden === 'caida' ? 'bg-violet-600 text-white' : 'bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0'}`}>
              {orden === 'caida' ? '↓ Por caída del rendimiento' : 'Ordenar por caída'}
            </button>
            {[
              ['todas', `Todas (${(cands.cuentas || []).length})`],
              ['caen', `Cambian +50 pts (${nCaen})`],
              ['frenadas', `Frenadas (${nFrenadas})`],
              ['sinsim', 'Sin simular'],
            ].map(([k, label]) => (
              <button key={k} onClick={() => setFiltro(k)}
                className={`px-2.5 py-1.5 rounded-md ${filtro === k ? 'bg-ink-0 text-bg-0' : 'bg-bg-2 dark:bg-bg-2/40 text-ink-2 hover:text-ink-0'}`}>
                {label}
              </button>
            ))}
            {(buscar || orden !== 'default' || filtro !== 'todas') && (
              <button onClick={() => { setBuscar(''); setOrden('default'); setFiltro('todas') }}
                className="px-2 py-1.5 text-ink-3 hover:text-ink-0">Limpiar</button>
            )}
            <span className="text-ink-3 ml-auto">{filas.length} de {(cands.cuentas || []).length}</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-ink-3 text-left border-b border-line/60">
                  <th className="py-1.5 pr-2"></th>
                  <th className="py-1.5 pr-3">Usuario</th>
                  <th className="py-1.5 pr-3">Estado</th>
                  <th className="py-1.5 pr-3 text-right">Ventas</th>
                  <th className="py-1.5 pr-3 text-right">Filas ARS</th>
                  <th className="py-1.5 pr-3 text-right">Δ P&L ventas</th>
                  <th className="py-1.5 pr-3 text-right">Δ Aportado</th>
                  <th className="py-1.5">Notas</th>
                </tr>
              </thead>
              <tbody>
                {filas.map(c => {
                  const s = sims[c.user_id]
                  const bloq = c.bloqueada_por_escala
                  const v2 = c.fx_version === 'v2'
                  return (
                    <tr key={c.user_id} className="border-b border-line/30">
                      <td className="py-1.5 pr-2">
                        <input type="checkbox" checked={sel.has(c.user_id)}
                          disabled={bloq || v2 || !!running}
                          onChange={() => toggle(c.user_id)} />
                      </td>
                      {/* El "por qué" del salto del aportado. La simulación dice CUÁNTO
                          se mueve; sin el desglose por año no se puede saber si ×18 es
                          la reparación (depósitos viejos, dólar barato) o el neteo de
                          depósitos viejos contra retiros nuevos. Read-only. */}
                      <td className="py-1.5 pr-3 tabular">
                        <button className="hover:underline hover:text-violet-400"
                          title="Ver de qué años viene el aportado"
                          onClick={() => verAportado(c.user_id)}>#{c.user_id}</button>
                        {c.tier ? ` · ${c.tier}` : ''}
                      </td>
                      <td className="py-1.5 pr-3">
                        {v2 ? <span className="text-emerald-500">v2 ✓</span>
                          : bloq ? <span className="text-amber-500">bloqueada (escala ×{c.ventas_con_escala_rota})</span>
                          : s?.applied ? <span className="text-emerald-500">migrada ✓</span>
                          : s?.ok ? <span className="text-violet-400">simulada</span>
                          : s ? <span className="text-red-400">error</span>
                          : <span className="text-ink-3">v1</span>}
                      </td>
                      <td className="py-1.5 pr-3 text-right tabular">{c.ventas}</td>
                      <td className="py-1.5 pr-3 text-right tabular">{c.flujos_ars}</td>
                      <td className="py-1.5 pr-3 text-right tabular">
                        {s?.ok ? fmt(s.delta?.pnl_ventas_usd) : '—'}
                      </td>
                      <td className="py-1.5 pr-3 text-right tabular">
                        {s?.ok ? fmt((s.delta?.deposits_usd || 0) - (s.delta?.withdrawals_usd || 0)) : '—'}
                      </td>
                      <td className="py-1.5 text-ink-3">
                        {s && !s.ok ? <span className="text-red-400">{(s.motivo || '').slice(0, 110)}</span>
                          : s?.ok && s.verificacion
                            ? (() => {
                                const v = s.verificacion
                                const nivel = nivelVerif(s)
                                const color = nivel === 'verde' ? 'text-emerald-500'
                                  : nivel === 'ambar' ? 'text-amber-500' : 'text-red-400'
                                const icono = nivel === 'verde' ? '✓' : nivel === 'ambar' ? '~' : '✗'
                                return <span className={color}>
                                  {icono} {v.ventas_al_tc_de_su_fecha} ventas al TC de su fecha
                                  {' · '}cash {v.cash_intacto ? 'intacto' : '⚠️ CAMBIÓ'}
                                  {' · '}TCs en flujos {v.tcs_distintos_en_flujos?.antes}→{v.tcs_distintos_en_flujos?.despues}
                                  {/* El aportado ANTES, para poder juzgar el Δ: "+US$ 3.320.849"
                                      no dice nada sin saber si la cuenta tenía 3 millones o 20 mil.
                                      Un múltiplo alto NO es necesariamente daño — es la firma de la
                                      reparación (un flujo de 2013 dolarizado a 1415 y re-derivado a
                                      ~5 se multiplica ×280). Lo que hay que mirar es si el múltiplo
                                      es coherente con la ÉPOCA de los flujos de esa cuenta. */}
                                  {v.aportado_antes_usd != null ? (
                                    <> · aportado US$ {Math.round(v.aportado_antes_usd).toLocaleString()}
                                      {' → '}US$ {Math.round(v.aportado_despues_usd).toLocaleString()}
                                      {v.aportado_delta_pct != null && Math.abs(v.aportado_delta_pct) >= 1
                                        ? ` (${v.aportado_delta_pct > 0 ? '+' : ''}${v.aportado_delta_pct}% · ×${(v.aportado_despues_usd / (v.aportado_antes_usd || 1)).toFixed(1)})`
                                        : ''}
                                    </>
                                  ) : ''}
                                  {/* LO QUE VA A VER EL USUARIO. Es la única forma de
                                      verificar sin entrar a una cuenta ajena: el hero del
                                      Dashboard muestra (cartera − aportado) / aportado, y
                                      migrar mueve SOLO el denominador (el valor de la
                                      cartera queda idéntico). Así que este salto es,
                                      literalmente, el cambio que el usuario va a abrir. */}
                                  {(v.rendimiento_antes_pct != null || v.rendimiento_despues_pct != null) ? (
                                    <span className={v.denominador_roto ? 'text-red-400 font-medium' : 'text-slate-300'}>
                                      {' · '}rendimiento del usuario{' '}
                                      {v.rendimiento_antes_pct != null ? `${v.rendimiento_antes_pct > 0 ? '+' : ''}${v.rendimiento_antes_pct}%` : '—'}
                                      {' → '}
                                      {v.rendimiento_despues_pct != null ? `${v.rendimiento_despues_pct > 0 ? '+' : ''}${v.rendimiento_despues_pct}%` : '—'}
                                      {v.valor_cartera_usd != null ? ` (cartera US$ ${Math.round(v.valor_cartera_usd).toLocaleString()})` : ''}
                                    </span>
                                  ) : ''}
                                  {v.denominador_roto ? <span className="text-red-400"> · ⛔ {v.denominador_roto}</span> : ''}
                                  {v.fechas_sospechosas ? <span className="text-red-400"> · ⛔ {v.fechas_sospechosas}</span> : ''}
                                  {v.fechas_aviso ? <span className="text-amber-400"> · ⚠️ {v.fechas_aviso}</span> : ''}
                                  {v.cae_de_ganar_a_perder_todo && !v.fechas_sospechosas
                                    ? <span className="text-amber-400"> · ⚠️ pasa de ganar a perder casi todo lo aportado — revisá el desglose por año</span>
                                    : ''}
                                  {(v.baseline_borrada_usd || 0) !== 0
                                    ? <span className="text-amber-400"> · ⚠️ se borra el capital inicial cargado a mano (US$ {Math.round(v.baseline_borrada_usd).toLocaleString()})</span>
                                    : ''}
                                  {v.delta_pnl_implausible ? ` · ⚠️ Δ P&L IMPLAUSIBLE (US$ ${Math.round(v.delta_pnl_por_venta).toLocaleString()}/venta) — el P&L ya estaba corrupto y migrar lo multiplica` : ''}
                                  {(s.rebuild?.errores || []).length ? ` · ⚠️ ${s.rebuild.errores.length} activo(s) con error de rebuild` : ''}
                                  {(v.ventas_con_tc_distinto || []).length ? ` · ${v.ventas_con_tc_distinto.length} venta(s) con TC distinto` : ''}
                                  {v.en_pares_salteados ? ` · ${v.en_pares_salteados} venta(s) de pares manuales (TC viejo, esperado)` : ''}
                                  {v.sin_serie_fx ? ` · ${v.sin_serie_fx} pre-serie FX (TC viejo)` : ''}
                                  {(v.flujos_manuales_usd_no_migrables || 0) > 0 ? ` · US$ ${Math.round(v.flujos_manuales_usd_no_migrables).toLocaleString()} de flujos manuales no migrables` : ''}
                                </span>
                              })()
                            : c.ventas_manuales > 0 ? `${c.ventas_manuales} venta(s) manual(es)` : ''}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="text-xs text-ink-3 mt-1">{(cands.cuentas || []).length} cuentas.</p>
          </div>
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
    return { users_changed: 0, changes: [], needs_review: [], errors: [], total_users: 0, skipped: 0, fci_funds: {} }
  }
  function absorb(agg, r) {
    agg.users_changed += r.users_changed || 0
    agg.skipped += r.skipped || 0
    agg.total_users = r.total_all_users || agg.total_users
    if (agg.changes.length < 2000) agg.changes.push(...(r.changes || []))
    else agg.truncated = true
    if (r.needs_review?.length) agg.needs_review.push(...r.needs_review)
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
          <div className="grid grid-cols-3 gap-3">
            <ConvCell label="Cuentas a corregir" value={preview.users_changed} hint="quedan sanas → se aplican" />
            <ConvCell label="A revisar (no se aplican)" value={preview.needs_review?.length || 0} hint="siguen en gigante" />
            <ConvCell label="Fondos FCI tocados" value={fciFunds.length} hint="verificar money-market" />
          </div>

          {/* Cuentas que el guard NO aplica: siguen en gigante tras corregir (over/under) */}
          {preview.needs_review?.length > 0 && (
            <div className="border border-rose-500/30 rounded-md bg-rose-500/5 p-3 space-y-1.5">
              <p className="text-[12.5px] font-semibold text-rose-600 dark:text-rose-400">
                ⛔ {preview.needs_review.length} cuenta(s) NO se aplican — siguen en gigante tras corregir (revisar aparte)
              </p>
              <div className="max-h-40 overflow-y-auto">
                <table className="w-full text-xs">
                  <thead><tr className="text-ink-3">
                    <th className="text-left px-1 py-0.5">Usuario</th><th className="text-left px-1">Correcciones</th>
                    <th className="text-left px-1">Peor capital (antes→después)</th>
                  </tr></thead>
                  <tbody>
                    {preview.needs_review.map((c, i) => (
                      <tr key={i} className="border-t border-line/20">
                        <td className="px-1 py-0.5 text-ink-2">#{c.uid}</td>
                        <td className="px-1 text-ink-2 tabular">
                          {[c.corrections.fci && `${c.corrections.fci} FCI`, c.corrections.seed && `${c.corrections.seed} seed`,
                            c.corrections.conduit && `${c.corrections.conduit} cond.`].filter(Boolean).join(' · ')}
                        </td>
                        <td className="px-1 text-ink-1 tabular">{fmt(c.worst_before)} → <span className="text-rose-500">{fmt(c.worst_after)}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ⭐ verificación humana del blocker: qué fondos toca la regla FCI */}
          {fciFunds.length > 0 && (
            <div className="border border-amber-500/30 rounded-md bg-amber-500/5 p-3 space-y-1.5">
              <p className="text-[12.5px] font-semibold text-amber-700 dark:text-amber-400">
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
        <span className="text-[12.5px] text-ink-2 font-medium">
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
      <div className="text-[12.5px] text-ink-2 leading-none font-medium">{label}</div>
      <div className="mt-1.5 text-xl font-medium tabular num leading-none text-ink-0">{value}</div>
      <div className="text-[10px] text-ink-3 mt-1 truncate">{hint}</div>
    </div>
  )
}


// ─── Embudo del free trial ────────────────────────────────────────────────
// Responde, en orden: ¿lo activan? ¿usan la app? ¿pagan? Un trial sin uso no
// falló al convertir — falló antes, y ahí el problema es el onboarding, no el
// precio. Por eso los pasos intermedios están a la vista y no solo la tasa.
function TrialFunnelPanel({ data }) {
  if (!data) return null
  const {
    activados, en_curso: enCurso, terminados, importaron, usaron_ia: usaronIa,
    convirtieron, pct_importaron: pctImp, pct_usaron_ia: pctIa,
    pct_conversion_cerrada: pctCerrada, cuando_pagan: cuando,
    enabled, monthly_cap: cap, activados_este_mes: esteMes, days,
  } = data

  const paso = (label, n, pct, nota) => (
    <div className="flex items-baseline gap-3 py-1.5">
      <span className="text-sm text-ink-1 flex-1">{label}</span>
      <span className="text-sm font-medium text-ink-0 tabular-nums">{n ?? 0}</span>
      <span className="text-xs text-ink-3 tabular-nums w-14 text-right">
        {pct != null ? `${pct}%` : '—'}
      </span>
      {nota && <span className="text-[11px] text-ink-3">{nota}</span>}
    </div>
  )

  return (
    <section className="bg-bg-1 border border-line rounded-lg p-5 mb-5">
      <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
        <h2 className="text-sm font-semibold text-ink-0">Free trial · últimos {days} días</h2>
        <span className={`text-[11px] px-2 py-0.5 rounded-sm ${enabled ? 'bg-rendi-pos/15 text-rendi-pos' : 'bg-rendi-warn/15 text-rendi-warn'}`}>
          {enabled ? 'activo' : 'apagado'}
          {cap ? ` · ${esteMes}/${cap} este mes` : ''}
        </span>
      </div>
      <p className="text-xs text-ink-3 mb-3">
        {enCurso} en curso · {terminados} terminados
      </p>

      <div className="divide-y divide-line/60">
        {paso('Activaron la prueba', activados, null)}
        {paso('…y después importaron', importaron, pctImp, 'la app con datos adentro')}
        {paso('…y usaron la IA', usaronIa, pctIa)}
        {paso('…y se suscribieron', convirtieron, null)}
      </div>

      <div className="mt-3 pt-3 border-t border-line flex items-baseline gap-2 flex-wrap">
        <span className="text-sm text-ink-2">Conversión sobre los que terminaron:</span>
        <span className="text-lg font-semibold text-ink-0 tabular-nums">
          {pctCerrada != null ? `${pctCerrada}%` : '—'}
        </span>
        <span className="text-[11px] text-ink-3">
          (los que siguen probando todavía no decidieron)
        </span>
      </div>

      {cuando && (convirtieron > 0) && (
        <p className="text-xs text-ink-3 mt-2">
          Pagan: {cuando.durante_pro} en la semana de Pro · {cuando.durante_plus} en los días de Plus
          · {cuando.despues} después de que terminó.
        </p>
      )}
    </section>
  )
}
