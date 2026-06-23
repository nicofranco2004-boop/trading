// Landing — primera impresión para visitantes sin login.
// Estética: terminal futurista. Grid de fondo, spotlight verde, hero con
// cursor blink, mock dashboard "live", reveal on scroll en features.

import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, Sparkles, RefreshCw, LineChart, Layers, Coins,
  Zap, Terminal, ChevronDown, Check, Lock,
  Upload, ListChecks, BarChart3, Bot, MessageSquare,
  Plus, Mail, Instagram, Linkedin,
  Building2, Bitcoin, TrendingUp, Landmark, Receipt,
} from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import {
  fmtArs,
  FREE_FEATURES, PLUS_FEATURES, PRO_FEATURES,
  PLUS_PRICE_ARS_MONTHLY, PRO_PRICE_ARS_MONTHLY,
} from './Planes'
import { api } from '../utils/api'
import { whatsappUrl } from '../utils/support'
import SupportWhatsAppFab, { WhatsAppIcon } from '../components/SupportWhatsAppFab'
import FAQ from '../components/landing/FAQ'

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
          <a href="#como-funciona" className="hidden sm:inline-flex text-xs font-mono uppercase tracking-label text-ink-3 hover:text-ink-1 px-3 py-1.5 transition-colors">
            Cómo funciona
          </a>
          <a href="#pricing" className="hidden sm:inline-flex text-xs font-mono uppercase tracking-label text-ink-3 hover:text-ink-1 px-3 py-1.5 transition-colors">
            Pricing
          </a>
          <Link
            to="/login"
            className="text-xs font-medium border border-data-violet text-data-violet hover:bg-data-violet/10 rounded-sm px-4 py-1.5 transition-colors"
          >
            Login
          </Link>
          <Link
            to="/login?mode=register"
            className="text-xs font-medium border border-data-violet bg-data-violet hover:bg-data-violet/90 text-white rounded-sm px-4 py-1.5 transition-colors"
          >
            Registrarse
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
        {/* Eyebrow — para quién es (sin jerga de dev/terminal) */}
        <div className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-label text-data-violet border border-data-violet/30 bg-data-violet/5 px-3 py-1 rounded-sm mb-8">
          <span>Para inversores argentinos</span>
        </div>

        {/* Headline — H1 único de la landing. Lidera con el beneficio emocional
            (cuánto ganaste de verdad) y nombra al "enemigo": pesos vs dólares.
            La keyword "multi-broker" pasa al subtítulo para SEO. */}
        <h1 className="font-sans font-semibold tracking-tight leading-[0.95] mb-6"
            style={{ fontSize: 'clamp(36px, 7vw, 80px)', letterSpacing: '-0.035em' }}>
          <span className="block text-ink-0">Sabé cuánto ganaste de verdad.</span>
          <span className="block headline-sweep">En dólares, no en pesos.</span>
        </h1>

        {/* Sub — keyword-rich AR (Cocos, IOL, Schwab, Binance, multi-broker, Coach IA)
            pero liderando con el dolor concreto, sin jerga ("P&L"/"USD blue"). */}
        <p className="max-w-2xl mx-auto text-base sm:text-lg text-ink-2 leading-relaxed mb-10">
          Juntá Cocos, IOL, Balanz, Schwab y Binance en una sola pantalla y mirá tu
          ganancia real en dólares —no el número inflado en pesos que te muestra el
          broker. Con un Coach IA que conoce tu cartera y te dice por qué subió o bajó.
        </p>

        {/* CTAs — primario sólido = crear cuenta (objetivo); demo = secundario ghost.
            Mismo patrón que el CtaFinal del fondo de la página. */}
        <div className="flex items-center justify-center gap-3 flex-wrap mb-4">
          <Link
            to="/login?mode=register"
            className="group inline-flex items-center gap-2 bg-data-violet hover:bg-data-violet/90 text-white font-medium rounded-sm px-5 py-2.5 transition-all hover:shadow-[0_0_24px_-4px_rgba(139,125,255,0.6)]"
          >
            Crear mi cuenta gratis
            <ArrowRight size={14} strokeWidth={2} className="group-hover:translate-x-0.5 transition-transform" />
          </Link>
          <button
            type="button"
            onClick={() => { window.location.href = '/?demo=1' }}
            className="inline-flex items-center gap-2 border border-line-3 hover:border-ink-2 hover:bg-bg-2/50 text-ink-0 font-medium rounded-sm px-5 py-2.5 transition-colors"
          >
            <Sparkles size={14} strokeWidth={2} />
            Ver demo sin registrarme
          </button>
        </div>

        {/* Microcopy de confianza — neutraliza la objeción #1 (seguridad) arriba
            del fold, sin agregar una sección. */}
        <p className="flex items-center justify-center gap-1.5 text-[12px] text-ink-3 mb-14">
          <Lock size={12} strokeWidth={2} className="text-data-violet/70" />
          Gratis para siempre · Solo lectura: no pedimos las claves de tu broker
        </p>

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

  // Barra de confianza + deseo + fricción-cero — no specs internas. El '8+'
  // mantiene el count-up (es el ancla multi-broker); el resto comunica
  // seguridad ('0 claves'), el diferencial AR ('USD real') y cero fricción
  // ('Gratis · sin tarjeta').
  const items = [
    { v: brokers, label: 'brokers en una pantalla', suffix: '+' },
    { text: '0',      label: 'claves de tu broker que pedimos' },
    { text: 'USD',    label: 'tu ganancia al dólar real' },
    { text: 'Gratis', label: 'para empezar · sin tarjeta' },
  ]

  return (
    <div ref={ref} className="grid grid-cols-2 md:grid-cols-4 max-w-3xl mx-auto border border-line rounded bg-bg-1/60 backdrop-blur-sm divide-x divide-y md:divide-y-0 divide-line/60">
      {items.map((it, i) => (
        <div key={i} className="px-4 py-4">
          <div className="font-sans font-medium tabular text-ink-0 mb-1"
               style={{ fontSize: 'clamp(20px, 2.4vw, 28px)', letterSpacing: '-0.02em' }}>
            {it.text != null ? it.text : `${Math.round(it.v).toLocaleString('es-AR')}${it.suffix || ''}`}
          </div>
          <div className="text-[11px] font-mono uppercase tracking-label text-ink-2 leading-tight">
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
            <span className="text-[11px] font-mono uppercase tracking-label text-ink-2">Por broker</span>
            <span className="text-[11px] font-mono uppercase tracking-label text-ink-2">3 activos</span>
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
      <div className="text-[11px] font-mono uppercase tracking-label text-ink-2 mb-1.5">{label}</div>
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
      <div className="text-center text-[11px] font-mono uppercase tracking-label text-ink-2 mb-4">
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

// ─── How it works — guía visual del flujo del producto ──────────────────────
// 5 pasos numerados, layout alternado (desktop) / stack vertical (mobile).
// Cada paso lleva un mock visual hecho con HTML/CSS coherente con LivePreview
// (no son screenshots — escalan con cambios de producto sin re-capturar).

function HowItWorks() {
  const ref = useReveal()
  const steps = [
    {
      n: '01',
      Icon: Upload,
      meta: 'CARTERA · CSV o MANUAL',
      title: 'Cargá tu cartera',
      body: 'Importás el CSV de Cocos, Schwab, Binance o Balanz — el parser detecta el formato y mapea cada movimiento (o usá el formato genérico para otros brokers). Si preferís control total, desde Cartera tocás "Agregar posición", elegís broker y activo —acciones, CEDEARs, cripto, bonos y ONs, fondos comunes (FCI) y plazos fijos—, cantidad y precio de entrada. Los depósitos y retiros se registran desde la caja de cada broker. Cada activo queda agrupado por broker, con moneda original, valor live en USD y P&L.',
      chips: ['CSV o manual', 'Acciones · CEDEARs · Cripto · Bonos · FCI · Plazo fijo', 'Depósitos y retiros'],
      Visual: MockPositions,
    },
    {
      n: '02',
      Icon: ListChecks,
      meta: 'OPERACIONES · COMPRAS + VENTAS',
      title: 'Añadí compras y ventas para seguir tu cartera',
      body: 'Las compras se agregan desde Cartera — si ya tenés esa posición, suma al lote existente. Para vender, abrís la posición y tocás "Registrar venta": Rendi aplica FIFO automático contra los lotes más viejos (criterio FIFO requerido por AFIP), calcula el P&L USD y % real, y transfiere la operación al historial de Operaciones. Si querés anotar un trade viejo sin precios exactos, dejás los campos vacíos y completás solamente P&L USD — atajo para cuentas externas.',
      chips: ['FIFO automático', 'Venta → Operaciones', 'Atajo sin precios'],
      Visual: MockOperations,
    },
    {
      n: '03',
      Icon: BarChart3,
      meta: 'INSIGHTS · COMPORTAMIENTO',
      title: 'Mirás tus Insights',
      body: 'Allocation por geografía (US, AR, cripto, cash), win rate, drawdown real, comparativa de tu perfil declarado vs tu cartera real, concentración top 3. Datos limpios sobre cómo decidís — no sobre cuánto te divierte mirar el gráfico.',
      chips: ['Allocation', 'Drawdown', 'Perfil vs cartera'],
      Visual: MockInsights,
    },
    {
      n: '04',
      Icon: Bot,
      meta: 'IA · ANÁLISIS PROFUNDO',
      title: 'Analizás con IA cada pantalla',
      body: 'En Dashboard, Insights, Operaciones, Reportes y más — un botón "Analizar" genera un informe estructurado: qué funcionó, qué cambió, dónde hay riesgo, qué decisión podrías tomar. Usa el snapshot real de tu cartera, no respuestas en abstracto.',
      chips: ['Por pantalla', 'Estructurado', 'Con tus datos'],
      Visual: MockAnalyze,
    },
    {
      n: '05',
      Icon: MessageSquare,
      meta: 'IA · CHAT CONVERSACIONAL',
      title: 'Le preguntás lo que necesites',
      body: 'En todos los planes accedés al Coach IA con 12 preguntas guiadas (6 consultas por semana). Con Pro desbloqueás chat libre: preguntá lo que quieras — "¿cuánto realmente gané en NVDA?", "¿por qué bajó AMD esta semana?", "recordá que el AL30 lo tengo en IOL". Memoria persistente: los hechos que le aclarás los respeta entre sesiones.',
      chips: ['12 guiadas · 6/sem (Free)', 'Chat libre · 40/sem (Pro)', 'Memoria persistente'],
      Visual: MockChat,
      cta: { label: 'Ver plan Pro', to: '/planes' },
    },
  ]

  return (
    <section
      id="como-funciona"
      ref={ref}
      className="reveal-up relative max-w-7xl mx-auto px-4 sm:px-6 pb-32 pt-12"
    >
      {/* Eyebrow + headline */}
      <div className="text-center mb-16">
        <div className="text-[11px] font-mono uppercase tracking-label text-ink-3 mb-3">/ cómo funciona</div>
        <h2 className="display-heading mb-3 max-w-2xl mx-auto">
          De cargar tu cartera a entender tus decisiones, <span className="text-ink-3">en 5 pasos.</span>
        </h2>
        <p className="text-sm text-ink-3 max-w-xl mx-auto">
          Cada paso suma una capa de claridad sobre lo que ya tenés. No te pide que cambies nada — te muestra lo que el Excel no.
        </p>
      </div>

      {/* Pasos */}
      <div className="space-y-20 lg:space-y-28">
        {steps.map((s, i) => (
          <HowItWorksStep key={s.n} step={s} reversed={i % 2 === 1} delayMs={i * 60} />
        ))}
      </div>

      {/* CTA "Ver guía completa" — links a /guia para los que quieren leer el manual
          completo. Outbound link interno; mejora dwell time + SEO interno. */}
      <div className="mt-20 flex flex-col items-center gap-3">
        <p className="text-sm text-ink-3 text-center max-w-md">
          ¿Querés ver todos los detalles de cómo funciona cada parte?
        </p>
        <a
          href="/guia"
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-md bg-bg-2 border border-line text-ink-0 text-sm hover:bg-bg-3 hover:border-data-violet transition-colors"
        >
          Ver guía completa
          <span aria-hidden="true">→</span>
        </a>
      </div>
    </section>
  )
}

function HowItWorksStep({ step, reversed, delayMs }) {
  const ref = useReveal()
  const { n, Icon, meta, title, body, chips, Visual, cta } = step
  return (
    <div
      ref={ref}
      className="reveal-up grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-16 items-center"
      style={{ animationDelay: `${delayMs}ms` }}
    >
      {/* Texto */}
      <div className={reversed ? 'lg:order-2' : ''}>
        {/* Número grande + ícono */}
        <div className="flex items-center gap-4 mb-5">
          <span
            className="font-mono text-5xl sm:text-6xl font-light text-ink-3 leading-none tabular"
            style={{ letterSpacing: '-0.04em' }}
          >
            {n}
          </span>
          <div className="w-10 h-10 rounded bg-bg-2 border border-line flex items-center justify-center text-data-violet">
            <Icon size={18} strokeWidth={1.75} />
          </div>
          {/* Meta visible desde xs ahora (antes hidden sm:inline causaba que en
              mobile se perdiera la categoría del paso). Audit #3 L_meta.
              text-ink-2 (no -3) para pasar WCAG AA en text 10px sobre bg-bg-1. */}
          <span className="text-[10px] font-mono uppercase tracking-caps text-ink-2">{meta}</span>
        </div>

        <h3 className="text-2xl sm:text-3xl font-semibold text-ink-0 tracking-tight mb-4 leading-tight">
          {title}
        </h3>
        <p className="text-base text-ink-2 leading-relaxed mb-5">
          {body}
        </p>

        {/* Chips */}
        <div className="flex items-center gap-2 flex-wrap">
          {chips.map(c => (
            <span
              key={c}
              className="text-[10px] font-mono uppercase tracking-caps text-ink-2 border border-line bg-bg-1/60 px-2 py-1 rounded-sm"
            >
              {c}
            </span>
          ))}
        </div>

        {/* CTA opcional — se muestra solo si el step lo declara (Paso 5 →
            Plan Pro). El visitor que terminó de leer la propuesta tiene
            intención caliente, no pierde el momento yendo al Pricing. */}
        {cta && (
          <div className="mt-5">
            <Link
              to={cta.to}
              className="inline-flex items-center gap-1.5 text-xs font-mono uppercase tracking-caps text-data-violet hover:text-data-violet/80 border border-data-violet/40 hover:border-data-violet/70 bg-data-violet/5 hover:bg-data-violet/10 px-3 py-1.5 rounded-sm transition-colors"
            >
              {cta.label}
              <ArrowRight size={11} strokeWidth={2} />
            </Link>
          </div>
        )}
      </div>

      {/* Visual: aria-hidden porque es decorativo (no contiene info que el
          screen reader necesite leer — el texto del step ya describe todo). */}
      <div className={reversed ? 'lg:order-1' : ''} aria-hidden="true">
        <div className="relative">
          {/* Glow sutil detrás del frame */}
          <div className="absolute -inset-4 bg-data-violet/5 blur-3xl rounded-3xl pointer-events-none" />
          <Visual />
        </div>
      </div>
    </div>
  )
}

// ─── BrokerSolutions: cards a las 6 keyword landings ─────────────────────────
// Sección crítica para SEO (audit 2026-05-25 / SEO C1):
// Las 6 landings keyword (/brokers/cocos, /iol, /binance, /cedears,
// /bonos-argentinos, /afip-cripto) quedaban huérfanas sin links desde la home.
// Google las indexa por sitemap pero sin recibir link equity de la página con
// más authority del dominio (home). Esta sección lo arregla.
//
// También sirve para conversión: el visitante que viene buscando "cómo se
// usa Rendi con Cocos" entra a la home y ve un atajo directo a su caso.

function BrokerSolutions() {
  const ref = useReveal()
  const items = [
    {
      to: '/brokers/cocos',
      Icon: Building2,
      title: 'Cocos Capital',
      desc: 'Importás tu CSV o cargás manual. Cocos USD y pesos en una vista, con TC blue automático.',
      meta: 'BROKER · AR',
    },
    {
      to: '/brokers/iol',
      Icon: Building2,
      title: 'IOL Inversiones',
      desc: 'CEDEARs, bonos, ON y FCI consolidados. P&L FIFO real en USD, listo para AFIP.',
      meta: 'BROKER · AR',
    },
    {
      to: '/brokers/binance',
      Icon: Bitcoin,
      title: 'Binance / Crypto',
      desc: 'Tu cartera cripto sin pegar pantallazos. BTC, ETH, USDT y stablecoins con P&L en USD.',
      meta: 'CRYPTO · CSV',
    },
    {
      to: '/cedears',
      Icon: TrendingUp,
      title: 'CEDEARs',
      desc: 'Valor real en USD (no la ilusión en pesos). Ratio de conversión y subyacente NYSE/NASDAQ.',
      meta: 'PRODUCTO · CEDEARs',
    },
    {
      to: '/bonos-argentinos',
      Icon: Landmark,
      title: 'Bonos AR',
      desc: 'AL30, GD30, TX26 con cupones, amortizaciones y MEP automático. Capital vs renta separados.',
      meta: 'PRODUCTO · BONOS',
    },
    {
      to: '/afip-cripto',
      Icon: Receipt,
      title: 'AFIP / Cripto',
      desc: 'Export CSV con P&L FIFO en USD listo para tu contador. Cripto, acciones y CEDEARs.',
      meta: 'COMPLIANCE · ARCA',
    },
  ]

  return (
    <section
      id="para-tu-broker"
      ref={ref}
      className="reveal-up relative max-w-7xl mx-auto px-4 sm:px-6 pb-24"
    >
      {/* Eyebrow + headline */}
      <div className="text-center mb-12">
        <div className="text-[11px] font-mono uppercase tracking-label text-ink-3 mb-3">
          / para tu broker
        </div>
        <h2 className="display-heading mb-3 max-w-2xl mx-auto">
          Soluciones específicas para tu cartera AR.{' '}
          <span className="text-ink-3">Sea Cocos, IOL, Binance o todos juntos.</span>
        </h2>
        <p className="text-sm text-ink-3 max-w-xl mx-auto">
          Cada caso de uso tiene su guía: qué importar, cómo se ve el P&amp;L, qué cuidar para AFIP.
        </p>
      </div>

      {/* Grid 3-col en desktop, 2-col tablet, 1-col mobile */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map((it, i) => (
          <BrokerSolutionCard key={it.to} {...it} delayMs={i * 70} />
        ))}
      </div>
    </section>
  )
}

function BrokerSolutionCard({ to, Icon, title, desc, meta, delayMs }) {
  const ref = useReveal()
  return (
    <Link
      to={to}
      ref={ref}
      className="reveal-up group relative p-5 border border-line rounded bg-bg-1/60 hover:bg-bg-2/60 hover:border-line-3 transition-all duration-300 overflow-hidden block"
      style={{ animationDelay: `${delayMs}ms` }}
    >
      {/* Hover glow corner */}
      <div
        className="absolute -top-12 -right-12 w-32 h-32 bg-data-violet/0 group-hover:bg-data-violet/10 rounded-full blur-2xl transition-colors duration-500"
        aria-hidden="true"
      />

      <div className="relative">
        <div className="flex items-center justify-between mb-4">
          <div className="w-9 h-9 rounded bg-bg-2 border border-line flex items-center justify-center text-ink-1 group-hover:text-data-violet group-hover:border-data-violet/30 transition-colors">
            <Icon size={16} strokeWidth={1.75} />
          </div>
          <span className="text-[9px] font-mono uppercase tracking-caps text-ink-3">{meta}</span>
        </div>
        <h3 className="text-base font-semibold text-ink-0 mb-2 tracking-tight">{title}</h3>
        <p className="text-sm text-ink-2 leading-relaxed mb-3">{desc}</p>
        {/* Arrow indicator que aparece al hover — sugiere que es link */}
        <div className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 group-hover:text-data-violet transition-colors">
          Ver guía
          <ArrowRight size={12} strokeWidth={2} className="transition-transform group-hover:translate-x-0.5" />
        </div>
      </div>
    </Link>
  )
}

// ─── Mocks visuales de cada paso ────────────────────────────────────────────
// Todos siguen la misma estética: border-line, bg-bg-1, header mono.
// Mantenidos chicos: el mensaje es "así se ve", no "esto es real".

function MockFrame({ title, children, footer }) {
  return (
    <div className="relative border border-line rounded-lg bg-bg-1/80 backdrop-blur-sm overflow-hidden shadow-[0_20px_60px_-30px_rgba(139,125,255,0.4)]">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-line/60 bg-bg-2/40">
        <div className="flex gap-1.5">
          <span className="w-2 h-2 rounded-full bg-rendi-neg/40" />
          <span className="w-2 h-2 rounded-full bg-rendi-warn/40" />
          <span className="w-2 h-2 rounded-full bg-rendi-pos/40" />
        </div>
        <span className="ml-2 text-[10px] font-mono text-ink-3">{title}</span>
      </div>
      <div className="p-4">{children}</div>
      {footer && (
        <div className="px-3 py-2 border-t border-line/60 bg-bg-2/30 text-[10px] font-mono text-ink-3">
          {footer}
        </div>
      )}
    </div>
  )
}

function MockPositions() {
  // Cartera agrupada por broker — matchea el patrón visual del /cartera real.
  // Cada broker es un mini-card con su moneda + valor total. Adentro, 2-3
  // posiciones representativas con qty + valor USD live + P&L %.
  const brokers = [
    {
      name: 'Schwab',
      currency: 'USD',
      total: 'US$ 22.480',
      positions: [
        // hasSellBtn: NVDA muestra el botón "Registrar venta" — el mismo
        // label que usa Positions.jsx en producto. Conecta visualmente: el
        // visitante ve la acción exacta que va a encontrar al loguearse.
        { asset: 'NVDA', qty: '14', value: 'US$ 7.812', pnlPct: '+38.4%', pos: true, hasSellBtn: true },
        { asset: 'AAPL', qty: '32', value: 'US$ 6.420', pnlPct: '+12.1%', pos: true },
      ],
    },
    {
      name: 'Cocos',
      currency: 'ARS',
      total: 'US$ 14.982',
      positions: [
        { asset: 'AL30', qty: '8.500', value: 'US$ 6.120', pnlPct: '+7.2%', pos: true },
        { asset: 'GGAL', qty: '1.200', value: 'US$ 4.860', pnlPct: '+18.5%', pos: true },
        // Cash: saldo de caja editable — la forma de registrar depósitos.
        // editable=true muestra chip "+ depósito" que refleja el modal real de cash flow.
        { asset: 'Caja', qty: 'ARS', value: 'US$ 4.002', pnlPct: '+ depósito', pos: true, isCash: true, editable: true },
      ],
    },
    {
      name: 'Binance',
      currency: 'USDT',
      total: 'US$ 10.755',
      positions: [
        { asset: 'BTC', qty: '0.12', value: 'US$ 8.220', pnlPct: '+24.0%', pos: true },
        { asset: 'ETH', qty: '0.9', value: 'US$ 2.535', pnlPct: '−3.4%', pos: false },
      ],
    },
  ]
  return (
    <MockFrame title="rendi · cartera" footer="3 brokers · 7 ítems · US$ 48.217 · incluye caja editable">
      <div className="space-y-3">
        {brokers.map((b, bIdx) => (
          <div key={b.name} className="border border-line/60 rounded bg-bg-2/20 overflow-hidden">
            {/* Header del broker */}
            <div className="flex items-center justify-between px-2.5 py-1.5 border-b border-line/60 bg-bg-2/40">
              <div className="flex items-center gap-2">
                <span className="text-xs text-ink-0 font-medium">{b.name}</span>
                <span className="text-[9px] font-mono uppercase tracking-caps text-ink-3 border border-line/60 px-1.5 py-0.5 rounded-sm">
                  {b.currency}
                </span>
                {/* Botón "+ Posición" solo en el primer broker para no saturar.
                    El visitante ve UNA vez de dónde sale la acción de agregar. */}
                {bIdx === 0 && (
                  <span className="text-[9px] font-mono uppercase tracking-caps text-data-violet border border-data-violet/30 bg-data-violet/5 px-1.5 py-0.5 rounded-sm inline-flex items-center gap-0.5">
                    <Plus size={8} strokeWidth={2.5} />
                    posición
                  </span>
                )}
              </div>
              <span className="text-[11px] font-mono tabular text-ink-1">{b.total}</span>
            </div>
            {/* Posiciones del broker */}
            <div className="px-2.5 py-1">
              {b.positions.map(p => (
                <div
                  key={p.asset}
                  className={`flex items-center gap-2 py-1 text-[11px] font-mono ${
                    p.isCash ? 'opacity-90' : ''
                  }`}
                >
                  <span className={`font-medium w-[52px] shrink-0 ${p.isCash ? 'text-ink-2 italic' : 'text-ink-0'}`}>{p.asset}</span>
                  <span className="text-ink-3 tabular w-[44px] shrink-0">{p.qty}</span>
                  <span className="text-ink-2 tabular flex-1 min-w-0 truncate">{p.value}</span>
                  {/* Acción contextual: "Registrar venta" para NVDA, chip
                      "+ depósito" para Caja. Visible siempre — no es interactivo
                      en el mock pero comunica el flujo real. Solo visible sm+
                      para que en mobile <360px no haya overflow del row. */}
                  {p.hasSellBtn && (
                    <span className="hidden sm:inline text-[9px] font-mono uppercase tracking-caps text-rendi-neg border border-rendi-neg/30 bg-rendi-neg/5 px-1.5 py-0.5 rounded-sm whitespace-nowrap shrink-0">
                      Registrar venta
                    </span>
                  )}
                  {p.editable && (
                    <span className="hidden sm:inline text-[9px] font-mono uppercase tracking-caps text-data-cyan border border-data-cyan/30 bg-data-cyan/5 px-1.5 py-0.5 rounded-sm whitespace-nowrap shrink-0" title="Depositá o retirá efectivo">
                      + depósito
                    </span>
                  )}
                  <span className={`text-right tabular font-medium w-[64px] shrink-0 ${
                    p.isCash
                      ? 'text-data-cyan text-[10px]'
                      : (p.pos ? 'text-rendi-pos' : 'text-rendi-neg')
                  }`}>
                    {p.pnlPct}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </MockFrame>
  )
}

function MockOperations() {
  // 5 rows que muestren la mezcla real: compras (sin P&L — apenas suman a la
  // cartera), ventas con FIFO (P&L automático contra lote más viejo) y
  // dividendos. Tag pill por tipo para que se distinga visualmente.
  const rows = [
    { date: '2024-11-15', asset: 'NVDA', type: 'venta',   pnl: '+US$320', pnlClass: 'text-rendi-pos', typeClass: 'text-data-violet border-data-violet/30 bg-data-violet/5' },
    { date: '2024-10-30', asset: 'NVDA', type: 'compra',  pnl: '—',       pnlClass: 'text-ink-3',     typeClass: 'text-data-cyan border-data-cyan/30 bg-data-cyan/5' },
    { date: '2024-10-22', asset: 'AMD',  type: 'venta',   pnl: '+US$210', pnlClass: 'text-rendi-pos', typeClass: 'text-data-violet border-data-violet/30 bg-data-violet/5' },
    { date: '2024-09-08', asset: 'INTC', type: 'venta',   pnl: '−US$180', pnlClass: 'text-rendi-neg', typeClass: 'text-data-violet border-data-violet/30 bg-data-violet/5' },
    { date: '2024-08-30', asset: 'AAPL', type: 'dividendo', pnl: '+US$45', pnlClass: 'text-rendi-pos', typeClass: 'text-data-amber border-data-amber/30 bg-data-amber/5' },
  ]
  return (
    <MockFrame title="rendi · operaciones" footer="Auto-generadas desde Cartera al ‘Registrar venta’ · FIFO + P&L USD">
      <div className="space-y-1">
        <div className="grid grid-cols-[80px_60px_1fr_80px] gap-2 pb-2 border-b border-line/60 text-[9px] font-mono uppercase tracking-caps text-ink-3">
          <span>Fecha</span>
          <span>Activo</span>
          <span>Tipo</span>
          <span className="text-right">P&L</span>
        </div>
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[80px_60px_1fr_80px] gap-2 py-1.5 text-[11px] font-mono items-center">
            <span className="text-ink-3 tabular">{r.date}</span>
            <span className="text-ink-0 font-medium">{r.asset}</span>
            <span className={`text-[9px] uppercase tracking-caps border px-1.5 py-0.5 rounded-sm inline-flex w-fit ${r.typeClass}`}>
              {r.type}
            </span>
            <span className={`${r.pnlClass} text-right tabular font-medium`}>{r.pnl}</span>
          </div>
        ))}
      </div>
    </MockFrame>
  )
}

function MockInsights() {
  const cards = [
    { label: 'Allocation US', value: '62%', sub: 'meta 55%', neutral: true },
    { label: 'Win rate', value: '68%', sub: '34 trades', pos: true },
    { label: 'Drawdown máx', value: '−14.2%', sub: 'jul-24', neg: true },
    { label: 'Concentración top 3', value: '41%', sub: 'NVDA · BTC · AL30', neutral: true },
  ]
  return (
    <MockFrame title="rendi · insights" footer="actualizado: hoy 09:42">
      <div className="grid grid-cols-2 gap-2">
        {cards.map(c => (
          <div key={c.label} className="border border-line/60 rounded bg-bg-2/30 p-2.5">
            <div className="text-[9px] font-mono uppercase tracking-label text-ink-3 mb-1.5">{c.label}</div>
            <div className={`text-lg font-semibold leading-none mb-1 tabular ${c.pos ? 'text-rendi-pos' : c.neg ? 'text-rendi-neg' : 'text-ink-0'}`}>
              {c.value}
            </div>
            <div className="text-[10px] font-mono text-ink-3 truncate">{c.sub}</div>
          </div>
        ))}
      </div>
    </MockFrame>
  )
}

function MockAnalyze() {
  return (
    <MockFrame title="rendi · análisis con IA" footer="generado en 4.2s · Pro">
      <div className="space-y-3">
        {/* Header */}
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-data-violet/20 border border-data-violet/40 flex items-center justify-center text-data-violet">
            <Sparkles size={11} strokeWidth={2} />
          </div>
          <span className="text-xs font-medium text-ink-0">Análisis de Insights</span>
          <span className="ml-auto text-[9px] font-mono uppercase tracking-caps text-ink-3">DRAWER</span>
        </div>

        {/* TLDR */}
        <div className="border-l-2 border-data-violet pl-3 py-1">
          <div className="text-[9px] font-mono uppercase tracking-label text-data-violet mb-1">TL;DR</div>
          <p className="text-[11px] text-ink-1 leading-snug">
            Tu cartera está sobre-expuesta a US tech (62% vs meta 55%). El win rate es alto pero proviene mayormente de NVDA — sin ella, el realizado sería negativo.
          </p>
        </div>

        {/* Secciones */}
        <div className="space-y-2">
          <div className="border border-line/60 rounded p-2 bg-bg-2/20">
            <div className="text-[10px] font-mono uppercase tracking-caps text-rendi-pos mb-1">✓ Funcionando</div>
            <p className="text-[11px] text-ink-2 leading-snug">Disciplina de toma de ganancia en NVDA — saliste 3 veces en máximos relativos.</p>
          </div>
          <div className="border border-line/60 rounded p-2 bg-bg-2/20">
            <div className="text-[10px] font-mono uppercase tracking-caps text-rendi-warn mb-1">⚠ Riesgo</div>
            <p className="text-[11px] text-ink-2 leading-snug">Top 3 concentrado 41% — un drawdown del 20% en una sola posición arrastra ~8% del total.</p>
          </div>
        </div>
      </div>
    </MockFrame>
  )
}

function MockChat() {
  return (
    <MockFrame title="rendi · coach IA · chat" footer="memoria activa · 12 hechos guardados">
      <div className="space-y-3">
        {/* User msg */}
        <div className="flex justify-end">
          <div className="max-w-[85%] bg-data-violet/10 border border-data-violet/30 rounded-lg px-3 py-2">
            <p className="text-[12px] text-ink-0 leading-snug">¿Cuánto realmente gané en NVDA?</p>
          </div>
        </div>

        {/* Bot msg */}
        <div className="flex justify-start">
          <div className="max-w-[90%] bg-bg-2/40 border border-line/60 rounded-lg px-3 py-2">
            <div className="flex items-center gap-1.5 mb-1.5">
              <div className="w-4 h-4 rounded bg-data-violet/20 border border-data-violet/40 flex items-center justify-center text-data-violet">
                <Sparkles size={8} strokeWidth={2.5} />
              </div>
              <span className="text-[9px] font-mono uppercase tracking-caps text-ink-3">coach IA</span>
            </div>
            <p className="text-[12px] text-ink-1 leading-snug">
              <span className="text-rendi-pos font-medium">+US$ 1.840 realizado</span> sobre 3 ventas (NVDA en 480, 510 y 545). Tu posición abierta tiene <span className="text-rendi-pos font-medium">+US$ 920 sin realizar</span> a precio de hoy.
            </p>
          </div>
        </div>

        {/* User msg corta */}
        <div className="flex justify-end">
          <div className="max-w-[80%] bg-data-violet/10 border border-data-violet/30 rounded-lg px-3 py-2">
            <p className="text-[12px] text-ink-0 leading-snug">recordá que el AL30 lo tengo en IOL</p>
          </div>
        </div>

        {/* Bot confirma memoria */}
        <div className="flex justify-start">
          <div className="max-w-[75%] bg-bg-2/40 border border-line/60 rounded-lg px-3 py-2 flex items-center gap-2">
            <Check size={12} strokeWidth={2.5} className="text-rendi-pos shrink-0" />
            <p className="text-[12px] text-ink-2 leading-snug">Guardado. Lo voy a usar en futuras respuestas.</p>
          </div>
        </div>
      </div>
    </MockFrame>
  )
}

// ─── Pricing ─────────────────────────────────────────────────────────────────
// Mismo template que /planes (3 secciones: cuotas + esenciales + diff/roadmap).
// Importamos los datasets desde Planes.jsx para mantener fuente única — si
// cambia una feature ahí, se refleja acá automáticamente.

function Pricing() {
  const ref = useReveal()
  // Pricing ARS hardcoded (2026-05-31): cobramos pesos fijos, sin conversión
  // al blue. Ver Planes.jsx para constants + razones operativas (Rebill cobra
  // USD 500/mes mínimo si facturás en USD).
  return (
    <section id="pricing" ref={ref} className="reveal-up relative max-w-6xl mx-auto px-4 sm:px-6 pb-24">
      <div className="text-center mb-12">
        <div className="text-[11px] font-mono uppercase tracking-label text-ink-3 mb-3">/ pricing</div>
        <h2 className="display-heading mb-2">Empezá gratis. Subí cuando lo necesites.</h2>
        <p className="text-sm text-ink-3 max-w-2xl mx-auto">
          Pago mensual en pesos, sin sorpresas. Free para empezar. Plus para sumar brokers, reportes históricos y export.
          Pro para IA premium y features avanzadas.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-3">
        {/* Free — gris neutral */}
        <PlanCard
          variant="free"
          name="Free"
          tagline="Para empezar a entender tu cartera"
          price="Gratis"
          priceSub="Para siempre"
          features={FREE_FEATURES}
          ctaLabel="Empezar gratis"
          ctaTo="/login?mode=register"
        />

        {/* Plus — cyan distintivo. Pricing fijo en pesos. */}
        <PlanCard
          variant="plus"
          name="Plus"
          tagline="Multi-broker + reportes completos"
          price={`$${fmtArs(PLUS_PRICE_ARS_MONTHLY)}`}
          priceSub="/ mes"
          priceFootnote="Sin sorpresas. Pago mensual en pesos."
          features={PLUS_FEATURES}
          ctaLabel="Empezar con Plus"
          ctaTo="/login?mode=register"
        />

        {/* Pro — VIOLET PREMIUM con badge "Más completo" */}
        <PlanCard
          variant="pro"
          badge="Más completo"
          name="Pro"
          tagline="IA premium + brokers ilimitados"
          price={`$${fmtArs(PRO_PRICE_ARS_MONTHLY)}`}
          priceSub="/ mes"
          priceFootnote="Sin sorpresas. Pago mensual en pesos."
          features={PRO_FEATURES}
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
// Features acepta DOS shapes (back-compat + nueva estructura):
//   - Array de strings — render simple legacy
//   - { essentials, diff?, quotas, roadmap? } — template 3-secciones nuevo
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
  const accent = isPro ? 'data-violet' : isPlus ? 'data-cyan' : 'rendi-pos'
  const checkColor = `text-${accent}`
  const ctaClass = isPro
    ? 'bg-data-violet hover:bg-data-violet/90 text-white hover:shadow-[0_0_32px_-4px_rgba(139,125,255,0.7)] shadow-md shadow-data-violet/30'
    : isPlus
      ? 'bg-data-cyan/10 hover:bg-data-cyan/20 text-data-cyan border border-data-cyan/40'
      : 'border border-line-3 hover:border-ink-2 hover:bg-bg-2/50 text-ink-0'
  const titleColor = isPro ? 'text-data-violet' : isPlus ? 'text-data-cyan' : 'text-ink-0'
  const isLegacy = Array.isArray(features)

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

        {/* CTA antes de las features → conversión: el botón siempre por
            encima del fold sin importar largo de la lista. */}
        <Link
          to={ctaTo}
          className={`block w-full text-center font-medium rounded-sm py-2.5 mb-6 transition-all inline-flex items-center justify-center gap-1.5 ${ctaClass}`}
        >
          {ctaLabel}
          <ArrowRight size={13} strokeWidth={2} />
        </Link>

        {/* Features — shape detectada */}
        {isLegacy ? (
          <ul className="space-y-2.5">
            {features.map((f, i) => {
              const label = typeof f === 'string' ? f : f.label
              return (
                <li key={i} className="flex items-start gap-2 text-xs text-ink-1 leading-relaxed">
                  <Check size={13} strokeWidth={2.5} className={`mt-0.5 flex-shrink-0 ${checkColor}`} />
                  <span>{label}</span>
                </li>
              )
            })}
          </ul>
        ) : (
          <div className="space-y-5">
            {/* Cuotas — grid mini ARRIBA para escaneo rápido */}
            {features.quotas && features.quotas.length > 0 && (
              <div>
                <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">Cuotas semanales</div>
                <div className="grid grid-cols-3 gap-1.5">
                  {features.quotas.map((q, i) => (
                    <div key={i} className="border border-line/60 rounded bg-bg-2/30 px-2 py-1.5 text-center">
                      <div className={`text-base font-bold tabular leading-none mb-0.5 ${checkColor}`}>
                        {q.value}
                      </div>
                      <div className="text-[8px] font-mono uppercase tracking-caps text-ink-3 leading-tight">
                        {q.label}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Esenciales */}
            {features.essentials && features.essentials.length > 0 && (
              <div>
                <div className="text-[11px] font-mono uppercase tracking-caps text-ink-2 mb-2">Lo que incluye</div>
                <ul className="space-y-2">
                  {features.essentials.slice(0, 6).map((f, i) => {
                    const isObj = typeof f === 'object'
                    const label = isObj ? f.label : f
                    return (
                      <li key={i} className="flex items-start gap-2 text-xs text-ink-1 leading-relaxed">
                        <Check size={12} strokeWidth={2.5} className={`mt-0.5 flex-shrink-0 ${checkColor}`} />
                        <span>{label}</span>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}

            {/* Diff — el AHA del upgrade */}
            {features.diff && (
              <div>
                <div className={`text-[10px] font-mono uppercase tracking-caps mb-2 ${checkColor}`}>
                  {features.diff.title}
                </div>
                <ul className="space-y-1.5">
                  {features.diff.items.map((t, i) => (
                    <li key={i} className="flex items-start gap-2 text-xs text-ink-2 leading-relaxed">
                      <Check size={12} strokeWidth={2.5} className={`mt-0.5 flex-shrink-0 ${checkColor}`} />
                      <span>{t}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        </div>
      </div>
    </div>
  )
}

// Prueba social + build-in-public. Neutraliza dos objeciones del tráfico frío
// justo antes del cierre: "¿quién está atrás?" (fundador con cara y nombre) y
// "¿lo usa alguien?" (count real de inversores verificados, vía /api/stats/public).
// La foto vive en /founder.jpg (public/); si no está, cae a las iniciales "NP".
function FounderBlock() {
  const ref = useReveal()
  const [users, setUsers] = useState(null)
  // Pre-cargamos la foto con new Image() y solo la mostramos si decodifica como
  // imagen real (naturalWidth > 0). Si /founder.jpg no existe, el SPA fallback
  // devuelve index.html (HTML con 200) que NO decodifica → quedan las iniciales,
  // nunca una imagen rota. (El onError de <img> con un 200-text/html es poco
  // confiable, por eso probamos antes de renderizar.)
  const [photoOk, setPhotoOk] = useState(false)

  useEffect(() => {
    let alive = true
    fetch('/api/stats/public')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (alive && d && typeof d.users === 'number') setUsers(d.users) })
      .catch(() => {})

    const probe = new Image()
    probe.onload = () => { if (alive && probe.naturalWidth > 0) setPhotoOk(true) }
    probe.onerror = () => {}
    probe.src = '/founder.jpg'

    return () => { alive = false }
  }, [])

  // Fallback conservador (≥40) si el fetch falla — nunca queda vacío ni infla.
  const count = users != null ? users : 40

  return (
    <section ref={ref} className="reveal-up max-w-3xl mx-auto px-4 sm:px-6 py-16 md:py-20">
      <div className="flex flex-col sm:flex-row items-center gap-6 text-center sm:text-left border border-line rounded-lg bg-bg-1/60 backdrop-blur-sm p-6 sm:p-8">
        {photoOk ? (
          <img
            src="/founder.jpg"
            alt="Nicolás Pussetto, fundador de Rendi"
            loading="lazy"
            className="w-20 h-20 rounded-full object-cover border border-line-2 flex-shrink-0"
          />
        ) : (
          <div className="w-20 h-20 rounded-full bg-data-violet/15 border border-data-violet/30 text-data-violet font-semibold text-xl flex items-center justify-center flex-shrink-0">
            NP
          </div>
        )}
        <div className="min-w-0">
          <p className="text-sm sm:text-base text-ink-1 leading-relaxed mb-4">
            “Soy inversor argentino, como vos. Hice Rendi porque estaba cansado de no
            saber, en dólares de verdad, cuánto ganaba con la plata repartida entre
            Cocos, IOL y Binance. Lo construyo a la vista de todos —sumate.”
          </p>
          <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-5">
            <div>
              <p className="text-sm font-medium text-ink-0">Nicolás Pussetto</p>
              <p className="text-[11px] font-mono uppercase tracking-label text-ink-2">
                Fundador de Rendi
              </p>
            </div>
            <div className="inline-flex items-center gap-2 text-xs text-ink-2 sm:ml-auto">
              <span className="relative flex h-2 w-2 flex-shrink-0" aria-hidden="true">
                <span className="absolute inline-flex h-full w-full rounded-full bg-rendi-pos/60 animate-ping" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-rendi-pos" />
              </span>
              <span>
                <span className="text-ink-0 font-semibold tabular">{count}</span>{' '}
                inversores ya consolidan su cartera en Rendi
              </span>
            </div>
          </div>
        </div>
      </div>
    </section>
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

// ─── Footer ──────────────────────────────────────────────────────────────────
// Estructura: 4 columnas (Producto, Cuenta, Legal, Contacto) en desktop;
// stack en mobile. Brand block aparte arriba a la izquierda. Línea final con
// año dinámico, "hecho en Argentina" y dominio.
//
// Hrefs sociales: WhatsApp y Mail apuntan a destinos reales (whatsappUrl()
// y mailto: a hola@rendi.finance). Instagram/LinkedIn/X tienen placeholders
// que el equipo de Rendi va a reemplazar cuando tenga las cuentas oficiales.
// Por ahora son links visualmente válidos pero apuntan a las pages "que
// faltan" — actualizar SOCIAL_LINKS abajo cuando los URLs estén.

const SUPPORT_EMAIL = 'hola@rendi.finance'

const SOCIAL_LINKS = {
  instagram: 'https://www.instagram.com/rendifinance/',
  // LinkedIn: perfil del fundador (build-in-public). Instagram ya es real.
  // X se quitó: la cuenta oficial todavía no existe y un ícono que lleva a una
  // cuenta inexistente destruye confianza. Re-agregar cuando esté creada.
  linkedin:  'https://www.linkedin.com/in/nicolas-pussetto-6a656a1a8/',
}

function Footer() {
  const year = new Date().getFullYear()
  return (
    <footer className="border-t border-line/40 mt-8">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-12">

        {/* Top: brand + tagline + columnas ───────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 md:gap-10 mb-10">

          {/* Brand block (md: 4 cols / lg: 4 cols) */}
          <div className="md:col-span-4">
            <div className="flex items-center gap-2.5 mb-3">
              <RendiLogo size={32} />
              <span className="text-base font-semibold text-ink-1">rendi</span>
            </div>
            <p className="text-xs text-ink-2 leading-relaxed max-w-xs">
              Tracker multi-broker para Argentina. P&amp;L real en USD, FIFO
              automático, Coach IA con memoria.
            </p>
            <p className="text-[11px] font-mono uppercase tracking-label text-ink-2 mt-4">
              Hecho en Argentina
            </p>
            <p className="text-xs text-ink-2 leading-relaxed mt-2">
              Construido por{' '}
              <a
                href={SOCIAL_LINKS.linkedin}
                target="_blank"
                rel="noreferrer noopener"
                className="text-ink-1 hover:text-data-violet underline underline-offset-2 transition-colors"
              >
                Nicolás Pussetto
              </a>, inversor argentino.
            </p>
          </div>

          {/* Producto */}
          <div className="md:col-span-2">
            <h3 className="text-[11px] font-mono uppercase tracking-label text-ink-2 mb-3">
              Producto
            </h3>
            <ul className="space-y-2 text-sm">
              <li><Link to="/planes" className="text-ink-1 hover:text-ink-0 transition-colors">Planes y precios</Link></li>
              <li><a href="#como-funciona" className="text-ink-1 hover:text-ink-0 transition-colors">Cómo funciona</a></li>
              <li><Link to="/guia" className="text-ink-1 hover:text-ink-0 transition-colors">Guía completa</Link></li>
              <li><a href="#faq" className="text-ink-1 hover:text-ink-0 transition-colors">Preguntas frecuentes</a></li>
              <li><Link to="/blog" className="text-ink-1 hover:text-ink-0 transition-colors">Blog</Link></li>
            </ul>
          </div>

          {/* Cuenta */}
          <div className="md:col-span-2">
            <h3 className="text-[11px] font-mono uppercase tracking-label text-ink-2 mb-3">
              Cuenta
            </h3>
            <ul className="space-y-2 text-sm">
              <li><Link to="/login?mode=register" className="text-ink-1 hover:text-ink-0 transition-colors">Crear cuenta gratis</Link></li>
              <li><Link to="/login" className="text-ink-1 hover:text-ink-0 transition-colors">Iniciar sesión</Link></li>
              <li>
                <button
                  type="button"
                  onClick={() => { window.location.href = '/?demo=1' }}
                  className="text-ink-1 hover:text-ink-0 transition-colors text-left"
                >
                  Probar demo
                </button>
              </li>
            </ul>
          </div>

          {/* Legal */}
          <div className="md:col-span-2">
            <h3 className="text-[11px] font-mono uppercase tracking-label text-ink-2 mb-3">
              Legal
            </h3>
            <ul className="space-y-2 text-sm">
              <li><Link to="/terminos" className="text-ink-1 hover:text-ink-0 transition-colors">Términos y condiciones</Link></li>
              <li><Link to="/reembolso" className="text-ink-1 hover:text-ink-0 transition-colors">Política de reembolso</Link></li>
              <li><Link to="/privacidad" className="text-ink-1 hover:text-ink-0 transition-colors">Privacidad</Link></li>
            </ul>
          </div>

          {/* Contacto */}
          <div className="md:col-span-2">
            <h3 className="text-[11px] font-mono uppercase tracking-label text-ink-2 mb-3">
              Contacto
            </h3>
            <ul className="space-y-2 text-sm">
              <li>
                <a
                  href={`mailto:${SUPPORT_EMAIL}`}
                  className="inline-flex items-center gap-2 text-ink-1 hover:text-ink-0 transition-colors"
                  title="Escribinos por mail"
                >
                  <Mail size={13} strokeWidth={1.75} />
                  <span className="text-xs">{SUPPORT_EMAIL}</span>
                </a>
              </li>
              <li>
                <a
                  href={whatsappUrl()}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-center gap-2 text-ink-1 hover:text-[#25D366] transition-colors"
                  title="WhatsApp"
                >
                  <WhatsAppIcon size={13} />
                  <span className="text-xs">WhatsApp</span>
                </a>
              </li>
            </ul>

            {/* Redes sociales — solo iconos en fila */}
            <div className="flex items-center gap-3 mt-4">
              <a
                href={SOCIAL_LINKS.instagram}
                target="_blank"
                rel="noreferrer noopener"
                className="text-ink-3 hover:text-ink-0 transition-colors"
                title="Rendi en Instagram"
                aria-label="Instagram"
              >
                <Instagram size={16} strokeWidth={1.75} />
              </a>
              <a
                href={SOCIAL_LINKS.linkedin}
                target="_blank"
                rel="noreferrer noopener"
                className="text-ink-3 hover:text-ink-0 transition-colors"
                title="Nicolás Pussetto (fundador de Rendi) en LinkedIn"
                aria-label="LinkedIn"
              >
                <Linkedin size={16} strokeWidth={1.75} />
              </a>
            </div>
          </div>

        </div>

        {/* Bottom bar: copyright + meta ─────────────────────────── */}
        <div className="pt-6 border-t border-line/40 flex items-center justify-between flex-wrap gap-3 text-[11px] font-mono uppercase tracking-label text-ink-2">
          <span>© {year} Rendi · rendi.finance</span>
          <span>Versión 2.0</span>
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
      <HowItWorks />
      <BrokerSolutions />
      <Pricing />
      <FAQ />
      <FounderBlock />
      <CtaFinal />
      <Footer />
      <SupportWhatsAppFab />
    </div>
  )
}
