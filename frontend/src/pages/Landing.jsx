// Landing — primera impresión para visitantes sin login.
// Estética: terminal futurista. Grid de fondo, spotlight verde, hero con
// cursor blink, mock dashboard "live", reveal on scroll en features.

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, Sparkles, RefreshCw, LineChart, Layers, Coins,
  Zap, Terminal, ChevronDown, Check,
} from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import { ARS_MONTHLY, ARS_PLUS_MONTHLY, FREE_FEATURES, PLUS_FEATURES, PRO_FEATURES } from './Planes'
import { whatsappUrl } from '../utils/support'
import SupportWhatsAppFab, { WhatsAppIcon } from '../components/SupportWhatsAppFab'

// ─── Hooks utilitarios ───────────────────────────────────────────────────────

function useReveal() {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { el.classList.add('in'); io.disconnect() } },
      { threshold: 0.15, rootMargin: '0px 0px -60px 0px' }
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return ref
}

// Counter que sube de 0 al target en `ms` ms (easing cubic-out).
function useCountUp(target, ms = 1200, start = false) {
  const [v, setV] = useState(0)
  useEffect(() => {
    if (!start) return
    let raf
    const t0 = performance.now()
    const tick = (t) => {
      const p = Math.min(1, (t - t0) / ms)
      const eased = 1 - Math.pow(1 - p, 3)
      setV(target * eased)
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, ms, start])
  return v
}

// ─── Componentes internos ────────────────────────────────────────────────────

function NavBar() {
  return (
    <header className="sticky top-0 z-30 backdrop-blur-md bg-bg-0/70 border-b border-line/40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-20 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-3 group">
          <RendiLogo size={48} />
          <span className="text-2xl font-semibold text-ink-0 tracking-tight">rendi</span>
        </Link>
        <nav className="flex items-center gap-1 sm:gap-2">
          <a href="#features" className="hidden sm:inline-flex text-xs font-mono uppercase tracking-label text-ink-3 hover:text-ink-1 px-3 py-1.5 transition-colors">
            Features
          </a>
          <a href="#live" className="hidden sm:inline-flex text-xs font-mono uppercase tracking-label text-ink-3 hover:text-ink-1 px-3 py-1.5 transition-colors">
            Live
          </a>
          <a href="#pricing" className="hidden sm:inline-flex text-xs font-mono uppercase tracking-label text-ink-3 hover:text-ink-1 px-3 py-1.5 transition-colors">
            Pricing
          </a>
          <Link to="/login" className="text-xs font-mono uppercase tracking-label text-ink-1 hover:text-ink-0 px-3 py-1.5 transition-colors">
            Login
          </Link>
          <Link
            to="/login?mode=register"
            className="text-xs font-medium bg-data-violet hover:bg-data-violet/90 text-white rounded-sm px-3 py-1.5 transition-colors inline-flex items-center gap-1.5"
          >
            Empezar gratis
            <ArrowRight size={12} strokeWidth={2} />
          </Link>
        </nav>
      </div>
    </header>
  )
}

function Hero() {
  return (
    <section className="relative overflow-hidden">
      {/* Fondo: grid + spotlight verde */}
      <div className="absolute inset-0 grid-bg pointer-events-none opacity-60" aria-hidden="true" />
      <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] rounded-full bg-data-violet/10 blur-3xl spotlight-pulse pointer-events-none" aria-hidden="true" />
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-bg-0 pointer-events-none" aria-hidden="true" />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 pt-20 sm:pt-28 pb-16 sm:pb-24 text-center">
        {/* Eyebrow — terminal prompt */}
        <div className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-label text-data-violet border border-data-violet/30 bg-data-violet/5 px-3 py-1 rounded-sm mb-8">
          <Terminal size={11} strokeWidth={2} />
          <span>rendi://portfolio_tracker</span>
          <span className="terminal-cursor text-data-violet">▍</span>
        </div>

        {/* Headline */}
        <h1 className="font-sans font-semibold tracking-tight leading-[0.95] mb-6"
            style={{ fontSize: 'clamp(36px, 7vw, 80px)', letterSpacing: '-0.035em' }}>
          <span className="block text-ink-0">Tu portfolio,</span>
          <span className="block headline-sweep">con coach IA.</span>
        </h1>

        {/* Sub */}
        <p className="max-w-2xl mx-auto text-base sm:text-lg text-ink-2 leading-relaxed mb-10">
          Preguntale por qué bajó tu P&amp;L del mes, dónde está concentrado el riesgo
          o qué activo te está costando plata. Detectores de sesgos que ningún Excel
          te marca. Multi-broker, P&amp;L real en USD.
        </p>

        {/* CTAs */}
        <div className="flex items-center justify-center gap-3 flex-wrap mb-14">
          <button
            type="button"
            onClick={() => { window.location.href = '/?demo=1' }}
            className="group inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-5 py-2.5 transition-all hover:shadow-[0_0_24px_-4px_rgba(139,125,255,0.6)]"
          >
            <Sparkles size={14} strokeWidth={2} />
            Probá la demo
            <ArrowRight size={14} strokeWidth={2} className="group-hover:translate-x-0.5 transition-transform" />
          </button>
          <Link
            to="/login?mode=register"
            className="inline-flex items-center gap-2 border border-line-3 hover:border-ink-2 hover:bg-bg-2/50 text-ink-0 font-medium rounded-sm px-5 py-2.5 transition-colors"
          >
            Empezar gratis
          </Link>
        </div>

        {/* Stats strip */}
        <StatsStrip />

        {/* Scroll hint */}
        <div className="mt-16 text-ink-3 animate-bounce">
          <ChevronDown size={20} strokeWidth={1.5} className="mx-auto" aria-hidden="true" />
        </div>
      </div>
    </section>
  )
}

function StatsStrip() {
  // Activamos counters cuando el strip entra en viewport.
  const ref = useRef(null)
  const [started, setStarted] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { setStarted(true); io.disconnect() }
    }, { threshold: 0.3 })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  const brokers = useCountUp(8, 900, started)
  const monedas = useCountUp(2, 700, started)
  const kpis    = useCountUp(40, 1200, started)
  const dias    = useCountUp(365, 1400, started)

  const items = [
    { v: brokers, label: 'brokers soportados', suffix: '+' },
    { v: monedas, label: 'monedas (USD · ARS)' },
    { v: kpis,    label: 'KPIs por mes',        suffix: '+' },
    { v: dias,    label: 'días tracked',        suffix: '/año' },
  ]

  return (
    <div ref={ref} className="grid grid-cols-2 md:grid-cols-4 max-w-3xl mx-auto border border-line rounded bg-bg-1/60 backdrop-blur-sm divide-x divide-y md:divide-y-0 divide-line/60">
      {items.map((it, i) => (
        <div key={i} className="px-4 py-4">
          <div className="font-sans font-medium tabular text-ink-0 mb-1"
               style={{ fontSize: 'clamp(20px, 2.4vw, 28px)', letterSpacing: '-0.02em' }}>
            {Math.round(it.v).toLocaleString('es-AR')}{it.suffix || ''}
          </div>
          <div className="text-[10px] font-mono uppercase tracking-label text-ink-3 leading-tight">
            {it.label}
          </div>
        </div>
      ))}
    </div>
  )
}

// Mock "live" dashboard — replica el layout real (KPI strip + cards por broker).
// Los valores son ilustrativos pero la estructura es la del Dashboard real.
function LivePreview() {
  const ref = useReveal()
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setTick(x => x + 1), 2200)
    return () => clearInterval(t)
  }, [])

  // Variación sutil determinista para "respiración"
  const wobble = (base, amp = 0.0006) => base * (1 + Math.sin(tick * 1.3 + base) * amp)
  const total = wobble(48217.42)
  const aportado = 38140
  const resultado = total - aportado
  const resultadoPct = (resultado / aportado) * 100
  const realizado = 4218

  // 3 brokers (matchea el patrón del Dashboard real)
  const brokers = [
    { name: 'Schwab',  currency: 'USD',  value: 22480, invested: 18200, pct:  +23.5 },
    { name: 'Cocos',   currency: 'ARS',  value: 14982, invested: 13100, pct:  +14.4 },
    { name: 'Binance', currency: 'USDT', value: 10755, invested:  8840, pct:  +21.7 },
  ]

  return (
    <section id="live" ref={ref} className="reveal-up relative max-w-6xl mx-auto px-4 sm:px-6 pb-24">
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-2 mb-3">
          <span className="live-dot" aria-hidden="true" />
          <span className="text-[11px] font-mono uppercase tracking-label text-rendi-pos">live preview</span>
        </div>
        <h2 className="display-heading mb-2">Sabés qué tenés, qué te aporta y qué te hace perder.</h2>
        <p className="text-sm text-ink-3 max-w-xl mx-auto">
          P&amp;L real en USD, atribución por activo y broker, comparativa contra S&amp;P e inflación.
          Identificás dónde está el riesgo y qué decisión tomar — antes de tomarla.
        </p>
      </div>

      <div className="border border-line rounded-lg bg-bg-1/80 backdrop-blur-sm overflow-hidden shadow-[0_0_60px_-20px_rgba(139,125,255,0.25)]">
        {/* Mac-style header */}
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-line/60 bg-bg-2/40">
          <div className="flex gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rendi-neg/50" />
            <span className="w-2.5 h-2.5 rounded-full bg-rendi-warn/50" />
            <span className="w-2.5 h-2.5 rounded-full bg-rendi-pos/50" />
          </div>
          <span className="ml-3 text-[11px] font-mono text-ink-3">rendi · dashboard</span>
          <span className="ml-auto text-[10px] font-mono text-ink-3">{new Date().toLocaleDateString('es-AR')}</span>
        </div>

        {/* KPI strip — 4 cells como el real */}
        <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-y md:divide-y-0 divide-line/60 border-b border-line/60">
          <KpiCell
            label="Capital total"
            value={`US$ ${total.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`}
            sub={`≈ ARS ${(total * 1415).toLocaleString('es-AR', { maximumFractionDigits: 0 })} al blue 1.415`}
          />
          <KpiCell
            label="Capital aportado"
            value={`US$ ${aportado.toLocaleString('es-AR')}`}
            sub="depósitos netos"
          />
          <KpiCell
            label="Resultado total"
            value={`+US$ ${resultado.toLocaleString('es-AR', { maximumFractionDigits: 0 })}`}
            sub={`+${resultadoPct.toFixed(1)}% desde el inicio`}
            positive
          />
          <KpiCell
            label="P&L realizado"
            value={`+US$ ${realizado.toLocaleString('es-AR')}`}
            sub="operaciones cerradas"
            positive
          />
        </div>

        {/* Cards por broker (matchea el grid del Dashboard real) */}
        <div className="px-4 py-4">
          <div className="flex items-center justify-between mb-3">
            <span className="text-[10px] font-mono uppercase tracking-label text-ink-3">Por broker</span>
            <span className="text-[10px] font-mono uppercase tracking-label text-ink-3">3 activos</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {brokers.map((b, i) => {
              const pnl = b.value - b.invested
              return (
                <div key={i} className="border border-line/60 rounded bg-bg-2/30 p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-ink-0 font-medium">{b.name}</span>
                    <span className="text-[9px] font-mono uppercase tracking-caps text-ink-3 border border-line/60 px-1.5 py-0.5 rounded-sm">
                      {b.currency}
                    </span>
                  </div>
                  <div className="font-sans text-lg font-medium tabular text-ink-0 leading-none mb-1">
                    US$ {b.value.toLocaleString('es-AR')}
                  </div>
                  <div className="text-[10px] font-mono text-ink-3">
                    Inv US$ {b.invested.toLocaleString('es-AR')} · <span className="text-rendi-pos">+US$ {pnl.toLocaleString('es-AR')} ({b.pct.toFixed(1)}%)</span>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}

function KpiCell({ label, value, sub, positive, pulse }) {
  return (
    <div className="px-4 py-3 min-w-0">
      <div className="text-[10px] font-mono uppercase tracking-label text-ink-3 mb-1.5">{label}</div>
      <div className={`data-hero leading-none truncate ${pulse ? 'value-pulse' : (positive ? 'text-rendi-pos' : 'text-ink-0')}`}>
        {value}
      </div>
      {sub && (
        <div className="text-[10px] font-mono text-ink-3 mt-1.5 truncate" title={sub}>{sub}</div>
      )}
    </div>
  )
}

function Features() {
  const ref = useReveal()
  const items = [
    {
      Icon: Layers,
      title: 'Multi-broker, una pantalla',
      body: 'Cocos, IOL, Schwab, Binance, Wise, Balanz. Importás tu CSV o cargás manual — cada operación queda en su broker, agregada en el global.',
      meta: 'PORTFOLIO · UNIFICADO',
    },
    {
      Icon: Coins,
      title: 'P&L en USD real',
      body: 'TC blue/MEP automático, conversión histórica para tus tenencias en pesos. Sin guessing — el USD del cierre es el USD que importa.',
      meta: 'FX · TC LIVE',
    },
    {
      Icon: Sparkles,
      title: 'IA que conoce tu portfolio',
      body: 'Preguntale lo que quieras: por qué bajó tu P&L del mes, dónde está concentrado el riesgo, qué activo aporta más drag, si tu allocation tiene sentido. Te responde con tus datos, no en abstracto.',
      meta: 'AI · CONVERSACIONAL',
    },
    {
      Icon: LineChart,
      title: 'Benchmarks reales',
      body: 'Compará tu rendimiento contra S&P 500 e inflación AR. En cada período: mensual, anual, acumulado. Sin trampas con bases.',
      meta: 'VS · MERCADO',
    },
    {
      Icon: Zap,
      title: 'Análisis de comportamiento',
      body: 'Detectores de overtrading, sesgo de confirmación, anchoring. Tu trading mirado desde la lente del behavioral, no del cheerleading.',
      meta: 'BEHAVIORAL · DETECT',
    },
    {
      Icon: RefreshCw,
      title: 'Sync diario',
      body: 'Snapshots automáticos del cierre. Tu serie temporal se va armando sola — no tenés que tocar nada.',
      meta: 'CRON · DAILY',
    },
  ]

  return (
    <section id="features" ref={ref} className="reveal-up relative max-w-7xl mx-auto px-4 sm:px-6 pb-24">
      <div className="text-center mb-12">
        <div className="text-[11px] font-mono uppercase tracking-label text-ink-3 mb-3">/ qué hace</div>
        <h2 className="display-heading mb-2 max-w-2xl mx-auto">
          Las decisiones se toman con datos limpios. <span className="text-ink-3">Rendi te los entrega.</span>
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((it, i) => (
          <FeatureCard key={i} {...it} delayMs={i * 80} />
        ))}
      </div>
    </section>
  )
}

function FeatureCard({ Icon, title, body, meta, delayMs }) {
  const ref = useReveal()
  return (
    <div
      ref={ref}
      className="reveal-up group relative p-5 border border-line rounded bg-bg-1/60 hover:bg-bg-2/60 hover:border-line-3 transition-all duration-300 overflow-hidden"
      style={{ animationDelay: `${delayMs}ms` }}
    >
      {/* Hover glow corner */}
      <div className="absolute -top-12 -right-12 w-32 h-32 bg-data-violet/0 group-hover:bg-data-violet/10 rounded-full blur-2xl transition-colors duration-500" aria-hidden="true" />

      <div className="relative">
        <div className="flex items-center justify-between mb-4">
          <div className="w-9 h-9 rounded bg-bg-2 border border-line flex items-center justify-center text-ink-1 group-hover:text-data-violet group-hover:border-data-violet/30 transition-colors">
            <Icon size={16} strokeWidth={1.75} />
          </div>
          <span className="text-[9px] font-mono uppercase tracking-caps text-ink-3">{meta}</span>
        </div>
        <h3 className="text-base font-semibold text-ink-0 mb-2 tracking-tight">{title}</h3>
        <p className="text-sm text-ink-2 leading-relaxed">{body}</p>
      </div>
    </div>
  )
}

function BrokerTicker() {
  // Logos como texto-mono — más sobrio que SVGs y matchea la estética terminal.
  const brokers = ['Cocos', 'IOL', 'Schwab', 'Binance', 'Wise', 'Balanz', 'BullMarket']
  const doubled = [...brokers, ...brokers] // duplico para scroll infinito
  return (
    <section className="border-y border-line/40 bg-bg-1/40 py-6 overflow-hidden">
      <div className="text-center text-[10px] font-mono uppercase tracking-label text-ink-3 mb-4">
        Compatible con los brokers que ya usás
      </div>
      <div className="relative">
        <div className="ticker-scroll flex gap-12 whitespace-nowrap">
          {doubled.map((b, i) => (
            <span key={i} className="text-base font-mono text-ink-2 hover:text-ink-0 transition-colors px-4">
              {b}
            </span>
          ))}
        </div>
        {/* Fade edges */}
        <div className="absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-bg-0 to-transparent pointer-events-none" />
        <div className="absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-bg-0 to-transparent pointer-events-none" />
      </div>
    </section>
  )
}

// ─── Pricing ─────────────────────────────────────────────────────────────────

function Pricing() {
  const ref = useReveal()
  // Tomamos las top features de cada plan — la página /planes muestra la lista
  // completa para usuarios logueados. Acá lo que importa es la lectura rápida.
  const freeTop = FREE_FEATURES.slice(0, 5)
  const plusTop = PLUS_FEATURES.slice(0, 6).map(f => typeof f === 'string' ? f : f.label)
  const proTop  = PRO_FEATURES.slice(0, 6).map(f => typeof f === 'string' ? f : f.label)

  return (
    <section id="pricing" ref={ref} className="reveal-up relative max-w-6xl mx-auto px-4 sm:px-6 pb-24">
      <div className="text-center mb-12">
        <div className="text-[11px] font-mono uppercase tracking-label text-ink-3 mb-3">/ pricing</div>
        <h2 className="display-heading mb-2">Empezá gratis. Subí cuando lo necesites.</h2>
        <p className="text-sm text-ink-3 max-w-2xl mx-auto">
          Free para empezar. Plus para sumar brokers, reportes históricos y distribución por activo.
          Pro para IA premium y features avanzadas.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-3">
        {/* Free — gris neutral */}
        <PlanCard
          variant="free"
          name="Free"
          tagline="Para empezar a entender tu portfolio"
          price="Gratis"
          priceSub="Para siempre"
          features={freeTop}
          ctaLabel="Empezar gratis"
          ctaTo="/login?mode=register"
        />

        {/* Plus — cyan distintivo */}
        <PlanCard
          variant="plus"
          name="Plus"
          tagline="Multi-broker + reportes completos"
          price={`ARS ${ARS_PLUS_MONTHLY}`}
          priceSub="/ mes"
          priceFootnote="Precio final · Plan anual con 15% off"
          features={plusTop}
          ctaLabel="Empezar con Plus"
          ctaTo="/login?mode=register"
        />

        {/* Pro — VIOLET PREMIUM con badge "Más completo" */}
        <PlanCard
          variant="pro"
          badge="Más completo"
          name="Pro"
          tagline="IA premium + brokers ilimitados"
          price={`ARS ${ARS_MONTHLY}`}
          priceSub="/ mes"
          priceFootnote="Precio final · Plan anual con 15% off"
          features={proTop}
          ctaLabel="Empezar con Pro"
          ctaTo="/login?mode=register"
        />
      </div>

      <p className="text-center text-[11px] text-ink-3 mt-6">
        ¿Querés ver el detalle completo? <Link to="/login?mode=register" className="text-ink-1 hover:text-data-violet transition-colors">Creá una cuenta</Link> y mirá la comparativa.
      </p>
    </section>
  )
}

// variant: 'free' | 'plus' | 'pro'
// Jerarquía visual: free=gris, plus=cyan distintivo, pro=violet premium (más fuerte)
function PlanCard({ name, tagline, price, priceSub, priceFootnote, features, ctaLabel, ctaTo, variant = 'free', badge }) {
  const isPlus = variant === 'plus'
  const isPro  = variant === 'pro'
  // Hover en el wrapper externo (con `group`) para que badge + card se muevan
  // juntos. Visuales del card responden via `group-hover:`.
  const wrapper = isPro
    ? 'border-2 border-data-violet/60 bg-gradient-to-br from-data-violet/[0.10] via-bg-1 to-data-violet/[0.04] shadow-[0_0_60px_-12px_rgba(139,125,255,0.45)] ring-1 ring-data-violet/20 scale-[1.02] group-hover:scale-[1.04] group-hover:shadow-[0_0_80px_-8px_rgba(139,125,255,0.65)] group-hover:border-data-violet group-hover:ring-data-violet/40'
    : isPlus
      ? 'border border-data-cyan/30 bg-bg-1/80 group-hover:border-data-cyan/60 group-hover:shadow-[0_0_40px_-12px_rgba(70,198,224,0.35)]'
      : 'border border-line bg-bg-1/60 group-hover:border-line-3 group-hover:shadow-[0_0_30px_-12px_rgba(255,255,255,0.08)]'
  const checkColor = isPro ? 'text-data-violet' : isPlus ? 'text-data-cyan' : 'text-ink-2'
  const ctaClass = isPro
    ? 'bg-data-violet hover:bg-data-violet/90 text-white hover:shadow-[0_0_32px_-4px_rgba(139,125,255,0.7)] shadow-md shadow-data-violet/30'
    : isPlus
      ? 'bg-data-cyan/10 hover:bg-data-cyan/20 text-data-cyan border border-data-cyan/40'
      : 'border border-line-3 hover:border-ink-2 hover:bg-bg-2/50 text-ink-0'
  const titleColor = isPro ? 'text-data-violet' : isPlus ? 'text-data-cyan' : 'text-ink-0'

  return (
    // Wrapper externo: NO overflow-hidden (badge tiene que poder salirse).
    // `group` + transform-on-hover → badge + card se levantan juntos.
    <div className="relative group transition-transform duration-300 ease-out hover:-translate-y-1.5">
      {/* Badge superior (fuera del card para que no lo clipee overflow-hidden) */}
      {badge && (
        <span className={`absolute -top-2.5 left-1/2 -translate-x-1/2 z-10 inline-flex items-center gap-1 px-2.5 py-0.5 rounded-sm text-[10px] font-mono uppercase tracking-caps whitespace-nowrap ${
          isPro ? 'bg-data-violet text-white shadow-sm shadow-data-violet/40' : 'bg-data-cyan/15 text-data-cyan border border-data-cyan/30'
        }`}>
          {badge}
        </span>
      )}

      <div className={`group relative p-6 rounded-lg transition-all duration-300 overflow-hidden ${wrapper}`}>
        {/* Glow corner Pro */}
        {isPro && (
          <div className="absolute -top-24 -right-24 w-56 h-56 bg-data-violet/15 rounded-full blur-3xl pointer-events-none" aria-hidden="true" />
        )}

        <div className="relative">
        <div className="flex items-baseline gap-2 mb-1">
          {isPro && <Sparkles size={14} strokeWidth={1.75} className="text-data-violet" />}
          <h3 className={`text-lg font-semibold tracking-tight ${titleColor}`}>
            {name}
          </h3>
        </div>
        <p className="text-xs text-ink-3 mb-5 leading-relaxed">{tagline}</p>

        <div className="mb-1 flex items-baseline gap-1.5">
          <span className="font-sans font-medium text-ink-0 tabular"
                style={{ fontSize: isPro ? 'clamp(32px, 4vw, 42px)' : 'clamp(28px, 3.4vw, 36px)', letterSpacing: '-0.02em' }}>
            {price}
          </span>
          {priceSub && <span className="text-xs text-ink-3">{priceSub}</span>}
        </div>
        {priceFootnote && (
          <p className="text-[10px] font-mono text-ink-3 mb-5">{priceFootnote}</p>
        )}
        {!priceFootnote && <div className="mb-5" />}

        <ul className="space-y-2.5 mb-6">
          {features.map((f, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-ink-1 leading-relaxed">
              <Check size={13} strokeWidth={2.5} className={`mt-0.5 flex-shrink-0 ${checkColor}`} />
              <span>{f}</span>
            </li>
          ))}
        </ul>

        <Link
          to={ctaTo}
          className={`block w-full text-center font-medium rounded-sm py-2.5 transition-all inline-flex items-center justify-center gap-1.5 ${ctaClass}`}
        >
          {ctaLabel}
          <ArrowRight size={13} strokeWidth={2} />
        </Link>
        </div>
      </div>
    </div>
  )
}

function CtaFinal() {
  const ref = useReveal()
  return (
    <section ref={ref} className="reveal-up relative max-w-4xl mx-auto px-4 sm:px-6 pb-24 text-center">
      <div className="relative border border-line rounded-lg bg-gradient-to-br from-bg-1 to-bg-2/60 p-10 overflow-hidden">
        <div className="absolute -top-20 left-1/2 -translate-x-1/2 w-[400px] h-[400px] rounded-full bg-data-violet/10 blur-3xl spotlight-pulse pointer-events-none" />
        <div className="relative">
          <div className="text-[11px] font-mono uppercase tracking-label text-data-violet mb-3">
            / empezá ahora
          </div>
          <h2 className="font-sans font-semibold text-ink-0 mb-3"
              style={{ fontSize: 'clamp(24px, 4vw, 40px)', letterSpacing: '-0.02em' }}>
            Tu primer reporte te espera del otro lado.
          </h2>
          <p className="text-sm text-ink-2 mb-7 max-w-md mx-auto">
            Sin tarjeta. Sin onboarding eterno. Cargás tu primera operación y ya estás viendo P&amp;L real.
          </p>
          <div className="flex items-center justify-center gap-3 flex-wrap">
            <Link
              to="/login?mode=register"
              className="inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-5 py-2.5 transition-all hover:shadow-[0_0_24px_-4px_rgba(139,125,255,0.6)]"
            >
              Crear cuenta gratis
              <ArrowRight size={14} strokeWidth={2} />
            </Link>
            <button
              type="button"
              onClick={() => { window.location.href = '/?demo=1' }}
              className="inline-flex items-center gap-2 text-sm text-ink-2 hover:text-ink-0 transition-colors"
            >
              o probá la demo →
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer className="border-t border-line/40 py-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 flex items-center justify-between flex-wrap gap-4">
        <div className="flex items-center gap-2.5">
          <RendiLogo size={32} />
          <span className="text-base font-semibold text-ink-1">rendi</span>
          <span className="text-[10px] font-mono uppercase tracking-label text-ink-3 ml-3">
            v2 · hecho en Buenos Aires
          </span>
        </div>
        <div className="flex items-center gap-5 text-[11px] font-mono uppercase tracking-label text-ink-3">
          <a
            href={whatsappUrl()}
            target="_blank"
            rel="noreferrer noopener"
            className="hover:text-[#25D366] transition-colors inline-flex items-center gap-1.5"
            title="Consultas por WhatsApp"
          >
            <WhatsAppIcon size={12} />
            Soporte
          </a>
          <Link to="/login" className="hover:text-ink-0 transition-colors">Login</Link>
          <Link to="/login?mode=register" className="hover:text-ink-0 transition-colors">Sign up</Link>
        </div>
      </div>
    </footer>
  )
}

// ─── Root ────────────────────────────────────────────────────────────────────

export default function Landing() {
  // Bloqueamos overflow horizontal por el spotlight grande del hero
  useEffect(() => {
    document.documentElement.style.scrollBehavior = 'smooth'
    return () => { document.documentElement.style.scrollBehavior = '' }
  }, [])

  return (
    <div className="min-h-screen bg-bg-0 text-ink-0 overflow-x-hidden">
      <NavBar />
      <Hero />
      <BrokerTicker />
      <LivePreview />
      <Features />
      <Pricing />
      <CtaFinal />
      <Footer />
      <SupportWhatsAppFab />
    </div>
  )
}
