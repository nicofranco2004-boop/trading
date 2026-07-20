// Config — settings con secciones (sub-sidebar en desktop, lista drill-in en mobile).
// ════════════════════════════════════════════════════════════════════════════
// Fase A del rediseño: MISMAS piezas que antes, reorganizadas en 5 secciones
// navegables por ?tab= (mismo mecanismo que Análisis/Cartera). Sin features
// nuevas — sólo estructura. Secciones:
//   • Cuenta          → Datos + Importar + Contraseña + Eliminar cuenta
//   • Planes          → PlanHero (plan actual, uso IA, gestión de suscripción)
//   • Tipos de cambio → Moneda de valuación (riel) + Cotizaciones (FX)
//   • Notificaciones  → placeholder "Próximamente"
//   • Soporte         → WhatsApp directo
//
// Desktop: PageHeader + sub-sidebar vertical + contenido de la sección activa.
// Mobile:  lista de secciones (sin ?tab) → drill-in a la sección (con back).

import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  RefreshCw, Lock, Upload, History, KeyRound, Sparkles, Zap, Loader2,
  CheckCircle2, AlertCircle, Trash2, UserRound, CreditCard, ArrowLeftRight,
  LifeBuoy, ChevronRight, ChevronLeft, Mail, CalendarClock, Check, ClipboardList,
} from 'lucide-react'
import { api } from '../utils/api'
import { useAuth } from '../contexts/AuthContext'
import { track } from '../utils/track'
import { useIsMobile } from '../hooks/useIsMobile'
import PageHeader from '../components/PageHeader'
import CurrencyRail from '../components/CurrencyRail'
import { useCurrency } from '../contexts/CurrencyContext'
import Panel from '../components/Panel'
import Pill from '../components/Pill'
import ImportWizard from '../components/import/ImportWizard'
import { usePlanFeatures } from '../hooks/usePlanFeatures'
import { whatsappUrl, SUPPORT_WHATSAPP_DISPLAY } from '../utils/support'
import { WhatsAppIcon } from '../components/SupportWhatsAppFab'
import { FREE_FEATURES, PLUS_FEATURES, PRO_FEATURES } from '../data/planCatalog'
import InvestorProfileForm from '../components/InvestorProfileForm'

const DOLAR_REFRESH_MS = 600_000 // 10 min

// ─── Secciones ───────────────────────────────────────────────────────────────

const TABS = [
  { id: 'cuenta',         label: 'Cuenta',           icon: UserRound,      sub: 'Datos, seguridad y eliminación' },
  { id: 'test',           label: 'Test de inversor', icon: ClipboardList,  sub: 'Contexto para el Coach IA' },
  { id: 'planes',         label: 'Planes',           icon: CreditCard,     sub: 'Tu plan y uso de IA' },
  { id: 'fx',             label: 'Tipos de cambio',  icon: ArrowLeftRight, sub: 'Moneda de valuación y cotizaciones' },
  { id: 'soporte',        label: 'Soporte',          icon: LifeBuoy,       sub: 'WhatsApp y ayuda' },
]
const VALID_TAB_IDS = new Set(TABS.map(t => t.id))
const DEFAULT_TAB = 'cuenta'
const TAB_LABEL = Object.fromEntries(TABS.map(t => [t.id, t.label]))

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

// ─── Página ──────────────────────────────────────────────────────────────────

const FIRST_IMPORT_FLAG = 'rendi_first_import_done'

export default function Config() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const { costBasis, setCostBasis } = useCurrency()
  const isMobile = useIsMobile()
  const [searchParams, setSearchParams] = useSearchParams()
  const [delState, setDelState] = useState({ loading: false, error: '' })
  const [brokers, setBrokers] = useState([])  // sólo para contador en "Cuenta"
  const [dolar, setDolar] = useState(null)
  const [pwForm, setPwForm] = useState({ current: '', next: '', confirm: '' })
  const [pwState, setPwState] = useState({ loading: false, error: '', success: '' })
  const [showImport, setShowImport] = useState(false)
  const [importJustConfirmed, setImportJustConfirmed] = useState(false)
  const [aiUsage, setAiUsage] = useState(null)
  const plan = usePlanFeatures()

  // Sección activa desde la URL (?tab=cuenta). En desktop, sin ?tab cae al
  // default 'cuenta'. En mobile, sin ?tab mostramos la LISTA de secciones
  // (patrón drill-in tipo iOS Settings). Tabs inválidos se ignoran.
  const urlTab = searchParams.get('tab')
  const validTab = urlTab && VALID_TAB_IDS.has(urlTab) ? urlTab : null
  const activeSection = validTab || (isMobile ? null : DEFAULT_TAB)

  useEffect(() => {
    loadDolar()
    loadBrokers()
    loadAiUsage()
    const id = setInterval(loadDolar, DOLAR_REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (activeSection) track('config_tab_viewed', { tab: activeSection, surface: isMobile ? 'mobile' : 'desktop' })
  }, [activeSection])  // eslint-disable-line react-hooks/exhaustive-deps — sólo trackeamos cambio de sección, no de breakpoint

  // replace:true (igual que Análisis/Cartera): la sección es una preferencia de
  // vista, no un paso navegable. Evita que el sub-sidebar arme un rastro en el
  // historial (Back caminaría las tabs) y que el "back" de mobile apile /config
  // en vez de popear (que haría que el Back del celular re-abra la sección).
  function goSection(id) {
    const next = new URLSearchParams(searchParams)
    next.set('tab', id)
    setSearchParams(next, { replace: true })
  }

  function backToList() {
    const next = new URLSearchParams(searchParams)
    next.delete('tab')
    setSearchParams(next, { replace: true })
  }

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

  async function deleteAccount() {
    const ok = window.confirm(
      'Vas a ELIMINAR tu cuenta de Rendi de forma permanente.\n\n' +
      'Se borran todos tus datos (brokers, posiciones, operaciones, imports, historial) y ' +
      'se cancela tu suscripción. Esta acción NO se puede deshacer.\n\n¿Confirmás?')
    if (!ok) return
    setDelState({ loading: true, error: '' })
    try {
      await api.delete('/me')
      logout()               // limpia sesión + storage
      navigate('/login', { replace: true })
    } catch (err) {
      setDelState({ loading: false, error: err.message || 'No se pudo eliminar la cuenta.' })
    }
  }

  const fetchedAt = dolar?.fetched_at ? new Date(dolar.fetched_at) : null
  const labelClass = 'block text-xs text-ink-3 mb-1'
  const inputClass = 'w-full bg-bg-2 border border-line rounded-sm px-3 py-2 text-sm text-ink-0 placeholder:text-ink-3 focus:outline-none focus:border-ink-2'

  // ─── Renderers de sección ──────────────────────────────────────────────────

  function renderCuenta() {
    return (
      <div className="space-y-4">
        {/* Datos del workspace. Brokers management se mudó a /posiciones. */}
        <Panel padding="none">
          <header className="px-4 py-3 border-b border-line">
            <h2 className="text-sm font-medium text-ink-0">Datos</h2>
            <p className="text-xs text-ink-3 mt-0.5">Tu identidad en Rendi</p>
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

        {/* Importar datos | Cambiar contraseña */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Importar datos */}
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

        {/* Zona de peligro — eliminar cuenta */}
        <Panel padding="none" className="border-rendi-neg/30">
          <div className="px-4 py-3 border-b border-rendi-neg/20 flex items-center gap-2">
            <AlertCircle size={14} className="text-rendi-neg" strokeWidth={1.75} />
            <h2 className="text-sm font-medium text-rendi-neg">Eliminar cuenta</h2>
          </div>
          <div className="px-4 py-4 flex items-center justify-between gap-4 flex-wrap">
            <p className="text-xs text-ink-3 leading-relaxed max-w-md">
              Elimina tu cuenta y todos tus datos de forma permanente (brokers, posiciones, operaciones,
              historial) y cancela tu suscripción. Esta acción <b>no se puede deshacer</b>.
            </p>
            <div className="flex flex-col items-end gap-1">
              <button
                onClick={deleteAccount}
                disabled={delState.loading}
                className="inline-flex items-center gap-1.5 text-xs bg-rendi-neg/10 hover:bg-rendi-neg/15 text-rendi-neg border border-rendi-neg/30 px-3 py-2 rounded-sm transition-colors disabled:opacity-50"
              >
                <Trash2 size={12} strokeWidth={1.75} />
                {delState.loading ? 'Eliminando…' : 'Eliminar mi cuenta'}
              </button>
              {delState.error && <span className="text-[11px] text-rendi-neg">{delState.error}</span>}
            </div>
          </div>
        </Panel>
      </div>
    )
  }

  function renderPlanes() {
    const tier = user?.tier || 'free'
    return (
      <div className="space-y-5">
        <PlanHero tier={tier} usage={aiUsage} />
        <PlanComparisonCards currentTier={tier} />
      </div>
    )
  }

  function renderFx() {
    return (
      <div className="space-y-6">
        {/* Moneda de valuación (riel unificado: USD MEP / USD CCL / Pesos).
            Mismo state global que el riel de Cartera/Análisis: cambiarlo acá lo
            cambia en toda la app. */}
        <section>
          <div className="border border-line rounded bg-bg-1 px-4 py-3.5">
            <div className="min-w-0 mb-3">
              <h2 className="text-sm font-medium text-ink-1">Moneda de valuación</h2>
              <p className="text-xs text-ink-3 mt-0.5">
                En qué moneda ves toda la app. <b>USD MEP</b>: dólar local (default). <b>USD CCL</b>: el
                dólar implícito en el precio de los CEDEARs. <b>Pesos</b>: todos tus valores en ARS.
              </p>
            </div>
            <CurrencyRail />
          </div>
        </section>

        {/* Costo en dólares — con qué dólar se cuenta lo invertido (solo display,
            per-device; espeja el patrón del riel de moneda). Solo afecta la columna
            INV. USD de la Cartera; el valor de mercado siempre va al dólar de hoy. */}
        <section>
          <div className="border border-line rounded bg-bg-1 px-4 py-3.5">
            <div className="min-w-0 mb-3">
              <h2 className="text-sm font-medium text-ink-1">Costo en dólares</h2>
              <p className="text-xs text-ink-3 mt-0.5">
                Con qué dólar contamos lo que invertiste. <b>Dólar de hoy</b> (default): tu
                ganancia en USD refleja solo cómo rindió el activo. <b>Dólar de la compra</b>:
                incluye la devaluación del peso desde que compraste. Cambia el <b>Invertido</b> y
                el <b>P&L en dólares</b> de la Cartera; el valor de mercado y las cifras en pesos
                no se tocan.
              </p>
            </div>
            <div className="inline-flex rounded-md border border-line overflow-hidden">
              {[
                { id: 'today', label: 'Dólar de hoy' },
                { id: 'purchase', label: 'Dólar de la compra' },
              ].map(opt => {
                const active = (costBasis || 'today') === opt.id
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => setCostBasis(opt.id)}
                    className={`px-3.5 py-2 text-xs font-medium transition-colors ${
                      active
                        ? 'bg-rendi-accent text-white'
                        : 'bg-bg-1 text-ink-2 hover:text-ink-0 hover:bg-bg-2'
                    } ${opt.id === 'purchase' ? 'border-l border-line' : ''}`}
                    aria-pressed={active}
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>
          </div>
        </section>

        {/* Cotizaciones en vivo */}
        <section>
          <div className="flex items-baseline justify-between mb-2 gap-3 flex-wrap">
            <h2 className="text-sm font-medium text-ink-1">Cotizaciones</h2>
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
      </div>
    )
  }

  function renderSoporte() {
    return (
      <Panel padding="none">
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
    )
  }

  // Test de inversor — el formulario de 7 preguntas que alimenta al Coach IA.
  // Se migró acá desde Análisis (2026-07-14): sólo se ve cuando el user entra a
  // esta sección, no siempre. El cruce cartera-vs-perfil sigue en Análisis ›
  // Perfil (con CTA a esta sección si el test no está completo).
  function renderPerfil() {
    return (
      <Panel padding="none">
        <header className="px-4 py-3 border-b border-line">
          <h2 className="text-sm font-medium text-ink-0">Test de inversor</h2>
          <p className="text-xs text-ink-3 mt-0.5">
            Un test corto para que el Coach IA te conozca · define tu perfil (conservador / moderado / agresivo).
            Las respuestas viajan al prompt cuando le hablás al modelo — no se comparten con nadie.
          </p>
        </header>
        <div className="p-4">
          <InvestorProfileForm />
        </div>
      </Panel>
    )
  }

  function renderSection(id) {
    switch (id) {
      case 'test':           return renderPerfil()
      case 'planes':         return renderPlanes()
      case 'fx':             return renderFx()
      case 'soporte':        return renderSoporte()
      case 'cuenta':
      default:               return renderCuenta()
    }
  }

  return (
    <div className="page-shell-wide">
      {/* ── MOBILE: lista de secciones (sin ?tab) ─────────────────────────── */}
      {isMobile && !activeSection && (
        <>
          <PageHeader
            title="Configuración"
            subtitle="Cuenta, plan, tipos de cambio y más."
          />
          <div className="bg-bg-1 border border-line/60 rounded-lg overflow-hidden">
            {TABS.map((t, i) => {
              const Icon = t.icon
              return (
                <button
                  key={t.id}
                  onClick={() => goSection(t.id)}
                  className={`flex items-center gap-3 px-4 py-3 w-full text-left hover:bg-bg-2/60 active:bg-bg-3 transition-colors ${i > 0 ? 'border-t border-line/40' : ''}`}
                >
                  <Icon size={18} strokeWidth={1.75} className="text-ink-2 flex-shrink-0" aria-hidden="true" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-ink-0 leading-tight">{t.label}</div>
                    <div className="text-[11px] text-ink-3 leading-tight mt-0.5">{t.sub}</div>
                  </div>
                  <ChevronRight size={15} strokeWidth={1.75} className="text-ink-3 flex-shrink-0" aria-hidden="true" />
                </button>
              )
            })}
          </div>
        </>
      )}

      {/* ── MOBILE: sección abierta (drill-in con back) ───────────────────── */}
      {isMobile && activeSection && (
        <>
          <button
            onClick={backToList}
            className="inline-flex items-center gap-1 text-sm font-medium text-data-violet mb-2 -ml-1 py-1.5 pr-2"
          >
            <ChevronLeft size={16} strokeWidth={2} aria-hidden="true" /> Configuración
          </button>
          <h1 className="text-xl font-medium text-ink-0 tracking-tight leading-tight mb-4">{TAB_LABEL[activeSection]}</h1>
          {renderSection(activeSection)}
        </>
      )}

      {/* ── DESKTOP: PageHeader + sub-sidebar + contenido ─────────────────── */}
      {!isMobile && (
        <>
          <PageHeader
            eyebrow="Workspace"
            title="Configuración"
            subtitle="Tu cuenta, tu plan, los tipos de cambio y las notificaciones — cada cosa en su lugar."
          />
          <div className="grid grid-cols-1 md:grid-cols-[190px_1fr] gap-6 items-start">
            <nav className="md:sticky md:top-4 flex flex-col gap-0.5" aria-label="Secciones de configuración">
              <div className="text-[10px] font-mono uppercase tracking-caps text-ink-3 px-2.5 pt-0.5 pb-2 select-none">Secciones</div>
              {TABS.map(t => {
                const Icon = t.icon
                const active = activeSection === t.id
                return (
                  <button
                    key={t.id}
                    onClick={() => goSection(t.id)}
                    aria-current={active ? 'page' : undefined}
                    className={`flex items-center gap-2.5 text-left w-full px-2.5 py-2 rounded-sm border transition-colors ${
                      active
                        ? 'bg-data-violet/10 text-data-violet border-data-violet/25 text-sm font-semibold'
                        : 'text-ink-2 border-transparent text-sm font-medium hover:text-ink-0 hover:bg-bg-2'
                    }`}
                  >
                    <Icon size={16} strokeWidth={1.75} className={active ? 'text-data-violet' : 'text-ink-3'} aria-hidden="true" />
                    {t.label}
                  </button>
                )
              })}
            </nav>
            <div className="min-w-0">
              {renderSection(activeSection)}
            </div>
          </div>
        </>
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
// Sección destacada con plan actual + uso semanal de IA + comparativa Free vs
// Pro + CTA upgrade (solo en Free). Tono violet para Pro, sutil para Free (que
// SIGUE el highlight es el botón de upgrade).

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
    <section className="border border-data-violet/30 bg-data-violet/[0.04] rounded-lg overflow-hidden">
      <div className="p-5 flex items-center gap-5 flex-wrap">
        {/* Left: tier badge + headline */}
        <div className="flex-1 min-w-[240px]">
          <div className="flex items-center gap-2 mb-1.5">
            <span className="font-mono text-[11px] uppercase tracking-caps text-ink-2">Plan actual</span>
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
            <span className="font-mono text-[11px] uppercase tracking-caps text-ink-2">Uso IA</span>
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
          className="inline-flex items-center gap-2 text-sm font-medium bg-data-violet hover:bg-data-violet/90 text-white border border-data-violet rounded-sm px-5 py-3 transition-colors shadow-md shadow-data-violet/20 press"
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
  // Estados del modal de cancelación: 'closed' | 'confirm' | 'success' | 'error'.
  // Reemplaza el confirm()/alert() nativo del browser (UX rota/fea — no
  // matchea el diseño de Rendi) por un modal estilizado.
  const [cancelModal, setCancelModal] = useState({ open: false, phase: 'confirm', errorMsg: null })

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

  // Abre el modal — la confirmación real la dispara el botón "Cancelar mi suscripción"
  // dentro del modal (que llama a confirmCancel). Antes usábamos confirm() nativo,
  // pero su UX rompe la estética de la app.
  function openCancelModal() {
    if (cancelling) return
    setCancelModal({ open: true, phase: 'confirm', errorMsg: null })
  }

  async function confirmCancel() {
    setCancelling(true)
    setCancelModal((m) => ({ ...m, phase: 'pending' }))
    try {
      await api.post('/billing/cancel', {})
      track('subscription_cancelled', { tier, source: 'config_plan_hero' })
      setCancelModal({ open: true, phase: 'success', errorMsg: null })
      // Pequeña pausa para que el user vea el "Cancelado correctamente" y
      // después refrescamos para que el resto de la UI muestre el nuevo estado.
      setTimeout(() => { window.location.reload() }, 1800)
    } catch (ex) {
      const msg = ex?.payload?.detail?.error || ex?.message || 'No pudimos cancelar la suscripción. Intentá de nuevo o escribinos a soporte.'
      setCancelModal({ open: true, phase: 'error', errorMsg: msg })
    } finally {
      setCancelling(false)
    }
  }

  function closeCancelModal() {
    if (cancelling) return  // no permitir cerrar mientras se procesa
    setCancelModal({ open: false, phase: 'confirm', errorMsg: null })
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
    <section className={`border rounded-lg p-5 flex items-center gap-5 flex-wrap ${containerStyle}`}>
      <div className="flex-1 min-w-[240px]">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="font-mono text-[11px] uppercase tracking-caps text-ink-2">Plan actual</span>
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
          <span className="font-mono text-[11px] uppercase tracking-caps text-ink-2">Uso IA</span>
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
            <span className="font-mono text-[11px] uppercase tracking-caps text-ink-2">Crédito</span>
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
              onClick={openCancelModal}
              disabled={cancelling}
              className="inline-flex items-center gap-1.5 text-xs font-medium bg-rendi-neg/[0.08] hover:bg-rendi-neg/15 text-rendi-neg border border-rendi-neg/30 rounded-sm px-3 py-2 transition-colors disabled:opacity-50"
            >
              {cancelling ? 'Cancelando…' : 'Cancelar suscripción'}
            </button>
          </>
        )}
      </div>

      {/* Modal de cancelación — estilizado, reemplaza confirm()/alert() nativos */}
      {cancelModal.open && (
        <CancelSubscriptionModal
          phase={cancelModal.phase}
          tierLabel={tierLabel}
          periodEndLabel={periodEndLabel}
          errorMsg={cancelModal.errorMsg}
          onConfirm={confirmCancel}
          onClose={closeCancelModal}
        />
      )}
    </section>
  )
}

// ─── Modal de cancelación de suscripción ──────────────────────────────────────
// Reemplaza el `confirm()` + `alert()` nativos del browser por una UX in-app
// que matchea el resto del diseño de Rendi. 4 fases:
//   - 'confirm':  el user todavía no decidió. Botón rojo "Cancelar mi suscripción".
//   - 'pending':  request en flight. Spinner + texto.
//   - 'success':  cancelado OK. Mensaje confirmando + reload automático.
//   - 'error':    falló el API. Mensaje del backend + botón "Cerrar".
function CancelSubscriptionModal({ phase, tierLabel, periodEndLabel, errorMsg, onConfirm, onClose }) {
  const isPending = phase === 'pending'
  const isSuccess = phase === 'success'
  const isError = phase === 'error'
  const isConfirm = phase === 'confirm'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4"
      onClick={isPending ? undefined : onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="cancel-modal-title"
    >
      <div
        className="bg-bg-1 border border-line-2/70 rounded-lg max-w-md w-full p-6 shadow-[0_20px_60px_-10px_rgba(0,0,0,0.6)]"
        onClick={(e) => e.stopPropagation()}
      >
        {isConfirm && (
          <>
            <h2 id="cancel-modal-title" className="text-lg font-semibold text-ink-0 mb-3">
              ¿Cancelar tu suscripción {tierLabel}?
            </h2>
            <div className="text-sm text-ink-2 leading-relaxed space-y-3 mb-5">
              <p>
                Mantenés acceso a {tierLabel} hasta el fin del período actual
                {periodEndLabel ? <> (<span className="text-ink-0">{periodEndLabel}</span>)</> : null}.
                Después tu cuenta vuelve a Free automáticamente.
              </p>
              <p className="text-xs text-ink-3">
                Podés reactivarla en cualquier momento desde la página de Planes.
                Tus datos no se pierden.
              </p>
            </div>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="inline-flex items-center gap-1.5 text-sm font-medium bg-bg-2 hover:bg-bg-2/80 text-ink-1 border border-line/60 rounded-sm px-4 py-2 transition-colors"
              >
                Volver
              </button>
              <button
                type="button"
                onClick={onConfirm}
                className="inline-flex items-center gap-1.5 text-sm font-medium bg-rendi-neg/15 hover:bg-rendi-neg/25 text-rendi-neg border border-rendi-neg/40 rounded-sm px-4 py-2 transition-colors"
              >
                Cancelar mi suscripción
              </button>
            </div>
          </>
        )}

        {isPending && (
          <div className="flex items-center gap-3 py-2">
            <Loader2 size={18} strokeWidth={1.75} className="animate-spin text-data-violet flex-shrink-0" />
            <div>
              <p className="text-sm text-ink-0 font-medium">Cancelando…</p>
              <p className="text-xs text-ink-3 mt-0.5">Esto puede tardar unos segundos.</p>
            </div>
          </div>
        )}

        {isSuccess && (
          <>
            <div className="flex items-start gap-3 mb-2">
              <CheckCircle2 size={20} strokeWidth={1.75} className="text-rendi-pos flex-shrink-0 mt-0.5" />
              <div>
                <h2 className="text-base font-semibold text-ink-0">Suscripción cancelada</h2>
                <p className="text-sm text-ink-2 mt-1 leading-relaxed">
                  Mantenés acceso a {tierLabel} hasta el fin del período cobrado.
                  Después tu cuenta vuelve a Free.
                </p>
              </div>
            </div>
            <p className="text-xs text-ink-3 mt-3">Actualizando la página…</p>
          </>
        )}

        {isError && (
          <>
            <div className="flex items-start gap-3 mb-4">
              <AlertCircle size={20} strokeWidth={1.75} className="text-rendi-neg flex-shrink-0 mt-0.5" />
              <div>
                <h2 className="text-base font-semibold text-ink-0">No pudimos cancelar</h2>
                <p className="text-sm text-ink-2 mt-1 leading-relaxed">
                  {errorMsg || 'Hubo un error al cancelar tu suscripción.'}
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end">
              <button
                type="button"
                onClick={onClose}
                className="inline-flex items-center gap-1.5 text-sm font-medium bg-bg-2 hover:bg-bg-2/80 text-ink-1 border border-line/60 rounded-sm px-4 py-2 transition-colors"
              >
                Cerrar
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function PlanHeroAdmin({ usage }) {
  const navigate = useNavigate()
  const count = usage?.analyses_count ?? 0
  return (
    <section className="border border-rendi-pos/30 bg-rendi-pos/[0.04] rounded-lg px-5 py-3.5 flex items-center gap-3 flex-wrap">
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

// ─── PlanComparisonCards ──────────────────────────────────────────────────────
// Cuadros de "qué incluye cada plan" (Free / Plus / Pro) debajo del PlanHero,
// en la sección Planes de Config. Reusa la MISMA data que /planes (data/
// planCatalog.js) para no duplicar ni desincronizar. Resalta en violet el plan
// que el user ya tiene. Para precios + upgrade, linkea a /planes.
const CONFIG_PLANS = [
  { id: 'free', name: 'Free', feat: FREE_FEATURES },
  { id: 'plus', name: 'Plus', feat: PLUS_FEATURES },
  { id: 'pro',  name: 'Pro',  feat: PRO_FEATURES },
]

function PlanComparisonCards({ currentTier }) {
  const norm = (currentTier || 'free').toLowerCase()
  return (
    <section>
      <div className="flex items-baseline justify-between gap-3 mb-3 flex-wrap">
        <h2 className="text-sm font-medium text-ink-1">Qué incluye cada plan</h2>
        <Link to="/planes" className="text-xs text-data-violet hover:underline inline-flex items-center gap-1">
          Ver planes y precios →
        </Link>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {CONFIG_PLANS.map(p => {
          const isCurrent = norm === p.id
          return (
            <div
              key={p.id}
              className={`rounded-lg border p-4 flex flex-col ${isCurrent ? 'border-data-violet/40 bg-data-violet/[0.04]' : 'border-line bg-bg-1'}`}
            >
              <div className="flex items-center justify-between gap-2 mb-3">
                <span className={`text-sm font-semibold ${isCurrent ? 'text-data-violet' : 'text-ink-0'}`}>{p.name}</span>
                {isCurrent && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm font-mono text-[9px] font-medium tracking-caps bg-data-violet/15 text-data-violet">
                    Tu plan
                  </span>
                )}
              </div>

              {/* Quotas — grid mini de números (análisis/sem, chat/sem, brokers) */}
              <div className="grid grid-cols-3 gap-2 mb-3">
                {p.feat.quotas.map(q => (
                  <div key={q.label} className="rounded-sm bg-bg-2/50 border border-line/50 px-2 py-1.5 text-center">
                    <div className="text-base font-medium tabular text-ink-0 leading-none">{q.value}</div>
                    <div className="text-[10px] text-ink-3 mt-1 leading-tight">{q.label}</div>
                  </div>
                ))}
              </div>

              {/* Essentials — features core con check */}
              <ul className="space-y-1.5">
                {p.feat.essentials.map((f, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <Check size={13} strokeWidth={2.25} className="mt-0.5 flex-shrink-0 text-rendi-pos" aria-hidden="true" />
                    <span className="text-xs text-ink-2 leading-snug">
                      {f.label}
                      {f.sub && <span className="block text-[11px] text-ink-3 mt-0.5">{f.sub}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </section>
  )
}
