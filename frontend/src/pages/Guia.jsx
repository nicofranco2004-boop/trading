// Guia — índice del manual de Rendi. Página /guia.
// ════════════════════════════════════════════════════════════════════════════
// Hub de las 6 secciones del manual. Cada card linkea a su sub-página.
// Linkeado desde:
//   - Landing.jsx → botón "Ver guía completa" en HowItWorks
//   - Sidebar.jsx → item "Guía" en el footer (users logueados)

import { Link } from 'react-router-dom'
import {
  Rocket, Briefcase, Compass, Sparkles as SparkIcon, Bell, UserCog,
  ArrowRight, BookOpen,
} from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'

// Mantener esta lista alineada con las sub-páginas de pages/guia/ y con
// los links prev/next dentro de cada sub-página.
const SECTIONS = [
  {
    n: 1,
    to: '/guia/empezar',
    icon: Rocket,
    title: 'Empezar',
    desc: 'Crear cuenta, agregar broker, importar CSV o cargar tu primera operación manual.',
  },
  {
    n: 2,
    to: '/guia/cartera-y-operaciones',
    icon: Briefcase,
    title: 'Cartera y operaciones',
    desc: 'Posiciones, compra/venta con FIFO, bonos AR, CEDEARs, crypto y resumen mensual.',
  },
  {
    n: 3,
    to: '/guia/insights-y-reportes',
    icon: Compass,
    title: 'Insights y reportes',
    desc: 'Las 5 cards de análisis, timeline histórico, detectores de comportamiento y export CSV.',
  },
  {
    n: 4,
    to: '/guia/coach-ia',
    icon: SparkIcon,
    title: 'Coach IA',
    desc: '12 preguntas guiadas, chat libre (Pro), memoria persistente y cuotas semanales.',
  },
  {
    n: 5,
    to: '/guia/novedades',
    icon: Bell,
    title: 'Novedades',
    desc: 'Eventos del mercado, noticias filtradas por tus tickers y noticias macro generales.',
  },
  {
    n: 6,
    to: '/guia/cuenta-y-planes',
    icon: UserCog,
    title: 'Cuenta y planes',
    desc: 'Configuración, planes Free/Plus/Pro, cambio de plan, cancelación y push notifications.',
  },
]

export default function Guia() {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title="Guía completa de Rendi — Manual de uso"
        description="Cómo usar Rendi paso a paso: agregar operaciones, importar CSV, ver insights, usar el Coach IA, gestionar tu suscripción. Manual completo para inversores argentinos."
        canonical="/guia"
      />

      <header className="border-b border-line">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 hover:opacity-90">
            <RendiLogo size={28} />
            <span className="font-semibold text-base tracking-tight">rendi</span>
          </Link>
          <nav className="flex items-center gap-5 text-sm">
            <Link to="/planes" className="text-ink-2 hover:text-ink-0">Planes</Link>
            <Link to="/login" className="text-ink-2 hover:text-ink-0">Iniciar sesión</Link>
          </nav>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-12 md:py-16">

        {/* Hero */}
        <section className="mb-12 text-center">
          <div className="inline-flex items-center gap-2 mb-4 px-3 py-1 rounded-full bg-data-violet/10 border border-data-violet/30">
            <BookOpen size={14} strokeWidth={1.75} className="text-data-violet" />
            <span className="text-[12px] text-data-violet font-medium">
              Guía completa
            </span>
          </div>
          <h1 className="text-3xl md:text-5xl font-semibold tracking-tight mb-4 text-ink-0">
            Cómo usar Rendi
          </h1>
          <p className="text-base md:text-lg text-ink-2 max-w-2xl mx-auto leading-relaxed">
            Todo lo que necesitás saber para sacarle el jugo a Rendi. Desde cargar tu
            primera operación hasta usar el Coach IA con memoria. 6 secciones, lectura
            de 5-10 min cada una.
          </p>
        </section>

        {/* Grid de secciones */}
        <section>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {SECTIONS.map((s) => {
              const Icon = s.icon
              return (
                <Link
                  key={s.n}
                  to={s.to}
                  className="block border border-line/60 hover:border-data-violet/40 hover:bg-data-violet/[0.03] rounded-lg p-6 transition-colors group"
                >
                  <div className="flex items-start gap-4">
                    <div className="w-10 h-10 rounded-md bg-data-violet/10 flex items-center justify-center flex-shrink-0 group-hover:bg-data-violet/15 transition-colors">
                      <Icon size={18} strokeWidth={1.75} className="text-data-violet" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[12.5px] text-ink-2 font-medium">
                          {s.n} de {SECTIONS.length}
                        </span>
                      </div>
                      <h2 className="text-lg font-semibold text-ink-0 mb-1.5 group-hover:text-data-violet transition-colors">
                        {s.title}
                      </h2>
                      <p className="text-sm text-ink-2 leading-relaxed mb-3">
                        {s.desc}
                      </p>
                      <div className="inline-flex items-center gap-1.5 text-xs text-data-violet font-medium">
                        Leer sección
                        <ArrowRight size={12} strokeWidth={1.75} className="group-hover:translate-x-0.5 transition-transform" />
                      </div>
                    </div>
                  </div>
                </Link>
              )
            })}
          </div>
        </section>

        {/* Recursos rápidos */}
        <section className="mt-12 pt-10 border-t border-line/40">
          <h2 className="text-sm text-ink-3 mb-4 font-medium">
            Recursos rápidos
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <a
              href="/?demo=1"
              className="block border border-line/60 hover:border-line-3 rounded-sm px-4 py-3 transition-colors"
            >
              <div className="text-sm font-medium text-ink-1 mb-0.5">Probar demo</div>
              <div className="text-xs text-ink-3">Sin cuenta. Sin compromiso.</div>
            </a>
            <Link
              to="/#faq"
              className="block border border-line/60 hover:border-line-3 rounded-sm px-4 py-3 transition-colors"
            >
              <div className="text-sm font-medium text-ink-1 mb-0.5">Preguntas frecuentes</div>
              <div className="text-xs text-ink-3">Lo que más nos consultan.</div>
            </Link>
            <Link
              to="/planes"
              className="block border border-line/60 hover:border-line-3 rounded-sm px-4 py-3 transition-colors"
            >
              <div className="text-sm font-medium text-ink-1 mb-0.5">Planes y precios</div>
              <div className="text-xs text-ink-3">Free, Plus y Pro.</div>
            </Link>
          </div>
        </section>

      </main>

      <footer className="border-t border-line mt-16">
        <div className="max-w-4xl mx-auto px-6 py-6 flex items-center justify-between text-xs text-ink-3">
          <Link to="/" className="hover:text-ink-1">← Volver al inicio</Link>
          <div className="flex items-center gap-4">
            <Link to="/planes" className="hover:text-ink-1">Planes</Link>
            <Link to="/terminos" className="hover:text-ink-1">Términos</Link>
          </div>
        </div>
      </footer>
    </div>
  )
}
