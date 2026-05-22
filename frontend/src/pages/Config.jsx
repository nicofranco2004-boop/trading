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
import { RefreshCw, Lock, Upload, History, KeyRound, Sparkles, Zap } from 'lucide-react'
import { api } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import { track } from '../utils/track'
import PageHeader from '../components/PageHeader'
import Panel from '../components/Panel'
import Pill from '../components/Pill'
import ImportWizard from '../components/import/ImportWizard'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { whatsappUrl, SUPPORT_WHATSAPP_DISPLAY } from '../utils/support'
import { WhatsAppIcon } from '../components/SupportWhatsAppFab'

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

// currencyTone() vive ahora en BrokerManager.jsx — Config sólo muestra el
// contador de brokers, no toca el currency styling.

// ─── Página ──────────────────────────────────────────────────────────────────

const FIRST_IMPORT_FLAG = 'rendi_first_import_done'

export default function Config() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [brokers, setBrokers] = useState([])  // sólo para contador en "Cuenta"
  const [dolar, setDolar] = useState(null)
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' })
  const [pwState, setPwState] = useState({ loading: false, error: '', success: '' })
  const [showImport, setShowImport] = useState(false)
  const [importJustConfirmed, setImportJustConfirmed] = useState(false)
  const [aiUsage, setAiUsage] = useState(null)
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
    // Sólo para mostrar el contador en la sección "Cuenta". El CRUD de
    // brokers vive ahora en /posiciones (BrokerManager).
    setBrokers(await api.get('/brokers'))
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
      await api.post('/auth/change-password', {
        current_password: pwForm.current,
        new_password: pwForm.next,
      })
      // El backend rota la cookie HttpOnly automáticamente — no hace falta
      // tocar nada local.
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

      {/* ── Cuenta / Workspace info ──────────────────────────────────────── */}
      {/* Brokers management se mudó a /posiciones (BrokerManager). */}
      <Panel padding="none" className="mb-4">
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
            <Pill tone="signal">{(plan.tier || 'free').toUpperCase()}</Pill>
          </MetaRow>
          <MetaRow label="Brokers">
            <span className="tabular">
              {brokers.length} {brokers.length === 1 ? 'conectado' : 'conectados'}
              <span className="text-ink-3 ml-1.5">· se gestionan desde /posiciones</span>
            </span>
          </MetaRow>
          <MetaRow label="Miembro desde" last>
            <span className="tabular text-xs">{memberSince(user?.created_at)}</span>
          </MetaRow>
        </div>
      </Panel>

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

      {/* ── Soporte ─────────────────────────────────────────────────────── */}
      <Panel padding="none" className="mt-4">
        <div className="px-4 py-3 border-b border-line/40 flex items-center justify-between">
          <h2 className="text-sm font-medium text-ink-0">Soporte</h2>
          <span className="text-[10px] text-ink-3 uppercase tracking-wider">WhatsApp directo</span>
        </div>
        <div className="px-4 py-4 flex items-center justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <div className="text-sm text-ink-1">¿Dudas, problemas o sugerencias?</div>
            <div className="text-xs text-ink-3 mt-1">
              Te respondemos por WhatsApp. <span className="font-mono">{SUPPORT_WHATSAPP_DISPLAY}</span>
            </div>
          </div>
          <a
            href={whatsappUrl()}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1.5 text-xs bg-[#25D366]/10 hover:bg-[#25D366]/15 text-[#25D366] border border-[#25D366]/30 px-3 py-2 rounded-sm transition-colors"
          >
            <WhatsAppIcon size={13} />
            Hablanos por WhatsApp
          </a>
        </div>
      </Panel>

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

function PlanHero({ tier, usage }) {
  if (tier === 'admin') return <PlanHeroAdmin usage={usage} />
  if (tier === 'pro' || tier === 'plus') return <PlanHeroPro tier={tier} usage={usage} />
  return <PlanHeroFree usage={usage} />
}

// PlanHero compacto para Free — KPIs de uso + CTA "Mejorar plan" prominente.
// La comparativa completa de features vive en /planes (página dedicada).
function PlanHeroFree({ usage }) {
  const navigate = useNavigate()
  const count = usage?.analyses_count ?? 0
  const limit = usage?.analyses_limit ?? 6
  const pct = limit > 0 ? Math.min(100, (count / limit) * 100) : 0
  const remaining = Math.max(0, limit - count)

  function onUpgradeClick() {
    track('plan_hero_upgrade_clicked', { source: 'config' })
    navigate('/planes')
  }

  return (
    <section className="mb-6 border border-data-violet/30 bg-data-violet/[0.04] rounded-lg overflow-hidden">
      <div className="p-5 flex items-center gap-5 flex-wrap">
        {/* Left: tier badge + headline */}
        <div className="flex-1 min-w-[240px]">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="font-mono text-[10px] uppercase tracking-caps text-ink-3">Plan actual</span>
            <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm font-mono text-[9px] font-medium tracking-caps bg-bg-2 text-ink-2">
              FREE
            </span>
          </div>
          <h2 className="text-base font-semibold text-ink-0 leading-snug">
            Mejorá a Pro y desbloqueá todo
          </h2>
          <p className="text-xs text-ink-2 mt-1">
            10× más análisis IA, brokers ilimitados, follow-ups y mucho más.
          </p>
        </div>

        {/* Middle: usage strip compacto */}
        <div className="min-w-[180px]">
          <div className="flex items-baseline justify-between gap-3 mb-1">
            <span className="font-mono text-[10px] uppercase tracking-caps text-ink-3">Uso IA</span>
            <span className="font-mono text-xs text-ink-1 tabular">{count} / {limit}</span>
          </div>
          <div className="h-1.5 bg-bg-2 rounded-full overflow-hidden mb-1">
            <div
              className={`h-full transition-all ${pct >= 100 ? 'bg-rendi-neg' : pct >= 80 ? 'bg-data-amber' : 'bg-data-violet'}`}
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-[10px] text-ink-3 leading-tight">
            {remaining > 0
              ? `${remaining} ${remaining === 1 ? 'restante' : 'restantes'} (7 días)`
              : 'Llegaste al límite'}
          </p>
        </div>

        {/* Right: CTA prominente. Sin precio acá — el user lo descubre en /planes
            cuando ya entendió el valor (mejor conversión). */}
        <button
          type="button"
          onClick={onUpgradeClick}
          className="inline-flex items-center gap-2 text-sm font-medium bg-data-violet hover:bg-data-violet/90 text-white border border-data-violet rounded-sm px-5 py-3 transition-colors shadow-md shadow-data-violet/20"
        >
          <Sparkles size={14} strokeWidth={1.75} />
          Mejorar plan
        </button>
      </div>
    </section>
  )
}

// PlanHero compacto Pro/Plus — info del plan activo + link a /planes y opción
// de cancelar la suscripción. La cancelación llama POST /api/billing/cancel
// (que pega a Rebill PATCH status='cancelled'). El user mantiene acceso al
// tier hasta fin del período cobrado.
//
// Estados visuales:
//   • subscription_status=authorized → ACTIVO + botón "Cancelar suscripción"
//   • subscription_status=cancelled  → CANCELADO, vence X + botón "Reactivar"
//     (que es un Suscribirse nuevo a /planes, no un undo de la cancelación)
function PlanHeroPro({ tier = 'pro', usage }) {
  const navigate = useNavigate()
  const { user } = useAuth()
  const count = usage?.analyses_count ?? 0
  const isPlus = tier === 'plus'
  const tierLabel = isPlus ? 'PLUS' : 'PRO'
  const limit = usage?.analyses_limit ?? (isPlus ? 6 : 60)
  const pct = limit > 0 ? Math.min(100, (count / limit) * 100) : 0
  const [cancelling, setCancelling] = useState(false)

  // Single source of truth: access_mode viene calculado del backend.
  //   'authorized'  → sub Rebill activa, autorenovable. Botones: cambiar / cancelar.
  //   'credit_only' → vive del crédito post-cambio de plan. Botones: cambiar / configurar pago.
  //   'cancelled'   → canceló manualmente. Botones: reactivar.
  //   'free'        → tier free.
  // Fallback: si el user tiene tier=pro|plus pero no access_mode (demo o
  // legacy pre-deploy), asumimos 'authorized' — es lo seguro para no mostrar
  // "cancelado" cuando en realidad el user sí tiene acceso activo.
  const accessMode = user?.access_mode || (tier === 'pro' || tier === 'plus' ? 'authorized' : 'free')
  const subStatus = user?.subscription_status
  const periodEnd = user?.subscription_period_end
  const isCancelled = accessMode === 'cancelled'
  const isCreditOnly = accessMode === 'credit_only'
  const isAuthorized = accessMode === 'authorized'

  // Estado del crédito (modelo Rendi-managed proration). Cuando el user
  // cambió de plan mid-período o cancela mid-período, el acceso al tier
  // viene del crédito remanente, no de la sub Rebill.
  const creditDays = Number(user?.credit_days_remaining || 0)
  const creditUsd = Number(user?.credit_remaining_usd || 0)
  const creditUntil = user?.credit_active_until || null
  const anchorPlan = user?.credit_anchor_plan || null
  const anchorPeriod = user?.credit_anchor_period || null
  const hasCredit = creditDays > 0

  async function handleCancel() {
    if (cancelling) return
    if (!confirm(`¿Cancelar tu suscripción ${tierLabel}? Mantenés acceso hasta el fin del período actual cobrado. Después tu cuenta vuelve a Free.`)) return
    setCancelling(true)
    try {
      const res = await api.post('/billing/cancel', {})
      alert(`Suscripción cancelada. Mantenés ${tierLabel} hasta el fin del período cobrado.`)
      track('subscription_cancelled', { tier, source: 'config_plan_hero' })
      // Refresca la página para que el badge / KPIs reflejen el nuevo status
      window.location.reload()
    } catch (ex) {
      const msg = ex?.payload?.detail?.error || ex?.message || 'No pudimos cancelar la suscripción.'
      alert(msg)
    } finally {
      setCancelling(false)
    }
  }

  // Formato de fecha de expiración. Si tenemos credit_active_until lo
  // preferimos (es nuestro source of truth post-migración); si no,
  // fallback a current_period_end de la sub Rebill.
  const expiryRaw = creditUntil || periodEnd
  let periodEndLabel = ''
  if (expiryRaw) {
    try {
      const d = new Date(expiryRaw)
      if (!isNaN(d)) periodEndLabel = d.toLocaleDateString('es-AR', { day: '2-digit', month: 'long', year: 'numeric' })
    } catch {}
  }

  // Estilos por modo: authorized usa violet (autorrenovable), credit_only usa
  // cyan (en período de gracia activo), cancelled usa neutrales (en transición
  // a Free). Single source of truth: accessMode.
  const containerStyle = isAuthorized
    ? 'border-data-violet/40 bg-data-violet/[0.06]'
    : isCreditOnly
      ? 'border-data-cyan/40 bg-data-cyan/[0.05]'
      : 'border-line-2/70 bg-bg-2/30'

  const badgeStyle = isAuthorized
    ? 'bg-data-violet/15 text-data-violet'
    : isCreditOnly
      ? 'bg-data-cyan/15 text-data-cyan'
      : 'bg-ink-3/15 text-ink-2'

  const statusPill = isAuthorized
    ? { dotCls: 'bg-rendi-pos', textCls: 'text-rendi-pos', label: 'Activo' }
    : isCreditOnly
      ? { dotCls: 'bg-data-cyan', textCls: 'text-data-cyan', label: 'En crédito' }
      : { dotCls: 'bg-ink-3', textCls: 'text-ink-2', label: 'Cancelado' }

  const title = isAuthorized
    ? `Rendi ${isPlus ? 'Plus' : 'Pro'} está activo`
    : isCreditOnly
      ? `Rendi ${isPlus ? 'Plus' : 'Pro'} con tu crédito convertido`
      : `Rendi ${isPlus ? 'Plus' : 'Pro'} hasta fin de período`

  const descriptionText = isAuthorized
    ? (isPlus
        ? 'Multi-broker, insights completos, comportamiento avanzado y export CSV. Se renueva automáticamente.'
        : 'Análisis profundos, follow-ups, brokers ilimitados, export CSV y mucho más. Se renueva automáticamente.')
    : isCreditOnly
      ? (periodEndLabel
          ? `Cambiaste de plan: tenés acceso a ${isPlus ? 'Plus' : 'Pro'} hasta el ${periodEndLabel} con el crédito convertido. Después te avisamos para que configures el pago si querés seguir.`
          : `Cambiaste de plan: tenés acceso a ${isPlus ? 'Plus' : 'Pro'} con el crédito convertido del plan anterior. Cuando se acabe te avisamos para que configures el pago si querés seguir.`)
      : (periodEndLabel
          ? `Tu suscripción está cancelada. Mantenés acceso hasta el ${periodEndLabel}. Después la cuenta vuelve a Free.`
          : 'Tu suscripción está cancelada. Mantenés acceso hasta fin del período cobrado. Después la cuenta vuelve a Free.')

  return (
    <section className={`mb-6 border rounded-lg p-5 flex items-center gap-5 flex-wrap ${containerStyle}`}>
      <div className="flex-1 min-w-[240px]">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="font-mono text-[10px] uppercase tracking-caps text-ink-3">Plan actual</span>
          <span className={`inline-flex items-center px-1.5 py-0.5 rounded-sm font-mono text-[9px] font-medium tracking-caps ${badgeStyle}`}>
            {tierLabel}
          </span>
          <span className={`inline-flex items-center gap-1 text-[10px] font-mono uppercase tracking-caps ${statusPill.textCls}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${statusPill.dotCls}`} />
            {statusPill.label}
          </span>
        </div>
        <h2 className="text-base font-semibold text-ink-0 leading-snug">{title}</h2>
        <p className="text-xs text-ink-2 mt-1">{descriptionText}</p>
      </div>

      <div className="min-w-[180px]">
        <div className="flex items-baseline justify-between gap-3 mb-1">
          <span className="font-mono text-[10px] uppercase tracking-caps text-ink-3">Uso IA</span>
          <span className="font-mono text-xs text-ink-1 tabular">{count} / {limit}</span>
        </div>
        <div className="h-1.5 bg-bg-2 rounded-full overflow-hidden mb-1">
          <div className={`h-full transition-all ${
            isAuthorized ? 'bg-data-violet' : isCreditOnly ? 'bg-data-cyan' : 'bg-ink-3'
          }`} style={{ width: `${pct}%` }} />
        </div>
        <p className="text-[10px] text-ink-3 leading-tight">
          Ventana móvil 7 días
        </p>
      </div>

      {/* Bloque de crédito — sólo si el user tiene crédito activo y un anchor.
          Muestra cuántos días quedan + el valor en USD para que el user
          entienda exactamente qué tiene "comprado". */}
      {hasCredit && anchorPlan && anchorPeriod && (
        <div className="min-w-[180px] border-l border-line/40 pl-5">
          <div className="flex items-baseline justify-between gap-3 mb-1">
            <span className="font-mono text-[10px] uppercase tracking-caps text-ink-3">Crédito</span>
            <span className="font-mono text-xs text-ink-1 tabular">
              {Math.round(creditDays)} días
            </span>
          </div>
          <div className="text-[10px] text-ink-3 leading-tight">
            Acceso a <span className="text-ink-2 capitalize">{anchorPlan}</span>{' '}
            ({anchorPeriod === 'annual' ? 'anual' : 'mensual'}){' '}
            equivale a <span className="text-ink-2 tabular">${creditUsd.toFixed(2)}</span>
          </div>
          {periodEndLabel && (
            <div className="text-[10px] text-ink-3 leading-tight mt-0.5">
              Vence el <span className="text-ink-2">{periodEndLabel}</span>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        {isCancelled && (
          // Cancelled (user-initiated): mostrar reactivar — los va a llevar a
          // /planes donde hace "Suscribirme" normal.
          <button
            type="button"
            onClick={() => navigate('/planes')}
            className="inline-flex items-center gap-1.5 text-xs font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 rounded-sm px-3 py-2 transition-colors"
          >
            Reactivar suscripción
          </button>
        )}
        {isCreditOnly && (
          // Credit-only: el user no tiene sub Rebill activa — el "Cancelar
          // suscripción" no aplica. Mostrar "Cambiar plan" (puede convertir
          // crédito al otro tier) y "Configurar pago" (subscribe normal,
          // que ADEMÁS extiende el crédito por +30/+365 días). No mostramos
          // un botón rojo de cancel porque no hay nada que cancelar — el
          // crédito vence solo.
          <>
            <button
              type="button"
              onClick={() => navigate('/planes')}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-data-violet/10 hover:bg-data-violet/15 text-data-violet border border-data-violet/30 rounded-sm px-3 py-2 transition-colors"
            >
              Cambiar plan
            </button>
            <button
              type="button"
              onClick={() => navigate('/planes')}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-bg-2/60 hover:bg-bg-2 text-ink-1 border border-line/60 rounded-sm px-3 py-2 transition-colors"
            >
              Configurar pago
            </button>
          </>
        )}
        {isAuthorized && (
          <>
            <button
              type="button"
              onClick={() => navigate('/planes')}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-bg-2/60 hover:bg-bg-2 text-ink-1 border border-line/60 rounded-sm px-3 py-2 transition-colors"
            >
              {hasCredit && anchorPlan ? 'Cambiar plan' : 'Ver detalles del plan'}
            </button>
            <button
              type="button"
              onClick={handleCancel}
              disabled={cancelling}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-rendi-neg/[0.08] hover:bg-rendi-neg/15 text-rendi-neg border border-rendi-neg/30 rounded-sm px-3 py-2 transition-colors disabled:opacity-50"
            >
              {cancelling ? 'Cancelando…' : 'Cancelar suscripción'}
            </button>
          </>
        )}
      </div>
    </section>
  )
}

function PlanHeroAdmin({ usage }) {
  const navigate = useNavigate()
  const count = usage?.analyses_count ?? 0
  return (
    <section className="mb-6 border border-rendi-pos/30 bg-rendi-pos/[0.04] rounded-lg px-5 py-3.5 flex items-center gap-3 flex-wrap">
      <Zap size={14} strokeWidth={1.75} className="text-rendi-pos flex-shrink-0" />
      <span className="font-mono text-[10px] uppercase tracking-caps text-rendi-pos">Plan ADMIN</span>
      <span className="text-sm text-ink-1 flex-1 min-w-[200px]">
        Acceso interno sin tope. {count > 0 ? `Usaste ${count} análisis IA en los últimos 7 días.` : 'Sin uso de IA reciente.'}
      </span>
      <button
        type="button"
        onClick={() => navigate('/planes')}
        className="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-caps text-ink-3 hover:text-ink-0 transition-colors"
      >
        Ver planes →
      </button>
    </section>
  )
}
