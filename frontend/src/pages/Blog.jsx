// Blog — índice del blog público de Rendi.
// ════════════════════════════════════════════════════════════════════════════
// Página /blog que lista todos los artículos publicados con metadata. Cada
// post vive en pages/blog/articles/{slug}.jsx — para agregar uno nuevo,
// crear el archivo + agregar entry al array POSTS de abajo + ruta en
// App.jsx + sumar al sitemap.
//
// Estrategia editorial: contenido pillar que rankea long-tail AR. Cada
// artículo target una keyword específica que un inversor argentino
// googlearía: "FIFO CEDEARs", "P&L USD blue", "comparativa brokers AR", etc.

import { Link } from 'react-router-dom'
import { ArrowRight, Calendar } from 'lucide-react'
import RendiLogo from '../components/RendiLogo'
import PageMeta from '../components/PageMeta'

// Source of truth de los posts publicados. Mantener sincronizado con los
// archivos en pages/blog/articles/ y con sitemap.xml.
const POSTS = [
  {
    slug: 'fifo-cedears-argentina',
    title: 'Cómo funciona el FIFO en CEDEARs (criterio fiscal AR)',
    excerpt: 'Por qué AFIP exige FIFO, cómo se aplica al vender un CEDEAR, errores comunes que cuestan caro en la declaración y cómo automatizarlo sin armar Excels.',
    category: 'FIFO y AFIP',
    publishedAt: '2026-05-24',
    readTime: '8 min',
  },
  {
    slug: 'pnl-real-usd-blue-argentina',
    title: 'P&L real en USD blue: por qué tus pesos te engañan',
    excerpt: 'La diferencia entre "ganaste 50% en pesos" y "ganaste 5% en dólares". Cómo medir tu rendimiento real cuando operás en un país con inflación alta.',
    category: 'P&L y rendimiento',
    publishedAt: '2026-05-24',
    readTime: '6 min',
  },
  {
    slug: 'comparativa-brokers-argentina',
    title: 'Cocos vs IOL vs Balanz vs Bull: qué broker AR conviene en 2026',
    excerpt: 'Comparativa honesta de los 4 brokers más populares en Argentina: comisiones, catálogo, app, soporte. Cuál elegir según tu perfil.',
    category: 'Brokers AR',
    publishedAt: '2026-05-24',
    readTime: '10 min',
  },
]

export default function Blog() {
  return (
    <div className="min-h-screen bg-bg-0 text-ink-0">
      <PageMeta
        title="Blog de Rendi — Tracker de inversiones Argentina"
        description="Artículos sobre FIFO en CEDEARs, P&L en USD blue, AFIP cripto, comparativas de brokers argentinos. Contenido para inversores AR multi-broker."
        canonical="/blog"
      />

      <header className="border-b border-line">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
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

      <main className="max-w-3xl mx-auto px-6 py-12 md:py-16">
        <section className="mb-12">
          <p className="font-mono text-[11px] uppercase tracking-caps text-data-violet mb-3">Blog de Rendi</p>
          <h1 className="text-3xl md:text-4xl font-semibold tracking-tight mb-4 text-ink-0">
            Aprende a invertir mejor desde Argentina
          </h1>
          <p className="text-base text-ink-2 leading-relaxed max-w-2xl">
            Artículos sobre FIFO en CEDEARs, P&L real en USD blue, AFIP cripto,
            comparativas de brokers. Para inversores argentinos que quieren entender
            qué pasa con su plata.
          </p>
        </section>

        <section>
          <ul className="space-y-4">
            {POSTS.map((p) => (
              <li key={p.slug}>
                <Link
                  to={`/blog/${p.slug}`}
                  className="block border border-line/60 hover:border-line-3 hover:bg-bg-1/40 rounded-lg p-6 transition-colors group"
                >
                  <div className="flex items-center gap-3 text-xs text-ink-3 font-mono uppercase tracking-caps mb-3">
                    <span className="text-data-violet">{p.category}</span>
                    <span>·</span>
                    <span className="inline-flex items-center gap-1">
                      <Calendar size={11} strokeWidth={1.75} />
                      {(() => { try { const d = new Date(p.publishedAt + 'T00:00:00'); return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short', year: 'numeric' }) } catch { return p.publishedAt } })()}
                    </span>
                    <span>·</span>
                    <span>{p.readTime}</span>
                  </div>
                  <h2 className="text-xl font-semibold text-ink-0 mb-2 group-hover:text-data-violet transition-colors">
                    {p.title}
                  </h2>
                  <p className="text-sm text-ink-2 leading-relaxed mb-3">
                    {p.excerpt}
                  </p>
                  <div className="inline-flex items-center gap-1.5 text-xs text-data-violet font-medium">
                    Leer artículo
                    <ArrowRight size={12} strokeWidth={1.75} className="group-hover:translate-x-0.5 transition-transform" />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      </main>

      <footer className="border-t border-line mt-16">
        <div className="max-w-3xl mx-auto px-6 py-6 flex items-center justify-between text-xs text-ink-3">
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
